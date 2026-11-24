from driftwood.media.home import pick_featured
from driftwood.media.schemas import HomeRow, MediaSummary, MediaType


def item(media_type: MediaType, id: int, *, backdrop: bool = True) -> MediaSummary:
    return MediaSummary(
        media_type=media_type,
        id=id,
        title=f"{media_type} {id}",
        poster_path="/p.jpg",
        backdrop_path="/b.jpg" if backdrop else None,
        overview="Something happens.",
    )


def test_featured_interleaves_rows_and_skips_items_without_backdrop() -> None:
    movies = HomeRow(id="m", title="M", items=[item(MediaType.movie, 1), item(MediaType.movie, 2)])
    shows = HomeRow(
        id="t",
        title="T",
        items=[item(MediaType.tv, 1, backdrop=False), item(MediaType.tv, 2)],
    )
    featured = pick_featured([movies, shows], count=3)
    assert [(f.media_type, f.id) for f in featured] == [
        (MediaType.movie, 1),
        (MediaType.movie, 2),
        (MediaType.tv, 2),
    ]
