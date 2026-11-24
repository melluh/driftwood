import asyncio
import logging

import httpx

from driftwood.media.mapping import to_details, to_summary
from driftwood.media.schemas import MediaDetails, MediaSummary, MediaType
from driftwood.titles.index import TitleMatch
from driftwood.titles.store import TitleIndexStore
from driftwood.tmdb.client import TmdbClient, TmdbNotFoundError

log = logging.getLogger(__name__)


class MediaService:
    def __init__(self, titles: TitleIndexStore, tmdb: TmdbClient) -> None:
        self.titles = titles
        self.tmdb = tmdb

    async def _hydrate(self, match: TitleMatch) -> MediaSummary | None:
        """
        Full display info (poster, year, localized title) for one index match.
        Falls back to the bare index data if TMDB can't be reached; drops the
        match if TMDB no longer knows the title.
        """
        try:
            data = await self.tmdb.details(match.media_type, match.id)
        except TmdbNotFoundError:
            return None
        except httpx.HTTPError:
            log.warning("Could not hydrate %s %d", match.media_type, match.id, exc_info=True)
            return MediaSummary(
                media_type=match.media_type,
                id=match.id,
                title=match.title,
                original_title=match.title,
                popularity=match.popularity,
            )
        return to_summary(match.media_type, data)

    async def search(self, query: str) -> list[MediaSummary]:
        scored = await self.titles.search(query)
        hydrated = await asyncio.gather(*(self._hydrate(item.entry) for item in scored))
        return [summary for summary in hydrated if summary is not None]

    async def details(self, media_type: MediaType, media_id: int) -> MediaDetails | None:
        try:
            data = await self.tmdb.details(media_type, media_id)
        except TmdbNotFoundError:
            return None
        return to_details(media_type, data)
