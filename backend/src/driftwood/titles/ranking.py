"""
Pool-agnostic title ranking, ported from MediaManager's `common/ranking.py`.

Candidates are split into two tiers rather than blending every signal into
one formula:

- "Structural" matches (the query is a title prefix, optionally skipping a
  leading article, or matches the title's acronym) already have relevance
  established by that relationship, so popularity decides which one the user
  most likely means; the fuzzy score only breaks near-ties.
- Everything else is a typo / near-miss, so closeness of the text match
  dominates and popularity only breaks ties.
"""

from dataclasses import dataclass
from typing import Protocol

from rapidfuzz import fuzz, process

from driftwood.titles.normalize import normalize_title

ARTICLES = ("the", "a", "an")
ACRONYM_PROXY_SCORE = 90.0
STRUCTURAL_FUZZY_WEIGHT = 0.05


class Rankable(Protocol):
    normalized: str
    acronym_full: str
    acronym_no_article: str
    popularity_pct: float


@dataclass(slots=True)
class ScoredEntry[T]:
    entry: T
    is_structural: bool
    tier_score: float

    @property
    def sort_key(self) -> tuple[bool, float]:
        return self.is_structural, self.tier_score


def _acronym(tokens: list[str]) -> str:
    return "".join(token[0] for token in tokens if token)


def strip_leading_article(normalized: str) -> str:
    """`normalized` without one leading the/a/an, or unchanged if it has none."""
    head, _, rest = normalized.partition(" ")
    return rest if rest and head in ARTICLES else normalized


def derive_title_fields(title: str) -> tuple[str, str, str]:
    """
    Normalizes `title` and derives its two acronym variants: initials of every
    token, and the same with one leading article stripped first. This is what
    lets "lotr" match "The Lord of the Rings".

    :return: (normalized, acronym_full, acronym_no_article).
    """
    normalized = normalize_title(title)
    tokens = normalized.split(" ") if normalized else []
    acronym_full = _acronym(tokens)
    no_article_tokens = tokens[1:] if tokens and tokens[0] in ARTICLES else tokens
    return normalized, acronym_full, _acronym(no_article_tokens)


def is_acronym_query(normalized_query: str) -> bool:
    return normalized_query.isalpha() and 2 <= len(normalized_query) <= 6


def is_title_prefix(normalized_title: str, normalized_query: str) -> bool:
    """
    Whether the query is a prefix of the title, allowing one leading article in
    the title to be skipped ("matrix" matches "The Matrix", but "star" does not
    match "The Tonight Show Starring Jimmy Fallon").
    """
    return normalized_title.startswith(normalized_query) or strip_leading_article(
        normalized_title
    ).startswith(normalized_query)


def structural_tier_score(popularity_pct: float, fuzzy_score: float) -> float:
    return popularity_pct + STRUCTURAL_FUZZY_WEIGHT * fuzzy_score


def fuzzy_tier_score(popularity_pct: float, fuzzy_score: float) -> float:
    return 0.75 * fuzzy_score + 0.25 * popularity_pct


def rank_entries[T: Rankable](
    entries: list[T],
    normalized_titles: list[str],
    query: str,
    *,
    score_cutoff: float,
    candidate_limit: int,
) -> list[ScoredEntry[T]]:
    """
    Ranks `entries` against `query`, best first.

    Structural status is determined exhaustively, independent of
    `score_cutoff`, so a genuine prefix match is never dropped for scoring low
    on raw text similarity ("borat" vs. the film's very long official title).

    Two scorers do two jobs: plain `ratio` decides fuzzy *inclusion* (it is
    length-sensitive, so a short title can't pass for being one word of a long
    query), and `token_set_ratio` *ranks* the survivors (so "oak street" scores
    well against "The End of Oak Street").

    :param normalized_titles: `entries[i].normalized`, as a flat parallel list
        for rapidfuzz.
    :param candidate_limit: How many fuzzy-only candidates rapidfuzz considers.
    """
    normalized_query = normalize_title(query)
    if not normalized_query or not entries:
        return []

    acronym_query = is_acronym_query(normalized_query)
    structural_indices: set[int] = set()
    scored: dict[int, float] = {}

    for index, entry in enumerate(entries):
        is_prefix_hit = is_title_prefix(entry.normalized, normalized_query)
        is_acronym_hit = acronym_query and normalized_query in (
            entry.acronym_full,
            entry.acronym_no_article,
        )
        if not (is_prefix_hit or is_acronym_hit):
            continue
        structural_indices.add(index)
        scored[index] = (
            fuzz.token_set_ratio(normalized_query, entry.normalized)
            if is_prefix_hit
            else ACRONYM_PROXY_SCORE
        )

    matches = process.extract(
        normalized_query,
        normalized_titles,
        scorer=fuzz.ratio,
        score_cutoff=score_cutoff,
        limit=candidate_limit,
    )
    for _choice, _score, index in matches:
        if index not in scored:
            scored[index] = fuzz.token_set_ratio(normalized_query, normalized_titles[index])

    ranked: list[ScoredEntry[T]] = []
    for index, fuzzy_score in scored.items():
        entry = entries[index]
        is_structural = index in structural_indices
        score_fn = structural_tier_score if is_structural else fuzzy_tier_score
        ranked.append(
            ScoredEntry(
                entry=entry,
                is_structural=is_structural,
                tier_score=score_fn(entry.popularity_pct, fuzzy_score),
            )
        )

    ranked.sort(key=lambda item: item.sort_key, reverse=True)
    return ranked
