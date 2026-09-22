# Gallery on a chosen scenario — phase A manifest (2026-09-20)

Backend: the §5.4a per-scenario projection, written with every publish and
refresh, read by `POST /api/proposals` when a `scenario_variant_id` is
requested. Plan: `docs/2026-09-20_gallery_scenario_plan.md` (§6 has the
as-built deviations). **Backend 0.5.0 → 0.5.1. No `ROUTE_BUILDER_VERSION`,
`CALC_VERSION` or `FAMILY_DOCUMENT_FORMAT` change** — nothing existing
changes value or shape. One additive migration.

## Files touched

### Schema

- `backend/db/dev/sql/create_proposal_schema.sql` — new table
  `proposals.proposal_scenario_summaries` (§5.4 KPI columns nullable,
  `status`/`error_code`, `geom_simplified`, `segments` JSONB, PK
  `(proposal_id, scenario_variant_id)`, FK cascade from `proposals`), two
  indexes, column comments.
- `backend/db/dev/sql/migrations/2026-09-20_proposal_scenario_summaries.sql`
  — the same, `IF NOT EXISTS`, with the deploy-order note.

### Projection and compute

- `backend/adapters/proposal/projection.py` — `corridor_key()` and
  `corridor_segments(route)`: the route's per-segment shapes keyed by the
  direction-collapsed stop pair, the `segments` column.
- `backend/api/helpers/family_compute.py` — `family_request_from_echo()`
  factored out of `build_or_load_family()` and reused (one construction of
  `FamilyRequest`, not two).
- `backend/api/helpers/scenario_summaries.py` (new) —
  `compute_scenario_rows(compute_request)`: one-composition family across
  every current variant on a shared `FamilyContext`; ok members projected
  through `build_summary_db_row()` + `corridor_segments()`, error members
  kept as error rows with their classified code. Suggestions forced off.

### Repository

- `backend/adapters/proposal/repository.py`
  - write: `_write_state()` takes `scenario_rows` and calls
    `_replace_scenario_summaries()` (delete-then-insert, in the publish /
    refresh transaction); `publish()` and `refresh_proposal()` gain the
    `scenario_rows=None` argument (None = the caller could not compute them —
    the seed — and clears the rows); `replace_scenario_summaries()` and
    `list_scenario_backfill()` for the script.
  - read: `_gallery_cte()` → `_gallery_ctes(filters, scenario_variant_id)`:
    engagement CTE + gallery in one, the proposal side read from
    `_SCENARIO_ENGAGEMENT_CTE` (joined to the container for identity, name,
    timestamps) when a variant is given. Both union branches now carry
    `status`, `error_code`, `scenario_variant_id`. `list_summaries`,
    `map_routes`, `map_lines`, `map_stop_counts`, `map_country_counts` take
    the variant; `map_lines` has a JSON-corridor branch
    (`jsonb_each(segments)`, representative geometry fetched by proposal id
    - key, still outside the grouping aggregate). Stats stay base.
  - `_SCENARIO_METRIC_COLUMNS` lists the KPI columns once for the insert and
    the variant CTE.

### API

- `backend/api/helpers/proposal_serialize.py` — `validate_list_body()`
  accepts a positive-int top-level `scenario_variant_id`;
  `summary_row_to_dict()` adds `status`, `error_code`, `scenario_variant_id`
  and is null-safe on the array columns.
- `backend/api/proposals.py` — passes the variant to every section, echoes
  it as `summaries.scenario_variant_id`, 400 `unknown_scenario_variant` for
  an id that is not a current scenario's variant (`_is_current_variant()`).
- `backend/api/helpers/publish_dispatch.py`,
  `backend/api/helpers/proposal_load.py` — compute the rows from the
  resolved echo (`computed["request"]`) and pass them to publish / refresh.

### Script

- `backend/scripts/refresh_proposals.py` — refresh writes the rows too;
  new `--scenario-summaries` backfill mode (`run_scenario_backfill()`,
  `list_scenario_backfill()` queue, `replace_scenario_summaries()` write,
  same `--dry-run` / `--limit` / `--concurrency`); host env defaults factored
  into `_host_env_defaults()`.

### Version

- `backend/pyproject.toml` — 0.5.0 → 0.5.1. If `uv.lock` is tracked in the
  repo (it is not in the snapshot), run `uv lock` after extracting so the
  root package version in the lock matches.

### Tests

- `backend/tests/test_56_proposal_scenario_summaries.py` (new, 10 cases):
  one row per current variant on publish; base row equals
  `proposal_summaries`; the HSR variant is its own computation; corridor
  keys direction-collapsed; overwrite replaces the rows (composition and
  version); backfill queue empty after a publish; default gallery
  unchanged (`status: "ok"`, null variant); gallery on the HSR variant
  returns that row's figures, `map_routes` geometry and `map_lines`
  corridors; an error variant lists the row without figures (skipped on a
  stack that computes every variant); unknown / non-integer variant → 400.

### Docs

- `backend/adapters/proposal/README.md` — §5.4a (new), §4.2 and §7.1
  updated, modules table.
- `backend/api/README.md` — `POST /api/proposals` contract: the field, the
  three row fields, the errors.
- `backend/db/README.md` — table row and migration entry.
- `docs/DEPLOY_HANDOVER.md` §21 — deploy order (migration → api →
  backfill), what a deployment without 2032 stores, publish-cost watch.
- `docs/FRONTEND_HANDOVER.md` §24 — the request field and the `api.ts`
  changes phase C will need.
- `docs/2026-09-20_gallery_scenario_plan.md` — decisions recorded, phase B
  cheap path spelled out, §6 as-built deviations.

## Gates

| Gate                                        | Result                                          |
| ------------------------------------------- | ----------------------------------------------- |
| `ruff format --check` (touched files)       | clean                                           |
| `ruff check` (adapters, api, scripts, test) | clean                                           |
| `ast.parse` on every touched module         | clean                                           |
| Integration tests                           | **not run here** — needs the live stack (below) |

## Your run

1. Extract, delete the zip.
2. Fresh stack so the seed creates the table:
   `cd backend/docker && docker compose down -v && docker compose up -d --build`
   (an existing dev database can instead apply the migration file).
3. `uv run pytest tests/test_56_proposal_scenario_summaries.py -v`, then
   the full suite — `test_50`/`test_52`/`test_53`/`test_55` exercise the
   default path and the refresh script and are the ones most likely to
   notice a regression on the base CTE.
4. Time one publish before and after (request log, or the test's own
   duration) — this is the number decision 2 and the phase-B cheap path
   rest on.
5. `uv run --extra dev python -m scripts.refresh_proposals --scenario-summaries --dry-run`
   should list exactly the seed example (published without a router).

Phase B (builder debounced save) and phase C (gallery panel) follow once
this is green on your stack.
