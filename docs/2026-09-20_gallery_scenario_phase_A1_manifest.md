# Gallery on a chosen scenario — phase A.1 manifest (2026-09-20)

Publish-cost fix for phase A, on the numbers measured on David's stack.
**Backend 0.5.1 → 0.5.2. No schema change, no migration, no API change** —
the rows, the endpoint and the response are exactly phase A's.

## What the measurement said

| Measured (dev stack, warm)               | 0.5.1                             |
| ---------------------------------------- | --------------------------------- |
| `POST /api/proposal/publish` (overwrite) | 2.5–2.8 s                         |
| `compute_scenario_rows()` alone, 3 runs  | 1.74–1.88 s                       |
| rows produced                            | 4 ok / 8 (no Infra 2032 instance) |

The 1.8 s did not fall across repeated runs, so it was not routing (those
legs are in `route_cache`). It was a catalog load per scenario on a fresh
`FamilyContext` — including the four Infra 2032 variants, which cannot
compute on that stack at all: `FamilyContext.prewarm()` loads tracks,
stops, passages and compositions _before_ it asks for the router, so half
the work was thrown away.

## The two fixes

1. **Unservable variants short-circuit.** The router registry is a dict
   keyed by `routing_graph_key`; one lookup per distinct graph decides
   every variant on it. Those become `routing_graph_not_configured` error
   rows with nothing loaded.
2. **The publish reads the builder's family document.** After an Evaluate
   or Recalculate, `family.documents` holds the default family for exactly
   these stops and HOW fields, and every member carries the §5.4 summary
   this projection rebuilds plus a compact route and the geometry pool. On
   a key hit the rows are a lookup plus the geometry work — no routing, no
   catalogs, no evaluation. A miss (refresh script, swept TTL, version
   bump) falls back to the phase-A build.

Both paths produce identical rows by construction: the document's summary
_is_ `build_summary_row()`'s output, and the full-route and compact-route
geometry helpers share one simplification.

## Files touched

### `backend/adapters/proposal/projection.py`

- `trip_coordinate_lists(route)` and `_simplified_multiline(lines)` split
  out of `_geom_simplified()` (no behaviour change).
- `compact_route_geometry(compact_route, geometry_pool)` → `(geom_simplified,
corridor segments)` for a family document's compact route, which keys
  segments by `from`/`to` indices into the trip's `stops` and moves
  coordinates into the shared pool.

### `backend/api/helpers/scenario_summaries.py`

- `compute_scenario_rows()` restructured into three steps:
  `_split_by_routing_graph()` → `_rows_from_document()` →
  `_rows_from_build()`, with `_row()` as the single row shape.
- `SCENARIO_ROW_SOURCE` module-level marker (`"document"` / `"build"` /
  `"unavailable"`) for the tests and one INFO log line per call, so the
  deploy can see which path ran.
- The family key for the document lookup uses the DEFAULT axes (every
  current variant × the whole catalog) — what the builder posts.

### `backend/tests/test_56_proposal_scenario_summaries.py`

Two cases added (12 total):

- `test_unservable_variants_short_circuit` — every variant is either
  servable or error-coded, and a graph is never both.
- `test_document_and_build_paths_agree` — the rows from the document and
  the rows from a build (document cache flushed) match on status, error
  code, every compared KPI, the corridor key set and `geom_simplified`.
  Skips if no document existed for the request.

### Version and docs

- `backend/pyproject.toml` — 0.5.2.
- `backend/adapters/proposal/README.md` §5.4a — "How a row is made"
  rewritten as the three steps, with the measurement that motivated them.
- `docs/DEPLOY_HANDOVER.md` §21 — version, and the publish-cost paragraph
  replaced with the measured numbers, the fix and what to watch.
- `docs/FRONTEND_HANDOVER.md` §24 — version only.

## Gates

`ruff format --check` and `ruff check` clean on every touched file.
Integration tests not run here — they need the live stack.

## Your run

1. Extract, delete the zip, rebuild the api image:
   `docker compose -f backend\\docker\\docker-compose.yml up -d --build api`
2. `uv run pytest tests/test_56_proposal_scenario_summaries.py -v`
3. Re-run the timing from step 3.3 (three overwrites after one Evaluate-
   style family) and 3.4. Expect the publish back near its pre-phase-A
   cost on the document path, and the isolated `compute_scenario_rows()`
   in the tens of milliseconds when a document is present; the build path
   (cache flushed) should still drop noticeably, since the 2032 variants
   no longer load catalogs.
4. `docker logs night-train-api | Select-String "scenario rows"` shows
   which path each publish took.

If 3 lands where it should, phase B is a plain debounced publish-overwrite
and I start on it.
