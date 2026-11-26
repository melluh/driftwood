"""Spawning ffmpeg so it can't outlive the server.

Segmenting runs are paused with SIGSTOP while the player has enough buffered.
If the server dies without stopping them (a crash, SIGKILL, an OOM kill) a
paused orphan would never run again, nor exit, and keeps its files open. On
Linux the kernel kills the child when its parent goes away.
"""

import ctypes
import signal
import sys
from typing import Any

_PR_SET_PDEATHSIG = 1


def _child_options() -> dict[str, Any]:
    if sys.platform != "linux":
        return {}
    try:
        # Looked up here, not in the forked child, which should do as little as possible.
        prctl = ctypes.CDLL(None, use_errno=True).prctl
    except (OSError, AttributeError):
        return {}

    def die_with_parent() -> None:
        prctl(_PR_SET_PDEATHSIG, signal.SIGKILL)

    return {"preexec_fn": die_with_parent}


CHILD_OPTIONS = _child_options()
"""Extra `create_subprocess_exec` arguments for long-running ffmpeg processes."""
