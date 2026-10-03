# Gallery loading — phase 1: cards first, thinner geometry (2026-10-03)

Branch `fix-gallery-loading`. Backend 0.5.10, no migration.

## Why

The unfiltered gallery timed out on production. Measured 2026-10-03 against
https://targetnetwork.back-on-track.eu (1,334 proposals, 205 existing,
28,372 segments, 1,518 ONTD corridors), one section per request:

| Section      | Time   | Body     |
| ------------ | ------ | -------- |
| `summaries`  | 0.4 s  | 39 KB    |
| `map_routes` | 6.1 s  | 4.3 MB   |
| `map_lines`  | 31.4 s | 8.8 MB   |

The gallery asked for all three in ONE request on the 15 s interactive
budget, so it failed before any card rendered. Filtered queries stayed under
the deadline, which is why only they worked.

## What changes

1. **Cards first.** `Gallery.vue` sends `summaries` + `map_routes` per page
   and the corridor overview (`map_lines`) as its own request per query, on
   the `heavy` budget (no deadline, cancellable). The map shows a
   "Loading map…" chip, or "The map couldn't be loaded. Try again" on failure;
   the card column never waits for it. A sort-only change reloads the cards
   and keeps the corridors.
2. **Thinner card routes.** `map_routes` simplifies the stored
   `geom_simplified` once more on read (`MAP_ROUTES_SIMPLIFY_TOLERANCE_DEG`
   = 0.002°, ≈200 m, `preserveCollapsed` so short routes survive).
3. **5 decimals.** `map_lines` and `map_routes` write coordinates with
   `ST_AsGeoJSON(…, 5)` (`GALLERY_GEOJSON_DECIMALS`, ≈1 m) instead of the
   default 9.
4. **Interrupted loads resume.** Leaving the gallery while its first page or
   the corridors are in flight used to cancel them silently and come back to
   an empty column (no skeleton, no count, no retry). The teardown now
   remembers what it cancelled and `onActivated` resumes exactly that.

Not in this phase: `map_lines` is still the 31 s query, now off the critical
path. Phase 2 replaces it with a precomputed per-variant corridor table.

## Files

- `backend/adapters/proposal/repository.py` — `MAP_ROUTES_SIMPLIFY_TOLERANCE_DEG`,
  `GALLERY_GEOJSON_DECIMALS`; `map_routes()` simplifies + rounds on read
  (its two SELECT-list params precede the WHERE params); `map_lines()`
  rounds to 5 decimals.
- `backend/tests/test_52_proposals_gallery_api.py` —
  `test_map_geometry_is_thinned_for_the_wire` (≤ 5 decimals in both
  sections), `_coordinates()` helper.
- `backend/pyproject.toml` — 0.5.9 → 0.5.10.
- `backend/api/README.md`, `backend/adapters/proposal/README.md` — wire
  thinning and the separate `map_lines` request.
- `frontend/src/lib/proposalsApi.ts` — `fetchMapCorridors()` (`heavy` budget).
- `frontend/src/components/Gallery.vue` — `PAGE_SECTIONS` (one constant for
  every page), `queryScope()` shared by list and corridors, `loadCorridors()`
  with its own abort slot + sequence, `resetAndLoad({ corridors })`, the
  query watcher tells sort-only changes apart, interrupted-load resume.
- `frontend/src/components/GalleryMap.vue` — `corridorsStatus` prop, status
  chip with retry (`retry-corridors` event); late-arriving corridors no
  longer drop a hovered card's isolated route.
- `frontend/src/i18n/locales/en.json`, `de.json` — `gallery.map.loading`,
  `gallery.map.failed`.
- `frontend/README.md` — "Two requests per query".
- `docs/DEPLOY_HANDOVER.md` §22, `docs/FRONTEND_HANDOVER.md` §25.

## Gates

Frontend (run here): eslint, prettier, vue-tsc, vitest 383/383, `vite build`
— green. Backend: `ruff format` clean; integration tests NOT run here (need
the Docker stack).

## Your run

```powershell
cd backend; uv lock; uv run ruff format; uv run ruff check; uv run pytest tests/test_52_proposals_gallery_api.py tests/test_56_proposal_scenario_summaries.py -q; cd ..
cd frontend; npm run ci; npm run build; cd ..
```

`uv lock` only moves the project's own version line to 0.5.10 — commit
`backend/uv.lock` with the rest.

Then locally (devcontainer, port 5050), with the network tab open on
`/gallery`: two `POST /api/proposals` per cold load — one with
`["summaries","map_routes"]` (cards appear when it lands) and one with
`["map_lines"]` (map fills in). The timing loop from the diagnosis, against
local or staging after deploy, should show `map_routes` well under 1 s and
a few hundred KB.
