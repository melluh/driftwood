from driftwood.config import TitleIndexSettings
from driftwood.media.schemas import MediaType
from driftwood.titles.index import TitleIndex

type Row = tuple[MediaType, int, str, float]


def make_index(titles: list[str], head_size: int) -> TitleIndex:
    """An index whose rows are `titles` in popularity order (first = most popular)."""
    count = len(titles)
    rows: list[Row] = [
        (MediaType.movie, position + 1, title, float(count - position))
        for position, title in enumerate(titles)
    ]
    return TitleIndex(rows, head_size=head_size)


def settings(**overrides: object) -> TitleIndexSettings:
    return TitleIndexSettings(**overrides)  # type: ignore[arg-type]
