"""Users and server-side sessions.

The session cookie holds a random token; the database stores only its SHA-256,
so a leaked database can't be replayed as live sessions.
"""

import hashlib
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from driftwood.db.models import User, UserSession, utcnow


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _claim(claims: Mapping[str, Any], *names: str) -> str | None:
    for name in names:
        value = claims.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


async def upsert_user(db: AsyncSession, issuer: str, claims: Mapping[str, Any]) -> User:
    """Find the user for these OIDC claims (by issuer + `sub`), refreshing their profile."""
    subject = _claim(claims, "sub")
    if subject is None:
        raise ValueError("OIDC claims carry no subject")

    email = _claim(claims, "email")
    name = _claim(claims, "name", "preferred_username", "nickname", "email") or "User"
    avatar_url = _claim(claims, "picture")

    user = await db.scalar(select(User).where(User.issuer == issuer, User.subject == subject))
    if user is None:
        user = User(issuer=issuer, subject=subject)
        db.add(user)
    user.name = name
    user.email = email
    user.avatar_url = avatar_url
    user.last_login_at = utcnow()
    await db.flush()
    return user


async def create_session(db: AsyncSession, user: User, ttl: timedelta) -> str:
    """Start a session for `user` and return its (unhashed) cookie token."""
    now = utcnow()
    # Opportunistic cleanup; logins are rare enough for this to be cheap.
    await db.execute(delete(UserSession).where(UserSession.expires_at <= now))
    token = secrets.token_urlsafe(32)
    db.add(UserSession(token_hash=hash_token(token), user_id=user.id, expires_at=now + ttl))
    await db.flush()
    return token


@dataclass
class ResolvedSession:
    session: UserSession
    renewed: bool
    """True when the expiry was extended, so the cookie should be re-issued."""


async def resolve_session(db: AsyncSession, token: str, ttl: timedelta) -> ResolvedSession | None:
    """The live session for `token`, or None. Sliding expiry: a session past half
    its lifetime is extended, so active users stay signed in."""
    session = await db.get(UserSession, hash_token(token))
    if session is None:
        return None
    now = utcnow()
    if session.expires_at <= now:
        await db.delete(session)
        await db.commit()
        return None
    renewed = session.expires_at - now < ttl / 2
    if renewed:
        session.expires_at = now + ttl
        await db.commit()
    return ResolvedSession(session, renewed)


async def delete_session(db: AsyncSession, token: str) -> None:
    await db.execute(delete(UserSession).where(UserSession.token_hash == hash_token(token)))
    await db.commit()
