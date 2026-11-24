"""
In-memory title index over every TMDB movie and TV title, in two tiers.

- **Head** - the `head_size` most popular titles. Ranked exactly like
  MediaManager's autocomplete (`rank_entries`): prefix, acronym *and*
  fuzzy/typo matching. Fuzzy matching is a linear scan, which is why it is
  limited to this bounded set.
- **Tail** - everything else (the large majority of titles, most of them
  obscure). Held in compact sorted arrays and searched only by exact
  structure (title prefix, optionally skipping a leading article, or exact
  acronym) via binary search, so its size barely affects per-keystroke cost.

Popularity rank is mapped onto one monotonic `popularity_pct` scale across
both tiers (head: `TAIL_PCT_CEILING`..100, tail: 0..`TAIL_PCT_CEILING`).

Tail matches are deliberately scored in the *fuzzy* tier (with their low
percentile) rather than the structural one: a popular title matching the
query's structure always wins, a strong typo match on a popular title still
outranks an obscure one, but an obscure title matching the query exactly
outranks weak near-misses - so it surfaces once the query is specific enough.
"""

import gzip
import json
import logging
from bisect import bisect_left
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import overload

import numpy as np
from rapidfuzz import fuzz

from driftwood.config import TitleIndexSettings
from driftwood.media.schemas import MediaType
from driftwood.titles.normalize import normalize_title
from driftwood.titles.ranking import (
    ACRONYM_PROXY_SCORE,
    ScoredEntry,
    derive_title_fields,
    fuzzy_tier_score,
    is_acronym_query,
    rank_entries,
    strip_leading_article,
)

log = logging.getLogger(__name__)

TAIL_PCT_CEILING = 10.0
_ACRONYM_DTYPE = "<U6"  # longer acronyms can never match an acronym query
_PREFIX_SENTINEL = "\U0010ffff"
_MEDIA_TYPES: tuple[MediaType, ...] = tuple(MediaType)
_MEDIA_CODE = {media_type: code for code, media_type in enumerate(_MEDIA_TYPES)}


@dataclass(frozen=True, slots=True)
class TitleMatch:
    """What a search over the index yields: enough to identify and fetch the title."""

    media_type: MediaType
    id: int
    title: str
    popularity: float


@dataclass(slots=True)
class HeadEntry:
    match: TitleMatch
    normalized: str
    acronym_full: str
    acronym_no_article: str
    popularity_pct: float


class _StringTable(Sequence[str]):
    """
    An immutable list of strings packed into one UTF-8 buffer plus offsets.
    Holding the tail's ~1.4M titles as individual `str` objects would cost
    several times as much memory (and fragment the heap while building).
    """

    def __init__(self, strings: Iterable[str]) -> None:
        encoded = [string.encode() for string in strings]
        self._data = b"".join(encoded)
        lengths = np.fromiter((len(item) for item in encoded), dtype=np.int64, count=len(encoded))
        self._offsets = np.zeros(len(encoded) + 1, dtype=np.int64)
        np.cumsum(lengths, out=self._offsets[1:])

    def __len__(self) -> int:
        return len(self._offsets) - 1

    @overload
    def __getitem__(self, index: int) -> str: ...
    @overload
    def __getitem__(self, index: slice) -> list[str]: ...
    def __getitem__(self, index: int | slice) -> str | list[str]:
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(len(self)))]
        start, end = self._offsets[index], self._offsets[index + 1]
        return self._data[start:end].decode()


class _SortedKeys:
    """Sorted normalized-title keys, each mapped back to a tail position."""

    def __init__(self, pairs: list[tuple[str, int]]) -> None:
        pairs.sort()
        self.keys = _StringTable(key for key, _ in pairs)
        self.positions = np.fromiter((pos for _, pos in pairs), dtype=np.int32, count=len(pairs))

    def prefix_range(self, prefix: str) -> np.ndarray:
        start = bisect_left(self.keys, prefix)
        end = bisect_left(self.keys, prefix + _PREFIX_SENTINEL, lo=start)
        return self.positions[start:end]


class _SortedAcronyms:
    def __init__(self, pairs: list[tuple[str, int]]) -> None:
        pairs.sort()
        self.keys = np.array([key for key, _ in pairs], dtype=_ACRONYM_DTYPE)
        self.positions = np.fromiter((pos for _, pos in pairs), dtype=np.int32, count=len(pairs))

    def exact(self, acronym: str) -> np.ndarray:
        start = np.searchsorted(self.keys, acronym, side="left")
        end = np.searchsorted(self.keys, acronym, side="right")
        return self.positions[start:end]


def _most_popular(positions: np.ndarray, limit: int) -> np.ndarray:
    """The `limit` most popular tail positions (positions are popularity ranks)."""
    if len(positions) <= limit:
        return positions
    return np.partition(positions, limit - 1)[:limit]


class _Tail:
    def __init__(self, rows: list[tuple[MediaType, int, str, float]]) -> None:
        self.size = len(rows)
        self.media_codes = np.fromiter((_MEDIA_CODE[r[0]] for r in rows), dtype=np.int8)
        self.ids = np.fromiter((r[1] for r in rows), dtype=np.int32)
        self.popularity = np.fromiter((r[3] for r in rows), dtype=np.float32)
        self.titles = _StringTable(r[2] for r in rows)

        full_keys: list[tuple[str, int]] = []
        stripped_keys: list[tuple[str, int]] = []
        acronyms: list[tuple[str, int]] = []
        for position, (_, _, title, _) in enumerate(rows):
            normalized, acronym_full, acronym_no_article = derive_title_fields(title)
            if not normalized:
                continue
            full_keys.append((normalized, position))
            stripped = strip_leading_article(normalized)
            if stripped != normalized:
                stripped_keys.append((stripped, position))
            for acronym in {acronym_full, acronym_no_article}:
                if 2 <= len(acronym) <= 6:
                    acronyms.append((acronym, position))

        self.full_keys = _SortedKeys(full_keys)
        self.stripped_keys = _SortedKeys(stripped_keys)
        self.acronyms = _SortedAcronyms(acronyms)

    def popularity_pct(self, position: int) -> float:
        return TAIL_PCT_CEILING * (1 - position / self.size)

    def match(self, position: int) -> TitleMatch:
        return TitleMatch(
            media_type=_MEDIA_TYPES[self.media_codes[position]],
            id=int(self.ids[position]),
            title=self.titles[position],
            popularity=float(self.popularity[position]),
        )

    def search(self, normalized_query: str, limit: int) -> list[ScoredEntry[TitleMatch]]:
        if self.size == 0:
            return []

        prefix_hits = np.concatenate(
            [
                _most_popular(self.full_keys.prefix_range(normalized_query), limit),
                _most_popular(self.stripped_keys.prefix_range(normalized_query), limit),
            ]
        )
        acronym_hits = (
            _most_popular(self.acronyms.exact(normalized_query), limit)
            if is_acronym_query(normalized_query)
            else np.empty(0, dtype=np.int32)
        )

        fuzzy_scores: dict[int, float] = {}
        for position in acronym_hits.tolist():
            fuzzy_scores[position] = ACRONYM_PROXY_SCORE
        for position in prefix_hits.tolist():
            normalized = normalize_title(self.titles[position])
            fuzzy_scores[position] = fuzz.token_set_ratio(normalized_query, normalized)

        return [
            ScoredEntry(
                entry=self.match(position),
                is_structural=False,
                tier_score=fuzzy_tier_score(self.popularity_pct(position), score),
            )
            for position, score in fuzzy_scores.items()
        ]


class TitleIndex:
    """An immutable, loaded snapshot of the title index."""

    def __init__(self, rows: list[tuple[MediaType, int, str, float]], head_size: int) -> None:
        """
        :param rows: (media_type, id, title, popularity), most popular first.
        """
        head_rows, tail_rows = rows[:head_size], rows[head_size:]
        self.head: list[HeadEntry] = []
        for position, (media_type, entry_id, title, popularity) in enumerate(head_rows):
            normalized, acronym_full, acronym_no_article = derive_title_fields(title)
            pct = TAIL_PCT_CEILING + (100 - TAIL_PCT_CEILING) * (1 - position / len(head_rows))
            self.head.append(
                HeadEntry(
                    match=TitleMatch(media_type, entry_id, title, popularity),
                    normalized=normalized,
                    acronym_full=acronym_full,
                    acronym_no_article=acronym_no_article,
                    popularity_pct=pct,
                )
            )
        self.head_titles = [entry.normalized for entry in self.head]
        self.tail = _Tail(tail_rows)

    def __len__(self) -> int:
        return len(self.head) + self.tail.size

    def search(self, query: str, settings: TitleIndexSettings) -> list[ScoredEntry[TitleMatch]]:
        """Best matches for `query` across both tiers, best first, at most `max_results`."""
        normalized_query = normalize_title(query)
        if not normalized_query:
            return []

        head = rank_entries(
            self.head,
            self.head_titles,
            normalized_query,
            score_cutoff=settings.score_cutoff,
            candidate_limit=settings.candidate_limit,
        )
        results: list[ScoredEntry[TitleMatch]] = [
            ScoredEntry(item.entry.match, item.is_structural, item.tier_score) for item in head
        ]
        if len(normalized_query) >= settings.tail_min_query_length:
            results.extend(self.tail.search(normalized_query, settings.tail_candidate_limit))

        results.sort(key=lambda item: item.sort_key, reverse=True)
        return results[: settings.max_results]

    @classmethod
    def load(cls, path: Path, head_size: int) -> "TitleIndex":
        """Loads an index file written by `driftwood.titles.download` (blocking)."""
        rows: list[tuple[MediaType, int, str, float]] = []
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                if not (line := line.strip()):
                    continue
                row = json.loads(line)
                rows.append((MediaType(row["m"]), row["id"], row["t"], row["p"]))
        index = cls(rows, head_size)
        log.info("Loaded title index: %d head + %d tail entries", len(index.head), index.tail.size)
        return index
