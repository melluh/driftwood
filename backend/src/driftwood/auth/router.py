import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated
from urllib.parse import urlencode

from authlib.integrations.base_client import OAuthError
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from driftwood.auth.oidc import OidcProvider
from driftwood.auth.schemas import AuthConfig, CurrentUser
from driftwood.auth.sessions import create_session, delete_session, resolve_session, upsert_user
from driftwood.config import AuthSettings
from driftwood.db import DbSession
from driftwood.db.models import User
from driftwood.media.router import HomeServiceDep

log = logging.getLogger(__name__)

SESSION_COOKIE = "driftwood_session"
COOKIE_PATH = "/api"
"""The session cookie is only needed by API calls."""

OAUTH_STATE_COOKIE = "driftwood_oauth"
OAUTH_STATE_PATH = "/api/auth"
OAUTH_STATE_MAX_AGE = 10 * 60
"""Lifetime of the signed cookie carrying OAuth state between login and callback."""


@dataclass
class AuthState:
    settings: AuthSettings
    provider: OidcProvider | None
    """None when OIDC isn't configured."""

    @property
    def session_ttl(self) -> timedelta:
        return timedelta(days=self.settings.session_ttl_days)


def get_auth(request: Request) -> AuthState:
    return request.app.state.auth


AuthDep = Annotated[AuthState, Depends(get_auth)]


def safe_next(value: str | None) -> str:
    """Only same-origin paths are allowed as post-login destinations (no open redirect)."""
    if not value or not value.startswith("/") or value.startswith(("//", "/\\")):
        return "/"
    return value


def set_session_cookie(response: Response, auth: AuthState, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(auth.session_ttl.total_seconds()),
        path=COOKIE_PATH,
        secure=auth.settings.secure_cookies,
        httponly=True,
        samesite="lax",
    )


def clear_session_cookie(response: Response, auth: AuthState) -> None:
    response.delete_cookie(
        SESSION_COOKIE,
        path=COOKIE_PATH,
        secure=auth.settings.secure_cookies,
        httponly=True,
        samesite="lax",
    )


async def require_user(request: Request, response: Response, db: DbSession, auth: AuthDep) -> User:
    """Dependency guarding every API route except `/api/auth/*`: 401 without a live session."""
    token = request.cookies.get(SESSION_COOKIE)
    if token and (resolved := await resolve_session(db, token, auth.session_ttl)):
        if resolved.renewed:
            set_session_cookie(response, auth, token)
        return resolved.session.user
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")


UserDep = Annotated[User, Depends(require_user)]

router = APIRouter(prefix="/auth", tags=["auth"])


def _login_page(auth: AuthState, **params: str) -> RedirectResponse:
    query = f"?{urlencode(params)}" if params else ""
    return RedirectResponse(f"{auth.settings.public_url}/login{query}", status.HTTP_303_SEE_OTHER)


@router.get("/config")
async def auth_config(auth: AuthDep) -> AuthConfig:
    """Public: what the login screen needs to know."""
    return AuthConfig(
        provider_name=auth.settings.provider_name, configured=auth.provider is not None
    )


BACKDROP_POSTERS = 40


@router.get("/backdrop")
async def login_backdrop(home: HomeServiceDep) -> list[str]:
    """Public: TMDB poster paths of popular titles, decoration for the login screen.

    Deliberately just image paths (no titles, ids or anything user-specific),
    from the same cached lists as the home page. Empty when TMDB is unreachable.
    """
    try:
        page = await home.page()
    except Exception:
        log.warning("Login backdrop unavailable", exc_info=True)
        return []
    paths = [item.poster_path for row in page.rows for item in row.items if item.poster_path]
    return list(dict.fromkeys(paths))[:BACKDROP_POSTERS]


@router.get("/login", response_class=RedirectResponse)
async def login(
    request: Request,
    auth: AuthDep,
    next: Annotated[str | None, Query(max_length=2048)] = None,
) -> RedirectResponse:
    """Start the OAuth flow: redirects the browser to the provider's sign-in page."""
    if auth.provider is None:
        return _login_page(auth, error="not_configured")
    request.session["next"] = safe_next(next)
    redirect_uri = f"{auth.settings.public_url}/api/auth/callback"
    return await auth.provider.authorize_redirect(request, redirect_uri)


@router.get("/callback", response_class=RedirectResponse, include_in_schema=False)
async def callback(request: Request, auth: AuthDep, db: DbSession) -> RedirectResponse:
    """The provider redirects here; on success a session cookie is set."""
    next_path = safe_next(request.session.pop("next", None))
    if auth.provider is None:
        return _login_page(auth, error="not_configured")

    try:
        identity = await auth.provider.complete(request)
        user = await upsert_user(db, identity.issuer, identity.claims)
    except OAuthError as exc:
        log.warning("OAuth sign-in failed: %s %s", exc.error, exc.description or "")
        error = "denied" if exc.error == "access_denied" else "failed"
        return _login_page(auth, error=error, next=next_path)
    except Exception:
        # ID token validation, network or provider errors: never let a broken
        # sign-in produce a session.
        log.exception("OAuth sign-in failed")
        return _login_page(auth, error="failed", next=next_path)

    # Rotate: a fresh token for every sign-in.
    if previous := request.cookies.get(SESSION_COOKIE):
        await delete_session(db, previous)
    token = await create_session(db, user, auth.session_ttl)
    await db.commit()
    log.info("User %d (%s) signed in", user.id, user.name)

    response = RedirectResponse(f"{auth.settings.public_url}{next_path}", status.HTTP_303_SEE_OTHER)
    set_session_cookie(response, auth, token)
    return response


@router.get("/me")
async def me(user: UserDep) -> CurrentUser:
    """The signed-in user; 401 when signed out."""
    return CurrentUser(id=user.id, name=user.name, email=user.email, avatar_url=user.avatar_url)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, auth: AuthDep, db: DbSession) -> Response:
    if token := request.cookies.get(SESSION_COOKIE):
        await delete_session(db, token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response, auth)
    return response
