"""Requests should look like Firefox browsing TorrentLeech."""

import httpx

from driftwood.indexers.http import DEFAULT_USER_AGENT, browser_headers
from driftwood.indexers.models import SearchQuery, SearchType
from driftwood.indexers.torrentleech import MIN_REQUEST_INTERVAL, TorrentLeechIndexer

from .test_torrentleech_session import FakeTorrentLeech, make_indexer

BASE = "https://www.torrentleech.org/"


def test_browser_headers_for_a_first_page_load() -> None:
    headers = browser_headers("navigate", "GET", f"{BASE}user/account/login/", None)
    assert list(headers.items()) == list(
        {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Priority": "u=0, i",
        }.items()
    )


def test_browser_headers_for_a_form_post_and_a_script_fetch() -> None:
    post = browser_headers("navigate", "POST", f"{BASE}user/account/login/", f"{BASE}login")
    assert post["Origin"] == "https://www.torrentleech.org"
    assert post["Referer"] == f"{BASE}login"
    assert post["Sec-Fetch-Site"] == "same-origin"

    fetch = browser_headers("fetch", "GET", f"{BASE}torrents/browse/list", f"{BASE}torrents/browse")
    assert fetch["Accept"] == "application/json, text/plain, */*"
    assert (fetch["Sec-Fetch-Dest"], fetch["Sec-Fetch-Mode"]) == ("empty", "cors")
    assert "Upgrade-Insecure-Requests" not in fetch

    cross = browser_headers("navigate", "GET", f"{BASE}x", "https://example.com/")
    assert cross["Sec-Fetch-Site"] == "cross-site"


def by_path(site: FakeTorrentLeech, prefix: str, method: str = "GET") -> httpx.Request:
    return next(r for r in site.requests if r.url.path.startswith(prefix) and r.method == method)


async def test_a_session_looks_like_firefox() -> None:
    site = FakeTorrentLeech(nfos={"240001": b"Subtitles: English"})
    indexer = make_indexer(site)
    await indexer.search(SearchQuery(type=SearchType.MOVIE, imdb_id="tt0111161"))
    await indexer.fetch_nfo("240001")

    for request in site.requests:
        assert request.headers["User-Agent"] == DEFAULT_USER_AGENT
        assert "Firefox/140.0" in DEFAULT_USER_AGENT
        assert request.headers["Accept-Language"] == "en-US,en;q=0.5"
        assert request.headers["Accept-Encoding"] == "gzip, deflate, br, zstd"
    # Firefox's order on the wire: Host, then the browser set; Cookie is added by httpx.
    for request in site.requests:
        names = [k.decode() for k, _ in request.headers.raw]
        assert names[:5] == ["Host", "User-Agent", "Accept", "Accept-Language", "Accept-Encoding"]
        assert names.index("Connection") < names.index("Sec-Fetch-Dest")

    login_page = by_path(site, "/user/account/login/")
    assert login_page.headers["Sec-Fetch-Site"] == "none"
    assert "Referer" not in login_page.headers

    login_post = by_path(site, "/user/account/login/", "POST")
    assert login_post.headers["Origin"] == "https://www.torrentleech.org"
    assert login_post.headers["Referer"] == f"{BASE}user/account/login/"
    assert login_post.headers["Sec-Fetch-Mode"] == "navigate"

    search = by_path(site, "/torrents/browse/list")
    assert search.headers["Accept"] == "application/json, text/plain, */*"
    assert search.headers["Sec-Fetch-Mode"] == "cors"
    assert search.headers["Referer"] == f"{BASE}torrents/browse"
    assert "Cookie" in search.headers

    nfo = by_path(site, "/nfo/download/")
    assert nfo.headers["Sec-Fetch-Mode"] == "navigate"
    assert nfo.headers["Referer"] == f"{BASE}torrent/240001"


def test_request_gap() -> None:
    assert MIN_REQUEST_INTERVAL == 1.0
    assert TorrentLeechIndexer.min_request_interval == 1.0
