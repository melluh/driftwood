"""Playback sessions for files in the library.

A session belongs to one user and one file. It plays the file directly when
the browser can (MP4 with H.264 and AAC), otherwise as HLS with one rendition
per audio track: the video copied, the audio copied or encoded to AAC.
Renditions start ffmpeg on the first request and stop when nobody fetches from
them; the session goes when the player closes it or after a long idle time.
"""

import asyncio
import contextlib
import logging
import re
import secrets
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from driftwood.config import LibrarySettings, PlaybackSettings
from driftwood.db.models import MediaFile, MediaFileLink, MediaFileState
from driftwood.media.schemas import MediaType
from driftwood.playback.errors import PlaybackError
from driftwood.playback.policy import (
    PLAYABLE_SUFFIXES,
    AudioOutput,
    ClientCapabilities,
    audio_output,
    can_decode_audio,
    can_play_directly,
    video_problem,
)
from driftwood.playback.probe import MediaProbe, find_keyframes, probe_file
from driftwood.playback.process import input_args, spawn
from driftwood.playback.schemas import (
    PlaybackAudioTrack,
    PlaybackOffer,
    PlaybackRequest,
    PlaybackSession,
    PlaybackSubtitleTrack,
    PlaybackTrickplay,
    PlaybackVersion,
)
from driftwood.playback.segments import SegmentJob, SegmentPlan, SegmentSource
from driftwood.playback.subtitles import (
    SubtitleTrack,
    embedded_command,
    embedded_tracks,
    fingerprint,
    sidecar_commands,
    sidecar_tracks,
)
from driftwood.playback.trickplay import Trickplay, find_trickplay
from driftwood.playback.trickplay_generator import Priority, TrickplayGenerator, TrickplayJob

log = logging.getLogger(__name__)

API_PREFIX = "/api/playback"
_FONT_TYPES = {
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".ttc": "font/collection",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
}
"""What a font is served as, by its file name: never the type the file claims to be."""
_MAX_TRACKS = 64
"""Audio and embedded subtitle tracks offered, each: real files have a few dozen at most."""
_MAX_FONTS = 256
_EXTRACTION_TIMEOUT_SECONDS = 30 * 60
"""Extracting reads the whole file once; a slow disk can take minutes for a remux."""
_MAX_SESSIONS_PER_USER = 4
_REAP_INTERVAL_SECONDS = 15
_RESOLUTION = re.compile(r"(\d{3,4})p", re.IGNORECASE)


@dataclass
class _Audio:
    id: int
    stream: dict[str, Any]
    output: AudioOutput


@dataclass
class _Session:
    id: str
    user_id: int
    file_id: int
    path: Path
    probe: MediaProbe
    mode: str
    plan: SegmentPlan | None
    audio: list[_Audio]
    subtitles: list[SubtitleTrack]
    fonts: list[dict[str, Any]]
    directory: Path
    subtitle_directory: Path
    trickplay: Trickplay | None = None
    trickplay_job: TrickplayJob | None = None
    """Thumbnails being made while the session plays; `trickplay` once they're done."""
    created: float = field(default_factory=time.monotonic)
    last_used: float = field(default_factory=time.monotonic)
    jobs: dict[str, SegmentJob] = field(default_factory=dict)


@dataclass
class _Candidate:
    file: MediaFile
    path: Path | None = None
    probe: MediaProbe | None = None
    problem: str | None = None

    @property
    def height(self) -> int:
        video = self.probe.video if self.probe else None
        if video and isinstance(video.get("height"), int):
            return video["height"]
        match = _RESOLUTION.search(str(self.file.attributes.get("resolution") or ""))
        return int(match.group(1)) if match else 0


def _tags(stream: dict[str, Any]) -> dict[str, str]:
    tags = stream.get("tags")
    if not isinstance(tags, dict):
        return {}
    return {str(key).lower(): str(value) for key, value in tags.items()}


def _language(stream: dict[str, Any]) -> str | None:
    language = _tags(stream).get("language")
    return None if language in (None, "", "und") else language


def _disposition(stream: dict[str, Any], name: str) -> bool:
    disposition = stream.get("disposition")
    return isinstance(disposition, dict) and bool(disposition.get(name))


def _version(candidate: _Candidate, *, selected: bool) -> PlaybackVersion:
    attributes = candidate.file.attributes or {}
    video = candidate.probe.video if candidate.probe else None
    hdr = attributes.get("hdr_flags")
    return PlaybackVersion(
        file_id=candidate.file.id,
        name=PurePosixPath(candidate.file.path).name,
        height=candidate.height or None,
        source=str(attributes["source"]) if attributes.get("source") else None,
        video_codec=str(video["codec_name"]) if video and video.get("codec_name") else None,
        hdr_flags=[str(flag) for flag in hdr] if isinstance(hdr, list) else [],
        size=candidate.file.size,
        playable=candidate.problem is None,
        problem=candidate.problem,
        selected=selected,
    )


class PlaybackService:
    def __init__(self, settings: PlaybackSettings, library: LibrarySettings) -> None:
        self.settings = settings
        self.library = library
        self._sessions: dict[str, _Session] = {}
        self._indexing: dict[tuple[int, int], asyncio.Task[list[float]]] = {}
        self._extracting: dict[Path, asyncio.Task[None]] = {}
        self._reaper: asyncio.Task[None] | None = None
        self.trickplay = TrickplayGenerator(settings)

    @property
    def _session_root(self) -> Path:
        return self.settings.directory / "sessions"

    async def start(self) -> None:
        # Segments of sessions from a previous run are useless now.
        await asyncio.to_thread(shutil.rmtree, self._session_root, True)
        self._reaper = asyncio.create_task(self._reap_forever(), name="playback-reaper")

    async def shutdown(self) -> None:
        if self._reaper:
            self._reaper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reaper
        for session in list(self._sessions.values()):
            await self._close(session)
        for task in [*self._indexing.values(), *self._extracting.values()]:
            task.cancel()
        await self.trickplay.shutdown()

    @staticmethod
    def _finished(tasks: dict[Any, Any], key: object, task: asyncio.Task[Any]) -> None:
        tasks.pop(key, None)
        if not task.cancelled():
            task.exception()  # retrieved by the awaiting request, if it's still there

    # Starting playback

    async def create(
        self, db: AsyncSession, user_id: int, request: PlaybackRequest
    ) -> PlaybackOffer:
        capabilities = ClientCapabilities(
            hevc=request.capabilities.hevc, hevc_main10=request.capabilities.hevc_main10
        )
        candidates = [
            await self._candidate(db, media_file, capabilities)
            for media_file in await self._files(db, request)
        ]
        if not candidates:
            raise PlaybackError(404, "This title isn't in your library.")

        playable = [candidate for candidate in candidates if candidate.problem is None]
        if request.file_id is not None:
            chosen = next((c for c in candidates if c.file.id == request.file_id), None)
            if chosen is None:
                raise PlaybackError(404, "That version isn't in your library.")
        elif playable:
            chosen = max(playable, key=lambda c: (c.height, c.file.size))
        else:
            chosen = candidates[0]

        versions = [
            _version(candidate, selected=candidate is chosen)
            for candidate in sorted(candidates, key=lambda c: (c.height, c.file.size), reverse=True)
        ]
        if chosen.problem is not None:
            return PlaybackOffer(session=None, versions=versions, problem=chosen.problem)

        session = await self._open(db, user_id, chosen)
        return PlaybackOffer(session=self._describe(session), versions=versions)

    async def _files(self, db: AsyncSession, request: PlaybackRequest) -> list[MediaFile]:
        query = (
            select(MediaFile)
            .join(MediaFileLink, MediaFileLink.file_id == MediaFile.id)
            .where(
                MediaFile.state == MediaFileState.present.value,
                MediaFileLink.media_type == request.media_type.value,
                MediaFileLink.media_id == request.media_id,
            )
            .distinct()
        )
        if request.media_type is MediaType.tv:
            if request.season is None or request.episode is None:
                raise PlaybackError(422, "Pick an episode to play.")
            query = query.where(
                MediaFileLink.season == request.season,
                MediaFileLink.episode == request.episode,
            )
        return list((await db.scalars(query)).all())

    def _resolve(self, media_file: MediaFile) -> Path:
        root = next((root for root in self.library.roots if root.name == media_file.root), None)
        if root is None:
            raise PlaybackError(404, "The file's library folder is no longer configured.")
        try:
            root_path = root.path.resolve(strict=True)
            path = (root_path / PurePosixPath(media_file.path)).resolve(strict=True)
            path.relative_to(root_path)
        except (OSError, ValueError):
            raise PlaybackError(404, "The file is no longer on disk.") from None
        if not path.is_file():
            raise PlaybackError(404, "The file is no longer on disk.")
        return path

    async def _candidate(
        self, db: AsyncSession, media_file: MediaFile, capabilities: ClientCapabilities
    ) -> _Candidate:
        candidate = _Candidate(media_file)
        try:
            candidate.path = self._resolve(media_file)
            if candidate.path.suffix.casefold() not in PLAYABLE_SUFFIXES:
                raise PlaybackError(415, f"{candidate.path.suffix} files can't be played yet.")
            candidate.probe = await self._probe(db, media_file, candidate.path)
        except PlaybackError as exc:
            candidate.problem = exc.detail
            return candidate
        video = candidate.probe.video
        if candidate.probe.demuxer is None:
            # Probed before formats were restricted, and cached since.
            candidate.problem = "Only Matroska and MP4 files can be played."
        elif video is None:
            candidate.problem = "The file has no video stream."
        else:
            candidate.problem = video_problem(video, capabilities)
        return candidate

    async def _probe(self, db: AsyncSession, media_file: MediaFile, path: Path) -> MediaProbe:
        cached = MediaProbe.from_json(
            media_file.probe, size=media_file.size, mtime_ns=media_file.mtime_ns
        )
        if cached:
            return cached
        probe = await probe_file(self.settings.ffprobe, path)
        await self._store(db, media_file, probe)
        return probe

    async def _store(self, db: AsyncSession, media_file: MediaFile, probe: MediaProbe) -> None:
        media_file.probe = probe.to_json(size=media_file.size, mtime_ns=media_file.mtime_ns)
        await db.commit()

    async def _keyframes(
        self, db: AsyncSession, media_file: MediaFile, path: Path, probe: MediaProbe
    ) -> list[float]:
        if probe.keyframes:
            return probe.keyframes
        key = (media_file.id, media_file.mtime_ns)
        task = self._indexing.get(key)
        if task is None:
            task = asyncio.create_task(find_keyframes(self.settings.ffprobe, path, probe))
            self._indexing[key] = task
            task.add_done_callback(lambda t: self._finished(self._indexing, key, t))
        # shield: a client giving up shouldn't throw away a long packet scan.
        probe.keyframes = await asyncio.shield(task)
        await self._store(db, media_file, probe)
        return probe.keyframes

    async def _open(self, db: AsyncSession, user_id: int, candidate: _Candidate) -> _Session:
        assert candidate.path is not None and candidate.probe is not None
        probe = candidate.probe
        video = probe.video
        assert video is not None
        # Tracks ffmpeg may not decode are left out rather than failing the whole rendition.
        playable_audio = [stream for stream in probe.of_type("audio") if can_decode_audio(stream)]
        audio = [
            _Audio(id=index, stream=stream, output=audio_output(stream))
            for index, stream in enumerate(playable_audio[:_MAX_TRACKS])
        ]
        subtitles = embedded_tracks(probe.of_type("subtitle"))[:_MAX_TRACKS]
        subtitles += await asyncio.to_thread(sidecar_tracks, candidate.path, len(subtitles))
        fonts = (
            [
                stream
                for stream in probe.of_type("attachment")
                if Path(_tags(stream).get("filename", "")).suffix.casefold() in _FONT_TYPES
                or "font" in _tags(stream).get("mimetype", "")
            ][:_MAX_FONTS]
            if any(s.format == "ass" and s.stream_index is not None for s in subtitles)
            else []
        )

        trickplay = await asyncio.to_thread(
            find_trickplay,
            candidate.path,
            probe.duration,
            self.settings.trickplay_interval_seconds,
        )
        job = None
        if trickplay is None:
            # Made while this plays: sheets show up in the seek bar as they're done.
            job = await self.trickplay.submit(candidate.path, probe, Priority.watching)

        if can_play_directly(probe, candidate.path.suffix):
            mode, plan = "direct", None
        else:
            keyframes = await self._keyframes(db, candidate.file, candidate.path, probe)
            mode = "hls"
            plan = SegmentPlan.build(
                keyframes, probe.start_time, probe.duration, self.settings.segment_seconds
            )

        self._limit_sessions(user_id)
        identifier = secrets.token_urlsafe(16)
        session = _Session(
            id=identifier,
            user_id=user_id,
            file_id=candidate.file.id,
            path=candidate.path,
            probe=probe,
            mode=mode,
            plan=plan,
            audio=audio,
            subtitles=subtitles,
            fonts=fonts,
            directory=self._session_root / identifier,
            subtitle_directory=self.settings.directory
            / "subtitles"
            / f"{candidate.file.id}-{candidate.file.mtime_ns}-{fingerprint(subtitles)}",
            trickplay=trickplay,
            trickplay_job=job,
        )
        self._sessions[identifier] = session
        return session

    def _limit_sessions(self, user_id: int) -> None:
        mine = sorted(
            (s for s in self._sessions.values() if s.user_id == user_id),
            key=lambda s: s.last_used,
        )
        for session in mine[: max(0, len(mine) - _MAX_SESSIONS_PER_USER + 1)]:
            self._sessions.pop(session.id, None)
            task = asyncio.create_task(self._close(session))
            task.add_done_callback(lambda t: t.cancelled() or t.exception())

    def _describe(self, session: _Session) -> PlaybackSession:
        base = f"{API_PREFIX}/{session.id}"

        def audio_url(track: _Audio | None) -> str:
            if session.mode == "direct":
                return f"{base}/file"
            rendition = f"a{track.id}" if track else "video"
            return f"{base}/hls/{rendition}/index.m3u8"

        tracks = [
            PlaybackAudioTrack(
                id=track.id,
                language=_language(track.stream),
                title=_tags(track.stream).get("title"),
                codec=str(track.stream.get("codec_name") or "unknown"),
                channels=track.stream.get("channels"),
                default=_disposition(track.stream, "default"),
                url=audio_url(track),
            )
            for track in session.audio
        ]
        default = next((track for track in tracks if track.default), tracks[0] if tracks else None)
        return PlaybackSession(
            id=session.id,
            mode=session.mode,  # type: ignore[arg-type]
            duration=session.probe.duration,
            audio=tracks,
            url=default.url if default else audio_url(None),
            subtitles=[
                PlaybackSubtitleTrack(
                    id=subtitle.id,
                    language=subtitle.language,
                    title=subtitle.title,
                    forced=subtitle.forced,
                    hearing_impaired=subtitle.hearing_impaired,
                    external=subtitle.sidecar is not None,
                    format=subtitle.format,  # type: ignore[arg-type]
                    url=f"{base}/subtitles/{subtitle.id}.{subtitle.outputs[0]}",
                    text_url=(
                        f"{base}/subtitles/{subtitle.id}.vtt" if subtitle.format == "ass" else None
                    ),
                )
                for subtitle in session.subtitles
            ],
            fonts=[f"{base}/fonts/{index}" for index in range(len(session.fonts))],
            trickplay=self._describe_trickplay(session),
        )

    def _describe_trickplay(self, session: _Session) -> PlaybackTrickplay | None:
        job = session.trickplay_job
        if job is not None and not job.generating and job.error is None:
            session.trickplay, session.trickplay_job = job.trickplay(), None
            job = None
        if job is not None:
            if not job.generating and not job.ready:
                return None
            trickplay = job.trickplay()
            ready = [index in job.ready for index in range(trickplay.sheets)]
        elif session.trickplay is not None:
            trickplay = session.trickplay
            ready = [True] * trickplay.sheets
        else:
            return None
        base = f"{API_PREFIX}/{session.id}/trickplay"
        return PlaybackTrickplay(
            sheets=[f"{base}/{index}.jpg" for index in range(trickplay.sheets)],
            ready=ready,
            generating=job is not None and job.generating,
            columns=trickplay.columns,
            rows=trickplay.rows,
            width=trickplay.width,
            height=trickplay.height,
            interval=trickplay.interval,
            count=trickplay.count,
        )

    # Serving a session

    def session(self, session_id: str, user_id: int) -> _Session:
        session = self._sessions.get(session_id)
        if session is None or session.user_id != user_id:
            raise PlaybackError(404, "This playback session has ended.")
        session.last_used = time.monotonic()
        return session

    def direct_file(self, session_id: str, user_id: int) -> Path:
        session = self.session(session_id, user_id)
        if session.mode != "direct":
            raise PlaybackError(404, "This session streams HLS.")
        return session.path

    def trickplay_status(
        self, session_id: str, user_id: int, position: float | None
    ) -> PlaybackTrickplay | None:
        """The session's thumbnails so far; `position` is where the viewer is, to make
        the sheets there first."""
        session = self.session(session_id, user_id)
        if session.trickplay_job is not None and position is not None:
            session.trickplay_job.focus_on(position)
        return self._describe_trickplay(session)

    def trickplay_sheet(self, session_id: str, user_id: int, index: int) -> Path:
        session = self.session(session_id, user_id)
        if session.trickplay_job is not None:
            path = session.trickplay_job.sheet(index)
        else:
            path = session.trickplay.sheet(index) if session.trickplay else None
        if path is None:
            raise PlaybackError(404, "No such preview sheet.")
        return path

    def _job(self, session: _Session, rendition: str) -> SegmentJob:
        if session.plan is None:
            raise PlaybackError(404, "This session plays the file directly.")
        if job := session.jobs.get(rendition):
            return job
        if rendition == "video" and not session.audio:
            audio = None
        elif rendition.startswith("a") and rendition[1:].isdigit():
            audio = next((a for a in session.audio if a.id == int(rendition[1:])), None)
            if audio is None:
                raise PlaybackError(404, "No such audio track.")
        else:
            raise PlaybackError(404, "No such rendition.")
        video = session.probe.video
        demuxer = session.probe.demuxer
        assert video is not None and demuxer is not None
        job = SegmentJob(
            SegmentSource(
                ffmpeg=self.settings.ffmpeg,
                path=session.path,
                demuxer=demuxer,
                video_index=int(video["index"]),
                audio_index=int(audio.stream["index"]) if audio else None,
                audio=audio.output if audio else None,
            ),
            session.plan,
            session.directory / rendition,
            lead=self.settings.lead_segments,
            keep_behind=self.settings.keep_behind_segments,
        )
        session.jobs[rendition] = job
        return job

    def playlist(self, session_id: str, user_id: int, rendition: str) -> str:
        session = self.session(session_id, user_id)
        job = self._job(session, rendition)
        job.last_used = time.monotonic()
        return job.plan.playlist()

    async def segment(self, session_id: str, user_id: int, rendition: str, index: int) -> Path:
        session = self.session(session_id, user_id)
        return await self._job(session, rendition).segment(index)

    async def subtitle(self, session_id: str, user_id: int, track: int, kind: str) -> Path:
        session = self.session(session_id, user_id)
        subtitle = next((s for s in session.subtitles if s.id == track), None)
        if subtitle is None or kind not in subtitle.outputs:
            raise PlaybackError(404, "No such subtitle track.")
        directory = await self._extract(session)
        path = directory / f"{subtitle.id}.{kind}"
        if not path.is_file():
            raise PlaybackError(502, "This subtitle track couldn't be extracted.")
        return path

    async def font(self, session_id: str, user_id: int, index: int) -> tuple[Path, str]:
        session = self.session(session_id, user_id)
        if not 0 <= index < len(session.fonts):
            raise PlaybackError(404, "No such font.")
        directory = await self._extract(session)
        path = directory / f"font-{index}"
        if not path.is_file():
            raise PlaybackError(404, "The font couldn't be extracted.")
        suffix = Path(_tags(session.fonts[index]).get("filename", "")).suffix.casefold()
        return path, _FONT_TYPES.get(suffix, "application/octet-stream")

    async def _extract(self, session: _Session) -> Path:
        """Every subtitle track (and the fonts ASS needs), ready to serve.

        Embedded subtitle packets are spread through the whole file, so this
        reads all of it once; later sessions of the same file reuse the result."""
        directory = session.subtitle_directory
        if (directory / ".complete").exists():
            return directory
        task = self._extracting.get(directory)
        if task is None:
            task = asyncio.create_task(self._run_extraction(session))
            self._extracting[directory] = task
            task.add_done_callback(lambda t: self._finished(self._extracting, directory, t))
        await asyncio.shield(task)
        return directory

    async def _run_extraction(self, session: _Session) -> None:
        directory = session.subtitle_directory
        partial = directory.with_name(f"{directory.name}.partial-{secrets.token_hex(4)}")
        partial.mkdir(parents=True)
        command = [self.settings.ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
        for index, font in enumerate(session.fonts):
            command.extend([f"-dump_attachment:{font['index']}", str(partial / f"font-{index}")])
        assert session.probe.demuxer is not None
        command.extend(input_args(session.path, session.probe.demuxer))
        outputs = embedded_command(session.subtitles, partial)
        try:
            if outputs:
                await self._run_ffmpeg([*command, *outputs])
            for track in session.subtitles:
                if track.sidecar is None:
                    continue
                # A broken sidecar only loses its own track (served as a 502).
                try:
                    for args in await asyncio.to_thread(
                        sidecar_commands, self.settings.ffmpeg, track, partial
                    ):
                        await self._run_ffmpeg(args)
                except (OSError, PlaybackError) as exc:
                    log.warning("Skipping subtitle file %s: %s", track.sidecar.name, exc)
            (partial / ".complete").touch()
            await asyncio.to_thread(shutil.rmtree, directory, True)
            partial.rename(directory)
        except BaseException:
            await asyncio.to_thread(shutil.rmtree, partial, True)
            raise

    @staticmethod
    async def _run_ffmpeg(args: list[str]) -> None:
        process = await spawn(args)
        try:
            _, stderr = await asyncio.wait_for(
                process.communicate(), timeout=_EXTRACTION_TIMEOUT_SECONDS
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            raise PlaybackError(504, "Timed out extracting subtitles.") from None
        except BaseException:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise
        if process.returncode:
            lines = stderr.decode(errors="replace").strip().splitlines()
            raise PlaybackError(
                502, f"Couldn't extract subtitles: {lines[-1] if lines else 'ffmpeg failed'}"
            )

    # Ending sessions

    async def stop(self, session_id: str, user_id: int) -> None:
        session = self._sessions.get(session_id)
        if session is None or session.user_id != user_id:
            return
        self._sessions.pop(session_id, None)
        await self._close(session)

    async def _close(self, session: _Session) -> None:
        jobs, session.jobs = session.jobs, {}
        for job in jobs.values():
            await job.close()
        await asyncio.to_thread(shutil.rmtree, session.directory, True)

    async def reap(self) -> None:
        now = time.monotonic()
        for session in list(self._sessions.values()):
            if now - session.last_used > self.settings.session_idle_seconds:
                self._sessions.pop(session.id, None)
                await self._close(session)
                continue
            for rendition, job in list(session.jobs.items()):
                if now - job.last_used > self.settings.stream_idle_seconds:
                    # A paused player stops fetching; its segments come back on demand.
                    session.jobs.pop(rendition, None)
                    await job.close()

    async def _reap_forever(self) -> None:
        while True:
            await asyncio.sleep(_REAP_INTERVAL_SECONDS)
            try:
                await self.reap()
            except Exception:
                log.exception("Cleaning up playback sessions failed")
