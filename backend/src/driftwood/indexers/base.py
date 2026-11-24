import asyncio
from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar, Literal, Self

import httpx
from pydantic import BaseModel, HttpUrl

from driftwood.indexers.errors import AuthError
from driftwood.indexers.http import HttpSession
from driftwood.indexers.models import Capabilities, Release, SearchQuery


class IndexerSettings(BaseModel):
    base_url: HttpUrl | None = None
    """Pin one site URL; `None` tries the indexer's known mirrors in order."""
    enabled: bool = True


class Indexer(ABC):
    """What callers see of an indexer. Everything below this is per-site detail."""

    id: ClassVar[str]
    name: ClassVar[str]
    privacy: ClassVar[Literal["public", "semi-private", "private"]]
    settings_model: ClassVar[type[IndexerSettings]]
    default_mirrors: ClassVar[tuple[str, ...]]
    min_request_interval: ClassVar[float] = 0.0
    """Seconds between requests to the site."""

    def __init__(self, settings: IndexerSettings, http: HttpSession) -> None:
        self.settings = settings
        self.http = http

    @classmethod
    def create(cls, settings: IndexerSettings, *, data_directory: Path | None = None) -> Self:
        """An instance with its own HTTP session (cookies persisted under `data_directory`)."""
        mirrors = [str(settings.base_url)] if settings.base_url else list(cls.default_mirrors)
        http = HttpSession(
            mirrors,
            min_interval=cls.min_request_interval,
            cookie_file=data_directory / f"{cls.id}.cookies.json" if data_directory else None,
        )
        return cls(settings, http)

    @property
    @abstractmethod
    def capabilities(self) -> Capabilities: ...

    @abstractmethod
    async def search(self, query: SearchQuery) -> list[Release]: ...

    @abstractmethod
    async def download(self, release: Release) -> bytes:
        """The .torrent file's bytes (handles auth)."""

    async def fetch_nfo(self, guid: str) -> bytes | None:
        """The release's raw NFO, or None when it has none (or the indexer doesn't serve NFOs)."""
        return None

    async def test(self) -> None:
        """Log in and run an empty search; raises `IndexerError` on failure."""
        await self.search(SearchQuery())

    async def aclose(self) -> None:
        await self.http.aclose()


class SessionIndexer(Indexer):
    """
    Base for scraping-style indexers with a login session. Subclasses implement
    `login`, `is_logged_out`, and the pure `build_requests` / `parse_response`
    pair (testable against saved fixtures, no I/O).
    """

    def __init__(self, settings: IndexerSettings, http: HttpSession) -> None:
        super().__init__(settings, http)
        self._login_lock = asyncio.Lock()
        # Persisted cookies may still be a valid session; trust them until a
        # response says otherwise.
        self._logged_in = bool(http.client.cookies)
        self._session_generation = 0

    @abstractmethod
    async def login(self) -> None:
        """Log in and leave the session cookies in `self.http`; raise `AuthError` on failure."""

    @abstractmethod
    def is_logged_out(self, response: httpx.Response) -> bool: ...

    @abstractmethod
    def build_requests(self, query: SearchQuery) -> list[str]:
        """Paths (relative to the site's base URL) to fetch for `query`."""

    @abstractmethod
    def parse_response(self, response: httpx.Response, query: SearchQuery) -> list[Release]: ...

    async def ensure_logged_in(self) -> None:
        if self._logged_in:
            return
        async with self._login_lock:
            if not self._logged_in:
                await self._login()

    async def _login(self) -> None:
        self._logged_in = False
        await self.login()
        self._logged_in = True
        self._session_generation += 1
        self.http.save_cookies()

    async def _relogin(self, seen_generation: int) -> None:
        async with self._login_lock:
            if self._session_generation == seen_generation:  # nobody re-logged in meanwhile
                self.http.clear_cookies()
                await self._login()

    async def fetch(self, path: str) -> httpx.Response:
        """GET with the session; logs in again once if the session turns out to be expired."""
        await self.ensure_logged_in()
        generation = self._session_generation
        response = await self.http.get(path)
        if not self.is_logged_out(response):
            return response
        await self._relogin(generation)
        response = await self.http.get(path)
        if self.is_logged_out(response):
            raise AuthError(f"{self.name}: still logged out right after logging in")
        return response

    async def search(self, query: SearchQuery) -> list[Release]:
        releases: dict[str, Release] = {}
        for path in self.build_requests(query):
            response = await self.fetch(path)
            for release in self.parse_response(response, query):
                releases.setdefault(release.guid, release)
        results = list(releases.values())[query.offset :]
        return results[: query.limit] if query.limit is not None else results
