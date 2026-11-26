import asyncio
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status
from fastapi.responses import FileResponse

from driftwood.auth.router import UserDep
from driftwood.db import DbSession
from driftwood.playback.errors import PlaybackError
from driftwood.playback.schemas import PlaybackOffer, PlaybackRequest, PlaybackTrickplay
from driftwood.playback.service import PlaybackService

router = APIRouter(prefix="/playback", tags=["playback"])
SessionId = Annotated[str, Path(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]
Rendition = Annotated[str, Path(pattern=r"^(a\d+|video)$")]
# Everything served here is bytes from a torrent, or made from them: the browser
# must take it for the type it's served as, and never run it as a page of ours.
_UNTRUSTED = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "sandbox; default-src 'none'",
}
_NO_STORE = {"Cache-Control": "no-store", **_UNTRUSTED}
_PRIVATE = {"Cache-Control": "private, max-age=3600", **_UNTRUSTED}


def get_playback_service(request: Request) -> PlaybackService:
    return request.app.state.playback_service


PlaybackServiceDep = Annotated[PlaybackService, Depends(get_playback_service)]


def _http(exc: PlaybackError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.post("")
async def start_playback(
    service: PlaybackServiceDep, db: DbSession, user: UserDep, body: PlaybackRequest
) -> PlaybackOffer:
    """Open a session for the best version of a title this browser can play.

    Returns no session, but the versions and why each can't play, when none can."""
    try:
        return await service.create(db, user.id, body)
    except PlaybackError as exc:
        raise _http(exc) from exc


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def stop_playback(service: PlaybackServiceDep, user: UserDep, session_id: SessionId) -> None:
    await service.stop(session_id, user.id)


@router.get("/{session_id}/file", response_class=FileResponse)
async def direct_file(service: PlaybackServiceDep, user: UserDep, session_id: SessionId):
    try:
        path = service.direct_file(session_id, user.id)
    except PlaybackError as exc:
        raise _http(exc) from exc
    return FileResponse(path, media_type="video/mp4", headers=_PRIVATE)


@router.get("/{session_id}/hls/{rendition}/index.m3u8", response_class=Response)
async def playlist(
    service: PlaybackServiceDep, user: UserDep, session_id: SessionId, rendition: Rendition
) -> Response:
    try:
        text = service.playlist(session_id, user.id, rendition)
    except PlaybackError as exc:
        raise _http(exc) from exc
    return Response(text, media_type="application/vnd.apple.mpegurl", headers=_NO_STORE)


@router.get("/{session_id}/hls/{rendition}/{index}.ts", response_class=FileResponse)
async def segment(
    service: PlaybackServiceDep,
    user: UserDep,
    session_id: SessionId,
    rendition: Rendition,
    index: Annotated[int, Path(ge=0)],
):
    try:
        path = await service.segment(session_id, user.id, rendition, index)
    except PlaybackError as exc:
        raise _http(exc) from exc
    return FileResponse(path, media_type="video/mp2t", headers=_PRIVATE)


@router.get("/{session_id}/subtitles/{track}.{kind}", response_class=FileResponse)
async def subtitle(
    service: PlaybackServiceDep,
    user: UserDep,
    session_id: SessionId,
    track: Annotated[int, Path(ge=0)],
    kind: Literal["vtt", "ass", "sup"],
):
    try:
        path = await service.subtitle(session_id, user.id, track, kind)
    except PlaybackError as exc:
        raise _http(exc) from exc
    media_type = {
        "vtt": "text/vtt; charset=utf-8",
        "ass": "text/x-ssa; charset=utf-8",
        "sup": "application/octet-stream",
    }[kind]
    return FileResponse(path, media_type=media_type, headers=_PRIVATE)


@router.get("/{session_id}/trickplay")
async def trickplay(
    service: PlaybackServiceDep,
    user: UserDep,
    session_id: SessionId,
    position: Annotated[float | None, Query(ge=0)] = None,
) -> PlaybackTrickplay | None:
    """The session's seek-bar thumbnails so far, while they're being made.

    `position` (seconds) is where the viewer is: the sheets there are made next."""
    try:
        return service.trickplay_status(session_id, user.id, position)
    except PlaybackError as exc:
        raise _http(exc) from exc


@router.get("/{session_id}/trickplay/{index}.jpg", response_class=FileResponse)
async def trickplay_sheet(
    service: PlaybackServiceDep,
    user: UserDep,
    session_id: SessionId,
    index: Annotated[int, Path(ge=0)],
):
    try:
        path = await asyncio.to_thread(service.trickplay_sheet, session_id, user.id, index)
    except PlaybackError as exc:
        raise _http(exc) from exc
    return FileResponse(path, media_type="image/jpeg", headers=_PRIVATE)


@router.get("/{session_id}/fonts/{index}", response_class=FileResponse)
async def font(
    service: PlaybackServiceDep,
    user: UserDep,
    session_id: SessionId,
    index: Annotated[int, Path(ge=0)],
):
    try:
        path, media_type = await service.font(session_id, user.id, index)
    except PlaybackError as exc:
        raise _http(exc) from exc
    return FileResponse(path, media_type=media_type, headers=_PRIVATE)
