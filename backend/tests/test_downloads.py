import errno
import hashlib
import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import httpx
import pytest

from driftwood.config import (
    DownloadsSettings,
    LibraryRoot,
    LibrarySettings,
    PathMapping,
    QbittorrentSettings,
)
from driftwood.db import Database
from driftwood.downloads import importer
from driftwood.downloads.bencode import encode, infohash
from driftwood.downloads.importer import (
    Placement,
    Target,
    choose_video,
    destination,
    place,
    plan_import,
    subtitle_suffix,
    to_local,
    version_label,
)
from driftwood.downloads.qbittorrent import QbittorrentClient, QbittorrentError, TorrentFile
from driftwood.downloads.schemas import StartDownload
from driftwood.downloads.service import DownloadError, DownloadService
from driftwood.indexers.manager import SearchResult
from driftwood.indexers.models import Release, SearchQuery
from driftwood.library.service import LibraryService
from driftwood.media.releases import ReleaseLookup
from driftwood.media.schemas import MediaDetails, MediaType

VIDEO_EXTENSIONS = frozenset({".mkv", ".mp4"})
DUNE = Target(MediaType.movie, 438631, "Dune", 2021)
BEAR = Target(MediaType.tv, 136315, "The Bear", 2022, season=1, episode=2)


def torrent_bytes(name: str = "Dune.2021.1080p.WEB-DL.H.264-FLUX.mkv") -> bytes:
    info = {"name": name, "length": 10, "piece length": 16384, "pieces": b"\0" * 20}
    return encode({"announce": "http://tracker.invalid/announce", "info": info})


# -- bencode -------------------------------------------------------------------------------


def test_infohash_is_sha1_of_the_raw_info_dictionary() -> None:
    info = {"name": "x.mkv", "length": 1, "piece length": 16384, "pieces": b"\1" * 20}
    torrent = encode({"announce": "http://t.invalid", "info": info, "zcomment": "after"})
    assert infohash(torrent) == hashlib.sha1(encode(info)).hexdigest()


def test_v2_only_torrents_use_the_truncated_sha256() -> None:
    info = {"name": "x.mkv", "meta version": 2, "piece length": 16384, "file tree": {}}
    torrent = encode({"info": info})
    assert infohash(torrent) == hashlib.sha256(encode(info)).hexdigest()[:40]


# -- importer ------------------------------------------------------------------------------


def test_version_label_keeps_what_the_scanner_reads() -> None:
    assert version_label("Dune.2021.1080p.WEB-DL.DDP5.1.Atmos.H.264-FLUX") == (
        "1080p WEB-DL H.264-FLUX"
    )
    assert version_label("Dune.2021.2160p.UHD.BluRay.REMUX.DV.HDR10.HEVC-GRP") == (
        "2160p Remux DV HDR10 HEVC-GRP"
    )


def test_destinations_follow_jellyfin_naming() -> None:
    root = Path("/media")
    movie = destination(
        root / "movies", DUNE, "Dune.2021.1080p.WEB-DL.H.264-FLUX", PurePosixPath("a/b.MKV")
    )
    assert movie == root / (
        "movies/Dune (2021) [tmdbid-438631]/"
        "Dune (2021) [tmdbid-438631] - 1080p WEB-DL H.264-FLUX.mkv"
    )
    episode = destination(
        root / "tv",
        BEAR,
        "The.Bear.S01E02.1080p.WEB-DL.HEVC-NTb",
        PurePosixPath("The.Bear.S01E02.1080p.WEB-DL.HEVC-NTb.mkv"),
    )
    assert episode == root / (
        "tv/The Bear (2022) [tmdbid-136315]/Season 01/"
        "The Bear (2022) S01E02 - 1080p WEB-DL HEVC-NTb.mkv"
    )


def test_unsafe_title_characters_are_dropped() -> None:
    target = Target(MediaType.movie, 1, "Mission: Impossible / Fallout?", 2018)
    path = destination(Path("/m"), target, "x.1080p.WEB-DL", PurePosixPath("x.mkv"))
    assert path.parent.name == "Mission Impossible - Fallout (2018) [tmdbid-1]"


@pytest.mark.parametrize(
    ("name", "suffix"),
    [
        ("Dune.2021.1080p.en.srt", ".en"),
        ("Dune.2021.1080p.eng.forced.srt", ".en.forced"),
        ("Subs/2_English.srt", ".en"),
        ("Subs/English (SDH).srt", ".en.sdh"),
        ("Subs/Dutch.srt", ".nl"),
        ("Subs/3.srt", ""),
    ],
)
def test_subtitle_suffix(name: str, suffix: str) -> None:
    assert subtitle_suffix(PurePosixPath(name), "Dune.2021.1080p") == suffix


def test_choose_video_skips_samples_and_picks_the_requested_episode() -> None:
    files = [
        TorrentFile("Pack/Sample/sample.mkv", 900, 1),
        TorrentFile("Pack/The.Bear.S01E01.1080p.mkv", 1000, 1),
        TorrentFile("Pack/The.Bear.S01E02.1080p.mkv", 800, 1),
        TorrentFile("Pack/info.nfo", 1, 1),
    ]
    chosen = choose_video(files, BEAR, video_extensions=VIDEO_EXTENSIONS, min_size_bytes=0)
    assert chosen is not None and chosen.name == "Pack/The.Bear.S01E02.1080p.mkv"
    movie = choose_video(files, DUNE, video_extensions=VIDEO_EXTENSIONS, min_size_bytes=0)
    assert movie is not None and movie.name == "Pack/The.Bear.S01E01.1080p.mkv"


def test_plan_brings_subtitles_along_with_unique_names(tmp_path: Path) -> None:
    files = [
        TorrentFile("Dune/Dune.mkv", 1000, 1),
        TorrentFile("Dune/Subs/2_English.srt", 1, 1),
        TorrentFile("Dune/Subs/3_English.srt", 1, 1),
        TorrentFile("Dune/Subs/4_Dutch.srt", 1, 1),
    ]
    plan = plan_import(
        files,
        save_path=tmp_path / "dl",
        root=tmp_path / "movies",
        target=DUNE,
        release_title="Dune.2021.1080p.WEB-DL.H.264-FLUX",
        video_extensions=VIDEO_EXTENSIONS,
        min_size_bytes=0,
        subtitles=True,
    )
    stem = "Dune (2021) [tmdbid-438631] - 1080p WEB-DL H.264-FLUX"
    assert plan.video.source == tmp_path / "dl/Dune/Dune.mkv"
    assert [p.destination.name for p in plan.subtitles] == [
        f"{stem}.en.srt",
        f"{stem}.2.en.srt",
        f"{stem}.nl.srt",
    ]


def test_path_mappings_use_the_longest_prefix() -> None:
    mappings = [
        PathMapping(remote="/downloads", local=Path("/srv/torrents")),
        PathMapping(remote="/downloads/tv", local=Path("/mnt/tv-dl")),
    ]
    assert to_local("/downloads/movies/x", mappings) == Path("/srv/torrents/movies/x")
    assert to_local("/downloads/tv/x", mappings) == Path("/mnt/tv-dl/x")
    assert to_local("/elsewhere/x", mappings) == Path("/elsewhere/x")


def test_place_hardlinks(tmp_path: Path) -> None:
    source = tmp_path / "dl" / "video.mkv"
    source.parent.mkdir()
    source.write_bytes(b"video")
    target = tmp_path / "lib" / "Movie" / "video.mkv"
    assert place(Placement(source, target), "copy") == "hardlink"
    assert os.path.samefile(source, target)
    assert place(Placement(source, target), "copy") == "existing"


def test_place_copies_across_filesystems(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def no_link(*_: Any) -> None:
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(importer.os, "link", no_link)
    source = tmp_path / "video.mkv"
    source.write_bytes(b"video")
    target = tmp_path / "lib" / "video.mkv"
    assert place(Placement(source, target), "copy") == "copy"
    assert target.read_bytes() == b"video" and source.exists()
    assert not any(p.name.endswith(".partial") for p in target.parent.iterdir())


# -- service -------------------------------------------------------------------------------


class FakeQbittorrent:
    """qBittorrent's WebUI API, as far as Driftwood uses it."""

    def __init__(self, save_path: str) -> None:
        self.save_path = save_path
        self.torrents: dict[str, dict[str, Any]] = {}
        self.files: dict[str, list[dict[str, Any]]] = {}
        self.api_key = "qbt_test"

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v2/")
        if request.headers.get("authorization") != f"Bearer {self.api_key}":
            return httpx.Response(401, text="Unauthorized")
        if path == "torrents/createCategory":
            return httpx.Response(200)
        if path == "torrents/add":
            body = request.content
            start = body.index(b"d8:announce")
            end = body.index(b"\r\n--", start)
            torrent_hash = infohash(body[start:end])
            self.torrents[torrent_hash] = {
                "hash": torrent_hash,
                "name": "Dune.2021.1080p.WEB-DL.H.264-FLUX",
                "state": "metaDL",
                "progress": 0,
                "size": 2_000_000_000,
                "amount_left": 2_000_000_000,
                "dlspeed": 0,
                "eta": 8640000,
                "num_seeds": 0,
                "num_complete": 40,
                "num_leechs": 0,
                "save_path": self.save_path,
            }
            return httpx.Response(200, text="Ok.")
        if path == "torrents/info":
            hashes = request.url.params["hashes"].split("|")
            rows = [self.torrents[h] for h in hashes if h in self.torrents]
            return httpx.Response(200, content=json.dumps(rows))
        if path == "torrents/files":
            return httpx.Response(200, content=json.dumps(self.files[request.url.params["hash"]]))
        if path == "torrents/delete":
            for torrent_hash in request.content.decode().split("&")[0].split("=")[1].split("%7C"):
                self.torrents.pop(torrent_hash, None)
            return httpx.Response(200)
        return httpx.Response(404)


class FakeReleases:
    def __init__(self, release: Release) -> None:
        self.release = release

    async def find(self, media_type: MediaType, media_id: int, **_: Any) -> ReleaseLookup:
        media = MediaDetails.model_construct(
            media_type=media_type, id=media_id, title="Dune", year=2021
        )
        return ReleaseLookup(media, SearchQuery(), SearchResult(releases=[self.release]))


class FakeIndexers:
    def __init__(self, torrent: bytes) -> None:
        self.torrent = torrent
        self.downloads = 0

    async def download(self, release: Release) -> bytes:
        self.downloads += 1
        return self.torrent


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    database = Database(f"sqlite+aiosqlite:///{tmp_path}/downloads.db")
    await database.migrate()
    yield database
    await database.dispose()


RELEASE = Release(
    indexer_id="torrentleech",
    guid="123",
    title="Dune.2021.1080p.WEB-DL.H.264-FLUX",
    details_url=None,
    download_url="https://tl.invalid/download/123/x.torrent",
    size=2_000_000_000,
    published=datetime(2026, 1, 1, tzinfo=UTC),
    categories=[2000],
)


def make_service(
    tmp_path: Path, database: Database, qbit: FakeQbittorrent, torrent: bytes
) -> tuple[DownloadService, FakeIndexers]:
    library_settings = LibrarySettings(
        roots=[LibraryRoot(name="movies", path=tmp_path / "movies", kind="movies")],
        min_size_mb=0,
    )
    (tmp_path / "movies").mkdir()
    qbit_settings = QbittorrentSettings(
        url="http://qbit.invalid:8080",
        api_key="qbt_test",
        path_mappings=[PathMapping(remote="/downloads", local=tmp_path / "torrents")],
    )
    client = QbittorrentClient(qbit_settings, transport=httpx.MockTransport(qbit.handler))
    indexers = FakeIndexers(torrent)
    service = DownloadService(
        DownloadsSettings(qbittorrent=qbit_settings),
        library_settings,
        database,
        releases=FakeReleases(RELEASE),  # type: ignore[arg-type]
        indexers=indexers,  # type: ignore[arg-type]
        library=LibraryService(library_settings, database),
        client=client,
    )
    return service, indexers


REQUEST = StartDownload(
    media_type=MediaType.movie, media_id=438631, indexer="torrentleech", guid="123"
)


async def test_download_then_import_into_the_library(tmp_path: Path, database: Database) -> None:
    torrent = torrent_bytes()
    torrent_hash = infohash(torrent)
    qbit = FakeQbittorrent(save_path="/downloads/driftwood")
    service, indexers = make_service(tmp_path, database, qbit, torrent)

    started = await service.start(REQUEST, user_id=None)
    assert started.state == "downloading"
    assert torrent_hash in qbit.torrents
    # A second click doesn't grab it again.
    assert (await service.start(REQUEST, user_id=None)).id == started.id
    assert indexers.downloads == 1

    await service._tick()
    status = await service.get(started.id)
    assert status is not None and status.activity == "connecting" and status.eta_seconds is None

    qbit.torrents[torrent_hash].update(
        state="downloading", progress=0.25, amount_left=1_500_000_000, dlspeed=10_000_000, eta=150
    )
    await service._tick()
    status = await service.get(started.id)
    assert status is not None
    assert (status.activity, status.progress, status.eta_seconds) == ("downloading", 0.25, 150)
    assert status.downloaded == 500_000_000
    assert await service.active_for(MediaType.movie, 438631, None, None) == status

    # Complete: the video and its subtitle are linked into the library.
    content = tmp_path / "torrents" / "driftwood" / "Dune.2021.1080p.WEB-DL.H.264-FLUX"
    content.mkdir(parents=True)
    (content / "Dune.2021.1080p.WEB-DL.H.264-FLUX.mkv").write_bytes(b"video")
    (content / "Dune.2021.1080p.WEB-DL.H.264-FLUX.en.srt").write_bytes(b"1")
    qbit.files[torrent_hash] = [
        {"name": f"{content.name}/{content.name}.mkv", "size": 5, "progress": 1},
        {"name": f"{content.name}/{content.name}.en.srt", "size": 1, "progress": 1},
    ]
    qbit.torrents[torrent_hash].update(state="stalledUP", progress=1, amount_left=0, eta=8640000)
    await service._tick()
    await next(iter(service._imports.values()))

    status = await service.get(started.id)
    assert status is not None
    assert status.state == "completed", status.error
    assert status.file_id is not None and status.progress == 1
    folder = tmp_path / "movies" / "Dune (2021) [tmdbid-438631]"
    video = folder / "Dune (2021) [tmdbid-438631] - 1080p WEB-DL H.264-FLUX.mkv"
    assert os.path.samefile(video, content / f"{content.name}.mkv")
    assert (folder / "Dune (2021) [tmdbid-438631] - 1080p WEB-DL H.264-FLUX.en.srt").exists()
    assert await service.active_for(MediaType.movie, 438631, None, None) is None


async def test_a_torrent_removed_from_qbittorrent_fails(tmp_path: Path, database: Database) -> None:
    torrent = torrent_bytes()
    qbit = FakeQbittorrent(save_path="/downloads")
    service, _ = make_service(tmp_path, database, qbit, torrent)
    started = await service.start(REQUEST, user_id=None)
    qbit.torrents.clear()
    await service._tick()
    status = await service.get(started.id)
    assert status is not None and status.state == "failed"
    assert status.error == "The torrent was removed from qBittorrent"


async def test_cancel_deletes_the_torrent(tmp_path: Path, database: Database) -> None:
    torrent = torrent_bytes()
    qbit = FakeQbittorrent(save_path="/downloads")
    service, _ = make_service(tmp_path, database, qbit, torrent)
    started = await service.start(REQUEST, user_id=None)
    cancelled = await service.cancel(started.id)
    assert cancelled is not None and cancelled.state == "cancelled"
    assert qbit.torrents == {}


async def test_a_release_missing_from_the_results_is_a_conflict(
    tmp_path: Path, database: Database
) -> None:
    qbit = FakeQbittorrent(save_path="/downloads")
    service, _ = make_service(tmp_path, database, qbit, torrent_bytes())
    with pytest.raises(DownloadError) as caught:
        await service.start(REQUEST.model_copy(update={"guid": "999"}), user_id=None)
    assert caught.value.status_code == 409


async def test_a_wrong_api_key_is_reported() -> None:
    qbit = FakeQbittorrent(save_path="/downloads")
    settings = QbittorrentSettings(url="http://qbit.invalid", api_key="qbt_wrong")
    client = QbittorrentClient(settings, transport=httpx.MockTransport(qbit.handler))
    with pytest.raises(QbittorrentError, match="rejected the API key"):
        await client.info("0" * 40)
    await client.aclose()


async def test_cancelling_is_refused_near_the_hit_and_run_threshold(
    tmp_path: Path, database: Database
) -> None:
    torrent = torrent_bytes()
    torrent_hash = infohash(torrent)
    qbit = FakeQbittorrent(save_path="/downloads")
    service, _ = make_service(tmp_path, database, qbit, torrent)
    started = await service.start(REQUEST, user_id=None)

    # 5% done, but 8% transferred (discarded pieces count for the tracker too).
    qbit.torrents[torrent_hash].update(
        state="downloading", amount_left=1_900_000_000, downloaded=160_000_000
    )
    await service._tick()
    status = await service.get(started.id)
    assert status is not None and status.can_cancel is False

    with pytest.raises(DownloadError) as caught:
        await service.cancel(started.id)
    assert caught.value.status_code == 409
    assert torrent_hash in qbit.torrents
    status = await service.get(started.id)
    assert status is not None and status.state == "downloading"


async def test_cancelling_checks_fresh_numbers(tmp_path: Path, database: Database) -> None:
    torrent = torrent_bytes()
    torrent_hash = infohash(torrent)
    qbit = FakeQbittorrent(save_path="/downloads")
    service, _ = make_service(tmp_path, database, qbit, torrent)
    started = await service.start(REQUEST, user_id=None)
    await service._tick()  # 0%: cancellable as far as the last tick knows
    qbit.torrents[torrent_hash].update(state="downloading", amount_left=1_000_000_000)
    with pytest.raises(DownloadError):
        await service.cancel(started.id)
    assert torrent_hash in qbit.torrents
