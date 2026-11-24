from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request

from driftwood.media.home import HomeService
from driftwood.media.releases import ReleaseService
from driftwood.media.schemas import (
    HomePage,
    MediaDetails,
    MediaSummary,
    MediaType,
    ReleaseSearch,
    SearchStatus,
    WatchPlan,
)
from driftwood.media.service import MediaService
from driftwood.media.watch import WatchService

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
    Nothing is downloaded yet.
    """
    plan = await service.plan(media_type, media_id, season=season, episode=episode)
    if plan is None:
        raise HTTPException(status_code=404, detail="Media not found")
    return plan
