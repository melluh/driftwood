"""HLS segments copied out of a file on demand, at its own keyframes.

The playlist is a complete VOD playlist built before playback from the video
stream's keyframes, so the player knows the duration and can seek anywhere.
Segments start exactly at the planned keyframes no matter where ffmpeg started,
so a run started for a seek produces the same bytes a run from the start would.

One ffmpeg run per job produces segments ahead of what the player has asked
for. It pauses (SIGSTOP) once it's `lead` segments ahead and resumes when the
player catches up; a request outside what the run will produce soon restarts it
there. Segments far behind the player are deleted, and come back on demand.
"""

import asyncio
import contextlib
import itertools
import logging
import math
import os
import shutil
import signal
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from driftwood.playback.errors import PlaybackError
from driftwood.playback.policy import AudioOutput
from driftwood.playback.process import CHILD_OPTIONS

log = logging.getLogger(__name__)

_CAN_PAUSE = hasattr(signal, "SIGSTOP")
# Seeking to a keyframe's exact time can land on the keyframe before it: ffmpeg
# backs off 3/23 s for streams with B-frames. Aim this far past it instead.
_SEEK_MARGIN = 0.25
_FAR_FUTURE = "999999999"
_SEGMENT_WAIT_SECONDS = 60


@dataclass(frozen=True)
class SegmentPlan:
    origin: float
    """Container start time: the zero of the playback timeline."""
    end: float
    starts: list[float]
    """The keyframe each segment starts at."""
    cuts: list[float]
    """Between each segment's first keyframe and the keyframe before it (unused for 0).

    ffmpeg's segment muxer cuts at the first keyframe at or after a time, and
    measures that time from wherever its run started. Midpoints leave half a
    GOP of slack either way."""
    seeks: list[float]

    @classmethod
    def build(
        cls, keyframes: list[float], origin: float, duration: float, target: float
    ) -> "SegmentPlan":
        end = origin + duration
        frames = sorted({frame for frame in keyframes if frame < end - 0.25}) or [origin]
        starts = [frames[0]]
        cuts = [frames[0]]
        for previous, frame in itertools.pairwise(frames):
            if frame - starts[-1] >= target:
                starts.append(frame)
                cuts.append((previous + frame) / 2)
        if len(starts) > 1 and end - starts[-1] < target / 3:
            # Fold a sliver at the very end into the segment before it.
            starts.pop()
            cuts.pop()
        following = dict(itertools.pairwise(frames))
        seeks = [
            start + min(_SEEK_MARGIN, (following.get(start, start + 1) - start) / 2)
            for start in starts
        ]
        return cls(origin=origin, end=end, starts=starts, cuts=cuts, seeks=seeks)

    def __len__(self) -> int:
        return len(self.starts)

    def durations(self) -> list[float]:
        bounds = [self.origin, *self.starts[1:], self.end]
        return [later - earlier for earlier, later in itertools.pairwise(bounds)]

    def playlist(self) -> str:
        durations = self.durations()
        lines = [
            "#EXTM3U",
            "#EXT-X-VERSION:3",
            f"#EXT-X-TARGETDURATION:{math.ceil(max(durations))}",
            "#EXT-X-MEDIA-SEQUENCE:0",
            "#EXT-X-PLAYLIST-TYPE:VOD",
            "#EXT-X-INDEPENDENT-SEGMENTS",
        ]
        for index, duration in enumerate(durations):
            lines.extend([f"#EXTINF:{duration:.6f},", f"{index}.ts"])
        lines.append("#EXT-X-ENDLIST")
        return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class SegmentSource:
    ffmpeg: str
    path: Path
    video_index: int
    audio_index: int | None
    audio: AudioOutput | None


class SegmentJob:
    def __init__(
        self,
        source: SegmentSource,
        plan: SegmentPlan,
        directory: Path,
        *,
        lead: int,
        keep_behind: int,
    ) -> None:
        self.source = source
        self.plan = plan
        self.directory = directory
        self.lead = lead
        self.keep_behind = keep_behind
        self.last_used = time.monotonic()
        self._ready: set[int] = set()
        self._waiters: dict[int, asyncio.Event] = {}
        self._lock = asyncio.Lock()
        self._process: asyncio.subprocess.Process | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._paused = False
        self._next = 0
        """The segment the running ffmpeg is writing."""
        self._run_start = 0
        self._requested = 0
        self._error: str | None = None
        self._closed = False

    def path(self, index: int) -> Path:
        return self.directory / f"{index:05d}.ts"

    async def segment(self, index: int) -> Path:
        if not 0 <= index < len(self.plan):
            raise PlaybackError(404, "No such segment.")
        if self._closed:
            raise PlaybackError(410, "Playback has stopped.")
        self.last_used = time.monotonic()
        self._requested = index
        self._prune()
        if index in self._ready and self.path(index).exists():
            self._throttle()
            return self.path(index)
        self._ready.discard(index)

        deadline = time.monotonic() + _SEGMENT_WAIT_SECONDS
        starts = 0
        while index not in self._ready:
            if self._closed:
                raise PlaybackError(410, "Playback has stopped.")
            event = self._waiters.setdefault(index, asyncio.Event())
            async with self._lock:
                if index not in self._ready and not self._will_produce(index):
                    if starts == 2:
                        raise PlaybackError(
                            502, self._error or "ffmpeg stopped before writing the segment."
                        )
                    starts += 1
                    await self._start(index)
                    event = self._waiters.setdefault(index, asyncio.Event())
            self._throttle()
            # Woken when the segment is listed, or when the run ends or is replaced.
            try:
                await asyncio.wait_for(event.wait(), timeout=deadline - time.monotonic())
            except TimeoutError:
                raise PlaybackError(504, "Timed out waiting for ffmpeg.") from None
        return self.path(index)

    def _will_produce(self, index: int) -> bool:
        running = self._process is not None and self._process.returncode is None
        return running and self._run_start <= index <= self._next + 2

    def _throttle(self) -> None:
        process = self._process
        if not _CAN_PAUSE or process is None or process.returncode is not None:
            return
        ahead = self._next - self._requested
        with contextlib.suppress(ProcessLookupError):
            if self._paused and ahead < self.lead:
                os.kill(process.pid, signal.SIGCONT)
                self._paused = False
            elif not self._paused and ahead >= self.lead and self._next < len(self.plan):
                # (Past the last segment ffmpeg is only finishing up; let it exit.)
                os.kill(process.pid, signal.SIGSTOP)
                self._paused = True

    def _prune(self) -> None:
        low = self._requested - self.keep_behind
        high = self._requested + 3 * self.lead
        for index in [index for index in self._ready if not low <= index <= high]:
            self._ready.discard(index)
            self.path(index).unlink(missing_ok=True)

    def command(self, index: int) -> list[str]:
        source, plan = self.source, self.plan
        origin_seek = max(0.0, plan.seeks[index] - plan.origin)
        cuts = [f"{cut - plan.starts[index]:.3f}" for cut in plan.cuts[index + 1 :]]
        command = [
            source.ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-copyts",
            "-ss",
            f"{origin_seek:.3f}",
            # Keep audio from the keyframe on: an accurate seek would start it
            # 0.25 s late and leave a gap at every restart.
            "-noaccurate_seek",
            "-i",
            str(source.path),
            "-map",
            f"0:{source.video_index}",
            "-c:v",
            "copy",
        ]
        if source.audio_index is not None and source.audio is not None:
            command.extend(["-map", f"0:{source.audio_index}", "-c:a", source.audio.codec])
            if source.audio.channels:
                command.extend(["-ac", str(source.audio.channels)])
            if source.audio.bitrate:
                command.extend(["-b:a", source.audio.bitrate])
        command.extend(
            [
                "-sn",
                "-dn",
                "-map_metadata",
                "-1",
                "-map_chapters",
                "-1",
                "-max_muxing_queue_size",
                "4096",
                # Keep source timestamps in every run. Left on, a run from the
                # very start shifts by the B-frame delay to avoid negative DTS,
                # and mid-file runs don't. Both the segment muxer and the
                # mpegts muxer inside it would shift.
                "-avoid_negative_ts",
                "disabled",
                "-f",
                "segment",
                "-segment_format",
                "mpegts",
                "-segment_format_options",
                "avoid_negative_ts=disabled",
                "-segment_times",
                ",".join(cuts) or _FAR_FUTURE,
                "-segment_start_number",
                str(index),
                "-segment_list",
                "pipe:1",
                "-segment_list_type",
                "csv",
                str(self.directory / "%05d.ts"),
            ]
        )
        return command

    async def _start(self, index: int) -> None:
        await self._stop_process()
        self.directory.mkdir(parents=True, exist_ok=True)
        self._error = None
        self._run_start = self._next = index
        self._paused = False
        try:
            process = await asyncio.create_subprocess_exec(
                *self.command(index),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                **CHILD_OPTIONS,
            )
        except OSError as exc:
            raise PlaybackError(503, f"Could not run ffmpeg: {exc}") from exc
        self._process = process
        task = asyncio.create_task(self._watch(process), name=f"segments-{self.directory.name}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _watch(self, process: asyncio.subprocess.Process) -> None:
        assert process.stdout is not None and process.stderr is not None
        stderr: deque[str] = deque(maxlen=10)

        async def read_stderr() -> None:
            assert process.stderr is not None
            while line := await process.stderr.readline():
                if text := line.decode(errors="replace").strip():
                    stderr.append(text)

        stderr_task = asyncio.create_task(read_stderr())
        while line := await process.stdout.readline():
            name = line.decode(errors="replace").split(",", 1)[0]
            try:
                index = int(Path(name).stem)
            except ValueError:
                continue
            if process is not self._process:
                continue
            self._ready.add(index)
            self._next = index + 1
            if event := self._waiters.pop(index, None):
                event.set()
            self._throttle()
        code = await process.wait()
        await stderr_task
        if process is not self._process:
            return
        if code:
            self._error = "ffmpeg failed: " + ("; ".join(stderr) or f"exit code {code}")
            log.warning("Segmenting %s: %s", self.source.path.name, self._error)
        self._process = None
        self._wake_all()

    def _wake_all(self) -> None:
        waiters, self._waiters = self._waiters, {}
        for event in waiters.values():
            event.set()

    async def _stop_process(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                # SIGKILL, not SIGTERM: ffmpeg would finalize and list the
                # half-written segment as complete.
                process.kill()
            await process.wait()
        self._paused = False
        self._wake_all()

    async def close(self) -> None:
        self._closed = True
        await self._stop_process()
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await asyncio.to_thread(shutil.rmtree, self.directory, True)
