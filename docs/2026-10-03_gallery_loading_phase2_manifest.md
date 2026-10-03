# Gallery loading — phase 2: precomputed corridors + the data-task runner (2026-10-03)

Branch `fix-gallery-loading`. Backend 0.5.11, migration
`2026-10-03_proposal_corridors.sql`, one data task. No frontend change.

## Why

After phase 1 the cards render in a second, but the corridor overview
(`map_lines`) still took 31 s on production: every request walked all 28k
segments and parsed one full-resolution shape per corridor. And the fix
needs a backfill on databases with existing data — which the deploy had no
place for: `migrate` runs SQL only, and bulk data work (refreshes after
version bumps, backfills) was a hand-run script.

## What changes

1. **`proposals.proposal_corridors`** (adapters/proposal/README.md §5.4b): one
   row per (proposal, scenario variant | NULL = base, direction-collapsed
   stop pair), geometry simplified at write time, `geometry_routed` measured
   before simplification. Written in the same transaction as every publish
   and refresh (`_write_state()` → `_replace_corridors()`) and whenever the
   §5.4a rows are replaced. The derivation is pure SQL over stored data, so
   publish, refresh and backfill are one code path.
2. **`map_lines` reads the table**; while any proposal lacks rows
   (`list_corridor_gaps()` non-empty — the window before the backfill) it
   answers from `_map_lines_derived()`, the old query kept verbatim. Correct
   throughout, only slow until the task has run. Delete the fallback once
   staging and production show the task done.
3. **Data tasks — `db/run_tasks.py` + `db/tasks/`**: the batch half of the
   database pipeline, next to `db/migrate.py`. Python task files, filename
   order, recorded per attempt in `admin.data_task_runs`, pending until a run
   is `done`, refuse to start with migrations pending, stop at the first
   failure. `--list / --dry-run / --check / --run FILE / --baseline`. Tasks
   are idempotent and resumable by contract; the recipe for "re-project every
   proposal after a version bump" is in db/README.md.
4. **Deploy wiring**: new one-shot `data-tasks` in
   `deploy/coolify/app.docker-compose.yml` — after `migrate`, beside the api,
   on `tn-shared` with the routing URLs so refresh-type tasks work too. Dev
   stacks: `docker/entrypoint.sh` runs `migrate.py --baseline` after the seed
   (a fresh seed is every migration; the runner insists on that record) and
   the runner in the background.
5. **First task**: `2026-10-03_backfill_proposal_corridors.py` —
   `rebuild_corridors()` for every proposal on the gap queue. No routing
   engine, about a minute for a thousand proposals.

## Files

- `backend/db/dev/sql/migrations/2026-10-03_proposal_corridors.sql` — new
  table + index + comments (`UNIQUE NULLS NOT DISTINCT` keeps the base rows
  unique; PostGIS 16 everywhere).
- `backend/db/dev/sql/create_proposal_schema.sql` — the same table for fresh
  seeds.
- `backend/adapters/proposal/repository.py` — `_CORRIDOR_INSERT` +
  base/variant sources, `_replace_corridors()`, `_CORRIDOR_GAPS_SQL`,
  `list_corridor_gaps()`, `rebuild_corridors()`, `_corridors_complete()`;
  `map_lines()` rewritten on the table, old body kept as
  `_map_lines_derived()`; `_write_state()` and `replace_scenario_summaries()`
  call `_replace_corridors()`.
- `backend/db/run_tasks.py` — the runner (new).
- `backend/db/tasks/2026-10-03_backfill_proposal_corridors.py` — the task (new).
- `backend/docker/entrypoint.sh` — `migrate.py --baseline`, runner in background.
- `deploy/coolify/app.docker-compose.yml` — `data-tasks` one-shot.
- `deploy/coolify/README.md` — first-seed `--baseline` for tasks, one-shot list.
- `backend/tests/test_57_proposal_corridors.py` — six tests (new); `tests/README.md` entry.
- `backend/pyproject.toml` — 0.5.10 → 0.5.11 (`uv lock` moves `uv.lock`).
- `backend/db/README.md` — "Data tasks" section, migration list, table row.
- `backend/adapters/proposal/README.md` — §5.4b, §7.1 map_lines note.
- `backend/api/README.md` — map_lines note.
- `docs/DEPLOY_HANDOVER.md` — §23 (and §22's closing line).

## Gates

`ruff format` + `ruff check` on every touched Python file: clean. Backend
integration tests NOT run here (Docker stack) — test_57 is new, test_52 and
test_56 exercise `map_lines` on both paths.

## Your run

```powershell
cd backend; uv lock; uv run ruff format; uv run ruff check; cd ..
docker-compose -f backend\docker\docker-compose.yml -f .devcontainer\docker-compose.yml up --build --force-recreate -d
```

Watch the api log for `Recording migrations as applied` and
`run_tasks.py: … 2026-10-03_backfill_proposal_corridors.py` (a no-op on a
fresh seed). Then:

```powershell
cd backend; uv run pytest tests/test_57_proposal_corridors.py tests/test_56_proposal_scenario_summaries.py tests/test_52_proposals_gallery_api.py -q; cd ..
```

To see the fallback and the backfill on your stack by hand: delete the rows
in pgAdmin (`DELETE FROM proposals.proposal_corridors;`), open the gallery —
the api log says `proposal_corridors incomplete — deriving at request time`
and the map still fills — then

```powershell
docker exec night-train-api python db/run_tasks.py --list
docker exec night-train-api python db/run_tasks.py --run 2026-10-03_backfill_proposal_corridors.py
docker exec night-train-api python db/run_tasks.py --list
```

Then the timing loop from the phase-1 manifest against your local API with
`include: ["map_lines"]` and no filter.
