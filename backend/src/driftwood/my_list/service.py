"""Each user's "My list": titles saved to come back to, shown as a shelf on the home page."""

import asyncio
import logging

import httpx
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from driftwood.db.models import MyListItem, User, utcnow
from driftwood.media.mapping import to_summary
from driftwood.media.schemas import MediaSummary, MediaType
from driftwood.tmdb.client import TmdbClient, TmdbNotFoundError

log = logging.getLogger(__name__)


class MyListService:
    def __init__(self, tmdb: TmdbClient) -> None:
        self.tmdb = tmdb

    async def _hydrate(self, item: MyListItem) -> MediaSummary | None:
        """Current TMDB display data, falling back to the stored snapshot when
        TMDB is unreachable. Titles TMDB no longer knows are left out."""
        media_type = MediaType(item.media_type)
        try:
            data = await self.tmdb.details(media_type, item.media_id)
        except TmdbNotFoundError:
            return None
        except httpx.HTTPError:
            log.warning("Could not hydrate %s %d", media_type, item.media_id, exc_info=True)
            return MediaSummary(
                media_type=media_type,
                id=item.media_id,
                title=item.title,
                year=item.year,
                poster_path=item.poster_path,
            )
        return to_summary(media_type, data)

    async def items(self, db: AsyncSession, user: User) -> list[MediaSummary]:
        """The user's list, most recently added first."""
        rows = await db.scalars(
            select(MyListItem)
            .where(MyListItem.user_id == user.id)
            .order_by(MyListItem.added_at.desc(), MyListItem.id.desc())
        )
        hydrated = await asyncio.gather(*(self._hydrate(row) for row in rows))
        return [summary for summary in hydrated if summary is not None]

    async def _find(
        self, db: AsyncSession, user: User, media_type: MediaType, media_id: int
    ) -> MyListItem | None:
        return await db.scalar(
            select(MyListItem).where(
                MyListItem.user_id == user.id,
                MyListItem.media_type == media_type.value,
                MyListItem.media_id == media_id,
            )
        )

    async def contains(
        self, db: AsyncSession, user: User, media_type: MediaType, media_id: int
    ) -> bool:
        return await self._find(db, user, media_type, media_id) is not None

    async def add(self, db: AsyncSession, user: User, media_type: MediaType, media_id: int) -> bool:
        """Saves a title (idempotent). False when TMDB doesn't know it."""
        if await self._find(db, user, media_type, media_id) is not None:
            return True
        try:
            summary = to_summary(media_type, await self.tmdb.details(media_type, media_id))
        except TmdbNotFoundError:
            return False
        db.add(
            MyListItem(
                user_id=user.id,
                media_type=media_type.value,
                media_id=media_id,
                title=summary.title,
                year=summary.year,
                poster_path=summary.poster_path,
                added_at=utcnow(),
            )
        )
        try:
            await db.commit()
        except IntegrityError:
            # A concurrent request saved it first.
            await db.rollback()
        return True

    async def remove(
        self, db: AsyncSession, user: User, media_type: MediaType, media_id: int
    ) -> None:
        await db.execute(
            delete(MyListItem).where(
                MyListItem.user_id == user.id,
                MyListItem.media_type == media_type.value,
                MyListItem.media_id == media_id,
            )
        )
        await db.commit()
