# Indexer client design: TorrentLeech first, more later

Notes for a Python implementation of torrent indexer search. The first target is
TorrentLeech (TL), but the design should let more indexers be added without
touching callers.

Source of truth for TL behaviour: Prowlarr's Cardigann definition
`definitions/v11/torrentleech.yml` in https://github.com/Prowlarr/Indexers
(engine: `Prowlarr/src/NzbDrone.Core/Indexers/Definitions/Cardigann/`).
Re-check it when TL breaks; the community updates it quickly.

---

## 1. Abstraction schema

Three layers. Callers only ever see layer 1.

```
          caller (CLI / service / *arr bridge)
                         │  SearchQuery → list[Release]
┌────────────────────────▼─────────────────────────┐
│ 1. Indexer interface  (Protocol / ABC)           │
│    capabilities · search · download · test       │
├──────────────────────────────────────────────────┤
│ 2. Per-indexer implementation                    │
│    TorrentLeechIndexer, later: XIndexer, …       │
│    (or one CardigannIndexer driven by YAML)      │
├──────────────────────────────────────────────────┤
│ 3. Shared infrastructure                         │
│    HttpSession (cookies, rate limit, retries,    │
│    mirror fallback) · category map · settings    │
│    storage · date/size parsing helpers           │
└──────────────────────────────────────────────────┘
```

### 1.1 Core data models (`models.py`)

Use `dataclasses` (or pydantic if settings validation is wanted).

```python
class SearchType(StrEnum):
    GENERIC = "search"
    TV = "tv-search"
    MOVIE = "movie-search"

@dataclass(frozen=True)
class SearchQuery:
    type: SearchType = SearchType.GENERIC
    q: str | None = None                 # free text
    categories: tuple[int, ...] = ()     # Torznab IDs (2000, 5040, ...)
    imdb_id: str | None = None           # "tt1234567"
    tmdb_id: int | None = None
    tvdb_id: int | None = None
    season: int | None = None
    episode: str | None = None           # str: may be "3" or "2024.01.31"
    year: int | None = None
    limit: int | None = None
    offset: int = 0

@dataclass
class Release:
    indexer_id: str                      # "torrentleech"
    guid: str                            # stable per-indexer id, e.g. TL fid
    title: str
    details_url: str | None
    download_url: str                    # may need the session to fetch
    size: int | None                     # bytes
    published: datetime | None           # tz-aware, UTC
    categories: list[int]                # Torznab IDs (mapped)
    seeders: int | None = None
    leechers: int | None = None
    grabs: int | None = None
    imdb_id: str | None = None
    genres: list[str] = field(default_factory=list)
    download_factor: float = 1.0         # 0.0 = freeleech
    upload_factor: float = 1.0
    minimum_ratio: float | None = None
    minimum_seed_time: int | None = None # seconds
    magnet: str | None = None
    infohash: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)  # debugging

@dataclass(frozen=True)
class CategoryMapping:
    site_id: str            # site's own id, kept as str ("26")
    torznab_id: int         # 5030
    description: str        # "TV Episodes"
    default: bool = False

@dataclass(frozen=True)
class Capabilities:
    search_modes: dict[SearchType, frozenset[str]]  # {"tv-search": {"q","season","ep"}}
    categories: tuple[CategoryMapping, ...]
    supports_raw_search: bool = False
```

Torznab categories are shared vocabulary across indexers. Keep one module
(`categories.py`) with the standard IDs (the table is in Prowlarr's
`NewznabStandardCategory.cs`). Useful ones for TL: Movies 2000, Movies/Foreign 2010,
Movies/Other 2020, Movies/SD 2030, Movies/HD 2040, Movies/UHD 2045,
Movies/BluRay 2050, Movies/DVD 2070, Movies/WEB-DL 2080, TV 5000, TV/Foreign
5020, TV/SD 5030, TV/HD 5040, TV/Anime 5070, Audio 3000, Audio/Video 3020,
PC 4000, PC/0day 4010, PC/ISO 4020, PC/Mac 4030, PC/Mobile-Other 4040,
PC/Games 4050, Console/* 1000–1180, Books/EBook 7020, Books/Comics 7030,
Other 8000.

Category mapping rules (copy Prowlarr's behaviour):
- Torznab → site: a query for a parent (e.g. 5000) matches every site category
  mapped to 5000 *or any 50xx child*.
- Site → Torznab: a result carries the mapped ID plus its parent (5040 → [5040, 5000]).
- No requested categories → send none (site searches everything), unless the
  indexer defines `default` mappings.

### 1.2 Indexer interface (`base.py`)

```python
class Indexer(ABC):
    id: ClassVar[str]               # "torrentleech"
    name: ClassVar[str]
    privacy: ClassVar[Literal["public", "semi-private", "private"]]
    settings_model: ClassVar[type[IndexerSettings]]

    def __init__(self, settings: IndexerSettings, http: HttpSession): ...

    @property
    @abstractmethod
    def capabilities(self) -> Capabilities: ...

    @abstractmethod
    async def search(self, query: SearchQuery) -> list[Release]: ...

    @abstractmethod
    async def download(self, release: Release) -> bytes:
        """Return the .torrent bytes (handles auth)."""

    async def test(self) -> None:
        """Log in and run an empty search; raise IndexerError on failure."""
        await self.search(SearchQuery())
```

Recommended internal split for scraping-style indexers (not part of the public
interface, but a helper base class `SessionIndexer(Indexer)` can provide it):

```python
    async def ensure_logged_in(self) -> None      # lazy, idempotent
    async def login(self) -> None                 # site-specific
    def is_logged_out(self, resp) -> bool         # redirect to login / test selector missing
    def build_requests(self, q: SearchQuery) -> list[Request]   # pure, unit-testable
    def parse_response(self, resp, q) -> list[Release]          # pure, unit-testable
```

`search()` = ensure_logged_in → for each request: fetch → if `is_logged_out`,
re-login once and retry → parse → dedupe by guid → apply limit/offset.

Keeping `build_requests` and `parse_response` pure (no I/O) means they can be
tested against saved fixtures without credentials.

### 1.3 Settings

Per-indexer pydantic model, so a UI/CLI can be generated from it (same idea as
the `settings:` block in Cardigann YAML).

```python
class IndexerSettings(BaseModel):
    base_url: HttpUrl | None = None      # None → first working mirror
    enabled: bool = True

class TorrentLeechSettings(IndexerSettings):
    username: str
    password: SecretStr
    alt_2fa_token: SecretStr | None = None
    freeleech_only: bool = False
    exclude_scene: bool = False
    exclude_archives: bool = False       # appends "-tags:rar"; ignored for IMDb search
    sort: Literal["added", "seeders", "size", "nameSort"] = "added"
    order: Literal["desc", "asc"] = "desc"
```

Secrets (passwords, cookies, 2FA token) must never be logged; redact URLs and
form bodies in debug logs.

### 1.4 Shared HTTP layer (`http.py`)

One `HttpSession` per indexer instance (use `httpx.AsyncClient`):
- **Cookie jar**, persisted to disk per indexer (avoid logging in on every run;
  TL may rate-limit or flag repeated logins).
- **Rate limiter**: minimum interval between requests per indexer
  (TL: 4.1 s). Simple `asyncio.Lock` + last-request timestamp.
- **Mirrors**: list of base URLs; on connection error, try the next and
  remember the one that works.
- **Redirect handling**: don't auto-follow on search requests; a 302 to the
  login page means "session expired".
- **Retries** with backoff on 5xx / timeouts only (never on 4xx).
- User-Agent configurable. Cloudflare / FlareSolverr support is a later,
  optional plug-in (`ChallengeSolver` hook), not needed for TL today.

### 1.5 Registry

```python
INDEXERS: dict[str, type[Indexer]] = {}
def register(cls): INDEXERS[cls.id] = cls; return cls
```

Config file (TOML/YAML) lists instances: `{id: torrentleech, settings: {...}}`.
An `IndexerManager` fans a query out to all enabled indexers concurrently
(`asyncio.gather`, per-indexer timeout, errors collected not raised) and merges
results.

### 1.6 Errors

```
IndexerError
├── AuthError            # bad credentials, 2FA required → disable until fixed
├── RateLimitedError     # back off
├── SiteUnavailableError # all mirrors down / 5xx
└── ParseError           # site layout changed → include URL + snippet
```

### 1.7 Path to "many indexers"

Two kinds of implementation fit behind the same `Indexer` interface:
1. **Hand-written classes** (start here, TL first). Best for a few important
   trackers.
2. **`CardigannIndexer`**: one generic class that loads a Prowlarr YAML file
   and interprets it. Only worth building once there are several indexers to
   support. Main work: a regex-based "Go-template" engine (`if/else/end`,
   `and/or/eq/ne`, `join`, `range`, `re_replace`), about 30 filters (most used:
   `re_replace`, `replace`, `dateparse`, `append`, `regexp`, `querystring`),
   CSS selectors with `:contains`/`:has`/`:root` (soupsieve), JSONPath
   (jsonpath-ng), Go/.NET date layouts → `strptime`, and .NET regex quirks.
   Check pyackett (https://github.com/dmarkey/pyackett) first, since it already
   does this; it's young (0.5.0, Oct 2026) and PyPI lists no license.
   Prowlarr is GPLv3 and the Indexers repo has no license file, so check
   licensing before bundling definitions.

The models above deliberately mirror the Cardigann/Torznab fields so option 2
can be added later without changing anything above layer 2.

---

## 2. TorrentLeech specifics

### 2.1 Sites

Mirrors (in Prowlarr's order): `https://www.torrentleech.org/`,
`https://www.torrentleech.cc/`, `https://www.torrentleech.me/`,
`https://www.tleechreload.org/`, `https://www.tlgetin.cc/`. Also listed:
`https://rss.torrentleech.cc/`. Legacy: `https://v4.torrentleech.org/`.

### 2.2 Login (HTML form)

1. `GET {base}user/account/login/`
2. Parse `form[name="login-form"]`. Collect **all** named `<input>`s (hidden
   fields included; skip disabled ones and unchecked checkboxes/radios), using
   their `value` or `""`.
3. Override: `username`, `password`, `alt2FAToken` (empty string if unset).
4. POST (form-encoded) to the form's `action` attribute (resolve relative to the
   login URL).
5. Error detection on the response:
   - `p.text-danger` present → AuthError with that text.
   - `.login-container h2` containing "One Time Password" → "2FA enabled; set
     Alt 2FA Token (Site Profile → Alt 2FA Token)".
   - `form[name="login-form"]` still present → generic login failure.
6. Success test: `GET {base}` and check for `a[href="/user/account/logout"]`.

Session-expiry check on later requests: a redirect, an HTTP error, or (for HTML
responses only) the logout link missing → re-login once and retry.

### 2.3 Search request

GET, JSON response. Path built from the parts in this order:

```
torrents/browse/list
  [/categories/{site_ids joined by ","}]          if any categories
  [/facets/tags:{FREELEECH}{,}{nonscene}]         if freeleech_only or exclude_scene
  /imdbID/{tt…}/                                  if imdb_id
   OR /exact/1/query/{keywords}/                  otherwise
  [newfilter/2/]                                  if keywords empty (browse; includes 0day + music)
  orderby/{sort}/order/{order}
```

Examples:
- `torrents/browse/list/categories/26,32/exact/1/query/the%20office%20S01/orderby/added/order/desc`
- `torrents/browse/list/imdbID/tt0111161/orderby/seeders/order/desc`
- `torrents/browse/list/facets/tags:FREELEECH,nonscene/exact/1/query//newfilter/2/orderby/added/order/desc` (empty search)

Note: with IMDb search the keywords segment is skipped, but `newfilter/2/` is
still added when keywords are empty. Reproduce this exactly; it's what
Prowlarr sends.

Keyword construction:
- tokens = [q, series/movie title, year, episode string] (skip empties), joined by space.
- TV episode string: `S{season:02}E{ep:02}`, or `S{season:02}` for season-only. Check
  the Prowlarr `TvSearchCriteria` for the exact format.
- Filters, in order: replace `(^|\s)-` with `" "` (a leading `-` would *exclude*
  terms on TL); if `exclude_archives`, append ` -tags:rar`.
- URL-encode with `quote(…, safe="")` (spaces → `%20`, not `+`).

Rate limit: ≥ 4.1 s between requests.

Results per page follow the user's TL profile setting ("Torrents per page");
advise setting it to 100. Prowlarr does not paginate TL. Pagination
(`/page/N`?) is unverified, so check against the site before relying on it.

### 2.4 Response parsing

```jsonc
{
  "numFound": 1234,
  "torrentList": [
    {
      "fid": 123456,
      "filename": "Some.Release.torrent",
      "name": "Some.Release.1080p.WEB-DL",   // can be null!
      "categoryID": 32,
      "tags": ["Comedy", "FREELEECH", ...],
      "imdbID": "tt1234567",
      "seeders": 10, "leechers": 2, "completed": 55,
      "size": 1234567890,                    // bytes
      "addedTimestamp": "2021-10-25 02:18:31",
      "download_multiplier": 0               // 0 = freeleech
    }
  ]
}
```

Field mapping:

| Release field       | Source                                                                 |
|---------------------|------------------------------------------------------------------------|
| guid                | `fid`                                                                  |
| title               | `name` with `(?i)^\[REQ(UEST(ED)?)?\]\s*` removed; if null → "TorrentLeech did not provide a title" (or skip) |
| details_url         | `{base}torrent/{fid}`                                                  |
| download_url        | `{base}download/{fid}/{filename}` (needs session cookies)              |
| categories          | map `categoryID` → Torznab (+ parent)                                  |
| genres              | `tags` ∩ {Action, Adventure, Animation, Biography, Comedy, Crime, Documentary, Drama, Family, Fantasy, Game-Show, History, Horror, Kids, Music, Musical, Mystery, News, Reality-TV, Romance, Sci-Fi, Science-Fiction, Sport, Soap, Talk-Show, Thriller, War, Western} |
| imdb_id             | `imdbID`                                                               |
| seeders/leechers    | `seeders` / `leechers`                                                 |
| grabs               | `completed`                                                            |
| size                | `size`                                                                 |
| published           | `addedTimestamp`, format `%Y-%m-%d %H:%M:%S`. Timezone follows the account profile setting, so make it a setting (default UTC) |
| download_factor     | `0` if `download_multiplier == 0` else `1`                             |
| upload_factor       | `1`                                                                    |
| minimum_ratio       | `1.0`                                                                  |
| minimum_seed_time   | `864000` s (10 days; less for upgraded user classes)                   |

Treat every field as optional (`.get`) except `fid`; log and skip malformed rows
rather than failing the whole search.

### 2.5 Category map (site id → Torznab)

| site | Torznab          | desc                    | site | Torznab            | desc                  |
|-----:|------------------|-------------------------|-----:|--------------------|-----------------------|
| 8    | Movies/SD 2030   | Movies Cam              | 18   | Console/XBox 1040  | Games XBOX            |
| 9    | Movies/SD 2030   | Movies TS/TC            | 19   | Console/XBox 360 1050 | Games XBOX360      |
| 11   | Movies/SD 2030   | Movies DVDRip/DVDScreener | 40 | Console/XBox One 1140 | Games XBOXONE      |
| 37   | Movies/WEB-DL 2080 | Movies WEBRip         | 20   | Console/PS3 1080   | Games PS2             |
| 43   | Movies/HD 2040   | Movies HDRip            | 21   | Console/PS3 1080   | Games (desc says Mac) |
| 14   | Movies/HD 2040   | Movies BlurayRip        | 39   | Console/PS4 1180   | Games PS4             |
| 12   | Movies/DVD 2070  | Movies DVD-R            | 49   | Console/PS4 1180   | Games PS5             |
| 13   | Movies/BluRay 2050 | Movies Bluray         | 22   | Console/PSP 1020   | Games PSP             |
| 47   | Movies/UHD 2045  | Movies 4K               | 28   | Console/Wii 1030   | Games Wii             |
| 15   | Movies 2000      | Movies Boxsets          | 30   | Console/NDS 1010   | Games Nintendo DS     |
| 29   | Movies/Other 2020 | Documentaries          | 48   | Console/Other 1090 | Games Nintendo Switch |
| 36   | Movies/Foreign 2010 | Movies Foreign       | 23   | PC/ISO 4020        | PC ISO                |
| 26   | TV/SD 5030       | TV Episodes             | 24   | PC/Mac 4030        | PC Mac                |
| 32   | TV/HD 5040       | TV Episodes HD          | 25   | PC/Mobile-Other 4040 | PC Mobile           |
| 27   | TV 5000          | TV Boxsets              | 33   | PC/0day 4010       | PC 0-day              |
| 34   | TV/Anime 5070    | TV Anime                | 38   | Other 8000         | Education             |
| 35   | TV 5000          | TV Cartoons             | 45   | Books/EBook 7020   | Books EBooks          |
| 44   | TV/Foreign 5020  | TV Foreign              | 46   | Books/Comics 7030  | Books Comics          |
| 17   | PC/Games 4050    | Games PC                | 31   | Audio 3000         | Audio                 |
| 42   | PC/Mac 4030      | Games Mac               | 16   | Audio/Video 3020   | Music videos          |

Supported search params (capabilities): search [q]; tv-search [q, season, ep];
movie-search [q, imdbid]; music-search [q]; book-search [q]. Raw search
supported. Movie search by IMDb ignores `exclude_archives`.

### 2.6 Download

`GET {base}download/{fid}/{filename}` with the logged-in session. Verify the
response is a torrent (starts with `d` / bencoded, or
`Content-Type: application/x-bittorrent`); an HTML response means the session
expired, so re-login once.

---

## 3. Suggested layout and stack

```
src/new_media/indexers/
  __init__.py          # registry
  base.py              # Indexer ABC, SessionIndexer helper
  models.py            # SearchQuery, Release, Capabilities, CategoryMapping
  categories.py        # Torznab standard table + mapping helpers
  http.py              # HttpSession: cookies, rate limit, mirrors, retries
  errors.py
  manager.py           # fan-out across indexers
  torrentleech.py      # TorrentLeechIndexer + TorrentLeechSettings
  # later: cardigann/ (engine.py, templates.py, filters.py, selectors.py)
tests/indexers/
  fixtures/torrentleech/{login_page.html, login_failed.html, search.json, search_null_title.json}
  test_torrentleech_requests.py   # URL building, pure
  test_torrentleech_parse.py      # fixture parsing, pure
  test_categories.py
```

Dependencies: `httpx`, `beautifulsoup4` + `lxml` (login form), `pydantic`
(settings), `pytest` + `pytest-asyncio` + `respx` (HTTP mocking). Add
`soupsieve`/`jsonpath-ng`/`pyyaml` only when the Cardigann engine is built.

## 4. Implementation order

1. `models.py`, `categories.py`, `errors.py`: no I/O, fully unit-tested.
2. `http.py` with rate limiter + persisted cookie jar.
3. `TorrentLeechIndexer.build_requests`: test against the URL examples in §2.3.
4. `parse_response`: test with fixtures (capture a real response once; strip
   personal data before committing).
5. Login + session-expiry detection + retry-once.
6. `download()`.
7. Small CLI: `new-media search torrentleech "query" --cat 5040`.
8. Optional: a Torznab XML endpoint so Sonarr/Radarr can use it directly.
9. Second indexer → check that the abstraction holds before building Cardigann.

## 5. Open questions / to verify against the live site

- Timezone of `addedTimestamp` (profile-dependent) → setting.
- Pagination support in the browse/list JSON endpoint.
- Whether TL offers an RSS/API-key based search that avoids form login
  (`rss.torrentleech.cc` is listed as a link).
- Rate-limit / ban policy for automated login; persist cookies to minimise logins.
