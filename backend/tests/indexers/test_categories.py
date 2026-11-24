from driftwood.indexers import categories
from driftwood.indexers.models import CategoryMapping
from driftwood.indexers.torrentleech import CATEGORIES


def test_parent_and_with_parent() -> None:
    assert categories.parent(5040) == 5000
    assert categories.parent(5000) == 5000
    assert categories.with_parent(5040) == [5040, 5000]
    assert categories.with_parent(2000) == [2000]


def test_parent_query_matches_every_child_mapping() -> None:
    assert categories.to_site_ids([5000], CATEGORIES) == ["26", "32", "27", "34", "35", "44"]


def test_child_query_matches_only_that_child() -> None:
    assert categories.to_site_ids([5040], CATEGORIES) == ["32"]
    assert categories.to_site_ids([2030], CATEGORIES) == ["8", "9", "11"]


def test_no_categories_requested_sends_none_unless_defaults() -> None:
    assert categories.to_site_ids([], CATEGORIES) == []
    defaults = (CategoryMapping("1", 2000, "a", default=True), CategoryMapping("2", 5000, "b"))
    assert categories.to_site_ids([], defaults) == ["1"]


def test_site_to_torznab_includes_parent() -> None:
    assert categories.to_torznab("32", CATEGORIES) == [5040, 5000]
    assert categories.to_torznab("15", CATEGORIES) == [2000]
    assert categories.to_torznab("999", CATEGORIES) == []
