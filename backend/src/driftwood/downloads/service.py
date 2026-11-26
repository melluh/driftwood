"""
Grabs a release through qBittorrent, follows it to completion, and imports it
into the library so it can be played.

One monitor loop polls qBittorrent for every active download (one request per
tick) and keeps the latest numbers in memory; status requests read those, so
any number of watchers costs qBittorrent nothing extra. Downloads live in the
database, so a restart picks up where it left off.
"""

import asyncio
import contextlib
import logging

import httpx
from sqlalchemy import select

from driftwood.config import DownloadsSettings, LibraryRoot, LibrarySettings
from driftwood.db import Database
from driftwood.db.models import ACTIVE_DOWNLOAD_STATES, Download, DownloadState, utcnow
from driftwood.indexers.errors import IndexerError
from driftwood.indexers.manager import IndexerManager
from driftwood.library.service import LibraryService
from driftwood.media.releases import ReleaseService
from driftwood.media.schemas import MediaType
from driftwood.playback.trickplay_generator import TrickplayGenerator

from .bencode import BencodeError, infohash
from .importer import ImportFailure, Target, execute, plan_import, to_local
from .qbittorrent import (
    CHECKING_STATES,
    ERROR_STATES,
    PAUSED_STATES,
    STALLED_STATES,
    QbittorrentClient,
    QbittorrentError,
    TorrentInfo,
)
from .schemas import DownloadStatus, StartDownload, TorrentActivity

log = logging.getLogger(__name__)

_IDLE_POLL_SECONDS = 30
"""With nothing active the loop only wakes up when a download starts (or this often)."""


class DownloadError(Exception):
    """A download can't be started; `status_code` is the HTTP status to answer with."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _activity(info: TorrentInfo) -> TorrentActivity:
    if info.complete:
        return "complete"
    if info.state in PAUSED_STATES:
        return "paused"
    if info.state in CHECKING_STATES:
        return "checking"
    if info.state in STALLED_STATES:
        # metaDL / stalled before the first byte: still finding peers.
        return "connecting" if info.downloaded == 0 else "stalled"
    if info.state in {"downloading", "forcedDL"}:
        return "downloading"
    return "unknown"


class DownloadService:
    def __init__(
        self,
        settings: DownloadsSettings,
        library_settings: LibrarySettings,
        database: Database,
        *,
        releases: ReleaseService,
        indexers: IndexerManager,
        library: LibraryService,
        client: QbittorrentClient | None,
        trickplay: TrickplayGenerator | None = None,
    ) -> None:
        self.settings = settings
        self.library_settings = library_settings
        self.database = database
        self.releases = releases
        self.indexers = indexers
        self.library = library
        self.client = client
        self.trickplay = trickplay
        self._live: dict[str, TorrentInfo] = {}
        """Latest qBittorrent numbers by infohash."""
        self._client_error: str | None = None
        """Set while qBittorrent can't be reached."""
        self._imports: dict[int, asyncio.Task[None]] = {}
        self._wake = asyncio.Event()
        self._start_lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return self.client is not None

    def root_for(self, media_type: MediaType) -> LibraryRoot | None:
        kind = "movies" if media_type is MediaType.movie else "tv"
        wanted = self.settings.movies_root if kind == "movies" else self.settings.tv_root
        for root in self.library_settings.roots:
            if (root.name == wanted) if wanted else (root.kind == kind):
                return root
        return None

    # -- API ---------------------------------------------------------------------------------

    async def start(self, request: StartDownload, *, user_id: int | None) -> DownloadStatus:
        """Hand the release to qBittorrent (once: a repeat request returns the same download)."""
        if self.client is None:
            raise DownloadError("No download client is configured", 503)
        root = self.root_for(request.media_type)
        if root is None:
            kind = "movies" if request.media_type is MediaType.movie else "tv"
            raise DownloadError(f"No library root of kind {kind!r} to put the download in", 503)
        season = episode = None
        if request.media_type is MediaType.tv:
            season, episode = request.season or 1, request.episode or 1

        async with self._start_lock:
            async with self.database.sessionmaker() as db:
                existing = await db.scalar(
                    select(Download)
                    .where(
                        Download.indexer == request.indexer,
                        Download.guid == request.guid,
                        Download.media_type == request.media_type.value,
                        Download.media_id == request.media_id,
                        Download.season.is_(None) if season is None else Download.season == season,
                        Download.episode.is_(None)
                        if episode is None
                        else Download.episode == episode,
                        Download.state.in_(ACTIVE_DOWNLOAD_STATES),
                    )
                    .order_by(Download.id.desc())
                )
                if existing is not None:
                    return self._status(existing, user_id)

            lookup = await self.releases.find(
                request.media_type, request.media_id, season=season, episode=episode
            )
            if lookup is None:
                raise DownloadError("Media not found", 404)
            release = next(
                (
                    r
                    for r in lookup.result.releases
                    if r.indexer_id == request.indexer and r.guid == request.guid
                ),
                None,
            )
            if release is None:
                raise DownloadError(
                    "That release isn't in the indexer's results anymore; search again", 409
                )
            try:
                torrent = await self.indexers.download(release)
                torrent_hash = infohash(torrent)
            except (IndexerError, httpx.HTTPError, TimeoutError) as exc:
                raise DownloadError(f"Couldn't fetch the .torrent: {exc}", 502) from exc
            except BencodeError as exc:
                raise DownloadError(f"The indexer sent an invalid .torrent: {exc}", 502) from exc
            try:
                await self.client.add(torrent, torrent_hash)
            except QbittorrentError as exc:
                raise DownloadError(str(exc), 502) from exc

            now = utcnow()
            row = Download(
                user_id=user_id,
                media_type=request.media_type.value,
                media_id=request.media_id,
                season=season,
                episode=episode,
                title=lookup.media.title,
                year=lookup.media.year,
                indexer=release.indexer_id,
                guid=release.guid,
                release_title=release.title,
                infohash=torrent_hash,
                size=release.size,
                state=DownloadState.downloading.value,
                created_at=now,
                updated_at=now,
            )
            async with self.database.sessionmaker() as db, db.begin():
                db.add(row)
            log.info(
                "Downloading %s (%s) for %s %d",
                release.title,
                torrent_hash,
                request.media_type.value,
                request.media_id,
            )
        self._wake.set()
        return self._status(row, user_id)

    async def get(self, download_id: int, *, user_id: int | None) -> DownloadStatus | None:
        """A download's status as `user_id` sees it (only its owner may cancel it)."""
        async with self.database.sessionmaker() as db:
            row = await db.get(Download, download_id)
        return self._status(row, user_id) if row else None

    async def active_for(
        self,
        media_type: MediaType,
        media_id: int,
        season: int | None,
        episode: int | None,
        *,
        user_id: int | None,
    ) -> DownloadStatus | None:
        """The download in progress for a title (or episode), if there is one."""
        query = select(Download).where(
            Download.media_type == media_type.value,
            Download.media_id == media_id,
            Download.state.in_(ACTIVE_DOWNLOAD_STATES),
        )
        if media_type is MediaType.tv:
            query = query.where(
                Download.season == (season or 1), Download.episode == (episode or 1)
            )
        async with self.database.sessionmaker() as db:
            row = await db.scalar(query.order_by(Download.id.desc()))
        return self._status(row, user_id) if row else None

    async def cancel(self, download_id: int, *, user_id: int | None) -> DownloadStatus | None:
        """Stop a download and delete its data from qBittorrent; only its owner may."""
        async with self.database.sessionmaker() as db:
            row = await db.get(Download, download_id)
        if row is None:
            return None
        if not self._owned_by(row, user_id):
            raise DownloadError("Only the person who started this download can cancel it", 403)
        if row.state == DownloadState.importing.value:
            raise DownloadError("It's already being added to the library", 409)
        if row.state != DownloadState.downloading.value:
            return self._status(row, user_id)
        if self.client is not None:
            # Fresh numbers, not the last tick's: the torrent may have moved on since.
            try:
                info = await self.client.info(row.infohash)
            except QbittorrentError as exc:
                raise DownloadError(str(exc), 502) from exc
            if info is not None and not self._cancellable(info):
                raise DownloadError(
                    f"It's {info.tracker_share:.0%} downloaded: cancelling now would leave a hit "
                    "and run on the tracker, so it has to finish and seed",
                    409,
                )
            try:
                await self.client.delete(row.infohash, delete_files=True)
            except QbittorrentError as exc:
                raise DownloadError(str(exc), 502) from exc
        self._live.pop(row.infohash, None)
        await self._set_state(row.id, DownloadState.cancelled)
        return await self.get(row.id, user_id=user_id)

    def _cancellable(self, info: TorrentInfo) -> bool:
        return info.tracker_share < self.settings.cancel_limit

    @staticmethod
    def _owned_by(row: Download, user_id: int | None) -> bool:
        """Downloads are shared (anyone may follow one), but only the user who started
        one may cancel it. One without an owner (theirs was deleted) is anyone's."""
        return row.user_id is None or row.user_id == user_id

    def _status(self, row: Download, user_id: int | None) -> DownloadStatus:
        status = DownloadStatus(
            id=row.id,
            state=row.state,  # type: ignore[arg-type]
            media_type=MediaType(row.media_type),
            media_id=row.media_id,
            season=row.season,
            episode=row.episode,
            release_title=row.release_title,
            size=row.size,
            error=row.error,
            file_id=row.file_id,
            created_at=row.created_at,
            completed_at=row.completed_at,
        )
        if row.state in (DownloadState.completed.value, DownloadState.importing.value):
            status.progress = 1
            status.downloaded = row.size or 0
        info = self._live.get(row.infohash)
        if row.state == DownloadState.downloading.value:
            if info is not None:
                status.activity = _activity(info)
                status.progress = info.progress
                status.size = info.size or row.size
                status.downloaded = info.downloaded
                status.download_speed = info.download_speed
                status.eta_seconds = info.eta
                status.seeds = info.seeds
                status.peers = info.peers
                status.can_cancel = self._cancellable(info) and self._owned_by(row, user_id)
            else:
                status.activity = "connecting"
                # Unknown progress: offer it, and let `cancel` check the real numbers.
                status.can_cancel = self._owned_by(row, user_id)
            status.error = self._client_error
        return status

    # -- Monitor -----------------------------------------------------------------------------

    async def run(self) -> None:
        if self.client is None:
            log.info("no download client configured")
            return
        await self._resume_imports()
        while True:
            active = False
            try:
                active = await self._tick()
            except Exception:
                log.exception("Download monitor tick failed")
            self._wake.clear()
            interval = self.settings.poll_interval_seconds if active else _IDLE_POLL_SECONDS
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=interval)

    async def _resume_imports(self) -> None:
        """An import cut short by a restart starts over (it is idempotent)."""
        async with self.database.sessionmaker() as db, db.begin():
            rows = await db.scalars(
                select(Download).where(Download.state == DownloadState.importing.value)
            )
            for row in rows:
                row.state = DownloadState.downloading.value

    async def _tick(self) -> bool:
        """Poll qBittorrent once; returns whether anything is still downloading."""
        assert self.client is not None
        async with self.database.sessionmaker() as db:
            rows = list(
                await db.scalars(
                    select(Download).where(Download.state == DownloadState.downloading.value)
                )
            )
        if not rows:
            self._live.clear()
            return False
        try:
            live = await self.client.info_many([row.infohash for row in rows])
        except QbittorrentError as exc:
            if self._client_error is None:
                log.warning("Can't read download progress: %s", exc)
            self._client_error = "Can't reach qBittorrent right now"
            return True
        self._client_error = None
        self._live = live

        for row in rows:
            info = live.get(row.infohash)
            if info is None:
                await self._fail(row.id, "The torrent was removed from qBittorrent")
            elif info.state in ERROR_STATES:
                await self._fail(row.id, f"qBittorrent reports a problem with it ({info.state})")
            elif info.complete and row.id not in self._imports:
                task = asyncio.create_task(self._import(row, info), name=f"import-{row.id}")
                self._imports[row.id] = task
                task.add_done_callback(lambda _, key=row.id: self._imports.pop(key, None))
        return True

    async def _set_state(self, download_id: int, state: DownloadState, **values: object) -> None:
        async with self.database.sessionmaker() as db, db.begin():
            row = await db.get(Download, download_id)
            if row is None:
                return
            row.state = state.value
            row.updated_at = utcnow()
            for key, value in values.items():
                setattr(row, key, value)

    async def _fail(self, download_id: int, message: str) -> None:
        log.warning("Download %d failed: %s", download_id, message)
        await self._set_state(download_id, DownloadState.failed, error=message[:2048])

    async def _import(self, row: Download, info: TorrentInfo) -> None:
        assert self.client is not None
        await self._set_state(row.id, DownloadState.importing, size=info.size or row.size)
        media_type = MediaType(row.media_type)
        root = self.root_for(media_type)
        try:
            if root is None:
                raise ImportFailure("The library root for it is no longer configured")
            files = await self.client.files(row.infohash)
            target = Target(
                media_type=media_type,
                media_id=row.media_id,
                title=row.title,
                year=row.year,
                season=row.season,
                episode=row.episode,
            )
            plan = plan_import(
                files,
                save_path=to_local(info.save_path, self.client.settings.path_mappings),
                root=root.path,
                target=target,
                release_title=row.release_title,
                video_extensions=frozenset(
                    ext.casefold() for ext in self.library_settings.video_extensions
                ),
                min_size_bytes=int(self.library_settings.min_size_mb * 1024 * 1024),
                subtitles=self.settings.subtitles,
            )
            await asyncio.to_thread(execute, plan, self.settings.fallback)
            file_id = await self.library.add_file(root, plan.video.destination)
            if file_id is None:
                raise ImportFailure(
                    f"Imported to {plan.video.destination}, but the library didn't recognise it"
                )
        except (ImportFailure, QbittorrentError) as exc:
            await self._fail(row.id, str(exc))
            return
        except OSError as exc:
            await self._fail(row.id, f"Couldn't import the files: {exc}")
            return
        except Exception as exc:
            log.exception("Import of download %d failed", row.id)
            await self._fail(row.id, f"Couldn't import the files: {exc!r}")
            return
        await self._set_state(
            row.id, DownloadState.completed, file_id=file_id, completed_at=utcnow(), error=None
        )
        log.info("Download %d is in the library as file %d", row.id, file_id)
        if self.trickplay is not None:
            # Often watched right away: seek-bar thumbnails are wanted as soon as possible.
            self.trickplay.request(plan.video.destination)

    async def shutdown(self) -> None:
        for task in list(self._imports.values()):
            task.cancel()
        if self._imports:
            await asyncio.gather(*self._imports.values(), return_exceptions=True)
        if self.client is not None:
            await self.client.aclose()
