from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class TmdbSettings(BaseModel):
    api_key: str = ""
    """TMDB v3 API key, sent as the `api_key` query parameter."""

    base_url: str = "https://api.themoviedb.org/3"
    language: str = "en-US"

    cache_ttl_seconds: float = 6 * 3600
    """How long fetched movie/TV details are kept in the in-memory cache."""

    cache_max_entries: int = 5_000


class TitleIndexSettings(BaseModel):
    directory: Path = Path("data/title_index")

    head_size: int = 150_000
    """The most popular titles, ranked with the full fuzzy + structural logic
    (typo tolerance included). Everything below is the "tail": still searchable,
    but only through structural (title-prefix / acronym) matches, which keeps
    per-keystroke cost bounded while still letting obscure titles surface."""

    score_cutoff: float = 60.0
    """Minimum rapidfuzz `ratio` for a fuzzy-only head candidate - see `rank_entries`."""

    candidate_limit: int = 300
    """How many fuzzy-only head candidates rapidfuzz considers per query."""

    tail_candidate_limit: int = 50
    """Most popular structural tail matches considered per lookup."""

    tail_min_query_length: int = 3
    """Normalized query length below which the tail is not searched at all: a
    1-2 character prefix matches a huge, meaningless slice of obscure titles."""

    max_results: int = 10

    stale_after_hours: float = 36.0
    """How old the on-disk index may get before startup refreshes it immediately."""

    refresh_interval_hours: float = 24.0


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DRIFTWOOD_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
    )

    tmdb: TmdbSettings = TmdbSettings()
    title_index: TitleIndexSettings = TitleIndexSettings()


@lru_cache
def get_settings() -> Settings:
    return Settings()
