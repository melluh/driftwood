"""
Extracts subtitle and audio languages from a release's NFO.

NFOs come in two shapes, often mixed: a MediaInfo dump (`Text #1` sections
with `Language : English`, `Forced : No`), and scene-style key/value lines
(`Subtitles......: English, Dutch, Swedish`), frequently inside ASCII art.
"""

import re
from dataclasses import dataclass
from functools import lru_cache

from babelfish import Error as BabelfishError
from babelfish import Language

_SECTION = re.compile(
    r"^[^\w\n]*(general|video|audio|text|menu|chapters?|image)(?:\s*#\s*\d+)?[^\w\n]*$",
    re.IGNORECASE,
)
_FIELD = re.compile(r"^[^\w\n]*([A-Za-z][\w ()/-]*?)\s*:\s*(.*?)[^\w)\n]*$")
_SCENE_SUBTITLES = re.compile(
    r"^[^\w\n]*(?:subs?|subtitles?)(?:\s+languages?)?[\s.]*[:=\-]+\s*(?P<value>.+?)[^\w)\n]*$",
    re.IGNORECASE,
)
_SCENE_AUDIO = re.compile(
    r"^[^\w\n]*(?:audio|languages?)[\s.]*[:=\-]+\s*(?P<value>.+?)[^\w)\n]*$", re.IGNORECASE
)
_LIST_SEPARATOR = re.compile(r"\s*(?:[,/|+&;]|\band\b)\s*", re.IGNORECASE)
_NONE_VALUES = {"none", "no", "n/a", "na", "-", "nope", "not included", "no subs"}
_QUALIFIERS = re.compile(r"\b(?:sdh|cc|forced|full|signs?(?: ?& ?songs)?|subs?|subtitles?)\b", re.I)
_FORCED = re.compile(r"\bforced\b", re.IGNORECASE)


@dataclass(frozen=True)
class SubtitleTrack:
    language: str
    """ISO 639-1 (`en`) when one exists, else 639-3 (`fil`), else the raw lowercased name."""
    forced: bool = False
    """Forced tracks only cover foreign-language lines, so they don't count as subtitles."""


@dataclass(frozen=True)
class NfoInfo:
    subtitles: tuple[SubtitleTrack, ...] = ()
    subtitles_known: bool = False
    """Whether the NFO says anything about subtitles. A MediaInfo dump without
    `Text` sections, or `Subtitles: None`, means there are none."""
    audio_languages: tuple[str, ...] = ()


@lru_cache(maxsize=1024)
def normalize_language(value: str) -> str | None:
    """`English`, `eng`, `en`, `English (US)`, `pt-BR` → `en` / `pt`; None if not a language."""
    text = re.sub(r"\(.*?\)|\[.*?\]", " ", value)
    text = _QUALIFIERS.sub(" ", text)
    text = re.split(r"[-_]", text.strip(), maxsplit=1)[0] if len(text.strip()) <= 6 else text
    text = " ".join(text.split()).strip(" .:-").lower()
    if not text or not re.fullmatch(r"[a-z][a-z ]*", text):
        return None
    language: Language | None = None
    try:
        if len(text) == 2:
            language = Language.fromalpha2(text)
        elif len(text) == 3:
            try:
                language = Language.fromalpha3b(text)
            except BabelfishError:
                language = Language(text)
        else:
            language = Language.fromname(text.title())
    except (BabelfishError, ValueError, KeyError):
        return None
    try:
        return language.alpha2
    except BabelfishError:
        return language.alpha3


def _split_languages(value: str) -> tuple[list[SubtitleTrack], bool]:
    """Parse `English, Dutch (Forced)`. Returns the tracks and whether `value` said "none"."""
    if value.strip(" .").lower() in _NONE_VALUES:
        return [], True
    tracks = []
    for item in _LIST_SEPARATOR.split(value):
        # "English DD5.1": fall back to the first word.
        language = normalize_language(item) or normalize_language(item.split(" ", 1)[0])
        if language:
            tracks.append(SubtitleTrack(language, forced=bool(_FORCED.search(item))))
    return tracks, False


def _dedupe[T](items: list[T]) -> tuple[T, ...]:
    return tuple(dict.fromkeys(items))


def parse_nfo(text: str) -> NfoInfo:
    subtitles: list[SubtitleTrack] = []
    audio: list[str] = []
    known = False
    has_mediainfo = False

    section: str | None = None
    fields: dict[str, str] = {}

    def close_section() -> None:
        if section == "text":
            language = normalize_language(fields.get("language", "")) or "und"
            forced = fields.get("forced", "").lower() == "yes" or bool(
                _FORCED.search(fields.get("title", ""))
            )
            subtitles.append(SubtitleTrack(language, forced))
        elif section == "audio" and (language := normalize_language(fields.get("language", ""))):
            audio.append(language)

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if header := _SECTION.match(line):
            close_section()
            section, fields = header.group(1).lower(), {}
            has_mediainfo = has_mediainfo or section in ("video", "audio", "text")
            continue
        if section is not None:
            if not line.strip():
                close_section()
                section, fields = None, {}
                continue
            if field := _FIELD.match(line):
                fields.setdefault(field.group(1).strip().lower(), field.group(2).strip())
            continue

        if match := _SCENE_SUBTITLES.match(line):
            tracks, said_none = _split_languages(match.group("value"))
            if tracks or said_none:
                subtitles.extend(tracks)
                known = True
        elif match := _SCENE_AUDIO.match(line):
            tracks, _ = _split_languages(match.group("value"))
            audio.extend(track.language for track in tracks)
    close_section()

    return NfoInfo(
        subtitles=_dedupe(subtitles),
        subtitles_known=known or has_mediainfo,
        audio_languages=_dedupe(audio),
    )


def decode_nfo(content: bytes) -> str:
    """NFOs are usually CP437 (DOS box drawing); some are UTF-8."""
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("cp437")
