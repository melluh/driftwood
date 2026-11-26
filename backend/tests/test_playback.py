import asyncio
import contextlib
import json
import shutil
import subprocess
import sys
import time
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from driftwood.config import LibraryRoot, LibrarySettings, PlaybackSettings
from driftwood.db import Database
from driftwood.library.service import LibraryService
from driftwood.playback.mkv import read_keyframes
from driftwood.playback.policy import (
    ClientCapabilities,
    audio_output,
    can_play_directly,
    video_problem,
)
from driftwood.playback.probe import MediaProbe, find_keyframes, probe_file
from driftwood.playback.router import router as playback_router
from driftwood.playback.segments import SegmentJob, SegmentPlan, SegmentSource
from driftwood.playback.service import PlaybackService
from driftwood.playback.subtitles import embedded_command, embedded_tracks
from driftwood.playback.trickplay import MARKER, find_trickplay, jpeg_size
from driftwood.playback.trickplay_generator import (
    Layout,
    Priority,
    TrickplayGenerator,
    TrickplayJob,
    sheet_filter,
    thumbnail_size,
)
from tests.test_auth import PUBLIC_URL, FakeIdp, make_app, sign_in

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg and ffprobe are needed",
)
KEYFRAMES = [0, 2.5, 7, 8, 15.3, 20, 26.1, 33, 34, 40]
# mpegts adds its default 1.4 s mux delay to every timestamp.
MPEGTS_OFFSET = 1.4


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def _first_keyframe(path: Path) -> float:
    output = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "packet=pts_time,flags",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return min(float(line.split(",")[0]) for line in output.splitlines() if "K" in line)


@pytest.fixture(scope="module")
def media(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is needed")
    directory = tmp_path_factory.mktemp("media")
    srt = directory / "en.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:03,000\nHello there\n\n", encoding="utf-8")
    ass = directory / "signs.ass"
    ass.write_text(
        "[Script Info]\nScriptType: v4.00+\n\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize\nStyle: Default,Sign Font,20\n\n[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:02.00,0:00:04.00,Default,,0,0,0,,{\\an8}A sign\n",
        encoding="utf-8",
    )
    font = directory / "sign.ttf"
    font.write_bytes(b"not really a font")
    force = ",".join(str(time) for time in KEYFRAMES)
    video = [
        "-f",
        "lavfi",
        "-i",
        "testsrc2=d=45:s=320x180:r=24",
        "-f",
        "lavfi",
        "-i",
        "sine=d=45,aformat=channel_layouts=5.1",
    ]
    x264 = ["-c:v", "libx264", "-bf", "3", "-g", "1000", "-sc_threshold", "0"]
    mkv = directory / "Movie [tmdbid-1]" / "Movie.1080p.mkv"
    mkv.parent.mkdir()
    _ffmpeg(
        *video,
        "-i",
        str(srt),
        "-i",
        str(ass),
        *x264,
        "-force_key_frames",
        force,
        "-map",
        "0",
        "-map",
        "1",
        "-map",
        "1",
        "-map",
        "2",
        "-map",
        "3",
        "-c:a:0",
        "ac3",
        "-c:a:1",
        "aac",
        "-c:s:0",
        "srt",
        "-c:s:1",
        "ass",
        "-metadata:s:a:0",
        "language=eng",
        "-metadata:s:a:1",
        "language=jpn",
        "-metadata:s:s:0",
        "language=eng",
        "-attach",
        str(font),
        "-metadata:s:t",
        "mimetype=application/x-truetype-font",
        str(mkv),
    )
    # Sidecars: named after the video, in the encodings and naming styles found in the wild.
    sidecar = mkv.with_name("Movie.1080p.nl.forced.srt")
    sidecar.write_bytes("1\n00:00:05,000 --> 00:00:07,000\nÉén bord\n\n".encode("cp1252"))
    mkv.with_name("Movie.1080p.English.SDH.srt").write_text(
        "\ufeff1\n00:00:08,000 --> 00:00:09,000\n[DOOR CREAKS]\n\n", encoding="utf-8"
    )
    mkv.with_name("Movie.1080p.ger.sup").write_bytes(b"PG fake picture subtitles")
    mkv.with_name("Movie.1080p.broken.srt").write_bytes(b"\x00\x01 not a subtitle file")
    mkv.with_name("Unrelated.eng.srt").write_text("not for this video", encoding="utf-8")
    # Jellyfin trickplay: 45 s at one thumbnail per 10 s is 5 thumbnails, two 2x2 sheets.
    sheets = mkv.with_name("Movie.1080p.trickplay") / "32 - 2x2"
    sheets.mkdir(parents=True)
    for index in range(2):
        _ffmpeg("-f", "lavfi", "-i", "color=c=gray:s=64x36", "-frames:v", "1",
                str(sheets / f"{index}.jpg"))  # fmt: skip
    mp4 = directory / "Direct [tmdbid-2]" / "Direct.mp4"
    mp4.parent.mkdir()
    _ffmpeg(*video, *x264, "-c:a", "aac", "-ac", "2", "-movflags", "+faststart", str(mp4))
    hevc = directory / "Hevc [tmdbid-3]" / "Hevc.2160p.mkv"
    hevc.parent.mkdir()
    _ffmpeg(
        "-f", "lavfi", "-i", "testsrc2=d=4:s=320x180:r=24", "-c:v", "libx265",
        "-x265-params", "log-level=error", str(hevc),
    )  # fmt: skip
    return {"mkv": mkv, "mp4": mp4, "hevc": hevc, "root": directory}


def test_plan_starts_segments_on_keyframes_at_least_the_target_apart() -> None:
    plan = SegmentPlan.build([0, 2, 4, 6.5, 7, 13, 19.5, 20], origin=0, duration=21, target=6)

    assert plan.starts == [0, 6.5, 13]  # 19.5 would leave a 1.5 s sliver
    assert plan.cuts[1:] == [(4 + 6.5) / 2, (7 + 13) / 2]
    assert plan.seeks == [0.25, 6.75, 13.25]
    assert plan.durations() == [6.5, 6.5, 8]
    assert sum(plan.durations()) == 21


def test_embedded_picture_subtitles_are_copied_out_as_sup() -> None:
    streams = [
        {"index": 2, "codec_name": "hdmv_pgs_subtitle", "tags": {"language": "eng"}},
        {"index": 3, "codec_name": "dvd_subtitle"},
        {"index": 4, "codec_name": "subrip", "disposition": {"forced": 1}},
    ]
    tracks = embedded_tracks(streams)

    assert [(t.format, t.stream_index, t.forced) for t in tracks] == [
        ("pgs", 2, False),
        ("webvtt", 4, True),
    ]
    command = embedded_command(tracks, Path("/out"))
    assert command[:6] == ["-map", "0:2", "-c:s", "copy", "/out/0.sup", "-map"]


def test_playlist_is_a_complete_vod_playlist() -> None:
    text = SegmentPlan.build([0, 6, 12], origin=0, duration=15, target=6).playlist()

    assert "#EXT-X-PLAYLIST-TYPE:VOD" in text
    assert text.rstrip().endswith("#EXT-X-ENDLIST")
    assert "#EXT-X-TARGETDURATION:6" in text
    assert [line for line in text.splitlines() if line.endswith(".ts")] == ["0.ts", "1.ts", "2.ts"]


@pytest.mark.parametrize(
    ("stream", "capabilities", "playable"),
    [
        ({"codec_name": "h264", "pix_fmt": "yuv420p"}, ClientCapabilities(), True),
        ({"codec_name": "h264", "pix_fmt": "yuv420p10le"}, ClientCapabilities(hevc=True), False),
        ({"codec_name": "hevc", "pix_fmt": "yuv420p"}, ClientCapabilities(), False),
        ({"codec_name": "hevc", "pix_fmt": "yuv420p10le"}, ClientCapabilities(hevc=True), False),
        (
            {"codec_name": "hevc", "pix_fmt": "yuv420p10le"},
            ClientCapabilities(hevc=True, hevc_main10=True),
            True,
        ),
        (
            {
                "codec_name": "hevc",
                "pix_fmt": "yuv420p10le",
                "side_data_list": [
                    {"side_data_type": "DOVI configuration record", "dv_profile": 5}
                ],
            },
            ClientCapabilities(hevc=True, hevc_main10=True),
            False,
        ),
        ({"codec_name": "av1", "pix_fmt": "yuv420p"}, ClientCapabilities(), False),
    ],
)
def test_video_problem(stream, capabilities, playable) -> None:
    assert (video_problem(stream, capabilities) is None) is playable


@needs_ffmpeg
async def test_matroska_cues_give_the_same_keyframes_as_a_packet_scan(media) -> None:
    probe = await probe_file("ffprobe", media["mkv"])
    from_cues = read_keyframes(media["mkv"])
    probe.format_name = "mov"  # forces the packet scan
    scanned = await find_keyframes("ffprobe", media["mkv"], probe)

    assert from_cues == pytest.approx(scanned, abs=0.002)
    assert from_cues == pytest.approx(KEYFRAMES, abs=0.05)


@needs_ffmpeg
async def test_direct_play_only_for_browser_ready_mp4(media) -> None:
    assert can_play_directly(await probe_file("ffprobe", media["mp4"]), ".mp4")
    assert not can_play_directly(await probe_file("ffprobe", media["mkv"]), ".mkv")


async def _job(
    media: dict[str, Path], tmp_path: Path, *, lead: int
) -> tuple[SegmentJob, MediaProbe]:
    probe = await probe_file("ffprobe", media["mkv"])
    keyframes = await find_keyframes("ffprobe", media["mkv"], probe)
    plan = SegmentPlan.build(keyframes, probe.start_time, probe.duration, 6)
    audio = probe.of_type("audio")[0]
    video = probe.video
    assert video is not None
    source = SegmentSource(
        "ffmpeg", media["mkv"], video["index"], audio["index"], audio_output(audio)
    )
    return SegmentJob(source, plan, tmp_path / "job", lead=lead, keep_behind=1), probe


@needs_ffmpeg
async def test_segments_start_on_planned_keyframes_wherever_ffmpeg_starts(media, tmp_path) -> None:
    job, _probe = await _job(media, tmp_path, lead=20)
    try:
        # From the start, a seek forward, and back: three ffmpeg runs.
        for index in [0, 1, 4, 2, 3]:
            path = await job.segment(index)
            assert _first_keyframe(path) - MPEGTS_OFFSET == pytest.approx(
                job.plan.starts[index], abs=0.002
            )
    finally:
        await job.close()
    assert not job.directory.exists()


@needs_ffmpeg
async def test_ffmpeg_pauses_when_far_ahead_and_resumes_on_demand(media, tmp_path) -> None:
    job, _probe = await _job(media, tmp_path, lead=2)
    try:
        await job.segment(0)
        for _ in range(100):
            if job._paused:
                break
            await asyncio.sleep(0.05)
        assert job._paused
        assert job._next == 2
        await job.segment(1)
        assert (await job.segment(len(job.plan) - 1)).exists()
        # Done with the last segment: not left paused, but allowed to exit.
        for _ in range(100):
            if job._process is None:
                break
            await asyncio.sleep(0.05)
        assert job._process is None
        assert not job._paused
        # Far behind the player: deleted, and made again when asked for.
        assert not job.path(0).exists()
        assert (await job.segment(0)).exists()
    finally:
        await job.close()


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    database = Database(f"sqlite+aiosqlite:///{tmp_path}/playback.db")
    await database.migrate()
    yield database
    await database.dispose()


@contextlib.asynccontextmanager
async def _client(
    database: Database, root: Path, settings: PlaybackSettings
) -> AsyncIterator[httpx.AsyncClient]:
    library = LibrarySettings(
        roots=[LibraryRoot(name="movies", path=root, kind="movies")], min_size_mb=0
    )
    library_service = LibraryService(library, database)
    await library_service.scanner.scan_all()
    playback = PlaybackService(settings, library)
    await playback.start()
    idp = FakeIdp()
    app = make_app(database, idp)
    app.include_router(playback_router, prefix="/api")
    app.state.playback_service = playback
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url=PUBLIC_URL) as client:
            await sign_in(client, idp)
            yield client
    finally:
        await playback.shutdown()


@pytest.fixture
async def client(database: Database, media, tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    # The media is shared by the module's tests: nothing may add thumbnails to it.
    settings = PlaybackSettings(directory=tmp_path / "playback", trickplay_generate=False)
    async with _client(database, media["root"], settings) as client:
        yield client


@needs_ffmpeg
async def test_mkv_plays_as_hls_with_every_audio_and_subtitle_track(client) -> None:
    response = await client.post("/api/playback", json={"media_type": "movie", "media_id": 1})
    assert response.status_code == 200, response.text
    offer = response.json()
    session = offer["session"]
    assert session["mode"] == "hls"
    assert [track["language"] for track in session["audio"]] == ["eng", "jpn"]
    assert session["url"] == session["audio"][0]["url"]
    assert session["duration"] == pytest.approx(45, abs=0.1)
    assert offer["versions"][0]["playable"]

    playlist = await client.get(session["audio"][1]["url"])
    assert playlist.headers["content-type"] == "application/vnd.apple.mpegurl"
    assert "#EXT-X-ENDLIST" in playlist.text
    base = session["audio"][1]["url"].rsplit("/", 1)[0]
    segment = await client.get(f"{base}/3.ts")
    assert segment.status_code == 200
    assert segment.headers["content-type"] == "video/mp2t"

    srt, ass, broken, sdh, picture, dutch = session["subtitles"]
    assert (srt["language"], srt["format"], srt["external"]) == ("eng", "webvtt", False)
    assert srt["text_url"] is None
    assert "Hello there" in (await client.get(srt["url"])).text
    assert ass["format"] == "ass"
    assert "A sign" in (await client.get(ass["url"])).text
    assert "A sign" in (await client.get(ass["text_url"])).text
    assert len(session["fonts"]) == 1
    assert (await client.get(session["fonts"][0])).content == b"not really a font"

    # Sidecar files, sorted by name after the embedded tracks.
    assert all(track["external"] for track in (broken, sdh, picture, dutch))
    assert (sdh["language"], sdh["hearing_impaired"], sdh["format"]) == ("eng", True, "webvtt")
    assert "[DOOR CREAKS]" in (await client.get(sdh["url"])).text
    assert (dutch["language"], dutch["forced"]) == ("nl", True)
    assert "Één bord" in (await client.get(dutch["url"])).text  # was Windows-1252
    assert (picture["language"], picture["format"]) == ("ger", "pgs")
    assert picture["url"].endswith(".sup")
    assert (await client.get(picture["url"])).content == b"PG fake picture subtitles"
    # A broken file loses only its own track.
    assert (await client.get(broken["url"])).status_code == 502

    trickplay = session["trickplay"]
    assert {key: trickplay[key] for key in ("columns", "rows", "width", "height", "count")} == {
        "columns": 2, "rows": 2, "width": 32, "height": 18, "count": 5,
    }  # fmt: skip
    assert len(trickplay["sheets"]) == 2
    sheet = await client.get(trickplay["sheets"][1])
    assert sheet.headers["content-type"] == "image/jpeg"
    assert sheet.content.startswith(b"\xff\xd8")
    missing = trickplay["sheets"][1].replace("/1.jpg", "/2.jpg")
    assert (await client.get(missing)).status_code == 404

    assert (await client.delete(f"/api/playback/{session['id']}")).status_code == 204
    assert (await client.get(session["url"])).status_code == 404


@needs_ffmpeg
async def test_browser_ready_mp4_is_served_with_byte_ranges(client) -> None:
    offer = (await client.post("/api/playback", json={"media_type": "movie", "media_id": 2})).json()
    session = offer["session"]
    assert session["mode"] == "direct"
    assert session["trickplay"] is None

    response = await client.get(session["url"], headers={"Range": "bytes=0-99"})
    assert response.status_code == 206
    assert len(response.content) == 100


@needs_ffmpeg
async def test_unplayable_title_explains_why_instead_of_opening_a_session(client) -> None:
    request = {"media_type": "movie", "media_id": 3}
    offer = (await client.post("/api/playback", json=request)).json()
    assert offer["session"] is None
    assert "HEVC" in offer["problem"]
    assert offer["versions"][0]["playable"] is False

    request["capabilities"] = {"hevc": True, "hevc_main10": True}
    offer = (await client.post("/api/playback", json=request)).json()
    assert offer["session"]["mode"] == "hls"


@needs_ffmpeg
async def test_titles_outside_the_library_are_not_found(client) -> None:
    response = await client.post("/api/playback", json={"media_type": "movie", "media_id": 99})
    assert response.status_code == 404


@needs_ffmpeg
def test_trickplay_needs_sheets_that_fit_the_interval(tmp_path: Path) -> None:
    video = tmp_path / "Film.mkv"
    sheets = tmp_path / "Film.trickplay" / "320 - 10x10"
    sheets.mkdir(parents=True)
    for index in range(6):
        _ffmpeg("-f", "lavfi", "-i", "color=s=3200x1720", "-frames:v", "1",
                str(sheets / f"{index}.jpg"))  # fmt: skip
    assert jpeg_size(sheets / "0.jpg") == (3200, 1720)

    trickplay = find_trickplay(video, 5817.7, 10)  # 582 thumbnails
    assert trickplay is not None
    assert (trickplay.width, trickplay.height, trickplay.count) == (320, 172, 582)
    assert trickplay.sheet(5) == sheets / "5.jpg"
    assert trickplay.sheet(6) is None
    # Saved every 10 s, but assumed every 5 s: the previews would show the wrong moments.
    assert find_trickplay(video, 5817.7, 5) is None
    assert find_trickplay(tmp_path / "Other.mkv", 5817.7, 10) is None


@pytest.mark.skipif(sys.platform != "linux", reason="parent death signals are Linux-only")
def test_paused_ffmpeg_dies_with_a_crashed_server(tmp_path: Path) -> None:
    script = tmp_path / "crash.py"
    script.write_text(
        "import asyncio, os, signal\n"
        "from driftwood.playback.process import CHILD_OPTIONS\n"
        "async def main():\n"
        "    child = await asyncio.create_subprocess_exec('sleep', '60', **CHILD_OPTIONS)\n"
        "    os.kill(child.pid, signal.SIGSTOP)\n"
        "    print(child.pid, flush=True)\n"
        "    os.kill(os.getpid(), signal.SIGKILL)\n"
        "asyncio.run(main())\n"
    )
    result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    pid = int(result.stdout)
    for _ in range(50):
        if not Path(f"/proc/{pid}").exists():
            break
        time.sleep(0.05)
    assert not Path(f"/proc/{pid}").exists()


def test_thumbnails_keep_the_display_aspect_ratio() -> None:
    assert thumbnail_size({"width": 1920, "height": 800}, 320) == (320, 134)
    # Anamorphic PAL DVD: 720x576 frames shown at 16:9.
    anamorphic = {"width": 720, "height": 576, "sample_aspect_ratio": "64:45"}
    assert thumbnail_size(anamorphic, 320) == (320, 180)
    assert thumbnail_size({**anamorphic, "sample_aspect_ratio": "0:1"}, 320) == (320, 256)
    # A phone video stored sideways, shown upright.
    rotated = {"width": 1920, "height": 1080, "side_data_list": [{"rotation": -90}]}
    assert thumbnail_size(rotated, 320) == (320, 568)


def test_sheets_from_the_viewers_position_onwards_go_first() -> None:
    layout = Layout(width=320, height=180, columns=10, rows=10, interval=10, count=943)
    job = TrickplayJob(
        video=Path("film.mkv"),
        directory=Path("film.trickplay"),
        layout=layout,
        video_index=0,
        transfer=None,
        stamp={},
        priority=Priority.imported,
        pending=set(range(layout.sheets)),
    )
    job.focus_on(4321)  # in sheet 4, which covers 4000-5000 s
    order = []
    while (index := job.next_sheet()) is not None:
        job.pending.discard(index)
        order.append(index)
    assert order == [4, 5, 6, 7, 8, 9, 3, 2, 1, 0]
    job.focus_on(1e9)
    assert job.focus == 9


async def _generate(generator: TrickplayGenerator, video: Path) -> TrickplayJob:
    probe = await probe_file("ffprobe", video)
    job = await generator.submit(video, probe, Priority.imported)
    assert job is not None
    await asyncio.wait_for(job.done.wait(), 60)
    assert job.error is None
    return job


@needs_ffmpeg
async def test_sheets_made_side_by_side_match_one_pass_over_the_file(media, tmp_path) -> None:
    video = tmp_path / "Movie.mkv"
    shutil.copyfile(media["mkv"], video)
    settings = PlaybackSettings(trickplay_interval_seconds=2, trickplay_width=64)
    generator = TrickplayGenerator(settings, columns=2, rows=2)
    try:
        job = await _generate(generator, video)
    finally:
        await generator.shutdown()

    # 45 s, a thumbnail every 2 s: 23 of them on six 2x2 sheets.
    trickplay = find_trickplay(video, 45, 2)
    assert trickplay is not None
    assert trickplay.directory == tmp_path / "Movie.trickplay" / "64 - 2x2"
    assert (trickplay.sheets, trickplay.count, trickplay.width, trickplay.height) == (6, 23, 64, 36)
    assert sorted(path.name for path in trickplay.directory.iterdir()) == [
        f"{index}.jpg" for index in range(6)
    ]
    reference = tmp_path / "reference"
    reference.mkdir()
    _ffmpeg("-skip_frame", "nokey", "-i", str(video), "-map", "0:v:0",
            "-vf", sheet_filter(job.layout), "-c:v", "mjpeg", "-q:v", "4",
            "-start_number", "0", str(reference / "%d.jpg"))  # fmt: skip
    for index in range(6):
        made = (trickplay.directory / f"{index}.jpg").read_bytes()
        assert made == (reference / f"{index}.jpg").read_bytes(), f"sheet {index}"


@needs_ffmpeg
async def test_an_interrupted_run_carries_on_and_other_sheets_are_left_alone(
    media, tmp_path
) -> None:
    video = tmp_path / "Movie.mkv"
    shutil.copyfile(media["mkv"], video)
    settings = PlaybackSettings(trickplay_interval_seconds=2, trickplay_width=64)
    generator = TrickplayGenerator(settings, columns=2, rows=2)
    try:
        job = await _generate(generator, video)
        directory = job.directory
        # Cut short after two sheets: the marker's still there, the rest isn't.
        (directory / MARKER).write_text(json.dumps(job.stamp), encoding="utf-8")
        for index in range(2, 6):
            (directory / f"{index}.jpg").unlink()
        (directory / ".3.jpg.tmp").write_bytes(b"half a sheet")
        kept = (directory / "1.jpg").stat().st_ino
        assert find_trickplay(video, 45, 2) is None  # unfinished: not taken for a whole set

        generator = TrickplayGenerator(settings, columns=2, rows=2)
        probe = await probe_file("ffprobe", video)
        job = await generator.submit(video, probe, Priority.imported)
        assert job is not None
        assert job.ready == {0, 1}
        await asyncio.wait_for(job.done.wait(), 60)
        assert (directory / "1.jpg").stat().st_ino == kept
        assert find_trickplay(video, 45, 2) is not None
        assert not (directory / ".3.jpg.tmp").exists()

        # Sheets that don't fit and aren't Driftwood's (Jellyfin's, at another interval).
        (directory / "5.jpg").unlink()
        generator = TrickplayGenerator(settings, columns=2, rows=2)
        assert await generator.submit(video, probe, Priority.imported) is None
        assert not (directory / "5.jpg").exists()
    finally:
        await generator.shutdown()


@needs_ffmpeg
async def test_thumbnails_are_made_while_a_video_without_them_plays(
    database: Database, media, tmp_path: Path
) -> None:
    root = tmp_path / "library"
    shutil.copytree(media["mp4"].parent, root / media["mp4"].parent.name)
    settings = PlaybackSettings(
        directory=tmp_path / "playback", trickplay_interval_seconds=1, trickplay_workers=2
    )
    request = {"media_type": "movie", "media_id": 2}
    async with _client(database, root, settings) as client:
        session = (await client.post("/api/playback", json=request)).json()["session"]
        trickplay = session["trickplay"]
        # 45 thumbnails, one a second: a sheet of 100 holds them all.
        assert trickplay["generating"] is True
        assert (trickplay["count"], trickplay["ready"]) == (45, [False])

        status = f"/api/playback/{session['id']}/trickplay"
        for _ in range(600):
            trickplay = (await client.get(status, params={"position": 30})).json()
            if not trickplay["generating"]:
                break
            await asyncio.sleep(0.05)
        assert trickplay["generating"] is False
        assert trickplay["ready"] == [True]
        assert (trickplay["width"], trickplay["height"]) == (320, 180)
        sheet = await client.get(trickplay["sheets"][0])
        assert sheet.status_code == 200
        (tmp_path / "sheet.jpg").write_bytes(sheet.content)
        assert jpeg_size(tmp_path / "sheet.jpg") == (3200, 1800)

        # The next session finds them on disk.
        session = (await client.post("/api/playback", json=request)).json()["session"]
        assert session["trickplay"]["generating"] is False


@needs_ffmpeg
async def test_a_download_and_a_viewer_asking_at_once_share_one_job(media, tmp_path) -> None:
    video = tmp_path / "Movie.mkv"
    shutil.copyfile(media["mkv"], video)
    settings = PlaybackSettings(trickplay_interval_seconds=2, trickplay_width=64)
    generator = TrickplayGenerator(settings, columns=2, rows=2)
    try:
        probe = await probe_file("ffprobe", video)
        imported, watching = await asyncio.gather(
            generator.submit(video, probe, Priority.imported),
            generator.submit(video, probe, Priority.watching),
        )
        assert imported is watching is not None
        assert imported.priority is Priority.watching
        await asyncio.wait_for(imported.done.wait(), 60)
        assert imported.error is None
        assert find_trickplay(video, 45, 2) is not None
    finally:
        await generator.shutdown()
