from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from pydantic import Field

from driftwood.media.schemas import Schema


class LibraryEpisode(Schema):
    season: int
    episode: int


class LibraryFile(Schema):
    id: int
    path: str
    size: int
    resolution: str | None = None
    source: str | None = None
    codec: str | None = None
    hdr_flags: list[str] = Field(default_factory=list)
    audio_codecs: list[str] = Field(default_factory=list)
    episodes: list[LibraryEpisode] = Field(default_factory=list)


class LibraryAvailability(Schema):
    ready: bool
    files: list[LibraryFile]
    episodes: list[LibraryEpisode]


class LibraryStatus(Schema):
    state: Literal["idle", "scanning"]
    last_scan_at: datetime | None
    files: int
    unmatched: int


@dataclass
class ScanReport:
    added: int = 0
    updated: int = 0
    missing: int = 0
    removed: int = 0
    unmatched: int = 0
    skipped_roots: list[str] = field(default_factory=list)
