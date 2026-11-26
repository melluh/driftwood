# Driftwood

A media interface: search any movie or TV series and view its details. Metadata and images come from [TMDB](https://www.themoviedb.org/).

```
backend/    Python 3.13 + FastAPI (uv)
frontend/   SvelteKit 3 + Svelte 5 (SPA, adapter-static)
docs/       Design notes
```

## Running locally

```sh
# Backend: http://localhost:8000 (API under /api, docs at /docs)
cd backend
cp .env.example .env          # then set the TMDB key and OIDC provider (see Sign-in)
uv run fastapi dev src/driftwood/main.py

# Frontend: http://localhost:5173 (proxies /api to the backend)
cd frontend
npm install
npm run dev
```

On first start the backend downloads TMDB's daily title exports (~30 MB compressed) and builds the
search index, which takes about a minute. Until then `/api/search/status` reports `building`.
The index refreshes daily.

## Sign-in

Everything requires signing in through an OpenID Connect provider (Google, Authentik, Keycloak,
Pocket ID, ...). Register an OAuth client with the provider using the redirect URI
`<public_url>/api/auth/callback` (`http://localhost:5173/api/auth/callback` in development) and set
the `DRIFTWOOD_AUTH__*` variables from `backend/.env.example`.

- The backend runs the authorization code flow with PKCE (Authlib verifies the ID token), then
  creates a server-side session: an HttpOnly cookie holding a random token, stored hashed in the
  `sessions` table. Sessions slide: 30 days from last use.
- Every `/api` route except `/api/auth/*` returns 401 without a session; the frontend's root layout
  sends signed-out visitors to `/login?next=...`. The one public data endpoint is
  `/api/auth/backdrop`: bare TMDB poster paths of popular titles for the login screen's poster wall.
- Users are keyed by (issuer, `sub`) in the `users` table, profile refreshed on each sign-in.

The database is SQLite at `backend/data/driftwood.db` by default (`DRIFTWOOD_DATABASE__URL`).
Migrations live in `backend/src/driftwood/db/migrations` and run automatically on startup; create a
new one after changing `db/models.py` with
`cd backend && uv run alembic revision --autogenerate -m "describe the change"`.

## Search

Search is instant (no submit step) and served from a local index of all ~1.5M TMDB movie and TV
titles, built from TMDB's daily ID exports. The ranking is ported from MediaManager's autocomplete:

- **Head** (the 150k most popular titles) gets full matching: title prefixes (skipping a leading
  "the/a/an"), acronyms (`lotr`), and typo tolerance (`matrx`).
- **Tail** (everything else) is matched by prefix and acronym only, using binary search over packed
  sorted arrays. Obscure titles surface once the query is specific enough, while popular titles
  still rank first.

The top results are then hydrated with TMDB details (localized title, year, poster) through a
shared in-memory cache that the details page also uses. Images are loaded straight from TMDB's
CDN, with a `srcset` sized to each slot.

Known limitation: TMDB's exports carry only *original* titles, so a translated title (for example
"Spirited Away" for 千と千尋の神隠し) doesn't match yet.

Benchmark the index against the real export with `uv run python scripts/bench_index.py`.

## Torrent indexers

`backend/src/driftwood/indexers/` searches torrent indexers behind one interface
(`SearchQuery` → `list[Release]`), following [docs/indexer-design.md](docs/indexer-design.md).
TorrentLeech is the first one. Enable it in `backend/.env`:

```sh
DRIFTWOOD_INDEXERS__TORRENTLEECH__USERNAME=...
DRIFTWOOD_INDEXERS__TORRENTLEECH__PASSWORD=...
# DRIFTWOOD_INDEXERS__TORRENTLEECH__ALT_2FA_TOKEN=...   # if 2FA is on (Site Profile → Alt 2FA Token)
# DRIFTWOOD_INDEXERS__TORRENTLEECH__TIMEZONE=Europe/Amsterdam   # your TL profile's timezone
```

Set "Torrents per page" to 100 in your TorrentLeech profile; results aren't paginated. Session
cookies are kept in `backend/data/indexers/` so restarts don't log in again. Requests are spaced
1 s apart (Prowlarr uses 4.1 s) and look like Firefox 140: its user agent, full header set and
order, Sec-Fetch-* and Referer as a browser tab would send them, HTTP/2, and gzip/brotli/zstd. The
TLS handshake is still Python's. `GET /api/media/{type}/{id}/releases` searches every enabled indexer for a
title (movies by IMDb id, series by title); each media page has a debug "Find torrents" button
that calls it.

## Watch: picking a release

The Watch button opens a full-screen watch view at `/{movie|tv}/{id}/watch`. It searches the
indexers (`GET /api/media/{type}/{id}/watch`) and shows the release it would grab. Nothing is
downloaded yet.

Selection (`backend/src/driftwood/selection/`) is ported from MediaManager's slot scoring:

- Release names are parsed with guessit into resolution, source, codec, HDR, audio, language and
  group. Cams, telesyncs and screeners, dubbed or multi-language releases, releases with fewer than
  3 seeders, and releases whose bitrate (size / TMDB runtime) falls outside their slot's range are
  dropped.
- Each release goes into the first matching quality **slot**: 4K Remux, 4K Encode, 1080p Remux,
  1080p Encode, 720p. Scores only compare releases within a slot, using that slot's weights:
  - **Speed** slots (1080p Encode, 720p: the ones Watch grabs from) favour starting to watch soon.
    Size scores up to 400: full points at the slot's target bitrate, falling linearly to 0 at its
    minimum (quality loss) and its maximum (longer download). Seeders score `40 × log2(seeders)`,
    up to 200 (reached at 32). Source matters less: WEB-DL and Blu-ray encode 300, WEBRip 200,
    HDTV 50, DVD 0.
  - **Quality** slots (4K and Remux: manual upgrades) keep MediaManager's scale, where source
    dominates (WEB-DL 1000, Remux 950, Blu-ray 900, WEBRip 700, …), size scores up to 100 and
    seeders up to 60.
  - Both add codec (AV1 150, HEVC 120, H.264 50), HDR (off by default,
    `DRIFTWOOD_SELECTION__HDR_LADDER__ENABLED=true` turns it on; Dolby Vision without an HDR10
    fallback always loses 20) and audio as a tiebreak. Weights are configurable
    (`speed_weights`, `quality_weights`).
  - Freeleech adds 300 (`freeleech_bonus`; partial freeleech earns its share). That beats source,
    codec and seeder differences, and a freeleech file up to about twice the target size, but not
    one further off, nor missing or unconfirmed subtitles (−1000).
- Watch grabs the best **1080p Encode**. Its range is 4–6–15 Mbps as H.264: 6 Mbps is about
  4.2 GB for a 97-minute film and 5.4 GB for two hours; below 4 Mbps (~2.8 GB / 97 min) is rejected.
  HEVC and AV1 count as H.264-equivalent (×1.4 and ×1.6, `codec_efficiency`), so a 2.4 GB HEVC
  encode counts as ~5 Mbps. If there's no 1080p release, Watch falls back to 720p, then 4K Encode,
  1080p Remux and 4K Remux. The other slots' best releases are shown as manual upgrades.
- Series watch a single episode (`?season=&episode=`, default S01E01).
- **Subtitles** are checked against the release's NFO (TorrentLeech:
  `nfo/download/{id}`). It reads MediaInfo dumps (`Text #n` sections) and scene-style
  `Subtitles: English, Dutch` lines. A release whose NFO lists no wanted language (forced tracks
  don't count) loses 1000 points within its slot. So does one with no NFO, an NFO that doesn't
  mention subtitles, or only untagged tracks: unconfirmed counts as missing
  (`unknown_subtitles_penalty` can set it apart). Wanted subtitles add 25. If the best release of the 1080p slot turns out to have no wanted
  subtitles, Watch moves on to the next slot's best release.
- NFOs are fetched one at a time and only for the release about to be picked: the pick, and the
  next one if the pick is demoted, up to 5 per Watch. Each is an indexer request, 1 s apart on
  TorrentLeech. NFOs are cached for a day. `GET /api/releases/{indexer}/{guid}/nfo` returns an NFO
  and what was read from it; the watch screen shows it under "NFO".

Slots, the watch order, release group tiers, the HDR ladder, the wanted subtitle languages and
the penalties are configurable under `DRIFTWOOD_SELECTION__*` (see `selection/config.py`), e.g.
`DRIFTWOOD_SELECTION__SUBTITLE_LANGUAGES='["en", "nl"]'`. Names and ISO codes both work; an empty
list turns subtitle checks off.

## Library

Driftwood scans shared media roots and marks a title **Ready to play** when a matching file is present. Configure `DRIFTWOOD_LIBRARY__ROOTS` in `backend/.env` as a JSON list of roots, each with a unique `name`, an absolute `path`, and a `kind` of `movies` or `tv`. Example:

```sh
DRIFTWOOD_LIBRARY__ROOTS='[{"name":"movies","path":"/srv/movies","kind":"movies"},{"name":"tv","path":"/srv/tv","kind":"tv"}]'
```

Include a TMDB tag such as `[tmdbid-438631]`, `[tmdbid=438631]`, `[tmdb-438631]`, or `{tmdb-438631}` in the filename or a parent directory. TV filenames also need a season/episode pattern guessit recognises (such as `S01E02`); `Season 01` and `Specials` directories provide a fallback season. The scanner runs at startup and periodically, and a signed-in client can request a scan through `/api/library/scan`.

### Playing from the library

**Watch** plays the library's copy when there is one, and falls back to the release search when there isn't, or when no copy can play in the browser (the search page then says why). Install `ffmpeg` and `ffprobe` on the backend host.

Video is never re-encoded, so a copy plays only when the browser can decode its video: 8-bit H.264 everywhere, HEVC where the browser reports support for it (10-bit HEVC and Dolby Vision profile 5 are checked separately). MP4 files with H.264 and AAC are served as they are, with byte ranges for seeking. Everything else streams as HLS: a complete VOD playlist is built up front from the video's keyframes (read from the Matroska cue index, or a one-off packet scan cached in the database), and segments are copied out on demand, so the full duration is known and seeking anywhere works straight away. Each audio track is its own rendition, copied when it's AAC and encoded to AAC otherwise. ffmpeg runs a minute or so ahead of the player, is paused (SIGSTOP) beyond that, and is stopped when the player closes or stops fetching.

Text subtitles (SRT, ASS, WebVTT, mov_text) are extracted once per file in a single pass and cached; ASS tracks are drawn with their styling and embedded fonts by JASSUB, with a plain-text fallback. Image-based subtitles (PGS, VobSub) aren't shown, since that would need re-encoding the video.

Seek-bar thumbnails come from trickplay images Jellyfin already made, when it was set to save them next to the media (`<video name>.trickplay/320 - 10x10/0.jpg`, ...). Jellyfin doesn't record the interval on disk, so Driftwood assumes its default of 10 seconds (`DRIFTWOOD_PLAYBACK__TRICKPLAY_INTERVAL_SECONDS`) and ignores sheets whose count doesn't fit the video's duration at that interval.

Segments and extracted subtitles live in `DRIFTWOOD_PLAYBACK__DIRECTORY` (default: `driftwood-playback` in the system temp directory). Budget a few hundred MB per active stream (more for 4K remuxes), and prefer a disk-backed directory if `/tmp` is a RAM-backed tmpfs.

## Development

```sh
cd backend && uv run pytest && uv run ruff check . && uv run ruff format --check .
cd frontend && npm run check && npm run lint
cd frontend && npm run openapi   # regenerate API types (backend must be running)
```

Theme colors, spacing and type live in `frontend/src/lib/styles/tokens.css`.
Shift `--hue-base` / `--hue-accent` to retune the whole palette.
