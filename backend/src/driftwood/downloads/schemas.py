from datetime import datetime
from typing import Literal

from pydantic import Field

from driftwood.media.schemas import MediaType, Schema

DownloadStateName = Literal["downloading", "importing", "completed", "failed", "cancelled"]
TorrentActivity = Literal[
    "connecting", "downloading", "stalled", "paused", "checking", "complete", "unknown"
]


class StartDownload(Schema):
    media_type: MediaType
    media_id: int = Field(gt=0)
    season: int | None = Field(default=None, ge=0)
    episode: int | None = Field(default=None, ge=1)
    indexer: str = Field(max_length=64)
    guid: str = Field(max_length=128)
    """The release from the watch plan to grab."""


class DownloadStatus(Schema):
    id: int
    state: DownloadStateName
    media_type: MediaType
    media_id: int
    season: int | None
    episode: int | None
    release_title: str
    activity: TorrentActivity | None = None
    """What qBittorrent is doing while `state` is `downloading`."""
    progress: float = 0
    """0..1."""
    size: int | None = None
    """Bytes to download."""
    downloaded: int = 0
    download_speed: int = 0
    """Bytes per second."""
    eta_seconds: int | None = None
    """None while qBittorrent can't estimate it."""
    seeds: int = 0
    """Seeds connected to."""
    peers: int = 0
    error: str | None = None
    """Why it failed, or (while downloading) why progress can't be read right now."""
    can_cancel: bool = False
    """Still early enough to cancel without a hit and run on the tracker."""
    file_id: int | None = None
    """The library file to play, once completed."""
    created_at: datetime
    completed_at: datetime | None = None
