from driftwood.indexers.models import SearchType
from driftwood.media.releases import describe, release_query, search_title
from driftwood.media.schemas import MediaDetails, MediaType


def test_search_title_drops_punctuation_release_names_omit() -> None:
    assert search_title("Grey's Anatomy") == "Greys Anatomy"
    assert search_title("Mission: Impossible - Fallout") == "Mission Impossible Fallout"
    assert search_title("Spider-Man: No Way Home") == "Spider Man No Way Home"


def test_movie_query_uses_imdb_and_year() -> None:
    media = MediaDetails(
        media_type=MediaType.movie, id=278, title="The Shawshank Redemption", year=1994,
        imdb_id="tt0111161",
    )  # fmt: skip
    query = release_query(media)
    assert query.type is SearchType.MOVIE
    assert (query.q, query.year, query.imdb_id, query.categories) == (
        "The Shawshank Redemption",
        1994,
        "tt0111161",
        (2000,),
    )
    assert (
        describe(query)
        == "movie-search imdb=tt0111161 q='The Shawshank Redemption' year=1994 cat=2000"
    )


def test_tv_query_searches_by_title() -> None:
    media = MediaDetails(media_type=MediaType.tv, id=2316, title="The Office", year=2005)
    query = release_query(media)
    assert query.type is SearchType.TV
    assert (query.q, query.year, query.categories) == ("The Office", None, (5000,))
