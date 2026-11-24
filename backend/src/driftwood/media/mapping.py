"""Maps TMDB movie / TV JSON onto Driftwood's schemas - the one place their field names differ."""

from typing import Any

from driftwood.media.schemas import CastMember, Genre, MediaDetails, MediaSummary, MediaType

type TmdbJson = dict[str, Any]

MAX_CAST = 20

_FIELDS: dict[MediaType, dict[str, str]] = {
    MediaType.movie: {
        "title": "title",
        "original_title": "original_title",
        "date": "release_date",
    },
    MediaType.tv: {
        "title": "name",
        "original_title": "original_name",
        "date": "first_air_date",
    },
}


def _year(date: str | None) -> int | None:
    if date and len(date) >= 4 and date[:4].isdigit():
        return int(date[:4])
    return None


def _runtime(media_type: MediaType, data: TmdbJson) -> int | None:
    if media_type is MediaType.movie:
        return data.get("runtime") or None
    episode_runtimes = data.get("episode_run_time") or []
    if episode_runtimes:
        return episode_runtimes[0]
    last_episode = data.get("last_episode_to_air") or {}
    return last_episode.get("runtime") or None


def to_summary(media_type: MediaType, data: TmdbJson) -> MediaSummary:
    fields = _FIELDS[media_type]
    return MediaSummary(
        media_type=media_type,
        id=data["id"],
        title=data.get(fields["title"]) or data.get(fields["original_title"]) or "",
        original_title=data.get(fields["original_title"]),
        year=_year(data.get(fields["date"])),
        poster_path=data.get("poster_path"),
        backdrop_path=data.get("backdrop_path"),
        popularity=data.get("popularity"),
    )


def to_details(media_type: MediaType, data: TmdbJson) -> MediaDetails:
    fields = _FIELDS[media_type]
    credits = data.get("credits") or {}
    external_ids = data.get("external_ids") or {}
    return MediaDetails(
        **to_summary(media_type, data).model_dump(),
        tagline=data.get("tagline") or None,
        overview=data.get("overview") or None,
        genres=[Genre(**genre) for genre in data.get("genres") or []],
        runtime=_runtime(media_type, data),
        release_date=data.get(fields["date"]) or None,
        last_air_date=data.get("last_air_date") or None,
        status=data.get("status") or None,
        vote_average=data.get("vote_average"),
        vote_count=data.get("vote_count"),
        number_of_seasons=data.get("number_of_seasons"),
        number_of_episodes=data.get("number_of_episodes"),
        original_language=data.get("original_language"),
        imdb_id=data.get("imdb_id") or external_ids.get("imdb_id"),
        cast=[
            CastMember(
                id=member["id"],
                name=member.get("name", ""),
                character=member.get("character") or None,
                profile_path=member.get("profile_path"),
            )
            for member in (credits.get("cast") or [])[:MAX_CAST]
        ],
    )
