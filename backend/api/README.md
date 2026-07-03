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
| `POST` | `/api/route/planOrUpdate` | Plan a new route or adjust an existing one |

**`POST /api/route/planOrUpdate` — Request body**

The backend automatically derives whether a full reroute is needed:
- No `route` in body → **plan** (new route)
- `route` in body, same stops and composition → **adjust** (schedule/stop-type change only)
- `route` in body, stops or composition changed → **plan** (full reroute)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `proposal_id` | int | ✓ | Proposal ID (stable across versions) |
| `proposal_version` | int | ✓ | Version counter — increment on every change |
| `stops` | array | ✓ for new route | Ordered stop list `[{stop_id, stop_type}, ...]` |
| `composition_id` | string | ✓ for new route | From `/api/params/compositions` |
| `departure_time` | string | — | `HH:MM`, supports `00:00`–`47:59`. Omit to keep existing |
| `route` | object | — | Route JSON from a previous call. Required for adjust |
| `stop_type_changes` | object | — | `{stop_id: stop_type}` — update stop types without rerouting |

Stop types: `"boarding"`, `"alighting"`, `"both"`.

**Response**

| Field | Type | Description |
|-------|------|-------------|
| `route_builder_version` | string | Route model version |
| `action_taken` | string | `"plan"` or `"adjust"` |
| `route` | object | Route JSON — pass this to `/api/evaluation/calc` |

The route JSON embeds all physics (segments, geometry, timetable, country shares)
but no monetary values or demand. Demand (`od_pairs`) must be added before calling
the evaluation endpoint.

---

### Evaluation

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/evaluation/calc` | Run full cost and revenue evaluation |

**`POST /api/evaluation/calc` — Request body**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `route` | object | ✓ | Route JSON from `/api/route/planOrUpdate` with `od_pairs` populated |

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
| `422` | `domain_error` | Valid request but pipeline failed (e.g. unknown stop, no route found) |
| `500` | `route_error` | Unexpected error in route builder |
| `500` | `calc_error` | Unexpected error in evaluation |
| `503` | `infrastructure_error` | DB unreachable or unknown composition ID |
| `501` | `not_implemented` | Endpoint exists but is not yet implemented |