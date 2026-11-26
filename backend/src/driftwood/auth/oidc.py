"""The OpenID Connect client (authorization code flow with PKCE, via Authlib)."""

import logging
from dataclasses import dataclass
from typing import Any

from authlib.integrations.starlette_client import OAuth, StarletteOAuth2App
from starlette.requests import Request

from driftwood.config import AuthSettings

log = logging.getLogger(__name__)


@dataclass
class OidcIdentity:
    issuer: str
    claims: dict[str, Any]


class OidcProvider:
    def __init__(self, settings: AuthSettings, transport: Any = None) -> None:
        """`transport` (tests only) replaces the HTTP transport of Authlib's client,
        which is httpx2's when installed, else httpx's."""
        client_kwargs: dict[str, Any] = {
            "scope": settings.scopes,
            "code_challenge_method": "S256",
        }
        if transport is not None:  # tests: a fake identity provider
            client_kwargs["transport"] = transport
        if not settings.client_secret:
            client_kwargs["token_endpoint_auth_method"] = "none"

        oauth = OAuth()
        oauth.register(
            "oidc",
            client_id=settings.client_id,
            client_secret=settings.client_secret or None,
            server_metadata_url=(
                f"{settings.issuer_url.rstrip('/')}/.well-known/openid-configuration"
            ),
            client_kwargs=client_kwargs,
        )
        client = oauth.create_client("oidc")
        assert isinstance(client, StarletteOAuth2App)
        self.client = client

    async def authorize_redirect(self, request: Request, redirect_uri: str) -> Any:
        return await self.client.authorize_redirect(request, redirect_uri)

    async def complete(self, request: Request) -> OidcIdentity:
        """Exchange the callback's code for tokens and return the verified identity.

        Raises `authlib.integrations.base_client.OAuthError` when the provider
        reports an error or the state / ID token doesn't check out.
        """
        token = await self.client.authorize_access_token(request)
        metadata = await self.client.load_server_metadata()
        # Present when the provider returned an ID token; Authlib has verified its
        # signature, issuer, audience, expiry and nonce.
        claims: dict[str, Any] = dict(token.get("userinfo") or {})

        # Some providers keep the profile out of the ID token; fill it in from userinfo.
        if metadata.get("userinfo_endpoint") and ("sub" not in claims or "name" not in claims):
            try:
                userinfo = dict(await self.client.userinfo(token=token))
            except Exception:
                if "sub" not in claims:
                    raise  # no ID token to fall back on: there's no identity without it
                # Just the profile was missing; the ID token already says who this is.
                log.warning(
                    "Couldn't fetch the userinfo profile; using the ID token's claims",
                    exc_info=True,
                )
                userinfo = {"sub": claims["sub"]}
            if "sub" in claims and userinfo.get("sub") != claims["sub"]:
                raise ValueError("userinfo subject does not match the ID token")
            claims = {**userinfo, **claims}

        issuer = claims.get("iss") or metadata["issuer"]
        return OidcIdentity(issuer=issuer, claims=claims)
