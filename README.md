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
cp .env.example .env          # then set DRIFTWOOD_TMDB__API_KEY (TMDB v3 key)
uv run fastapi dev src/driftwood/main.py

# Frontend: http://localhost:5173 (proxies /api to the backend)
cd frontend
npm install
npm run dev
```

On first start the backend downloads TMDB's daily title exports (~30 MB compressed) and builds the
search index, which takes about a minute. Until then `/api/search/status` reports `building`.
The index refreshes daily.

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

## Development

```sh
cd backend && uv run pytest && uv run ruff check . && uv run ruff format --check .
cd frontend && npm run check && npm run lint
cd frontend && npm run openapi   # regenerate API types (backend must be running)
```

Theme colors, spacing and type live in `frontend/src/lib/styles/tokens.css`.
Shift `--hue-base` / `--hue-accent` to retune the whole palette.
