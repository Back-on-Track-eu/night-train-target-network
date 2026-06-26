# Night Train — Backend Model Layer

This folder contains the domain model for evaluating night train route economics.

---

## Architecture

```
models/
├── params.py                        # Shared parameter dataclasses (loaded from DB)
├── utils.py                         # Shared unit conversion and geography utilities
├── route/
│   ├── trip.py                      # Trip, TripPath, TripSegment, CountryLeg, StopTime
│   ├── route.py                     # Route, ParkingLocation, RouteStats
│   ├── route_factory.py             # plan_route() and adjust_route() sole constructors
│   └── routing/
│       ├── rail_router.py           # OpenRailRouting (GraphHopper) wrapper
│       └── docker/                  # Self-hosted routing engine Docker setup
├── energy/
│   ├── calc_energy_consumption.py   # Per-country-leg energy model
│   └── version.py                   # ENERGY_CALC_VERSION
└── cost_rev_eval/
    ├── calc.py                      # Cost/revenue evaluation
    └── version.py                   # CALC_VERSION
```

---

## Pipeline

```
plan_route(proposal_id, proposal_version, stop_inputs, composition_id, departure_time_min, loader, router)
  |
  +-- loader.build_composition()      -> Composition + ParamVersions
  +-- loader.build_all_tracks()       -> TrackInfraCollection + ParamVersions
  +-- loader.build_all_stops()        -> StopInfraCollection + ParamVersions
  |
  +-- rail_router.route(stops, composition, tracks)   -> TripPath (energy_kwh = 0.0)
  +-- calc_energy_consumption(trip_path, composition) -> enriches CountryLeg.energy_kwh
  +-- _compute_stop_times(stops, trip_path, ...)      -> list[StopTime]
  |
  +-- Trip._create(...) x 2 (outbound + return)
        +-- Route._create(...)                        -> Route
```

For schedule-only changes (departure time, stop types), use `adjust_route()` instead.
It copies the existing TripPath without rerouting.

---

## Separation of concerns

| Layer | Responsibility |
|---|---|
| `route_factory.py` | Sole constructor for Trip and Route — orchestrates the full pipeline |
| `rail_router.py` | HTTP communication with routing engine, country attribution, buffer computation -> TripPath |
| `calc_energy_consumption.py` | Energy model — enriches CountryLeg.energy_kwh in-place |
| `calc.py` | All monetary values — TAC, energy cost, station charges, staff, amortisation, margin |
| `trip.py` | Physics domain object — distances, times, energy. No monetary values |
| `route.py` | Route container — two trips (outbound + return), RouteStats, operator invariant |
| `params.py` | Immutable parameter dataclasses loaded from DB. ParamVersions records field-level provenance |

**Strict boundary:** Trip and Route carry physics only. All EUR values live exclusively in calc.py.

---

## ID convention

GTFS-compatible string IDs derived from the proposal:

```
route_id : P{proposal_id}_V{proposal_version}_R1
trip_id  : P{proposal_id}_V{proposal_version}_R1_D{direction}_T{trip_index}

e.g. P1_V1_R1       -- route for proposal 1, version 1
     P1_V1_R1_D0_T1 -- outbound trip
     P1_V1_R1_D1_T1 -- return trip
```

proposal_version increments on every change. plan_route() produces a fresh route;
adjust_route() copies an existing route with new IDs for the new version.

---

## Unit conventions

| Quantity | Unit | Suffix |
|---|---|---|
| Distance | metres | `_m` |
| Duration | minutes | `_min` |
| Clock time | minutes from midnight day 1 | `_min` |
| Energy | kWh | `_kwh` |
| Cost | EUR | `_eur` |
| Speed | km/h | `_kmh` (derived only) |

Conversions between units live in `models/utils.py`.

---

## Parameter provenance

Every Trip carries `model_versions: ModelVersions` and `param_versions: ParamVersions`.

ParamVersions records one entry per parameter field used in the computation, keyed
by `"table_short:entity_id:field_name"` e.g. `"track_infra:DE:tac_eur_train_km"`.
Each entry carries the DB row version, source, and column description from the DB —
enabling full reproducibility and transparent frontend display.

---

## Energy model

Energy consumption is estimated per country leg:

```
energy_kwh = total_weight_t x distance_km x (
    energy_factor_weight
    + energy_factor_speed  x avg_speed_kmh^2
    + energy_factor_terrain x terrain_score
)
```

Energy factor coefficients are stored on CompositionType in the DB.
Terrain score comes from TrackInfrastructure per country.

Note: The energy regression coefficients require calibration against real
consumption data (Deutsche Bahn Trassenfinder). Calibration is deferred.