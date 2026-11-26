from datetime import datetime
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


class TorrentRelease(Schema):
    """A torrent an indexer found for a title."""

    indexer: str
    guid: str
    title: str
    details_url: str | None = None
    size: int | None = None
    """Bytes."""
    published: datetime | None = None
    categories: list[int] = Field(default_factory=list)
    """Torznab category ids."""
    seeders: int | None = None
    leechers: int | None = None
    grabs: int | None = None
    freeleech: bool = False
    imdb_id: str | None = None
    genres: list[str] = Field(default_factory=list)


class IndexerFailure(Schema):
    indexer: str
    message: str


class ReleaseSearch(Schema):
    query: str
    """What was sent to the indexers, for debugging."""
    indexers: list[str]
    """Ids of the indexers searched; empty when none are configured."""
    releases: list[TorrentRelease]
    """Most seeded first."""
    failures: list[IndexerFailure]


class ReleaseAttributes(Schema):
    """What the release name says about its quality (parsed with guessit)."""

    resolution: str | None = None
    source: str | None = None
    codec: str | None = None
    hdr_flags: list[str] = Field(default_factory=list)
    audio_codecs: list[str] = Field(default_factory=list)
    language_variant: str | None = None
    release_group: str | None = None
    season: int | None = None
    episodes: list[int] = Field(default_factory=list)


class ScoreFactor(Schema):
    name: str
    points: int


class SubtitleTrack(Schema):
    language: str
    """ISO 639-1 code (`en`) where one exists; `und` when the NFO doesn't say."""
    forced: bool = False


class SubtitleStatus(StrEnum):
    wanted = "wanted"
    missing = "missing"
    unknown = "unknown"
    not_checked = "not_checked"


class RankedRelease(Schema):
    release: TorrentRelease
    attributes: ReleaseAttributes
    slot: str | None = None
    """Quality slot name, e.g. `1080p_encode`; None if it fits no slot."""
    slot_label: str | None = None
    score: int
    """Only comparable with releases in the same slot."""
    factors: list[ScoreFactor]
    effective_mbps: float | None = None
    """Average bitrate (size / runtime)."""
    equivalent_mbps: float | None = None
    """The bitrate scored against the slot's target: H.264-equivalent in slots that
    mix codecs (HEVC x1.4, AV1 x1.6), else the same as `effective_mbps`."""
    subtitle_status: SubtitleStatus | None = None
    """From the NFO: `wanted` (has a wanted language), `missing`, `unknown` (no NFO or it
    doesn't say) or `not_checked`. None when no subtitle languages are configured."""
    subtitles: list[SubtitleTrack] = Field(default_factory=list)
    audio_languages: list[str] = Field(default_factory=list)


class Rejected(Schema):
    reason: str
    count: int


class WatchEpisode(Schema):
    season: int
    episode: int


class WatchPlan(Schema):
    """Which release to grab to start watching now, plus higher-quality alternatives."""

    query: str
    indexers: list[str]
    failures: list[IndexerFailure]
    episode: WatchEpisode | None = None
    """For series: the episode that was searched."""
    pick: RankedRelease | None = None
    """The release to grab now: a modest 1080p encode when there is one."""
    options: list[RankedRelease]
    """The best release of every slot, best quality first (the pick included)."""
    considered: int
    """Releases the indexers returned."""
    subtitle_languages: list[str]
    """Wanted subtitle languages (ISO codes); empty when subtitle checks are off."""
    nfos_checked: int
    """NFOs fetched to verify subtitles."""
    rejected: list[Rejected]
    can_download: bool = False
    """Whether a download client (qBittorrent) is configured to grab the pick."""


class ReleaseNfo(Schema):
    text: str | None = None
    """The NFO as text; None when the release has none."""
    subtitles_known: bool = False
    subtitles: list[SubtitleTrack] = Field(default_factory=list)
    audio_languages: list[str] = Field(default_factory=list)
