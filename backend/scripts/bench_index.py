"""
Benchmarks the title index against the real TMDB export: build time, memory
and per-query latency. Downloads the export first if the local copy is stale.

    uv run python scripts/bench_index.py [extra queries...]
"""

import asyncio
import resource
import statistics
import sys
import time

from driftwood.config import get_settings
from driftwood.titles.download import index_path, is_stale, refresh_title_index
from driftwood.titles.index import TitleIndex

DEFAULT_QUERIES = [
    "a",
    "the",
    "star",
    "star wars",
    "lotr",
    "got",
    "matrx",
    "the matrix",
    "borat",
    "breaking bad",
    "oak street",
    "spirited away",
    "sen to chihiro",
    "the end of oak",
]
ROUNDS = 5


def rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


async def main() -> None:
    settings = get_settings().title_index
    if is_stale(settings.directory, settings.stale_after_hours):
        print("Downloading TMDB export...")
        start = time.perf_counter()
        await refresh_title_index(settings.directory)
        print(f"  done in {time.perf_counter() - start:.1f}s")

    baseline = rss_mb()
    start = time.perf_counter()
    index = TitleIndex.load(index_path(settings.directory), settings.head_size)
    print(f"Loaded {len(index):,} titles in {time.perf_counter() - start:.1f}s")
    print(f"Peak RSS: {rss_mb():.0f} MB (baseline {baseline:.0f} MB)\n")

    latencies: list[float] = []
    for query in DEFAULT_QUERIES + sys.argv[1:]:
        timings = []
        for _ in range(ROUNDS):
            start = time.perf_counter()
            results = index.search(query, settings)
            timings.append((time.perf_counter() - start) * 1000)
        latencies.extend(timings)
        print(f"{query!r}: {statistics.median(timings):.0f} ms")
        for item in results[:5]:
            tier = "S" if item.is_structural else "f"
            m = item.entry
            print(f"    [{tier} {item.tier_score:6.1f}] {m.title} ({m.media_type} {m.id})")

    latencies.sort()
    p50 = statistics.median(latencies)
    p95 = latencies[int(len(latencies) * 0.95)]
    print(f"\nLatency p50 {p50:.0f} ms, p95 {p95:.0f} ms")


if __name__ == "__main__":
    asyncio.run(main())
