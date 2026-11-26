from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from driftwood.db import Database
from driftwood.media.schemas import MediaType
from driftwood.progress.router import router as progress_router
from driftwood.progress.service import WatchProgressService, next_episode
from driftwood.tmdb.client import TmdbNotFoundError
from tests.test_auth import PUBLIC_URL, FakeIdp, make_app, sign_in

SERIES = {
    "id": 1399,
    "name": "Game of Thrones",
    "first_air_date": "2011-04-17",
    "poster_path": "/got.jpg",
    "seasons": [
        {"season_number": 0, "episode_count": 2},
        {"season_number": 1, "episode_count": 3},
        {"season_number": 2, "episode_count": 2},
        {"season_number": 3, "episode_count": 2},
    ],
    # S03E02 hasn't aired yet.
    "last_episode_to_air": {"season_number": 3, "episode_number": 1},
}

TITLES: dict[tuple[MediaType, int], dict[str, Any]] = {
    (MediaType.movie, 603): {"id": 603, "title": "The Matrix", "release_date": "1999-03-30"},
    (MediaType.movie, 604): {"id": 604, "title": "The Matrix Reloaded"},
    (MediaType.tv, 1399): SERIES,
}

SEASONS = {
    (1399, 1): {
        "episodes": [
            {"episode_number": 1, "name": "Winter Is Coming", "runtime": 62},
            {"episode_number": 2, "name": "The Kingsroad", "runtime": 56},
            {"episode_number": 3, "name": "Lord Snow", "runtime": 58},
        ]
    },
    (1399, 2): {"episodes": [{"episode_number": 1, "name": "The North Remembers"}]},
}


class FakeTmdb:
    async def details(self, media_type: MediaType, media_id: int) -> dict[str, Any]:
        if (media_type, media_id) not in TITLES:
            raise TmdbNotFoundError(f"/{media_type}/{media_id}")
        return TITLES[media_type, media_id]

    async def season(self, series_id: int, season_number: int) -> dict[str, Any]:
        if (series_id, season_number) not in SEASONS:
            raise TmdbNotFoundError(f"/tv/{series_id}/season/{season_number}")
        return SEASONS[series_id, season_number]


@pytest.fixture
async def database(tmp_path) -> AsyncIterator[Database]:
    database = Database(f"sqlite+aiosqlite:///{tmp_path}/driftwood.db")
    await database.migrate()
    yield database
    await database.dispose()


def _client(database: Database, idp: FakeIdp) -> httpx.AsyncClient:
    app = make_app(database, idp)
    app.include_router(progress_router, prefix="/api")
    app.state.progress_service = WatchProgressService(FakeTmdb())  # type: ignore[arg-type]
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=PUBLIC_URL)


@pytest.fixture
async def client(database: Database) -> AsyncIterator[httpx.AsyncClient]:
    idp = FakeIdp()
    async with _client(database, idp) as client:
        await sign_in(client, idp)
        yield client


async def _save(client: httpx.AsyncClient, path: str, position: float, duration: float, **episode):
    response = await client.put(
        f"/api/progress/{path}", json={"position": position, "duration": duration, **episode}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _continue(response: httpx.Response) -> list[tuple]:
    return [
        (item["media"]["id"], item["season"], item["episode"], item["position"], item["up_next"])
        for item in response.json()
    ]


async def test_movie_progress_and_completion(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/progress/movie/603")).json() == []

    saved = await _save(client, "movie/603", 600, 8000)
    assert saved["completed"] is False
    assert saved["resume_at"] == 600

    # Updating keeps one row.
    await _save(client, "movie/603", 900, 8000)
    listed = (await client.get("/api/progress/movie/603")).json()
    assert [(p["position"], p["season"]) for p in listed] == [(900, None)]

    finished = await _save(client, "movie/603", 7500, 8000)
    assert finished["completed"] is True
    assert finished["resume_at"] == 0

    # Completed sticks while rewatching.
    rewatch = await _save(client, "movie/603", 120, 8000)
    assert rewatch["completed"] is True
    assert rewatch["resume_at"] == 120


async def test_episode_progress_is_per_episode(client: httpx.AsyncClient) -> None:
    await _save(client, "tv/1399", 100, 3600, season=1, episode=1)
    await _save(client, "tv/1399", 200, 3600, season=1, episode=2)
    await _save(client, "tv/1399", 150, 3600, season=1, episode=1)
    listed = (await client.get("/api/progress/tv/1399")).json()
    assert [(p["season"], p["episode"], p["position"]) for p in listed] == [
        (1, 1, 150),
        (1, 2, 200),
    ]


async def test_episode_fields_are_validated(client: httpx.AsyncClient) -> None:
    body = {"position": 10, "duration": 100}
    assert (await client.put("/api/progress/tv/1399", json=body)).status_code == 422
    movie = {**body, "season": 1, "episode": 1}
    assert (await client.put("/api/progress/movie/603", json=movie)).status_code == 422
    assert (await client.put("/api/progress/movie/603", json={"position": 1})).status_code == 422


async def test_continue_watching_movies(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/progress/continue")).json() == []
    await _save(client, "movie/603", 600, 8000)  # part-way
    await _save(client, "movie/604", 7900, 8000)  # finished
    await _save(client, "movie/999", 600, 8000)  # unknown to TMDB
    response = await client.get("/api/progress/continue")
    assert _continue(response) == [(603, None, None, 600, False)]
    assert response.json()[0]["media"]["title"] == "The Matrix"

    # Barely started doesn't count.
    await _save(client, "movie/604", 10, 8000)
    assert _continue(await client.get("/api/progress/continue")) == [(603, None, None, 600, False)]


async def test_continue_watching_series(client: httpx.AsyncClient) -> None:
    # Part-way through an episode: resume it.
    await _save(client, "tv/1399", 300, 3600, season=1, episode=2)
    response = await client.get("/api/progress/continue")
    assert _continue(response) == [(1399, 1, 2, 300, False)]
    assert response.json()[0]["episode_title"] == "The Kingsroad"

    # Finished it: the next episode, from the start.
    await _save(client, "tv/1399", 3500, 3600, season=1, episode=2)
    response = await client.get("/api/progress/continue")
    assert _continue(response) == [(1399, 1, 3, 0, True)]
    assert response.json()[0]["duration"] == 58 * 60

    # Peeking at the next one doesn't change that.
    await _save(client, "tv/1399", 5, 3600, season=1, episode=3)
    assert _continue(await client.get("/api/progress/continue")) == [(1399, 1, 3, 0, True)]

    # The season finale leads into the next season.
    await _save(client, "tv/1399", 3500, 3600, season=1, episode=3)
    response = await client.get("/api/progress/continue")
    assert _continue(response) == [(1399, 2, 1, 0, True)]
    assert response.json()[0]["episode_title"] == "The North Remembers"

    # Caught up with what's aired: nothing to continue.
    await _save(client, "tv/1399", 3500, 3600, season=3, episode=1)
    assert _continue(await client.get("/api/progress/continue")) == []


async def test_continue_watching_is_most_recent_first(client: httpx.AsyncClient) -> None:
    await _save(client, "tv/1399", 300, 3600, season=1, episode=1)
    await _save(client, "movie/603", 600, 8000)
    assert [item[0] for item in _continue(await client.get("/api/progress/continue"))] == [
        603,
        1399,
    ]
    await _save(client, "tv/1399", 310, 3600, season=1, episode=1)
    assert [item[0] for item in _continue(await client.get("/api/progress/continue"))] == [
        1399,
        603,
    ]


async def test_progress_is_per_user(database: Database) -> None:
    alice_idp, bob_idp = FakeIdp(), FakeIdp()
    bob_idp.claims = {**bob_idp.claims, "sub": "user-2", "name": "Bob"}
    async with _client(database, alice_idp) as alice, _client(database, bob_idp) as bob:
        await sign_in(alice, alice_idp)
        await sign_in(bob, bob_idp)
        await _save(alice, "movie/603", 600, 8000)
        assert (await bob.get("/api/progress/movie/603")).json() == []
        assert (await bob.get("/api/progress/continue")).json() == []


def test_next_episode() -> None:
    assert next_episode(SERIES, 1, 1) == (1, 2)
    assert next_episode(SERIES, 1, 3) == (2, 1)
    assert next_episode(SERIES, 2, 2) == (3, 1)
    assert next_episode(SERIES, 3, 1) is None  # S03E02 hasn't aired
    assert next_episode(SERIES, 0, 1) == (0, 2)
    assert next_episode(SERIES, 0, 2) is None
    assert next_episode({**SERIES, "last_episode_to_air": None}, 1, 1) is None


async def test_history(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/progress/history")).json() == {
        "items": [],
        "has_more": False,
        "next_offset": 0,
    }
    await _save(client, "movie/603", 7900, 8000)  # finished
    await _save(client, "tv/1399", 5, 3600, season=1, episode=1)  # only peeked: left out
    await _save(client, "tv/1399", 1200, 3600, season=1, episode=2)  # part-way
    await _save(client, "movie/999", 600, 8000)  # unknown to TMDB: left out

    page = (await client.get("/api/progress/history")).json()
    assert page["has_more"] is False
    items = [
        (i["media"]["id"], i["season"], i["episode"], i["finished"], i["completed"])
        for i in page["items"]
    ]
    assert items == [(1399, 1, 2, False, False), (603, None, None, True, True)]
    episode = page["items"][0]
    assert episode["episode_title"] == "The Kingsroad"
    assert episode["position"] == 1200
    assert episode["resume_at"] == 1200
    assert episode["media"]["title"] == "Game of Thrones"

    # A rewatch keeps the completion, but the last play is part-way.
    await _save(client, "movie/603", 600, 8000)
    first = (await client.get("/api/progress/history")).json()["items"][0]
    assert (first["media"]["id"], first["completed"], first["finished"]) == (603, True, False)

    # Paging is over rows: newest first, 603 then the unknown 999 (dropped), then 1399.
    page = (await client.get("/api/progress/history", params={"limit": 2})).json()
    assert [i["media"]["id"] for i in page["items"]] == [603]
    assert page["has_more"] is True
    page = (await client.get("/api/progress/history", params={"limit": 2, "offset": 2})).json()
    assert [i["media"]["id"] for i in page["items"]] == [1399]
    assert page["has_more"] is False
