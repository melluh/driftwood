import re
import unicodedata

_NON_TITLE_CHARS = re.compile(r"[^\w\s]|_", re.UNICODE)
_WHITESPACE = re.compile(r"\s+")


def normalize_title(title: str) -> str:
    """
    A title reduced to what two spellings of the same name have in common:
    case-folded, accent-free, punctuation-free, single-spaced.
    """
    decomposed = unicodedata.normalize("NFKD", title)
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    without_punctuation = _NON_TITLE_CHARS.sub(" ", without_accents.casefold())
    return _WHITESPACE.sub(" ", without_punctuation).strip()
