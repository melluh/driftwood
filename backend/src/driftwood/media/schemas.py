from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class MediaType(StrEnum):
    movie = "movie"
    tv = "tv"


class Schema(BaseModel):
    # Fields with defaults are always present in responses; say so in the
    # OpenAPI schema so generated frontend types don't mark them optional.
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class MediaSummary(Schema):
    """Everything a search result needs to render, images included."""

    media_type: MediaType
    id: int
    title: str
    original_title: str | None = None
    year: int | None = None
    poster_path: str | None = None
    backdrop_path: str | None = None
    overview: str | None = None
    vote_average: float | None = None
    popularity: float | None = None


class Genre(Schema):
    id: int
    name: str


class CastMember(Schema):
    id: int
    name: str
    character: str | None = None
    profile_path: str | None = None


class MediaDetails(MediaSummary):
    tagline: str | None = None
    genres: list[Genre] = Field(default_factory=list)
    runtime: int | None = None
    """Minutes. For TV, the typical episode runtime."""
    release_date: str | None = None
    """Movie release date, or TV first-air date (ISO yyyy-mm-dd)."""
    last_air_date: str | None = None
    status: str | None = None
    vote_count: int | None = None
    number_of_seasons: int | None = None
    number_of_episodes: int | None = None
    original_language: str | None = None
    imdb_id: str | None = None
    cast: list[CastMember] = Field(default_factory=list)


class IndexStatus(StrEnum):
    ready = "ready"
    building = "building"
    missing = "missing"


class SearchStatus(Schema):
    status: IndexStatus
    entries: int


class HomeRow(Schema):
    id: str
    title: str
    items: list[MediaSummary]


class HomePage(Schema):
    featured: list[MediaSummary]
    """Large, rotating highlights for the top of the page (all have a backdrop)."""
    rows: list[HomeRow]
