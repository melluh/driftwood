import asyncio
import logging
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath

from sqlalchemy import delete, select

from driftwood.config import LibraryRoot, LibrarySettings
from driftwood.db import Database
from driftwood.db.models import MediaFile, MediaFileLink, MediaFileState, utcnow
from driftwood.selection.classification import classify_release

from .matching import Link, match_file
from .schemas import ScanReport

log = logging.getLogger(__name__)

type WalkEntry = tuple[str, int, int]


@dataclass(frozen=True)
class _WalkResult:
    files: list[WalkEntry]
    accessible: bool


def _walk_entries(
    root_path: Path,
    start_path: Path,
    *,
    extensions: frozenset[str],
    ignored_dirs: frozenset[str],
    min_size_bytes: int,
    exact_file: bool,
) -> _WalkResult:
    """Walk synchronously; called in a worker thread."""
    if exact_file:
        try:
            if (
                start_path.name.startswith(".")
                or start_path.name in {"@eaDir", "#recycle"}
                or start_path.suffix.casefold() not in extensions
                or start_path.stem.casefold() == "sample"
                or start_path.stem.casefold().endswith(("-sample", ".sample"))
            ):
                return _WalkResult([], True)
            stat = start_path.stat()
        except FileNotFoundError:
            return _WalkResult([], True)
        except OSError:
            log.warning("Could not inspect library file %s", start_path, exc_info=True)
            return _WalkResult([], False)
        if stat.st_size < min_size_bytes:
            return _WalkResult([], True)
        relative = start_path.relative_to(root_path).as_posix()
        return _WalkResult([(relative, stat.st_size, stat.st_mtime_ns)], True)

    pending = [start_path]
    files: list[WalkEntry] = []
    accessible = False

    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = list(iterator)
        except OSError:
            log.warning("Could not read library directory %s", directory, exc_info=True)
            if directory == start_path:
                return _WalkResult(files, False)
            continue

        if directory == start_path:
            accessible = True

        for entry in entries:
            name = entry.name
            if name.startswith(".") or name in {"@eaDir", "#recycle"}:
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    if name.casefold() not in ignored_dirs:
                        pending.append(Path(entry.path))
                    continue
                if exact_file and Path(entry.path) != start_path:
                    continue
                if not entry.is_file(follow_symlinks=True):
                    continue
                suffix = Path(name).suffix.casefold()
                if suffix not in extensions:
                    continue
                stem = Path(name).stem.casefold()
                if stem == "sample" or stem.endswith(("-sample", ".sample")):
                    continue
                stat = entry.stat(follow_symlinks=True)
            except OSError:
                log.warning("Could not inspect library entry %s", entry.path, exc_info=True)
                continue
            if stat.st_size < min_size_bytes:
                continue
            relative = Path(entry.path).relative_to(root_path).as_posix()
            files.append((relative, stat.st_size, stat.st_mtime_ns))

    return _WalkResult(files, accessible)


def _json_safe(value: object) -> object:
    if isinstance(value, tuple | list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    return value


def _attributes(filename: str) -> dict[str, object]:
    values = asdict(classify_release(Path(filename).stem))
    result = _json_safe(values)
    assert isinstance(result, dict)
    return result


def _link_rows(links: list[Link], *, file_id: int | None = None) -> list[MediaFileLink]:
    return [
        MediaFileLink(
            file_id=file_id,
            media_type=link.media_type.value,
            media_id=link.media_id,
            season=link.season,
            episode=link.episode,
        )
        for link in links
    ]


class Scanner:
    def __init__(
        self,
        settings: LibrarySettings,
        database: Database,
        *,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.settings = settings
        self.database = database
        self.clock = clock

    async def scan_all(self) -> ScanReport:
        report = ScanReport()
        for root in self.settings.roots:
            root_report = await self._scan_root(root, root.path.absolute())
            self._merge(report, root_report)
        self._log_report(report)
        return report

    async def scan_path(self, absolute_path: Path) -> ScanReport:
        target = absolute_path.absolute()
        for root in self.settings.roots:
            root_path = root.path.absolute()
            try:
                relative = target.relative_to(root_path)
            except ValueError:
                continue
            if target == root_path:
                report = await self._scan_root(root, target)
                self._log_report(report)
                return report
            if target.is_symlink() and target.is_dir():
                report = ScanReport()
                self._log_report(report)
                return report
            ignored = {name.casefold() for name in self.settings.ignored_dirs}
            file_target = target.is_file() or (
                not target.exists() and target.suffix.casefold() in self.settings.video_extensions
            )
            parent_parts = relative.parts[:-1] if file_target else relative.parts
            if any(
                part.startswith(".") or part in {"@eaDir", "#recycle"} for part in relative.parts
            ) or any(part.casefold() in ignored for part in parent_parts):
                report = ScanReport()
                self._log_report(report)
                return report
            report = await self._scan_root(
                root,
                target,
                scope=PurePosixPath(relative.as_posix()),
            )
            self._log_report(report)
            return report
        raise ValueError(f"path is not inside a configured library root: {absolute_path}")

    async def _scan_root(
        self,
        root: LibraryRoot,
        start_path: Path,
        *,
        scope: PurePosixPath | None = None,
    ) -> ScanReport:
        root_path = root.path.absolute()
        if not root_path.is_dir():
            log.warning("Library root %s is not a readable directory: %s", root.name, root_path)
            return ScanReport(skipped_roots=[root.name])

        exact_file = start_path.is_file() or (
            not start_path.exists()
            and bool(start_path.suffix)
            and start_path.suffix.casefold() in self.settings.video_extensions
        )
        walk = await asyncio.to_thread(
            _walk_entries,
            root_path,
            start_path,
            extensions=frozenset(ext.casefold() for ext in self.settings.video_extensions),
            ignored_dirs=frozenset(name.casefold() for name in self.settings.ignored_dirs),
            min_size_bytes=int(self.settings.min_size_mb * 1024 * 1024),
            exact_file=exact_file,
        )
        if not walk.accessible:
            log.warning("Skipping missing reconciliation for library root %s", root.name)
            return ScanReport(skipped_roots=[root.name])

        now = self.clock()
        grace = timedelta(days=self.settings.missing_grace_days)
        report = ScanReport()
        async with self.database.sessionmaker() as db, db.begin():
            rows = list(
                (await db.scalars(select(MediaFile).where(MediaFile.root == root.name))).all()
            )
            if scope is not None:
                scope_text = scope.as_posix()
                if exact_file:
                    rows = [row for row in rows if row.path == scope_text]
                else:
                    prefix = f"{scope_text.rstrip('/')}/"
                    rows = [
                        row for row in rows if row.path == scope_text or row.path.startswith(prefix)
                    ]

            existing = {row.path: row for row in rows}
            found = {path: (size, mtime_ns) for path, size, mtime_ns in walk.files}

            for path, (size, mtime_ns) in found.items():
                relative_path = PurePosixPath(path)
                row = existing.get(path)
                if row is None:
                    links = match_file(relative_path, root.kind)
                    if not links:
                        report.unmatched += 1
                        log.debug("Unmatched library file %s/%s", root.name, path)
                        continue
                    row = MediaFile(
                        root=root.name,
                        path=path,
                        size=size,
                        mtime_ns=mtime_ns,
                        state=MediaFileState.present.value,
                        missing_since=None,
                        attributes=_attributes(path),
                        probe=None,
                        first_seen_at=now,
                        last_seen_at=now,
                        links=_link_rows(links),
                    )
                    db.add(row)
                    report.added += 1
                    continue

                row.last_seen_at = now
                if row.state == MediaFileState.missing.value:
                    row.state = MediaFileState.present.value
                    row.missing_since = None
                if row.size == size and row.mtime_ns == mtime_ns:
                    continue

                links = match_file(relative_path, root.kind)
                if not links:
                    await db.delete(row)
                    report.removed += 1
                    continue
                row.size = size
                row.mtime_ns = mtime_ns
                row.attributes = _attributes(path)
                await db.execute(delete(MediaFileLink).where(MediaFileLink.file_id == row.id))
                db.add_all(_link_rows(links, file_id=row.id))
                report.updated += 1

            in_scope = set(existing) | set(found)
            present_rows = [row for row in existing.values() if row.state == "present"]
            if not found and present_rows:
                log.warning(
                    "Library scan for %s found no video files while %d files are present; "
                    "leaving missing state unchanged",
                    root.name,
                    len(present_rows),
                )
            else:
                for path, row in existing.items():
                    if path not in in_scope or path in found:
                        continue
                    if row.state == MediaFileState.present.value:
                        row.state = MediaFileState.missing.value
                        row.missing_since = now
                        report.missing += 1
                    elif row.missing_since is not None and row.missing_since + grace <= now:
                        await db.delete(row)
                        report.removed += 1

        return report

    @staticmethod
    def _merge(target: ScanReport, source: ScanReport) -> None:
        target.added += source.added
        target.updated += source.updated
        target.missing += source.missing
        target.removed += source.removed
        target.unmatched += source.unmatched
        target.skipped_roots.extend(source.skipped_roots)

    @staticmethod
    def _log_report(report: ScanReport) -> None:
        log.info(
            "Library scan: added=%d updated=%d missing=%d removed=%d unmatched=%d skipped_roots=%s",
            report.added,
            report.updated,
            report.missing,
            report.removed,
            report.unmatched,
            report.skipped_roots,
        )
