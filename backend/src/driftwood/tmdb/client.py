from http import HTTPStatus
from typing import Any

import httpx

from driftwood.config import TmdbSettings
from driftwood.media.schemas import MediaType
from driftwood.tmdb.cache import AsyncTtlCache

type TmdbJson = dict[str, Any]

_DETAIL_APPENDS = "credits,external_ids"


class TmdbNotFoundError(Exception):
    pass


class TmdbClient:
    """
    Thin TMDB v3 client. Detail responses are cached in memory, so search
    hydration and the details page share one fetch per title.
    """

    def __init__(self, http: httpx.AsyncClient, settings: TmdbSettings) -> None:
        self.http = http
        self.settings = settings
        self._details_cache: AsyncTtlCache[tuple[MediaType, int], TmdbJson] = AsyncTtlCache(
            ttl_seconds=settings.cache_ttl_seconds, max_entries=settings.cache_max_entries
        )

    async def _get(self, path: str, **params: str) -> TmdbJson:
        response = await self.http.get(
            f"{self.settings.base_url}{path}",
            params={"api_key": self.settings.api_key, "language": self.settings.language, **params},
        )
        if response.status_code == HTTPStatus.NOT_FOUND:
            raise TmdbNotFoundError(path)
        response.raise_for_status()
        return response.json()

    async def details(self, media_type: MediaType, media_id: int) -> TmdbJson:
        """Full movie / TV details, including credits and external ids."""
        path = f"/{media_type.value}/{media_id}"
        return await self._details_cache.get(
            (media_type, media_id),
            lambda: self._get(path, append_to_response=_DETAIL_APPENDS),
        )
