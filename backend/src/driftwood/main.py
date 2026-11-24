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
from driftwood.config import get_settings
from driftwood.db import Database
from driftwood.media.home import HomeService
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
    if not settings.auth.configured:
        log.warning(
            "DRIFTWOOD_AUTH__ISSUER_URL / DRIFTWOOD_AUTH__CLIENT_ID are not set; nobody can sign in"
        )

    database = Database(settings.database.url)
    await database.migrate()
    app.state.database = database
    provider = OidcProvider(settings.auth) if settings.auth.configured else None
    app.state.auth = AuthState(settings.auth, provider)

    titles = TitleIndexStore(settings.title_index)
    limits = httpx.Limits(max_connections=20, max_keepalive_connections=20)
    async with httpx.AsyncClient(timeout=10, limits=limits) as http:
        tmdb = TmdbClient(http, settings.tmdb)
        app.state.media_service = MediaService(titles, tmdb)
        app.state.home_service = HomeService(tmdb)
        index_task = asyncio.create_task(titles.run(), name="title-index")
        try:
            yield
        finally:
            index_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await index_task
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
