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
    """Below this (or above `max_mbps`) the release is rejected as mislabeled or fake."""
    preferred_mbps: float
    """Releases score by how close they land to this."""
    max_mbps: float


class SlotDefinition(BaseModel):
    name: str
    label: str
    conditions: list[SlotCondition] = Field(default_factory=list)
    bitrate: BitrateBand | None = None


class ReleaseGroupTier(BaseModel):
    tier: int
    """Lower is better."""
    groups: list[str] = Field(default_factory=list)


class HdrLadder(BaseModel):
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
        # watching, so it aims lower (about 5.5 GB for a two-hour movie).
        bitrate=BitrateBand(min_mbps=3, preferred_mbps=6, max_mbps=15),
    ),
    SlotDefinition(
        name="720p",
        label="720p",
        conditions=[_eq("resolution", "720p")],
        bitrate=BitrateBand(min_mbps=1.5, preferred_mbps=4, max_mbps=8),
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
