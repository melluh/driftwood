import gzip
import io
import json
from pathlib import Path

from driftwood.media.schemas import MediaType
from driftwood.titles import download
from driftwood.titles.index import TitleIndex


def gz_lines(*rows: object) -> io.BytesIO:
    payload = "\n".join(row if isinstance(row, str) else json.dumps(row) for row in rows)
    return io.BytesIO(gzip.compress(payload.encode()))


def test_parse_skips_adult_malformed_and_incomplete_rows() -> None:
    stream = gz_lines(
        {"id": 1, "original_title": "Ok", "popularity": 1.0},
        {"id": 2, "original_title": "Adult", "adult": True},
        "not json",
        {"id": 3},
    )
    entries = list(download.parse_export_stream(MediaType.movie, stream))
    assert [entry.id for entry in entries] == [1]


def test_index_file_round_trips_sorted_by_popularity(tmp_path: Path) -> None:
    movies = tmp_path / "movies.gz"
    shows = tmp_path / "shows.gz"
    movies.write_bytes(gz_lines({"id": 1, "original_title": "Low", "popularity": 1}).getvalue())
    shows.write_bytes(gz_lines({"id": 2, "original_name": "High", "popularity": 9}).getvalue())

    entries = download._merge_entries({MediaType.movie: movies, MediaType.tv: shows})
    path = tmp_path / download.INDEX_FILENAME
    download._write_index_file(entries, path)

    index = TitleIndex.load(path, head_size=1)
    assert [entry.match.title for entry in index.head] == ["High"]
    assert index.tail.match(0).title == "Low"
    assert index.tail.match(0).media_type is MediaType.movie


def test_failed_download_keeps_existing_index(tmp_path: Path, monkeypatch) -> None:
    existing = download.index_path(tmp_path)
    existing.write_bytes(b"existing")

    def fail(*_args: object) -> None:
        raise RuntimeError("offline")

    monkeypatch.setattr(download, "_fetch_export_file", fail)
    assert download._refresh_sync(tmp_path) is False
    assert existing.read_bytes() == b"existing"
