"""
Whether a title has a release worth watching (what "Watch" would grab: no cams,
telesyncs or screeners, enough seeders), so the home page only suggests titles
that can actually be played.

Every check is an indexer search, and indexers are slow and rate limited
(TorrentLeech allows one request per ~4 s), so checks run one at a time in the
background and their verdicts are kept on disk across restarts.
"""

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass

from driftwood.config import HomeSettings
from driftwood.media.schemas import MediaType
from driftwood.media.watch import WatchService

log = logging.getLogger(__name__)

FORGET_AFTER_SECONDS = 14 * 24 * 3600
"""Verdicts this old are dropped from the file: the title left the popular lists."""

type MediaKey = tuple[MediaType, int]
type Check = Callable[[MediaType, int], Awaitable[bool]]


class CheckFailedError(Exception):
    """The indexers couldn't answer, so the title's availability is still unknown."""


def watch_check(watch: WatchService) -> Check:
    """Available when "Watch" would pick a release (series: S01E01, like Watch itself)."""

    async def check(media_type: MediaType, media_id: int) -> bool:
        plan = await watch.plan(media_type, media_id)
        if plan is None:
            return False  # unknown to TMDB
        if plan.pick is None and plan.failures:
            failures = "; ".join(f"{f.indexer}: {f.message}" for f in plan.failures)
            raise CheckFailedError(failures)
        return plan.pick is not None

    return check


@dataclass(frozen=True, slots=True)
class Verdict:
    available: bool
    checked_at: float
    """Unix time."""


def _encode(key: MediaKey) -> str:
    return f"{key[0].value}:{key[1]}"


def _decode(raw: str) -> MediaKey:
    media_type, media_id = raw.split(":")
    return MediaType(media_type), int(media_id)


class AvailabilityChecker:
    """
    Remembers which titles have a watchable release. `request` queues titles
    whose verdict is missing or stale; `run` works through the queue one title
    at a time, in the order they were requested.
    """

    def __init__(
        self,
        check: Check,
        settings: HomeSettings,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._check = check
        self.settings = settings
        self._clock = clock
        self._verdicts: dict[MediaKey, Verdict] = {}
        self._failed_at: dict[MediaKey, float] = {}
        self._pending: dict[MediaKey, None] = {}  # an ordered set
        self._wake = asyncio.Event()
        self._load()

    def available(self, key: MediaKey) -> bool | None:
        """The latest verdict, even a stale one (it's rechecked); None if never checked."""
        verdict = self._verdicts.get(key)
        return verdict.available if verdict else None

    def _needs_check(self, key: MediaKey) -> bool:
        now = self._clock()
        failed_at = self._failed_at.get(key)
        if failed_at is not None and now - failed_at < self.settings.failed_retry_minutes * 60:
            return False
        verdict = self._verdicts.get(key)
        if verdict is None:
            return True
        ttl_hours = (
            self.settings.available_ttl_hours
            if verdict.available
            else self.settings.unavailable_ttl_hours
        )
        return now - verdict.checked_at >= ttl_hours * 3600

    def request(self, keys: Iterable[MediaKey]) -> None:
        """Queue the titles that need a (re)check; earlier keys are checked first."""
        for key in keys:
            if key not in self._pending and self._needs_check(key):
                self._pending[key] = None
                self._wake.set()

    async def check_now(self, key: MediaKey) -> None:
        try:
            available = await self._check(*key)
        except Exception as exc:
            log.warning("Availability check for %s failed: %s", _encode(key), exc)
            self._failed_at[key] = self._clock()
            return
        self._failed_at.pop(key, None)
        self._verdicts[key] = Verdict(available, self._clock())
        self._save()

    async def run(self) -> None:
        while True:
            await self._wake.wait()
            while self._pending:
                key = next(iter(self._pending))
                del self._pending[key]
                if self._needs_check(key):
                    await self.check_now(key)
            self._wake.clear()

    # Persistence, so a restart doesn't hide everything until it's all been rechecked.

    def _load(self) -> None:
        path = self.settings.availability_file
        try:
            raw = json.loads(path.read_text())
            self._verdicts = {
                _decode(key): Verdict(bool(value["available"]), float(value["checked_at"]))
                for key, value in raw.items()
            }
        except FileNotFoundError:
            return
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            log.warning("Ignoring unreadable %s: %s", path, exc)

    def _save(self) -> None:
        path = self.settings.availability_file
        cutoff = self._clock() - FORGET_AFTER_SECONDS
        self._verdicts = {k: v for k, v in self._verdicts.items() if v.checked_at >= cutoff}
        data = {
            _encode(key): {"available": v.available, "checked_at": v.checked_at}
            for key, v in self._verdicts.items()
        }
        temporary = path.with_suffix(path.suffix + ".tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(data))
            temporary.replace(path)
        except OSError as exc:
            log.warning("Could not save %s: %s", path, exc)
            with contextlib.suppress(OSError):
                temporary.unlink()
