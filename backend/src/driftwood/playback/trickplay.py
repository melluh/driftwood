"""Seek-bar preview thumbnails that Jellyfin saved next to a video.

With "Save trickplay images next to media" on, Jellyfin writes
`<video stem>.trickplay/<width> - <columns>x<rows>/<n>.jpg`: sheets numbered from
0, each a full `columns x rows` grid of `width`-pixel-wide thumbnails (the last
sheet padded out), one thumbnail every `interval` seconds from the start.

The interval lives in Jellyfin's database rather than on disk, so it's assumed
(Jellyfin's default is 10 s) and checked against the number of sheets the
duration needs. Thumbnails at the wrong times are worse than none.

Driftwood makes the same files itself for videos that have none (see
`trickplay_generator`); a layout directory it's still filling holds a
`MARKER` file and is skipped here until the last sheet is in.
"""

import math
import re
import struct
from dataclasses import dataclass
from pathlib import Path

from driftwood.playback.paths import within

_LAYOUT = re.compile(r"^(\d+) - (\d+)x(\d+)$")
MARKER = ".driftwood-partial"
"""In a layout directory whose sheets are still being made."""
_PREFERRED_WIDTH = 320
# Start-of-frame markers: baseline, extended, progressive, lossless (and their
# arithmetic-coded variants). 0xC4, 0xC8 and 0xCC are other segments.
_SOF_MARKERS = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}


@dataclass(frozen=True)
class Trickplay:
    directory: Path
    sheets: int
    columns: int
    rows: int
    width: int
    """Of one thumbnail, in pixels."""
    height: int
    interval: float
    """Seconds between thumbnails."""
    count: int
    """Thumbnails covering the video, across all sheets."""

    def sheet(self, index: int) -> Path | None:
        if not 0 <= index < self.sheets:
            return None
        path = self.directory / f"{index}.jpg"
        return path if path.is_file() and within(path, self.directory) else None


def jpeg_size(path: Path) -> tuple[int, int] | None:
    """(width, height) from a JPEG's frame header, without decoding it."""
    try:
        with path.open("rb") as file:
            if file.read(2) != b"\xff\xd8":
                return None
            while True:
                marker = file.read(2)
                if len(marker) < 2 or marker[0] != 0xFF:
                    return None
                if marker[1] == 0xFF:  # fill byte before the real marker
                    file.seek(-1, 1)
                    continue
                if 0xD0 <= marker[1] <= 0xD9 or marker[1] == 0x01:
                    continue  # standalone markers carry no length
                length_bytes = file.read(2)
                if len(length_bytes) < 2:
                    return None
                (length,) = struct.unpack(">H", length_bytes)
                if marker[1] in _SOF_MARKERS:
                    header = file.read(5)
                    if len(header) < 5:
                        return None
                    height, width = struct.unpack(">HH", header[1:5])
                    return (width, height) if width and height else None
                file.seek(length - 2, 1)
    except OSError:
        return None


def layout_directory(video: Path, width: int, columns: int, rows: int) -> Path:
    """Where Jellyfin keeps `width`-pixel thumbnails of `video`, `columns` x `rows` a sheet."""
    return video.with_name(f"{video.stem}.trickplay") / f"{width} - {columns}x{rows}"


def thumbnail_count(duration: float, interval: float) -> int:
    """Thumbnails covering a video: one at 0 s, then one every `interval` seconds."""
    return max(1, math.ceil(duration / interval))


def _sheet_count(directory: Path) -> int:
    """How many sheets there are, counting 0.jpg, 1.jpg, ... until one is missing."""
    count = 0
    while (sheet := directory / f"{count}.jpg").is_file() and within(sheet, directory):
        count += 1
    return count


def find_trickplay(video: Path, duration: float, interval: float) -> Trickplay | None:
    """The video's trickplay thumbnails, or None when there are none that fit it."""
    if duration <= 0 or interval <= 0:
        return None
    root = video.with_name(f"{video.stem}.trickplay")
    try:
        layouts = [
            (int(match[1]), int(match[2]), int(match[3]), entry)
            for entry in root.iterdir()
            if entry.is_dir()
            and (match := _LAYOUT.match(entry.name))
            and within(entry, video.parent)
        ]
    except OSError:
        return None
    # Several widths can sit side by side; the one nearest Jellyfin's default suits a seek bar.
    layouts.sort(key=lambda layout: abs(layout[0] - _PREFERRED_WIDTH))
    for width, columns, rows, directory in layouts:
        if not (width and columns and rows) or (directory / MARKER).exists():
            continue
        sheets = _sheet_count(directory)
        thumbnails = thumbnail_count(duration, interval)
        expected = math.ceil(thumbnails / (columns * rows))
        # A rounding difference at the very end may add or drop one sheet; a
        # different interval (or a different cut of the video) shifts it by more.
        if not sheets or abs(sheets - expected) > 1:
            continue
        size = jpeg_size(directory / "0.jpg")
        if size is None or size[0] < columns or size[1] < rows:
            continue
        return Trickplay(
            directory=directory,
            sheets=sheets,
            columns=columns,
            rows=rows,
            width=size[0] // columns,
            height=size[1] // rows,
            interval=interval,
            count=min(thumbnails, sheets * columns * rows),
        )
    return None
