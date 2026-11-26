import asyncio
import contextlib
import logging
import secrets
from collections.abc import AsyncIterator

import httpx
from fastapi import Depends, FastAPI
from starlette.middleware.sessions import SessionMiddleware

from driftwood.auth.oidc import OidcProvider
from driftwood.auth.router import (
    OAUTH_STATE_COOKIE,
    OAUTH_STATE_MAX_AGE,
    OAUTH_STATE_PATH,
    AuthState,
    require_user,
)
from driftwood.auth.router import router as auth_router
from driftwood.config import IndexersSettings, get_settings
from driftwood.db import Database
from driftwood.downloads.qbittorrent import QbittorrentClient
from driftwood.downloads.router import router as downloads_router
from driftwood.downloads.service import DownloadService
from driftwood.indexers import INDEXERS
from driftwood.indexers.base import Indexer
from driftwood.indexers.manager import IndexerManager
from driftwood.library.router import router as library_router
from driftwood.library.service import LibraryService
from driftwood.media.home import HomeService
from driftwood.media.releases import ReleaseService
from driftwood.media.router import router as media_router
from driftwood.media.service import MediaService
from driftwood.media.watch import WatchService
from driftwood.my_list.router import router as my_list_router
from driftwood.my_list.service import MyListService
from driftwood.playback.router import router as playback_router
from driftwood.playback.service import PlaybackService
from driftwood.titles.store import TitleIndexStore
from driftwood.tmdb.client import TmdbClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)


def create_indexers(settings: IndexersSettings) -> list[Indexer]:
    configured = {"torrentleech": settings.torrentleech}
    indexers = []
    for indexer_id, indexer_settings in configured.items():
        if indexer_settings is None or not indexer_settings.enabled:
            continue
        indexers.append(
            INDEXERS[indexer_id].create(indexer_settings, data_directory=settings.directory)
        )
    log.info("Indexers enabled: %s", ", ".join(i.id for i in indexers) or "none")
    return indexers


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    if not settings.tmdb.api_key:
        log.warning("DRIFTWOOD_TMDB__API_KEY is not set; TMDB requests will fail")
    if not settings.auth.configured:
        log.warning(
            "DRIFTWOOD_AUTH__ISSUER_URL / DRIFTWOOD_AUTH__CLIENT_ID are not set; nobody can sign in"
        )

    database = Database(settings.database.url)
    await database.migrate()
    app.state.database = database
    library_service = LibraryService(settings.library, database)
    app.state.library_service = library_service
    playback_service = PlaybackService(settings.playback, settings.library)
    await playback_service.start()
    app.state.playback_service = playback_service
    for root in settings.library.roots:
        if not root.path.exists():
            log.warning("Library root %s does not exist: %s", root.name, root.path)
    provider = OidcProvider(settings.auth) if settings.auth.configured else None
    app.state.auth = AuthState(settings.auth, provider)

    titles = TitleIndexStore(settings.title_index)
    indexers = IndexerManager(
        create_indexers(settings.indexers),
        timeout_seconds=settings.indexers.search_timeout_seconds,
    )
    limits = httpx.Limits(max_connections=20, max_keepalive_connections=20)
    async with httpx.AsyncClient(timeout=10, limits=limits) as http:
        tmdb = TmdbClient(http, settings.tmdb)
        app.state.media_service = MediaService(titles, tmdb)
        app.state.home_service = HomeService(tmdb)
        app.state.my_list_service = MyListService(tmdb)
        release_service = ReleaseService(
            tmdb, indexers, cache_ttl_seconds=settings.indexers.results_cache_ttl_seconds
        )
        app.state.release_service = release_service
        qbittorrent = settings.downloads.qbittorrent
        download_service = DownloadService(
            settings.downloads,
            settings.library,
            database,
            releases=release_service,
            indexers=indexers,
            library=library_service,
            client=QbittorrentClient(qbittorrent) if qbittorrent else None,
        )
        app.state.download_service = download_service
        app.state.watch_service = WatchService(
            release_service, settings.selection, can_download=download_service.enabled
        )
        tasks = [
            asyncio.create_task(titles.run(), name="title-index"),
            asyncio.create_task(library_service.run(), name="library"),
            asyncio.create_task(download_service.run(), name="downloads"),
        ]
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            await download_service.shutdown()
            await library_service.shutdown()
            await playback_service.shutdown()
            await indexers.aclose()
            await database.dispose()


def _oauth_state_secret() -> str:
    if key := get_settings().auth.secret_key:
        return key
    log.warning("DRIFTWOOD_AUTH__SECRET_KEY is not set; using a random per-process key")
    return secrets.token_urlsafe(32)


app = FastAPI(title="Driftwood", lifespan=lifespan)
# Carries OAuth state / PKCE verifier / nonce between /api/auth/login and the callback.
app.add_middleware(
    SessionMiddleware,
    secret_key=_oauth_state_secret(),
    session_cookie=OAUTH_STATE_COOKIE,
    max_age=OAUTH_STATE_MAX_AGE,
    path=OAUTH_STATE_PATH,
    same_site="lax",
    https_only=get_settings().auth.secure_cookies,
)
app.include_router(auth_router, prefix="/api")
# Everything else requires a signed-in user.
app.include_router(media_router, prefix="/api", dependencies=[Depends(require_user)])
app.include_router(my_list_router, prefix="/api", dependencies=[Depends(require_user)])
app.include_router(library_router, prefix="/api", dependencies=[Depends(require_user)])
app.include_router(playback_router, prefix="/api", dependencies=[Depends(require_user)])
app.include_router(downloads_router, prefix="/api", dependencies=[Depends(require_user)])
