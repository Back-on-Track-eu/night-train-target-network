# WP18 — Proposal family: one compute for every scenario × composition

Plan v2, 2026-09-09 (v1 of the same day folded in: D1 → `/calc` retired, D5 → auto-stop `add`
dropped, D9 → views on the fly, layered code and schema structure, compact wire contracts).
Supersedes the calc-matrix design (`2026-09-06_calc_matrix_wp14_streaming_plan.md` Phases B–D);
keeps WP14 (pool, gthread).

Baseline: `backend-dev` at ROUTE_BUILDER 0.9.33 / CALC 0.9.25 / backend 0.4.0 with the matrix
batch applied. Measured on the dev stack (`scripts/bench_member.py`, Berlin–Wien, NEW-BAL-7):

| what | ms |
|---|---|
| member, legs live (first ever) | 2 942 |
| member, legs cached, request cache bypassed | 352 |
| evaluate + views (domain) | **3** |
| `views_to_dict` | 55 |
| ⇒ route reassembly + timetable + demand + **catalog loads** | ~294 |

Evaluation is free; a member costs what rebuilding its route and reloading every catalog costs.
The family shares both inside one build and changes nothing in the pipeline's shape.

---

## Hand-off — read this first in the implementation chat

This section is the state of `backend-dev` (worktree `proposal-builder-redesign`) on 2026-09-09
that the plan is written against. Everything below the vocabulary section assumes it.

### What is on the branch (applied as zips, in this order, on top of the 2026-09-06 snapshot)

1. `calc-matrix-wp14-viewport` — WP14 pool + gthread (`adapters/db_pool.py`, all 8 adapters, `test_05`),
   `/calc/matrix` (`proposal_matrix.py`, `matrix_serialize.py`, `test_41`), `Scenario.dimensions`,
   five summary KPIs + migration `2026-09-07_proposal_summaries_supply_kpis.sql`, CALC 0.9.25,
   pyproject 0.4.0, the zone A–E frontend (`ProposalResults.vue` + 12 components), four panels deleted.
2. `ownership-pill`, `ownership-state` — `OwnershipLine.vue`, tri-state `proposalOwnership`.
3. `country-flags` — `CountryFlags.vue` shared by gallery card and route stats.
4. `preview-network`, `preview-network-copy` — `PREVIEW_NETWORKS = ['2032']` in `lib/scenarioAxes.ts`
   (`VITE_PREVIEW_NETWORKS`); 2032 hidden from switches, comparison and the matrix axis.
5. `scenario-card-polish`, `info-popover-reuse`, `scenario-summary-type` — `InfoPopover.vue` (shared
   shell), `InfoHint.vue`, `FactorInfoPopover.vue` on it; scenario summary styling.
6. `matrix-wiring` — client switched from NDJSON to the document encoding; `gridMatrix` (summary,
   scenarios × all compositions) + `scenarioMatrix` (full, scenarios × selected composition);
   scenario switch served from `cellAsCalcResponse()`. `matrix_serialize.SharedPool` ids now hash
   kind + data.
7. `fix-apierror-reexport` — `export { ApiError } from './apiError'` in `proposalsApi.ts` (blank page).
8. `bench-member`, `bench-member-fix` — `scripts/bench_member.py` (numbers at the top of this plan).

### What is verified and what is not

- Verified in the sandbox on every batch: `ruff format --check`, `ruff check` (findings identical to
  baseline), `ast.parse`, `generate_model_docs --check`, `vue-tsc`, `eslint`, `prettier`, `vitest`
  (223), and from batch 7 on `vite build`.
- **Never run**: the backend integration suite against a live stack (`test_05`, `test_11`, `test_37`,
  `test_41`, and every module exercising the pooled adapters). The stack itself comes up and
  `/calc` works (KPIs render, `bench_member.py` ran through `compute_proposal()`).
- **Not confirmed working**: the matrix path end to end. Its first version failed on the wire with
  a generic network error; the document-mode rewrite (batch 6) has not been seen succeeding. The
  plan retires it, so do not spend time on it — but do not assume its frontend wiring is sound either.

### Documents that are now deliberately out of date (rewritten in Phase B3 — do not trust, do not polish)

- `docs/FRONTEND_HANDOVER.md` §12 (matrix contract, two-grid client) → §13 replaces it.
- `docs/DEPLOY_HANDOVER.md` §4c (`CALC_MATRIX_*`, NDJSON/Caddy check) → §4d replaces it.
- `backend/api/README.md` `/calc` and `/calc/matrix` sections; `backend/adapters/proposal/README.md`
  §2.1–2.5 (compute cache under `proposals`, matrix); `docs/PARKED_WORK.md` §2 (marked shipped —
  still true) and §3 (WP17 as a matrix axis → becomes a family axis).
- `docs/2026-09-06_calc_matrix_wp14_streaming_plan.md` Phases B–D — superseded by this document.
- `frontend/README.md` "Comparison matrix" paragraph.

### Facts the plan relies on that live in code, not in any doc

- `tests/helpers.compute()` posts to `/calc`; 14 test modules go through it — the B2 change to
  `helpers.py` is what keeps the content tests alive after `/calc` is gone.
- `publish_dispatch.py` refuses any `scenario_id` other than the current base (`ScenarioNotBaseError`)
  — hence "presented member = base × composition". Modes today: `new` (optional
  `based_on_proposal_id`), `overwrite`.
- `route_trip()` (`rail_router.py`) is the L1/L2 boundary: `router.route(stops, max_speed_kmh,
  avoid_hsr, gauge_mm, routing_mode)` is memoisable; `apply_country_buffer`, `apply_traction_dynamics`
  and `calc_energy_consumption` mutate legs in place → the memo must hand out copies. `route_variant_key`
  and the leg cache already key on the resolved custom model.
- `run_compute()` loads `build_all_tracks/stops/passages(scenario_id)` and
  `build_all_compositions()` on every call (`route_factory.plan_route`, `_build_trip_pair`) — the
  bulk of the 294 ms. `provenance.tracks/stop_infra/passages` are what `evaluate_and_build_views()`
  needs.
- `resolve_routing_params()` derives `avoid_hsr` per country as `composition.hsr_allowed ∧
  track.hsr_allowed` — this is why the route-variant key is `(max_speed_kmh, hsr_allowed)` and why
  today's catalog gives 8 variants (two speed classes coincide with `material_strategy`).
- The frontend only ever sent `auto_stop_addition: suggest` then `off` (`requestCalc` /
  `recomputeWithSelection`); `add` is expected unused (D5 pre-check).
- `Scenario.dimensions` is derived in `scenario_serialize.py` from `scenario_key` +
  `routing_graph_key`; `scenario_variants` (Phase A) will carry it as columns via the variant's scenario.
- `summary_row_to_dict()`, `_upsert_summary()`, the gallery CTE column lists and
  `filter_builder.RANGE_COLUMNS` each enumerate the summary columns explicitly — every summary key
  is a DB column; adding one is a migration.
- Sketch: `docs/design/2026-09-06_viewport-rearrangement-sketch.md` (this batch) defines zones A–E and
  the interaction rules the frontend components implement; the HTML mock stays outside the repo.

### Conventions the implementation chat must keep (also in AGENTS.md / CLAUDE.md)

Zips extractable from repo root with a manifest; `uv` from `backend/`; ruff style; no
`git add -A`; commit messages via `-F`; three-way `feat`/`test`/`docs`; version bumps when
CI-watched files diff; handovers under `docs/`; serialization never in domain objects.

### First thing to do

Phase 0: extend `scripts/bench_member.py` with the memo split (a throwaway `MemoLoader`/`MemoRouter`
in the script is fine before `models/family/context.py` exists), run it twice on the dev stack, run
the D5 pre-check, record both in the PR description. Then Phase A.

---

## 0. Vocabulary and layers

| term | layer | is |
|---|---|---|
| **parameters** | P | calibrated catalogs (`input_params`), scenario pins, measure sets, scenario variants |
| **legs** | L1 | geometry + raw driving time per stop pair on one graph with one resolved custom model (`route_cache`) |
| **trip / timetable** | L2 | trips built from legs: buffer, dynamics, dwell, padding, expert overrides, energy |
| **demand** | L3 | stopgap loads per OD |
| **evaluation** | L4 | cost / revenue / emissions and their views |
| **member** | L1–L4 | one (scenario variant, composition) for one stop list + HOW: route + summary; views on demand |
| **family** | L5 | every member for one stop list + HOW under the current pins — computed, cached, never edited |
| **scenario variant** | P | the flattened axis the frontend addresses: scenario × measure set |
| **proposal** | S | identity + ownership + presentation: stop list, HOW, presented member, name, author, discussion |
| **presented member** | S | what a published proposal shows in the gallery: current base scenario × the author's composition (publish rule unchanged) |

A single member is a **1 × 1 family** (`scenario_variant_ids` / `composition_ids` filters on the
family body). There is no separate single-member endpoint any more; `compute_member()` remains the
*function* publish, refresh and the views call run.

---

## 1. Decisions (confirmed unless marked open)

| # | decision |
|---|---|
| **D1** | `POST /api/proposal/calc` and `/calc/matrix` are **removed**. `api/helpers/proposal_compute.py` becomes `member_compute.py` / `compute_member()` — the L1–L4 primitive with the member cache, called by the views path, publish, the on-load fallback and `refresh_proposals.py`. Tests fetch a member as a 1 × 1 family. |
| **D2** | No `route_variants` table. L1 already persists per leg in `route_cache.route_segments`, shared across proposals; the family shares built legs in memory (D4). |
| **D3** | Family persistence = one row per key in `family.documents` with the member cache's TTL; nothing per published proposal beyond `proposals` + `proposal_summaries`. |
| **D4** | Route + timetable + demand built once per (scenario, composition) = 72; measure sets multiply evaluation only. Sharing via `FamilyContext` (`MemoLoader`, `MemoRouter`) — `route_factory.py` / `pipeline.run_compute()` unchanged. |
| **D5** | `auto_stop_addition` becomes `off \| suggest`; the `add` path (`apply_auto_stop_addition`) is deleted from `route_factory.py` → **ROUTE_BUILDER 0.9.34**. A family always builds on the input stop list; `suggest` runs once on the baseline member and its suggestions ride on the document. Pre-check before the migration: `SELECT count(*) FROM proposals.proposals WHERE compute_request->>'auto_stop_addition' = 'add'` — expected 0. |
| **D6** | `POST /api/proposal/publish` `mode: new \| overwrite \| copy` (`copy` = `new` with `based_on_proposal_id` required). Load stays `GET /api/proposal/<id>`. |
| **D7** | `scenario.measure_sets` (1 row `none`) + `scenario.scenario_variants` (materialised, 6 rows); `GET /api/scenarios` exposes both; the family axis and the frontend address `scenario_variant_id`. |
| **D8** | `evaluate_route(…, measures: MeasureSet)` threaded as identity factors on ticket revenue, energy cost, track access; recorded in the result → **CALC 0.9.26**. |
| **D9** | Views on the fly: `GET …/views` = `compute_member()` for that member (member-cache hit or ≈ 350 ms, then cached). No LRU. The builder never writes 648 members into the member cache. |
| **D10** | Config: `FAMILY_MAX_MEMBERS` (1 000), `FAMILY_WORKERS` (4); `CALC_MATRIX_*` removed. |
| **D11** | Wire contracts carry no provenance, no parameter blocks, no models registry and no duplicated geometry (§2.5, §2.6). Static things have their own endpoints: `GET /api/models` (new — the formula/version registry), `GET /api/params/*` (existing — parameters with sources, per scenario). |
| **D12 (open)** | `proposals.likes` / `comments` stay in `proposals` (user state *about* a proposal) — or move to an `engagement` schema in the same migration. Default: stay. |

---

## 2. Architecture

### 2.1 Code — one package per layer

```
backend/
├── models/                                   DOMAIN — no I/O anywhere below this line
│   ├── params.py                             P  catalogs, Scenario, + MeasureSet, ScenarioVariant, NO_MEASURES
│   ├── route/
│   │   ├── routing/                          L1 rail_router (leg routing, gauge, dynamics), leg cache key
│   │   ├── timetable.py, expert_timetable.py L2 timetable strategies, expert overrides
│   │   ├── route_factory.py                  L2 trips from routed legs — `add` path removed (D5)
│   │   └── model.py                          constants, ROUTE_BUILDER_VERSION 0.9.34
│   ├── demand/                               L3
│   ├── energy/  emissions/  evaluation/      L4 (`evaluate_route(…, measures)`)
│   ├── pipeline.py                           MEMBER: run_compute(), evaluate_and_build_views() — unchanged
│   └── family/                               L5 (new)
│       ├── key.py                            family_key(): which pins enter the key, and nothing else
│       ├── context.py                        FamilyContext = MemoLoader + MemoRouter (build-scoped, no I/O)
│       └── builder.py                        run_family(): stops once, axes, members = run_compute() on the context
│
├── adapters/                                 I/O — one module per persistent layer
│   ├── db_pool.py
│   ├── data_loader_from_db.py                P  (+ build_all_measure_sets, list_scenario_variants)
│   ├── route_segment_repository.py           C1 route_cache
│   ├── family/                               C2 (new; was adapters/proposal/compute_cache.py)
│   │   ├── member_cache.py                       family.members    request_hash → member payload
│   │   └── document_cache.py                     family.documents  family_key  → document
│   └── proposal/                             S  published state, engagement, projection, filters, GTFS
│
└── api/
    ├── params.py, scenarios.py, models.py    P  (models.py new: GET /api/models)
    ├── proposal_family.py                    L5 POST /proposal/family · GET …/<key> · GET …/<key>/members/<sv>/<comp>/views
    ├── proposal_publish.py                   S  mode new | overwrite | copy
    ├── proposals.py, proposal_compare.py     S  load, list, compare, stats
    └── helpers/
        ├── member_compute.py                 was proposal_compute.py: compute_member(), HOW validation, member cache
        ├── family_compute.py                 validate_family_body, build_or_load_family, member_views
        ├── family_serialize.py               document + views shaping; SharedPool (from matrix_serialize)
        ├── route_serialize.py                + route_compact_to_dict() (§2.5)
        └── ✗ proposal_matrix.py  ✗ matrix_serialize.py  ✗ api/proposal_calc.py
```

### 2.2 Layers on the pipeline as it is

```
run_compute()                                  run_family()
  plan_route()                                   catalogs: MemoLoader — once per scenario
    _build_trip()                                legs:     MemoRouter — router.route() once per
      route_trip() ── router.route()  ◄──────────           (stops, max_speed, avoid_hsr, gauge, mode), copies out
      apply_country_buffer / dynamics            per (scenario, composition): run_compute() as today
      timetable, energy                          per measure set: evaluate_and_build_views()
  distribute_demand()                            document: summaries + compact routes + shared geometries
  evaluate_and_build_views()   ◄───────────────  views on demand: compute_member() (member cache)
```

### 2.3 Database — one schema per persistent layer

| schema | layer | lifetime | tables | WP18 change |
|---|---|---|---|---|
| `ontd` | source data | reloaded from Drive | 21 | — |
| `input_params` | **P** calibrated catalogs, full-table version snapshots | permanent, append-only | 18 | — |
| `scenario` | **P** pins + the variant axis | permanent, append-only | `scenarios`, **`measure_sets`**, **`scenario_variants`** | +2 |
| `route_cache` | **C1** legs | permanent; invalidated by graph import / route-builder bump | `graph_state`, `route_segments` | — |
| `family` | **C2** computed members + documents — pure functions of pins | ephemeral, one TTL, `flush()` on any bump | **`members`** (was `proposals.compute_cache_result` + `_pointer`), **`documents`** | new schema |
| `proposals` | **S** published state, presentation, engagement, audit | permanent, versioned per proposal | `proposals`, `routes`, `trips`, `stop_times`, `shapes`, `calendar*`, `segments`, `od_pairs`, `parkings`, `shuntings`, `seasonal_schedules`, `timetable_warnings`, `proposal_summaries`, `likes`, `comments`, `update_log` | compute cache leaves |
| `admin` | operations | permanent | 6 | — |

Every row in `proposals` is state a user owns; every row in `family` can be truncated without loss;
`route_cache` is reproducible but worth keeping; `scenario` + `input_params` are the only things a
number depends on. `refresh_proposals.py` reads as: flush `family`, recompute presented members.

```
scenario.measure_sets        measure_set_id PK, key TEXT UNIQUE, vat_exempt, energy_tax_exempt,
                             tac_direct_cost BOOL, description  — unversioned definitions (WP17 rates
                             get their own versioned table)
scenario.scenario_variants   scenario_variant_id PK, scenario_id FK, measure_set_id FK,
                             UNIQUE(scenario_id, measure_set_id)
family.members               request_hash PK, route_fingerprint, scenario_id, composition_id,
                             resolved_request JSONB, payload JSONB, created_at   (today's two cache
                             tables collapsed to one — the pointer/result split existed to share
                             payloads across requests that converge on one result; kept as a
                             UNIQUE(route_fingerprint, scenario_id, composition_id) index instead)
family.documents             family_key PK, route_builder_version, calc_version, payload JSONB, created_at
```

Migrations: `2026-09-10_scenario_variants.sql`, `2026-09-10_family_schema.sql` (schema, `members`
from the two cache tables, `documents`), `2026-09-10_auto_stop_add_removed.sql` (assertion only —
fails loudly if the D5 pre-check is not 0). `db/schema.py` keeps `scenario` + `route_cache`;
`db/dev/sql/create_family_schema.sql` joins `create_proposal_schema.sql`; `db/README.md` carries the
table above.

### 2.4 Endpoints

| call | does |
|---|---|
| `POST /api/proposal/family` | stops + HOW (`timetable_mode`, `fixed_night_interval`, `schedule_mode`, `routing_mode`, `auto_stop_addition: off\|suggest`, `expert_timetable`) + optional `scenario_variant_ids`, `composition_ids` (null = full axes), `presented: {scenario_variant_id, composition_id}` (default base × `DEFAULT_COMPOSITION_ID`). Builds or loads the family → document (§2.5). 400 validation / `family_too_large`, 503 data not loaded. Synchronous. |
| `GET /api/proposal/family/<key>` | the document from `family.documents`; 404 when expired (client POSTs again). |
| `GET /api/proposal/family/<key>/members/<scenario_variant_id>/<composition_id>/views` | `{views}` for one member (§2.6) via `compute_member()`. For a published proposal's presented member the stored `evaluation_output` is served when its versions match (today's on-load fallback, moved here). |
| `GET /api/models` | **new** — `models_to_dict()`: versions, descriptions, formula registry. Static; `Cache-Control: max-age`. Was inlined in every calc response. |
| `GET /api/params/*` | existing — parameters with sources per scenario, for the "provenance" the calc response used to inline. |
| `GET /api/scenarios` | + `measure_sets`, `scenario_variants`. |
| `GET /api/proposal/<id>` | compact route (§2.5) + summary + `family_request` (stops + HOW) + `presented` instead of route + `evaluation_output`. |
| `POST /api/proposal/publish` | `mode` per D6; `compute_request` = HOW + composition at base, as today. |
| ✗ `POST /api/proposal/calc`, ✗ `POST /api/proposal/calc/matrix` | removed. |

### 2.5 Family document — everything once

```jsonc
{
  "family_key": "sha256:…",
  "route_builder_version": "0.9.34", "calc_version": "0.9.26",
  "request": { "stops": [...], …HOW… },                        // resolved echo — publish sends it back
  "suggested_stops": [ … ],                                    // "suggest" only, from the baseline member
  "axes": {
    "scenario_variants": [ { "scenario_variant_id", "scenario_id", "measure_set_id", "scenario_key",
                             "scenario_name", "is_current_base", "routing_graph_key", "dimensions" } ],
    "compositions":      [ "NEW-BAL-7", … ]                    // ids only — the catalog is GET /api/params/compositions
  },
  "presented": { "scenario_variant_id": 1, "composition_id": "NEW-BAL-7" },
  "geometries": { "g:…": [[lon, lat], …] },                    // ≈ 8, content-addressed (SharedPool)
  "routes": { "r:1:NEW-BAL-7": { …route_compact_to_dict… } },  // 72, one per (scenario, composition)
  "members": [
    { "scenario_variant_id": 1, "composition_id": "NEW-BAL-7", "status": "ok",
      "route_ref": "r:1:NEW-BAL-7", "route_fingerprint": "sha256:…", "summary": { …§5.4… } },
    { "scenario_variant_id": 5, "composition_id": "…", "status": "error",
      "error": "routing_graph_not_configured", "message": "…" }
  ],
  "stats": { "n_members", "n_ok", "n_error", "n_routes", "elapsed_s", "cache_hit" }
}
```

`route_compact_to_dict()` (new in `route_serialize.py`, also what `GET /api/proposal/<id>` returns):

- **keeps** `route_id`, `scenario_id`, `schedule`, `trip_pairs[].composition_id`, per trip
  `general_parameters` and `segments` (`geometry_id` → shared `g:`), `parkings`, `shuntings`,
  `timetable_warnings`;
- **drops** `trip_pairs[].composition` (catalog), `od_pairs` (demand — evaluation input), the
  `track_infrastructure` provenance list, `geometries` (shared);
- **de-duplicates stops**: each trip carries `stops[]` once (id, name, country, lat/lon, type,
  arrival/departure, auto_added) and segments reference `from`/`to` by index instead of inlining both
  stop dicts — today every stop is serialised twice per trip.

Members are ordered scenario-variants-outer, compositions-inner. Error codes are
`classify_compute_error()`'s. On a one-instance stack every `infra_2032` member is an error member;
the document is still 200.

Size (Berlin–Wien, 6 × 12): summaries 72 × ~0.5 KB, compact routes 72 × ~6 KB, geometries 8 × ~150 KB,
axes — ≈ 1.7 MB, ≈ 350 KB gzipped (documents are JSON, so Flask-Compress applies).

### 2.6 Views response

`{ "views": { …views_to_dict… } }` — nothing else. Parameters (`evaluation.input.parameters`) are
`GET /api/params/*` for the member's scenario; the models registry is `GET /api/models`.

### 2.7 Interaction

1. **Open a proposal**: `GET /api/proposal/<id>` (compact route + summary, instant) → render →
   `POST /api/proposal/family` with `family_request` → switches and comparison light up.
2. **Evaluate (builder)**: `POST family` with `auto_stop_addition: suggest` → suggestions from the
   document → accepted stops = new family with `off`.
3. **Switch scenario variant / composition**: no request — `routes[route_ref]`, `geometries`, `summary`.
4. **Open zone E / change selection with zone E open**: `GET …/views`.
5. **Expert timetable, mode, night interval**: new key → `POST family` (legs cached, ≈ 2 s).
6. **Stop edit**: new family.
7. **Publish**: `compute_request` = `request` + presented composition at base; modes per D6.
8. **Version bump**: `refresh_proposals.py` flushes `family`, recomputes presented members.

---

## 3. Backend — file by file

### Phase 0 — attribution (no product change)

- `backend/scripts/bench_member.py` — member on `MemoLoader` alone, `MemoRouter` alone, both;
  document size for the default family. Kept as the family's regression bench.

### Phase A — parameters, pins, hooks (independently mergeable)

- `backend/db/schema.py` — `scenario.measure_sets`, `scenario.scenario_variants` with column docs.
- `backend/db/dev/sql/migrations/2026-09-10_scenario_variants.sql`.
- `backend/db/dev/seed.py` — `none` measure set; `materialise_scenario_variants(cur)` (cross
  product, `ON CONFLICT DO NOTHING`), called after the scenario rows and reused by the migration.
- `backend/models/params.py` — `MeasureSet`, `NO_MEASURES`, `MeasureSetCollection`, `ScenarioVariant`.
- `backend/adapters/data_loader_from_db.py` — `build_all_measure_sets()`, `list_scenario_variants()`,
  `resolve_scenario_variant(id) -> (Scenario, MeasureSet)`.
- `backend/models/evaluation/calc.py` — `measures` parameter, three identity factors, each commented
  with the WP17 rate it will carry; `EvaluationResult.measures`. `models/evaluation/model.py` —
  **CALC 0.9.26** + changelog; `docs/MODEL.md` regenerated.
- `backend/models/pipeline.py` — `run_compute(…, measures=NO_MEASURES)` pass-through.
- `backend/api/helpers/scenario_serialize.py` — `measure_set_to_dict`, `scenario_variant_to_dict`;
  both groups in `scenario_collection_to_dict`.
- `backend/api/models.py` — **new** `GET /api/models`; registered in `main.py`.
- Docs: `backend/api/README.md` (Scenarios, Models), `backend/db/README.md`,
  `backend/models/scenarios/README.md` (variants; why measures are not scenario rows).
- Tests: `test_11_scenarios_api.py` (+ measure sets, variants pinned per pair); `test_30` (+
  `NO_MEASURES` leaves every KPI byte-identical — fixture pin); `test_10_params_api.py` (+ `/models`).

### Phase B1 — route builder: `add` removed (independently mergeable)

- `backend/models/route/route_factory.py` — `apply_auto_stop_addition` branch and function removed;
  `VALID_AUTO_STOP_ADDITION_MODES = {off, suggest}` (`models/route/model.py`); **ROUTE_BUILDER
  0.9.34** + changelog; `known_auto_added_stop_ids` / `Stop.auto_added` kept (suggestions accepted
  by the user are ordinary stops from then on — decide whether the flag stays meaningful; default:
  keep, value always False).
- `backend/models/route/timetable.py` — `apply_auto_stop_addition` deleted if unused elsewhere
  (`suggest_auto_stops` stays).
- `backend/db/dev/sql/migrations/2026-09-10_auto_stop_add_removed.sql` — `DO $$ … RAISE …` assertion.
- Tests: the module exercising `add` (to be located in Phase 0) loses its `add` cases; validation
  tests expect `add` → 400.
- Docs: route builder README, `api/README.md` request vocabulary.

### Phase B2 — family (backend core)

- `backend/models/family/key.py`, `context.py`, `builder.py` (§2.1/2.2). `builder.run_family()`:
  baseline member first (`suggest` honoured there, `off` everywhere else), then
  `ThreadPoolExecutor(FAMILY_WORKERS)` over (scenario, composition), then measure sets.
  `FamilyResult` = resolved request, suggestions, `members`, `routes` (domain objects).
- `backend/adapters/family/member_cache.py` (from `adapters/proposal/compute_cache.py`, one table),
  `document_cache.py`; one `flush()` covering both; `adapters/family/README.md`.
- `backend/api/helpers/member_compute.py` (rename of `proposal_compute.py`): `compute_member()`,
  `validate_how_fields()`, `classify_compute_error()`, `canonical_sha256()`; payload no longer carries
  `models` or `input.parameters` (views only) — callers: `publish_dispatch.py`, `proposals.py`,
  `refresh_proposals.py`, `seed.py`, tests.
- `backend/api/helpers/family_compute.py`, `family_serialize.py`, `route_serialize.py`
  (`route_compact_to_dict`), `api/proposal_family.py` (blueprint), `api/helpers/dependencies.py`
  (family caches on the pool), `api/config.py` (D10), `main.py` (blueprint; Compress note).
- `backend/api/proposals.py` — `GET /proposal/<id>` compact shape (§2.4); on-load fallback moved
  behind the views endpoint.
- `backend/api/helpers/publish_dispatch.py` — `mode: copy`.
- `backend/scripts/refresh_proposals.py` — flush `family`.
- **Deleted**: `api/proposal_calc.py`, `api/helpers/proposal_matrix.py`, `matrix_serialize.py`,
  `adapters/proposal/compute_cache.py`, `tests/test_35_proposal_calc_api.py`,
  `tests/test_41_proposal_calc_matrix_api.py`.
- `backend/pyproject.toml` — 0.4.0 → 0.5.0.
- Tests:
  - `tests/helpers.py` — `compute()` = 1 × 1 family + views; `member()`; returns the calc-shaped
    dict the content tests read (`route`, `summary`, `views`) so `test_20/22/30/36/37/39/40/50–55`
    change only where they read `evaluation.models` / `input.parameters` (→ `/api/models`,
    `/api/params`).
  - `tests/test_06_family_context.py` — **new**: `MemoRouter` routes once, hands out independent
    copies; `MemoLoader` returns the same collection; delegation.
  - `tests/test_42_proposal_family_api.py` — **new**: validation; document shape; `n_members` =
    variants × compositions; order; every `route_ref` / `geometry_id` resolves and no geometry is
    repeated; presented member ≡ `compute_member()` (fingerprint, summary, views); `infra_2032` error
    members; `suggest` once; expert timetable changes key + members, not geometries; second POST
    `cache_hit`; `GET …/<key>`; views endpoint hit + rebuild; `family_too_large`; publish `copy` /
    `overwrite` from a member.
  - `tests/test_39_compute_cache.py` → `test_39_family_cache.py` (members + documents, sweep, flush).
  - `tests/test_53_proposal_refresh.py` — flush covers `family`.
  - `tests/README.md`.

### Phase B3 — docs

- `backend/api/README.md` (Family, Models; calc sections removed; publish modes),
  `backend/adapters/proposal/README.md` §2 rewritten around the family (layers, D2–D5, cost table;
  §2.3 → `adapters/family/README.md`), `backend/adapters/README.md`, `backend/db/README.md`,
  `backend/models/family/README.md`.
- `docs/FRONTEND_HANDOVER.md` §13 (document + views + models + compact route + proposal load shape —
  every `api.ts` change), `docs/DEPLOY_HANDOVER.md` §4d (three migrations, D5 pre-check, `FAMILY_*`,
  cache truncate = `family` schema, refresh run, `/api/models` cache header), `docs/PARKED_WORK.md`
  (WP17: hook exists).

## 4. Frontend — file by file (Phase C)

- `types/api.ts` — `MeasureSet`, `ScenarioVariant`, `Family*`, `ViewsResponse`, `ModelsResponse`,
  `CompactRoute` (stops once, segment stop indices), `ProposalDetailResponse` new shape, `PublishMode`
  + `copy`; `Matrix*`, `ProposalCalcResponse` removed.
- `lib/proposalFamily.ts` (+ test) — `memberKey`, `routeFor(document, member)` (compact route +
  inlined geometry → the viewport's `RouteResult`), `byScenarioVariant`, `byComposition`,
  `baselineMember`.
- `lib/scenarioAxes.ts` (+ test) — over `ScenarioVariant[]`.
- `lib/proposalsApi.ts` — `postFamily`, `getFamily`, `getMemberViews`, `getModels`; `calcMatrix`
  removed; publish mode type.
- `composables/useProposalFamily.ts` — replaces `useCalcMatrix.ts`; `viewsFor(member)` with a
  per-family views cache; `useModels()` (once per session).
- `components/ProposalViewport.vue` — `adaptRoute()` on the compact shape (stops by index);
  `startFamily()` after load / evaluate; `applyMember()`; `applyViews()` lazily; suggestions from the
  document; publish from `request` + presented; matrix wiring removed.
- `ProposalResults.vue`, `CompareSection.vue`, `ScenarioCompareBars.vue`,
  `ScenarioCompositionGrid.vue`, `SupplyTable.vue`, `SettingsSection.vue`, `MainKpiGrid.vue` —
  family-member props; `CostRevenueBreakdown.vue` — views + models arrive lazily (loading state).
- `stores/store.ts` — `scenarioVariants`, `selectedScenarioVariantId`; `models` fetched once.
- **Deleted**: `lib/calcMatrix.ts` (+ test), `composables/useCalcMatrix.ts`.
- `i18n/locales/en.json`, `frontend/README.md`; `npm run ci` gains `vite build`.

## 5. Phases, checkpoints, pipeline

| phase | scope | checkpoint |
|---|---|---|
| **0** | bench split, document size, D5 pre-check on staging + prod | numbers in the PR description |
| **A** | parameters, variants, measures hook, `/api/models`, CALC 0.9.26 | `test_10/11/30/37` green; `generate_model_docs --check`; migration on a prod copy |
| **B1** | `add` removed, ROUTE_BUILDER 0.9.34 | route tests green; assertion migration passes on prod copy |
| **B2** | family core, caches, endpoints, compact contracts, `/calc` removal, publish `copy` | `test_06/42/39/50–53` + full suite green; 8-parallel family soak; family ≤ 3 s warm on the VPS |
| **B3** | backend docs, handovers | — |
| **C** | frontend | `npm run ci` incl. `vite build`; manual: open, evaluate with suggestions, switch, zone E, expert edit, publish copy/overwrite, 375 px |
| **D** | staging promotion | Giovanni: migrations in order, `FAMILY_*`, `family` truncate, refresh run |

A and B1 merge independently. B2 and C go to `staging` together — `/calc` disappears in B2, so the
old frontend cannot run against the new backend; `staging` takes both in one promotion.

CI checklist: CALC 0.9.26 (A), ROUTE_BUILDER 0.9.34 (B1), `pyproject` 0.5.0 (B2), `docs/MODEL.md`
regenerated, three migrations present, `.env.example` covers `FAMILY_*`, `tests/README.md` current.
Commits three-way per phase (`feat` / `test` / `docs`), `-F` files, explicit paths.

## 6. Risks and bounds

- **Trip build cost** (Phase 0): at 100 ms per (scenario, composition) the family is still ≈ 2 s on
  4 workers; above ~200 ms the builder shares the timetable across compositions of one speed class —
  inside `run_family`, invisible to the contract.
- **Compact route vs. the viewport's `adaptRoute()`**: the one frontend change with real surface
  (stops by index). Covered by the `proposalFamily.test.ts` fixture and the manual pass.
- **Stored `evaluation_output` still carries the old full shape**: the views endpoint reads only
  `views` out of it; a refresh run rewrites the rest on the next bump.
- **Thread-safety**: catalogs are read-only collections; legs are copied out of the memo; the memo
  dicts are the only shared mutable state, under their locks.
- **WP17 later**: rows and factors only; key, document, axis and caches already carry the dimension.
