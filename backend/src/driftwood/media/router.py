from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request

from driftwood.indexers.errors import IndexerError
from driftwood.media.home import HomeService
from driftwood.media.releases import ReleaseService
from driftwood.media.schemas import (
    HomePage,
    MediaDetails,
    MediaSummary,
    MediaType,
    ReleaseNfo,
    ReleaseSearch,
    SearchStatus,
    SubtitleTrack,
    WatchPlan,
)
from driftwood.media.service import MediaService
from driftwood.media.watch import WatchService
from driftwood.selection.nfo import parse_nfo

router = APIRouter()


def get_media_service(request: Request) -> MediaService:
    return request.app.state.media_service


def get_home_service(request: Request) -> HomeService:
    return request.app.state.home_service


def get_release_service(request: Request) -> ReleaseService:
    return request.app.state.release_service


def get_watch_service(request: Request) -> WatchService:
    return request.app.state.watch_service


MediaServiceDep = Annotated[MediaService, Depends(get_media_service)]
HomeServiceDep = Annotated[HomeService, Depends(get_home_service)]
ReleaseServiceDep = Annotated[ReleaseService, Depends(get_release_service)]
WatchServiceDep = Annotated[WatchService, Depends(get_watch_service)]


@router.get("/home")
async def home(service: HomeServiceDep) -> HomePage:
    """Featured highlights plus rows of suggestions for the home page."""
    return await service.page()


@router.get("/search")
async def search(
    service: MediaServiceDep,
    q: Annotated[str, Query(max_length=200)] = "",
) -> list[MediaSummary]:
    """
    Instant, typo- and abbreviation-tolerant title suggestions across movies
    and TV, popular titles first. Every result carries its image paths.
    """
    query = q.strip()
    if not query:
        return []
    return await service.search(query)


@router.get("/search/status")
async def search_status(service: MediaServiceDep) -> SearchStatus:
    return service.titles.status


@router.get("/media/{media_type}/{media_id}")
async def media_details(
    service: MediaServiceDep,
    media_type: MediaType,
    media_id: Annotated[int, Path(gt=0)],
) -> MediaDetails:
    details = await service.details(media_type, media_id)
    if details is None:
        raise HTTPException(status_code=404, detail="Media not found")
    return details


@router.get("/media/{media_type}/{media_id}/releases")
async def media_releases(
    service: ReleaseServiceDep,
    media_type: MediaType,
    media_id: Annotated[int, Path(gt=0)],
) -> ReleaseSearch:
    """
    Torrents the configured indexers have for this title. Indexer failures are
    reported in `failures` rather than failing the request.
    """
    result = await service.search(media_type, media_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Media not found")
    return result


@router.get("/media/{media_type}/{media_id}/watch")
async def media_watch(
    service: WatchServiceDep,
    media_type: MediaType,
    media_id: Annotated[int, Path(gt=0)],
    season: Annotated[int | None, Query(ge=0)] = None,
    episode: Annotated[int | None, Query(ge=1)] = None,
) -> WatchPlan:
    """
    Searches the indexers and picks the release to grab for watching right
    away (a modest 1080p encode when available), with the best release of
    every other quality slot as manual upgrades. Series default to S01E01.
    `POST /api/downloads` grabs one.
    """
    plan = await service.plan(media_type, media_id, season=season, episode=episode)
    if plan is None:
        raise HTTPException(status_code=404, detail="Media not found")
    return plan


@router.get("/releases/{indexer}/{guid}/nfo")
async def release_nfo(
    service: ReleaseServiceDep,
    indexer: Annotated[str, Path(max_length=64)],
    guid: Annotated[str, Path(max_length=128)],
) -> ReleaseNfo:
    """A release's NFO and what Driftwood reads from it (subtitles, audio languages)."""
    try:
        text = await service.nfo_text(indexer, guid)
    except IndexerError as exc:
        raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}") from exc
    if text is None:
        return ReleaseNfo()
    info = parse_nfo(text)
    return ReleaseNfo(
        text=text,
        subtitles_known=info.subtitles_known,
        subtitles=[SubtitleTrack(language=t.language, forced=t.forced) for t in info.subtitles],
        audio_languages=list(info.audio_languages),
    )
