"""
Torrent indexer search. Callers use `Indexer` / `IndexerManager` with
`SearchQuery` → `Release`; see docs/indexer-design.md.
"""

from driftwood.indexers import torrentleech  # noqa: F401  (registers the indexer)
from driftwood.indexers.registry import INDEXERS, register

__all__ = ["INDEXERS", "register"]
