"""Making Jellyfin-style trickplay sheets for videos that have none.

Seek-bar thumbnails are wanted most right after a download is imported, when
someone is often already watching it. So this aims to be fast, and useful
before it's finished:

- Only keyframes are decoded (`-skip_frame nokey`, as Jellyfin's "key frames
  only" option does). A thumbnail then shows the keyframe at or just before its
  time, which is close enough for a seek-bar preview and costs a fraction of
  decoding every frame.
- Each sheet is its own ffmpeg run that seeks to where the sheet starts, so
  sheets render side by side (`trickplay_workers`). One keyframe-only pass over
  a whole film is decode-bound on about one core: a 2.5 h 1080p encode took
  105 s that way and 12 s as ten parallel sheets, with byte-identical sheets.
- A sheet is moved into place as soon as it's done, and players can show it
  right away. Sheets from where the viewer is onwards go first.
- The layout directory holds a marker until the last sheet is in, so the
  reader never takes a half-made set for a finished one, and a restart carries
  on where it stopped instead of starting over.

ffmpeg runs at a low CPU priority, so playback (which may be reading the same
file) comes first.
"""

import asyncio
import contextlib
import json
import logging
import math
import os
import shutil
import time
from dataclasses import dataclass, field
from enum import IntEnum
from fractions import Fraction
from pathlib import Path
from typing import Any

from driftwood.config import PlaybackSettings
from driftwood.playback.errors import PlaybackError
from driftwood.playback.policy import PLAYABLE_SUFFIXES
from driftwood.playback.probe import MediaProbe, probe_file
from driftwood.playback.process import VIDEO_DECODERS, input_args, kill, spawn
from driftwood.playback.trickplay import (
    MARKER,
    Trickplay,
    find_trickplay,
    layout_directory,
    thumbnail_count,
)

log = logging.getLogger(__name__)

COLUMNS = ROWS = 10
"""Thumbnails per sheet row and column: Jellyfin's default tiling."""
_JPEG_QUALITY = "4"
"""ffmpeg's `-q:v` for the sheets, 2 (best) to 31."""
_SHEET_TIMEOUT_SECONDS = 3 * 60
"""A sheet usually takes seconds; one this slow means ffmpeg is stuck."""
_HDR_TRANSFERS = frozenset({"smpte2084", "arib-std-b67"})


class Priority(IntEnum):
    """Which job's sheets are made first when several are waiting."""

    imported = 1
    watching = 2


@dataclass(frozen=True)
class Layout:
    width: int
    height: int
    columns: int
    rows: int
    interval: float
    count: int

    @property
    def per_sheet(self) -> int:
        return self.columns * self.rows

    @property
    def sheets(self) -> int:
        return math.ceil(self.count / self.per_sheet)

    @property
    def sheet_seconds(self) -> float:
        return self.per_sheet * self.interval


def _ratio(value: object) -> Fraction | None:
    try:
        numerator, denominator = (int(part) for part in str(value).split(":"))
    except ValueError:
        return None
    return Fraction(numerator, denominator) if numerator > 0 and denominator > 0 else None


def _rotated(stream: dict[str, Any]) -> bool:
    """Whether the video is shown turned a quarter (ffmpeg turns it upright when decoding)."""
    for side_data in stream.get("side_data_list") or []:
        if isinstance(side_data, dict) and "rotation" in side_data:
            try:
                return round(abs(float(side_data["rotation"]))) % 180 == 90
            except (TypeError, ValueError):
                return False
    return False


def thumbnail_size(stream: dict[str, Any], width: int) -> tuple[int, int]:
    """A thumbnail `width` wide with the video's display aspect ratio and an even height."""
    try:
        frame_width, frame_height = int(stream["width"]), int(stream["height"])
    except (KeyError, TypeError, ValueError):
        frame_width = frame_height = 0
    if frame_width <= 0 or frame_height <= 0:
        raise PlaybackError(422, "The video stream has no known size.")
    aspect = Fraction(frame_width, frame_height) * (_ratio(stream.get("sample_aspect_ratio")) or 1)
    if _rotated(stream):
        aspect = 1 / aspect
    return width, max(2, round(width / aspect / 2) * 2)


@dataclass(eq=False)
class TrickplayJob:
    video: Path
    directory: Path
    layout: Layout
    demuxer: str
    video_index: int
    transfer: str | None
    """The video's transfer characteristics, for tone mapping HDR."""
    stamp: dict[str, Any]
    """What the marker records: which version of the video the sheets are of."""
    priority: Priority
    submitted: float = field(default_factory=time.monotonic)
    focus: int = 0
    """The sheet the viewer is at: it and the ones after it are made first."""
    pending: set[int] = field(default_factory=set)
    running: set[int] = field(default_factory=set)
    ready: set[int] = field(default_factory=set)
    error: str | None = None
    done: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def generating(self) -> bool:
        return not self.done.is_set()

    def trickplay(self) -> Trickplay:
        layout = self.layout
        return Trickplay(
            directory=self.directory,
            sheets=layout.sheets,
            columns=layout.columns,
            rows=layout.rows,
            width=layout.width,
            height=layout.height,
            interval=layout.interval,
            count=layout.count,
        )

    def sheet(self, index: int) -> Path | None:
        return self.directory / f"{index}.jpg" if index in self.ready else None

    def focus_on(self, seconds: float) -> None:
        sheet = int(max(seconds, 0) // self.layout.sheet_seconds)
        self.focus = min(sheet, self.layout.sheets - 1)

    def next_sheet(self) -> int | None:
        """The sheet to make next: from the viewer's onwards, then back from it."""
        if not self.pending:
            return None
        return min(self.pending, key=lambda i: (i < self.focus, abs(i - self.focus)))


class TrickplayGenerator:
    def __init__(
        self, settings: PlaybackSettings, *, columns: int = COLUMNS, rows: int = ROWS
    ) -> None:
        self.settings = settings
        self.columns = columns
        self.rows = rows
        self._jobs: dict[Path, TrickplayJob] = {}
        self._starting: dict[Path, asyncio.Task[TrickplayJob | None]] = {}
        """Jobs being set up: a second caller waits for the same one."""
        self._failed: set[Path] = set()
        """Videos to leave alone until the next restart."""
        self._busy = 0
        self._tasks: set[asyncio.Task[Any]] = set()
        self._closed = False
        self._tone_mapping: asyncio.Task[bool] | None = None

    @property
    def enabled(self) -> bool:
        return self.settings.trickplay_generate

    def job(self, video: Path) -> TrickplayJob | None:
        return self._jobs.get(video)

    async def shutdown(self) -> None:
        self._closed = True
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _spawn(self, coroutine: Any, name: str) -> asyncio.Task[Any]:
        task = asyncio.create_task(coroutine, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    # Asking for thumbnails

    def request(self, video: Path, priority: Priority = Priority.imported) -> None:
        """Make thumbnails for `video` in the background, unless it has some already."""
        if self.enabled and not self._closed:
            self._spawn(self._request(video, priority), f"trickplay-request-{video.name}")

    async def _request(self, video: Path, priority: Priority) -> None:
        if video.suffix.casefold() not in PLAYABLE_SUFFIXES:
            # Nobody can watch it here, so its thumbnails aren't worth running ffmpeg on it.
            return
        try:
            video = await asyncio.to_thread(video.resolve, True)
            if video in self._jobs or video in self._failed:
                return
            probe = await probe_file(self.settings.ffprobe, video)
            await self.submit(video, probe, priority)
        except (OSError, PlaybackError) as exc:
            log.warning("Can't make trickplay for %s: %s", video.name, exc)

    async def submit(
        self, video: Path, probe: MediaProbe, priority: Priority
    ) -> TrickplayJob | None:
        """Start (or hurry along) making thumbnails for a video without any.

        `video` is a resolved path. Returns None when they can't be made, or
        when the video turns out to have them already."""
        if not self.enabled or self._closed or video in self._failed:
            return None
        if (job := self._jobs.get(video)) is None:
            starting = self._starting.get(video)
            if starting is None:
                starting = self._spawn(
                    self._start(video, probe, priority), f"trickplay-start-{video.name}"
                )
                self._starting[video] = starting
                starting.add_done_callback(lambda _: self._starting.pop(video, None))
            job = await asyncio.shield(starting)
        if job is not None:
            job.priority = max(job.priority, priority)
        return job

    async def _start(
        self, video: Path, probe: MediaProbe, priority: Priority
    ) -> TrickplayJob | None:
        try:
            job = await asyncio.to_thread(self._prepare, video, probe, priority)
        except (OSError, PlaybackError) as exc:
            log.warning("Can't make trickplay for %s: %s", video.name, exc)
            self._failed.add(video)
            return None
        if job is None or self._closed:
            return None
        self._jobs[video] = job
        log.info(
            "Making trickplay for %s: %d sheets, %d already made",
            video.name,
            job.layout.sheets,
            len(job.ready),
        )
        if job.pending:
            self._pump()
        else:
            self._spawn(self._finish(job, time.monotonic()), f"trickplay-finish-{video.name}")
        return job

    def _prepare(self, video: Path, probe: MediaProbe, priority: Priority) -> TrickplayJob | None:
        """Set up the layout directory, keeping sheets an interrupted run already made."""
        stream = probe.video
        if stream is None:
            raise PlaybackError(415, "The file has no video stream.")
        if probe.demuxer is None or stream.get("codec_name") not in VIDEO_DECODERS:
            raise PlaybackError(415, "The video can't be played, so it gets no thumbnails.")
        interval = self.settings.trickplay_interval_seconds
        if find_trickplay(video, probe.duration, interval):
            return None
        width, height = thumbnail_size(stream, self.settings.trickplay_width)
        layout = Layout(
            width=width,
            height=height,
            columns=self.columns,
            rows=self.rows,
            interval=interval,
            count=thumbnail_count(probe.duration, interval),
        )
        stat = video.stat()
        stamp = {
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "duration": probe.duration,
            "interval": interval,
            "height": height,
        }
        directory = layout_directory(video, width, self.columns, self.rows)
        marker = directory / MARKER
        if directory.exists():
            if not marker.is_file():
                # Someone else's (Jellyfin's, at another interval): not ours to overwrite.
                log.info("%s has trickplay that doesn't fit; leaving it be", video.name)
                return None
            try:
                resumable = json.loads(marker.read_text(encoding="utf-8")) == stamp
            except (OSError, ValueError):
                resumable = False
            if not resumable:
                shutil.rmtree(directory)
        directory.mkdir(parents=True, exist_ok=True)
        if not marker.is_file():
            marker.write_text(json.dumps(stamp), encoding="utf-8")
        for leftover in directory.glob(".*.tmp"):
            leftover.unlink(missing_ok=True)

        sheets = range(layout.sheets)
        ready = {index for index in sheets if (directory / f"{index}.jpg").is_file()}
        return TrickplayJob(
            video=video,
            directory=directory,
            layout=layout,
            demuxer=probe.demuxer,
            video_index=int(stream["index"]),
            transfer=stream.get("color_transfer"),
            stamp=stamp,
            priority=priority,
            pending=set(sheets) - ready,
            ready=ready,
        )

    # Making sheets

    def _pump(self) -> None:
        """Start sheets while there are free workers: the most urgent job's first."""
        while not self._closed and self._busy < self.settings.trickplay_workers:
            waiting = [job for job in self._jobs.values() if job.pending]
            if not waiting:
                return
            job = max(waiting, key=lambda job: (job.priority, -job.submitted))
            index = job.next_sheet()
            assert index is not None
            job.pending.discard(index)
            job.running.add(index)
            self._busy += 1
            self._spawn(self._render(job, index), f"trickplay-{job.video.name}-{index}")

    async def _render(self, job: TrickplayJob, index: int) -> None:
        started = time.monotonic()
        try:
            await self._make_sheet(job, index)
        except PlaybackError as exc:
            if job.error is None:
                log.warning("Trickplay for %s stopped: %s", job.video.name, exc.detail)
            job.error = exc.detail
            job.pending.clear()
        except OSError as exc:
            job.error = str(exc)
            job.pending.clear()
            log.warning("Trickplay for %s stopped: %s", job.video.name, exc)
        else:
            job.ready.add(index)
            log.debug("Trickplay sheet %d of %s took %.1f s", index, job.video.name,
                      time.monotonic() - started)  # fmt: skip
        finally:
            job.running.discard(index)
            self._busy -= 1
        if not job.pending and not job.running:
            self._spawn(self._finish(job, started), f"trickplay-finish-{job.video.name}")
        self._pump()

    async def _finish(self, job: TrickplayJob, started: float) -> None:
        try:
            if job.error is None:
                # Only now does the reader take it for a finished set.
                await asyncio.to_thread((job.directory / MARKER).unlink, True)
        except OSError as exc:
            job.error = str(exc)
        finally:
            self._jobs.pop(job.video, None)
            if job.error is not None:
                self._failed.add(job.video)
            job.done.set()
        if job.error is None:
            log.info("Made trickplay for %s (%d sheets)", job.video.name, job.layout.sheets)

    async def _make_sheet(self, job: TrickplayJob, index: int) -> None:
        target = job.directory / f"{index}.jpg"
        partial = job.directory / f".{index}.jpg.tmp"
        command = [
            self.settings.ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-skip_frame",
            "nokey",
        ]
        if index:
            # From the keyframe at or before the sheet's start, like a pass over the whole file.
            start = index * job.layout.sheet_seconds
            command += ["-noaccurate_seek", "-ss", f"{start:.6f}"]
        command += [
            *input_args(job.video, job.demuxer),
            "-map",
            f"0:{job.video_index}",
            "-an",
            "-sn",
            "-dn",
            "-vf",
            sheet_filter(
                job.layout, hdr=job.transfer if await self._tone_map(job.transfer) else None
            ),
            "-frames:v",
            "1",
            "-c:v",
            "mjpeg",
            "-q:v",
            _JPEG_QUALITY,
            "-f",
            "image2",
            "-update",
            "1",
            str(partial),
        ]
        process = await spawn(command, reads=[job.video], writes=[job.directory], background=True)
        try:
            _, stderr = await asyncio.wait_for(process.communicate(), _SHEET_TIMEOUT_SECONDS)
        except TimeoutError:
            await _abandon(process, partial)
            raise PlaybackError(504, f"Sheet {index} took too long.") from None
        except BaseException:
            await _abandon(process, partial)
            raise
        if process.returncode or not partial.is_file():
            lines = stderr.decode(errors="replace").strip().splitlines()
            partial.unlink(missing_ok=True)
            raise PlaybackError(502, f"ffmpeg failed on sheet {index}: "
                                f"{lines[-1] if lines else 'no output'}")  # fmt: skip
        await asyncio.to_thread(os.replace, partial, target)

    async def _tone_map(self, transfer: str | None) -> bool:
        """Whether to tone map: for HDR video, when ffmpeg has the filters for it."""
        if transfer not in _HDR_TRANSFERS:
            return False
        if self._tone_mapping is None:
            self._tone_mapping = self._spawn(self._has_tone_mapping(), "trickplay-tone-mapping")
        return await asyncio.shield(self._tone_mapping)

    async def _has_tone_mapping(self) -> bool:
        try:
            process = await spawn(
                [self.settings.ffmpeg, "-hide_banner", "-filters"],
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except PlaybackError:
            return False
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=30)
        except TimeoutError:
            await kill(process)
            return False
        names = {line.split()[1] for line in stdout.decode().splitlines() if len(line.split()) > 2}
        if not {"zscale", "tonemap"} <= names:
            log.info("ffmpeg lacks zscale/tonemap: HDR thumbnails will look washed out")
            return False
        return True


async def _abandon(process: asyncio.subprocess.Process, partial: Path) -> None:
    await kill(process)
    with contextlib.suppress(OSError):
        partial.unlink(missing_ok=True)


def sheet_filter(layout: Layout, *, hdr: str | None = None) -> str:
    """Keyframes in, one `columns` x `rows` sheet of thumbnails out.

    `fps` picks the frame for every `interval` seconds from 0 (repeating the
    first keyframe when a seek lands just after it) and keeps the last one at
    the end of the file; `tile` pads a short last sheet with black. `hdr` is
    the transfer of HDR video to tone map, which is scaled down first so that
    costs next to nothing."""
    size = f"{layout.width}:{layout.height}"
    if hdr:
        scale = (
            f"zscale=w={layout.width}:h={layout.height}:tin={hdr}:min=bt2020nc:pin=bt2020:rin=tv:"
            "t=linear:npl=100,format=gbrpf32le,"
            "zscale=p=bt709,tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p"
        )
    else:
        scale = f"scale={size}"
    return (
        f"fps=fps=1/{layout.interval:g}:start_time=0:eof_action=pass,{scale},setsar=1,"
        f"tile={layout.columns}x{layout.rows}"
    )
