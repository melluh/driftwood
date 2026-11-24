import re
from pathlib import PurePosixPath

_TMDB_TAG = re.compile(r"[\[{]tmdb(?:id)?[-=](\d+)[\]}]", re.IGNORECASE)


def find_tmdb_id(relative_path: PurePosixPath) -> int | None:
    """Find the nearest TMDB tag, checking the filename before its parent directories."""
    for part in (relative_path.name, *reversed(relative_path.parent.parts)):
        if match := _TMDB_TAG.search(part):
            media_id = int(match.group(1))
            if media_id > 0:
                return media_id
    return None
