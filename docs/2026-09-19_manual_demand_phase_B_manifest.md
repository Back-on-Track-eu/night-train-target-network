# Manual demand inputs — Phase B delivery manifest

Date: 2026-09-19 · Guide: `docs/2026-09-18_manual_demand_guide.md` §6 Phase B ·
Scope: **Demand model 0.1.0 (backend).** Builds on Phase A (ROUTE_BUILDER 0.9.40, CALC 0.9.33).

Decisions applied (David, 2026-09-19): `places_sold` is a float; the demand block
lives beside `summary` (family) and under `evaluation.demand` (member); the
placeholder demand KPIs are replaced by the model's own figures with two sources
(shift from air, other/induced); emission factors re-based on Back-on-Track 2022
(389 / 132 / 14); air share 0 below 300 km, 25 % at 300 km, linear to 100 % at
1 200 km; "other" half car, half induced; echo precision weights 4 / pins 2 decimals.

Versions: **DEMAND 0.1.0 · CALC 0.9.34** (the guide's 0.9.33 was used by the Phase A
fix) **· EMISSIONS 0.2.0 · FAMILY_DOCUMENT_FORMAT 7**.

## What changed

### Model (`backend/models/`)

| # | File | Change |
|---|---|---|
| 1 | `demand/model.py` | DEMAND **0.1.0**: description, changelog. Constants: `CLASS_ORDER`, `DEMAND_LEVELS`, `DEFAULT_DEMAND_LEVEL`, `GROUP_ORDER`, `GROUP_CLASS_PREFERENCES`, `GROUP_LABELS`, `DEFAULT_GROUP_SHARES_PCT`, `ROUNDS_PCT`, `RULE_SHARE`, `OD_PRESETS`, `OD_WEIGHT_MIN/SPAN`, `DEFAULT_OD_WEIGHT`, `AIR_SHIFT_FLOOR_KM/AT_FLOOR/FULL_KM`, `OTHER_CAR_SHARE`; the D31 tariff (`FARE_PER_KM_BY_CLASS`, `FARE_PER_PAX_BY_CLASS` — renamed from `STOPGAP_*`, likewise services/catering); `STOPGAP_UTILIZATION_PER` removed; `OPEN_TODOS` rewritten. |
| 2 | **new** `demand/groups.py` | `allocate()` — one-to-one port of the sketch (rounds 50/20/20/10, rule share 80 %, strict class lists); `split_by_group()`. |
| 3 | **new** `demand/od_matrix.py` | `sellable_pairs()` (the stop-type rule from the stopgap), `boarding/alighting_stop_ids()`, `preset_weights()`, `resolve_weights()`, `od_shares()`, `pin_pair()`, `drop_stale_pins()`, `average_distance_km()`. |
| 4 | **new** `demand/sources.py` | `air_share(km)`, `split_sources(loads)` → air / car / induced trips and trip-km. |
| 5 | **new** `demand/distribute.py` | `DemandInputs`, `PairDemand`, `DemandResult`, `distribute_demand(route, inputs, fares)`: per trip = per year ÷ departures, allocation per pair, outbound matrix + mirrored return, float `places_sold`, two-part `avg_price`, sources. |
| 6 | **deleted** `demand/stopgap.py` | — |
| 7 | `demand/README.md` | Rewritten for 0.1.0. |
| 8 | `params.py` | `ODPair.places_sold: float` (+ docstring). |
| 9 | `pipeline.py` | `run_compute(demand: DemandInputs)`; `ComputeResult.demand`. |
| 10 | `family/builder.py` | `FamilyRequest.demand`, `FamilyMember.demand`. |
| 11 | `family/key.py` | `demand` in `REQUEST_KEY_FIELDS`, keyed minus `level` and `od.preset`. |
| 12 | `evaluation/summary.py` | `_demand_kpis()` replaces `_placeholder_demand_kpis()`: trips = passengers, trip-km = sold pax-km, `shift_air_*`, **`shift_other_*` (renamed from `shift_car_*`)**, CO₂ from the three sources, `subsidy_eur_per_t_co2` null unless positive, `demand_kpis_placeholder: false`. |
| 13 | `evaluation/calc.py` | `places_sold` typed float; renamed constant imports. |
| 14 | `evaluation/model.py` | **CALC 0.9.34** changelog; formula refs point at the renamed constants. |
| 15 | `emissions/model.py` | **EMISSIONS 0.2.0**: factors 389 / 132 / 14 g CO₂e/pkm with the Back-on-Track 2022 source; `MODE_SHIFT_SHARES` removed. `emissions/README.md` updated. |
| 16 | `route/route.py`, `route/route_factory.py`, `family/README.md`, `models/README.md` | Stopgap mentions → the demand model. |

### API (`backend/api/`)

| # | File | Change |
|---|---|---|
| 17 | `helpers/member_compute.py` | `validate_demand()`, `normalize_demand()` (defaults, canonical order, level ↔ total rule, weights 4 dp, pins 2 dp), `demand_inputs()`; echo gains `demand`; member payload gains `evaluation.demand`. |
| 18 | `helpers/family_compute.py` | Passes `demand` to `FamilyRequest`; views endpoint answers `{views, operations, demand}`. |
| 19 | `helpers/family_serialize.py` | **FORMAT 7**; every ok member carries `demand`. |
| 20 | `helpers/evaluation_serialize.py` | `demand_to_dict(demand, route)`; registry `demand.defaults` (level, levels, group shares, od weight, tariff) and `demand.constants` (the rule); `utilization_per` gone. |
| 21 | `helpers/proposal_serialize.py`, `helpers/proposal_compare.py`, `helpers/route_serialize.py` | Column rename; `places_sold` read as float. |
| 22 | `proposal_share.py` | Comment only. |
| 23 | `README.md` | Demand request contract, response shape, closed placeholder policy, gallery example values. |

### Persistence (`backend/adapters/`, `backend/db/`)

| # | File | Change |
|---|---|---|
| 24 | **new** `db/dev/sql/migrations/2026-09-19b_manual_demand.sql` | `od_pairs.places_sold` → DOUBLE PRECISION; `shift_car_*` → `shift_other_*` (guarded); `demand_kpis_placeholder` default FALSE; comments. Idempotent; run twice on Postgres 16. |
| 25 | `db/dev/sql/create_proposal_schema.sql` | Same shape, latest DDL. |
| 26 | `db/dev/seed.py` | Example proposal runs the new model at its defaults; request echo carries `demand`. |
| 27 | `adapters/proposal/gtfs_store.py` | `places_sold` read as float. |
| 28 | `adapters/proposal/repository.py`, `filter_builder.py` | Column rename in the gallery SQL and filter map. |
| 29 | `adapters/proposal/README.md` | §8.1 placeholder policy closed; column names. |

### Tests, tooling, docs

| # | File | Change |
|---|---|---|
| 30 | **new** `tests/test_83_demand_units.py` + **new** `tests/fixtures/demand_reference.json` | 38 standalone tests: the §3 reference table to the cent, the findings, presets/pins, sources, `distribute_demand()` on a hand-built Berlin–Verona route (mirror, weights, pins, night stop, level, share edits), the request boundary, the family-key rule; writes the parity fixture for the frontend. |
| 31 | `tests/test_42_proposal_family_api.py` | Member keys include `demand`; shape and identity checks; views endpoint set. |
| 32 | `tests/test_37_proposal_projection.py` | Placeholder assertions → the model's own KPIs. |
| 33 | `tests/test_21_*`, `test_30_*`, `test_36_*`, `test_10_*`, `tests/helpers.py`, `tests/README.md` | Renamed constants, D31 defaults, wording, `test_83` row. |
| 34 | `.github/workflows/backend-tests.yml` | Version gate: the four demand modules → `DEMAND_MODEL_VERSION`; `operations.py` → `CALC_VERSION`. |
| 35 | `scripts/model_docs/{extract,render_site,render_model_md}.py` | No `MODE_SHIFT_SHARES`; prose points at the source split. |
| 36 | `docs/MODEL.md`, `docs-site/reference/{standard-values,emission-factors}.md`, `docs-site/cost/{catering-contribution,services-revenue}.md` | Regenerated. |

Not touched, deliberately: the frontend (Phases C/D — `types/api.ts` will rename
`shift_car_*` and gain the `demand` block there), `docs/DEPLOY_HANDOVER.md` (E).

## Verification

- `uv run ruff format --check .` / `ruff check .` clean; `generate_model_docs.py --check` current.
- Standalone: `test_21`, `test_83`, `test_7x_units`, `test_76_gate_page` — 244 passed.
- Migration SQL: twice against a mini schema (type change, rename, default).
- Stack tests to watch locally: `test_10`, `test_30`, `test_36`, `test_37`, `test_40`, `test_42`, `test_50`, `test_52`, `test_53`, `test_54`, `test_55`.

## Rollout

1. `migrate.py` applies `2026-09-19_schedule_frequency.sql` then `2026-09-19b_manual_demand.sql`.
2. `refresh_proposals.py` recomputes every proposal (all three version bumps mark them outdated); the family caches are truncated by it.
3. Until Phase C: the frontend still reads `summary.shift_car_*` (now absent → shows "—") and posts no `demand` block (→ Medium, even spread). Deploy A–D together.

## Commit split

- `feat(demand): manual demand model 0.1.0 — allocation, OD spread, sources (CALC 0.9.34, EMISSIONS 0.2.0)` — files 1–29, 34, 35.
- `test(demand): reference table to the cent, distribute on a route, parity fixture` — files 30–33.
- `docs(demand): model README, API contract, generated docs, phase B manifest` — files 7, 23, 29, 36 and this manifest.
