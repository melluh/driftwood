from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request

from driftwood.media.home import HomeService
from driftwood.media.schemas import (
    HomePage,
    MediaDetails,
    MediaSummary,
    MediaType,
    SearchStatus,
)
from driftwood.media.service import MediaService

router = APIRouter()


def get_media_service(request: Request) -> MediaService:
    return request.app.state.media_service


def get_home_service(request: Request) -> HomeService:
    return request.app.state.home_service


MediaServiceDep = Annotated[MediaService, Depends(get_media_service)]
HomeServiceDep = Annotated[HomeService, Depends(get_home_service)]


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
