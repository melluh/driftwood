import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import PurePosixPath
from typing import Literal

from guessit import guessit

from driftwood.media.schemas import MediaType

from .tags import find_tmdb_id

_SEASON_DIRECTORY = re.compile(r"^season\s*(\d+)$", re.IGNORECASE)


@lru_cache(maxsize=8192)
def _guess_episode(filename: str) -> dict[str, object]:
    return dict(guessit(filename, {"type": "episode"}))


@dataclass(frozen=True)
class Link:
    media_type: MediaType
    media_id: int
    season: int | None = None
    episode: int | None = None


def _episode_numbers(value: object) -> list[int]:
    values = value if isinstance(value, list) else [value]
    return [number for number in values if isinstance(number, int) and number >= 0]


def _parent_season(relative_path: PurePosixPath) -> int | None:
    for directory in reversed(relative_path.parent.parts):
        if directory.casefold() == "specials":
            return 0
        if match := _SEASON_DIRECTORY.fullmatch(directory):
            return int(match.group(1))
    return None


def match_file(relative_path: PurePosixPath, kind: Literal["movies", "tv"]) -> list[Link]:
    """Match the file's TMDB tag and (for TV) episode numbering."""
    media_id = find_tmdb_id(relative_path)
    if media_id is None:
        return []
    if kind == "movies":
        return [Link(MediaType.movie, media_id)]

    guess = _guess_episode(relative_path.name)
    episodes = _episode_numbers(guess.get("episode"))
    if not episodes:
        return []
    season = guess.get("season")
    if not isinstance(season, int):
        season = _parent_season(relative_path)
    if season is None:
        season = 1
    return [Link(MediaType.tv, media_id, season, episode) for episode in episodes]
