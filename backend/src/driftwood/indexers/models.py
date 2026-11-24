"""Indexer-neutral search and result models. They mirror Torznab / Cardigann fields."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class SearchType(StrEnum):
    GENERIC = "search"
    TV = "tv-search"
    MOVIE = "movie-search"


@dataclass(frozen=True)
class SearchQuery:
    type: SearchType = SearchType.GENERIC
    q: str | None = None
    """Free text; for TV / movie searches this is the series or movie title."""
    categories: tuple[int, ...] = ()
    """Torznab category ids (2000, 5040, ...)."""
    imdb_id: str | None = None
    tmdb_id: int | None = None
    tvdb_id: int | None = None
    season: int | None = None
    episode: str | None = None
    """A string: may be "3" or a daily-show date like "2024.01.31"."""
    year: int | None = None
    limit: int | None = None
    offset: int = 0


@dataclass
class Release:
    indexer_id: str
    guid: str
    """Stable per-indexer id, e.g. the TorrentLeech fid."""
    title: str
    details_url: str | None
    download_url: str
    """May need the indexer's logged-in session to fetch."""
    size: int | None
    """Bytes."""
    published: datetime | None
    """Timezone-aware, UTC."""
    categories: list[int]
    """Torznab ids, mapped (each with its parent)."""
    seeders: int | None = None
    leechers: int | None = None
    grabs: int | None = None
    imdb_id: str | None = None
    genres: list[str] = field(default_factory=list)
    download_factor: float = 1.0
    """0.0 means freeleech."""
    upload_factor: float = 1.0
    minimum_ratio: float | None = None
    minimum_seed_time: int | None = None
    """Seconds."""
    magnet: str | None = None
    infohash: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class CategoryMapping:
    site_id: str
    """The site's own category id, kept as a string ("26")."""
    torznab_id: int
    description: str
    default: bool = False


@dataclass(frozen=True)
class Capabilities:
    search_modes: dict[SearchType, frozenset[str]]
    categories: tuple[CategoryMapping, ...]
    supports_raw_search: bool = False
