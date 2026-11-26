"""Keeping files found next to a video from leading anywhere else."""

from pathlib import Path


def within(path: Path, directory: Path) -> bool:
    """Whether `path` exists and, following any symlinks, lies inside `directory`.

    Subtitles and thumbnails are found by name next to a video and then served:
    a symlink among them must not hand out a file from elsewhere on the machine."""
    try:
        return path.resolve(strict=True).is_relative_to(directory.resolve(strict=True))
    except (OSError, RuntimeError):  # missing, unreadable, or a symlink loop
        return False
