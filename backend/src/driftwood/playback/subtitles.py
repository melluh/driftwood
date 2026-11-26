"""Subtitle tracks of a file: embedded streams and sidecar files next to it.

Each track is offered in the format the browser renders it from: WebVTT for
plain text (SRT, WebVTT, mov_text), ASS for styled text (drawn by JASSUB, with
a WebVTT fallback), and PGS (`.sup`) for the picture-based subtitles of
Blu-ray rips. DVD (VobSub) subtitles aren't offered.
"""

import hashlib
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from driftwood.playback.process import input_args

TEXT_CODECS = {"subrip", "webvtt", "mov_text", "text"}
ASS_CODECS = {"ass", "ssa"}
PGS_CODECS = {"hdmv_pgs_subtitle"}

_SIDECAR_FORMATS = {".srt": "subrip", ".vtt": "webvtt", ".ass": "ass", ".ssa": "ssa", ".sup": "pgs"}
_SIDECAR_DEMUXERS = {"subrip": "srt", "webvtt": "webvtt", "ass": "ass", "ssa": "ass"}
"""How ffmpeg reads a text sidecar: by its extension, never by guessing from its content."""
MAX_SIDECARS = 64
_MAX_TEXT_SIDECAR_BYTES = 10 * 1024**2
"""A feature film's SRT is about 100 KB; ASS with heavy typesetting a few MB."""
_MAX_PGS_SIDECAR_BYTES = 256 * 1024**2
_HEARING_IMPAIRED = {"sdh", "hi", "cc"}
_LANGUAGE_NAMES = {
    "english": "eng",
    "dutch": "dut",
    "nederlands": "dut",
    "french": "fre",
    "german": "ger",
    "spanish": "spa",
    "italian": "ita",
    "portuguese": "por",
    "japanese": "jpn",
    "korean": "kor",
    "chinese": "chi",
    "russian": "rus",
    "swedish": "swe",
    "danish": "dan",
    "norwegian": "nor",
    "finnish": "fin",
    "polish": "pol",
}
_CODE = re.compile(r"^[a-z]{2,3}(-[a-z]{2,4})?$")


@dataclass
class SubtitleTrack:
    id: int
    format: str
    """`webvtt`, `ass` or `pgs`: what the browser renders it from."""
    codec: str
    language: str | None = None
    title: str | None = None
    forced: bool = False
    hearing_impaired: bool = False
    stream_index: int | None = None
    """Set for a stream embedded in the video file."""
    sidecar: Path | None = None
    """Set for a subtitle file next to the video file."""

    @property
    def outputs(self) -> tuple[str, ...]:
        """File extensions this track is served as."""
        if self.format == "pgs":
            return ("sup",)
        if self.format == "ass":
            return ("ass", "vtt")
        return ("vtt",)


def _format(codec: str) -> str | None:
    if codec in TEXT_CODECS:
        return "webvtt"
    if codec in ASS_CODECS:
        return "ass"
    if codec in PGS_CODECS or codec == "pgs":
        return "pgs"
    return None


def embedded_tracks(streams: list[dict[str, Any]]) -> list[SubtitleTrack]:
    tracks = []
    for stream in streams:
        codec = str(stream.get("codec_name") or "")
        subtitle_format = _format(codec)
        if subtitle_format is None:
            continue
        raw_tags = stream.get("tags")
        tags = (
            {str(k).lower(): str(v) for k, v in raw_tags.items()}
            if isinstance(raw_tags, dict)
            else {}
        )
        disposition = stream.get("disposition")
        disposition = disposition if isinstance(disposition, dict) else {}
        language = tags.get("language")
        tracks.append(
            SubtitleTrack(
                id=len(tracks),
                format=subtitle_format,
                codec=codec,
                language=None if language in (None, "", "und") else language,
                title=tags.get("title") or None,
                forced=bool(disposition.get("forced")),
                hearing_impaired=bool(disposition.get("hearing_impaired")),
                stream_index=int(stream["index"]),
            )
        )
    return tracks


def _describe_sidecar(path: Path, video_stem: str) -> dict[str, Any]:
    """`Movie.en.forced.srt` → language `en`, forced. Other words become the title."""
    labels = path.name[len(video_stem) : -len(path.suffix)].strip(".").split(".")
    language = None
    forced = hearing_impaired = False
    title_words = []
    for label in filter(None, labels):
        word = label.lower()
        if word == "forced":
            forced = True
        elif word in _HEARING_IMPAIRED:
            hearing_impaired = True
        elif word in {"default", "full"} or word.isdigit():
            continue
        elif language is None and (_CODE.match(word) or word in _LANGUAGE_NAMES):
            language = _LANGUAGE_NAMES.get(word, word)
        else:
            title_words.append(label)
    return {
        "language": language,
        "forced": forced,
        "hearing_impaired": hearing_impaired,
        "title": " ".join(title_words) or None,
    }


def _small_enough(path: Path) -> bool:
    limit = _MAX_PGS_SIDECAR_BYTES if path.suffix.lower() == ".sup" else _MAX_TEXT_SIDECAR_BYTES
    try:
        return path.stat().st_size <= limit
    except OSError:
        return False


def sidecar_tracks(video: Path, first_id: int) -> list[SubtitleTrack]:
    """Subtitle files named after the video: `Movie.srt`, `Movie.eng.srt`, `Movie.en.sdh.srt`.

    At most `MAX_SIDECARS` of them, each of a size real subtitles have."""
    prefix = video.stem + "."
    try:
        candidates = sorted(
            (
                entry
                for entry in video.parent.iterdir()
                if entry.name.startswith(prefix)
                and entry.suffix.lower() in _SIDECAR_FORMATS
                and entry.is_file()
                and _small_enough(entry)
            ),
            key=lambda entry: entry.name.casefold(),
        )[:MAX_SIDECARS]
    except OSError:
        return []
    tracks = []
    for path in candidates:
        codec = _SIDECAR_FORMATS[path.suffix.lower()]
        subtitle_format = _format(codec)
        assert subtitle_format is not None
        tracks.append(
            SubtitleTrack(
                id=first_id + len(tracks),
                format=subtitle_format,
                codec=codec,
                sidecar=path,
                **_describe_sidecar(path, video.stem),
            )
        )
    return tracks


def fingerprint(tracks: list[SubtitleTrack]) -> str:
    """Changes when a sidecar is added, removed or edited, so stale extractions aren't reused."""
    parts = []
    for track in tracks:
        if track.sidecar is not None:
            try:
                stat = track.sidecar.stat()
            except OSError:
                continue
            parts.append(f"{track.sidecar.name}:{stat.st_size}:{stat.st_mtime_ns}")
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:10] if parts else "embedded"


def embedded_command(tracks: list[SubtitleTrack], directory: Path) -> list[str]:
    """ffmpeg output options extracting every embedded track in one pass."""
    args: list[str] = []
    for track in tracks:
        if track.stream_index is None:
            continue
        stream = f"0:{track.stream_index}"
        if track.format == "pgs":
            args += ["-map", stream, "-c:s", "copy", str(directory / f"{track.id}.sup")]
            continue
        args += ["-map", stream, "-c:s", "webvtt", str(directory / f"{track.id}.vtt")]
        if track.format == "ass":
            codec = "copy" if track.codec == "ass" else "ass"
            args += ["-map", stream, "-c:s", codec, str(directory / f"{track.id}.ass")]
    return args


def utf8_copy(source: Path, target: Path) -> Path:
    """The sidecar re-encoded to the UTF-8 ffmpeg expects (old SRTs are often Windows-1252)."""
    data = source.read_bytes()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
    target.write_text(text, encoding="utf-8")
    return target


def sidecar_commands(ffmpeg: str, track: SubtitleTrack, directory: Path) -> list[list[str]]:
    """Copies (and ffmpeg conversions) turning a sidecar into the files it's served as.

    Returns the ffmpeg commands still to run after the direct copies are made."""
    assert track.sidecar is not None
    if track.format == "pgs":
        shutil.copyfile(track.sidecar, directory / f"{track.id}.sup")
        return []
    if track.format == "ass":
        # Served as it is (in UTF-8); libass reads SSA too.
        source = utf8_copy(track.sidecar, directory / f"{track.id}.ass")
    else:
        source = utf8_copy(track.sidecar, directory / f"{track.id}.source{track.sidecar.suffix}")
    return [
        [
            *(ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y"),
            *input_args(source, _SIDECAR_DEMUXERS[track.codec]),
            *("-c:s", "webvtt", str(directory / f"{track.id}.vtt")),
        ]
    ]
