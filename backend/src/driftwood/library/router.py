from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, status

from driftwood.auth.router import UserDep
from driftwood.db import DbSession
from driftwood.library.schemas import LibraryAvailability, LibraryStatus
from driftwood.library.service import LibraryService
from driftwood.media.schemas import MediaType

router = APIRouter(prefix="/library", tags=["library"])
MediaId = Annotated[int, Path(gt=0)]


def get_library_service(request: Request) -> LibraryService:
    return request.app.state.library_service


LibraryServiceDep = Annotated[LibraryService, Depends(get_library_service)]


@router.get("/status")
async def library_status(service: LibraryServiceDep, user: UserDep) -> LibraryStatus:
    return service.status


@router.post("/scan", status_code=status.HTTP_202_ACCEPTED)
async def request_library_scan(service: LibraryServiceDep, user: UserDep) -> LibraryStatus:
    service.request_scan()
    return service.status


@router.get("/{media_type}/{media_id}")
async def library_availability(
    service: LibraryServiceDep,
    db: DbSession,
    user: UserDep,
    media_type: MediaType,
    media_id: MediaId,
) -> LibraryAvailability:
    return await service.availability(db, media_type, media_id)
