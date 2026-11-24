"""The releases endpoint, end to end against a fake TMDB and a fake TorrentLeech."""

from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from driftwood.indexers.manager import IndexerManager
from driftwood.media.releases import ReleaseService
from driftwood.media.router import router
from driftwood.media.schemas import MediaType
from driftwood.media.watch import WatchService
from driftwood.selection.config import SelectionSettings
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


def watch_client(indexers: IndexerManager) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    releases = ReleaseService(FakeTmdb(), indexers, cache_ttl_seconds=60)  # type: ignore[arg-type]
    app.state.watch_service = WatchService(releases, SelectionSettings())
    return TestClient(app)


def test_watch_endpoint_picks_a_1080p_release() -> None:
    site = FakeTorrentLeech()
    response = watch_client(IndexerManager([make_indexer(site)])).get("/api/media/movie/278/watch")
    assert response.status_code == httpx.codes.OK
    body = response.json()
    # FakeTmdb has no runtime, so bitrate bands are skipped.
    assert body["pick"]["release"]["guid"] == "240001"
    assert body["pick"]["slot"] == "1080p_encode"
    assert body["pick"]["attributes"]["resolution"] == "1080p"
    assert [o["slot"] for o in body["options"]] == ["4k_encode", "1080p_encode", "720p"]
    assert body["considered"] == 3
    assert body["episode"] is None


def test_watch_endpoint_without_indexers() -> None:
    body = watch_client(IndexerManager([])).get("/api/media/movie/278/watch").json()
    assert body["pick"] is None
    assert body["options"] == []


def test_watch_verifies_subtitles_through_nfos() -> None:
    # The 1080p pick only has Dutch subtitles, so Watch checks the next
    # candidate (the 720p) and picks that one, which has English.
    site = FakeTorrentLeech(
        nfos={"240001": b"Subtitles: Dutch", "240003": b"Subtitles...: English, Dutch"}
    )
    api = watch_client(IndexerManager([make_indexer(site)]))
    body = api.get("/api/media/movie/278/watch").json()
    assert body["pick"]["release"]["guid"] == "240003"
    assert body["pick"]["subtitle_status"] == "wanted"
    assert body["pick"]["subtitles"] == [
        {"language": "en", "forced": False},
        {"language": "nl", "forced": False},
    ]
    assert body["nfos_checked"] == 2
    assert body["subtitle_languages"] == ["en"]
    by_slot = {o["slot"]: o for o in body["options"]}
    assert by_slot["1080p_encode"]["subtitle_status"] == "missing"
    assert by_slot["4k_encode"]["subtitle_status"] == "not_checked"
    assert [p for p in site.paths if p.startswith("/nfo/")] == [
        "/nfo/download/240001",
        "/nfo/download/240003",
    ]


def test_release_nfo_endpoint() -> None:
    site = FakeTorrentLeech(
        nfos={"240001": "Subtitles: English, French\nNotes: très bien".encode("cp437")}
    )
    api = client(IndexerManager([make_indexer(site)]))
    body = api.get("/api/releases/torrentleech/240001/nfo").json()
    assert body["text"] == "Subtitles: English, French\nNotes: très bien"
    assert body["subtitles_known"] is True
    assert [s["language"] for s in body["subtitles"]] == ["en", "fr"]

    assert api.get("/api/releases/torrentleech/999/nfo").json()["text"] is None
    assert api.get("/api/releases/nope/1/nfo").status_code == httpx.codes.BAD_GATEWAY
