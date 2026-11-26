"""Just enough bencode to read a .torrent's name and infohash."""

import hashlib
from typing import Any


class BencodeError(ValueError):
    pass


def _decode(data: bytes, index: int) -> tuple[Any, int]:
    try:
        token = data[index : index + 1]
        if token == b"i":
            end = data.index(b"e", index)
            return int(data[index + 1 : end]), end + 1
        if token == b"l":
            index += 1
            items = []
            while data[index : index + 1] != b"e":
                item, index = _decode(data, index)
                items.append(item)
            return items, index + 1
        if token == b"d":
            index += 1
            result: dict[bytes, Any] = {}
            while data[index : index + 1] != b"e":
                key, index = _decode(data, index)
                if not isinstance(key, bytes):
                    raise BencodeError("dictionary key is not a string")
                result[key], index = _decode(data, index)
            return result, index + 1
        if token.isdigit():
            colon = data.index(b":", index)
            length = int(data[index:colon])
            start = colon + 1
            if start + length > len(data):
                raise BencodeError("string runs past the end of the data")
            return data[start : start + length], start + length
    except (ValueError, IndexError) as exc:
        if isinstance(exc, BencodeError):
            raise
        raise BencodeError(f"malformed bencode at byte {index}") from exc
    raise BencodeError(f"unexpected byte {token!r} at {index}")


def _info_span(data: bytes) -> tuple[int, int]:
    """Byte range of the raw `info` value: the infohash is taken over its exact bytes."""
    if data[:1] != b"d":
        raise BencodeError("a torrent file is a dictionary")
    index = 1
    while data[index : index + 1] != b"e":
        key, index = _decode(data, index)
        start = index
        _, index = _decode(data, index)
        if key == b"info":
            return start, index
    raise BencodeError("torrent has no info dictionary")


def infohash(torrent: bytes) -> str:
    """
    The id qBittorrent uses for the torrent: the v1 (SHA-1) infohash, or for a
    v2-only torrent its SHA-256 infohash truncated to 40 hex characters.
    """
    start, end = _info_span(torrent)
    info, _ = _decode(torrent, start)
    if not isinstance(info, dict):
        raise BencodeError("info is not a dictionary")
    raw = torrent[start:end]
    v2_only = info.get(b"meta version") == 2 and b"pieces" not in info
    if v2_only:
        return hashlib.sha256(raw).hexdigest()[:40]
    return hashlib.sha1(raw).hexdigest()


def encode(value: Any) -> bytes:
    """Bencode `value` (used by tests to build torrents)."""
    if isinstance(value, int):
        return b"i%de" % value
    if isinstance(value, str):
        value = value.encode()
    if isinstance(value, bytes):
        return b"%d:%s" % (len(value), value)
    if isinstance(value, list):
        return b"l" + b"".join(encode(item) for item in value) + b"e"
    if isinstance(value, dict):
        items = sorted((k.encode() if isinstance(k, str) else k, v) for k, v in value.items())
        return b"d" + b"".join(encode(k) + encode(v) for k, v in items) + b"e"
    raise TypeError(f"can't bencode {type(value).__name__}")
