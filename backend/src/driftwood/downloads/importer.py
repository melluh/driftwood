"""
Moves a finished torrent's video (and its subtitles) into a library root.

Files are hardlinked where possible, so the torrent keeps seeding from its own
copy at no extra disk space. Names follow Jellyfin's conventions, with the
quality as a version label so the library scanner still reads it:

    Movies/Dune (2021) [tmdbid-438631]/Dune (2021) [tmdbid-438631] - 1080p WEB-DL H.264-FLUX.mkv
    TV/The Bear (2022) [tmdbid-136315]/Season 01/The Bear (2022) S01E02 - 1080p WEB-DL HEVC-NTb.mkv
    ...and next to the video: <video name>.en.srt, <video name>.nl.forced.srt
"""

import errno
import logging
import os
import re
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from driftwood.config import PathMapping
from driftwood.media.schemas import MediaType
from driftwood.playback.subtitles import MAX_SIDECARS, sidecar_size_limit
from driftwood.selection.classification import classify_release
from driftwood.selection.nfo import normalize_language

from .qbittorrent import TorrentFile

log = logging.getLogger(__name__)

SUBTITLE_EXTENSIONS = frozenset({".srt", ".ass", ".ssa", ".vtt", ".sup", ".idx", ".sub"})
_SUBTITLE_FLAGS = {"forced": "forced", "sdh": "sdh", "hi": "sdh", "cc": "sdh"}
_UNSAFE = re.compile(r'[<>:"|?*\x00-\x1f]')
_SLASHES = re.compile(r"[/\\]")
_SAMPLE_DIRS = frozenset({"sample", "samples"})

_SOURCE_LABELS = {
    "remux": "Remux",
    "bluray-encode": "BluRay",
    "web-dl": "WEB-DL",
    "webrip": "WEBRip",
    "hdtv": "HDTV",
    "dvd": "DVD",
}
_CODEC_LABELS = {"h264": "H.264", "h265": "HEVC", "av1": "AV1", "xvid": "XviD"}
_HDR_LABELS = {"dv": "DV", "hdr10plus": "HDR10+", "hdr10": "HDR10"}

type Mode = Literal["hardlink", "copy", "move", "existing"]


class ImportFailure(Exception):
    """The torrent's files can't be imported; the message is shown to the user."""


@dataclass(frozen=True)
class Target:
    media_type: MediaType
    media_id: int
    title: str
    year: int | None
    season: int | None = None
    episode: int | None = None


@dataclass(frozen=True)
class Placement:
    source: Path
    destination: Path
    within: Path
    """The directory `source` must stay inside: the torrent's save path."""


@dataclass(frozen=True)
class ImportPlan:
    video: Placement
    subtitles: list[Placement]


def to_local(path: str, mappings: list[PathMapping]) -> Path:
    """qBittorrent's view of a path → Driftwood's, by the longest matching prefix."""
    posix = PurePosixPath(path)
    best: tuple[int, Path] | None = None
    for mapping in mappings:
        remote = PurePosixPath(mapping.remote)
        if posix == remote or remote in posix.parents:
            depth = len(remote.parts)
            if best is None or depth > best[0]:
                best = (depth, mapping.local / posix.relative_to(remote))
    return best[1] if best else Path(path)


def safe_name(text: str) -> str:
    """A string usable as a file or directory name on any common filesystem."""
    text = _SLASHES.sub("-", text)
    text = _UNSAFE.sub("", text)
    text = " ".join(text.split())
    return text.strip(" .") or "Untitled"


def version_label(release_title: str) -> str:
    """`Dune.2021.1080p.WEB-DL.DDP5.1.H.264-FLUX` → `1080p WEB-DL H.264-FLUX`."""
    attributes = classify_release(release_title)
    parts = [
        attributes.resolution,
        _SOURCE_LABELS.get(attributes.source or ""),
        *(_HDR_LABELS[flag] for flag in attributes.hdr_flags if flag in _HDR_LABELS),
        _CODEC_LABELS.get(attributes.codec or ""),
    ]
    label = " ".join(part for part in parts if part)
    if not label:
        return safe_name(release_title)
    if attributes.release_group:
        label += f"-{safe_name(attributes.release_group)}"
    return label


def _safe_relative(name: str) -> bool:
    """Whether a file name from the torrent stays inside the save path it's joined to.

    qBittorrent (libtorrent) cleans names up itself; this doesn't rely on it.
    Joining an absolute name would replace the save path altogether."""
    path = PurePosixPath(name)
    return bool(name) and "\0" not in name and not path.is_absolute() and ".." not in path.parts


def _is_sample(path: PurePosixPath) -> bool:
    stem = path.stem.casefold()
    return (
        stem == "sample"
        or stem.endswith(("-sample", ".sample", "_sample"))
        or any(part.casefold() in _SAMPLE_DIRS for part in path.parent.parts)
    )


def _episode_matches(path: PurePosixPath, target: Target) -> bool:
    attributes = classify_release(path.stem)
    return attributes.season == target.season and target.episode in attributes.episodes


def choose_video(
    files: list[TorrentFile],
    target: Target,
    *,
    video_extensions: frozenset[str],
    min_size_bytes: int,
) -> TorrentFile | None:
    """The torrent's main video: for a series the requested episode, else the largest file."""
    videos = [
        file
        for file in files
        if PurePosixPath(file.name).suffix.casefold() in video_extensions
        and not _is_sample(PurePosixPath(file.name))
        and file.size >= min_size_bytes
    ]
    if target.media_type is MediaType.tv and len(videos) > 1:
        episode = [f for f in videos if _episode_matches(PurePosixPath(f.name), target)]
        if episode:
            videos = episode
    return max(videos, key=lambda file: file.size, default=None)


def _videos(files: list[TorrentFile], video_extensions: frozenset[str]) -> list[PurePosixPath]:
    return [
        PurePosixPath(file.name)
        for file in files
        if PurePosixPath(file.name).suffix.casefold() in video_extensions
        and not _is_sample(PurePosixPath(file.name))
    ]


def subtitle_suffix(path: PurePosixPath, video_stem: str) -> str:
    """
    The language / flag part of a subtitle's name, the way the player reads it
    from a sidecar: `.en`, `.nl.forced`, `.en.sdh`, or "" when it doesn't say.
    `Movie.en.srt`, `Subs/2_English.srt` and `English (SDH).srt` all work.
    """
    stem = path.stem
    if stem.casefold().startswith(video_stem.casefold()):
        stem = stem[len(video_stem) :]
    language = None
    flags: list[str] = []
    for token in re.split(r"[\s._\-()\[\]]+", stem):
        word = token.casefold()
        if not word or word.isdigit():
            continue
        if word in _SUBTITLE_FLAGS:
            if _SUBTITLE_FLAGS[word] not in flags:
                flags.append(_SUBTITLE_FLAGS[word])
        elif language is None and len(word) >= 2:
            language = normalize_language(token)
    return "".join(f".{label}" for label in [language, *flags] if label)


def choose_subtitles(
    files: list[TorrentFile], video: PurePosixPath, video_extensions: frozenset[str]
) -> list[PurePosixPath]:
    """
    Subtitle files that belong to `video`: all of them when it's the torrent's
    only video, otherwise the ones named after it or kept in a folder named
    after it (`Subs/<video name>/2_English.srt`).
    """
    subtitles = [
        PurePosixPath(file.name)
        for file in files
        if PurePosixPath(file.name).suffix.casefold() in SUBTITLE_EXTENSIONS
    ]
    if len(_videos(files, video_extensions)) <= 1:
        return sorted(subtitles)
    stem = video.stem.casefold()
    return sorted(
        path
        for path in subtitles
        if path.stem.casefold().startswith(stem)
        or any(part.casefold() == stem for part in path.parent.parts)
    )


def destination(root: Path, target: Target, release_title: str, video: PurePosixPath) -> Path:
    """Where the video goes in the library root, named the Jellyfin way."""
    year = f" ({target.year})" if target.year else ""
    title = safe_name(target.title)
    folder = f"{title}{year} [tmdbid-{target.media_id}]"
    label = version_label(release_title)
    extension = video.suffix.lower()
    if target.media_type is MediaType.movie:
        return root / folder / f"{folder} - {label}{extension}"

    season = target.season or 0
    episodes = list(classify_release(video.stem).episodes)
    if target.episode not in episodes:
        episodes = [target.episode or 1]
    code = f"S{season:02d}" + "-".join(f"E{number:02d}" for number in sorted(episodes))
    season_folder = "Specials" if season == 0 else f"Season {season:02d}"
    return root / folder / season_folder / f"{title}{year} {code} - {label}{extension}"


def plan_import(
    files: list[TorrentFile],
    *,
    save_path: Path,
    root: Path,
    target: Target,
    release_title: str,
    video_extensions: frozenset[str],
    min_size_bytes: int,
    subtitles: bool,
) -> ImportPlan:
    unsafe = [file.name for file in files if not _safe_relative(file.name)]
    if unsafe:
        log.warning("Ignoring torrent files outside the save path: %r", unsafe[:10])
        files = [file for file in files if _safe_relative(file.name)]
    video = choose_video(
        files, target, video_extensions=video_extensions, min_size_bytes=min_size_bytes
    )
    if video is None:
        raise ImportFailure("The torrent has no video file to import")
    video_path = PurePosixPath(video.name)
    video_destination = destination(root, target, release_title, video_path)

    placements: list[Placement] = []
    if subtitles:
        # The ones playback would offer: a torrent stuffed with subtitles brings no more.
        sizes = {PurePosixPath(file.name): file.size for file in files}
        wanted = [
            path
            for path in choose_subtitles(files, video_path, video_extensions)
            if sizes[path] <= sidecar_size_limit(path.suffix)
        ][:MAX_SIDECARS]
        taken: set[str] = set()
        for path in wanted:
            suffix = subtitle_suffix(path, video_path.stem)
            extension = path.suffix.lower()
            name = f"{video_destination.stem}{suffix}{extension}"
            counter = 2
            while name.casefold() in taken:
                name = f"{video_destination.stem}.{counter}{suffix}{extension}"
                counter += 1
            taken.add(name.casefold())
            placements.append(
                Placement(save_path / path, video_destination.with_name(name), save_path)
            )
    return ImportPlan(Placement(save_path / video_path, video_destination, save_path), placements)


_NO_HARDLINK = {errno.EXDEV, errno.EPERM, errno.EMLINK, errno.EOPNOTSUPP, errno.ENOTSUP}


def place(placement: Placement, fallback: Literal["copy", "move"]) -> Mode:
    """
    Hardlink `source` to `destination`, or copy / move it when the two aren't on
    one filesystem. The file appears under its final name only once complete
    (the scanner skips the hidden partial file).

    `source` must be a regular file inside `within`: a symlink in the torrent, or
    a folder of it that is one, could otherwise bring any file of this machine
    into the library.
    """
    source, target = placement.source, placement.destination
    try:
        info = os.lstat(source)
    except FileNotFoundError:
        raise ImportFailure(
            f"{source} isn't there (check DRIFTWOOD_DOWNLOADS__QBITTORRENT__PATH_MAPPINGS)"
        ) from None
    if not stat.S_ISREG(info.st_mode):
        raise ImportFailure(f"{source} isn't a regular file")
    if not source.resolve(strict=True).is_relative_to(placement.within.resolve(strict=True)):
        raise ImportFailure(f"{source} is outside the torrent's save path")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and os.path.samefile(source, target):
        return "existing"
    partial = target.with_name(f".{target.name}.partial")
    partial.unlink(missing_ok=True)
    try:
        try:
            os.link(source, partial, follow_symlinks=False)
            mode: Mode = "hardlink"
        except OSError as exc:
            if exc.errno not in _NO_HARDLINK:
                raise
            if fallback == "move":
                shutil.move(source, partial)
                mode = "move"
            else:
                shutil.copyfile(source, partial, follow_symlinks=False)
                shutil.copystat(source, partial, follow_symlinks=False)
                mode = "copy"
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    return mode


def execute(plan: ImportPlan, fallback: Literal["copy", "move"]) -> Mode:
    """Place the video, then its subtitles; a subtitle that fails is only logged."""
    mode = place(plan.video, fallback)
    log.info("Imported %s → %s (%s)", plan.video.source, plan.video.destination, mode)
    for subtitle in plan.subtitles:
        try:
            place(subtitle, fallback)
        except (OSError, ImportFailure):
            log.warning("Could not import subtitle %s", subtitle.source, exc_info=True)
    return mode
