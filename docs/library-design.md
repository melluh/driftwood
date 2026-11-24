# Library design: tracking media files on disk

Implementation plan for knowing which titles Driftwood has files for, and showing
"Ready to play" on the media page. Written to be implemented as-is; decisions marked
**Decided** were settled with the project owner and shouldn't be reopened.

---

## 1. Goals and decisions

- Track every playable video file under the configured library roots, linked to the TMDB
  title (and, for TV, the season/episode) it contains.
- Discover files already on disk automatically, using the `[tmdbid-…]` tag in their path.
- The media page shows **Ready to play** when at least one file for the title is present.

**Decided:**

1. **The filesystem is the source of truth; the database is a rebuildable cache.** Every
   match comes from the path alone. Dropping the tables and rescanning must reproduce the
   same state. There is no manual matching, now or later.
2. **Movies and TV live in separate roots.** Each root declares its kind, and that kind
   alone decides `media_type`. (TMDB ids are namespaced per type: movie 1399 and TV 1399
   are different titles, so a bare tag can't say which one it is.)
3. **One way in.** A future download/import step will not write rows itself: it moves the
   finished file into a root, *named with the tag*, and asks the scanner to scan that path.
4. **The library is shared**, not per user (it's what's on the household's disks). Its
   routes still require a signed-in user, like everything under `/api`.
5. Unmatched files are not stored; they're logged and counted in the scan status.
6. No filesystem watching (inotify/`watchfiles`) in v1: it doesn't work on NFS/SMB mounts.
   A periodic scan plus an on-demand scan endpoint is the baseline.

---

## 2. Configuration (`backend/src/driftwood/config.py`)

Add next to the other settings groups and hang it off `Settings` as `library`:

```python
class LibraryRoot(BaseModel):
    name: str
    """Stable key stored in the database, e.g. "movies". Paths are stored relative to the
    root, so the mount point (`path`) can change without invalidating anything."""

    path: Path
    kind: Literal["movies", "tv"]


class LibrarySettings(BaseModel):
    roots: list[LibraryRoot] = []
    """e.g. DRIFTWOOD_LIBRARY__ROOTS='[{"name":"movies","path":"/srv/movies","kind":"movies"},
    {"name":"tv","path":"/srv/tv","kind":"tv"}]'"""

    scan_interval_minutes: float = 30

    video_extensions: frozenset[str] = frozenset(
        {".mkv", ".mp4", ".m4v", ".avi", ".mov", ".ts", ".m2ts", ".webm", ".wmv"}
    )

    min_size_mb: float = 50
    """Smaller video files are treated as samples and ignored."""

    ignored_dirs: frozenset[str] = frozenset(
        {"extras", "featurettes", "behind the scenes", "deleted scenes", "interviews",
         "scenes", "shorts", "trailers", "sample", "samples", "other"}
    )
    """Directory names (compared case-insensitively) whose contents are never scanned."""

    missing_grace_days: float = 7
    """How long a file that disappeared is kept (as `missing`) before its row is deleted."""
```

Validate that root names are unique (a `model_validator` on `LibrarySettings`). Add the
variable to `backend/.env.example` with a comment, and a short "Library" section to the
README (how to configure roots, which naming conventions are recognised).

---

## 3. Data model (`backend/src/driftwood/db/models.py`)

Two tables. Follow the conventions in `models.py`: `UTCDateTime` for timestamps,
`utcnow()` for defaults, `String(n)` lengths, and the naming convention on `Base.metadata`.

### `media_files`: one row per matched physical file

| column          | type                         | notes                                                         |
|-----------------|------------------------------|---------------------------------------------------------------|
| `id`            | int PK                       |                                                               |
| `root`          | `String(64)`                 | `LibraryRoot.name`                                            |
| `path`          | `String(4096)`               | POSIX path relative to the root                               |
| `size`          | `BigInteger`                 | bytes                                                         |
| `mtime_ns`      | `BigInteger`                 | `stat().st_mtime_ns`; with `size`, decides whether to re-parse |
| `state`         | `String(16)`                 | `present` \| `missing` (a `StrEnum` in Python)                |
| `missing_since` | `UTCDateTime`, nullable      | set when a file first goes missing, cleared when it returns   |
| `attributes`    | `JSON`                       | `classify_release(filename)` output, see §4.3                 |
| `probe`         | `JSON`, nullable             | reserved for ffprobe data later; always null in v1            |
| `first_seen_at` | `UTCDateTime`                |                                                               |
| `last_seen_at`  | `UTCDateTime`                | updated on every scan that sees the file                      |

Constraints and indexes: `UNIQUE(root, path)`, `INDEX(state)`.

### `media_file_links`: what a file contains

A separate table because one file can hold several episodes (`S01E01E02` gives two rows).

| column       | type                                         | notes               |
|--------------|----------------------------------------------|---------------------|
| `id`         | int PK                                       |                     |
| `file_id`    | FK → `media_files.id`, `ondelete="CASCADE"`  |                     |
| `media_type` | `String(8)`                                  | `MediaType` value   |
| `media_id`   | int                                          | TMDB id             |
| `season`     | int, nullable                                | null for movies     |
| `episode`    | int, nullable                                | null for movies     |

Constraints and indexes: `UNIQUE(file_id, media_type, media_id, season, episode)`,
`INDEX(media_type, media_id)`. A `relationship` from `MediaFile.links` with
`cascade="all, delete-orphan"` keeps rewriting links simple.

### Migration

`cd backend && uv run alembic revision --autogenerate -m "media files"`, then review it
against `versions/20261124_0002_my_list.py` (revision ids are short sequential strings:
this one is `"0003"`, file `2026MMDD_0003_media_files.py`). SQLite needs `batch_alter_table`
for index creation, as in 0002. Migrations run automatically on startup.

---

## 4. Matching: path → links (pure functions)

New package `backend/src/driftwood/library/`. Keep §4.1 and §4.2 free of I/O so they can
be tested with plain path strings.

### 4.1 `tags.py`: finding the TMDB id

Recognise these conventions (Jellyfin, Plex, and common variants), case-insensitively:

```
[tmdbid-438631]   [tmdbid=438631]   [tmdb-438631]   {tmdb-438631}   {tmdbid-438631}
```

A single regex works: `[\[{]tmdb(?:id)?[-=](\d+)[\]}]`. Expose
`find_tmdb_id(relative_path: PurePosixPath) -> int | None`. It looks at the **file name
first**, then each parent directory from nearest to farthest, up to (not including) the
root. The nearest tag wins. Ignore ids ≤ 0.

Typical layouts:

```
movies/Dune (2021) [tmdbid-438631]/Dune (2021) [tmdbid-438631] - 2160p.mkv
movies/Dune (2021) [tmdbid-438631]/Dune.2021.2160p.UHD.BluRay.x265-GROUP.mkv
tv/Game of Thrones (2011) [tmdbid-1399]/Season 01/Game of Thrones S01E01.mkv
tv/Game of Thrones (2011) [tmdbid-1399]/Specials/Game of Thrones S00E01.mkv
```

### 4.2 `matching.py`: links for one file

```python
@dataclass(frozen=True)
class Link:
    media_type: MediaType
    media_id: int
    season: int | None = None
    episode: int | None = None

def match_file(relative_path: PurePosixPath, kind: Literal["movies", "tv"]) -> list[Link]:
    """Empty when the file can't be matched."""
```

- No tag means `[]`.
- **Movies root:** `[Link(movie, id)]`.
- **TV root:** episode numbers come from guessit on the **file name** (`guessit(name, {"type":
  "episode"})`; reuse the guessit options/caching approach in
  `selection/classification.py`):
  - `season`: guessit's `season`; otherwise the nearest parent directory matching
    `^season\s*(\d+)$` (case-insensitive) or named `specials` (season 0).
  - `episode`: guessit's `episode`, an int or a list (multi-episode). One link per episode.
  - No episode number found means `[]` (unmatched; logged by the scanner). Absolute
    anime numbering and date-based episodes are out of scope.
  - Formats like `1x05` are handled by guessit. If guessit yields an episode but no
    season, and no `Season NN`/`Specials` directory exists, assume season 1.

### 4.3 File attributes

`attributes` = `dataclasses.asdict(classify_release(file_name_without_extension))` from
`driftwood.selection.classification`, made JSON-safe (tuples become lists). It's a JSON
column so the classifier can change without migrations. When the classifier changes, a
file's attributes are only refreshed when the file itself changes. That's acceptable;
a forced full re-parse can be added later.

---

## 5. Scanning (`library/scanner.py`)

```python
class Scanner:
    def __init__(self, settings: LibrarySettings, database: Database) -> None: ...
    async def scan_all(self) -> ScanReport: ...
    async def scan_path(self, absolute_path: Path) -> ScanReport:
        """Scan one file or directory inside a root (the future download hook)."""
```

### 5.1 Walking (runs in `asyncio.to_thread`)

For each root, walk with `os.scandir` (iteratively, not recursively). Do not follow
symlinked directories, to avoid loops; symlinked files are fine. Skip:

- hidden entries (name starts with `.`) and `@eaDir` / `#recycle` (NAS junk);
- directories whose lowercased name is in `ignored_dirs`;
- files whose lowercased suffix isn't in `video_extensions`;
- files smaller than `min_size_mb`;
- files whose stem ends in `-sample` / `.sample`, or is `sample` (case-insensitive).

Yield `(relative_posix_path, size, mtime_ns)`. Catch `OSError` per directory (log and
continue) so one unreadable folder doesn't abort the scan.

### 5.2 Reconciling (one transaction per root)

Load the root's existing rows (`path → (id, size, mtime_ns, state)`) in one query.

| Situation                                 | Action                                                                                  |
|-------------------------------------------|-----------------------------------------------------------------------------------------|
| on disk, not in DB                        | `match_file`; if links: insert file + links; else count as unmatched (log at DEBUG)     |
| on disk, in DB, same `size` + `mtime_ns`  | set `last_seen_at`; if `missing`: back to `present`, clear `missing_since`              |
| on disk, in DB, size or mtime changed     | re-run `match_file` and `classify_release`; replace links; if no longer matched: delete |
| in DB, not on disk, `present`             | set `missing`, `missing_since = now`                                                    |
| in DB, `missing` past `missing_grace_days`| delete (links cascade)                                                                  |

A rename or move shows up as "missing" plus "new". That's fine, since matching is
path-based.

**Unmounted-share safeguard:** if a root's `path` isn't a readable directory, or the walk
finds zero video files while the DB has `present` rows for that root, skip the
missing/delete steps for that root and log a warning. An offline NAS must never mark the
whole library as missing.

`scan_path` does the same for a subtree. It never marks files outside that subtree
missing. A path that isn't under any root raises `ValueError`.

### 5.3 Reporting

```python
@dataclass
class ScanReport:
    added: int = 0
    updated: int = 0
    missing: int = 0
    removed: int = 0
    unmatched: int = 0
    skipped_roots: list[str] = field(default_factory=list)
```

Log one INFO line per scan with these counts.

---

## 6. Service (`library/service.py`)

```python
class LibraryService:
    def __init__(self, settings: LibrarySettings, database: Database) -> None: ...

    async def run(self) -> None:
        """Full scan at startup, then every `scan_interval_minutes`. Runs forever."""

    def request_scan(self) -> bool:
        """Start a full scan in the background unless one is running. False if one is."""

    @property
    def status(self) -> LibraryStatus: ...

    async def availability(
        self, db: AsyncSession, media_type: MediaType, media_id: int
    ) -> LibraryAvailability: ...
```

- Model `run()` on `TitleIndexStore.run()` in `titles/store.py`: catch and log exceptions
  so a failed scan never kills the loop.
- Allow one scan at a time with an `asyncio.Lock`. `request_scan` and the periodic loop
  share it, and a requested scan while one is running is a no-op. Keep a reference to
  background tasks so they aren't garbage-collected.
- With no roots configured, `run()` logs once ("no library roots configured") and idles.
  Availability is always "not ready".
- `availability` makes one query: present files joined to links for
  `(media_type, media_id)`.
- Wire it in `main.py`'s `lifespan`: `app.state.library_service = LibraryService(...)`, and
  start `run()` as a task next to `index_task` with the same cancel-on-shutdown handling.
  Log a warning at startup for each root whose path doesn't exist.

---

## 7. API (`library/router.py`)

Schemas go in the router module (as `MyListStatus` does) or a `library/schemas.py`, built
on `driftwood.media.schemas.Schema`:

```python
class LibraryEpisode(Schema):
    season: int
    episode: int

class LibraryFile(Schema):
    id: int
    path: str                    # relative to its root, for display/debugging
    size: int
    resolution: str | None = None
    source: str | None = None
    codec: str | None = None
    hdr_flags: list[str] = []
    audio_codecs: list[str] = []
    episodes: list[LibraryEpisode] = []   # empty for movies

class LibraryAvailability(Schema):
    ready: bool                  # at least one present file
    files: list[LibraryFile]     # best first: resolution desc, then size desc
    episodes: list[LibraryEpisode]  # de-duplicated, sorted; empty for movies

class LibraryStatus(Schema):
    state: Literal["idle", "scanning"]
    last_scan_at: datetime | None
    files: int                   # present files
    unmatched: int               # from the last full scan
```

Routes, prefix `/library`, included in `main.py` with
`dependencies=[Depends(require_user)]` like `my_list_router`:

| Method | Path                                    | Returns               | Notes                                    |
|--------|-----------------------------------------|-----------------------|------------------------------------------|
| GET    | `/api/library/{media_type}/{media_id}`  | `LibraryAvailability` | no TMDB lookup; unknown ids are `ready: false` |
| GET    | `/api/library/status`                   | `LibraryStatus`       |                                          |
| POST   | `/api/library/scan`                     | `LibraryStatus`, 202  | starts a full scan unless one is running |

Declare `/status` and `/scan` before the `{media_type}/{media_id}` route. Validate
`media_id` with `Path(gt=0)` as the other routers do.

---

## 8. Frontend: "Ready to play"

1. With the backend running: `cd frontend && npm run openapi` regenerates
   `src/lib/api/schema.d.ts`. Never edit that file by hand. Export the new types from
   `src/lib/api/client.ts` if it re-exports schema types there (check how `MediaSummary`
   is exported).
2. `src/lib/library/library.ts`, modelled on `src/lib/my-list/my-list.ts`:
   ```ts
   /** What's on disk for a title, or null when that couldn't be checked. */
   export async function loadAvailability(media: MediaKey, fetch: typeof globalThis.fetch)
     : Promise<LibraryAvailability | null>
   ```
3. `src/routes/[type=mediatype]/[id=tmdbid]/+page.ts`: add it to the existing
   `Promise.all` next to `loadInMyList` and return it as `availability`.
4. `src/routes/[type=mediatype]/[id=tmdbid]/+page.svelte`: when `availability?.ready`,
   render a `Chip` (`#lib/components/ui/Chip.svelte`, `tone="accent"`) with the `check`
   icon (`Icon.svelte`) inside the hero, directly above the `.actions` row:
   - **Movie:** `Ready to play`, plus ` · 2160p` from `files[0].resolution` when known,
     and ` HDR` when `files[0].hdr_flags` is non-empty.
   - **TV:** `Ready to play · N of M episodes`, where N counts `episodes` with
     `season >= 1` and M is `media.number_of_episodes` (which excludes specials). Use
     `Ready to play · N episodes` when M is unknown, or `All episodes` when N ≥ M.
   - Show nothing when `availability` is null or not ready. Don't show an error state.
   Put the label logic in a small pure function (e.g. `readyLabel(media, availability)`
   in `library.ts`) so it can be unit tested if frontend tests exist, and keep the
   component itself presentational.
5. `npm run check` and `npm run lint` must pass.

The Watch button is unchanged in v1. Playing local files is a follow-up (§10).

---

## 9. Tests (`backend/tests/`)

Follow the existing style (`pytest`, async tests, `tmp_path`). For the database and
router, see `test_my_list.py` and `test_auth.py` (`make_app`, `sign_in`, `FakeIdp`, a
`Database` on a temporary SQLite file with `migrate()`).

- **`test_library_tags.py`:** table-driven `find_tmdb_id`. All bracket variants and
  casing; the tag on the file vs. the directory vs. both (nearest wins); no tag; `tmdbid-0`;
  an `imdbid-…`/`tvdbid-…` tag alone gives none.
- **`test_library_matching.py`:**
  - movie in a movies root;
  - TV episode with a `Season 01` directory;
  - season from the file name only;
  - multi-episode `S01E01E02` gives two links;
  - `Specials/…S00E03` gives season 0;
  - a TV file without an episode number gives `[]`;
  - the same tag in a movies root vs. a TV root gives different `media_type`.
- **`test_library_scanner.py`** builds trees under `tmp_path`. Make "video" files by
  writing small files and setting `min_size_mb=0` in the test settings; the size filter
  gets its own test.
  - first scan adds; a second scan changes nothing (idempotent);
  - a touched (mtime-changed) file is re-parsed;
  - a renamed file that loses its tag is deleted;
  - a deleted file becomes `missing`, comes back `present` when restored, and is removed
    after the grace period (inject a clock or pass `now` to make this testable);
  - samples, `Extras/`, hidden files and non-video extensions are ignored;
  - **safeguard:** a root path that doesn't exist, and a root that's suddenly empty, mark
    nothing missing;
  - `scan_path` on a subtree doesn't touch files outside it.
- **`test_library_api.py`:**
  - availability for a movie;
  - availability for TV (episodes de-duplicated and sorted);
  - a missing file doesn't count as ready;
  - unknown title gives `ready: false`;
  - unauthenticated requests get 401;
  - `POST /scan` returns 202.

Run with `cd backend && uv run pytest` (`asyncio_mode = "auto"`, so no async markers are
needed), then `uv run ruff check . && uv run ruff format --check .`. The frontend has no
test runner, so its checks are `npm run check` and `npm run lint`.

---

## 10. Out of scope / follow-ups

- Watch plays the local file when the title is ready, skipping the indexer search.
- A "Ready to play" badge on `MediaCard` in home rows and search, via a bulk availability
  endpoint.
- ffprobe into `probe` (real audio and subtitle tracks, duration), so the subtitle
  preference can be checked against local files too.
- Sidecar subtitle files (`.srt`, `.ass`) next to videos.
- The download pipeline: it calls `Scanner.scan_path` after moving a finished,
  tag-named file into a root.
- Filesystem watching for local (non-network) roots.
