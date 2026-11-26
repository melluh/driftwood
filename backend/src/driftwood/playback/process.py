"""Running ffmpeg and ffprobe on files nobody vouches for.

Media files, their subtitles and their metadata come from torrents, so every run
parses hostile input. To keep a bug in one of ffmpeg's parsers from reaching far:

- Inputs are local files only (`-protocol_whitelist file`), read with the demuxer
  ffprobe recognised them as and only the decoders playback needs (`input_args`).
  ffprobe itself can't be held to a decoder list (it opens one for every stream and
  fails on any it may not use), so it only gets the protocol and demuxer lists.
- Children start with a bare environment (no secrets passed in as variables), no
  core dumps, and caps on the memory they use and the size of any file they write.

Segmenting runs are paused with SIGSTOP while the player has enough buffered.
If the server dies without stopping them (a crash, SIGKILL, an OOM kill) a
paused orphan would never run again, nor exit, and keeps its files open. On
Linux the kernel kills the child when its parent goes away.
"""

import asyncio
import ctypes
import os
import signal
import sys
from collections.abc import Callable
from pathlib import Path

from driftwood.playback.errors import PlaybackError

_PR_SET_PDEATHSIG = 1
_BACKGROUND_NICENESS = 10
_MEMORY_LIMIT = 4 * 1024**3
"""Bytes of heap and anonymous memory: a 4K HEVC decode stays well under a gigabyte."""
_FILE_SIZE_LIMIT = 4 * 1024**3
"""Largest file a child may write: far above any segment, sheet or subtitle."""

DEMUXERS = ("matroska", "mov")
"""Formats playback reads (`mov` is ffmpeg's MP4 demuxer)."""
VIDEO_DECODERS = ("h264", "hevc")
"""The video codecs browsers can play without re-encoding (see `policy`)."""
AUDIO_DECODERS: dict[str, tuple[str, ...]] = {
    "aac": ("aac", "aac_fixed"),
    "aac_latm": ("aac_latm",),
    "ac3": ("ac3", "ac3_fixed"),
    "eac3": ("eac3",),
    "dts": ("dca",),
    "truehd": ("truehd",),
    "mlp": ("mlp",),
    "flac": ("flac",),
    "opus": ("opus",),
    "vorbis": ("vorbis",),
    "mp3": ("mp3float", "mp3"),
    "mp2": ("mp2float", "mp2"),
    "alac": ("alac",),
    **{
        pcm: (pcm,)
        for pcm in (
            "pcm_s16le",
            "pcm_s24le",
            "pcm_s32le",
            "pcm_s16be",
            "pcm_s24be",
            "pcm_bluray",
            "pcm_dvd",
        )
    },
}
"""Audio codecs (as ffprobe names them) that can be played, and their ffmpeg decoders."""
SUBTITLE_DECODERS = ("subrip", "srt", "ass", "ssa", "webvtt", "mov_text", "text")
DECODERS = ",".join(
    [
        *VIDEO_DECODERS,
        *(decoder for decoders in AUDIO_DECODERS.values() for decoder in decoders),
        *SUBTITLE_DECODERS,
    ]
)


def input_args(path: Path, demuxer: str) -> list[str]:
    """ffmpeg options opening `path` as a local file, with `demuxer` and only `DECODERS`."""
    return [
        *("-protocol_whitelist", "file"),
        *("-codec_whitelist", DECODERS),
        *("-f", demuxer),
        *("-i", str(path)),
    ]


def _environment() -> dict[str, str]:
    return {"PATH": os.environ.get("PATH", os.defpath)}


def _limit(resource_module, kind: int, value: int) -> tuple[int, int]:
    """`value`, or less where the hard limit is already lower."""
    _soft, hard = resource_module.getrlimit(kind)
    if hard != resource_module.RLIM_INFINITY:
        value = min(value, hard)
    return value, value


def _child_setup(niceness: int = 0) -> Callable[[], None] | None:
    if sys.platform != "linux":
        return None
    import resource

    try:
        # Looked up here, not in the forked child, which should do as little as possible.
        prctl = ctypes.CDLL(None, use_errno=True).prctl
    except (OSError, AttributeError):
        prctl = None
    limits = [
        (resource.RLIMIT_CORE, (0, 0)),
        (resource.RLIMIT_DATA, _limit(resource, resource.RLIMIT_DATA, _MEMORY_LIMIT)),
        (resource.RLIMIT_FSIZE, _limit(resource, resource.RLIMIT_FSIZE, _FILE_SIZE_LIMIT)),
    ]

    def setup() -> None:
        if prctl is not None:
            prctl(_PR_SET_PDEATHSIG, signal.SIGKILL)
        for kind, value in limits:
            resource.setrlimit(kind, value)
        if niceness:
            os.nice(niceness)

    return setup


_SETUP = _child_setup()
_BACKGROUND_SETUP = _child_setup(_BACKGROUND_NICENESS)


async def spawn(
    args: list[str],
    *,
    stdout: int = asyncio.subprocess.DEVNULL,
    stderr: int = asyncio.subprocess.PIPE,
    background: bool = False,
) -> asyncio.subprocess.Process:
    """Start ffmpeg or ffprobe (`args[0]`) under the limits above.

    `background` is for work nobody waits on directly: it yields the CPU to playback."""
    setup = _BACKGROUND_SETUP if background else _SETUP
    try:
        return await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            env=_environment(),
            **({"preexec_fn": setup} if setup else {}),
        )
    except OSError as exc:
        raise PlaybackError(503, f"Could not run {args[0]}: {exc}") from exc
