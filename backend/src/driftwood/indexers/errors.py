class IndexerError(Exception):
    """Base class for every indexer failure."""


class AuthError(IndexerError):
    """Bad credentials or 2FA required: the indexer stays unusable until settings change."""


class RateLimitedError(IndexerError):
    pass


class SiteUnavailableError(IndexerError):
    """Every mirror is down, or the site keeps answering 5xx."""


class ParseError(IndexerError):
    """The site's response no longer matches what the parser expects (layout changed)."""

    def __init__(self, message: str, *, url: str | None = None, snippet: str | None = None):
        details = [message]
        if url:
            details.append(f"url={url}")
        if snippet:
            details.append(f"snippet={snippet[:200]!r}")
        super().__init__(" ".join(details))
        self.url = url
        self.snippet = snippet
