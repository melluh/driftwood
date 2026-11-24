"""Login, session expiry and download against a fake TorrentLeech (no network)."""

import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import SecretStr

from driftwood.indexers.errors import AuthError, IndexerError, SiteUnavailableError
from driftwood.indexers.http import HttpSession
from driftwood.indexers.manager import IndexerManager
from driftwood.indexers.models import SearchQuery, SearchType
from driftwood.indexers.torrentleech import MIRRORS, TorrentLeechIndexer, TorrentLeechSettings

FIXTURES = Path(__file__).parent / "fixtures" / "torrentleech"
TORRENT = b"d8:announce30:https://tracker.example/announce4:infod4:name4:testee"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


class FakeTorrentLeech:
    def __init__(
        self,
        *,
        password: str = "secret",
        down_hosts: tuple[str, ...] = (),
        nfos: dict[str, bytes] | None = None,
    ) -> None:
        self.password = password
        self.down_hosts = down_hosts
        self.nfos = nfos or {}
        """NFO bytes by fid; the fid "html" answers with a site page instead."""
        self.sessions: set[str] = set()
        self.logins = 0
        self.login_forms: list[dict[str, list[str]]] = []
        self.paths: list[str] = []

    def expire_sessions(self) -> None:
        self.sessions.clear()

    def html(self, name: str, **kwargs: object) -> httpx.Response:
        return httpx.Response(
            200, text=fixture(name), headers={"content-type": "text/html"}, **kwargs
        )  # type: ignore[arg-type]

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.host in self.down_hosts:
            raise httpx.ConnectError("connection refused", request=request)
        path = request.url.path
        self.paths.append(path)
        logged_in = request.headers.get("cookie", "").removeprefix("tlsession=") in self.sessions

        if path == "/user/account/login/" and request.method == "GET":
            return self.html("login_page.html")
        if path == "/user/account/login/" and request.method == "POST":
            form = parse_qs(request.content.decode(), keep_blank_values=True)
            self.login_forms.append(form)
            if form.get("username") == ["melle"] and form.get("password") == [self.password]:
                self.logins += 1
                token = f"s{self.logins}"
                self.sessions.add(token)
                return httpx.Response(
                    302, headers={"location": "/", "set-cookie": f"tlsession={token}; Path=/"}
                )
            return self.html("login_failed.html")
        if path == "/":
            return self.html("home.html" if logged_in else "login_page.html")
        if path.startswith("/torrents/browse/list"):
            if not logged_in:
                return httpx.Response(302, headers={"location": "/user/account/login/"})
            return httpx.Response(200, json=json.loads(fixture("search.json")))
        if path.startswith("/nfo/download/"):
            if not logged_in:
                return self.html("login_page.html")
            fid = path.removeprefix("/nfo/download/")
            if fid == "html":
                return self.html("home.html")
            if fid in self.nfos:
                return httpx.Response(
                    200,
                    content=self.nfos[fid],
                    headers={"content-type": "application/octet-stream"},
                )
            return httpx.Response(404)
        if path.startswith("/download/"):
            if not logged_in:
                return self.html("login_page.html")
            return httpx.Response(
                200, content=TORRENT, headers={"content-type": "application/x-bittorrent"}
            )
        return httpx.Response(404)


def make_indexer(
    site: FakeTorrentLeech, *, password: str = "secret", cookie_file: Path | None = None
) -> TorrentLeechIndexer:
    settings = TorrentLeechSettings(username="melle", password=SecretStr(password))
    http = HttpSession(
        MIRRORS,
        cookie_file=cookie_file,
        transport=httpx.MockTransport(site.handler),
        retry_backoff=0,
    )
    return TorrentLeechIndexer(settings, http)


MOVIE = SearchQuery(type=SearchType.MOVIE, q="The Shawshank Redemption", imdb_id="tt0111161")


async def test_search_logs_in_lazily_and_parses() -> None:
    site = FakeTorrentLeech()
    indexer = make_indexer(site)
    releases = await indexer.search(MOVIE)
    assert [r.guid for r in releases] == ["240001", "240002", "240003"]
    assert site.logins == 1
    form = site.login_forms[0]
    assert form["_csrf"] == ["token123"]
    assert form["alt2FAToken"] == [""]
    assert form["remember_me"] == ["on"]
    assert "/torrents/browse/list/imdbID/tt0111161/orderby/added/order/desc" in site.paths

    await indexer.search(MOVIE)
    assert site.logins == 1  # session reused


async def test_limit_and_offset() -> None:
    indexer = make_indexer(FakeTorrentLeech())
    query = SearchQuery(type=SearchType.MOVIE, imdb_id="tt0111161", offset=1, limit=1)
    assert [r.guid for r in await indexer.search(query)] == ["240002"]


async def test_expired_session_relogs_in_once() -> None:
    site = FakeTorrentLeech()
    indexer = make_indexer(site)
    await indexer.search(MOVIE)
    site.expire_sessions()
    releases = await indexer.search(MOVIE)
    assert len(releases) == 3
    assert site.logins == 2


async def test_bad_credentials_raise_auth_error() -> None:
    site = FakeTorrentLeech()
    indexer = make_indexer(site, password="wrong")
    with pytest.raises(AuthError, match="Invalid username or password"):
        await indexer.search(MOVIE)


async def test_cookies_persist_across_instances(tmp_path: Path) -> None:
    site = FakeTorrentLeech()
    cookie_file = tmp_path / "torrentleech.cookies.json"
    await make_indexer(site, cookie_file=cookie_file).search(MOVIE)
    assert cookie_file.exists()
    assert oct(cookie_file.stat().st_mode & 0o777) == "0o600"

    await make_indexer(site, cookie_file=cookie_file).search(MOVIE)
    assert site.logins == 1


async def test_mirror_fallback() -> None:
    site = FakeTorrentLeech(down_hosts=("www.torrentleech.org",))
    indexer = make_indexer(site)
    releases = await indexer.search(MOVIE)
    assert indexer.http.base_url == "https://www.torrentleech.cc/"
    assert releases[0].details_url == "https://www.torrentleech.cc/torrent/240001"


async def test_all_mirrors_down() -> None:
    hosts = tuple(httpx.URL(m).host for m in MIRRORS)
    indexer = make_indexer(FakeTorrentLeech(down_hosts=hosts))
    with pytest.raises(SiteUnavailableError):
        await indexer.search(MOVIE)


async def test_download_relogs_in_when_html_comes_back() -> None:
    site = FakeTorrentLeech()
    indexer = make_indexer(site)
    release = (await indexer.search(MOVIE))[0]
    site.expire_sessions()
    assert await indexer.download(release) == TORRENT
    assert site.logins == 2


async def test_manager_collects_failures() -> None:
    good = make_indexer(FakeTorrentLeech())
    bad = make_indexer(FakeTorrentLeech(), password="wrong")
    result = await IndexerManager([good, bad]).search(MOVIE)
    assert len(result.releases) == 3
    assert result.searched == ["torrentleech", "torrentleech"]
    assert len(result.failures) == 1
    assert result.failures[0].message.startswith("AuthError")


async def test_fetch_nfo() -> None:
    nfo = (FIXTURES / "nfo_scene.nfo").read_bytes()
    site = FakeTorrentLeech(nfos={"240001": nfo})
    indexer = make_indexer(site)
    assert await indexer.fetch_nfo("240001") == nfo
    assert "/nfo/download/240001" in site.paths
    assert await indexer.fetch_nfo("999") is None  # 404: no NFO
    assert await indexer.fetch_nfo("html") is None  # a site page, not a file


async def test_fetch_nfo_relogs_in_when_session_expired() -> None:
    site = FakeTorrentLeech(nfos={"240001": b"Subtitles: English"})
    indexer = make_indexer(site)
    await indexer.fetch_nfo("240001")
    site.expire_sessions()
    assert await indexer.fetch_nfo("240001") == b"Subtitles: English"
    assert site.logins == 2


async def test_manager_routes_nfo_to_the_indexer() -> None:
    site = FakeTorrentLeech(nfos={"240001": b"Subtitles: English"})
    manager = IndexerManager([make_indexer(site)])
    assert await manager.fetch_nfo("torrentleech", "240001") == b"Subtitles: English"
    with pytest.raises(IndexerError):
        await manager.fetch_nfo("nope", "1")
