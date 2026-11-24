import asyncio
import ctypes
import ctypes.util
import gc
import logging

from driftwood.config import TitleIndexSettings
from driftwood.media.schemas import IndexStatus, SearchStatus
from driftwood.titles.download import index_path, is_stale, refresh_title_index
from driftwood.titles.index import TitleIndex, TitleMatch
from driftwood.titles.ranking import ScoredEntry

log = logging.getLogger(__name__)


def _release_freed_memory() -> None:
    """
    Building an index allocates (and frees) far more than the index keeps;
    on glibc, hand that freed memory back to the OS instead of holding it.
    """
    gc.collect()
    if libc_name := ctypes.util.find_library("c"):
        trim = getattr(ctypes.CDLL(libc_name), "malloc_trim", None)
        if trim is not None:
            trim(0)


class TitleIndexStore:
    """
    Owns the currently loaded `TitleIndex` snapshot and keeps it fresh.
    Searches always run against a complete snapshot; a refresh builds the next
    one off the event loop and swaps it in atomically.
    """

    def __init__(self, settings: TitleIndexSettings) -> None:
        self.settings = settings
        self._index: TitleIndex | None = None
        self._building = False

    @property
    def status(self) -> SearchStatus:
        if self._index is not None:
            state = IndexStatus.ready
        elif self._building:
            state = IndexStatus.building
        else:
            state = IndexStatus.missing
        return SearchStatus(status=state, entries=len(self._index) if self._index else 0)

    async def search(self, query: str) -> list[ScoredEntry[TitleMatch]]:
        index = self._index
        if index is None:
            return []
        return await asyncio.to_thread(index.search, query, self.settings)

    async def _load(self) -> None:
        path = index_path(self.settings.directory)
        if not path.exists():
            return
        self._index = await asyncio.to_thread(TitleIndex.load, path, self.settings.head_size)
        _release_freed_memory()

    async def run(self) -> None:
        """Load (downloading first if stale), then refresh on a fixed interval. Runs forever."""
        self._building = True
        try:
            if is_stale(self.settings.directory, self.settings.stale_after_hours):
                await refresh_title_index(self.settings.directory)
            await self._load()
        except Exception:
            log.exception("Failed to load the title index")
        finally:
            self._building = False

        while True:
            await asyncio.sleep(self.settings.refresh_interval_hours * 3600)
            try:
                if await refresh_title_index(self.settings.directory):
                    await self._load()
            except Exception:
                log.exception("Title index refresh failed; keeping the current index")
