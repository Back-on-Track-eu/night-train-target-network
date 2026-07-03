# Night Train — Backend Model Layer

This folder contains the domain model for evaluating night train route economics.

---

## Structure

```
models/
├── params.py                        # Shared parameter dataclasses (loaded from DB)
├── utils.py                         # Shared unit conversion utilities
├── route/
│   ├── trip.py                      # Stop, Segment, Trip — physics domain objects
│   ├── route.py                     # Route, TripPair, Parking, Shunting, ODPair, Schedule
│   ├── route_factory.py             # plan_route(), adjust_route(), distribute_demand()
│   └── routing/
│       ├── rail_router.py           # OpenRailRouting (GraphHopper) wrapper
│       └── docker/                  # Self-hosted routing engine Docker setup
├── energy/
│   ├── calc_energy_consumption.py   # Per-segment energy model
│   └── version.py                   # ENERGY_CALC_VERSION
└── evaluation/
    ├── calc.py                      # Cost/revenue evaluation → EvaluationResult
    ├── views.py                     # Breakdown aggregation, allocation, normalisation
    ├── version.py                   # CALC_VERSION
    └── README.md                    # Evaluation layer documentation
```

---

## Pipeline

```
plan_route(proposal_id, proposal_version, schedule, trip_pair_inputs, loader, router)
  │
  ├── loader.build_composition()      → Composition
  ├── loader.build_all_tracks()       → TrackInfraCollection
  ├── loader.build_all_stops()        → StopInfraCollection
  │
  ├── rail_router.route(stops, composition, tracks)   → list[RoutedLeg]
  ├── calc_energy_consumption(legs, composition)       → enriches RoutedLeg.energy_kwh
  ├── _build_trip(legs, stops, ...)                   → Trip (outbound)
  ├── _build_trip(legs, stops, ...)                   → Trip (return)
  │
  └── Route._create(schedule, trip_pairs, parkings, shuntings)  → Route

distribute_demand(route, utilization_per, fare_per_km_by_class)  → Route (with od_pairs)

evaluate_route(route, tracks, stop_infra)  → EvaluationResult   [calc.py]

build_breakdown*(route, result)            → Breakdown matrices  [views.py]
```

For schedule-only changes (departure time, stop types), use `adjust_route()`.

---

## Separation of concerns

| Layer | Responsibility |
|---|---|
| `route_factory.py` | Sole constructor for `Trip`, `TripPair`, `Route` — orchestrates the full plan/adjust pipeline |
| `rail_router.py` | HTTP calls to routing engine, country attribution, buffer computation → `RoutedLeg` |
| `calc_energy_consumption.py` | Energy model — enriches `RoutedLeg.energy_kwh` |
| `calc.py` | All monetary values — produces flat `EvaluationResult` with one cost object per event |
| `views.py` | Aggregation, allocation, and normalisation — produces `Breakdown` matrices |
| `trip.py` | Physics domain objects: `Stop`, `Segment`, `Trip`. No monetary values |
| `route.py` | Route container: `Route`, `TripPair`, `Parking`, `Shunting`, `ODPair`, `Schedule` |
| `params.py` | Immutable parameter dataclasses loaded from DB |

**Strict boundary:** `Trip` and `Route` carry physics only. All EUR values live
exclusively in `calc.py`. All serialization lives in `api/helpers/serialize.py`.

---

## Key domain objects

### Trip and Route

`Stop` — one stop call on a trip. `country_code` from `StopInfrastructure`.
`stop_type` is `BOARDING`, `ALIGHTING`, or `BOTH` — controls which OD pairs
are valid and whether station charges apply.

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