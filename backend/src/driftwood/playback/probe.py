"""What's inside a media file: streams from ffprobe, keyframes from the index."""

import asyncio
import itertools
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from driftwood.playback.errors import PlaybackError
from driftwood.playback.mkv import read_keyframes
from driftwood.playback.process import DEMUXERS, spawn

log = logging.getLogger(__name__)

PROBE_VERSION = 1
# Cues pointing only at every Nth keyframe would make segments this long.
_MAX_INDEXED_GAP = 20.0
# Remuxes have a few dozen streams (anime: a hundred fonts); thousands only make work.
_MAX_STREAMS = 512


@dataclass
class MediaProbe:
    format_name: str
    start_time: float
    duration: float
    streams: list[dict[str, Any]]
    keyframes: list[float] | None = None
    """Keyframe times of the first video stream; filled in only for HLS playback."""

    def of_type(self, codec_type: str) -> list[dict[str, Any]]:
        return [stream for stream in self.streams if stream.get("codec_type") == codec_type]

    @property
    def demuxer(self) -> str | None:
        """The demuxer to read the file with (one of `DEMUXERS`), or None for another format."""
        return next((name for name in self.format_name.split(",") if name in DEMUXERS), None)

    @property
    def video(self) -> dict[str, Any] | None:
        return next(
            (
                stream
                for stream in self.of_type("video")
                if not stream.get("disposition", {}).get("attached_pic")
            ),
            None,
        )

    def to_json(self, *, size: int, mtime_ns: int) -> dict[str, Any]:
        return {
            "version": PROBE_VERSION,
            "size": size,
            "mtime_ns": mtime_ns,
            "format_name": self.format_name,
            "start_time": self.start_time,
            "duration": self.duration,
            "streams": self.streams,
            "keyframes": self.keyframes,
        }

    @classmethod
    def from_json(cls, data: object, *, size: int, mtime_ns: int) -> "MediaProbe | None":
        """The cached probe, or None when it's missing or describes another version of the file."""
        if not isinstance(data, dict):
            return None
        if (
            data.get("version") != PROBE_VERSION
            or data.get("size") != size
            or data.get("mtime_ns") != mtime_ns
        ):
            return None
        try:
            return cls(
                format_name=str(data["format_name"]),
                start_time=float(data["start_time"]),
                duration=float(data["duration"]),
                streams=list(data["streams"]),
                keyframes=data.get("keyframes"),
            )
        except (KeyError, TypeError, ValueError):
            return None


async def _run(executable: str, args: list[str], timeout: float) -> bytes:
    process = await spawn([executable, *args], stdout=asyncio.subprocess.PIPE)
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except BaseException:
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise
    if process.returncode:
        detail = stderr.decode(errors="replace").strip().splitlines()
        raise PlaybackError(422, f"Could not read the media file: {detail[-1] if detail else ''}")
    return stdout


async def probe_file(ffprobe: str, path: Path) -> MediaProbe:
    try:
        stdout = await _run(
            ffprobe,
            [
                *("-v", "error"),
                *("-protocol_whitelist", "file"),
                # Anything else is refused before a demuxer chosen by content parses it.
                *("-format_whitelist", ",".join(DEMUXERS)),
                *("-show_format", "-show_streams", "-of", "json"),
                str(path),
            ],
            timeout=60,
        )
    except TimeoutError:
        raise PlaybackError(504, "Timed out while reading the media file.") from None
    try:
        result = json.loads(stdout)
        streams = [stream for stream in result["streams"] if isinstance(stream, dict)]
        media_format = result["format"]
        duration = float(media_format.get("duration") or 0)
        start_time = float(media_format.get("start_time") or 0)
        format_name = str(media_format.get("format_name") or "")
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        raise PlaybackError(422, "ffprobe returned unreadable stream information.") from None
    if duration <= 0:
        raise PlaybackError(422, "The media file has no known duration.")
    if len(streams) > _MAX_STREAMS:
        raise PlaybackError(422, f"The media file has {len(streams)} streams; that's too many.")
    return MediaProbe(format_name, start_time, duration, streams)


def _usable(keyframes: list[float] | None, probe: MediaProbe) -> bool:
    if not keyframes:
        return False
    end = probe.start_time + probe.duration
    points = [probe.start_time, *keyframes, end]
    return keyframes[0] - probe.start_time < 5 and all(
        later - earlier <= _MAX_INDEXED_GAP for earlier, later in itertools.pairwise(points)
    )


async def find_keyframes(ffprobe: str, path: Path, probe: MediaProbe) -> list[float]:
    """Keyframe times of the first video stream, from the Matroska index when possible.

    Falling back to listing every packet reads the whole file, which can take a
    minute for a large remux; the result is cached with the file's probe.
    """
    video = probe.video
    if video is None:
        raise PlaybackError(415, "The file has no video stream.")
    if probe.demuxer is None:
        raise PlaybackError(415, "Only Matroska and MP4 files can be played.")
    if probe.demuxer == "matroska":
        keyframes = await asyncio.to_thread(read_keyframes, path)
        if _usable(keyframes, probe):
            assert keyframes is not None
            return keyframes
        log.info("Matroska cues of %s are unusable; scanning packets", path.name)

    try:
        stdout = await _run(
            ffprobe,
            [
                "-v",
                "error",
                *("-protocol_whitelist", "file"),
                *("-f", probe.demuxer),
                "-select_streams",
                str(video["index"]),
                "-show_entries",
                "packet=pts_time,flags",
                "-of",
                "csv=p=0",
                str(path),
            ],
            timeout=30 * 60,
        )
    except TimeoutError:
        raise PlaybackError(504, "Timed out while indexing the media file.") from None
    keyframes: set[float] = set()
    for line in stdout.decode(errors="replace").splitlines():
        time, _, flags = line.partition(",")
        if "K" in flags:
            try:
                keyframes.add(round(float(time), 6))
            except ValueError:
                continue
    if not keyframes:
        raise PlaybackError(422, "The video stream has no keyframes ffmpeg can seek to.")
    return sorted(keyframes)
