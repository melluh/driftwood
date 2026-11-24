from driftwood.media.mapping import to_details, to_summary
from driftwood.media.schemas import MediaType

MOVIE = {
    "id": 603,
    "title": "The Matrix",
    "original_title": "The Matrix",
    "release_date": "1999-03-31",
    "poster_path": "/p.jpg",
    "backdrop_path": "/b.jpg",
    "runtime": 136,
    "genres": [{"id": 28, "name": "Action"}],
    "imdb_id": "tt0133093",
    "credits": {"cast": [{"id": 6384, "name": "Keanu Reeves", "character": "Neo"}]},
}
SHOW = {
    "id": 1396,
    "name": "Breaking Bad",
    "original_name": "Breaking Bad",
    "first_air_date": "2008-01-20",
    "poster_path": None,
    "episode_run_time": [],
    "last_episode_to_air": {"runtime": 47},
    "number_of_seasons": 5,
    "external_ids": {"imdb_id": "tt0903747"},
}


def test_movie_summary() -> None:
    summary = to_summary(MediaType.movie, MOVIE)
    assert (summary.title, summary.year, summary.poster_path) == ("The Matrix", 1999, "/p.jpg")


def test_movie_details() -> None:
    details = to_details(MediaType.movie, MOVIE)
    assert details.runtime == 136
    assert details.genres[0].name == "Action"
    assert details.cast[0].character == "Neo"


def test_tv_details_use_tv_field_names() -> None:
    details = to_details(MediaType.tv, SHOW)
    assert (details.title, details.year) == ("Breaking Bad", 2008)
    assert details.release_date == "2008-01-20"
    assert details.runtime == 47
    assert details.imdb_id == "tt0903747"
    assert details.poster_path is None
