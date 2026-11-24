from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from driftwood.indexers.base import Indexer

INDEXERS: dict[str, type["Indexer"]] = {}


def register[T: type["Indexer"]](cls: T) -> T:
    INDEXERS[cls.id] = cls
    return cls
