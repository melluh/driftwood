import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

import httpx
from fastapi import FastAPI

from driftwood.config import get_settings
from driftwood.media.router import router as media_router
from driftwood.media.service import MediaService
from driftwood.titles.store import TitleIndexStore
from driftwood.tmdb.client import TmdbClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    if not settings.tmdb.api_key:
        log.warning("DRIFTWOOD_TMDB__API_KEY is not set; TMDB requests will fail")

    titles = TitleIndexStore(settings.title_index)
    limits = httpx.Limits(max_connections=20, max_keepalive_connections=20)
    async with httpx.AsyncClient(timeout=10, limits=limits) as http:
        app.state.media_service = MediaService(titles, TmdbClient(http, settings.tmdb))
        index_task = asyncio.create_task(titles.run(), name="title-index")
        try:
            yield
        finally:
            index_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await index_task


app = FastAPI(title="Driftwood", lifespan=lifespan)
app.include_router(media_router, prefix="/api")
