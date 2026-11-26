import os
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


def _default_trickplay_workers() -> int:
    return max(1, min(8, (os.cpu_count() or 2) // 2))


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
    """Seconds between seek-bar thumbnails. Jellyfin's "Interval" setting (10 s by
    default) for the thumbnails it saved next to videos: ones whose sheet count
    doesn't fit this interval are ignored. Driftwood makes its own at it too."""
    trickplay_generate: bool = True
    """Make seek-bar thumbnails for videos that have none: as soon as a download is
    imported, and when a video is first played. They're saved next to the video the
    way Jellyfin saves them, so the library folders need to be writable."""
    trickplay_width: int = Field(default=320, ge=64, le=1920)
    """Width of a generated thumbnail in pixels (Jellyfin's default)."""
    trickplay_workers: int = Field(default_factory=_default_trickplay_workers, ge=1)
    """ffmpeg processes making thumbnail sheets at once, each one whole sheet. They
    run at a low CPU priority; the default is half the CPU cores, at most 8."""


class PathMapping(BaseModel):
    remote: str
    """A path prefix as qBittorrent reports it, e.g. `/downloads` inside its container."""
    local: Path
    """Where Driftwood sees that same directory."""


class QbittorrentSettings(BaseModel):
    url: str
    """WebUI address, e.g. `http://localhost:8080`."""
    api_key: str = ""
    """A WebUI API key (`qbt_...`, qBittorrent 5.2+: Options → WebUI → API Key → Generate),
    sent as a Bearer token. Leave empty when qBittorrent skips authentication for Driftwood's
    address."""
    category: str = "driftwood"
    """Every torrent Driftwood adds gets this category (created when missing)."""
    save_path: str | None = None
    """Download directory as qBittorrent sees it; None uses the category's or qBittorrent's
    default."""
    path_mappings: list[PathMapping] = Field(default_factory=list)
    """Translate qBittorrent's paths when it runs elsewhere (a container, another host)."""
    timeout_seconds: float = 15


class DownloadsSettings(BaseModel):
    qbittorrent: QbittorrentSettings | None = None
    """Set `DRIFTWOOD_DOWNLOADS__QBITTORRENT__URL` (and credentials) to enable downloading."""
    poll_interval_seconds: float = Field(default=2, gt=0)
    """How often active torrents are checked for completion."""
    subtitles: bool = True
    """Import subtitle files that come with the video (`.srt`, `.ass`, ...) next to it."""
    fallback: Literal["copy", "move"] = "copy"
    """When a hardlink isn't possible (another filesystem): copy, which keeps the torrent
    seeding, or move, which saves space but leaves qBittorrent with missing files."""
    cancel_limit: float = Field(default=0.07, ge=0, le=1)
    """Share of a torrent (0..1) beyond which it can no longer be cancelled. TorrentLeech
    counts a hit and run for any torrent downloaded 10% or more that isn't seeded back to 1:1,
    so cancelling past that only leaves data that must be seeded anyway; the margin covers
    what arrives between the check and the removal."""
    movies_root: str | None = None
    """Library root (by name) that movies go to; the first `movies` root when unset."""
    tv_root: str | None = None
    """Library root (by name) that episodes go to; the first `tv` root when unset."""


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
    downloads: DownloadsSettings = DownloadsSettings()


@lru_cache
def get_settings() -> Settings:
    return Settings()
