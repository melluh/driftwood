"""Running ffmpeg and ffprobe on files nobody vouches for.

Media files, their subtitles and their metadata come from torrents, so every run
parses hostile input. To keep a bug in one of ffmpeg's parsers from reaching far:

- Inputs are local files only (`-protocol_whitelist file`), read with the demuxer
  ffprobe recognised them as and only the decoders playback needs (`input_args`).
  ffprobe itself can't be held to a decoder list (it opens one for every stream and
  fails on any it may not use), so it only gets the protocol and demuxer lists.
- Children start with a bare environment (no secrets passed in as variables), no
  core dumps, and caps on the memory they use and the size of any file they write.
- Where bubblewrap works, each run is sandboxed: no network, the system read-only,
  and of everything else only the files it reads (read-only) and the directory it
  writes to. A parser bug then can't reach the database, the secrets, the library,
  or anything on the network. With `sandbox="auto"` (the default), a host where
  bwrap can't run ffmpeg runs it unsandboxed, with a warning.

Every child leads its own process group, which the sandbox's processes share, so
signals go to the group (`send`, `kill`).

Segmenting runs are paused with SIGSTOP while the player has enough buffered.
If the server dies without stopping them (a crash, SIGKILL, an OOM kill) a
paused orphan would never run again, nor exit, and keeps its files open. On
Linux the kernel kills the child when its parent goes away.
"""

import asyncio
import contextlib
import ctypes
import logging
import os
import shutil
import signal
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Literal

from driftwood.playback.errors import PlaybackError

log = logging.getLogger(__name__)

type SandboxMode = Literal["auto", "bwrap", "off"]

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

# The system, read-only: enough for a distribution's ffmpeg and the libraries it links.
_SYSTEM_DIRECTORIES = ("/bin", "/sbin", "/lib", "/lib32", "/lib64", "/libx32")
_SYSTEM_FILES = ("/etc/ld.so.cache", "/etc/ld.so.conf", "/etc/ld.so.conf.d", "/etc/alternatives")
_SANDBOX_CHECK_SECONDS = 30


class _Sandbox:
    def __init__(self) -> None:
        self.mode: SandboxMode = "auto"
        self.problems: dict[str, str | None] = {}
        """Per executable: None when it runs sandboxed, else why it can't. (Two runs
        starting at once may both check; that only costs a second `-version`.)"""


_sandbox = _Sandbox()


def configure_sandbox(mode: SandboxMode) -> None:
    """`auto` sandboxes where bwrap can, `bwrap` refuses to run otherwise, `off` never does."""
    global _sandbox
    _sandbox = _Sandbox()
    _sandbox.mode = mode


def _resolve(executable: str) -> str | None:
    found = shutil.which(executable, path=_environment()["PATH"])
    return os.path.realpath(found) if found else None


def _sandbox_args(
    bwrap: str, executable: str, reads: Iterable[Path], writes: Iterable[Path]
) -> list[str]:
    args = [bwrap, "--unshare-all", "--die-with-parent", "--cap-drop", "ALL"]
    args += ["--ro-bind", "/usr", "/usr"]
    for directory in _SYSTEM_DIRECTORIES:
        if os.path.islink(directory):
            args += ["--symlink", os.readlink(directory), directory]
        elif os.path.isdir(directory):
            args += ["--ro-bind", directory, directory]
    for path in _SYSTEM_FILES:
        args += ["--ro-bind-try", path, path]
    if not executable.startswith("/usr/"):
        # An ffmpeg of its own (a static build, jellyfin-ffmpeg in /opt, ...).
        home = os.path.dirname(executable)
        args += ["--ro-bind", home, home]
    args += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
    for directory in writes:
        path = os.path.abspath(directory)
        args += ["--bind", path, path]
    for file in reads:
        path = os.path.abspath(file)
        args += ["--ro-bind", path, path]
    return [*args, "--chdir", "/", "--", executable]


async def _check(bwrap: str, executable: str) -> str | None:
    """Why `executable` can't run in the sandbox, or None when it can."""
    try:
        process = await asyncio.create_subprocess_exec(
            *_sandbox_args(bwrap, executable, (), ()),
            "-version",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            env=_environment(),
        )
    except OSError as exc:
        return str(exc)
    try:
        _, stderr = await asyncio.wait_for(process.communicate(), _SANDBOX_CHECK_SECONDS)
    except TimeoutError:
        process.kill()
        await process.wait()
        return "timed out"
    if process.returncode:
        lines = stderr.decode(errors="replace").strip().splitlines()
        return lines[-1] if lines else f"exit code {process.returncode}"
    return None


async def sandbox_command(
    args: list[str], reads: Iterable[Path] = (), writes: Iterable[Path] = ()
) -> list[str]:
    """`args` wrapped in the sandbox, or as they are where it's off or can't work."""
    sandbox = _sandbox
    if sandbox.mode == "off":
        return args
    bwrap = _resolve("bwrap")
    executable = _resolve(args[0])
    if bwrap is None or executable is None:
        problem = "bwrap isn't installed" if bwrap is None else f"{args[0]} isn't installed"
    else:
        if executable not in sandbox.problems:
            problem = await _check(bwrap, executable)
            sandbox.problems[executable] = problem
            if problem is None:
                log.info("Running %s sandboxed with bwrap", executable)
            elif sandbox.mode == "auto":
                log.warning(
                    "%s can't run sandboxed (%s); running it unsandboxed. Fix bwrap or set "
                    "DRIFTWOOD_PLAYBACK__SANDBOX=off",
                    executable,
                    problem,
                )
        problem = sandbox.problems[executable]
        if problem is None:
            assert executable is not None and bwrap is not None
            return [*_sandbox_args(bwrap, executable, reads, writes), *args[1:]]
    if sandbox.mode == "bwrap":
        raise PlaybackError(503, f"Could not sandbox {args[0]}: {problem}")
    return args


async def spawn(
    args: list[str],
    *,
    reads: Iterable[Path] = (),
    writes: Iterable[Path] = (),
    stdout: int = asyncio.subprocess.DEVNULL,
    stderr: int = asyncio.subprocess.PIPE,
    background: bool = False,
) -> asyncio.subprocess.Process:
    """Start ffmpeg or ffprobe (`args[0]`) under the limits above.

    Sandboxed, it sees only the files in `reads` and may only write in the
    (existing) directories in `writes`. `background` is for work nobody waits on
    directly: it yields the CPU to playback."""
    reads, writes = list(reads), list(writes)
    command = await sandbox_command(args, reads, writes)
    setup = _BACKGROUND_SETUP if background else _SETUP
    try:
        return await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            env=_environment(),
            # Its own process group (for `send`), and no controlling terminal to write to.
            start_new_session=True,
            **({"preexec_fn": setup} if setup else {}),
        )
    except OSError as exc:
        raise PlaybackError(503, f"Could not run {args[0]}: {exc}") from exc


def send(process: asyncio.subprocess.Process, signal_number: int) -> None:
    """Signal the child and everything it started (in the sandbox: ffmpeg itself)."""
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal_number)


async def kill(process: asyncio.subprocess.Process) -> None:
    """Kill the child's whole group, and wait for the child."""
    if process.returncode is None:
        send(process, signal.SIGKILL)
    await process.wait()
