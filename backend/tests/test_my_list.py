from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from driftwood.db import Database
from driftwood.media.schemas import MediaType
from driftwood.my_list.router import router as my_list_router
from driftwood.my_list.service import MyListService
from driftwood.tmdb.client import TmdbNotFoundError
from tests.test_auth import PUBLIC_URL, FakeIdp, make_app, sign_in

TITLES: dict[tuple[MediaType, int], dict[str, Any]] = {
    (MediaType.movie, 603): {
        "id": 603,
        "title": "The Matrix",
        "release_date": "1999-03-30",
        "poster_path": "/matrix.jpg",
        "backdrop_path": "/matrix-bd.jpg",
        "overview": "Neo wakes up.",
    },
    (MediaType.tv, 1399): {
        "id": 1399,
        "name": "Game of Thrones",
        "first_air_date": "2011-04-17",
        "poster_path": "/got.jpg",
    },
}


class FakeTmdb:
    def __init__(self) -> None:
        self.down = False

    async def details(self, media_type: MediaType, media_id: int) -> dict[str, Any]:
        if self.down:
            raise httpx.ConnectError("TMDB is down")
        if (media_type, media_id) not in TITLES:
            raise TmdbNotFoundError(f"/{media_type}/{media_id}")
        return TITLES[media_type, media_id]


@pytest.fixture
def tmdb() -> FakeTmdb:
    return FakeTmdb()


@pytest.fixture
async def database(tmp_path) -> AsyncIterator[Database]:
    database = Database(f"sqlite+aiosqlite:///{tmp_path}/driftwood.db")
    await database.migrate()
    yield database
    await database.dispose()


def _client(database: Database, idp: FakeIdp, tmdb: FakeTmdb) -> httpx.AsyncClient:
    app = make_app(database, idp)
    app.include_router(my_list_router, prefix="/api")
    app.state.my_list_service = MyListService(tmdb)  # type: ignore[arg-type]
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=PUBLIC_URL)


@pytest.fixture
async def client(database: Database, tmdb: FakeTmdb) -> AsyncIterator[httpx.AsyncClient]:
    idp = FakeIdp()
    async with _client(database, idp, tmdb) as client:
        await sign_in(client, idp)
        yield client


def _keys(response: httpx.Response) -> list[tuple[str, int]]:
    return [(item["media_type"], item["id"]) for item in response.json()]


async def test_add_list_and_remove(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/my-list")).json() == []
    assert (await client.get("/api/my-list/movie/603")).json() == {"in_list": False}

    assert (await client.put("/api/my-list/movie/603")).json() == {"in_list": True}
    assert (await client.put("/api/my-list/tv/1399")).json() == {"in_list": True}
    assert (await client.get("/api/my-list/movie/603")).json() == {"in_list": True}

    listed = await client.get("/api/my-list")
    assert _keys(listed) == [("tv", 1399), ("movie", 603)]  # newest first
    assert listed.json()[1]["title"] == "The Matrix"
    assert listed.json()[1]["poster_path"] == "/matrix.jpg"

    assert (await client.delete("/api/my-list/tv/1399")).json() == {"in_list": False}
    assert _keys(await client.get("/api/my-list")) == [("movie", 603)]


async def test_add_and_remove_are_idempotent(client: httpx.AsyncClient) -> None:
    await client.put("/api/my-list/movie/603")
    assert (await client.put("/api/my-list/movie/603")).status_code == 200
    assert _keys(await client.get("/api/my-list")) == [("movie", 603)]

    await client.delete("/api/my-list/movie/603")
    assert (await client.delete("/api/my-list/movie/603")).status_code == 200
    assert (await client.get("/api/my-list")).json() == []


async def test_unknown_titles_cannot_be_added(client: httpx.AsyncClient) -> None:
    assert (await client.put("/api/my-list/movie/999")).status_code == 404
    # Same id, other media type: still unknown.
    assert (await client.put("/api/my-list/tv/603")).status_code == 404
    assert (await client.get("/api/my-list")).json() == []


async def test_lists_are_per_user(database: Database, tmdb: FakeTmdb) -> None:
    ada, bob = FakeIdp(), FakeIdp()
    bob.claims = {**bob.claims, "sub": "user-2", "name": "Bob"}
    async with (
        _client(database, ada, tmdb) as ada_client,
        _client(database, bob, tmdb) as bob_client,
    ):
        await sign_in(ada_client, ada)
        await sign_in(bob_client, bob)
        await ada_client.put("/api/my-list/movie/603")

        assert (await bob_client.get("/api/my-list")).json() == []
        assert (await bob_client.get("/api/my-list/movie/603")).json() == {"in_list": False}
        await bob_client.delete("/api/my-list/movie/603")
        assert _keys(await ada_client.get("/api/my-list")) == [("movie", 603)]


async def test_list_falls_back_to_snapshot_when_tmdb_is_down(
    client: httpx.AsyncClient, tmdb: FakeTmdb
) -> None:
    await client.put("/api/my-list/movie/603")
    tmdb.down = True
    [item] = (await client.get("/api/my-list")).json()
    assert (item["title"], item["year"], item["poster_path"]) == ("The Matrix", 1999, "/matrix.jpg")


async def test_signed_out_requests_are_rejected(database: Database, tmdb: FakeTmdb) -> None:
    async with _client(database, FakeIdp(), tmdb) as client:
        assert (await client.get("/api/my-list")).status_code == 401
        assert (await client.put("/api/my-list/movie/603")).status_code == 401
