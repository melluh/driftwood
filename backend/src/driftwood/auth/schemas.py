from pydantic import BaseModel


class AuthConfig(BaseModel):
    provider_name: str
    configured: bool
    """False when no OIDC provider is set up, so signing in can't work."""


class CurrentUser(BaseModel):
    id: int
    name: str
    email: str | None
    avatar_url: str | None
