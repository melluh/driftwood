"""Finds torrent releases for a TMDB title through the configured indexers."""

import re

from driftwood.indexers import categories
from driftwood.indexers.manager import IndexerManager, SearchResult
from driftwood.indexers.models import Release, SearchQuery, SearchType
from driftwood.media.mapping import to_details
from driftwood.media.schemas import (
    IndexerFailure,
    MediaDetails,
    MediaType,
    ReleaseSearch,
    TorrentRelease,
)
from driftwood.tmdb.cache import AsyncTtlCache
from driftwood.tmdb.client import TmdbClient, TmdbNotFoundError

_APOSTROPHES = re.compile("['`’]")  # noqa: RUF001
_SEPARATORS = re.compile(r"[\s:;,!?&/\\|\-–—]+")  # noqa: RUF001


def search_title(title: str) -> str:
    """Titles the way release names spell them: "Grey's Anatomy: X" → "Greys Anatomy X"."""
    return _SEPARATORS.sub(" ", _APOSTROPHES.sub("", title)).strip()


def release_query(media: MediaDetails) -> SearchQuery:
    if media.media_type is MediaType.movie:
        return SearchQuery(
            type=SearchType.MOVIE,
            q=search_title(media.title),
            year=media.year,
            imdb_id=media.imdb_id,
            tmdb_id=media.id,
            categories=(categories.MOVIES,),
        )
    return SearchQuery(
        type=SearchType.TV,
        q=search_title(media.title),
        imdb_id=media.imdb_id,
        tmdb_id=media.id,
        categories=(categories.TV,),
    )


def describe(query: SearchQuery) -> str:
    parts = [query.type.value]
    if query.imdb_id and query.type is SearchType.MOVIE:
        parts.append(f"imdb={query.imdb_id}")
    if query.q:
        parts.append(f"q={query.q!r}")
    if query.year:
        parts.append(f"year={query.year}")
    if query.categories:
        parts.append("cat=" + ",".join(map(str, query.categories)))
    return " ".join(parts)


def to_schema(release: Release) -> TorrentRelease:
    return TorrentRelease(
        indexer=release.indexer_id,
        guid=release.guid,
        title=release.title,
        details_url=release.details_url,
        size=release.size,
        published=release.published,
        categories=release.categories,
        seeders=release.seeders,
        leechers=release.leechers,
        grabs=release.grabs,
        freeleech=release.download_factor == 0,
        imdb_id=release.imdb_id,
        genres=release.genres,
    )


class _FailedSearch(Exception):
    """Carries a partly failed result past the cache, so it isn't stored."""

    def __init__(self, result: SearchResult) -> None:
        self.result = result


class ReleaseService:
    def __init__(
        self, tmdb: TmdbClient, indexers: IndexerManager, *, cache_ttl_seconds: float
    ) -> None:
        self.tmdb = tmdb
        self.indexers = indexers
        self._cache: AsyncTtlCache[SearchQuery, SearchResult] = AsyncTtlCache(
            ttl_seconds=cache_ttl_seconds, max_entries=500
        )

    async def _search(self, query: SearchQuery) -> SearchResult:
        async def fetch() -> SearchResult:
            result = await self.indexers.search(query)
            if result.failures:
                raise _FailedSearch(result)
            return result

        try:
            return await self._cache.get(query, fetch)
        except _FailedSearch as failed:
            return failed.result

    async def search(self, media_type: MediaType, media_id: int) -> ReleaseSearch | None:
        try:
            data = await self.tmdb.details(media_type, media_id)
        except TmdbNotFoundError:
            return None
        query = release_query(to_details(media_type, data))
        result = await self._search(query) if self.indexers.indexers else SearchResult()
        releases = sorted(result.releases, key=lambda r: r.seeders or 0, reverse=True)
        return ReleaseSearch(
            query=describe(query),
            indexers=result.searched,
            releases=[to_schema(release) for release in releases],
            failures=[
                IndexerFailure(indexer=f.indexer_id, message=f.message) for f in result.failures
            ],
        )
