import asyncio
from dataclasses import dataclass
from itertools import chain, zip_longest

from driftwood.media.mapping import TmdbJson, to_summary
from driftwood.media.schemas import HomePage, HomeRow, MediaSummary, MediaType
from driftwood.tmdb.client import TmdbClient

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


def pick_featured(rows: list[HomeRow], count: int = FEATURED_COUNT) -> list[MediaSummary]:
    """Interleaves the rows' top items (movie, show, movie, ...) that have art and a synopsis."""
    interleaved = chain.from_iterable(zip_longest(*(row.items for row in rows)))
    featurable = (item for item in interleaved if item is not None and _is_featurable(item))
    return list(featurable)[:count]


class HomeService:
    """Builds the home page from TMDB's popular movie and TV lists."""

    def __init__(self, tmdb: TmdbClient) -> None:
        self.tmdb = tmdb

    async def _row(self, source: RowSource) -> HomeRow:
        results = await self.tmdb.popular(source.media_type)
        return HomeRow(
            id=source.id,
            title=source.title,
            items=_summaries(source.media_type, results),
        )

    async def page(self) -> HomePage:
        rows = list(await asyncio.gather(*(self._row(source) for source in ROWS)))
        return HomePage(featured=pick_featured(rows), rows=rows)
