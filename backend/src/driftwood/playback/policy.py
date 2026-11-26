"""Which files a browser can play, and how: as they are, remuxed, or not at all.

Video is never re-encoded (too slow for a home server), so a file is playable
only when the browser can decode its video stream. Audio is cheap to encode and
becomes AAC unless it already is.
"""

from dataclasses import dataclass
from typing import Any

from driftwood.playback.probe import MediaProbe
from driftwood.playback.process import AUDIO_DECODERS

PLAYABLE_SUFFIXES = frozenset({".mkv", ".mp4", ".m4v"})
"""Files playback opens at all; anything else is never handed to ffmpeg."""
_EIGHT_BIT_420 = {"yuv420p", "yuvj420p"}
_TEN_BIT_420 = {"yuv420p10le"}
_DIRECT_AUDIO = {"aac", "mp3"}
_DIRECT_SUFFIXES = {".mp4", ".m4v"}


@dataclass(frozen=True)
class ClientCapabilities:
    hevc: bool = False
    hevc_main10: bool = False


@dataclass(frozen=True)
class AudioOutput:
    codec: str
    """`copy`, or the encoder ffmpeg should use."""
    channels: int | None = None
    bitrate: str | None = None


def _dolby_vision_profile(stream: dict[str, Any]) -> int | None:
    for side_data in stream.get("side_data_list") or []:
        if isinstance(side_data, dict) and "dv_profile" in side_data:
            try:
                return int(side_data["dv_profile"])
            except (TypeError, ValueError):
                return None
    return None


def video_problem(stream: dict[str, Any], capabilities: ClientCapabilities) -> str | None:
    """Why this browser can't decode the video stream, or None when it can."""
    codec = stream.get("codec_name")
    pix_fmt = stream.get("pix_fmt")
    if codec == "h264":
        if pix_fmt in _EIGHT_BIT_420:
            return None
        return "10-bit or 4:4:4 H.264 video can't be decoded by browsers."
    if codec == "hevc":
        if not capabilities.hevc:
            return "This browser can't play HEVC (H.265) video."
        if _dolby_vision_profile(stream) == 5:
            return "Dolby Vision profile 5 video has no HDR10 layer browsers can show."
        if pix_fmt in _EIGHT_BIT_420:
            return None
        if pix_fmt in _TEN_BIT_420:
            if capabilities.hevc_main10:
                return None
            return "This browser can't play 10-bit HEVC video."
        return f"HEVC video in {pix_fmt or 'an unknown pixel format'} can't be decoded by browsers."
    name = str(codec or "unknown").upper()
    return f"{name} video isn't supported; H.264 and HEVC are."


def can_decode_audio(stream: dict[str, Any]) -> bool:
    """Whether ffmpeg may decode (or copy) this audio track: see `process.AUDIO_DECODERS`."""
    return stream.get("codec_name") in AUDIO_DECODERS


def audio_output(stream: dict[str, Any]) -> AudioOutput:
    if stream.get("codec_name") == "aac" and int(stream.get("channels") or 2) <= 6:
        return AudioOutput("copy")
    channels = int(stream.get("channels") or 2)
    if channels <= 2:
        return AudioOutput("aac", 2, "192k")
    return AudioOutput("aac", 6, "448k")


def can_play_directly(probe: MediaProbe, suffix: str) -> bool:
    """Whether the browser can play the file as it is, seeking with byte ranges."""
    video = probe.video
    audio = probe.of_type("audio")
    return (
        suffix.casefold() in _DIRECT_SUFFIXES
        and "mp4" in probe.format_name
        and video is not None
        and video.get("codec_name") == "h264"
        and video.get("pix_fmt") in _EIGHT_BIT_420
        and len(audio) <= 1
        and all(stream.get("codec_name") in _DIRECT_AUDIO for stream in audio)
    )
