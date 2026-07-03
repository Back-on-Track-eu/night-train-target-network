# Night Train — Evaluation Layer

This folder contains the cost and revenue evaluation pipeline for night train routes.
It is the mathematical core of the project — everything that produces a EUR number lives here.

```
models/evaluation/
├── calc.py      # Cost/revenue calculation → EvaluationResult
├── views.py     # Breakdown aggregation, allocation, normalisation
└── version.py   # CALC_VERSION
```

---

## Concepts

### Canonical unit

Everything in `Breakdown` is **€/year**. Costs computed per-segment or per-event
are multiplied by `operating_days_per_year` at build time. Normalisers then divide
back down to per-day, per-km, or per-place-km as needed.

### Physics vs money

`Trip` and `Route` carry only physics — distances, times, country shares, energy.
All EUR values live exclusively in `calc.py`. This boundary is strict.

### Demand

OD pairs live on `TripPair.od_pairs`. Each `ODPair` specifies annual `places_sold`
and `avg_price` for one origin→destination×class combination on one trip.
The proxy demand model (`distribute_demand()` in `route_factory.py`) distributes
demand uniformly across valid boarding→alighting OD pairs at a given utilisation rate.

---

## calc.py — EvaluationResult

`evaluate_route(route, tracks, stop_infra)` returns a flat `EvaluationResult`
with one entry per segment, stop, parking location, shunting event, composition,
and OD pair. No aggregation, no normalisation — raw per-event costs only.

### Cost structure

| Cost object | Unit | One per |
|---|---|---|
| `SegmentCost` | €/segment | Segment × trip |
| `StopCost` | €/trip-call | Stop × trip (not per adjacent segment) |
| `ParkingCost` | €/operating-day | Parking location (deduplicated by stop) |
| `ShuntingCost` | €/event | Shunting event (one per trip terminal, not deduplicated) |
| `CompositionFleetCost` | €/year (amort/fin/overhead) or €/operating-day (cleaning) | Composition |
| `RouteCost` | €/trip-cycle | Route (loco lease only) |
| `ODPairRevenue` | €/year | OD pair × trip |
| `ODPairCost` | €/year | OD pair × trip (svc_stockings, var_overhead) |
| `ODPairMargin` | €/year | OD pair × trip (EBIT carve-out) |

`SegmentCost` also carries physics fields needed by the view layer:
`driving_time_min`, `country_distance_shares`, `country_time_shares`.

`StopCost` carries `country_code` from `Stop.country_code`.

### Segment passenger loads

`compute_segment_passenger_loads()` pre-computes, for each `(trip_id, segment_index)`,
how many annual passenger place-km and place-hours each OD pair contributes to that
segment. This includes unweighted and density-weighted versions, plus per-country
breakdowns. The result is stored in `EvaluationResult.segment_passenger_loads` and
is the foundation for all OD-proportional cost allocations in the view layer.

---

## views.py — Breakdown tree and views

### Breakdown tree

```
Breakdown (€/year)
├── cost: CostBreakdown
│   ├── operator: OperatorCost
│   │   ├── variable: OperatorVariableCost
│   │   │     driver, crew, coach_maintenance, loco,
│   │   │     svc_stockings, var_overhead
│   │   └── fixed: OperatorFixedCost
│   │         coach_amortisation, financing, fix_overhead,
│   │         cleaning, shunting
│   └── infrastructure: InfrastructureCost
│         tac, energy, station_charge, parking
├── revenue: RevenueBreakdown   ticket_revenue
└── margin:  MarginBreakdown    ebit_margin
```

All nodes support `+=` via `__iadd__` for accumulation. All 17 leaves are €/year.

### Layer 1 — whole route / per trip pair

`build_breakdown(route, result, trip_pair=None)` — canonical annual Breakdown.

`build_breakdown_per_trip_pair(route, result)` — `dict[str, Breakdown]` keyed by
outbound `trip_id`, plus `"all"` for the whole route.

### Layer 2A — per trip pair × country

`build_breakdown_per_trip_pair_per_country(route, result)` —
`dict[tuple[str, str], Breakdown]` keyed by `(pair_key, country_code)`.
`"all"` is a wildcard in either position.

Allocation rules per country:

| Cost | Method |
|---|---|
| `driver`, `crew`, `loco`, `cleaning` | `country_time_shares` |
| `coach_maintenance`, `coach_amortisation`, `financing`, `fix_overhead` | `country_distance_shares` |
| `shunting` | 100% to terminal stop's country (`Shunting.country_code`) |
| `tac`, `energy` | Directly from `SegmentCost` (already split in calc.py) |
| `station_charge` | 100% to `StopCost.country_code` |
| `parking` | 100% to `Parking.country_code` |
| `svc_stockings`, `var_overhead`, `revenue`, `margin` | OD weighted place-km share per country |

### Layer 2B — per trip pair × OD pair

`build_breakdown_per_trip_pair_per_od(route, result)` —
`dict[tuple[str, str], Breakdown]` keyed by `(pair_key, od_key)`.

`od_key` is `"{origin_stop_id}__{destination_stop_id}__{class_main}"` — no
`trip_id` in the key, so Copenhagen→Munich aggregates across both trip pairs
in a Y-shaped route.

Allocation rules per OD pair:

| Cost | Method |
|---|---|
| `coach_maintenance`, `tac`, `energy` | Weighted place-km share per segment |
| `driver`, `crew` | Weighted place-hours share per segment |
| `coach_amortisation`, `financing`, `fix_overhead` | OD distance share of full trip |
| `loco`, `cleaning` | Weighted place-hours share of pair total |
| `station_charge`, `dwell_driver`, `dwell_crew` | `places_sold` share at boarding/alighting stop |
| `shunting`, `parking` | Revenue share (`od_revenue / total_trip_revenue`) |
| `svc_stockings`, `var_overhead`, `revenue`, `margin` | Direct from `ODPairRevenue/Cost/Margin` |

### Layer 2C — per trip × stop

`build_breakdown_per_trip_per_stop(route, result)` —
`dict[tuple[str, str], Breakdown]` keyed by `(trip_id, stop_id)`.

Only boarding and alighting OD pairs are attributed at each stop — through-riders
are invisible at the stop level. Fixed costs are allocated by half the boarding/
alighting OD pairs' weighted place-km relative to the route total (half at origin,
half at destination, so all stops sum to 100%).

### Layer 3 — normalisers

All normalisers take a `Breakdown` and return a new `Breakdown` with every leaf
divided by the denominator. The source `Breakdown` is unchanged.

| Function | Denominator | Result unit |
|---|---|---|
| `normalise(breakdown, denominator)` | Caller-supplied | Arbitrary |
| `normalise_per_operating_day(breakdown, route)` | `operating_days_per_year` | €/operating-day |
| `normalise_per_trip_km(breakdown, route, trip_pair=None)` | Total trip distance km (both directions) | €/km |
| `normalise_per_available_place_km(breakdown, route, trip_pair=None)` | Capacity × distance | €/available-place-km |
| `normalise_per_sold_place_km(breakdown, route, trip_pair=None)` | `places_sold` × distance per OD range | €/sold-place-km |

---

## API integration

The evaluation pipeline is called by `POST /api/evaluation/calc` in `api/evaluation.py`.
Serialization and deserialization are handled exclusively by `api/helpers/serialize.py`.
Domain objects have no `to_dict()` or `from_dict()` methods.

### Request flow

```
POST /api/evaluation/calc
  │
  ├── [1/5] Validate body + route_from_dict(body["route"], loader)
  │          serialize.py: deserializes Route JSON → Route domain object
  │          loader.build_composition() reloads cost params from DB
  │
  ├── [2/5] loader.build_all_tracks() + loader.build_all_stops()
  │
  ├── [3/5] evaluate_route(route, tracks, stop_infra) → EvaluationResult
  │          calc.py: all per-event cost/revenue computation
  │
  ├── [4/5] build_breakdown* functions → Breakdown matrices
  │          views.py: aggregation, allocation, normalisation
  │
  └── [5/5] normalise_all_to_dict + matrix_to_dict → JSON response
             serialize.py: converts Breakdown tree to nested dict
             all 5 normalisations included per cell
```

### Response structure

```json
{
  "calc_version": "...",
  "result": {
    "route_id": "P1_V1_R1",
    "views": {
      "route": {
        "per_year":                { <Breakdown dict> },
        "per_operating_day":       { <Breakdown dict> },
        "per_trip_km":             { <Breakdown dict> },
        "per_available_place_km":  { <Breakdown dict> },
        "per_sold_place_km":       { <Breakdown dict> }
      },
      "per_trip_pair": {
        "P1_V1_R1_D0_T1": { "per_year": {...}, ... },
        "all":             { "per_year": {...}, ... }
      },
      "per_trip_pair_per_country": {
        "P1_V1_R1_D0_T1": {
          "DE": { "per_year": {...}, ... },
          "AT": { "per_year": {...}, ... },
          "all": { "per_year": {...}, ... }
        },
        "all": { "DE": {...}, "all": {...} }
      },
      "per_trip_pair_per_od": {
        "P1_V1_R1_D0_T1": {
          "AT_WIEN_HBF__DE_BERLIN_HBF__Couchette": { "per_year": {...}, ... },
          "all": { "per_year": {...}, ... }
        },
        "all": { "AT_WIEN_HBF__DE_BERLIN_HBF__Couchette": {...}, ... }
      },
      "per_trip_per_stop": {
        "P1_V1_R1_D0_T1": {
          "AT_WIEN_HBF": { "per_year": {...}, ... },
          "all": { "per_year": {...}, ... }
        },
        "all": { "AT_WIEN_HBF": {...}, ... }
      }
    }
  }
}
```

Each `<Breakdown dict>` has this structure:

```json
{
  "cost": {
    "operator": {
      "variable": {
        "driver_eur": 0.0, "crew_eur": 0.0, "coach_maintenance_eur": 0.0,
        "loco_eur": 0.0, "svc_stockings_eur": 0.0, "var_overhead_eur": 0.0,
        "total_eur": 0.0
      },
      "fixed": {
        "coach_amortisation_eur": 0.0, "financing_eur": 0.0,
        "fix_overhead_eur": 0.0, "cleaning_eur": 0.0, "shunting_eur": 0.0,
        "total_eur": 0.0
      },
      "total_eur": 0.0
    },
    "infrastructure": {
      "tac_eur": 0.0, "energy_eur": 0.0,
      "station_charge_eur": 0.0, "parking_eur": 0.0,
      "total_eur": 0.0
    },
    "total_eur": 0.0
  },
  "revenue": { "ticket_revenue_eur": 0.0, "total_eur": 0.0 },
  "margin":  { "ebit_margin_eur": 0.0, "total_eur": 0.0 },
  "total_cost_eur": 0.0,
  "total_revenue_eur": 0.0,
  "net_eur": 0.0
}
```

### Demand in the route JSON

Demand is embedded in the route JSON under `trip_pairs[].od_pairs`. Each OD pair
specifies `trip_id`, `origin_stop_id`, `destination_stop_id`, `class_main`,
`places_sold` (annual), and `avg_price` (EUR). The proxy demand model
(`route_factory.distribute_demand()`) can populate these automatically from a
utilisation rate and per-km fare.

---

## Open items / known limitations

- Energy regression coefficients not yet calibrated — flat 28 kWh/km dummy used
- Y/X-shape routes: `loco_propulsion_min` and `shunting_count` don't yet deduplicate
  shared trunk infrastructure across trip pairs (TODO comments in `route.py`)
- `seat/couchette/sleeper_density` still `0.0` in `DBDataLoader` — deferred
- Per-class normalisation (one `Breakdown` per class) not yet implemented