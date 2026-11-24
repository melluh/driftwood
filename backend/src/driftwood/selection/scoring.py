"""
Slot-based release scoring, ported from MediaManager's `media_manager/indexer/scoring.py`.

Each release is classified, hard-filtered (cams, language variants, low
seeders, implausible bitrate, wrong episode), put into the first slot it
matches, and scored only against releases in that same slot. Weights keep
MediaManager's magnitude spacing (source ~1000s, HDR ~100s, codec ~100s,
group tier ≤100), except that bitrate fit and seeders weigh more: Driftwood
grabs for immediate watching, where a smaller file and a fast swarm matter.
"""

import math
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from driftwood.indexers.models import Release
from driftwood.selection.classification import ReleaseAttributes, classify_release
from driftwood.selection.config import (
    BitrateBand,
    HdrLadder,
    ReleaseGroupTier,
    SelectionSettings,
    SlotCondition,
    SlotDefinition,
)
from driftwood.selection.nfo import NfoInfo, normalize_language

SOURCE_QUALITY_SCORE = {
    "web-dl": 1000,
    "remux": 950,
    "bluray-encode": 900,
    "webrip": 700,
    "hdtv": 400,
    "dvd": 300,
}

CODEC_QUALITY_SCORE = {"av1": 150, "h265": 120, "h264": 50, "xvid": 0}

AUDIO_TIEBREAK_SCORE = {"truehd": 8, "ddp": 8, "dts": 5, "atmos": 4, "opus": 3, "aac": 2}

BITRATE_FIT_MAX_SCORE = 100
"""MediaManager uses 40; closeness to the (smaller) preferred size matters more here."""

SEEDER_HEALTH_MAX_SCORE = 60
"""MediaManager uses 25; more seeders means the download starts playing sooner."""


class Rejection:
    LOW_QUALITY_SOURCE = "cam / telesync / screener"
    LANGUAGE_VARIANT = "dubbed or multi-language"
    LOW_SEEDERS = "too few seeders"
    BITRATE = "bitrate outside the slot's range"
    WRONG_EPISODE = "not the requested episode"


@dataclass(frozen=True)
class EpisodeTarget:
    season: int
    episode: int


class SubtitleStatus(StrEnum):
    WANTED = "wanted"
    """The NFO lists a full subtitle track in a wanted language."""
    MISSING = "missing"
    """The NFO lists the subtitles (or says there are none), and none is wanted."""
    UNKNOWN = "unknown"
    """No NFO, or the NFO doesn't say."""
    NOT_CHECKED = "not_checked"
    """The NFO wasn't fetched (only likely picks are checked)."""


ACCEPTABLE_SUBTITLES = {SubtitleStatus.WANTED, SubtitleStatus.NOT_CHECKED, None}

type NfoResults = Mapping[str, NfoInfo | None]
"""Fetched NFOs by `nfo_key`; None means the release has no NFO."""


def nfo_key(release: Release) -> str:
    return f"{release.indexer_id}:{release.guid}"


def wanted_languages(settings: SelectionSettings) -> frozenset[str]:
    return frozenset(
        normalize_language(lang) or lang.lower() for lang in settings.subtitle_languages
    )


def subtitle_status(
    release: Release, nfos: NfoResults, wanted: frozenset[str]
) -> SubtitleStatus | None:
    """None when subtitle checks are off (no wanted languages)."""
    if not wanted:
        return None
    key = nfo_key(release)
    if key not in nfos:
        return SubtitleStatus.NOT_CHECKED
    nfo = nfos[key]
    if nfo is None or not nfo.subtitles_known:
        return SubtitleStatus.UNKNOWN
    full_tracks = [track for track in nfo.subtitles if not track.forced]
    if any(track.language in wanted for track in full_tracks):
        return SubtitleStatus.WANTED
    if any(track.language == "und" for track in full_tracks):
        return SubtitleStatus.UNKNOWN  # MediaInfo track without a language tag
    return SubtitleStatus.MISSING


@dataclass
class Candidate:
    release: Release
    attributes: ReleaseAttributes
    slot: SlotDefinition | None = None
    slot_index: int | None = None
    effective_mbps: float | None = None
    score: int = 0
    factors: list[tuple[str, int]] = field(default_factory=list)
    nfo: NfoInfo | None = None
    subtitles: SubtitleStatus | None = None


@dataclass
class Selection:
    candidates: list[Candidate]
    """Every surviving release: slotted ones by slot order then score, unslotted last."""
    rejected: Counter[str]

    @property
    def slot_winners(self) -> list[Candidate]:
        """The best candidate of each slot, in slot (quality) order."""
        winners: dict[int, Candidate] = {}
        for candidate in self.candidates:
            if candidate.slot_index is not None:
                winners.setdefault(candidate.slot_index, candidate)
        return [winners[index] for index in sorted(winners)]

    def _watch_leaders(self, watch_slots: list[str]) -> list[Candidate]:
        winners = {c.slot.name: c for c in self.slot_winners if c.slot}
        return [winners[name] for name in watch_slots if name in winners]

    def watch_pick(self, watch_slots: list[str]) -> Candidate | None:
        """
        The best release of the first `watch_slots` entry whose best release has
        (or may have) wanted subtitles; failing that, the first slot's best.
        """
        leaders = self._watch_leaders(watch_slots)
        acceptable = (c for c in leaders if c.subtitles in ACCEPTABLE_SUBTITLES)
        return next(acceptable, leaders[0] if leaders else None)

    def next_nfo_target(self, watch_slots: list[str]) -> Candidate | None:
        """
        The release whose NFO to fetch next: the would-be pick, while it is
        unchecked. None once the pick is settled (checked and fine, or nothing
        left to check). Checking one at a time keeps indexer requests minimal.
        """
        for leader in self._watch_leaders(watch_slots):
            if leader.subtitles is SubtitleStatus.NOT_CHECKED:
                return leader
            if leader.subtitles in ACCEPTABLE_SUBTITLES:
                return None
        return None


def _group_tier(release_group: str | None, tiers: list[ReleaseGroupTier]) -> int | None:
    if not release_group:
        return None
    group = release_group.lower()
    for tier in tiers:
        if group in {g.lower() for g in tier.groups}:
            return tier.tier
    return None


def _matches(
    attributes: ReleaseAttributes, condition: SlotCondition, tiers: list[ReleaseGroupTier]
) -> bool:
    if condition.attribute == "release_group_tier":
        actual: object = _group_tier(attributes.release_group, tiers)
    else:
        actual = getattr(attributes, condition.attribute, None)
    value = condition.value
    values = value if isinstance(value, list) else [value]
    actual_set = set(actual) if isinstance(actual, tuple | list) else None

    match condition.operator:
        case "eq":
            return actual == value
        case "in":
            return bool(actual_set & set(values)) if actual_set is not None else actual in values
        case "not_in":
            return (
                not (actual_set & set(values)) if actual_set is not None else actual not in values
            )
        case "contains":
            return actual_set is not None and value in actual_set


def find_slot(
    attributes: ReleaseAttributes, slots: list[SlotDefinition], tiers: list[ReleaseGroupTier]
) -> tuple[SlotDefinition, int] | None:
    for index, slot in enumerate(slots):
        if all(_matches(attributes, condition, tiers) for condition in slot.conditions):
            return slot, index
    return None


def hdr_tier(hdr_flags: tuple[str, ...]) -> str:
    flags = set(hdr_flags)
    dv, plus, hdr10 = "dv" in flags, "hdr10plus" in flags, "hdr10" in flags
    if dv and plus:
        return "dv_hdr10plus"
    if dv and hdr10:
        return "dv_hdr10"
    if plus:
        return "hdr10plus"
    if hdr10:
        return "hdr10"
    if dv:
        return "dv"
    return "sdr"


def hdr_score(tier: str, ladder: HdrLadder) -> int:
    index = ladder.order.index(tier) if tier in ladder.order else len(ladder.order)
    score = 100 * (len(ladder.order) - index)
    return score + ladder.dv_only_penalty if tier == "dv" else score


def bitrate_fit_score(mbps: float | None, band: BitrateBand | None) -> int:
    if band is None or mbps is None or not band.min_mbps <= mbps <= band.max_mbps:
        return 0
    half_range = (
        band.preferred_mbps - band.min_mbps
        if mbps <= band.preferred_mbps
        else band.max_mbps - band.preferred_mbps
    )
    if half_range <= 0:
        return BITRATE_FIT_MAX_SCORE
    fit = max(0.0, 1 - abs(mbps - band.preferred_mbps) / half_range)
    return round(BITRATE_FIT_MAX_SCORE * fit)


def seeder_score(seeders: int | None) -> int:
    return min(SEEDER_HEALTH_MAX_SCORE, round(10 * math.log2(max(1, seeders or 0))))


def effective_mbps(
    release: Release, attributes: ReleaseAttributes, runtime_minutes: int | None
) -> float | None:
    """Average bitrate from size and runtime; None when either (or the episode count) is unknown."""
    if not release.size or not runtime_minutes or runtime_minutes <= 0:
        return None
    if attributes.season is not None and not attributes.episodes:
        return None  # season pack: episode count unknown
    parts = max(1, len(attributes.episodes))
    return release.size * 8 / (runtime_minutes * 60 * parts) / 1_000_000


def _rejection(
    release: Release,
    attributes: ReleaseAttributes,
    settings: SelectionSettings,
    episode: EpisodeTarget | None,
) -> str | None:
    if attributes.source == "low-quality":
        return Rejection.LOW_QUALITY_SOURCE
    variant = attributes.language_variant
    if variant is not None and variant not in settings.allowed_language_variants:
        return Rejection.LANGUAGE_VARIANT
    if (release.seeders or 0) < settings.min_seeders:
        return Rejection.LOW_SEEDERS
    if episode is not None and (
        attributes.season != episode.season or episode.episode not in attributes.episodes
    ):
        return Rejection.WRONG_EPISODE
    return None


def score_releases(
    releases: list[Release],
    settings: SelectionSettings,
    *,
    runtime_minutes: int | None,
    episode: EpisodeTarget | None = None,
    nfos: NfoResults | None = None,
) -> Selection:
    """
    Classify, filter, slot and score. `nfos` holds the NFOs fetched so far
    (see `Selection.next_nfo_target`). CPU-bound (guessit): run it off the event loop.
    """
    candidates: list[Candidate] = []
    rejected: Counter[str] = Counter()
    tiers = settings.release_group_tiers
    nfos = nfos or {}
    wanted = wanted_languages(settings)

    for release in releases:
        attributes = classify_release(release.title)
        if reason := _rejection(release, attributes, settings, episode):
            rejected[reason] += 1
            continue

        candidate = Candidate(release, attributes)
        candidate.effective_mbps = effective_mbps(release, attributes, runtime_minutes)
        if found := find_slot(attributes, settings.slots, tiers):
            slot, index = found
            band = slot.bitrate
            mbps = candidate.effective_mbps
            if band is not None and mbps is not None and not band.min_mbps <= mbps <= band.max_mbps:
                rejected[Rejection.BITRATE] += 1
                continue
            candidate.slot, candidate.slot_index = slot, index

        tier = hdr_tier(attributes.hdr_flags)
        source = attributes.source
        factors = [
            (f"source:{source}", SOURCE_QUALITY_SCORE.get(source, 0) if source else 0),
            (f"codec:{attributes.codec}", CODEC_QUALITY_SCORE.get(attributes.codec or "", 0)),
            (f"hdr:{tier}", hdr_score(tier, settings.hdr_ladder)),
            (
                "bitrate_fit",
                bitrate_fit_score(
                    candidate.effective_mbps, candidate.slot.bitrate if candidate.slot else None
                ),
            ),
            ("seeders", seeder_score(release.seeders)),
            (
                "audio",
                max((AUDIO_TIEBREAK_SCORE.get(c, 0) for c in attributes.audio_codecs), default=0),
            ),
        ]
        group_tier = _group_tier(attributes.release_group, tiers)
        if group_tier is not None:
            factors.append((f"release_group_tier:{group_tier}", max(0, 100 - group_tier * 10)))
        if release.download_factor < 1:
            discount = 1 - max(0.0, release.download_factor)
            factors.append(("freeleech", round(settings.freeleech_bonus * discount)))
        candidate.nfo = nfos.get(nfo_key(release))
        candidate.subtitles = subtitle_status(release, nfos, wanted)
        subtitle_points = {
            SubtitleStatus.WANTED: settings.wanted_subtitles_bonus,
            SubtitleStatus.MISSING: -settings.missing_subtitles_penalty,
            SubtitleStatus.UNKNOWN: -settings.effective_unknown_subtitles_penalty,
        }
        if candidate.subtitles in subtitle_points:
            factors.append(
                (f"subtitles:{candidate.subtitles}", subtitle_points[candidate.subtitles])
            )
        candidate.score = sum(points for _, points in factors)
        candidate.factors = [(name, points) for name, points in factors if points]
        candidates.append(candidate)

    candidates.sort(
        key=lambda c: (
            c.slot_index if c.slot_index is not None else 10**9,
            -c.score,
            0 if c.release.download_factor == 0 else 1,  # freeleech breaks ties
        )
    )
    return Selection(candidates, rejected)
