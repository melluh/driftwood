"""
Torznab standard categories (from Prowlarr's `NewznabStandardCategory.cs`) and
the mapping rules between them and an indexer's own category ids.
"""

from collections.abc import Iterable

from driftwood.indexers.models import CategoryMapping

TORZNAB: dict[int, str] = {
    1000: "Console",
    1010: "Console/NDS",
    1020: "Console/PSP",
    1030: "Console/Wii",
    1040: "Console/XBox",
    1050: "Console/XBox 360",
    1080: "Console/PS3",
    1090: "Console/Other",
    1140: "Console/XBox One",
    1180: "Console/PS4",
    2000: "Movies",
    2010: "Movies/Foreign",
    2020: "Movies/Other",
    2030: "Movies/SD",
    2040: "Movies/HD",
    2045: "Movies/UHD",
    2050: "Movies/BluRay",
    2070: "Movies/DVD",
    2080: "Movies/WEB-DL",
    3000: "Audio",
    3020: "Audio/Video",
    4000: "PC",
    4010: "PC/0day",
    4020: "PC/ISO",
    4030: "PC/Mac",
    4040: "PC/Mobile-Other",
    4050: "PC/Games",
    5000: "TV",
    5020: "TV/Foreign",
    5030: "TV/SD",
    5040: "TV/HD",
    5070: "TV/Anime",
    7000: "Books",
    7020: "Books/EBook",
    7030: "Books/Comics",
    8000: "Other",
}

MOVIES = 2000
TV = 5000


def parent(torznab_id: int) -> int:
    """The top-level category: 5040 → 5000. Parents are their own parent."""
    return torznab_id // 1000 * 1000


def with_parent(torznab_id: int) -> list[int]:
    top = parent(torznab_id)
    return [torznab_id] if top == torznab_id else [torznab_id, top]


def to_site_ids(requested: Iterable[int], mappings: Iterable[CategoryMapping]) -> list[str]:
    """
    Site category ids for a query. Asking for a parent (5000) matches every
    site category mapped to it or to one of its children (50xx). Order follows
    `mappings`; no requested categories means the indexer's `default` ones, if any.
    """
    wanted = set(requested)
    mappings = list(mappings)
    if not wanted:
        selected = [m for m in mappings if m.default]
    else:
        selected = [m for m in mappings if m.torznab_id in wanted or parent(m.torznab_id) in wanted]
    return list(dict.fromkeys(m.site_id for m in selected))


def to_torznab(site_id: str, mappings: Iterable[CategoryMapping]) -> list[int]:
    """Torznab ids for a result's site category: the mapped id(s) plus their parents."""
    ids: list[int] = []
    for mapping in mappings:
        if mapping.site_id == site_id:
            ids.extend(with_parent(mapping.torznab_id))
    return list(dict.fromkeys(ids))
