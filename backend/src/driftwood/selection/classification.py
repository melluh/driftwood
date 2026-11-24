"""
Release-name classification, ported from MediaManager's
`media_manager/indexer/classification.py`. guessit is the authoritative parser;
the regexes below patch its known gaps (AV1, HDR10+, a few scene language tags).
"""

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from guessit import guessit

_AV1_PATTERN = re.compile(r"\bav1\b", re.IGNORECASE)
_HDR10PLUS_PATTERN = re.compile(r"\bhdr10[\s._-]*(?:\+|plus\b)", re.IGNORECASE)
_HDR10_PATTERN = re.compile(r"\bhdr10\b", re.IGNORECASE)
_NORDIC_PATTERN = re.compile(r"\bnordic\b", re.IGNORECASE)
_GERMAN_DL_PATTERN = re.compile(r"\bgerman[ ._-]?dl\b", re.IGNORECASE)
_DUBBED_PATTERN = re.compile(r"\bdubbed\b", re.IGNORECASE)

_SOURCE_BLURAY = {"blu-ray", "ultra hd blu-ray"}

LOW_QUALITY_SOURCES = frozenset(
    {
        "camera",
        "hd camera",
        "telesync",
        "hd telesync",
        "telecine",
        "hd telecine",
        "workprint",
        "screener",
    }
)
"""guessit sources that are never worth watching: cams, telesyncs, screeners."""

_CODEC_MAP = {
    "h.264": "h264",
    "avc": "h264",
    "h.265": "h265",
    "hevc": "h265",
    "xvid": "xvid",
    "divx": "xvid",
}

_AUDIO_CODEC_MAP = {
    "dolby digital plus": "ddp",
    "dolby digital": "dd",
    "dolby truehd": "truehd",
    "dts-hd": "dts",
    "dts": "dts",
    "opus": "opus",
    "aac": "aac",
    "flac": "flac",
    "pcm": "pcm",
}


@dataclass(frozen=True)
class ReleaseAttributes:
    resolution: str | None = None
    """`2160p`, `1080p`, `720p`, `480p`, ..."""
    source: str | None = None
    """`remux`, `bluray-encode`, `web-dl`, `webrip`, `hdtv`, `dvd`; `low-quality` = cam/ts/scr."""
    codec: str | None = None
    """`h264`, `h265`, `av1`, `xvid`."""
    hdr_flags: tuple[str, ...] = ()
    """Any of `hdr10`, `hdr10plus`, `dv`; empty means SDR."""
    audio_codecs: tuple[str, ...] = ()
    language_variant: str | None = None
    """`multi`, `nordic`, `german_dl`, `dubbed`, or None for the original language."""
    release_group: str | None = None
    season: int | None = None
    episodes: tuple[int, ...] = field(default_factory=tuple)
    """Episode numbers in the release; empty for movies and season packs."""


def _as_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def _as_ints(value: object) -> tuple[int, ...]:
    values = value if isinstance(value, list) else [] if value is None else [value]
    return tuple(v for v in values if isinstance(v, int))


def _derive_source(source: object, other_tokens: list[str]) -> str | None:
    other_lower = {t.lower() for t in other_tokens}
    sources = [s.lower() for s in _as_list(source)]
    if any(s in LOW_QUALITY_SOURCES for s in sources):
        return "low-quality"
    source_lower = sources[0] if sources else ""

    if source_lower in _SOURCE_BLURAY:
        return "remux" if "remux" in other_lower else "bluray-encode"
    if source_lower == "web":
        return "webrip" if "rip" in other_lower else "web-dl"
    if source_lower == "hdtv":
        return "hdtv"
    if source_lower == "dvd":
        return "dvd"
    return None


def _derive_codec(video_codec: object, title: str) -> str | None:
    if isinstance(video_codec, str) and (mapped := _CODEC_MAP.get(video_codec.lower())):
        return mapped
    if _AV1_PATTERN.search(title):
        return "av1"
    return None


def _derive_hdr_flags(other_tokens: list[str], title: str) -> tuple[str, ...]:
    other_lower = {t.lower() for t in other_tokens}
    flags: list[str] = []
    if "dolby vision" in other_lower:
        flags.append("dv")
    # Checked against the raw title: guessit sometimes misses "HDR10" glued to "Plus"/"+".
    if _HDR10PLUS_PATTERN.search(title):
        flags.append("hdr10plus")
    elif "hdr10" in other_lower or _HDR10_PATTERN.search(title):
        flags.append("hdr10")
    return tuple(flags)


def _derive_audio(audio_codec: object, audio_profile: object) -> tuple[str, ...]:
    tokens = _as_list(audio_codec)
    codecs: list[str] = []
    has_atmos = False
    for token in tokens:
        token_lower = token.lower()
        if "atmos" in token_lower:
            has_atmos = True
            continue
        mapped = _AUDIO_CODEC_MAP.get(token_lower)
        if mapped and mapped not in codecs:
            codecs.append(mapped)
    if (
        isinstance(audio_profile, str)
        and "master audio" in audio_profile.lower()
        and "dts" not in codecs
        and any("dts" in t.lower() for t in tokens)
    ):
        codecs.append("dts")
    if has_atmos:
        codecs.append("atmos")
    return tuple(codecs)


def _derive_language_variant(title: str, language: object) -> str | None:
    if _NORDIC_PATTERN.search(title):
        return "nordic"
    if _GERMAN_DL_PATTERN.search(title):
        return "german_dl"
    if _DUBBED_PATTERN.search(title):
        return "dubbed"
    languages = _as_list(language)
    if len(languages) > 1 or any(lang.lower() == "mul" for lang in languages):
        return "multi"
    return None


@lru_cache(maxsize=8192)
def _guess(title: str) -> dict[str, Any]:
    return dict(guessit(title))


@lru_cache(maxsize=8192)
def classify_release(title: str) -> ReleaseAttributes:
    """Parse a release title into structured attributes. Synchronous and CPU-bound (~5 ms)."""
    guess = _guess(title)
    other_tokens = _as_list(guess.get("other"))
    season = guess.get("season")
    return ReleaseAttributes(
        resolution=guess.get("screen_size"),
        source=_derive_source(guess.get("source"), other_tokens),
        codec=_derive_codec(guess.get("video_codec"), title),
        hdr_flags=_derive_hdr_flags(other_tokens, title),
        audio_codecs=_derive_audio(guess.get("audio_codec"), guess.get("audio_profile")),
        language_variant=_derive_language_variant(title, guess.get("language")),
        release_group=guess.get("release_group"),
        season=season if isinstance(season, int) else None,
        episodes=_as_ints(guess.get("episode")),
    )
