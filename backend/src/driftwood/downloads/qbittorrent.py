"""A small client for qBittorrent's WebUI API (v2): add, inspect and remove torrents."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from driftwood.config import QbittorrentSettings

log = logging.getLogger(__name__)

NO_ETA = 8_640_000
"""qBittorrent's "infinity" ETA (100 days)."""

COMPLETE_STATES = frozenset(
    {"uploading", "stalledUP", "pausedUP", "stoppedUP", "queuedUP", "forcedUP"}
)
"""The torrent has all its data (`checkingUP` is still verifying it)."""
ERROR_STATES = frozenset({"error", "missingFiles"})
PAUSED_STATES = frozenset({"pausedDL", "stoppedDL"})
STALLED_STATES = frozenset({"stalledDL", "metaDL", "queuedDL"})
CHECKING_STATES = frozenset(
    {"checkingDL", "checkingUP", "checkingResumeData", "allocating", "moving"}
)


class QbittorrentError(Exception):
    """qBittorrent can't be reached or refused a request."""


@dataclass(frozen=True)
class TorrentInfo:
    hash: str
    name: str
    state: str
    progress: float
    """0..1."""
    size: int
    """Bytes of the files selected for download."""
    downloaded: int
    """Bytes of selected files that are complete (`size - amount_left`)."""
    transferred: int
    """Bytes received from peers in all, as reported to the tracker (includes discarded
    pieces, so it can exceed `downloaded`)."""
    total_size: int
    """The whole torrent, selected or not: what trackers measure a share of."""
    download_speed: int
    """Bytes per second."""
    eta: int | None
    """Seconds; None when qBittorrent can't estimate it."""
    seeds: int
    """Seeds connected to."""
    seeds_total: int
    """Seeds in the swarm, as last reported by the tracker."""
    peers: int
    save_path: str

    @property
    def tracker_share(self) -> float:
        """How much of the torrent the tracker sees as downloaded (0..1, may exceed 1)."""
        if self.total_size <= 0:
            return 0.0
        return max(self.downloaded, self.transferred) / self.total_size

    @property
    def complete(self) -> bool:
        return self.progress >= 1 and self.state in COMPLETE_STATES

    @classmethod
    def parse(cls, row: dict[str, Any]) -> "TorrentInfo":
        size = int(row.get("size") or 0)
        eta = int(row.get("eta") or 0)
        return cls(
            hash=str(row["hash"]),
            name=str(row.get("name") or ""),
            state=str(row.get("state") or "unknown"),
            progress=float(row.get("progress") or 0),
            size=size,
            downloaded=max(0, size - int(row.get("amount_left") or 0)),
            transferred=int(row.get("downloaded") or 0),
            total_size=int(row.get("total_size") or size),
            download_speed=int(row.get("dlspeed") or 0),
            eta=eta if 0 < eta < NO_ETA else None,
            seeds=int(row.get("num_seeds") or 0),
            seeds_total=max(0, int(row.get("num_complete") or 0)),
            peers=int(row.get("num_leechs") or 0),
            save_path=str(row.get("save_path") or ""),
        )


@dataclass(frozen=True)
class TorrentFile:
    name: str
    """Path inside the save path, including the torrent's own folder."""
    size: int
    progress: float


class QbittorrentClient:
    def __init__(
        self, settings: QbittorrentSettings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.settings = settings
        headers = {"Authorization": f"Bearer {settings.api_key}"} if settings.api_key else {}
        self.http = httpx.AsyncClient(
            base_url=settings.url.rstrip("/") + "/api/v2/",
            headers=headers,
            timeout=settings.timeout_seconds,
            transport=transport,
        )
        self._category_ready = False

    async def aclose(self) -> None:
        await self.http.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """A request authenticated with the API key (if any)."""
        try:
            response = await self.http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise QbittorrentError(f"can't reach qBittorrent: {exc!r}") from exc
        if response.status_code in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN):
            if self.settings.api_key:
                raise QbittorrentError("qBittorrent rejected the API key")
            raise QbittorrentError(
                "qBittorrent wants authentication: set DRIFTWOOD_DOWNLOADS__QBITTORRENT__API_KEY"
            )
        return response

    async def _ensure_category(self) -> None:
        if self._category_ready:
            return
        data = {"category": self.settings.category}
        if self.settings.save_path:
            data["savePath"] = self.settings.save_path
        response = await self._request("POST", "torrents/createCategory", data=data)
        # 409: it exists already. Anything else still lets `add` create it implicitly.
        if response.status_code not in (httpx.codes.OK, httpx.codes.CONFLICT):
            log.warning(
                "Creating qBittorrent category %r returned HTTP %d",
                self.settings.category,
                response.status_code,
            )
        self._category_ready = True

    async def add(self, torrent: bytes, infohash: str, *, tags: tuple[str, ...] = ()) -> None:
        """Add a .torrent unless qBittorrent has it already, and wait until it shows up."""
        if await self.info(infohash) is not None:
            return
        await self._ensure_category()
        data = {"category": self.settings.category}
        if self.settings.save_path:
            data["savepath"] = self.settings.save_path
        if tags:
            data["tags"] = ",".join(tags)
        response = await self._request(
            "POST",
            "torrents/add",
            data=data,
            files={"torrents": (f"{infohash}.torrent", torrent, "application/x-bittorrent")},
        )
        # "Fails." / 409 also covers a torrent that is already there; `info` below decides.
        if response.status_code not in (httpx.codes.OK, httpx.codes.CONFLICT):
            raise QbittorrentError(f"qBittorrent refused the torrent (HTTP {response.status_code})")
        # Adding is asynchronous inside qBittorrent; give it a moment to register.
        for _ in range(20):
            if await self.info(infohash) is not None:
                return
            await asyncio.sleep(0.25)
        raise QbittorrentError("qBittorrent didn't add the torrent")

    async def info(self, infohash: str) -> TorrentInfo | None:
        torrents = await self.info_many([infohash])
        return torrents.get(infohash.lower())

    async def info_many(self, infohashes: list[str]) -> dict[str, TorrentInfo]:
        """Torrents by (lowercase) infohash; torrents qBittorrent doesn't have are left out."""
        if not infohashes:
            return {}
        response = await self._request(
            "GET", "torrents/info", params={"hashes": "|".join(h.lower() for h in infohashes)}
        )
        if response.status_code != httpx.codes.OK:
            raise QbittorrentError(f"torrents/info returned HTTP {response.status_code}")
        torrents = [TorrentInfo.parse(row) for row in response.json()]
        return {torrent.hash.lower(): torrent for torrent in torrents}

    async def files(self, infohash: str) -> list[TorrentFile]:
        response = await self._request("GET", "torrents/files", params={"hash": infohash})
        if response.status_code != httpx.codes.OK:
            raise QbittorrentError(f"torrents/files returned HTTP {response.status_code}")
        return [
            TorrentFile(
                name=str(row["name"]),
                size=int(row.get("size") or 0),
                progress=float(row.get("progress") or 0),
            )
            for row in response.json()
        ]

    async def delete(self, infohash: str, *, delete_files: bool) -> None:
        response = await self._request(
            "POST",
            "torrents/delete",
            data={"hashes": infohash, "deleteFiles": "true" if delete_files else "false"},
        )
        if response.status_code != httpx.codes.OK:
            raise QbittorrentError(f"torrents/delete returned HTTP {response.status_code}")
