"""Watch progress per user: resume points, what's been finished, and "Continue watching"."""

import asyncio
import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from driftwood.db.models import User, WatchProgress, utcnow
from driftwood.media.mapping import to_summary
from driftwood.media.schemas import MediaType
from driftwood.progress.schemas import ContinueWatching, WatchProgressUpdate
from driftwood.progress.schemas import WatchProgress as WatchProgressOut
from driftwood.tmdb.client import TmdbClient, TmdbNotFoundError

log = logging.getLogger(__name__)

type TmdbJson = dict[str, Any]

STARTED_SECONDS = 30.0
"""Less than this in, nothing worth resuming (the user only peeked)."""
FINISHED_RATIO = 0.9
"""This far through counts as watched: what's left is mostly credits."""
CONTINUE_WATCHING_LIMIT = 20


class InvalidEpisodeError(ValueError):
    pass


def is_finished(row: WatchProgress) -> bool:
    return row.position >= row.duration * FINISHED_RATIO


def is_in_progress(row: WatchProgress) -> bool:
    return row.position >= STARTED_SECONDS and not is_finished(row)


def resume_at(row: WatchProgress) -> float:
    return row.position if is_in_progress(row) else 0.0


def to_schema(row: WatchProgress) -> WatchProgressOut:
    return WatchProgressOut(
        season=row.season,
        episode=row.episode,
        position=row.position,
        duration=row.duration,
        completed=row.completed,
        resume_at=resume_at(row),
        updated_at=row.updated_at,
    )


def next_episode(details: TmdbJson, season: int, episode: int) -> tuple[int, int] | None:
    """The episode after `season`x`episode` that has already aired, from TMDB series details.

    Specials (season 0) don't lead into the regular seasons."""
    counts = {
        s["season_number"]: s.get("episode_count") or 0
        for s in details.get("seasons") or []
        if s.get("season_number") is not None
    }
    if episode < counts.get(season, 0):
        candidate = (season, episode + 1)
    elif season == 0:
        return None
    else:
        later = sorted(number for number, count in counts.items() if number > season and count)
        if not later:
            return None
        candidate = (later[0], 1)
    last = details.get("last_episode_to_air") or {}
    if last.get("season_number") is None or last.get("episode_number") is None:
        return None
    return candidate if candidate <= (last["season_number"], last["episode_number"]) else None


class WatchProgressService:
    def __init__(self, tmdb: TmdbClient) -> None:
        self.tmdb = tmdb

    @staticmethod
    def _where(
        user: User, media_type: MediaType, media_id: int, season: int | None, episode: int | None
    ):
        return (
            WatchProgress.user_id == user.id,
            WatchProgress.media_type == media_type.value,
            WatchProgress.media_id == media_id,
            WatchProgress.season.is_(None) if season is None else WatchProgress.season == season,
            WatchProgress.episode.is_(None)
            if episode is None
            else WatchProgress.episode == episode,
        )

    async def for_title(
        self, db: AsyncSession, user: User, media_type: MediaType, media_id: int
    ) -> list[WatchProgressOut]:
        """The movie's progress, or every episode of a series the user has played."""
        rows = await db.scalars(
            select(WatchProgress)
            .where(
                WatchProgress.user_id == user.id,
                WatchProgress.media_type == media_type.value,
                WatchProgress.media_id == media_id,
            )
            .order_by(WatchProgress.season, WatchProgress.episode)
        )
        return [to_schema(row) for row in rows]

    async def save(
        self,
        db: AsyncSession,
        user: User,
        media_type: MediaType,
        media_id: int,
        update: WatchProgressUpdate,
    ) -> WatchProgressOut:
        if media_type is MediaType.tv and (update.season is None or update.episode is None):
            raise InvalidEpisodeError("Series progress needs a season and episode")
        if media_type is MediaType.movie and (
            update.season is not None or update.episode is not None
        ):
            raise InvalidEpisodeError("Movies have no seasons or episodes")
        position = min(update.position, update.duration)
        where = self._where(user, media_type, media_id, update.season, update.episode)

        for attempt in range(2):
            row = await db.scalar(select(WatchProgress).where(*where))
            if row is None:
                row = WatchProgress(
                    user_id=user.id,
                    media_type=media_type.value,
                    media_id=media_id,
                    season=update.season,
                    episode=update.episode,
                    completed=False,
                )
                db.add(row)
            row.position = position
            row.duration = update.duration
            row.completed = row.completed or is_finished(row)
            row.updated_at = utcnow()
            try:
                await db.commit()
            except IntegrityError:
                # Another request (a second tab) created the row first: update that one.
                await db.rollback()
                if attempt:
                    raise
                continue
            break
        return to_schema(row)

    async def continue_watching(self, db: AsyncSession, user: User) -> list[ContinueWatching]:
        """Movies left part-way, and per series the episode left part-way or the next one up.
        Most recently watched first."""
        rows = await db.scalars(
            select(WatchProgress)
            .where(WatchProgress.user_id == user.id)
            .order_by(WatchProgress.updated_at.desc(), WatchProgress.id.desc())
        )
        # Per title, the latest play that got anywhere (in progress, or finished).
        latest: dict[tuple[str, int], WatchProgress] = {}
        episodes: dict[tuple[int, int, int], WatchProgress] = {}
        for row in rows:
            if (
                row.media_type == MediaType.tv.value
                and row.season is not None
                and row.episode is not None
            ):
                episodes[row.media_id, row.season, row.episode] = row
            key = (row.media_type, row.media_id)
            if key not in latest and (is_in_progress(row) or is_finished(row)):
                latest[key] = row

        candidates = [
            row
            for row in latest.values()
            if row.media_type == MediaType.tv.value or is_in_progress(row)
        ][: CONTINUE_WATCHING_LIMIT * 2]
        entries = await asyncio.gather(*(self._entry(row, episodes) for row in candidates))
        return [entry for entry in entries if entry is not None][:CONTINUE_WATCHING_LIMIT]

    async def _entry(
        self, row: WatchProgress, episodes: dict[tuple[int, int, int], WatchProgress]
    ) -> ContinueWatching | None:
        media_type = MediaType(row.media_type)
        try:
            details = await self.tmdb.details(media_type, row.media_id)
        except TmdbNotFoundError:
            return None
        except httpx.HTTPError:
            log.warning("Could not hydrate %s %d", media_type, row.media_id, exc_info=True)
            return None
        media = to_summary(media_type, details)

        if media_type is MediaType.movie:
            return ContinueWatching(
                media=media, position=row.position, duration=row.duration, updated_at=row.updated_at
            )

        assert row.season is not None and row.episode is not None
        if is_in_progress(row):
            season, episode = row.season, row.episode
            position, duration, up_next = row.position, row.duration, False
        else:
            following = next_episode(details, row.season, row.episode)
            if following is None:
                return None
            season, episode = following
            seen = episodes.get((row.media_id, season, episode))
            position = resume_at(seen) if seen else 0.0
            duration = seen.duration if seen else None
            up_next = True

        title, runtime = await self._episode_info(row.media_id, season, episode)
        return ContinueWatching(
            media=media,
            season=season,
            episode=episode,
            episode_title=title,
            position=position,
            duration=duration if duration is not None else runtime,
            up_next=up_next,
            updated_at=row.updated_at,
        )

    async def _episode_info(
        self, series_id: int, season: int, episode: int
    ) -> tuple[str | None, float | None]:
        """The episode's name and runtime (seconds), when TMDB has them."""
        try:
            data = await self.tmdb.season(series_id, season)
        except (TmdbNotFoundError, httpx.HTTPError):
            return None, None
        for item in data.get("episodes") or []:
            if item.get("episode_number") == episode:
                runtime = item.get("runtime")
                return item.get("name") or None, runtime * 60.0 if runtime else None
        return None, None
