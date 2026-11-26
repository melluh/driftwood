from datetime import datetime

from pydantic import Field

from driftwood.media.schemas import MediaSummary, Schema


class WatchProgressUpdate(Schema):
    """Where the player is now. Series send the episode; movies leave it out."""

    season: int | None = Field(default=None, ge=0)
    episode: int | None = Field(default=None, ge=1)
    position: float = Field(ge=0)
    """Seconds."""
    duration: float = Field(gt=0)
    """Seconds."""


class WatchProgress(Schema):
    season: int | None = None
    episode: int | None = None
    position: float
    """Seconds."""
    duration: float
    """Seconds."""
    completed: bool
    """Watched to the end at some point (stays set while rewatching)."""
    resume_at: float
    """Where to start next time: `position` while part-way through, else 0."""
    updated_at: datetime


class ContinueWatching(Schema):
    """A title to pick up again: a movie or episode part-way through, or a series' next episode."""

    media: MediaSummary
    season: int | None = None
    episode: int | None = None
    episode_title: str | None = None
    position: float
    """Seconds to resume at; 0 for an episode that's up next."""
    duration: float | None = None
    """Seconds; None when an up-next episode's runtime isn't known."""
    up_next: bool = False
    """The episode after the one last finished, rather than one left part-way."""
    updated_at: datetime
    """When the user last watched this title."""
