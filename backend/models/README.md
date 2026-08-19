# Night Train — Backend Model Layer

This folder contains the domain model for evaluating night train route economics.

**Related documentation:** API reference (all endpoints consuming this layer) —
[`../api/README.md`](../api/README.md) · demand model —
[`demand/README.md`](demand/README.md) · emissions model —
[`emissions/README.md`](emissions/README.md) · evaluation model —
[`evaluation/README.md`](evaluation/README.md) · energy model —
[`energy/README.md`](energy/README.md) · routing engine setup —
[`route/routing/README.md`](route/routing/README.md) · database layer —
[`../db/README.md`](../db/README.md) · proposals architecture & storage —
[`../adapters/proposal/README.md`](../adapters/proposal/README.md)

---

## Structure

```
models/
├── formula.py                       # Shared Formula/FormulaParam dataclasses (LaTeX + description + input/output legend
│                                    # incl. 'ref' source pointers — rendered into docs/MODEL.md by scripts/generate_model_docs.py)
├── params.py                        # Shared parameter dataclasses (loaded from DB)
├── pipeline.py                      # run_compute() / evaluate_and_build_views() — domain-level pipeline dispatch
├── utils.py                         # Shared unit conversion utilities
├── demand/
│   ├── stopgap.py                   # distribute_demand() — stopgap uniform-distribution proxy
│   ├── model.py                     # DEMAND_MODEL_VERSION + stopgap standard values & open TODOs
│   └── README.md                    # Demand model documentation (incl. incoming real-model design)
├── route/
│   ├── trip.py                      # Stop, Segment, Trip — physics domain objects
│   ├── route.py                     # Route, TripPair, Parking, Shunting, ODPair, Schedule
│   ├── route_factory.py             # plan_route() — sole Trip/TripPair/Route constructor
│   ├── timetable.py                 # Pluggable timetable_mode / schedule_mode / auto_stop_addition strategies
│   ├── model.py                     # ROUTE_BUILDER_VERSION + all standard values & open TODOs of the route model
│   └── routing/                     # rail_router.py (GraphHopper wrapper) + dynamics.py (per-stop accel/brake time loss)
│       ├── rail_router.py           # OpenRailRouting (GraphHopper) wrapper
│       └── docker/                  # Self-hosted routing engine Docker setup
├── energy/
│   ├── calc_energy_consumption.py   # Per-segment energy model
│   └── model.py                     # ENERGY_CALC_VERSION
├── emissions/
│   ├── model.py                     # EMISSIONS_MODEL_VERSION + flat per-mode GHG factors + mode-shift shares
│   └── README.md                    # Emissions model documentation (sources, consumers, roadmap)
├── compositions/
│   ├── model.py                     # COMPOSITIONS_MODEL_VERSION — cost calibration anchor (calib/CALIBRATION.md)
│   │                                #   also the source of the loco_types catalog
│   └── calib/                       # Calibration notebooks, data, and CALIBRATION.md
├── infrastructure/
│   ├── model.py                     # INFRA_MODEL_VERSION + WEEKDAY_BLEND
│   ├── STOP_CLASSIFICATION.md       # Stop catalog classification pipeline
│   ├── tac/
│   │   ├── calc_tac.py              # Component track access charge per segment
│   │   └── calib/                   # TAC calibration notebooks + TAC_CALIBRATION.md
│   ├── energy_pricing/
│   │   ├── calc_energy_price.py     # Banded traction energy price + catenary charge per segment
│   │   └── calib/                   # Traction energy price + supply charges,
│   │                                #   ENERGY_PRICING_CALIBRATION.md
│   ├── facility/
│   │   ├── calc_facility.py         # Shunting event + stabling occupation with hotel power
│   │   └── calib/                   # FACILITY_CALIBRATION.md
│   ├── route_context/
│   │   └── calib/                   # Terrain, schedule supplement, dwell, HSR access —
│   │                                #   ROUTE_CONTEXT_CALIBRATION.md (no calc module:
│   │                                #   nothing here is a charge)
│   ├── stops/                       # RESERVED — station charge calibration
│   └── README.md                    # The four calibrated domains and their shared contract
└── evaluation/
    ├── calc.py                      # Cost/revenue evaluation → EvaluationResult
    ├── views.py                     # Breakdown aggregation, allocation, normalisation
    ├── summary.py                   # build_summary_row() — §5.4 gallery-KPI derivation (calc response + publish projection)
    ├── model.py                     # CALC_VERSION
    └── README.md                    # Evaluation layer documentation
```

---

## Pipeline

```
plan_route(trip_pair_inputs, loader, router, schedule_mode, proposal_id, proposal_version, scenario_id)
  │
  ├── loader.build_all_compositions()  → CompositionCollection (per composition_id: .get())
  ├── loader.build_all_tracks()       → TrackInfraCollection
  ├── loader.build_all_stops()        → StopInfraCollection
  ├── schedule_mode SWITCH (here)      → timetable.always_daily_schedule() (only mode today)
  │
  │  per TripPair (_build_trip_pair()):
  │  outbound direction (_build_trip()):
  ├── rail_router.route(stops, composition, tracks, routing_mode)  → list[RoutedLeg]
  │     (fullRouting: each leg carries the per-stop traction dynamics
  │     surcharge — accel/brake time loss, routing/dynamics.py — in its own
  │     dynamics_time_min field next to raw driving_time_min; applied inside
  │     route() so auto-stop mini-reroutes get it too; buffer quota applies
  │     to driving and dynamics, strictly after the physics)
  ├── auto_stop_addition SWITCH (here) → "off": step skipped entirely;
  │     "add": timetable.apply_auto_stop_addition(routed_legs, composition,
  │     tracks, stop_infra, router, routing_mode) → stop_ids, routed_legs
  │     (re-routes internally as needed); "suggest": timetable.
  │     suggest_auto_stops(...) → list[AutoStopSuggestion] (nothing added,
  │     nothing rerouted — suggestions bubble up through plan_route()'s
  │     return value for the API layer to serialize). Search + costing is
  │     shared (timetable.find_and_cost_auto_stop_candidates(), catalog
  │     prefiltered to route-touched countries, then to AUTO_STOP_BUFFER_M
  │     of the routed geometry — 10km, model.py). Costing itself is
  │     analytic-first (timetable._analytic_added_time_min(): dwell +
  │     routing/dynamics.py's own accel/brake pair + out-and-back detour
  │     at cruise speed, ZERO router calls) for candidates within
  │     AUTO_STOP_ANALYTIC_DETOUR_M (100m) of the geometry or already over
  │     budget on their analytic lower bound; only genuinely off-path
  │     candidates get a real 3-point mini-reroute (bounded concurrency).
  │     Only ever runs for outbound — see below.
  ├── _check_country_coverage(routed_legs, tracks)                 → raises ValueError if any
  │     transited country has no row at all in input_params.track_infrastructures
  │     (defaulted fields on an existing row are fine)
  ├── timetable_mode SWITCH (here)     → timetable.simple_automatic_timetable(...)
  │     ("simpleAutomatic") or timetable.simple_automatic_fixed_night_timetable(...)
  │     ("simpleAutomaticWithFixedNight", per-leg slack for a stretched night
  │     interval) → stop_inputs, departure_time_min[, slack_per_leg];
  │     both classify stops boarding/night/alighting via the shared
  │     NIGHT_START_MIN/NIGHT_END_MIN rule (model.py)
  ├── calc_energy_consumption(legs, composition)                   → enriches RoutedLeg.energy_kwh
  ├── timetable.build_final_timetable()                            → exact per-stop arrival/departure
  ├── _build_trip_stops_and_legs(...)                              → list[Segment]
  │     (slack_per_leg stamped onto Segment.slack_time_min, fixed-night only)
  ├── timetable.fixed_night_speed_warning(segments, interval)      → TimetableWarning | None
  │     (fixed-night only — interval stretched too slow? informational)
  ├── Trip._create(...)                                            → Trip (outbound)
  │
  │  return direction (_build_trip(), reusing outbound's decision):
  ├── stop_ids = reversed(outbound's final stop list, additions included)
  ├── rail_router.route(...) → list[RoutedLeg]  — still a real call, own physics
  ├── (auto_stop_addition NOT re-run — known_auto_added_stop_ids from outbound
  │     marks Stop.auto_added directly; see _build_trip_pair()'s comment for why)
  ├── ...same remaining steps as outbound...
  ├── Trip._create(...)                                            → Trip (return)
  │
  └── Route._create(schedule, trip_pairs, parkings, shuntings)  → Route

plan_route() returns (Route, RouteProvenance, list[AutoStopSuggestion]) —
suggestions non-empty only for auto_stop_addition="suggest".

distribute_demand(route, utilization_per, fare_per_km_by_class)  → Route (with od_pairs)  [demand/stopgap.py]

evaluate_route(route, tracks, stop_infra)  → EvaluationResult   [evaluation/calc.py]

build_all_views(route, result)             → ViewsBundle         [evaluation/views.py]
```

`models/pipeline.py` is the domain-level dispatch over these steps:
`run_compute()` runs the whole sequence (plan → stopgap demand → evaluate
→ views) for every compute path (`POST /api/proposal/calc`, publish);
`evaluate_and_build_views()` is the post-routing half, for callers that
bring their own `Route`/demand (the DB seed's hand-crafted example,
model-layer tests with controlled demand). Serialization stays out of
`pipeline.py` — that's `api/helpers/proposal_compute.py`.

`timetable_mode`, `schedule_mode`, and `auto_stop_addition` each have their
switch (which named behaviour runs) in `route_factory.py`, at whichever
level owns the relevant context — `schedule_mode` in `plan_route()` (route-
level, shared across every `TripPair`), `timetable_mode` in `_build_trip()`
(per-trip, since departure time is direction-specific); `routing_mode`'s
switch lives with its implementation in `rail_router.py`'s `route()`.
`auto_stop_addition` is a three-value enum (`"off"` / `"add"` / `"suggest"`)
and per-`TripPair`, not per-trip: `_build_trip_pair()` runs the candidate
search + costing once, from outbound, and reuses the result (reversed) for
return, rather than re-running the whole pass for what is physically the
same corridor reversed. This pass was measured as the dominant cost of
planning a route through the post-ONTD, 575-stop catalog — candidate
mini-reroutes at ~1.5s of router time each, 13-19s of costing per calc on
a 3-stop request (2026-08-06, `test_20_route_content.py::TestRouteGeometry`
went from 5s to 48s once the catalog grew from 58 to 575 stops). Fixed by
costing analytically wherever the router's own answer is knowable in
advance (see the pipeline diagram above) rather than by holding fewer
candidates — the search itself prefilters the catalog to route-touched
countries, read straight off the legs' country shares the router already
attributed, then to `AUTO_STOP_BUFFER_M` of the geometry. Return still gets its
own real routing call for its own (possibly asymmetric) physical path; only
the decision of *which stops to add* (or *which to suggest*) is shared, not
the routing. Accepted trade-off: return no longer gets an independent
detour-budget check against its own baseline trip time (see
`OPEN_TODOS["return_detour_budget"]` in `route/model.py`). `timetable.py`
holds one function per named behaviour and never branches on the mode/flag
itself — see that module's docstring. `VALID_TIMETABLE_MODES` /
`VALID_SCHEDULE_MODES` / `VALID_AUTO_STOP_ADDITION_MODES` in `timetable.py`
and `VALID_ROUTING_MODES` in `rail_router.py` are the single sources of
truth both the compute request validation
(`api/helpers/proposal_compute.py`) and the switches read from. Every
standard value the route model assumes (mode defaults, mirror time,
auto-stop thresholds, schedule constants) and every open TODO on the route
model are consolidated in `route/model.py` (`STANDARD VALUES` /
`OPEN_TODOS`); the stopgap demand parameters live in
`demand/model.py`.

---

## Separation of concerns

| Layer | Responsibility |
|---|---|
| `pipeline.py` | Domain-level dispatch: plan → demand → evaluate → views, one implementation for every compute path |
| `route_factory.py` | Sole constructor for `Trip`, `TripPair`, `Route` — orchestrates the full planning pipeline |
| `demand/stopgap.py` | Stopgap demand model — populates `TripPair.od_pairs` |
| `rail_router.py` | HTTP calls to routing engine, country attribution, buffer computation → `RoutedLeg` |
| `calc_energy_consumption.py` | Energy model — enriches `RoutedLeg.energy_kwh` (how many kWh) |
| `infrastructure/tac/calc_tac.py` | Component track access charge per segment |
| `infrastructure/energy_pricing/calc_energy_price.py` | Traction energy price per segment — banded day/night rate plus the catenary charge (what a kWh costs) |
| `infrastructure/facility/calc_facility.py` | One shunting movement, and one stabling occupation priced on the country's basis against the scheduled layover, plus hotel power |
| `calc.py` | All monetary values — produces flat `EvaluationResult` with one cost object per event |
| `views.py` | Aggregation, allocation, and normalisation — produces `Breakdown` matrices |
| `trip.py` | Physics domain objects: `Stop`, `Segment`, `Trip`, and `Segment.country_windows()` — the clock placement both charge models band against. No monetary values |
| `route.py` | Route container: `Route`, `TripPair`, `Parking`, `Shunting`, `ODPair`, `Schedule` |
| `params.py` | Immutable parameter dataclasses loaded from DB |

**Strict boundary:** `Trip` and `Route` carry physics only. All EUR values live
exclusively in `calc.py`. All serialization lives in `api/helpers/` — split by
domain into `route_serialize.py`, `evaluation_serialize.py`, `params_serialize.py`,
`proposal_serialize.py`, `feedback_serialize.py`, and `scenario_serialize.py`.

---

## Key domain objects

### Trip and Route

`Stop` — one stop call on a trip. `country_code` from `StopInfrastructure`.
`stop_type` is `BOARDING`, `ALIGHTING`, or `BOTH` — controls which OD pairs
are valid and whether station charges apply. `auto_added` is `True` for a
stop inserted by `auto_stop_addition` rather than supplied by the caller.

`Segment` — one leg between two consecutive stops. Carries physics:
`distance_m`, `driving_time_min`, `buffer_time_min`, `energy_kwh`,
`country_distance_shares`, `country_time_shares`.

`TripPair` — outbound + return trip sharing one `Composition`. Carries `od_pairs`
(demand for this pair) and `composition` (cost parameters).

`Route` — container for trip pairs, schedule, parkings, and shuntings.
`Route.countries` derives all countries from segment shares and stop locations.
`Route.shuntings` lists one `Shunting` per trip terminal (no deduplication).
`Route.parkings` lists one `Parking` per unique terminal stop (deduplicated).

### Parking and Shunting

`Parking` — overnight stabling. One per unique terminal stop across all trips.
Has `trip_ids` listing which trips park there. Cost rate from `TrackInfrastructure.parking_eur_day`.

`Shunting` — coupling/uncoupling movement. One per trip terminal, not deduplicated.
Has `trip_id`. Cost rate from `TrackInfrastructure.shunting_eur_event`.

### ODPair

`ODPair` — annual demand for one origin→destination×class combination on one trip.
Lives on `TripPair.od_pairs`. `places_sold` is annual (per-trip demand = `places_sold / operating_days`).
Valid OD pairs have a `BOARDING`/`BOTH` origin and `ALIGHTING`/`BOTH` destination.

---

## ID convention

GTFS-compatible string IDs:

```
route_id : P{proposal_id}_V{proposal_version}_R1
trip_id  : P{proposal_id}_V{proposal_version}_R1_D{direction}_T{index}

e.g. P1_V1_R1       — route for proposal 1, version 1
     P1_V1_R1_D0_T1 — outbound trip
     P1_V1_R1_D1_T1 — return trip
```

`proposal_id` is stable across versions. `proposal_version` increments on every change.

`route_factory.py` itself only ever sees concrete ints for both.
Ephemeral compute (`POST /api/proposal/calc`, `adapters/proposal/README.md`
§2.1) passes the fixed neutral placeholders `NEUTRAL_PROPOSAL_ID`/
`NEUTRAL_PROPOSAL_VERSION` (both `0`, `models/route/model.py`): that
endpoint never persists, so there's no collision risk — the `P0_V0_`
prefix exists only for the instant it takes `rewrite_id_prefix()`
(`adapters/proposal/id_prefix.py`) to strip it back off into the neutral
`R1`/`R1_D0_T1`/... IDs the merged response returns. Publish
(`adapters/proposal/repository.py`) then rewrites those bare structural
ids up to the real `P{proposal_id}_V{version}_` prefix.

`RouteProvenance` (returned alongside the `Route` by `plan_route()`)
carries `compositions` and `stop_infra` alongside `tracks`, so the
pipeline's evaluate step reuses what `plan_route()` already built
internally instead of a second DB/catalog load.

---

## Unit conventions

| Quantity | Unit | Suffix |
|---|---|---|
| Distance | metres | `_m` |
| Duration | minutes | `_min` |
| Clock time | minutes from midnight day 1 | `_min` |
| Energy | kWh | `_kwh` |
| Cost | EUR | `_eur` |
| Share / rate | dimensionless | `_per` |

---

## Energy model

Energy consumption is estimated per segment using a regression model:

```
energy_kwh = total_weight_t × distance_km × (
    factor_weight
    + factor_speed   × avg_speed_kmh²
    + factor_terrain × terrain_score
)
```

Coefficients are stored on `CompositionType`. Terrain score comes from
`TrackInfrastructure` per country. **Currently using a flat 28.0 kWh/km
dummy factor** — calibration against Deutsche Bahn Trassenfinder data is pending.
See `models/energy/README.md` for calibration guidance.