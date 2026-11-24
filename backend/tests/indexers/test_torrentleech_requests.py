"""URL building, checked against the examples in docs/indexer-design.md §2.3."""

from pydantic import SecretStr

from driftwood.indexers.models import SearchQuery, SearchType
from driftwood.indexers.torrentleech import (
    TorrentLeechSettings,
    build_search_path,
    episode_string,
    search_keywords,
)


def settings(**overrides: object) -> TorrentLeechSettings:
    return TorrentLeechSettings(username="u", password=SecretStr("p"), **overrides)  # type: ignore[arg-type]


def test_tv_season_search_with_categories() -> None:
    query = SearchQuery(type=SearchType.TV, q="the office", season=1, categories=(5030, 5040))
    assert build_search_path(query, settings()) == (
        "torrents/browse/list/categories/26,32/exact/1/query/the%20office%20S01/"
        "orderby/added/order/desc"
    )


def test_movie_imdb_search_skips_keywords() -> None:
    query = SearchQuery(type=SearchType.MOVIE, q="The Shawshank Redemption", imdb_id="tt0111161")
    assert build_search_path(query, settings(sort="seeders")) == (
        "torrents/browse/list/imdbID/tt0111161/orderby/seeders/order/desc"
    )


def test_imdb_search_without_keywords_still_adds_newfilter() -> None:
    query = SearchQuery(type=SearchType.MOVIE, imdb_id="tt0111161")
    assert build_search_path(query, settings()) == (
        "torrents/browse/list/imdbID/tt0111161/newfilter/2/orderby/added/order/desc"
    )


def test_empty_search_with_facets() -> None:
    path = build_search_path(SearchQuery(), settings(freeleech_only=True, exclude_scene=True))
    assert path == (
        "torrents/browse/list/facets/tags:FREELEECH,nonscene/exact/1/query//"
        "newfilter/2/orderby/added/order/desc"
    )


def test_exclude_archives_applies_to_keyword_search_only() -> None:
    keyword = SearchQuery(q="foo")
    assert "/query/foo%20-tags%3Arar/" in build_search_path(
        keyword, settings(exclude_archives=True)
    )
    imdb = SearchQuery(type=SearchType.MOVIE, q="foo", imdb_id="tt1")
    assert "rar" not in build_search_path(imdb, settings(exclude_archives=True))


def test_leading_dash_is_neutralized() -> None:
    assert search_keywords(SearchQuery(q="-foo bar -baz")) == "foo bar baz"
    assert search_keywords(SearchQuery(q="spider-man")) == "spider-man"


def test_movie_keywords_include_year() -> None:
    query = SearchQuery(type=SearchType.MOVIE, q="Dune", year=2021)
    assert search_keywords(query) == "Dune 2021"


def test_episode_strings() -> None:
    assert episode_string(1, "3") == "S01E03"
    assert episode_string(12, None) == "S12"
    assert episode_string(None, "2024.01.31") == "2024.01.31"
    assert episode_string(None, None) is None
    query = SearchQuery(type=SearchType.TV, q="Show", season=2, episode="5")
    assert search_keywords(query) == "Show S02E05"
