"""Video keyframe times from a Matroska file's Cues index.

Muxers (mkvmerge, ffmpeg) write a cue point for every video keyframe, so the
index gives exact segment boundaries after reading a few small elements near
the start or end of the file, without demuxing the clusters.
"""

import logging
from pathlib import Path

log = logging.getLogger(__name__)

_EBML = 0x1A45DFA3
_SEGMENT = 0x18538067
_SEEK_HEAD = 0x114D9B74
_SEEK = 0x4DBB
_SEEK_ID = 0x53AB
_SEEK_POSITION = 0x53AC
_INFO = 0x1549A966
_TIMESTAMP_SCALE = 0x2AD7B1
_TRACKS = 0x1654AE6B
_TRACK_ENTRY = 0xAE
_TRACK_NUMBER = 0xD7
_TRACK_TYPE = 0x83
_CUES = 0x1C53BB6B
_CUE_POINT = 0xBB
_CUE_TIME = 0xB3
_CUE_TRACK_POSITIONS = 0xB7
_CUE_TRACK = 0xF7
_CLUSTER = 0x1F43B675

_VIDEO_TRACK = 1
_MAX_ELEMENT = 64 * 1024 * 1024
_MAX_TOP_LEVEL = 200_000


class _Invalid(Exception):
    pass


def _vint_length(first: int) -> int:
    for length in range(1, 9):
        if first & (0x80 >> (length - 1)):
            return length
    raise _Invalid("invalid EBML variable-length integer")


def _parse_header(data: bytes, offset: int) -> tuple[int, int | None, int]:
    """(element id, payload size or None when unknown, payload offset)."""
    if offset >= len(data):
        raise _Invalid("truncated element")
    id_length = _vint_length(data[offset])
    if id_length > 4:
        raise _Invalid("element id too long")
    element_id = int.from_bytes(data[offset : offset + id_length])
    offset += id_length
    if offset >= len(data):
        raise _Invalid("truncated element")
    size_length = _vint_length(data[offset])
    raw = data[offset : offset + size_length]
    if len(raw) < size_length:
        raise _Invalid("truncated element")
    size = raw[0] & (0xFF >> size_length)
    for byte in raw[1:]:
        size = (size << 8) | byte
    unknown = size == (1 << (7 * size_length)) - 1
    return element_id, None if unknown else size, offset + size_length


def _children(data: bytes) -> list[tuple[int, bytes]]:
    offset = 0
    children = []
    while offset < len(data):
        element_id, size, start = _parse_header(data, offset)
        if size is None:
            raise _Invalid("unknown-size child element")
        children.append((element_id, data[start : start + size]))
        offset = start + size
    return children


def _uint(data: bytes) -> int:
    return int.from_bytes(data) if data else 0


def _read_header(file, position: int) -> tuple[int, int | None, int]:
    file.seek(position)
    head = file.read(12)
    element_id, size, start = _parse_header(head, 0)
    return element_id, size, position + start


def _read_payload(file, position: int, expected: int) -> bytes:
    element_id, size, start = _read_header(file, position)
    if element_id != expected or size is None or size > _MAX_ELEMENT:
        raise _Invalid(f"expected element {expected:#x} at {position}")
    file.seek(start)
    data = file.read(size)
    if len(data) < size:
        raise _Invalid("truncated element")
    return data


def _locate(file, file_size: int) -> tuple[dict[int, int], int]:
    """Absolute offsets of Info, Tracks and Cues, plus the segment data offset."""
    element_id, size, start = _read_header(file, 0)
    if element_id != _EBML or size is None:
        raise _Invalid("not an EBML file")
    element_id, size, segment_start = _read_header(file, start + size)
    if element_id != _SEGMENT:
        raise _Invalid("no Matroska segment")
    segment_end = file_size if size is None else min(file_size, segment_start + size)

    wanted = {_INFO, _TRACKS, _CUES}
    found: dict[int, int] = {}
    position = segment_start
    for _ in range(_MAX_TOP_LEVEL):
        if position >= segment_end or wanted <= found.keys():
            break
        element_id, size, payload = _read_header(file, position)
        if element_id in wanted:
            found.setdefault(element_id, position)
        elif element_id == _SEEK_HEAD and size is not None and size <= _MAX_ELEMENT:
            file.seek(payload)
            for child_id, seek in _children(file.read(size)):
                if child_id != _SEEK:
                    continue
                fields = dict(_children(seek))
                target = _uint(fields.get(_SEEK_ID, b""))
                if target in wanted and _SEEK_POSITION in fields:
                    found.setdefault(target, segment_start + _uint(fields[_SEEK_POSITION]))
        if size is None:
            # A live-muxed cluster of unknown size: nothing after it can be skipped to.
            break
        position = payload + size
    return found, segment_start


def read_keyframes(path: Path) -> list[float] | None:
    """Keyframe times (seconds) of the first video track, or None without a usable index."""
    try:
        with path.open("rb") as file:
            file_size = path.stat().st_size
            found, _segment_start = _locate(file, file_size)
            if _TRACKS not in found or _CUES not in found:
                return None

            scale = 1_000_000
            if _INFO in found:
                for element_id, value in _children(_read_payload(file, found[_INFO], _INFO)):
                    if element_id == _TIMESTAMP_SCALE:
                        scale = _uint(value) or scale

            video_track = None
            for element_id, entry in _children(_read_payload(file, found[_TRACKS], _TRACKS)):
                if element_id != _TRACK_ENTRY:
                    continue
                fields = dict(_children(entry))
                if _uint(fields.get(_TRACK_TYPE, b"")) == _VIDEO_TRACK:
                    video_track = _uint(fields.get(_TRACK_NUMBER, b""))
                    break
            if video_track is None:
                return None

            times: set[int] = set()
            for element_id, point in _children(_read_payload(file, found[_CUES], _CUES)):
                if element_id != _CUE_POINT:
                    continue
                cue_time = None
                tracks = []
                for child_id, value in _children(point):
                    if child_id == _CUE_TIME:
                        cue_time = _uint(value)
                    elif child_id == _CUE_TRACK_POSITIONS:
                        tracks.extend(
                            _uint(track)
                            for track_id, track in _children(value)
                            if track_id == _CUE_TRACK
                        )
                if cue_time is not None and video_track in tracks:
                    times.add(cue_time)
    except (OSError, _Invalid, ValueError) as exc:
        log.debug("No Matroska cues for %s: %s", path, exc)
        return None
    return [time * scale / 1_000_000_000 for time in sorted(times)] or None
