"""
Builds the on-disk title index from TMDB's daily ID exports.

Ported from MediaManager's `titleIndex/download.py`, with one deliberate
difference: every (non-adult) title is kept, not just the most popular ones.
Driftwood has no separate "real" search step, so obscure titles must be
findable through the index itself (see `driftwood.titles.index`).
"""

import asyncio
import gzip
import json
import logging
import tempfile
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from pathlib import Path
from typing import IO

import httpx

from driftwood.media.schemas import MediaType

log = logging.getLogger(__name__)

EXPORT_BASE_URL = "https://files.tmdb.org/p/exports"
INDEX_FILENAME = "title_index.ndjson.gz"

_EXPORT_KIND: dict[MediaType, str] = {
    MediaType.movie: "movie_ids",
    MediaType.tv: "tv_series_ids",
}
_TITLE_FIELD: dict[MediaType, str] = {
    MediaType.movie: "original_title",
    MediaType.tv: "original_name",
}


@dataclass(frozen=True, slots=True)
class RawEntry:
    id: int
    title: str
    popularity: float
    media_type: MediaType


def index_path(directory: Path) -> Path:
    return directory / INDEX_FILENAME


def parse_export_stream(media_type: MediaType, gzip_stream: IO[bytes]) -> Iterator[RawEntry]:
    """
    Parses one gzip-compressed daily-export NDJSON stream, skipping adult
    movies and any line that fails to parse or lacks the fields we need.
    """
    title_field = _TITLE_FIELD[media_type]
    with gzip.GzipFile(fileobj=gzip_stream) as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("adult"):
                continue
            entry_id = row.get("id")
            title = row.get(title_field)
            if entry_id is None or not title:
                continue
            yield RawEntry(
                id=int(entry_id),
                title=title,
                popularity=float(row.get("popularity") or 0.0),
                media_type=media_type,
            )


def _merge_entries(raw_paths: dict[MediaType, Path]) -> list[RawEntry]:
    """All entries from every export, sorted by popularity descending."""
    entries: list[RawEntry] = []
    for media_type, path in raw_paths.items():
        with path.open("rb") as fh:
            entries.extend(parse_export_stream(media_type, fh))
    entries.sort(key=lambda entry: entry.popularity, reverse=True)
    return entries


def _write_index_file(entries: list[RawEntry], path: Path) -> None:
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=6) as fh:
        for entry in entries:
            record = {
                "id": entry.id,
                "t": entry.title,
                "p": entry.popularity,
                "m": entry.media_type.value,
            }
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _fetch_export_file(client: httpx.Client, media_type: MediaType, dest_path: Path) -> None:
    """
    Downloads today's export for `media_type` (a static, unauthenticated file).
    Falls back to yesterday's once, since TMDB's publish time can slip.
    """
    kind = _EXPORT_KIND[media_type]
    today = datetime.now(UTC).date()
    for day_offset in (0, 1):
        date = today - timedelta(days=day_offset)
        url = f"{EXPORT_BASE_URL}/{kind}_{date:%m_%d_%Y}.json.gz"
        with client.stream("GET", url, timeout=120) as response:
            if response.status_code in (HTTPStatus.NOT_FOUND, HTTPStatus.FORBIDDEN):
                continue
            response.raise_for_status()
            with dest_path.open("wb") as fh:
                for chunk in response.iter_bytes():
                    fh.write(chunk)
            return
    msg = f"TMDB daily export for {kind} not found (tried today and yesterday)"
    raise RuntimeError(msg)


def _refresh_sync(directory: Path) -> bool:
    directory.mkdir(parents=True, exist_ok=True)
    final_path = index_path(directory)
    tmp_path = directory / f"{INDEX_FILENAME}.tmp"

    with tempfile.TemporaryDirectory(dir=directory) as scratch_dir:
        raw_paths = {
            media_type: Path(scratch_dir) / f"{kind}.json.gz"
            for media_type, kind in _EXPORT_KIND.items()
        }
        try:
            with httpx.Client(follow_redirects=True) as client:
                for media_type, dest_path in raw_paths.items():
                    _fetch_export_file(client, media_type, dest_path)
        except (httpx.HTTPError, RuntimeError):
            log.exception("Failed to download TMDB daily export; keeping existing title index")
            return False

        try:
            entries = _merge_entries(raw_paths)
            _write_index_file(entries, tmp_path)
        except Exception:
            log.exception("Failed to build TMDB title index; keeping existing index")
            tmp_path.unlink(missing_ok=True)
            return False

    tmp_path.replace(final_path)
    log.info("Refreshed TMDB title index: %d entries", len(entries))
    return True


async def refresh_title_index(directory: Path) -> bool:
    """
    Downloads the latest exports and atomically swaps a fresh index file into
    place. On failure the previous file is left untouched.

    :return: Whether a new index file was written.
    """
    return await asyncio.to_thread(_refresh_sync, directory)


def is_stale(directory: Path, stale_after_hours: float) -> bool:
    try:
        mtime = index_path(directory).stat().st_mtime
    except FileNotFoundError:
        return True
    return (time.time() - mtime) > stale_after_hours * 3600
