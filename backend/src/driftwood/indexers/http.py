"""Shared HTTP layer for indexers: cookies on disk, rate limiting, mirrors, retries."""

import asyncio
import contextlib
import json
import logging
import os
import time
from collections.abc import Sequence
from http.cookiejar import Cookie
from pathlib import Path
from typing import Any

import httpx

from driftwood.indexers.errors import RateLimitedError, SiteUnavailableError

log = logging.getLogger(__name__)

DEFAULT_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"


class HttpSession:
    """
    One per indexer instance. Requests take a path relative to the current
    mirror; a connection failure moves on to the next mirror and remembers the
    one that works. Redirects are not followed by default, so a 302 to a login
    page is visible to the caller as "session expired".

    Never logs request bodies or cookies: those carry credentials.
    """

    def __init__(
        self,
        mirrors: Sequence[str],
        *,
        min_interval: float = 0.0,
        cookie_file: Path | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: float = 30.0,
        max_retries: int = 2,
        retry_backoff: float = 1.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not mirrors:
            raise ValueError("at least one mirror is required")
        self.mirrors = [mirror.rstrip("/") + "/" for mirror in mirrors]
        self._mirror = 0
        self.min_interval = min_interval
        self.cookie_file = cookie_file
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self._throttle_lock = asyncio.Lock()
        self._last_request = -float("inf")
        self.client = httpx.AsyncClient(
            headers={"User-Agent": user_agent},
            timeout=timeout,
            follow_redirects=False,
            transport=transport,
        )
        self._load_cookies()

    @property
    def base_url(self) -> str:
        return self.mirrors[self._mirror]

    def url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        return self.base_url + path.lstrip("/")

    async def aclose(self) -> None:
        await self.client.aclose()

    async def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self.request("POST", path, **kwargs)

    async def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """
        `path` is relative to the active mirror (absolute URLs are sent as-is,
        without mirror fallback). Raises `SiteUnavailableError` when every
        mirror refuses connections or the site keeps failing.
        """
        if path.startswith(("http://", "https://")):
            return await self._send_with_retries(method, path, **kwargs)

        last_error: Exception | None = None
        start = self._mirror
        for offset in range(len(self.mirrors)):
            index = (start + offset) % len(self.mirrors)
            url = self.mirrors[index] + path.lstrip("/")
            try:
                response = await self._send_with_retries(method, url, **kwargs)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                log.warning("Mirror %s unreachable (%s)", self.mirrors[index], type(exc).__name__)
                last_error = exc
                continue
            if index != self._mirror:
                log.info("Switching to mirror %s", self.mirrors[index])
                self._mirror = index
            return response
        raise SiteUnavailableError(f"all mirrors unreachable: {last_error!r}")

    async def _send_with_retries(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        for attempt in range(self.max_retries + 1):
            last_attempt = attempt == self.max_retries
            await self._throttle()
            try:
                response = await self.client.request(method, url, **kwargs)
            except (httpx.ConnectError, httpx.ConnectTimeout):
                raise  # the mirror loop handles these
            except (httpx.TimeoutException, httpx.RemoteProtocolError) as exc:
                if last_attempt:
                    raise SiteUnavailableError(f"{method} {url}: {type(exc).__name__}") from exc
                await asyncio.sleep(self.retry_backoff * 2**attempt)
                continue

            if "set-cookie" in response.headers:
                self.save_cookies()
            if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
                raise RateLimitedError(f"{method} {url}: HTTP 429")
            if response.status_code >= 500:
                if last_attempt:
                    raise SiteUnavailableError(f"{method} {url}: HTTP {response.status_code}")
                await asyncio.sleep(self.retry_backoff * 2**attempt)
                continue
            return response
        raise AssertionError("unreachable")

    async def _throttle(self) -> None:
        if self.min_interval <= 0:
            return
        async with self._throttle_lock:
            wait = self._last_request + self.min_interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()

    # Cookie persistence, so restarts don't trigger a fresh login every time.

    def clear_cookies(self) -> None:
        self.client.cookies.clear()
        self.save_cookies()

    def save_cookies(self) -> None:
        if self.cookie_file is None:
            return
        cookies = [
            {
                "name": cookie.name,
                "value": cookie.value,
                "domain": cookie.domain,
                "path": cookie.path,
                "expires": cookie.expires,
                "secure": cookie.secure,
            }
            for cookie in self.client.cookies.jar
        ]
        try:
            self.cookie_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cookie_file.with_suffix(".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as file:
                json.dump(cookies, file)
            tmp.replace(self.cookie_file)
        except OSError:
            log.warning("Could not save cookies to %s", self.cookie_file, exc_info=True)

    def _load_cookies(self) -> None:
        if self.cookie_file is None or not self.cookie_file.exists():
            return
        try:
            cookies = json.loads(self.cookie_file.read_text())
        except (OSError, ValueError):
            log.warning("Ignoring unreadable cookie file %s", self.cookie_file)
            return
        now = time.time()
        for item in cookies:
            with contextlib.suppress(KeyError, TypeError):
                if item.get("expires") is not None and item["expires"] < now:
                    continue
                self.client.cookies.jar.set_cookie(_make_cookie(item))


def _make_cookie(item: dict[str, Any]) -> Cookie:
    domain: str = item["domain"]
    return Cookie(
        version=0,
        name=item["name"],
        value=item["value"],
        port=None,
        port_specified=False,
        domain=domain,
        domain_specified=bool(domain),
        domain_initial_dot=domain.startswith("."),
        path=item.get("path") or "/",
        path_specified=True,
        secure=bool(item.get("secure")),
        expires=item.get("expires"),
        discard=False,
        comment=None,
        comment_url=None,
        rest={},
    )
