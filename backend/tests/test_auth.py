"""The OIDC login flow end to end, against a fake identity provider.

Authlib does the real work (discovery, PKCE, state, ID token verification); only
the provider's HTTP endpoints are faked.
"""

import base64
import hashlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import httpx2
import pytest
from fastapi import APIRouter, Depends, FastAPI
from joserfc import jwt
from joserfc.jwk import RSAKey
from sqlalchemy import func, select, update
from starlette.middleware.sessions import SessionMiddleware

from driftwood.auth.oidc import OidcProvider
from driftwood.auth.router import (
    OAUTH_STATE_COOKIE,
    OAUTH_STATE_PATH,
    SESSION_COOKIE,
    AuthState,
    UserDep,
    require_user,
    safe_next,
)
from driftwood.auth.router import router as auth_router
from driftwood.config import AuthSettings
from driftwood.db import Database
from driftwood.db.models import User, UserSession, utcnow
from driftwood.media.schemas import HomePage, HomeRow, MediaSummary, MediaType

ISSUER = "https://idp.test"
CLIENT_ID = "driftwood"
PUBLIC_URL = "http://testserver"


@dataclass
class FakeIdp:
    """Just enough of an OpenID provider: discovery, JWKS, token and userinfo."""

    key: RSAKey = field(
        default_factory=lambda: RSAKey.generate_key(2048, parameters={"kid": "k1"}, private=True)
    )
    claims: dict[str, Any] = field(
        default_factory=lambda: {
            "sub": "user-1",
            "name": "Ada Lovelace",
            "email": "ada@example.com",
            "picture": "https://idp.test/ada.png",
        }
    )
    id_token_issuer: str = ISSUER
    pending: dict[str, dict[str, str]] = field(default_factory=dict)

    def approve(self, authorize_url: str) -> dict[str, str]:
        """The user signs in at the provider; returns the callback query."""
        query = {k: v[0] for k, v in parse_qs(urlsplit(authorize_url).query).items()}
        assert query["client_id"] == CLIENT_ID
        assert query["redirect_uri"] == f"{PUBLIC_URL}/api/auth/callback"
        assert query["code_challenge_method"] == "S256"
        code = f"code-{len(self.pending)}"
        self.pending[code] = query
        return {"code": code, "state": query["state"]}

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if path == "/.well-known/openid-configuration":
            return httpx2.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": f"{ISSUER}/authorize",
                    "token_endpoint": f"{ISSUER}/token",
                    "userinfo_endpoint": f"{ISSUER}/userinfo",
                    "jwks_uri": f"{ISSUER}/jwks",
                },
            )
        if path == "/jwks":
            return httpx2.Response(200, json={"keys": [self.key.as_dict(private=False)]})
        if path == "/token":
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            authorize = self.pending.pop(form["code"], None)
            if authorize is None:
                return httpx2.Response(400, json={"error": "invalid_grant"})
            digest = hashlib.sha256(form["code_verifier"].encode()).digest()
            challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
            if challenge != authorize["code_challenge"]:
                return httpx2.Response(400, json={"error": "invalid_grant"})
            now = int(utcnow().timestamp())
            id_claims = {
                **self.claims,
                "iss": self.id_token_issuer,
                "aud": CLIENT_ID,
                "iat": now,
                "exp": now + 300,
                "nonce": authorize["nonce"],
            }
            id_token = jwt.encode({"alg": "RS256", "kid": "k1"}, id_claims, self.key)
            return httpx2.Response(
                200,
                json={
                    "access_token": "access",
                    "token_type": "Bearer",
                    "expires_in": 300,
                    "id_token": id_token,
                },
            )
        if path == "/userinfo":
            return httpx2.Response(200, json=self.claims)
        return httpx2.Response(404)


@pytest.fixture
def idp() -> FakeIdp:
    return FakeIdp()


@pytest.fixture
async def database(tmp_path) -> AsyncIterator[Database]:
    database = Database(f"sqlite+aiosqlite:///{tmp_path}/driftwood.db")
    await database.migrate()
    yield database
    await database.dispose()


def make_app(database: Database, idp: FakeIdp, **settings: Any) -> FastAPI:
    auth_settings = AuthSettings(
        issuer_url=ISSUER,
        client_id=CLIENT_ID,
        client_secret="s3cret",
        public_url=PUBLIC_URL,
        **settings,
    )
    app = FastAPI()
    app.add_middleware(
        SessionMiddleware,
        secret_key="test",
        session_cookie=OAUTH_STATE_COOKIE,
        path=OAUTH_STATE_PATH,
    )
    app.include_router(auth_router, prefix="/api")

    protected = APIRouter()

    @protected.get("/protected")
    async def protected_route(user: UserDep) -> dict[str, str]:
        return {"name": user.name}

    app.include_router(protected, prefix="/api", dependencies=[Depends(require_user)])
    app.state.database = database
    provider = OidcProvider(auth_settings, transport=httpx2.MockTransport(idp.handler))
    app.state.auth = AuthState(auth_settings, provider)
    return app


@pytest.fixture
async def client(database: Database, idp: FakeIdp) -> AsyncIterator[httpx.AsyncClient]:
    app = make_app(database, idp)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=PUBLIC_URL) as client:
        yield client


async def sign_in(client: httpx.AsyncClient, idp: FakeIdp, next: str = "/") -> httpx.Response:
    start = await client.get("/api/auth/login", params={"next": next})
    assert start.status_code == 302
    callback_query = idp.approve(start.headers["location"])
    return await client.get("/api/auth/callback", params=callback_query)


async def test_signed_out_requests_are_rejected(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/protected")).status_code == 401
    assert (await client.get("/api/auth/me")).status_code == 401
    client.cookies.set(SESSION_COOKIE, "forged", path="/api")
    assert (await client.get("/api/protected")).status_code == 401


async def test_config_is_public(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/auth/config")
    assert response.json() == {"provider_name": "SSO", "configured": True}


async def test_sign_in_flow(client: httpx.AsyncClient, idp: FakeIdp, database: Database) -> None:
    response = await sign_in(client, idp, next="/movie/603?x=1")
    assert response.status_code == 303
    assert response.headers["location"] == f"{PUBLIC_URL}/movie/603?x=1"
    assert SESSION_COOKIE in response.cookies

    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json() == {
        "id": 1,
        "name": "Ada Lovelace",
        "email": "ada@example.com",
        "avatar_url": "https://idp.test/ada.png",
    }
    assert (await client.get("/api/protected")).json() == {"name": "Ada Lovelace"}

    async with database.sessionmaker() as db:
        user = await db.scalar(select(User))
        assert user is not None
        assert (user.issuer, user.subject) == (ISSUER, "user-1")
        # Only the token's hash is stored.
        stored = await db.scalar(select(UserSession.token_hash))
        assert stored != response.cookies[SESSION_COOKIE]


async def test_repeat_sign_in_updates_the_same_user(
    client: httpx.AsyncClient, idp: FakeIdp, database: Database
) -> None:
    await sign_in(client, idp)
    idp.claims["name"] = "Ada King"
    await sign_in(client, idp)

    assert (await client.get("/api/auth/me")).json()["name"] == "Ada King"
    async with database.sessionmaker() as db:
        assert await db.scalar(select(func.count()).select_from(User)) == 1
        # The earlier session was rotated out.
        assert await db.scalar(select(func.count()).select_from(UserSession)) == 1


async def test_logout(client: httpx.AsyncClient, idp: FakeIdp, database: Database) -> None:
    await sign_in(client, idp)
    token = client.cookies[SESSION_COOKIE]

    response = await client.post("/api/auth/logout")
    assert response.status_code == 204
    assert (await client.get("/api/auth/me")).status_code == 401

    # The server-side session is gone too, so the old token is useless.
    client.cookies.set(SESSION_COOKIE, token, path="/api")
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_forged_state_is_rejected(client: httpx.AsyncClient, idp: FakeIdp) -> None:
    start = await client.get("/api/auth/login")
    query = idp.approve(start.headers["location"])
    response = await client.get("/api/auth/callback", params={**query, "state": "attacker-state"})
    assert response.status_code == 303
    assert response.headers["location"].startswith(f"{PUBLIC_URL}/login?error=failed")
    assert SESSION_COOKIE not in response.cookies
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_callback_without_login_is_rejected(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/auth/callback", params={"code": "x", "state": "y"})
    assert response.headers["location"].startswith(f"{PUBLIC_URL}/login?error=failed")


async def test_id_token_from_wrong_issuer_is_rejected(
    client: httpx.AsyncClient, idp: FakeIdp
) -> None:
    idp.id_token_issuer = "https://evil.test"
    response = await sign_in(client, idp)
    assert response.headers["location"].startswith(f"{PUBLIC_URL}/login?error=failed")
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_provider_denial(client: httpx.AsyncClient, idp: FakeIdp) -> None:
    start = await client.get("/api/auth/login", params={"next": "/tv/1"})
    state = idp.approve(start.headers["location"])["state"]
    response = await client.get(
        "/api/auth/callback", params={"error": "access_denied", "state": state}
    )
    assert response.headers["location"] == f"{PUBLIC_URL}/login?error=denied&next=%2Ftv%2F1"


async def test_expired_session(client: httpx.AsyncClient, idp: FakeIdp, database: Database) -> None:
    await sign_in(client, idp)
    async with database.sessionmaker() as db:
        await db.execute(update(UserSession).values(expires_at=utcnow() - timedelta(seconds=1)))
        await db.commit()
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_session_is_renewed_when_half_expired(
    client: httpx.AsyncClient, idp: FakeIdp, database: Database
) -> None:
    await sign_in(client, idp)
    response = await client.get("/api/auth/me")
    assert SESSION_COOKIE not in response.cookies  # fresh: no renewal yet

    async with database.sessionmaker() as db:
        await db.execute(update(UserSession).values(expires_at=utcnow() + timedelta(days=1)))
        await db.commit()
    response = await client.get("/api/auth/me")
    assert response.status_code == 200
    assert SESSION_COOKIE in response.cookies
    async with database.sessionmaker() as db:
        expires_at = await db.scalar(select(UserSession.expires_at))
        assert expires_at is not None
        assert expires_at > utcnow() + timedelta(days=29)


async def test_unconfigured_provider(database: Database, idp: FakeIdp) -> None:
    app = make_app(database, idp)
    app.state.auth = AuthState(AuthSettings(public_url=PUBLIC_URL), None)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=PUBLIC_URL) as client:
        assert (await client.get("/api/auth/config")).json()["configured"] is False
        response = await client.get("/api/auth/login")
        assert response.headers["location"] == f"{PUBLIC_URL}/login?error=not_configured"


async def test_app_api_requires_sign_in(database: Database) -> None:
    from driftwood.main import app

    app.state.database = database
    app.state.auth = AuthState(AuthSettings(public_url=PUBLIC_URL), None)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=PUBLIC_URL) as client:
        for path in [
            "/api/home",
            "/api/search?q=x",
            "/api/search/status",
            "/api/media/movie/1",
            "/api/my-list",
            "/api/my-list/movie/1",
        ]:
            assert (await client.get(path)).status_code == 401, path


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "/"),
        ("", "/"),
        ("/movie/1?a=b", "/movie/1?a=b"),
        ("https://evil.test", "/"),
        ("//evil.test", "/"),
        ("/\\evil.test", "/"),
        ("movie/1", "/"),
    ],
)
def test_safe_next(value: str | None, expected: str) -> None:
    assert safe_next(value) == expected


class StubHome:
    def __init__(self, page: HomePage | None) -> None:
        self._page = page

    async def page(self) -> HomePage:
        if self._page is None:
            raise httpx.ConnectError("TMDB is down")
        return self._page


def _summary(media_type: MediaType, id: int, poster: str | None) -> MediaSummary:
    return MediaSummary(media_type=media_type, id=id, title=f"Title {id}", poster_path=poster)


async def _backdrop(database: Database, idp: FakeIdp, home: StubHome) -> httpx.Response:
    app = make_app(database, idp)
    app.state.home_service = home
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=PUBLIC_URL) as client:
        return await client.get("/api/auth/backdrop")


async def test_login_backdrop_is_public_and_only_poster_paths(
    database: Database, idp: FakeIdp
) -> None:
    rows = [
        HomeRow(
            id="movies",
            title="Movies",
            items=[_summary(MediaType.movie, 1, "/a.jpg"), _summary(MediaType.movie, 2, None)],
        ),
        HomeRow(
            id="tv",
            title="TV",
            items=[_summary(MediaType.tv, 3, "/b.jpg"), _summary(MediaType.tv, 4, "/a.jpg")],
        ),
    ]
    response = await _backdrop(database, idp, StubHome(HomePage(featured=[], rows=rows)))
    assert response.status_code == 200  # no session needed
    assert response.json() == ["/a.jpg", "/b.jpg"]


async def test_login_backdrop_survives_tmdb_outage(database: Database, idp: FakeIdp) -> None:
    response = await _backdrop(database, idp, StubHome(None))
    assert response.status_code == 200
    assert response.json() == []
