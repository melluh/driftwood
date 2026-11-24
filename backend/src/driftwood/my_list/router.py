from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request

from driftwood.auth.router import UserDep
from driftwood.db import DbSession
from driftwood.media.schemas import MediaSummary, MediaType, Schema
from driftwood.my_list.service import MyListService

router = APIRouter(prefix="/my-list", tags=["my-list"])


def get_my_list_service(request: Request) -> MyListService:
    return request.app.state.my_list_service


MyListServiceDep = Annotated[MyListService, Depends(get_my_list_service)]
MediaId = Annotated[int, Path(gt=0)]


class MyListStatus(Schema):
    in_list: bool


@router.get("")
async def my_list(service: MyListServiceDep, db: DbSession, user: UserDep) -> list[MediaSummary]:
    """The signed-in user's saved titles, most recently added first."""
    return await service.items(db, user)


@router.get("/{media_type}/{media_id}")
async def my_list_status(
    service: MyListServiceDep,
    db: DbSession,
    user: UserDep,
    media_type: MediaType,
    media_id: MediaId,
) -> MyListStatus:
    return MyListStatus(in_list=await service.contains(db, user, media_type, media_id))


@router.put("/{media_type}/{media_id}")
async def add_to_my_list(
    service: MyListServiceDep,
    db: DbSession,
    user: UserDep,
    media_type: MediaType,
    media_id: MediaId,
) -> MyListStatus:
    """Saves a title to the list. Adding one that's already there is a no-op."""
    if not await service.add(db, user, media_type, media_id):
        raise HTTPException(status_code=404, detail="Media not found")
    return MyListStatus(in_list=True)


@router.delete("/{media_type}/{media_id}")
async def remove_from_my_list(
    service: MyListServiceDep,
    db: DbSession,
    user: UserDep,
    media_type: MediaType,
    media_id: MediaId,
) -> MyListStatus:
    """Removes a title from the list. Removing one that isn't there is a no-op."""
    await service.remove(db, user, media_type, media_id)
    return MyListStatus(in_list=False)
