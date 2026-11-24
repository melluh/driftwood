"""
TorrentLeech, ported from Prowlarr's Cardigann definition
`definitions/v11/torrentleech.yml` (https://github.com/Prowlarr/Indexers).
Re-check that file when TorrentLeech changes; see docs/indexer-design.md §2.
"""

import logging
import re
from datetime import UTC, datetime
from typing import Any, ClassVar, Literal
from urllib.parse import quote, urljoin
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from pydantic import SecretStr

from driftwood.indexers import categories
from driftwood.indexers.base import IndexerSettings, SessionIndexer
from driftwood.indexers.errors import AuthError, IndexerError, ParseError
from driftwood.indexers.http import HttpSession
from driftwood.indexers.models import (
    Capabilities,
    CategoryMapping,
    Release,
    SearchQuery,
    SearchType,
)
from driftwood.indexers.registry import register

log = logging.getLogger(__name__)

MIRRORS = (
    "https://www.torrentleech.org/",
    "https://www.torrentleech.cc/",
    "https://www.torrentleech.me/",
    "https://www.tleechreload.org/",
    "https://www.tlgetin.cc/",
)

MIN_REQUEST_INTERVAL = 4.1
"""Seconds between requests, as in the Prowlarr definition."""

LOGIN_PATH = "user/account/login/"
LOGOUT_SELECTOR = 'a[href="/user/account/logout"]'
LOGIN_FORM_SELECTOR = 'form[name="login-form"]'

CATEGORIES: tuple[CategoryMapping, ...] = tuple(
    CategoryMapping(site_id, torznab_id, description)
    for site_id, torznab_id, description in [
        ("8", 2030, "Movies Cam"),
        ("9", 2030, "Movies TS/TC"),
        ("11", 2030, "Movies DVDRip/DVDScreener"),
        ("37", 2080, "Movies WEBRip"),
        ("43", 2040, "Movies HDRip"),
        ("14", 2040, "Movies BlurayRip"),
        ("12", 2070, "Movies DVD-R"),
        ("13", 2050, "Movies Bluray"),
        ("47", 2045, "Movies 4K"),
        ("15", 2000, "Movies Boxsets"),
        ("29", 2020, "Documentaries"),
        ("36", 2010, "Movies Foreign"),
        ("26", 5030, "TV Episodes"),
        ("32", 5040, "TV Episodes HD"),
        ("27", 5000, "TV Boxsets"),
        ("34", 5070, "TV Anime"),
        ("35", 5000, "TV Cartoons"),
        ("44", 5020, "TV Foreign"),
        ("17", 4050, "Games PC"),
        ("42", 4030, "Games Mac"),
        ("18", 1040, "Games XBOX"),
        ("19", 1050, "Games XBOX360"),
        ("40", 1140, "Games XBOXONE"),
        ("20", 1080, "Games PS2"),
        ("21", 1080, "Games PS3"),
        ("39", 1180, "Games PS4"),
        ("49", 1180, "Games PS5"),
        ("22", 1020, "Games PSP"),
        ("28", 1030, "Games Wii"),
        ("30", 1010, "Games Nintendo DS"),
        ("48", 1090, "Games Nintendo Switch"),
        ("23", 4020, "PC ISO"),
        ("24", 4030, "PC Mac"),
        ("25", 4040, "PC Mobile"),
        ("33", 4010, "PC 0-day"),
        ("38", 8000, "Education"),
        ("45", 7020, "Books EBooks"),
        ("46", 7030, "Books Comics"),
        ("31", 3000, "Audio"),
        ("16", 3020, "Music videos"),
    ]
)

GENRES = frozenset(
    {
        "Action", "Adventure", "Animation", "Biography", "Comedy", "Crime", "Documentary",
        "Drama", "Family", "Fantasy", "Game-Show", "History", "Horror", "Kids", "Music",
        "Musical", "Mystery", "News", "Reality-TV", "Romance", "Sci-Fi", "Science-Fiction",
        "Sport", "Soap", "Talk-Show", "Thriller", "War", "Western",
    }
)  # fmt: skip

_REQUEST_PREFIX = re.compile(r"^\[REQ(UEST(ED)?)?\]\s*", re.IGNORECASE)
_EXCLUDE_OPERATOR = re.compile(r"(^|\s)-")
_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

MISSING_TITLE = "TorrentLeech did not provide a title"
MINIMUM_RATIO = 1.0
MINIMUM_SEED_TIME = 864_000  # 10 days; less for upgraded user classes


class TorrentLeechSettings(IndexerSettings):
    username: str
    password: SecretStr
    alt_2fa_token: SecretStr | None = None
    """Site Profile → Alt 2FA Token; needed when 2FA is enabled on the account."""
    freeleech_only: bool = False
    exclude_scene: bool = False
    exclude_archives: bool = False
    """Appends `-tags:rar` to keyword searches (ignored for IMDb searches)."""
    sort: Literal["added", "seeders", "size", "nameSort"] = "added"
    order: Literal["desc", "asc"] = "desc"
    timezone: str = "UTC"
    """Timezone of the account's profile setting, which `addedTimestamp` follows."""


def episode_string(season: int | None, episode: str | None) -> str | None:
    """`S01E03`, `S01` for a whole season, or a daily-show date (`2024.01.31`) as-is."""
    if season is not None and episode and episode.isdigit():
        return f"S{season:02}E{int(episode):02}"
    if season is not None and not episode:
        return f"S{season:02}"
    return episode or None


def search_keywords(query: SearchQuery, *, exclude_archives: bool = False) -> str:
    tokens = [query.q, str(query.year) if query.year else None]
    if query.type is SearchType.TV:
        tokens.append(episode_string(query.season, query.episode))
    keywords = " ".join(token.strip() for token in tokens if token and token.strip())
    # A leading "-" would exclude the term on TorrentLeech.
    keywords = _EXCLUDE_OPERATOR.sub(" ", keywords)
    if exclude_archives:
        keywords += " -tags:rar"
    return keywords.strip()


def build_search_path(query: SearchQuery, settings: TorrentLeechSettings) -> str:
    imdb_id = query.imdb_id if query.type is SearchType.MOVIE else None
    keywords = search_keywords(query, exclude_archives=settings.exclude_archives and not imdb_id)

    path = "torrents/browse/list"
    site_categories = categories.to_site_ids(query.categories, CATEGORIES)
    if site_categories:
        path += "/categories/" + ",".join(site_categories)
    facets = [
        tag
        for tag, enabled in (
            ("FREELEECH", settings.freeleech_only),
            ("nonscene", settings.exclude_scene),
        )
        if enabled
    ]
    if facets:
        path += "/facets/tags:" + ",".join(facets)
    if imdb_id:
        path += f"/imdbID/{quote(imdb_id, safe='')}/"
    else:
        path += f"/exact/1/query/{quote(keywords, safe='')}/"
    if not keywords:
        path += "newfilter/2/"  # browse mode; also includes 0day and music
    return path + f"orderby/{settings.sort}/order/{settings.order}"


def clean_title(name: str | None, filename: str | None) -> str:
    if name:
        return _REQUEST_PREFIX.sub("", name).strip() or name
    if filename:
        return filename.removesuffix(".torrent")
    return MISSING_TITLE


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_timestamp(value: Any, timezone: ZoneInfo) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        local = datetime.strptime(value, _TIMESTAMP_FORMAT).replace(tzinfo=timezone)
    except ValueError:
        return None
    return local.astimezone(UTC)


def parse_row(row: dict[str, Any], base_url: str, timezone: ZoneInfo) -> Release:
    fid = row["fid"]
    filename = row.get("filename") or ""
    tags = row.get("tags") or []
    category = row.get("categoryID")
    return Release(
        indexer_id=TorrentLeechIndexer.id,
        guid=str(fid),
        title=clean_title(row.get("name"), filename),
        details_url=f"{base_url}torrent/{fid}",
        download_url=f"{base_url}download/{fid}/{quote(filename)}",
        size=_int(row.get("size")),
        published=parse_timestamp(row.get("addedTimestamp"), timezone),
        categories=categories.to_torznab(str(category), CATEGORIES) if category is not None else [],
        seeders=_int(row.get("seeders")),
        leechers=_int(row.get("leechers")),
        grabs=_int(row.get("completed")),
        imdb_id=row.get("imdbID") or None,
        genres=[tag for tag in tags if tag in GENRES],
        download_factor=0.0 if row.get("download_multiplier") == 0 else 1.0,
        upload_factor=1.0,
        minimum_ratio=MINIMUM_RATIO,
        minimum_seed_time=MINIMUM_SEED_TIME,
        raw=row,
    )


def parse_search_results(data: Any, base_url: str, timezone: ZoneInfo) -> list[Release]:
    """Parse the browse/list JSON. Malformed rows are logged and skipped."""
    if not isinstance(data, dict) or not isinstance(data.get("torrentList", []), list):
        raise ParseError("unexpected TorrentLeech search response", snippet=repr(data))
    releases = []
    for row in data.get("torrentList") or []:
        try:
            releases.append(parse_row(row, base_url, timezone))
        except (KeyError, TypeError, AttributeError):
            log.warning("Skipping malformed TorrentLeech row: %r", row)
    return releases


def parse_login_form(html: str, page_url: str) -> tuple[str, dict[str, str]] | None:
    """The login form's absolute action URL and its default field values, or None if absent."""
    soup = BeautifulSoup(html, "lxml")
    form = soup.select_one(LOGIN_FORM_SELECTOR)
    if form is None:
        return None
    fields: dict[str, str] = {}
    for field in form.select("input[name]"):
        if field.has_attr("disabled"):
            continue
        kind = str(field.get("type") or "text").lower()
        if kind in ("checkbox", "radio") and not field.has_attr("checked"):
            continue
        fields[str(field["name"])] = str(field.get("value") or "")
    action = urljoin(page_url, str(form.get("action") or ""))
    return action, fields


def check_login_result(html: str) -> None:
    """Raise `AuthError` if the page answering the login POST shows a failure."""
    soup = BeautifulSoup(html, "lxml")
    if (error := soup.select_one("p.text-danger")) is not None:
        raise AuthError(f"TorrentLeech login failed: {error.get_text(' ', strip=True)}")
    heading = soup.select_one(".login-container h2")
    if heading is not None and "One Time Password" in heading.get_text():
        raise AuthError(
            "TorrentLeech has 2FA enabled; set the Alt 2FA Token "
            "(Site Profile → Alt 2FA Token) in the indexer settings"
        )
    if soup.select_one(LOGIN_FORM_SELECTOR) is not None:
        raise AuthError("TorrentLeech login failed")


def has_logout_link(html: str) -> bool:
    return BeautifulSoup(html, "lxml").select_one(LOGOUT_SELECTOR) is not None


def _is_html(response: httpx.Response) -> bool:
    return "html" in response.headers.get("content-type", "")


def _is_torrent(response: httpx.Response) -> bool:
    content_type = response.headers.get("content-type", "")
    return "application/x-bittorrent" in content_type or response.content.startswith(b"d")


@register
class TorrentLeechIndexer(SessionIndexer):
    id: ClassVar[str] = "torrentleech"
    name: ClassVar[str] = "TorrentLeech"
    privacy: ClassVar[Literal["public", "semi-private", "private"]] = "private"
    settings_model: ClassVar[type[IndexerSettings]] = TorrentLeechSettings
    default_mirrors: ClassVar[tuple[str, ...]] = MIRRORS
    min_request_interval: ClassVar[float] = MIN_REQUEST_INTERVAL

    settings: TorrentLeechSettings

    def __init__(self, settings: TorrentLeechSettings, http: HttpSession) -> None:
        super().__init__(settings, http)
        self._timezone = ZoneInfo(settings.timezone)

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            search_modes={
                SearchType.GENERIC: frozenset({"q"}),
                SearchType.TV: frozenset({"q", "season", "ep"}),
                SearchType.MOVIE: frozenset({"q", "imdbid"}),
            },
            categories=CATEGORIES,
            supports_raw_search=True,
        )

    # Session

    async def login(self) -> None:
        page = await self.http.get(LOGIN_PATH, follow_redirects=True)
        form = parse_login_form(page.text, str(page.url))
        if form is None:
            if has_logout_link(page.text):  # cookies were still good
                return
            raise ParseError("TorrentLeech login form not found", url=str(page.url))

        action, fields = form
        alt_token = self.settings.alt_2fa_token
        fields.update(
            username=self.settings.username,
            password=self.settings.password.get_secret_value(),
            alt2FAToken=alt_token.get_secret_value() if alt_token else "",
        )
        result = await self.http.post(action, data=fields, follow_redirects=True)
        check_login_result(result.text)

        home = await self.http.get("", follow_redirects=True)
        if not has_logout_link(home.text):
            raise AuthError("TorrentLeech login did not produce a session")
        log.info("Logged in to TorrentLeech as %s", self.settings.username)

    def is_logged_out(self, response: httpx.Response) -> bool:
        if response.is_redirect or response.status_code >= 400:
            return True
        return _is_html(response) and not has_logout_link(response.text)

    # Search

    def build_requests(self, query: SearchQuery) -> list[str]:
        return [build_search_path(query, self.settings)]

    def parse_response(self, response: httpx.Response, query: SearchQuery) -> list[Release]:
        try:
            data = response.json()
        except ValueError as exc:
            raise ParseError(
                "TorrentLeech search did not return JSON",
                url=str(response.url),
                snippet=response.text,
            ) from exc
        return parse_search_results(data, self.http.base_url, self._timezone)

    # NFO

    async def fetch_nfo(self, guid: str) -> bytes | None:
        """`nfo/download/{fid}`; None when the torrent has no NFO."""
        path = f"nfo/download/{quote(guid, safe='')}"
        await self.ensure_logged_in()
        generation = self._session_generation
        response = await self.http.get(path)
        if response.status_code == httpx.codes.NOT_FOUND:
            return None
        if self.is_logged_out(response):
            await self._relogin(generation)
            response = await self.http.get(path)
            if response.status_code == httpx.codes.NOT_FOUND:
                return None
            if self.is_logged_out(response):
                raise AuthError("TorrentLeech: still logged out right after logging in")
        if _is_html(response) or not response.content.strip():
            return None  # a site page (e.g. "no NFO") rather than the file
        return response.content

    # Download

    async def download(self, release: Release) -> bytes:
        await self.ensure_logged_in()
        generation = self._session_generation
        response = await self.http.get(release.download_url)
        if response.status_code == httpx.codes.OK and _is_torrent(response):
            return response.content
        await self._relogin(generation)
        response = await self.http.get(release.download_url)
        if response.status_code == httpx.codes.OK and _is_torrent(response):
            return response.content
        raise IndexerError(
            f"TorrentLeech download of {release.guid} returned HTTP {response.status_code} "
            f"({response.headers.get('content-type', 'unknown type')}), not a torrent"
        )
