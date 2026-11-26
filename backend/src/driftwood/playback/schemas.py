from typing import Literal

from pydantic import Field

from driftwood.media.schemas import MediaType, Schema


class PlaybackCapabilities(Schema):
    """What the browser reported it can decode (`MediaSource.isTypeSupported`)."""

    hevc: bool = False
    hevc_main10: bool = False


class PlaybackRequest(Schema):
    media_type: MediaType
    media_id: int = Field(gt=0)
    season: int | None = Field(default=None, ge=0)
    episode: int | None = Field(default=None, ge=1)
    file_id: int | None = Field(default=None, gt=0)
    """A specific version; the best one this browser can play when omitted."""
    capabilities: PlaybackCapabilities = Field(default_factory=PlaybackCapabilities)


class PlaybackVersion(Schema):
    file_id: int
    name: str
    """The file name."""
    height: int | None = None
    source: str | None = None
    video_codec: str | None = None
    hdr_flags: list[str] = Field(default_factory=list)
    size: int
    playable: bool
    problem: str | None = None
    """Why this browser can't play it."""
    selected: bool = False


class PlaybackAudioTrack(Schema):
    id: int
    language: str | None = None
    title: str | None = None
    codec: str
    channels: int | None = None
    default: bool = False
    url: str
    """HLS playlist with this audio track (the file itself for direct play)."""


class PlaybackSubtitleTrack(Schema):
    id: int
    language: str | None = None
    title: str | None = None
    forced: bool = False
    hearing_impaired: bool = False
    external: bool = False
    """A subtitle file next to the video rather than a stream inside it."""
    format: Literal["webvtt", "ass", "pgs"]
    """How to render `url`: WebVTT text, styled ASS, or PGS pictures (a `.sup` file)."""
    url: str
    text_url: str | None = None
    """For ASS: the same subtitles as plain WebVTT, for when styled rendering fails."""


class PlaybackTrickplay(Schema):
    """Seek-bar preview thumbnails, tiled left to right, top to bottom on each sheet."""

    sheets: list[str]
    """JPEG URLs, each a grid of `columns` x `rows` thumbnails."""
    columns: int
    rows: int
    width: int
    """Of one thumbnail, in pixels."""
    height: int
    interval: float
    """Seconds between thumbnails: thumbnail `n` shows `n * interval`."""
    count: int


class PlaybackSession(Schema):
    id: str
    mode: Literal["direct", "hls"]
    duration: float
    audio: list[PlaybackAudioTrack]
    url: str
    """Where to start: the default audio track's URL."""
    subtitles: list[PlaybackSubtitleTrack]
    fonts: list[str]
    """Fonts embedded in the file, for rendering its ASS subtitles."""
    trickplay: PlaybackTrickplay | None = None
    """Thumbnails Jellyfin saved next to the file, when it has them."""


class PlaybackOffer(Schema):
    session: PlaybackSession | None
    """None when no version of the title can be played in this browser."""
    versions: list[PlaybackVersion]
    problem: str | None = None
