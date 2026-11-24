import asyncio
from pathlib import Path
from typing import Any

import pytest

from driftwood.config import HomeSettings
from driftwood.media.availability import AvailabilityChecker, MediaKey
from driftwood.media.home import HomeService
from driftwood.media.schemas import MediaType

MOVIE, TV = MediaType.movie, MediaType.tv


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


class FakeCheck:
    def __init__(self, available: set[MediaKey], failing: set[MediaKey] | None = None) -> None:
        self.available_keys = available
        self.failing = failing or set()
        self.calls: list[MediaKey] = []

    async def __call__(self, media_type: MediaType, media_id: int) -> bool:
        key = (media_type, media_id)
        self.calls.append(key)
        if key in self.failing:
            raise RuntimeError("indexer down")
        return key in self.available_keys


def settings(tmp_path: Path) -> HomeSettings:
    return HomeSettings(availability_file=tmp_path / "availability.json")


async def drain(checker: AvailabilityChecker) -> None:
    task = asyncio.create_task(checker.run())
    for _ in range(50):
        await asyncio.sleep(0)
    task.cancel()


async def test_checks_requested_titles_in_order_and_remembers_them(tmp_path: Path) -> None:
    check = FakeCheck({(MOVIE, 1)})
    checker = AvailabilityChecker(check, settings(tmp_path), clock=FakeClock())
    assert checker.available((MOVIE, 1)) is None

    checker.request([(MOVIE, 1), (TV, 2), (MOVIE, 1)])
    await drain(checker)
    assert check.calls == [(MOVIE, 1), (TV, 2)]
    assert checker.available((MOVIE, 1)) is True
    assert checker.available((TV, 2)) is False

    checker.request([(MOVIE, 1), (TV, 2)])
    await drain(checker)
    assert len(check.calls) == 2  # fresh verdicts aren't rechecked


async def test_stale_verdicts_are_kept_while_rechecked(tmp_path: Path) -> None:
    clock = FakeClock()
    check = FakeCheck({(MOVIE, 1)})
    checker = AvailabilityChecker(check, settings(tmp_path), clock=clock)
    checker.request([(MOVIE, 1), (MOVIE, 2)])
    await drain(checker)

    clock.now += 5 * 3600  # past the 4 h unavailable TTL, within the 24 h available one
    check.available_keys.add((MOVIE, 2))
    checker.request([(MOVIE, 1), (MOVIE, 2)])
    assert checker.available((MOVIE, 2)) is False
    await drain(checker)
    assert check.calls == [(MOVIE, 1), (MOVIE, 2), (MOVIE, 2)]
    assert checker.available((MOVIE, 2)) is True


async def test_failed_checks_stay_unknown_and_back_off(tmp_path: Path) -> None:
    clock = FakeClock()
    check = FakeCheck(set(), failing={(MOVIE, 1)})
    checker = AvailabilityChecker(check, settings(tmp_path), clock=clock)
    checker.request([(MOVIE, 1)])
    await drain(checker)
    assert checker.available((MOVIE, 1)) is None

    checker.request([(MOVIE, 1)])
    await drain(checker)
    assert len(check.calls) == 1

    clock.now += 11 * 60
    checker.request([(MOVIE, 1)])
    await drain(checker)
    assert len(check.calls) == 2


async def test_verdicts_survive_a_restart(tmp_path: Path) -> None:
    clock = FakeClock()
    checker = AvailabilityChecker(FakeCheck({(TV, 7)}), settings(tmp_path), clock=clock)
    checker.request([(TV, 7), (MOVIE, 8)])
    await drain(checker)

    check = FakeCheck(set())
    restarted = AvailabilityChecker(check, settings(tmp_path), clock=clock)
    assert restarted.available((TV, 7)) is True
    assert restarted.available((MOVIE, 8)) is False
    restarted.request([(TV, 7), (MOVIE, 8)])
    await drain(restarted)
    assert check.calls == []


def test_unreadable_file_is_ignored(tmp_path: Path) -> None:
    (tmp_path / "availability.json").write_text("{not json")
    checker = AvailabilityChecker(FakeCheck(set()), settings(tmp_path))
    assert checker.available((MOVIE, 1)) is None


class FakeTmdb:
    def __init__(self, ids: dict[MediaType, list[int]]) -> None:
        self.ids = ids

    async def popular(self, media_type: MediaType) -> list[dict[str, Any]]:
        name = "title" if media_type is MOVIE else "name"
        return [
            {
                "id": media_id,
                name: f"{media_type} {media_id}",
                "poster_path": "/p.jpg",
                "backdrop_path": "/b.jpg",
                "overview": "Something happens.",
            }
            for media_id in self.ids[media_type]
        ]


@pytest.fixture
def tmdb() -> FakeTmdb:
    return FakeTmdb({MOVIE: [1, 2, 3], TV: [10, 11]})


async def test_home_shows_only_titles_with_a_watchable_release(
    tmp_path: Path, tmdb: FakeTmdb
) -> None:
    check = FakeCheck({(MOVIE, 1), (MOVIE, 3)})
    checker = AvailabilityChecker(check, settings(tmp_path), clock=FakeClock())
    home = HomeService(tmdb, checker)  # type: ignore[arg-type]

    page = await home.page()
    assert page.rows == []  # nothing checked yet
    assert page.featured == []

    await drain(checker)
    # Interleaved, so the hero's candidates are checked first.
    assert check.calls == [(MOVIE, 1), (TV, 10), (MOVIE, 2), (TV, 11), (MOVIE, 3)]

    page = await home.page()
    assert [row.id for row in page.rows] == ["popular-movies"]
    assert [item.id for item in page.rows[0].items] == [1, 3]
    assert [(f.media_type, f.id) for f in page.featured] == [(MOVIE, 1), (MOVIE, 3)]


async def test_home_is_unfiltered_without_indexers(tmdb: FakeTmdb) -> None:
    page = await HomeService(tmdb, None).page()  # type: ignore[arg-type]
    assert [len(row.items) for row in page.rows] == [3, 2]
