from dataclasses import dataclass

from driftwood.titles.ranking import derive_title_fields, is_title_prefix, rank_entries


@dataclass
class Entry:
    title: str
    normalized: str
    acronym_full: str
    acronym_no_article: str
    popularity_pct: float


def entries(*titles_with_pct: tuple[str, float]) -> list[Entry]:
    return [Entry(title, *derive_title_fields(title), pct) for title, pct in titles_with_pct]


def rank(pool: list[Entry], query: str) -> list[str]:
    ranked = rank_entries(
        pool, [e.normalized for e in pool], query, score_cutoff=60, candidate_limit=300
    )
    return [item.entry.title for item in ranked]


def test_derive_title_fields_acronyms() -> None:
    normalized, full, no_article = derive_title_fields("The Lord of the Rings!")
    assert normalized == "the lord of the rings"
    assert (full, no_article) == ("tlotr", "lotr")


def test_prefix_skips_one_leading_article_only() -> None:
    assert is_title_prefix("the matrix", "matrix")
    assert not is_title_prefix("the tonight show starring jimmy fallon", "star")


def test_typo_query_still_ranks_correct_title_top() -> None:
    pool = entries(("Jurassic Park", 50), ("Juniper", 60), ("Park Life", 70))
    assert rank(pool, "jurasic prk")[0] == "Jurassic Park"


def test_acronym_without_article_matches_full_title() -> None:
    pool = entries(("The Lord of the Rings", 80), ("Lottery", 90))
    assert rank(pool, "lotr")[0] == "The Lord of the Rings"


def test_structural_prefix_outranks_fuzzy_match() -> None:
    pool = entries(("Star Trek", 40), ("Tar Trek", 99))
    assert rank(pool, "star tr")[0] == "Star Trek"


def test_popularity_decides_between_structural_matches() -> None:
    pool = entries(("The Matrix Revisited", 20), ("The Matrix", 95))
    assert rank(pool, "the matrix")[0] == "The Matrix"


def test_score_cutoff_excludes_irrelevant_entries() -> None:
    pool = entries(("Here", 99))
    assert rank(pool, "very weird search query goes here") == []


def test_long_title_found_by_short_prefix() -> None:
    pool = entries(("Borat: Cultural Learnings of America for Make Benefit Glorious Nation", 50))
    assert rank(pool, "borat") != []
