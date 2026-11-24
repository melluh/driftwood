import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from driftwood.config import LibraryRoot, LibrarySettings
from driftwood.db import Database
from driftwood.db.models import MediaFile, utcnow
from driftwood.library.scanner import Scanner


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    database = Database(f"sqlite+aiosqlite:///{tmp_path}/library.db")
    await database.migrate()
    yield database
    await database.dispose()


def _scanner(
    root: Path,
    database: Database,
    *,
    now: list[datetime] | None = None,
    **settings: object,
) -> Scanner:
    return Scanner(
        LibrarySettings(
            roots=[LibraryRoot(name="movies", path=root, kind="movies")],
            min_size_mb=0,
            **settings,
        ),
        database,
        clock=(lambda: now[0]) if now is not None else utcnow,
    )


def _video(path: Path, contents: bytes = b"video") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(contents)
    return path


async def _rows(database: Database) -> list[MediaFile]:
    async with database.sessionmaker() as db:
        return list((await db.scalars(select(MediaFile))).all())


async def test_scan_adds_and_is_idempotent(database: Database, tmp_path: Path) -> None:
    root = tmp_path / "movies"
    _video(root / "Dune [tmdbid-438631]" / "Dune.2021.2160p.mkv")
    scanner = _scanner(root, database)

    first = await scanner.scan_all()
    second = await scanner.scan_all()
    rows = await _rows(database)

    assert (first.added, second.added, second.updated) == (1, 0, 0)
    assert len(rows) == 1
    assert rows[0].attributes["resolution"] == "2160p"


async def test_changed_file_is_reparsed(database: Database, tmp_path: Path) -> None:
    root = tmp_path / "movies"
    video = _video(root / "Dune [tmdbid-438631]" / "Dune.1080p.mkv")
    scanner = _scanner(root, database)
    await scanner.scan_all()
    stat = video.stat()
    video.write_bytes(b"changed")
    os.utime(video, ns=(stat.st_atime_ns, stat.st_mtime_ns + 2_000_000_000))

    report = await scanner.scan_all()

    assert report.updated == 1
    assert (await _rows(database))[0].size == len(b"changed")


async def test_missing_file_returns_and_expires_after_grace(
    database: Database, tmp_path: Path
) -> None:
    root = tmp_path / "movies"
    video = _video(root / "Dune [tmdbid-438631]" / "Dune.mkv")
    _video(root / "Another [tmdbid-2]" / "Another.mkv")
    now = [datetime(2026, 1, 1, tzinfo=UTC)]
    scanner = _scanner(root, database, now=now, missing_grace_days=2)
    await scanner.scan_all()

    original_stat = video.stat()
    video.unlink()
    assert (await scanner.scan_all()).missing == 1
    row = next(row for row in await _rows(database) if row.path.endswith("Dune.mkv"))
    assert row.state == "missing"

    _video(video)
    os.utime(video, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    await scanner.scan_all()
    row = next(row for row in await _rows(database) if row.path.endswith("Dune.mkv"))
    assert row.state == "present"
    assert row.missing_since is None

    video.unlink()
    await scanner.scan_all()
    now[0] += timedelta(days=3)
    assert (await scanner.scan_all()).removed == 1
    assert [row.path for row in await _rows(database)] == ["Another [tmdbid-2]/Another.mkv"]


async def test_ignores_samples_extras_hidden_and_non_video_files(
    database: Database, tmp_path: Path
) -> None:
    root = tmp_path / "movies"
    _video(root / "Title [tmdbid-1]" / "Title.mkv")
    _video(root / "Title [tmdbid-2]" / "Title-sample.mkv")
    _video(root / "Title [tmdbid-3]" / "sample.mkv")
    _video(root / "Title [tmdbid-4]" / "Extras" / "extra.mkv")
    _video(root / ".hidden" / "Title [tmdbid-5].mkv")
    _video(root / "Title [tmdbid-6]" / "image.jpg")

    report = await _scanner(root, database).scan_all()

    assert report.added == 1


async def test_size_filter(database: Database, tmp_path: Path) -> None:
    root = tmp_path / "movies"
    _video(root / "Title [tmdbid-1]" / "Title.mkv", b"tiny")
    scanner = Scanner(
        LibrarySettings(
            roots=[LibraryRoot(name="movies", path=root, kind="movies")],
            min_size_mb=0.00001,
        ),
        database,
    )

    assert (await scanner.scan_all()).added == 0


async def test_unavailable_or_empty_root_does_not_mark_files_missing(
    database: Database, tmp_path: Path
) -> None:
    root = tmp_path / "movies"
    video = _video(root / "Title [tmdbid-1]" / "Title.mkv")
    scanner = _scanner(root, database)
    await scanner.scan_all()

    video.unlink()
    assert (await scanner.scan_all()).missing == 0
    assert (await _rows(database))[0].state == "present"

    root.rename(tmp_path / "offline")
    report = await scanner.scan_all()
    assert report.skipped_roots == ["movies"]
    assert (await _rows(database))[0].state == "present"


async def test_renamed_file_without_tag_is_not_rematched(
    database: Database, tmp_path: Path
) -> None:
    root = tmp_path / "movies"
    original = _video(root / "Title [tmdbid-1].mkv")
    scanner = _scanner(root, database, missing_grace_days=0)
    await scanner.scan_all()

    original.rename(root / "Title.mkv")
    report = await scanner.scan_all()
    assert report.missing == 1
    assert report.unmatched == 1
    assert (await scanner.scan_all()).removed == 1
    assert await _rows(database) == []


async def test_scan_path_does_not_reconcile_outside_subtree(
    database: Database, tmp_path: Path
) -> None:
    root = tmp_path / "movies"
    _video(root / "SeasonA" / "Title [tmdbid-1]" / "one.mkv")
    second = _video(root / "SeasonA" / "Title [tmdbid-2]" / "two.mkv")
    outside = _video(root / "Elsewhere" / "Title [tmdbid-3]" / "three.mkv")
    scanner = _scanner(root, database)
    await scanner.scan_all()

    second.unlink()
    await scanner.scan_path(root / "SeasonA")
    rows = {row.path: row.state for row in await _rows(database)}

    assert rows["SeasonA/Title [tmdbid-2]/two.mkv"] == "missing"
    assert rows["Elsewhere/Title [tmdbid-3]/three.mkv"] == "present"
    assert outside.exists()
