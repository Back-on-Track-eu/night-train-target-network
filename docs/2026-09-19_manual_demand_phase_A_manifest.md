# Manual demand inputs — Phase A delivery manifest

Date: 2026-09-19 · Guide: `docs/2026-09-18_manual_demand_guide.md` §6 Phase A ·
Scope: **Schedule — one frequency on the wire, the month grid underneath (backend).**

Decisions applied (David, 2026-09-19): the backend keeps
`Schedule.days_per_week_by_month` so a seasonal plan can return without a
domain change; the request posts one frequency; the new default is 3 days a
week; the two-season projection goes; every data change runs through
`db/migrate.py`.

## What changed

| # | File | Change |
|---|---|---|
| 1 | `backend/models/route/model.py` | `ROUTE_BUILDER_VERSION` 0.9.39 → **0.9.40** with changelog. `DEFAULT_SCHEDULE_MODE` replaced by `DEFAULT_DAYS_PER_WEEK = 3` (STANDARD VALUE, documented). Dead `WEEKS_PER_SEASON`, `DAYS_PER_OPERATING_WEEK` removed. |
| 2 | `backend/models/route/timetable.py` | `always_daily_schedule`, `custom_schedule`, `legacy_seasonal_schedules`, `VALID_SCHEDULE_MODES` removed. New `flat_schedule(days_per_week, turnaround)`; `schedule_from_dict()` reads the month map only. Module docstring: the schedule is no longer a mode switch. |
| 3 | `backend/models/route/route_factory.py` | `plan_route(schedule: dict, …)` takes the resolved month map (required) and builds the one `Schedule`; the `schedule_mode` switch and its error branches are gone. Docstrings updated. |
| 4 | `backend/models/route/route.py` | Docstrings only: fleet rule in days-per-week terms, pointer to `model.py`. Domain unchanged. |
| 5 | `backend/api/helpers/member_compute.py` | `validate_schedule(schedule)`: absent, `{"days_per_week": 1..7}` or a full month map (`'1'..'12'`, 0..7, ≥ 1 running). `normalize_schedule(schedule)` always returns the twelve-month map with string keys (default `DEFAULT_DAYS_PER_WEEK` everywhere). `schedule_mode` in a body is a 400 with a pointer to the new shape. Echo/`run_compute` call lose `schedule_mode`. |
| 6 | `backend/models/pipeline.py` | `run_compute(schedule: dict)` required, `schedule_mode` gone; docstring. |
| 7 | `backend/models/family/builder.py` | `FamilyRequest.schedule_mode` removed; `schedule: dict`. |
| 8 | `backend/api/helpers/family_compute.py` | No longer passes `schedule_mode`. |
| 9 | `backend/models/family/key.py` | `REQUEST_KEY_FIELDS` without `schedule_mode` (the map alone identifies the plan). |
| 10 | `backend/api/helpers/route_serialize.py` | `route_to_dict()` drops the derived `seasonal_schedules` block; the schedule block is `days_per_week_by_month` + `min_turnaround_min`. |
| 11 | `backend/adapters/proposal/gtfs_store.py` | Writes only `routes.schedule_months` (now required in the dict); no `seasonal_schedules` insert. Read path: `schedule_months` is the sole source; a NULL raises. `_insert_service` docstring: the GTFS calendar stays the coarse all-weekdays view. |
| 12 | `backend/adapters/proposal/repository.py` | Docstring: cascade list without `seasonal_schedules`. |
| 13 | `backend/db/dev/sql/create_proposal_schema.sql` | `routes.schedule_months JSONB NOT NULL`; `seasonal_schedules` table removed; `update_log.event` gains `migrated`; comments updated. |
| 14 | **new** `backend/db/dev/sql/migrations/2026-09-19_schedule_frequency.sql` | Server migration, one transaction via `migrate.py`: (1) folds the two-season rows into `schedule_months` where NULL (summer = Apr–Sep; daily → 7, three_per_week → 3), sets NOT NULL, drops `seasonal_schedules`; (2) strips `schedule_mode` from every stored `compute_request` (`alwaysDaily` → flat 7, `custom` keeps its map); (3) one `update_log` row (`migrated`, `user_id` NULL, no version bump) per rewritten proposal. Idempotent. Verified against Postgres 16 with a legacy route, a summer-only grid and an already-new request. |
| 15 | `backend/db/dev/seed.py` | Example proposal's route dict and request echo use the month map (`{str(m): 7}`) + `min_turnaround_min`. |
| 16 | `backend/tests/test_21_schedule_and_trainsets.py` | Rewritten boundary tests: both `schedule` shapes, rejections (0, 8, float, string, bool, mixed keys), default expansion, hash-equal spellings; `flat_schedule(3)` pins the guide's 156.857 operating days. |
| 17 | `backend/tests/test_20_route_content.py` | Explicit-defaults case posts `{"days_per_week": 3}`; `schedule_mode` removed from the invalid-mode parametrisation; new: `schedule_mode` → 400, one frequency echoes as the full month map. |
| 18 | `backend/tests/test_39_family_cache.py` | Cache-miss patches: a month map and `{"days_per_week": 7}`; the default spelled three ways hits one entry. |
| 19 | `backend/tests/test_06_family_context.py` | `run_compute` call passes the default map. |
| 20 | `backend/tests/test_02_db_seed.py` | `proposals.seasonal_schedules` removed from the expected tables. |
| 21 | `backend/scripts/bench_member.py`, `scripts/test_scenario_comparison_paris_berlin.py`, `scripts/test_timetable_comparison_hamburg_copenhagen.py`, `scripts/test_travel_time_paris_vienna.py` | Post `schedule: {"days_per_week": 7}` / pass the default map instead of `schedule_mode`. |
| 22 | `backend/api/README.md` | Family request example and a new paragraph on the two `schedule` shapes and the echo. |
| 23 | `backend/adapters/proposal/README.md` | §5.2 sidecar list: `routes.schedule_months` is the home; forward-looking note reworded. |
| 24 | `backend/db/README.md` | Table list without `seasonal_schedules`; `update_log` events include `migrated`; key-off paragraph. |
| 25 | `backend/models/README.md` | Pipeline diagram and switch paragraph. |
| 26 | `docs/MODEL.md`, `docs-site/reference/standard-values.md` | Regenerated (`scripts/generate_model_docs.py`): version 0.9.40, `DEFAULT_DAYS_PER_WEEK`, removed constants. |
| 27 | `docs/FRONTEND_HANDOVER_SUPPLY_SETTINGS.md` | "Superseded in part" note at the top: the schedule contract moved. |

Not touched, deliberately: `models/evaluation/operations.py` (`peak_month` keeps
its meaning on a grid), `models/evaluation/summary.py`, the frontend (Phase C),
`.github/workflows/backend-tests.yml` (the gate already pairs the route files
with `ROUTE_BUILDER_VERSION`), `docs/DEPLOY_HANDOVER.md` (addendum in Phase E
covering all phases).

## Contract after Phase A

```jsonc
"schedule": { "days_per_week": 3 }       // optional; or {"1": 7, ..., "12": 0}; omitted = 3 every month
"min_turnaround_min": 180                // unchanged
// resolved echo, always:
"schedule": { "1": 3, "2": 3, ..., "12": 3 }
```

`schedule_mode` is gone (400). The frontend today posts no block for daily
and `schedule_mode: custom` otherwise — Phase C switches it to always posting
`{"days_per_week": n}` and reading the committed grid's rounded average.

## Verification

- `uv run ruff format --check .` / `uv run ruff check .` — clean.
- Standalone units (`tests/test_21_*`, `test_7*_units`, `test_76_gate_page`): 206 passed.
- Migration SQL exercised on a local Postgres 16 (see file header for the cases).
- Stack tests (`test_02`, `test_06`, `test_20`, `test_36`, `test_39`, `test_42`, `test_50`, `test_53`) need the Docker stack — run in Phase E (`uv run --extra dev python -m pytest tests/ -v` after `docker-compose up -d --build api`).

## Rollout

1. Deploy as usual: `deploy.sh` → `migrate.py` applies `2026-09-19_schedule_frequency.sql` before the api starts (one transaction; refuses if any `routes` row has neither a map nor a projection).
2. Every stored proposal is outdated by the version bump: run `uv run --extra dev python -m scripts.refresh_proposals` (Phase E adds this step to `deploy.sh`).
3. Dev databases: reseed (`db/dev/seed.py` drops and recreates from `create_proposal_schema.sql`); if you keep a dev DB, run `python db/migrate.py` instead.
4. Until Phase C lands, the frontend's daily default posts no `schedule` block → the backend evaluates **3 days a week**, and its `custom` grids are rejected with 400 (`schedule_mode`). Deploy A–D together, or accept this on staging only.

## Commit split

- `feat(schedule): one frequency on the wire, month grid underneath (ROUTE_BUILDER 0.9.40)` — files 1–15.
- `test(schedule): both schedule shapes, default expansion, migration fixtures` — files 16–21.
- `docs(schedule): request contract, sidecar tables, generated model docs` — files 22–27 and this manifest.
