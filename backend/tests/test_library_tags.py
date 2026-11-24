from pathlib import PurePosixPath

import pytest

from driftwood.library.tags import find_tmdb_id


@pytest.mark.parametrize(
    "tag",
    [
        "[tmdbid-438631]",
        "[tmdbid=438631]",
        "[tmdb-438631]",
        "{tmdb-438631}",
        "{tmdbid-438631}",
        "[TMDBID-438631]",
    ],
)
def test_finds_tag_variants(tag: str) -> None:
    assert find_tmdb_id(PurePosixPath(f"Movie {tag}.mkv")) == 438631


def test_filename_tag_takes_precedence_over_parent() -> None:
    path = PurePosixPath("Outer [tmdbid-1]/Inner [tmdb-2]/Movie [tmdbid=3].mkv")
    assert find_tmdb_id(path) == 3


def test_nearest_parent_tag_takes_precedence() -> None:
    path = PurePosixPath("Outer [tmdbid-1]/Inner [tmdb-2]/Movie.mkv")
    assert find_tmdb_id(path) == 2


@pytest.mark.parametrize(
    "path",
    [
        "Movie.mkv",
        "Movie [tmdbid-0].mkv",
        "Movie [imdbid-123].mkv",
        "Movie [tvdbid-123].mkv",
    ],
)
def test_ignores_missing_or_invalid_tags(path: str) -> None:
    assert find_tmdb_id(PurePosixPath(path)) is None
