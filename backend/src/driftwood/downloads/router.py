from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status

from driftwood.auth.router import UserDep
from driftwood.media.schemas import MediaType

from .schemas import DownloadStatus, StartDownload
from .service import DownloadError, DownloadService

router = APIRouter(prefix="/downloads", tags=["downloads"])
DownloadId = Annotated[int, Path(gt=0)]


def get_download_service(request: Request) -> DownloadService:
    return request.app.state.download_service


DownloadServiceDep = Annotated[DownloadService, Depends(get_download_service)]


def _http(exc: DownloadError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


@router.post("", status_code=status.HTTP_201_CREATED)
async def start_download(
    service: DownloadServiceDep, user: UserDep, body: StartDownload
) -> DownloadStatus:
    """
    Fetch a release's .torrent from its indexer and add it to qBittorrent. Once
    complete it is linked into the library and `file_id` says what to play.
    Asking again for a release that's still downloading returns that download.
    """
    try:
        return await service.start(body, user_id=user.id)
    except DownloadError as exc:
        raise _http(exc) from exc


@router.get("")
async def active_download(
    service: DownloadServiceDep,
    user: UserDep,
    media_type: MediaType,
    media_id: Annotated[int, Query(gt=0)],
    season: Annotated[int | None, Query(ge=0)] = None,
    episode: Annotated[int | None, Query(ge=1)] = None,
) -> DownloadStatus | None:
    """The download in progress for a title (series: an episode, default S01E01), or null."""
    return await service.active_for(media_type, media_id, season, episode, user_id=user.id)


@router.get("/{download_id}")
async def download_status(
    service: DownloadServiceDep, user: UserDep, download_id: DownloadId
) -> DownloadStatus:
    """Progress, speed and ETA, refreshed from qBittorrent every couple of seconds."""
    result = await service.get(download_id, user_id=user.id)
    if result is None:
        raise HTTPException(status_code=404, detail="Download not found")
    return result


@router.delete("/{download_id}")
async def cancel_download(
    service: DownloadServiceDep, user: UserDep, download_id: DownloadId
) -> DownloadStatus:
    """Stop the download and delete what qBittorrent downloaded so far. Only the user who
    started it may (403 for anyone else)."""
    try:
        result = await service.cancel(download_id, user_id=user.id)
    except DownloadError as exc:
        raise _http(exc) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Download not found")
    return result
