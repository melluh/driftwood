import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from driftwood.config import LibraryRoot, LibrarySettings
from driftwood.db import Database
from driftwood.db.models import MediaFile, MediaFileLink, MediaFileState, utcnow
from driftwood.media.schemas import MediaType

from .scanner import Scanner
from .schemas import LibraryAvailability, LibraryEpisode, LibraryFile, LibraryStatus

log = logging.getLogger(__name__)
_RESOLUTION_NUMBER = re.compile(r"(\d+)")


class LibraryService:
    def __init__(self, settings: LibrarySettings, database: Database) -> None:
        self.settings = settings
        self.database = database
        self.scanner = Scanner(settings, database)
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[None]] = set()
        self._state: Literal["idle", "scanning"] = "idle"
        self._last_scan_at: datetime | None = None
        self._files = 0
        self._unmatched = 0

    @property
    def status(self) -> LibraryStatus:
        return LibraryStatus(
            state=self._state,
            last_scan_at=self._last_scan_at,
            files=self._files,
            unmatched=self._unmatched,
        )

    async def _scan_full(self) -> None:
        async with self._lock:
            self._state = "scanning"
            try:
                report = await self.scanner.scan_all()
                self._last_scan_at = utcnow()
                self._unmatched = report.unmatched
            except Exception:
                log.exception("Library scan failed")
            finally:
                self._state = "idle"
                await self._refresh_files()

    async def _refresh_files(self) -> None:
        try:
            async with self.database.sessionmaker() as db:
                self._files = (
                    await db.scalar(
                        select(func.count())
                        .select_from(MediaFile)
                        .where(MediaFile.state == MediaFileState.present.value)
                    )
                ) or 0
        except Exception:
            log.exception("Could not refresh library status")

    async def run(self) -> None:
        """Scan immediately and periodically; keep running after scan failures."""
        if not self.settings.roots:
            log.info("no library roots configured")
            while True:
                await asyncio.sleep(3600)

        await self._refresh_files()
        while True:
            await self._scan_full()
            await asyncio.sleep(self.settings.scan_interval_minutes * 60)

    def request_scan(self) -> bool:
        """Start a full scan in the background unless one is already running."""
        if self._lock.locked() or self._state == "scanning":
            return False
        self._state = "scanning"
        task = asyncio.create_task(self._scan_full(), name="library-scan")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return True

    async def add_file(self, root: LibraryRoot, path: Path) -> int | None:
        """
        Scan one new file in `root` right away (after any running scan) and
        return its id, or None when it didn't match a title.
        """
        async with self._lock:
            await self.scanner.scan_path(path)
        await self._refresh_files()
        relative = path.absolute().relative_to(root.path.absolute()).as_posix()
        async with self.database.sessionmaker() as db:
            return await db.scalar(
                select(MediaFile.id).where(
                    MediaFile.root == root.name,
                    MediaFile.path == relative,
                    MediaFile.state == MediaFileState.present.value,
                )
            )

    async def shutdown(self) -> None:
        """Stop on-demand scans before the database is disposed."""
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        self._state = "idle"

    async def availability(
        self, db: AsyncSession, media_type: MediaType, media_id: int
    ) -> LibraryAvailability:
        if not self.settings.roots:
            return LibraryAvailability(ready=False, files=[], episodes=[])
        rows = (
            await db.execute(
                select(MediaFile, MediaFileLink)
                .join(MediaFileLink, MediaFileLink.file_id == MediaFile.id)
                .where(
                    MediaFile.state == MediaFileState.present.value,
                    MediaFileLink.media_type == media_type.value,
                    MediaFileLink.media_id == media_id,
                )
            )
        ).all()
        grouped: dict[int, tuple[MediaFile, list[LibraryEpisode]]] = {}
        for media_file, link in rows:
            if media_file.id not in grouped:
                grouped[media_file.id] = (media_file, [])
            if link.season is not None and link.episode is not None:
                grouped[media_file.id][1].append(
                    LibraryEpisode(season=link.season, episode=link.episode)
                )

        files = []
        all_episodes: set[tuple[int, int]] = set()
        for media_file, episodes in grouped.values():
            attributes = media_file.attributes
            file_episodes = [
                LibraryEpisode(season=season, episode=episode)
                for season, episode in sorted({(ep.season, ep.episode) for ep in episodes})
            ]
            all_episodes.update((ep.season, ep.episode) for ep in file_episodes)
            files.append(
                LibraryFile(
                    id=media_file.id,
                    path=media_file.path,
                    size=media_file.size,
                    resolution=attributes.get("resolution"),
                    source=attributes.get("source"),
                    codec=attributes.get("codec"),
                    hdr_flags=attributes.get("hdr_flags", []),
                    audio_codecs=attributes.get("audio_codecs", []),
                    episodes=file_episodes,
                )
            )
        files.sort(key=self._file_order, reverse=True)
        episodes = (
            [
                LibraryEpisode(season=season, episode=episode)
                for season, episode in sorted(all_episodes)
            ]
            if media_type == MediaType.tv
            else []
        )
        return LibraryAvailability(ready=bool(files), files=files, episodes=episodes)

    @staticmethod
    def _file_order(file: LibraryFile) -> tuple[int, int]:
        resolution = _RESOLUTION_NUMBER.search(file.resolution or "")
        return (int(resolution.group(1)) if resolution else 0, file.size)
