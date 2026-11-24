from driftwood.indexers.models import Release
from driftwood.selection.classification import classify_release
from driftwood.selection.config import HdrLadder, ReleaseGroupTier, SelectionSettings
from driftwood.selection.nfo import NfoInfo, SubtitleTrack
from driftwood.selection.scoring import (
    Candidate,
    EpisodeTarget,
    Rejection,
    Selection,
    SubtitleStatus,
    score_releases,
)

GB = 1024**3
RUNTIME = 120  # minutes: 1 GB ≈ 1.19 Mbps


def release(title: str, size_gb: float, seeders: int = 50, *, freeleech: bool = False) -> Release:
    return Release(
        indexer_id="test",
        guid=title,
        title=title,
        details_url=None,
        download_url="",
        size=round(size_gb * GB),
        published=None,
        categories=[],
        seeders=seeders,
        download_factor=0.0 if freeleech else 1.0,
    )


def test_classification() -> None:
    attrs = classify_release("Dune.Part.Two.2024.2160p.WEB-DL.DDP5.1.Atmos.DV.HDR10.H.265-FLUX")
    assert (attrs.resolution, attrs.source, attrs.codec) == ("2160p", "web-dl", "h265")
    assert attrs.hdr_flags == ("dv", "hdr10")
    assert attrs.audio_codecs == ("ddp", "atmos")
    assert attrs.release_group == "FLUX"

    assert classify_release("Movie.2023.1080p.WEBRip.x265-GRP").source == "webrip"
    assert classify_release("Movie.2023.1080p.BluRay.REMUX.AVC-GRP").source == "remux"
    assert classify_release("Movie.2023.1080p.BluRay.x264-GRP").source == "bluray-encode"
    assert classify_release("Movie.2023.HDCAM.x264-GRP").source == "low-quality"
    assert classify_release("Movie.2023.1080p.AV1.WEB-DL-GRP").codec == "av1"
    assert classify_release("Movie.2023.MULTi.1080p.WEB.H264-GRP").language_variant == "multi"

    episode = classify_release("The.Office.US.S02E03.1080p.WEB.h264-GRP")
    assert (episode.season, episode.episodes) == (2, (3,))


def test_watch_picks_a_modest_1080p_encode_over_bigger_ones() -> None:
    releases = [
        release("Movie.2023.2160p.BluRay.REMUX.HEVC.DTS-HD.MA-GRP", 70),  # ~84 Mbps
        release("Movie.2023.2160p.WEB-DL.DDP5.1.HDR10.H.265-GRP", 14),  # ~16.7 Mbps
        release("Movie.2023.1080p.WEB-DL.DDP5.1.H.264-BIG", 11),  # ~13 Mbps
        release("Movie.2023.1080p.WEB-DL.DDP5.1.H.264-SMALL", 5),  # ~6 Mbps
        release("Movie.2023.720p.WEB-DL.H.264-GRP", 2.5),
    ]
    selection = score_releases(releases, SelectionSettings(), runtime_minutes=RUNTIME)
    pick = selection.watch_pick(SelectionSettings().watch_slots)
    assert pick is not None
    assert pick.release.title.endswith("-SMALL")
    assert pick.slot is not None and pick.slot.name == "1080p_encode"

    winners = [(c.slot.name if c.slot else None) for c in selection.slot_winners]
    assert winners == ["4k_remux", "4k_encode", "1080p_encode", "720p"]


# The Breakfast Club scenarios: 97 minutes, speed-scored 1080p Encode slot.
BREAKFAST = 97
NO_SUBS = SelectionSettings(subtitle_languages=[])


def breakfast(*releases: Release) -> list[Candidate]:
    return score_releases(list(releases), NO_SUBS, runtime_minutes=BREAKFAST).candidates


def test_size_near_target_beats_a_bigger_web_dl() -> None:
    ranked = breakfast(
        release("Movie.1985.1080p.WEB-DL.DD5.1.H.264-BIG", 8.5, 40),
        release("Movie.1985.1080p.BluRay.x264-SMALL", 4.2, 40),
    )
    assert ranked[0].release.title.endswith("-SMALL")
    assert ("bitrate_fit", 391) in ranked[0].factors
    assert ("source:bluray-encode", 300) in ranked[0].factors


def test_hevc_bitrate_counts_as_h264_equivalent() -> None:
    ranked = breakfast(
        release("Movie.1985.1080p.WEB-DL.DD5.1.H.264-BIG", 8.5, 40),
        release("Movie.1985.1080p.WEBRip.x265-TINY", 2.4, 40),
    )
    tiny = next(c for c in ranked if c.release.title.endswith("-TINY"))
    assert round(tiny.effective_mbps or 0, 1) == 3.5
    assert round(tiny.compared_mbps or 0, 1) == 5.0  # x1.4: above the 4 Mbps floor
    assert ranked[0] is tiny


def test_a_healthy_swarm_beats_a_better_source() -> None:
    ranked = breakfast(
        release("Movie.1985.1080p.BluRay.x264-FEW", 4.2, 5),
        release("Movie.1985.1080p.WEBRip.x264-MANY", 4.2, 500),
    )
    assert ranked[0].release.title.endswith("-MANY")
    assert ("seeders", 200) in ranked[0].factors


def test_below_the_target_loses_points_and_below_the_floor_is_rejected() -> None:
    selection = score_releases(
        [
            release("Movie.1985.1080p.WEB-DL.H.264-TARGET", 4.2),
            release("Movie.1985.1080p.WEB-DL.H.264-LEAN", 3.0),  # 4.4 Mbps
            release("Movie.1985.1080p.WEB-DL.H.264-STARVED", 2.6),  # 3.8 Mbps
        ],
        NO_SUBS,
        runtime_minutes=BREAKFAST,
    )
    by_title = {c.release.title.split("-")[-1]: c for c in selection.candidates}
    assert set(by_title) == {"TARGET", "LEAN"}
    assert by_title["TARGET"].score > by_title["LEAN"].score
    assert selection.rejected[Rejection.BITRATE] == 1


def test_upgrade_slots_keep_quality_weights() -> None:
    ranked = breakfast(release("Movie.1985.2160p.WEB-DL.H.265-UHD", 12))
    assert ranked[0].slot is not None and ranked[0].slot.name == "4k_encode"
    assert ("source:web-dl", 1000) in ranked[0].factors
    assert ("seeders", 56) in ranked[0].factors


def test_freeleech_wins_up_to_about_double_the_target_size() -> None:
    near = release("Movie.1985.1080p.WEB-DL.H.264-NEAR", 4.2)  # ~6 Mbps
    free_9 = release("Movie.1985.1080p.WEB-DL.H.264-FREE", 6.3, freeleech=True)  # ~9 Mbps
    free_14 = release("Movie.1985.1080p.WEB-DL.H.264-FREE", 9.8, freeleech=True)  # ~14 Mbps
    assert breakfast(near, free_9)[0].release is free_9
    assert breakfast(near, free_14)[0].release is near


def test_falls_back_to_720p_then_4k() -> None:
    settings = SelectionSettings()
    only_720 = score_releases(
        [release("Movie.2023.720p.WEB-DL.H.264-GRP", 2.5)], settings, runtime_minutes=RUNTIME
    )
    assert only_720.watch_pick(settings.watch_slots).slot.name == "720p"  # type: ignore[union-attr]

    only_4k = score_releases(
        [release("Movie.2023.2160p.WEB-DL.H.265-GRP", 14)], settings, runtime_minutes=RUNTIME
    )
    assert only_4k.watch_pick(settings.watch_slots).slot.name == "4k_encode"  # type: ignore[union-attr]


def test_hard_rejections() -> None:
    releases = [
        release("Movie.2023.HDCAM.x264-GRP", 1.5),
        release("Movie.2023.MULTi.1080p.WEB.H264-GRP", 5),
        release("Movie.2023.1080p.WEB-DL.H.264-DEAD", 5, seeders=1),
        release("Movie.2023.1080p.WEB-DL.H.264-FAKE", 0.5),  # 0.6 Mbps: mislabeled
    ]
    selection = score_releases(releases, SelectionSettings(), runtime_minutes=RUNTIME)
    assert selection.candidates == []
    assert selection.rejected == {
        Rejection.LOW_QUALITY_SOURCE: 1,
        Rejection.LANGUAGE_VARIANT: 1,
        Rejection.LOW_SEEDERS: 1,
        Rejection.BITRATE: 1,
    }
    assert selection.watch_pick(SelectionSettings().watch_slots) is None


def test_unknown_runtime_skips_bitrate_check() -> None:
    selection = score_releases(
        [release("Movie.2023.1080p.WEB-DL.H.264-GRP", 0.5)],
        SelectionSettings(),
        runtime_minutes=None,
    )
    assert len(selection.candidates) == 1
    assert selection.candidates[0].effective_mbps is None


def test_episode_target_filters_other_episodes_and_packs() -> None:
    releases = [
        release("Show.S01E01.1080p.WEB.h264-GRP", 1.2),
        release("Show.S01E02.1080p.WEB.h264-GRP", 1.2),
        release("Show.S01.1080p.WEB.h264-GRP", 12),
    ]
    selection = score_releases(
        releases, SelectionSettings(), runtime_minutes=30, episode=EpisodeTarget(1, 1)
    )
    assert [c.release.title for c in selection.candidates] == ["Show.S01E01.1080p.WEB.h264-GRP"]
    assert selection.rejected[Rejection.WRONG_EPISODE] == 2
    assert round(selection.candidates[0].effective_mbps or 0, 1) == 5.7


def test_release_group_tier() -> None:
    settings = SelectionSettings(release_group_tiers=[ReleaseGroupTier(tier=1, groups=["GOOD"])])
    releases = [
        release("Movie.2023.1080p.WEB-DL.H.264-OTHER", 5),
        release("Movie.2023.1080p.WEB-DL.H.264-GOOD", 5),
    ]
    selection = score_releases(releases, settings, runtime_minutes=RUNTIME)
    assert selection.candidates[0].release.title.endswith("-GOOD")


def test_freeleech_bonus_beats_better_source_codec_and_group() -> None:
    settings = SelectionSettings(release_group_tiers=[ReleaseGroupTier(tier=1, groups=["GOOD"])])
    releases = [
        release("Movie.2023.1080p.WEB-DL.H.265-GOOD", 5),
        release("Movie.2023.1080p.WEBRip.x264-FREE", 5, freeleech=True),
    ]
    selection = score_releases(releases, settings, runtime_minutes=RUNTIME)
    first = selection.candidates[0]
    assert first.release.title.endswith("-FREE")
    assert ("freeleech", 300) in first.factors
    assert not any(name == "freeleech" for name, _ in selection.candidates[1].factors)


def test_partial_freeleech_earns_part_of_the_bonus() -> None:
    half = release("Movie.2023.1080p.WEB-DL.H.264-HALF", 5)
    half.download_factor = 0.5
    selection = score_releases([half], SelectionSettings(), runtime_minutes=RUNTIME)
    assert ("freeleech", 150) in selection.candidates[0].factors


def test_freeleech_does_not_outweigh_missing_subtitles() -> None:
    free = release("Movie.2023.1080p.WEB-DL.H.264-FREE", 5, freeleech=True)
    paid = release("Movie.2023.1080p.WEB-DL.H.264-PAID", 5)
    nfos = {f"test:{free.title}": subs("nl"), f"test:{paid.title}": subs("en")}
    selection = score_releases(
        [free, paid], SelectionSettings(), runtime_minutes=RUNTIME, nfos=nfos
    )
    assert selection.candidates[0].release.title.endswith("-PAID")


def test_freeleech_still_breaks_exact_ties_with_the_bonus_off() -> None:
    tie = score_releases(
        [
            release("Movie.2023.1080p.WEB-DL.H.264-A", 5),
            release("Movie.2023.1080p.WEB-DL.H.264-B", 5, freeleech=True),
        ],
        SelectionSettings(freeleech_bonus=0),
        runtime_minutes=RUNTIME,
    )
    assert tie.candidates[0].release.title.endswith("-B")


# Subtitles (from NFOs)

SMALL = "Movie.2023.1080p.WEB-DL.H.264-SMALL"
OTHER = "Movie.2023.1080p.WEB-DL.H.264-OTHER"
SD = "Movie.2023.720p.WEB-DL.H.264-SD"
WATCH = SelectionSettings().watch_slots


def subs(*languages: str, forced: bool = False) -> NfoInfo:
    return NfoInfo(tuple(SubtitleTrack(lang, forced) for lang in languages), subtitles_known=True)


def key(title: str) -> str:
    return f"test:{title}"


def subtitle_releases() -> list[Release]:
    return [release(SMALL, 5), release(OTHER, 8), release(SD, 2.5)]


def scored(nfos: dict[str, NfoInfo | None], settings: SelectionSettings | None = None) -> Selection:
    return score_releases(
        subtitle_releases(), settings or SelectionSettings(), runtime_minutes=RUNTIME, nfos=nfos
    )


def test_unchecked_releases_get_no_subtitle_factor() -> None:
    selection = scored({})
    assert all(c.subtitles is SubtitleStatus.NOT_CHECKED for c in selection.candidates)
    assert not any(
        name.startswith("subtitles") for c in selection.candidates for name, _ in c.factors
    )
    target = selection.next_nfo_target(WATCH)
    assert target is not None and target.release.title == SMALL


def test_missing_subtitles_demote_a_release_within_its_slot() -> None:
    selection = scored({key(SMALL): subs("nl"), key(OTHER): subs("en", "nl")})
    by_title = {c.release.title: c for c in selection.candidates}
    assert by_title[SMALL].subtitles is SubtitleStatus.MISSING
    assert ("subtitles:missing", -1000) in by_title[SMALL].factors
    assert by_title[OTHER].subtitles is SubtitleStatus.WANTED
    assert ("subtitles:wanted", 25) in by_title[OTHER].factors
    pick = selection.watch_pick(WATCH)
    assert pick is not None and pick.release.title == OTHER
    assert selection.next_nfo_target(WATCH) is None  # the pick is verified


def test_next_target_is_the_new_leader_after_a_demotion() -> None:
    target = scored({key(SMALL): subs()}).next_nfo_target(WATCH)
    assert target is not None and target.release.title == OTHER


def test_forced_only_and_unknown_subtitles() -> None:
    selection = scored({key(SMALL): subs("en", forced=True), key(OTHER): None})
    by_title = {c.release.title: c for c in selection.candidates}
    assert by_title[SMALL].subtitles is SubtitleStatus.MISSING
    assert by_title[OTHER].subtitles is SubtitleStatus.UNKNOWN
    assert ("subtitles:unknown", -1000) in by_title[OTHER].factors
    untagged = scored({key(SMALL): subs("und")})
    assert {c.release.title: c for c in untagged.candidates}[
        SMALL
    ].subtitles is SubtitleStatus.UNKNOWN


def test_watch_moves_to_a_lower_slot_with_subtitles() -> None:
    selection = scored({key(SMALL): subs(), key(OTHER): subs("de"), key(SD): subs("en")})
    pick = selection.watch_pick(WATCH)
    assert pick is not None and pick.release.title == SD


def test_watch_falls_back_to_first_slot_when_nothing_has_subtitles() -> None:
    selection = scored({key(SMALL): subs(), key(OTHER): subs(), key(SD): subs()})
    pick = selection.watch_pick(WATCH)
    assert pick is not None and pick.slot is not None and pick.slot.name == "1080p_encode"
    assert selection.next_nfo_target(WATCH) is None


def test_subtitle_languages_accept_names_and_codes() -> None:
    settings = SelectionSettings(subtitle_languages=["Dutch", "eng"])
    selection = scored({key(SMALL): subs("nl")}, settings)
    assert {c.release.title: c for c in selection.candidates}[
        SMALL
    ].subtitles is SubtitleStatus.WANTED


def test_no_subtitle_languages_turns_checks_off() -> None:
    selection = scored({}, SelectionSettings(subtitle_languages=[]))
    assert selection.candidates[0].subtitles is None
    assert selection.next_nfo_target(WATCH) is None


def test_nfo_silent_on_subtitles_costs_as_much_as_the_wrong_language() -> None:
    silent = NfoInfo(subtitles_known=False, audio_languages=("en",))
    selection = scored({key(SMALL): silent, key(OTHER): subs("de")})
    by_title = {c.release.title: c for c in selection.candidates}
    assert ("subtitles:unknown", -1000) in by_title[SMALL].factors
    assert ("subtitles:missing", -1000) in by_title[OTHER].factors


def test_unknown_penalty_follows_missing_unless_set() -> None:
    assert (
        SelectionSettings(missing_subtitles_penalty=800).effective_unknown_subtitles_penalty == 800
    )
    settings = SelectionSettings(unknown_subtitles_penalty=250)
    assert settings.effective_unknown_subtitles_penalty == 250
    selection = scored({key(SMALL): None}, settings)
    by_title = {c.release.title: c for c in selection.candidates}
    assert ("subtitles:unknown", -250) in by_title[SMALL].factors


def test_freeleech_does_not_outweigh_unconfirmed_subtitles() -> None:
    free = release("Movie.2023.1080p.WEB-DL.H.264-FREE", 5, freeleech=True)
    paid = release("Movie.2023.1080p.WEB-DL.H.264-PAID", 5)
    nfos = {f"test:{free.title}": NfoInfo(), f"test:{paid.title}": subs("en")}
    selection = score_releases(
        [free, paid], SelectionSettings(), runtime_minutes=RUNTIME, nfos=nfos
    )
    assert selection.candidates[0].release.title.endswith("-PAID")


# HDR

HDR10 = "Movie.2023.2160p.WEB-DL.HDR10.H.265-HDR"
SDR = "Movie.2023.2160p.WEB-DL.H.265-SDR"
DV_ONLY = "Movie.2023.2160p.WEB-DL.DV.H.265-DV"


def hdr_scored(settings: SelectionSettings) -> dict[str, Candidate]:
    releases = [release(HDR10, 14), release(SDR, 14), release(DV_ONLY, 14)]
    selection = score_releases(releases, settings, runtime_minutes=RUNTIME)
    return {c.release.title: c for c in selection.candidates}


def test_hdr_scoring_is_off_by_default() -> None:
    by_title = hdr_scored(SelectionSettings())
    assert by_title[HDR10].score == by_title[SDR].score
    assert not any(name.startswith("hdr") for name, _ in by_title[HDR10].factors)
    # Dolby Vision without an HDR10 fallback still loses: wrong colors on non-DV displays.
    assert ("hdr:dv", -20) in by_title[DV_ONLY].factors
    assert by_title[DV_ONLY].score < by_title[SDR].score


def test_hdr_scoring_can_be_turned_on() -> None:
    by_title = hdr_scored(SelectionSettings(hdr_ladder=HdrLadder(enabled=True)))
    assert ("hdr:hdr10", 300) in by_title[HDR10].factors
    assert ("hdr:sdr", 100) in by_title[SDR].factors
    assert by_title[HDR10].score > by_title[SDR].score
