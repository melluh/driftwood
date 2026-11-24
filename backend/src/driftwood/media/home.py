import asyncio
import logging
from dataclasses import dataclass
from itertools import chain, zip_longest

from driftwood.media.availability import AvailabilityChecker, MediaKey
from driftwood.media.mapping import TmdbJson, to_summary
from driftwood.media.schemas import HomePage, HomeRow, MediaSummary, MediaType
from driftwood.tmdb.client import TmdbClient

log = logging.getLogger(__name__)

FEATURED_COUNT = 6


@dataclass(frozen=True, slots=True)
class RowSource:
    id: str
    title: str
    media_type: MediaType


ROWS: tuple[RowSource, ...] = (
    RowSource("popular-movies", "Popular movies", MediaType.movie),
    RowSource("popular-tv", "Popular TV series", MediaType.tv),
)


def _summaries(media_type: MediaType, results: list[TmdbJson]) -> list[MediaSummary]:
    """Displayable items only: anything without a poster is dropped."""
    summaries = (to_summary(media_type, result) for result in results)
    return [summary for summary in summaries if summary.poster_path]


def _is_featurable(item: MediaSummary) -> bool:
    return bool(item.backdrop_path and item.overview)


def interleave(rows: list[HomeRow]) -> list[MediaSummary]:
    """The rows' items alternated: movie, show, movie, ..."""
    interleaved = chain.from_iterable(zip_longest(*(row.items for row in rows)))
    return [item for item in interleaved if item is not None]


def pick_featured(rows: list[HomeRow], count: int = FEATURED_COUNT) -> list[MediaSummary]:
    """Interleaves the rows' top items (movie, show, movie, ...) that have art and a synopsis."""
    return [item for item in interleave(rows) if _is_featurable(item)][:count]


def _key(item: MediaSummary) -> MediaKey:
    return item.media_type, item.id


class HomeService:
    """
    Builds the home page from TMDB's popular movie and TV lists, keeping only
    titles with a watchable release. A title that hasn't been checked yet is
    left out until the background check gets to it.
    """

    def __init__(self, tmdb: TmdbClient, availability: AvailabilityChecker | None) -> None:
        """Without an availability checker (no indexers configured) nothing is filtered."""
        self.tmdb = tmdb
        self.availability = availability

    async def _row(self, source: RowSource) -> HomeRow:
        results = await self.tmdb.popular(source.media_type)
        return HomeRow(
            id=source.id,
            title=source.title,
            items=_summaries(source.media_type, results),
        )

    async def _rows(self) -> list[HomeRow]:
        rows = list(await asyncio.gather(*(self._row(source) for source in ROWS)))
        if self.availability is not None:
            # In the hero's order, so its candidates are checked first.
            self.availability.request(_key(item) for item in interleave(rows))
        return rows

    def _available(self, row: HomeRow) -> HomeRow:
        if self.availability is None:
            return row
        available = self.availability.available
        return row.model_copy(update={"items": [i for i in row.items if available(_key(i))]})

    async def page(self) -> HomePage:
        rows = [row for row in map(self._available, await self._rows()) if row.items]
        return HomePage(featured=pick_featured(rows), rows=rows)

    async def run(self) -> None:
        """Keeps the popular titles checked, so the page is full by the time it's opened."""
        if self.availability is None:
            return
        while True:
            try:
                await self._rows()
            except Exception:
                log.exception("Could not load the popular lists to check their availability")
            await asyncio.sleep(self.availability.settings.refresh_interval_minutes * 60)
