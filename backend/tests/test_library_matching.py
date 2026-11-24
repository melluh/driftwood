from pathlib import PurePosixPath

from driftwood.library.matching import Link, match_file
from driftwood.media.schemas import MediaType


def test_movie_match() -> None:
    assert match_file(PurePosixPath("Dune [tmdbid-438631]/Dune.mkv"), "movies") == [
        Link(MediaType.movie, 438631)
    ]


def test_tv_episode_uses_season_directory() -> None:
    assert match_file(
        PurePosixPath("Game of Thrones [tmdbid-1399]/Season 01/Game.of.Thrones.S01E01.mkv"),
        "tv",
    ) == [Link(MediaType.tv, 1399, 1, 1)]


def test_tv_episode_season_from_filename_without_parent() -> None:
    assert match_file(PurePosixPath("Show [tmdbid-22]/Show.S02E05.mkv"), "tv") == [
        Link(MediaType.tv, 22, 2, 5)
    ]


def test_multi_episode_file_has_one_link_per_episode() -> None:
    assert match_file(PurePosixPath("Show [tmdbid-22]/Show.S01E01E02.mkv"), "tv") == [
        Link(MediaType.tv, 22, 1, 1),
        Link(MediaType.tv, 22, 1, 2),
    ]


def test_specials_directory_supplies_season_zero() -> None:
    assert match_file(PurePosixPath("Show [tmdbid-22]/Specials/Show.S00E03.mkv"), "tv") == [
        Link(MediaType.tv, 22, 0, 3)
    ]


def test_tv_without_episode_number_is_unmatched() -> None:
    assert match_file(PurePosixPath("Show [tmdbid-22]/Show.mkv"), "tv") == []


def test_root_kind_determines_media_type() -> None:
    path = PurePosixPath("Title [tmdbid-1399]/Title.S01E01.mkv")
    assert match_file(path, "movies") == [Link(MediaType.movie, 1399)]
    assert match_file(path, "tv") == [Link(MediaType.tv, 1399, 1, 1)]
