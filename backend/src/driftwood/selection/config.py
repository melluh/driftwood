"""
Slot configuration (MediaManager's model, see its docs/configuration/slots-and-classification.md).
A slot is an ordered, AND-combined set of conditions over `ReleaseAttributes`,
plus an optional bitrate band. Releases are only ever compared within a slot.
"""

from typing import Literal

from pydantic import BaseModel, Field


class SlotCondition(BaseModel):
    attribute: str
    """A `ReleaseAttributes` field, or the virtual `release_group_tier`."""
    operator: Literal["eq", "in", "not_in", "contains"] = "eq"
    value: str | int | list[str]


class BitrateBand(BaseModel):
    min_mbps: float
    """Below this (or above `max_mbps`) the release is rejected: too low quality, or
    mislabeled / fake."""
    preferred_mbps: float
    """The size score peaks here and falls linearly to 0 at `min_mbps` (quality loss)
    and at `max_mbps` (longer download)."""
    max_mbps: float
    codec_adjusted: bool = False
    """Read the bitrates as H.264-equivalent: a release's bitrate is multiplied by its
    codec's `codec_efficiency` first, so an HEVC file at 4 Mbps counts as ~5.6. For
    slots that mix codecs; single-codec slots state their bitrates as-is."""


class ScoringWeights(BaseModel):
    """How much each property counts within a slot. Only differences between
    releases of the same slot matter, not the absolute numbers."""

    source: dict[str, int]
    """By source: `web-dl`, `remux`, `bluray-encode`, `webrip`, `hdtv`, `dvd`."""
    codec: dict[str, int] = Field(
        default_factory=lambda: {"av1": 150, "h265": 120, "h264": 50, "xvid": 0}
    )
    size: int
    """Points at the slot's preferred bitrate (see `BitrateBand`)."""
    seeders_per_doubling: float
    """Points per doubling of the seeder count: `n * log2(seeders)`..."""
    seeders_max: int
    """...up to this."""


QUALITY_WEIGHTS = ScoringWeights(
    # MediaManager's scale: source dominates, size and seeders break ties.
    source={
        "web-dl": 1000,
        "remux": 950,
        "bluray-encode": 900,
        "webrip": 700,
        "hdtv": 400,
        "dvd": 300,
    },
    size=100,
    seeders_per_doubling=10,
    seeders_max=60,
)

SPEED_WEIGHTS = ScoringWeights(
    # Watch now: a sensible size and a healthy swarm matter most. At 1080p a WEB-DL
    # and a Blu-ray encode look alike; a WEBRip is a step down, HDTV/DVD more so.
    source={
        "web-dl": 300,
        "remux": 300,
        "bluray-encode": 300,
        "webrip": 200,
        "hdtv": 50,
        "dvd": 0,
    },
    size=400,
    seeders_per_doubling=40,
    seeders_max=200,  # reached at 32 seeders
)


class SlotDefinition(BaseModel):
    name: str
    label: str
    conditions: list[SlotCondition] = Field(default_factory=list)
    bitrate: BitrateBand | None = None
    profile: Literal["speed", "quality"] = "quality"
    """Which weights score this slot: `speed` for slots Watch grabs from (start
    watching soon), `quality` for the manual upgrades."""


class ReleaseGroupTier(BaseModel):
    tier: int
    """Lower is better."""
    groups: list[str] = Field(default_factory=list)


class HdrLadder(BaseModel):
    enabled: bool = False
    """Score releases by HDR format (`order`). Off by default, for SDR-only devices:
    HDR then earns nothing, and only `dv_only_penalty` still applies, since Dolby Vision
    without an HDR10 fallback shows wrong colors on any non-DV display.
    Turn on with `DRIFTWOOD_SELECTION__HDR_LADDER__ENABLED=true`."""
    order: list[str] = Field(
        default_factory=lambda: ["dv_hdr10plus", "dv_hdr10", "hdr10plus", "hdr10", "dv", "sdr"]
    )
    """HDR combinations, best first."""
    dv_only_penalty: int = -20
    """Dolby Vision without an HDR10 fallback layer looks wrong on non-DV displays."""


def _eq(attribute: str, value: str) -> SlotCondition:
    return SlotCondition(attribute=attribute, operator="eq", value=value)


def _in(attribute: str, *values: str, negate: bool = False) -> SlotCondition:
    return SlotCondition(
        attribute=attribute, operator="not_in" if negate else "in", value=[*values]
    )


DEFAULT_SLOTS = [
    SlotDefinition(
        name="4k_remux",
        label="4K Remux",
        conditions=[_eq("resolution", "2160p"), _eq("source", "remux")],
        bitrate=BitrateBand(min_mbps=50, preferred_mbps=70, max_mbps=90),
    ),
    SlotDefinition(
        name="4k_encode",
        label="4K Encode",
        conditions=[
            _eq("resolution", "2160p"),
            _in("source", "remux", negate=True),
            _in("codec", "h265", "av1"),
        ],
        bitrate=BitrateBand(min_mbps=10, preferred_mbps=17, max_mbps=25),
    ),
    SlotDefinition(
        name="1080p_remux",
        label="1080p Remux",
        conditions=[_eq("resolution", "1080p"), _eq("source", "remux")],
        bitrate=BitrateBand(min_mbps=25, preferred_mbps=32, max_mbps=40),
    ),
    SlotDefinition(
        name="1080p_encode",
        label="1080p Encode",
        conditions=[
            _eq("resolution", "1080p"),
            _in("source", "remux", negate=True),
            _in("codec", "h264", "h265", "av1"),
        ],
        # MediaManager targets 8 Mbps; Driftwood grabs this slot for immediate
        # watching, so it aims lower: 6 Mbps H.264 is ~4.2 GB for 97 minutes, ~5.4 GB
        # for two hours. Below 4 Mbps (~2.8 GB / 97 min) quality suffers too much.
        bitrate=BitrateBand(min_mbps=4, preferred_mbps=6, max_mbps=15, codec_adjusted=True),
        profile="speed",
    ),
    SlotDefinition(
        name="720p",
        label="720p",
        conditions=[_eq("resolution", "720p")],
        bitrate=BitrateBand(min_mbps=1.5, preferred_mbps=4, max_mbps=8, codec_adjusted=True),
        profile="speed",
    ),
]


class SelectionSettings(BaseModel):
    slots: list[SlotDefinition] = Field(default_factory=lambda: list(DEFAULT_SLOTS))
    """Best quality first; a release belongs to the first slot whose conditions all match."""

    watch_slots: list[str] = Field(
        default_factory=lambda: ["1080p_encode", "720p", "4k_encode", "1080p_remux", "4k_remux"]
    )
    """"Watch" grabs the best release of the first slot here that has any. The other
    slots' best releases are offered as manual upgrades."""

    hdr_ladder: HdrLadder = Field(default_factory=HdrLadder)
    release_group_tiers: list[ReleaseGroupTier] = Field(default_factory=list)

    allowed_language_variants: list[str] = Field(default_factory=list)
    """`multi`, `nordic`, `german_dl`, `dubbed`: rejected unless listed here."""

    min_seeders: int = 3

    subtitle_languages: list[str] = Field(default_factory=lambda: ["en"])
    """Wanted subtitle languages, as names or ISO codes (`English`, `en`, `eng`). Releases
    are checked against their NFO; an empty list turns subtitle checks (and NFO fetching) off.
    Set as JSON: `DRIFTWOOD_SELECTION__SUBTITLE_LANGUAGES='["en", "nl"]'`."""

    missing_subtitles_penalty: int = 1000
    """Subtracted when the NFO lists the subtitles and none is wanted (or there are none).
    About the size of the whole source-quality scale, so a subtitled release wins its slot."""

    unknown_subtitles_penalty: int | None = None
    """Subtracted when the release has no NFO, its NFO doesn't mention subtitles, or it
    lists a subtitle track without a language. None (the default) means the same as
    `missing_subtitles_penalty`: unconfirmed subtitles count as missing ones."""

    @property
    def effective_unknown_subtitles_penalty(self) -> int:
        if self.unknown_subtitles_penalty is None:
            return self.missing_subtitles_penalty
        return self.unknown_subtitles_penalty

    wanted_subtitles_bonus: int = 25
    """Added when the NFO lists a full (non-forced) subtitle track in a wanted language."""

    freeleech_bonus: int = 300
    """Added to freeleech releases (scaled for partial freeleech: 50% off earns half).
    Beats differences in source, codec or seeders, but not the full size range (400 in
    speed slots), so a much bigger freeleech file still loses to one near the target;
    and never the subtitle penalties."""

    speed_weights: ScoringWeights = Field(default_factory=lambda: SPEED_WEIGHTS.model_copy())
    """Weights for `profile="speed"` slots (the ones Watch grabs from)."""

    quality_weights: ScoringWeights = Field(default_factory=lambda: QUALITY_WEIGHTS.model_copy())
    """Weights for `profile="quality"` slots (manual upgrades) and unslotted releases."""

    codec_efficiency: dict[str, float] = Field(default_factory=lambda: {"h265": 1.4, "av1": 1.6})
    """Bitrate multipliers to H.264-equivalent (unlisted codecs: 1.0). HEVC needs roughly
    30-40% less bitrate than H.264 for the same quality, AV1 a bit less still. Rules of
    thumb: encoder quality varies a lot."""

    def weights_for(self, slot: SlotDefinition | None) -> ScoringWeights:
        if slot is not None and slot.profile == "speed":
            return self.speed_weights
        return self.quality_weights

    nfo_fetch_budget: int = 5
    """Most NFOs fetched per Watch. Each is a request to the indexer (1 s apart on
    TorrentLeech), so only the release about to be picked is checked, one at a time."""
