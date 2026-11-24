import json
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from driftwood.indexers.errors import AuthError, ParseError
from driftwood.indexers.torrentleech import (
    MISSING_TITLE,
    check_login_result,
    has_logout_link,
    parse_login_form,
    parse_search_results,
)

FIXTURES = Path(__file__).parent / "fixtures" / "torrentleech"
BASE = "https://www.torrentleech.org/"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_parse_search_results() -> None:
    releases = parse_search_results(json.loads(fixture("search.json")), BASE, ZoneInfo("UTC"))
    assert [r.guid for r in releases] == ["240001", "240002", "240003"]

    first = releases[0]
    assert first.indexer_id == "torrentleech"
    assert first.title == "The.Shawshank.Redemption.1994.1080p.BluRay.x264-GRP"  # [REQ] stripped
    assert first.details_url == f"{BASE}torrent/240001"
    assert first.download_url == (
        f"{BASE}download/240001/The.Shawshank.Redemption.1994.1080p.BluRay.x264-GRP.torrent"
    )
    assert first.categories == [2040, 2000]
    assert first.genres == ["Drama", "Crime"]
    assert (first.seeders, first.leechers, first.grabs) == (120, 3, 4567)
    assert first.size == 12345678901
    assert first.published == datetime(2021, 10, 25, 2, 18, 31, tzinfo=UTC)
    assert first.download_factor == 0.0
    assert first.upload_factor == 1.0
    assert first.minimum_ratio == 1.0
    assert first.minimum_seed_time == 864_000
    assert first.imdb_id == "tt0111161"

    assert releases[1].categories == [2045, 2000]
    assert releases[1].download_factor == 1.0
    assert releases[2].imdb_id is None


def test_published_follows_profile_timezone() -> None:
    releases = parse_search_results(
        json.loads(fixture("search.json")), BASE, ZoneInfo("Europe/Amsterdam")
    )
    assert releases[0].published == datetime(2021, 10, 25, 0, 18, 31, tzinfo=UTC)


def test_null_title_falls_back_and_malformed_rows_are_skipped() -> None:
    data = json.loads(fixture("search_null_title.json"))
    releases = parse_search_results(data, BASE, ZoneInfo("UTC"))
    assert [r.guid for r in releases] == ["250001", "250003"]
    assert releases[0].title == "Some.Show.S01E01.1080p.WEB.h264-GRP"
    assert releases[0].categories == [5040, 5000]
    assert releases[1].title == MISSING_TITLE
    assert releases[1].size is None
    assert releases[1].published is None


def test_unexpected_payload_raises_parse_error() -> None:
    with pytest.raises(ParseError):
        parse_search_results(["nope"], BASE, ZoneInfo("UTC"))
    assert parse_search_results({"numFound": 0}, BASE, ZoneInfo("UTC")) == []


def test_parse_login_form_collects_inputs() -> None:
    form = parse_login_form(fixture("login_page.html"), f"{BASE}user/account/login/")
    assert form is not None
    action, fields = form
    assert action == f"{BASE}user/account/login/"
    assert fields == {
        "_csrf": "token123",
        "username": "",
        "password": "",
        "alt2FAToken": "",
        "remember_me": "on",
    }
    assert parse_login_form(fixture("home.html"), BASE) is None


def test_check_login_result() -> None:
    with pytest.raises(AuthError, match="Invalid username or password"):
        check_login_result(fixture("login_failed.html"))
    with pytest.raises(AuthError, match="2FA"):
        check_login_result(fixture("login_2fa.html"))
    with pytest.raises(AuthError, match="login failed"):
        check_login_result(fixture("login_page.html"))
    check_login_result(fixture("home.html"))


def test_has_logout_link() -> None:
    assert has_logout_link(fixture("home.html"))
    assert not has_logout_link(fixture("login_page.html"))
