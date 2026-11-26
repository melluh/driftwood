import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from driftwood.indexers.torrentleech import TorrentLeechSettings
from driftwood.selection.config import SelectionSettings


class TmdbSettings(BaseModel):
    api_key: str = ""
    """TMDB v3 API key, sent as the `api_key` query parameter."""

    base_url: str = "https://api.themoviedb.org/3"
    language: str = "en-US"

    cache_ttl_seconds: float = 6 * 3600
    """How long fetched movie/TV details are kept in the in-memory cache."""

    cache_max_entries: int = 5_000

    list_cache_ttl_seconds: float = 3600
    """How long list endpoints (e.g. popular media) are cached."""


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


class IndexersSettings(BaseModel):
    directory: Path = Path("data/indexers")
    """Per-indexer state, such as persisted session cookies."""

    search_timeout_seconds: float = 60.0

    results_cache_ttl_seconds: float = 600.0
    """How long a title's release search is reused, to go easy on the indexers."""

    torrentleech: TorrentLeechSettings | None = None
    """Set `DRIFTWOOD_INDEXERS__TORRENTLEECH__USERNAME` / `__PASSWORD` to enable."""


class DatabaseSettings(BaseModel):
    url: str = "sqlite+aiosqlite:///data/driftwood.db"
    """SQLAlchemy async database URL. Migrations run automatically on startup."""


class LibraryRoot(BaseModel):
    name: str = Field(max_length=64)
    """Stable key stored in the database; file paths are relative to this root."""

    path: Path
    kind: Literal["movies", "tv"]


class LibrarySettings(BaseModel):
    roots: list[LibraryRoot] = Field(default_factory=list)
    """Library roots, configured as a JSON list in DRIFTWOOD_LIBRARY__ROOTS."""

    scan_interval_minutes: float = 30
    video_extensions: frozenset[str] = frozenset(
        {".mkv", ".mp4", ".m4v", ".avi", ".mov", ".ts", ".m2ts", ".webm", ".wmv"}
    )
    min_size_mb: float = 50
    """Smaller video files are treated as samples and ignored."""
    ignored_dirs: frozenset[str] = frozenset(
        {
            "extras",
            "featurettes",
            "behind the scenes",
            "deleted scenes",
            "interviews",
            "scenes",
            "shorts",
            "trailers",
            "sample",
            "samples",
            "other",
        }
    )
    """Directory names (case-insensitive) whose contents are never scanned."""
    missing_grace_days: float = 7
    """How long missing files are retained before their rows are deleted."""

    @model_validator(mode="after")
    def unique_root_names(self) -> "LibrarySettings":
        names = [root.name for root in self.roots]
        if len(names) != len(set(names)):
            raise ValueError("library root names must be unique")
        return self


class PlaybackSettings(BaseModel):
    directory: Path = Field(
        default_factory=lambda: Path(tempfile.gettempdir()) / "driftwood-playback"
    )
    """Scratch space for HLS segments and extracted subtitles. A few hundred MB
    per active stream; prefer a disk over a RAM-backed /tmp for 4K remuxes."""
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    segment_seconds: float = Field(default=6, ge=2, le=30)
    """Target HLS segment length; segments start on the file's own keyframes."""
    lead_segments: int = Field(default=10, ge=2)
    """How far ffmpeg runs ahead of the player before it's paused."""
    keep_behind_segments: int = Field(default=5, ge=0)
    """Segments behind the player kept on disk for short rewinds."""
    stream_idle_seconds: int = Field(default=120, ge=10)
    """An audio rendition nobody fetched from for this long is stopped and deleted."""
    session_idle_seconds: int = Field(default=6 * 60 * 60, ge=60)
    """A playback session is forgotten after this long without requests."""
    trickplay_interval_seconds: float = Field(default=10, gt=0)
    """Seconds between the seek-bar thumbnails Jellyfin saved next to videos
    (Jellyfin's "Interval" setting, 10 s by default). Thumbnails whose sheet
    count doesn't fit this interval are ignored."""


class AuthSettings(BaseModel):
    issuer_url: str = ""
    """OpenID Connect issuer, e.g. `https://accounts.google.com`. Its
    `/.well-known/openid-configuration` is used to discover the endpoints."""

    client_id: str = ""
    client_secret: str = ""
    """Leave empty for a public client (PKCE only)."""

    scopes: str = "openid email profile"

    provider_name: str = "SSO"
    """Shown on the login button: "Continue with <provider_name>"."""

    public_url: str = "http://localhost:5173"
    """Origin the browser uses to reach Driftwood (frontend and `/api`). The OAuth
    redirect URI registered with the provider is `<public_url>/api/auth/callback`."""

    secret_key: str = ""
    """Signs the short-lived cookie that carries OAuth state during login. A random
    key is generated per process when unset, which breaks logins in flight across
    restarts and multiple workers."""

    session_ttl_days: float = 30
    """Sessions expire after this long without use."""

    @property
    def configured(self) -> bool:
        return bool(self.issuer_url and self.client_id)

    @property
    def secure_cookies(self) -> bool:
        return self.public_url.startswith("https://")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DRIFTWOOD_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
    )

    tmdb: TmdbSettings = TmdbSettings()
    title_index: TitleIndexSettings = TitleIndexSettings()
    indexers: IndexersSettings = IndexersSettings()
    selection: SelectionSettings = SelectionSettings()

    database: DatabaseSettings = DatabaseSettings()
    auth: AuthSettings = AuthSettings()
    library: LibrarySettings = LibrarySettings()
    playback: PlaybackSettings = PlaybackSettings()


@lru_cache
def get_settings() -> Settings:
    return Settings()
