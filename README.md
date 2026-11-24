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

## Development

```sh
cd backend && uv run pytest && uv run ruff check . && uv run ruff format --check .
cd frontend && npm run check && npm run lint
cd frontend && npm run openapi   # regenerate API types (backend must be running)
```

Theme colors, spacing and type live in `frontend/src/lib/styles/tokens.css`.
Shift `--hue-base` / `--hue-accent` to retune the whole palette.
