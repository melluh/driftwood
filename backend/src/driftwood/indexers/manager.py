import asyncio
import contextlib
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field

from driftwood.indexers.base import Indexer
from driftwood.indexers.errors import IndexerError
from driftwood.indexers.models import Release, SearchQuery

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class IndexerFailure:
    indexer_id: str
    message: str


@dataclass
class SearchResult:
    releases: list[Release] = field(default_factory=list)
    searched: list[str] = field(default_factory=list)
    """Ids of the indexers that were queried."""
    failures: list[IndexerFailure] = field(default_factory=list)


class IndexerManager:
    """Fans a query out to all enabled indexers concurrently; failures are collected, not raised."""

    def __init__(self, indexers: Sequence[Indexer], *, timeout_seconds: float = 60.0) -> None:
        self.indexers = [indexer for indexer in indexers if indexer.settings.enabled]
        self.timeout_seconds = timeout_seconds

    async def _search_one(self, indexer: Indexer, query: SearchQuery) -> list[Release]:
        async with asyncio.timeout(self.timeout_seconds):
            return await indexer.search(query)

    async def search(self, query: SearchQuery) -> SearchResult:
        outcomes = await asyncio.gather(
            *(self._search_one(indexer, query) for indexer in self.indexers),
            return_exceptions=True,
        )
        result = SearchResult(searched=[indexer.id for indexer in self.indexers])
        for indexer, outcome in zip(self.indexers, outcomes, strict=True):
            if isinstance(outcome, BaseException):
                if not isinstance(outcome, Exception):
                    raise outcome  # cancellation and friends
                if isinstance(outcome, TimeoutError):
                    message = f"timed out after {self.timeout_seconds:g}s"
                elif isinstance(outcome, IndexerError):
                    message = f"{type(outcome).__name__}: {outcome}"
                else:
                    message = f"unexpected {type(outcome).__name__}: {outcome}"
                log.warning("Indexer %s search failed: %s", indexer.id, message, exc_info=outcome)
                result.failures.append(IndexerFailure(indexer.id, message))
            else:
                result.releases.extend(outcome)
        return result

    async def fetch_nfo(self, indexer_id: str, guid: str) -> bytes | None:
        """A release's NFO from the indexer that found it. Raises `IndexerError` on failure."""
        for indexer in self.indexers:
            if indexer.id == indexer_id:
                async with asyncio.timeout(self.timeout_seconds):
                    return await indexer.fetch_nfo(guid)
        raise IndexerError(f"no enabled indexer {indexer_id!r}")

    async def download(self, release: Release) -> bytes:
        """The release's .torrent from the indexer that found it. Raises `IndexerError`."""
        for indexer in self.indexers:
            if indexer.id == release.indexer_id:
                async with asyncio.timeout(self.timeout_seconds):
                    return await indexer.download(release)
        raise IndexerError(f"no enabled indexer {release.indexer_id!r}")

    async def aclose(self) -> None:
        for indexer in self.indexers:
            with contextlib.suppress(Exception):
                await indexer.aclose()
