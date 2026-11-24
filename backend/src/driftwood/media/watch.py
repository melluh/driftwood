"""Decides which release to grab when the user presses Watch."""

import asyncio

from driftwood.media.releases import ReleaseService, describe, to_failures, to_schema
from driftwood.media.schemas import (
    MediaType,
    RankedRelease,
    Rejected,
    ReleaseAttributes,
    ScoreFactor,
    WatchEpisode,
    WatchPlan,
)
from driftwood.selection.config import SelectionSettings
from driftwood.selection.scoring import Candidate, EpisodeTarget, score_releases


def to_ranked(candidate: Candidate) -> RankedRelease:
    attributes = candidate.attributes
    return RankedRelease(
        release=to_schema(candidate.release),
        attributes=ReleaseAttributes(
            resolution=attributes.resolution,
            source=attributes.source,
            codec=attributes.codec,
            hdr_flags=list(attributes.hdr_flags),
            audio_codecs=list(attributes.audio_codecs),
            language_variant=attributes.language_variant,
            release_group=attributes.release_group,
            season=attributes.season,
            episodes=list(attributes.episodes),
        ),
        slot=candidate.slot.name if candidate.slot else None,
        slot_label=candidate.slot.label if candidate.slot else None,
        score=candidate.score,
        factors=[ScoreFactor(name=name, points=points) for name, points in candidate.factors],
        effective_mbps=round(candidate.effective_mbps, 2) if candidate.effective_mbps else None,
    )


class WatchService:
    def __init__(self, releases: ReleaseService, settings: SelectionSettings) -> None:
        self.releases = releases
        self.settings = settings

    async def plan(
        self,
        media_type: MediaType,
        media_id: int,
        *,
        season: int | None = None,
        episode: int | None = None,
    ) -> WatchPlan | None:
        """
        Search the indexers and pick a release. Series need one episode: it
        defaults to S01E01 (there's no watch history yet).
        """
        target = None
        if media_type is MediaType.tv:
            target = EpisodeTarget(season=season or 1, episode=episode or 1)
        lookup = await self.releases.find(
            media_type,
            media_id,
            season=target.season if target else None,
            episode=target.episode if target else None,
        )
        if lookup is None:
            return None

        selection = await asyncio.to_thread(
            score_releases,
            lookup.result.releases,
            self.settings,
            runtime_minutes=lookup.media.runtime,
            episode=target,
        )
        pick = selection.watch_pick(self.settings.watch_slots)
        return WatchPlan(
            query=describe(lookup.query),
            indexers=lookup.result.searched,
            failures=to_failures(lookup.result),
            episode=WatchEpisode(season=target.season, episode=target.episode) if target else None,
            pick=to_ranked(pick) if pick else None,
            options=[to_ranked(winner) for winner in selection.slot_winners],
            considered=len(lookup.result.releases),
            rejected=[
                Rejected(reason=reason, count=count)
                for reason, count in selection.rejected.most_common()
            ],
        )
