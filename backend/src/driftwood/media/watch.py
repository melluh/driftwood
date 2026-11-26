"""Decides which release to grab when the user presses Watch."""

import asyncio
import logging
from functools import partial

import httpx

from driftwood.indexers.errors import IndexerError
from driftwood.media.releases import ReleaseService, describe, to_failures, to_schema
from driftwood.media.schemas import (
    IndexerFailure,
    MediaType,
    RankedRelease,
    Rejected,
    ReleaseAttributes,
    ScoreFactor,
    SubtitleStatus,
    SubtitleTrack,
    WatchEpisode,
    WatchPlan,
)
from driftwood.selection.config import SelectionSettings
from driftwood.selection.nfo import NfoInfo, parse_nfo
from driftwood.selection.scoring import (
    Candidate,
    EpisodeTarget,
    nfo_key,
    score_releases,
    wanted_languages,
)

log = logging.getLogger(__name__)


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
        equivalent_mbps=round(candidate.compared_mbps, 2) if candidate.compared_mbps else None,
        subtitle_status=SubtitleStatus(candidate.subtitles) if candidate.subtitles else None,
        subtitles=[
            SubtitleTrack(language=track.language, forced=track.forced)
            for track in (candidate.nfo.subtitles if candidate.nfo else ())
        ],
        audio_languages=list(candidate.nfo.audio_languages) if candidate.nfo else [],
    )


class WatchService:
    def __init__(
        self, releases: ReleaseService, settings: SelectionSettings, *, can_download: bool = False
    ) -> None:
        self.releases = releases
        self.settings = settings
        self.can_download = can_download

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

        score = partial(
            score_releases,
            lookup.result.releases,
            self.settings,
            runtime_minutes=lookup.media.runtime,
            episode=target,
        )
        nfos: dict[str, NfoInfo | None] = {}
        nfo_failures: list[IndexerFailure] = []
        selection = await asyncio.to_thread(score, nfos=nfos)

        # Verify subtitles of the would-be pick through its NFO; if that demotes
        # it, the next pick gets checked, up to the fetch budget.
        if self.settings.subtitle_languages:
            for _ in range(self.settings.nfo_fetch_budget):
                candidate = selection.next_nfo_target(self.settings.watch_slots)
                if candidate is None:
                    break
                nfos[nfo_key(candidate.release)] = await self._nfo_info(candidate, nfo_failures)
                selection = await asyncio.to_thread(score, nfos=nfos)

        pick = selection.watch_pick(self.settings.watch_slots)
        return WatchPlan(
            query=describe(lookup.query),
            indexers=lookup.result.searched,
            failures=to_failures(lookup.result) + nfo_failures,
            episode=WatchEpisode(season=target.season, episode=target.episode) if target else None,
            pick=to_ranked(pick) if pick else None,
            options=[to_ranked(winner) for winner in selection.slot_winners],
            considered=len(lookup.result.releases),
            rejected=[
                Rejected(reason=reason, count=count)
                for reason, count in selection.rejected.most_common()
            ],
            subtitle_languages=sorted(wanted_languages(self.settings)),
            nfos_checked=len(nfos),
            can_download=self.can_download,
        )

    async def _nfo_info(
        self, candidate: Candidate, failures: list[IndexerFailure]
    ) -> NfoInfo | None:
        release = candidate.release
        try:
            text = await self.releases.nfo_text(release.indexer_id, release.guid)
        except (IndexerError, httpx.HTTPError, TimeoutError) as exc:
            log.warning("NFO fetch for %s failed: %r", nfo_key(release), exc)
            failures.append(
                IndexerFailure(
                    indexer=release.indexer_id, message=f"NFO for {release.guid}: {exc!r}"
                )
            )
            return None
        return parse_nfo(text) if text else None
