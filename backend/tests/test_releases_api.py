"""The releases endpoint, end to end against a fake TMDB and a fake TorrentLeech."""

from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from driftwood.indexers.manager import IndexerManager
from driftwood.media.releases import ReleaseService
from driftwood.media.router import router
from driftwood.media.schemas import MediaType
from driftwood.tmdb.client import TmdbNotFoundError
from tests.indexers.test_torrentleech_session import FakeTorrentLeech, make_indexer


class FakeTmdb:
    async def details(self, media_type: MediaType, media_id: int) -> dict[str, Any]:
        if media_id != 278:
            raise TmdbNotFoundError(media_id)
        return {
            "id": 278,
            "title": "The Shawshank Redemption",
            "release_date": "1994-09-23",
            "imdb_id": "tt0111161",
        }


def client(indexers: IndexerManager) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.release_service = ReleaseService(
        FakeTmdb(),  # type: ignore[arg-type]
        indexers,
        cache_ttl_seconds=60,
    )
    return TestClient(app)


def test_releases_endpoint_lists_torrents_most_seeded_first() -> None:
    site = FakeTorrentLeech()
    response = client(IndexerManager([make_indexer(site)])).get("/api/media/movie/278/releases")
    assert response.status_code == httpx.codes.OK
    body = response.json()
    assert body["query"].startswith("movie-search imdb=tt0111161")
    assert body["indexers"] == ["torrentleech"]
    assert body["failures"] == []
    assert [r["guid"] for r in body["releases"]] == ["240001", "240002", "240003"]
    first = body["releases"][0]
    assert first["freeleech"] is True
    assert first["seeders"] == 120
    assert first["published"] == "2021-10-25T02:18:31Z"


def test_releases_endpoint_without_indexers() -> None:
    body = client(IndexerManager([])).get("/api/media/movie/278/releases").json()
    assert body["indexers"] == []
    assert body["releases"] == []


def test_releases_endpoint_reports_indexer_failure() -> None:
    bad = make_indexer(FakeTorrentLeech(), password="wrong")
    body = client(IndexerManager([bad])).get("/api/media/movie/278/releases").json()
    assert body["releases"] == []
    assert body["failures"][0]["indexer"] == "torrentleech"
    assert "AuthError" in body["failures"][0]["message"]


def test_releases_endpoint_unknown_media() -> None:
    response = client(IndexerManager([])).get("/api/media/movie/1/releases")
    assert response.status_code == httpx.codes.NOT_FOUND
