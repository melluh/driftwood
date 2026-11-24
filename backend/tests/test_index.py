from tests.conftest import make_index, settings

POPULAR = ["The Matrix", "Star Wars", "Game of Thrones", "Jurassic Park"]
OBSCURE = ["Matrix of the Obscure Valley", "The Kazakh Steppe Chronicles", "Starfield Diaries"]


def titles(results) -> list[str]:
    return [item.entry.title for item in results]


def test_obscure_title_is_found_by_prefix() -> None:
    index = make_index(POPULAR + OBSCURE, head_size=len(POPULAR))
    assert "The Kazakh Steppe Chronicles" in titles(index.search("kazakh steppe", settings()))


def test_obscure_title_is_found_by_prefix_after_article() -> None:
    index = make_index(POPULAR + OBSCURE, head_size=len(POPULAR))
    assert titles(index.search("kazakh", settings()))[0] == "The Kazakh Steppe Chronicles"


def test_popular_structural_match_ranks_above_obscure_one() -> None:
    index = make_index(POPULAR + OBSCURE, head_size=len(POPULAR))
    found = titles(index.search("star", settings()))
    assert found.index("Star Wars") < found.index("Starfield Diaries")


def test_popular_typo_match_ranks_above_obscure_prefix_match() -> None:
    index = make_index(POPULAR + OBSCURE, head_size=len(POPULAR))
    assert titles(index.search("matrx", settings()))[0] == "The Matrix"


def test_obscure_acronym_match() -> None:
    index = make_index(POPULAR + OBSCURE, head_size=len(POPULAR))
    assert "The Kazakh Steppe Chronicles" in titles(index.search("ksc", settings()))


def test_short_queries_do_not_search_the_tail() -> None:
    index = make_index(POPULAR + OBSCURE, head_size=len(POPULAR))
    assert "Starfield Diaries" not in titles(index.search("st", settings()))


def test_results_are_capped() -> None:
    index = make_index([f"Alpha {n}" for n in range(50)], head_size=10)
    assert len(index.search("alpha", settings(max_results=7))) == 7


def test_tail_lookup_handles_unicode_titles() -> None:
    index = make_index([*POPULAR, "Amélie", "千と千尋の神隠し"], head_size=len(POPULAR))
    assert titles(index.search("amelie", settings()))[0] == "Amélie"
    assert titles(index.search("千と千尋", settings()))[0] == "千と千尋の神隠し"
