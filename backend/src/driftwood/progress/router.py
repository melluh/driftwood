from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request

from driftwood.auth.router import UserDep
from driftwood.db import DbSession
from driftwood.media.schemas import MediaType
from driftwood.progress.schemas import (
    ContinueWatching,
    WatchHistoryPage,
    WatchProgress,
    WatchProgressUpdate,
)
from driftwood.progress.service import InvalidEpisodeError, WatchProgressService

router = APIRouter(prefix="/progress", tags=["progress"])


def get_progress_service(request: Request) -> WatchProgressService:
    return request.app.state.progress_service


ProgressServiceDep = Annotated[WatchProgressService, Depends(get_progress_service)]
MediaId = Annotated[int, Path(gt=0)]


@router.get("/continue")
async def continue_watching(
    service: ProgressServiceDep, db: DbSession, user: UserDep
) -> list[ContinueWatching]:
    """Movies and episodes left part-way, and series' next episodes; most recent first."""
    return await service.continue_watching(db, user)


@router.get("/history")
async def watch_history(
    service: ProgressServiceDep,
    db: DbSession,
    user: UserDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> WatchHistoryPage:
    """Movies and episodes the user watched, most recent first, with how far they got."""
    return await service.history(db, user, offset, limit)


@router.get("/{media_type}/{media_id}")
async def title_progress(
    service: ProgressServiceDep,
    db: DbSession,
    user: UserDep,
    media_type: MediaType,
    media_id: MediaId,
) -> list[WatchProgress]:
    """The movie's progress (zero or one entry), or that of every episode played."""
    return await service.for_title(db, user, media_type, media_id)


@router.put("/{media_type}/{media_id}")
async def save_progress(
    service: ProgressServiceDep,
    db: DbSession,
    user: UserDep,
    media_type: MediaType,
    media_id: MediaId,
    body: WatchProgressUpdate,
) -> WatchProgress:
    """Records where playback is. Past 90% the movie / episode counts as completed."""
    try:
        return await service.save(db, user, media_type, media_id, body)
    except InvalidEpisodeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
