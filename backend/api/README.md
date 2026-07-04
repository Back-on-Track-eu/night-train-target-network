# Night Train — Backend API Reference

**V.901.3** — Base URL: `http://localhost:5000`

---

## Endpoints

### Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Liveness check — returns 200 if API process is running |

**Response**
```json
{"status": "ok"}
```

---

### Auth ⚠️ NOT YET IMPLEMENTED

> These endpoints are stubbed and return `501 Not Implemented`.
> Phase 5 will implement OTP/magic-link JWT auth.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/auth/request-code` | Send OTP to email address |
| `POST` | `/api/auth/verify` | Verify OTP and return JWT token |

---

### Feedback ⚠️ NOT YET IMPLEMENTED

> Stubbed — returns `501 Not Implemented`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/feedback` | Submit feedback on a model parameter |

---

### Scenarios ⚠️ NOT YET IMPLEMENTED

> Stubbed — returns `501 Not Implemented`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/scenario` | Save a new scenario |
| `GET` | `/api/scenarios` | List scenarios |
| `GET` | `/api/scenario/<id>` | Load a scenario by ID |

---

### Input Parameters

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/params/StopInfrastructures` | All stops with id, name, country, coordinates |
| `GET` | `/api/params/compositions` | All composition types with full parameters |
| `GET` | `/api/params/TrackInfrastructures` | All country track infrastructure parameters |

No request body — all are read-only GET endpoints.

Parameter fields (e.g. `tac_eur_train_km`, `parking_eur_day`) are returned as
field objects with provenance:

| Field | Type | Description |
|-------|------|-------------|
| `value` | number | Resolved parameter value |
| `is_default` | bool | `true` if resolved from the defaults table |
| `version` | int | DB row version of the source row |
| `source` | object | `{source_id, source_description, source_url}` |
| `description` | string | Column description from DB |

---

### Route

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/route/plan` | Plan a route — stateless, always a full build (no in-place adjust) |

**`POST /api/route/plan` — Request body**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `proposal_id` | int | — | Only set when replanning an already-saved proposal. Omit for a brand new proposal — a random placeholder id above one billion is assigned automatically and `proposal_version` is forced to `1` |
| `proposal_version` | int | — | See `proposal_id`. Ignored if `proposal_id` is omitted |
| `scenario_id` | int | — | Pins which version of every parameter table to use. Omit for the current live base scenario |
| `stops` | array of string | ✓ | Ordered list of stop IDs, min 2 — plain strings, e.g. `["DE_BERLIN_HBF", "AT_WIEN_HBF"]`. No per-stop type or time; both are derived automatically, see `timetable_mode` |
| `composition_id` | string | ✓ | From `/api/params/compositions` |
| `routing_mode` | string | — | Default `"fullRouting"` — see **Mode switches** below |
| `timetable_mode` | string | — | Default `"simpleAutomatic"` — see **Mode switches** below |
| `schedule_mode` | string | — | Default `"alwaysDaily"` — see **Mode switches** below |
| `auto_stop_addition` | bool | — | Default `false` — see **Mode switches** below |

**Example request**
```json
{
  "proposal_id": null,
  "proposal_version": null,
  "scenario_id": null,
  "stops": ["DE_BERLIN_HBF", "DE_DRESDEN_HBF", "AT_WIEN_HBF"],
  "composition_id": "STD-7.1",
  "routing_mode": "fullRouting",
  "timetable_mode": "simpleAutomatic",
  "schedule_mode": "alwaysDaily",
  "auto_stop_addition": false
}
```

**Mode switches**

`routing_mode` — controls how much routing complexity is applied:

| Value | Description |
|---|---|
| `"fullRouting"` (default) | HSR avoidance and speed cap derived automatically from the composition's `hsr_allowed`/`max_speed_kmh` and each transited country's `hsr_allowed` flag. Two-pass routing (snap pass, then custom-model pass) when avoidance actually applies. |
| `"simpleRouting"` | Bypasses all of that — single-pass, no speed cap, no HSR avoidance. Cheap and fast, but not representative of real physics. Intended for quick manual sanity checks only. |

`timetable_mode` — controls how departure time and boarding/alighting are derived:

| Value | Description |
|---|---|
| `"simpleAutomatic"` (default, only value) | Routes once, then mirrors the resulting trip duration around a fixed 02:30 constant to get the departure time: everything before 02:30 is a boarding stop, everything at/after is alighting. First stop is always boarding and last is always alighting regardless of clock time — they're termini by position, not by the mirror rule. Outbound and return are scheduled independently, so their departure times can differ (e.g. asymmetric HSR avoidance changes duration). |

`schedule_mode` — controls the route's seasonal operating frequency:

| Value | Description |
|---|---|
| `"alwaysDaily"` (default, only value) | Daily frequency in both seasons, regardless of actual demand. Reserved: a future demand-aware strategy can be added without changing this request shape. |

`auto_stop_addition` — whether to propose additional stops along the routed path:

| Value | Description |
|---|---|
| `false` (default) | No-op. |
| `true` | Accepted and validated, but not yet implemented — currently still a no-op. Reserved for a future implementation that looks along the routed path for stops worth adding beyond what was supplied. |

**Response**

```json
{
  "route_builder_version": "1.0.0",
  "request": { "...": "the request body above, echoed back unchanged" },
  "route": {
    "route_id": "P1573795219_V1_R1",
    "scenario_id": 1,
    "schedule": {
      "seasonal_schedules": [
        { "season": "summer", "frequency": "daily" },
        { "season": "winter", "frequency": "daily" }
      ]
    },
    "trip_pairs": [
      {
        "composition_id": "STD-7.1",
        "composition": { "...": "physics-relevant Composition fields, see below" },
        "od_pairs": [],
        "outbound": { "trip_id": "P..._D0_T1", "direction": 0, "segments": [ "...Segment, see below..." ] },
        "return_trip": { "trip_id": "P..._D1_T1", "direction": 1, "segments": [ "..." ] }
      }
    ],
    "parkings": [
      { "stop_id": "...", "stop_name": "...", "country_code": "...", "trip_ids": ["..."] }
    ],
    "shuntings": [
      { "stop_id": "...", "stop_name": "...", "country_code": "...", "trip_id": "..." }
    ],
    "track_infrastructure": [
      { "...": "one entry per country the route actually touches, see below" }
    ],
    "geometries": [
      { "id": "P..._D0_T1_L0", "coords": [[13.366, 52.523, "..."]] }
    ]
  }
}
```

`od_pairs` is always empty from this endpoint — demand is a separate step
(`distribute_demand()`), not part of planning. `route_id`/`trip_id` follow
`P{proposal_id}_V{version}_R1[_D{direction}_T{pair_index}]`.

**`route.trip_pairs[].composition`** — physics-relevant subset of the composition
used, not the full object (cost fields like `driver_costs_eur_h` are deliberately
excluded — see `/api/evaluation/calc` for those):

| Field | Description |
|---|---|
| `comp_id`, `comp_description`, `operator_id` | Identity |
| `max_speed_kmh`, `hsr_allowed` | Routing inputs |
| `min_boarding_time_min`, `min_alighting_time_min` | Dwell time inputs |
| `energy_factor_weight`, `energy_factor_speed`, `energy_factor_terrain` | Energy model inputs |
| `total_weight_t`, `total_crew` | Physical properties |
| `places_by_class`, `density_by_class` | Capacity, keyed by service class |

**`segments[]`** (on `outbound`/`return_trip`) — one entry per leg between two consecutive stops:

| Field | Type | Description |
|---|---|---|
| `from_stop`, `to_stop` | object | `Stop`, see below |
| `geometry_id` | string | References an entry in `route.geometries` — see below |
| `distance_m` | int | Leg distance |
| `driving_time_min`, `buffer_time_min` | int | Leg duration components |
| `energy_kwh` | float | Currently a flat 28.0 kWh/km dummy factor — not calibrated yet |
| `country_distance_shares`, `country_time_shares` | object | `{country_code: share}`, each sums to 1.0. Includes transit-only countries the leg crosses without stopping |

**`Stop`** (embedded in every `from_stop`/`to_stop`):

| Field | Type | Description |
|---|---|---|
| `stop_id`, `stop_name`, `country_code`, `lat`, `lon` | | Identity/location |
| `stop_type` | string | `"boarding"`, `"alighting"`, or `"both"` — see `timetable_mode` above |
| `arrival_time_min` | int or null | `null` only at the first stop of a trip |
| `departure_time_min` | int or null | `null` only at the last stop of a trip |

**`route.track_infrastructure[]`** — one entry per country the route's stops
and transited legs actually touch (not every country in the DB), physics-relevant
subset of `TrackInfrastructure` (cost fields like `tac_eur_train_km` excluded):

| Field | Type | Description |
|---|---|---|
| `country_code` | string | |
| `defaulted_fields` | array of string | Which of the fields below came from the EU-average default rather than this country's own seeded data. Empty if all real. A route through a country with **no row at all** in `track_infrastructures` is rejected outright with a `422 domain_error` — see **Error responses** — so `defaulted_fields` only ever reflects individual missing columns on an existing row, never a whole missing country |
| `hsr_allowed` | bool | |
| `min_boarding_time_min`, `min_alighting_time_min` | int | |
| `terrain_score`, `terrain_category` | float, string | |
| `buffer_quota_per` | float | |

**`route.geometries[]`** — every segment's full coordinate polyline, pulled out of
`segments[]` into one flat list rather than embedded inline (same total data,
easier to scan the rest of the route without wading through coordinate arrays):

| Field | Type | Description |
|---|---|---|
| `id` | string | Matches a `segments[].geometry_id` |
| `coords` | array | `[[lon, lat], ...]` |

---

### Evaluation

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/evaluation/calc` | Run full cost and revenue evaluation |

**`POST /api/evaluation/calc` — Request body**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `route` | object | ✓ | Route JSON from `/api/route/plan` with `od_pairs` populated |

Demand is embedded in the route JSON under `trip_pairs[].od_pairs`:

```json
{
  "route": {
    "route_id": "P1_V1_R1",
    "schedule": { ... },
    "trip_pairs": [
      {
        "composition_id": "STD-7.1",
        "od_pairs": [
          {
            "origin_stop_id":      "AT_WIEN_HBF",
            "destination_stop_id": "DE_BERLIN_HBF",
            "class_main":          "Couchette",
            "trip_id":             "P1_V1_R1_D0_T1",
            "places_sold":         40,
            "avg_price":           89.0
          }
        ],
        "outbound": { ... },
        "return_trip": { ... }
      }
    ],
    "parkings": [ ... ],
    "shuntings": [ ... ]
  }
}
```

`od_pairs` item fields:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `origin_stop_id` | string | ✓ | Must be a boarding or both-type stop in the trip |
| `destination_stop_id` | string | ✓ | Must be an alighting or both-type stop in the trip |
| `class_main` | string | ✓ | `"Seat"`, `"Couchette"`, `"Sleeper"`, `"Capsule"`, or `"Catering"` |
| `trip_id` | string | ✓ | Trip this OD pair belongs to (outbound or return) |
| `places_sold` | int | ✓ | Annual tickets sold for this OD pair (≥ 0) |
| `avg_price` | float | ✓ | Average ticket price in EUR (≥ 0) |

**Response**

```json
{
  "calc_version": "...",
  "result": {
    "route_id": "P1_V1_R1",
    "views": {
      "route":                      { <normalised breakdown> },
      "per_trip_pair":              { "<pair_key>": { <normalised breakdown> }, "all": { ... } },
      "per_trip_pair_per_country":  { "<pair_key>": { "<country_code>": { <normalised breakdown> }, "all": { ... } }, "all": { ... } },
      "per_trip_pair_per_od":       { "<pair_key>": { "<od_key>": { <normalised breakdown> }, "all": { ... } }, "all": { ... } },
      "per_trip_per_stop":          { "<trip_id>": { "<stop_id>": { <normalised breakdown> }, "all": { ... } }, "all": { ... } }
    }
  }
}
```

Each normalised breakdown contains five views:

| Key | Unit | Description |
|-----|------|-------------|
| `per_year` | €/year | Annual totals |
| `per_operating_day` | €/operating-day | Per day the service runs |
| `per_trip_km` | €/km | Per km of total trip distance (both directions) |
| `per_available_place_km` | €/available-place-km | Per capacity × distance |
| `per_sold_place_km` | €/sold-place-km | Per actual passenger × distance |

Each view is a nested cost/revenue/margin breakdown:

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

`od_key` format: `"{origin_stop_id}__{destination_stop_id}__{class_main}"`

See `models/evaluation/README.md` for full documentation of the evaluation model,
cost allocation rules, and view semantics.

---

## Error responses

| Status | `error` key | Meaning |
|--------|-------------|---------|
| `400` | `bad_request` | Request body is not valid JSON |
| `400` | `validation_error` | Invalid or missing fields — see `details` array |
| `422` | `domain_error` | Valid request but pipeline failed (e.g. unknown stop, no route found, route passes through a country with no row in `track_infrastructures` at all) |
| `500` | `route_error` | Unexpected error in route builder |
| `500` | `calc_error` | Unexpected error in evaluation |
| `503` | `infrastructure_error` | DB unreachable or unknown composition ID |
| `501` | `not_implemented` | Endpoint exists but is not yet implemented |