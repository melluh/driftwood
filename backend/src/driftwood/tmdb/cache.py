import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Hashable


class AsyncTtlCache[K: Hashable, V]:
    """
    A small in-memory TTL + LRU cache for async lookups. Concurrent requests
    for the same missing key share one in-flight fetch. Failed fetches are not
    cached.
    """

    def __init__(self, ttl_seconds: float, max_entries: int) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._entries: OrderedDict[K, tuple[float, V]] = OrderedDict()
        self._in_flight: dict[K, asyncio.Future[V]] = {}

    def _get_fresh(self, key: K) -> tuple[bool, V | None]:
        cached = self._entries.get(key)
        if cached is None:
            return False, None
        expires_at, value = cached
        if expires_at < time.monotonic():
            del self._entries[key]
            return False, None
        self._entries.move_to_end(key)
        return True, value

    def _store(self, key: K, value: V) -> None:
        self._entries[key] = (time.monotonic() + self.ttl_seconds, value)
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    async def get(self, key: K, fetch: Callable[[], Awaitable[V]]) -> V:
        hit, value = self._get_fresh(key)
        if hit:
            return value  # type: ignore[return-value]

        if (pending := self._in_flight.get(key)) is not None:
            return await asyncio.shield(pending)

        future: asyncio.Future[V] = asyncio.get_running_loop().create_future()
        self._in_flight[key] = future
        try:
            value = await fetch()
        except asyncio.CancelledError:
            future.cancel()
            raise
        except Exception as exc:
            future.set_exception(exc)
            future.exception()  # mark retrieved so waiter-less failures don't warn
            raise
        else:
            self._store(key, value)
            future.set_result(value)
            return value
        finally:
            del self._in_flight[key]
