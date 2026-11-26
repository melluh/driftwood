"""Spawning ffmpeg so it can't outlive the server.

Segmenting runs are paused with SIGSTOP while the player has enough buffered.
If the server dies without stopping them (a crash, SIGKILL, an OOM kill) a
paused orphan would never run again, nor exit, and keeps its files open. On
Linux the kernel kills the child when its parent goes away.
"""

import ctypes
import os
import signal
import sys
from typing import Any

_PR_SET_PDEATHSIG = 1
_BACKGROUND_NICENESS = 10


def _child_options(niceness: int = 0) -> dict[str, Any]:
    if sys.platform != "linux":
        return {}
    try:
        # Looked up here, not in the forked child, which should do as little as possible.
        prctl = ctypes.CDLL(None, use_errno=True).prctl
    except (OSError, AttributeError):
        prctl = None
    if prctl is None and not niceness:
        return {}

    def setup() -> None:
        if prctl is not None:
            prctl(_PR_SET_PDEATHSIG, signal.SIGKILL)
        if niceness:
            os.nice(niceness)

    return {"preexec_fn": setup}


CHILD_OPTIONS = _child_options()
"""Extra `create_subprocess_exec` arguments for long-running ffmpeg processes."""

BACKGROUND_CHILD_OPTIONS = _child_options(_BACKGROUND_NICENESS)
"""The same, for work nobody waits on directly: it yields the CPU to playback."""
