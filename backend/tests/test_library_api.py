from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from driftwood.config import LibraryRoot, LibrarySettings
from driftwood.db import Database
from driftwood.db.models import MediaFile
from driftwood.library.router import router as library_router
from driftwood.library.service import LibraryService
from tests.test_auth import PUBLIC_URL, FakeIdp, make_app, sign_in


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    database = Database(f"sqlite+aiosqlite:///{tmp_path}/library-api.db")
    await database.migrate()
    yield database
    await database.dispose()


def _client(database: Database, idp: FakeIdp, service: LibraryService) -> httpx.AsyncClient:
    app = make_app(database, idp)
    app.include_router(library_router, prefix="/api")
    app.state.library_service = service
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=PUBLIC_URL)


def _file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"video")


@pytest.fixture
def library(tmp_path: Path, database: Database) -> tuple[LibrarySettings, LibraryService]:
    movies = tmp_path / "movies"
    tv = tmp_path / "tv"
    settings = LibrarySettings(
        roots=[
            LibraryRoot(name="movies", path=movies, kind="movies"),
            LibraryRoot(name="tv", path=tv, kind="tv"),
        ],
        min_size_mb=0,
    )
    return settings, LibraryService(settings, database)


async def test_availability_for_movie(database: Database, library) -> None:
    settings, service = library
    _file(settings.roots[0].path / "Dune [tmdbid-438631]" / "Dune.2160p.HDR.mkv")
    await service.scanner.scan_all()

    idp = FakeIdp()
    async with _client(database, idp, service) as client:
        await sign_in(client, idp)
        response = await client.get("/api/library/movie/438631")

    data = response.json()
    assert data["ready"] is True
    assert data["files"][0]["resolution"] == "2160p"
    assert data["episodes"] == []


async def test_tv_episodes_are_sorted_and_deduplicated(database: Database, library) -> None:
    settings, service = library
    root = settings.roots[1].path
    _file(root / "Show [tmdbid-1399]" / "Season 01" / "Show.S01E02.mkv")
    _file(root / "Show [tmdbid-1399]" / "Season 01" / "Show.S01E01.mkv")
    _file(root / "Show [tmdbid-1399]" / "Season 02" / "Show.S02E01.mkv")
    await service.scanner.scan_all()

    idp = FakeIdp()
    async with _client(database, idp, service) as client:
        await sign_in(client, idp)
        response = await client.get("/api/library/tv/1399")

    episodes = response.json()["episodes"]
    assert episodes == [
        {"season": 1, "episode": 1},
        {"season": 1, "episode": 2},
        {"season": 2, "episode": 1},
    ]


async def test_missing_and_unknown_titles_are_not_ready(database: Database, library) -> None:
    settings, service = library
    _file(settings.roots[0].path / "Dune [tmdbid-603]" / "Dune.mkv")
    await service.scanner.scan_all()
    async with database.sessionmaker() as db:
        row = await db.scalar(select(MediaFile))
        assert row is not None
        row.state = "missing"
        await db.commit()

    idp = FakeIdp()
    async with _client(database, idp, service) as client:
        await sign_in(client, idp)
        missing = await client.get("/api/library/movie/603")
        unknown = await client.get("/api/library/movie/999")

    assert missing.json() == {"ready": False, "files": [], "episodes": []}
    assert unknown.json() == {"ready": False, "files": [], "episodes": []}


async def test_library_routes_require_sign_in_and_scan_returns_202(
    database: Database, library
) -> None:
    _, service = library
    idp = FakeIdp()
    async with _client(database, idp, service) as client:
        assert (await client.get("/api/library/status")).status_code == 401
        await sign_in(client, idp)
        response = await client.post("/api/library/scan")

    assert response.status_code == 202
    assert response.json()["state"] == "scanning"
    await service.shutdown()
