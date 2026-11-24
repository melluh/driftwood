import asyncio

import pytest

from driftwood.tmdb.cache import AsyncTtlCache


async def test_concurrent_misses_share_one_fetch() -> None:
    cache: AsyncTtlCache[str, int] = AsyncTtlCache(ttl_seconds=60, max_entries=10)
    calls = 0

    async def fetch() -> int:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return 42

    results = await asyncio.gather(*(cache.get("k", fetch) for _ in range(5)))
    assert results == [42] * 5
    assert calls == 1


async def test_failures_are_not_cached() -> None:
    cache: AsyncTtlCache[str, int] = AsyncTtlCache(ttl_seconds=60, max_entries=10)

    async def boom() -> int:
        raise ValueError

    async def ok() -> int:
        return 1

    with pytest.raises(ValueError):
        await cache.get("k", boom)
    assert await cache.get("k", ok) == 1


async def test_lru_eviction() -> None:
    cache: AsyncTtlCache[int, int] = AsyncTtlCache(ttl_seconds=60, max_entries=2)
    for key in range(3):
        await cache.get(key, lambda key=key: asyncio.sleep(0, key))

    async def refetched() -> int:
        return -1

    assert await cache.get(0, refetched) == -1
    assert await cache.get(2, refetched) == 2
