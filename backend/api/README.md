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

### Auth

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/auth/request-code` | Register a new user or log in an existing one — sends OTP by email |
| `POST` | `/api/auth/verify` | Verify OTP and return a JWT |
| `POST` | `/api/auth/guest` | Create an anonymous guest session — no email required |

**`POST /api/auth/request-code` — Request body**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `email` | string | ✓ | User email address |
| `display_name` | string | ✓ for new accounts | Chosen public name — must be unique. Required when registering; ignored on subsequent logins |

**Response** — always `200 {}` (no information leaked about whether the account exists).

| Status | `error` key | Meaning |
|--------|-------------|---------|
| `200` | — | OTP sent (or silently skipped if email send failed and retries exhausted) |
| `400` | `bad_request` | Missing/invalid fields or display_name already taken |
| `502` | `email_failed` | OTP email could not be sent |

---

**`POST /api/auth/verify` — Request body**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `email` | string | ✓ | User email address |
| `code` | string | ✓ | 6-digit OTP received by email |

**Response**
```json
{"token": "...", "user_id": 42, "display_name": "railfan42", "is_guest": false}
```

| Status | `error` key | Meaning |
|--------|-------------|---------|
| `200` | — | JWT issued |
| `400` | `bad_request` | Missing fields |
| `401` | `invalid_code` | Wrong, expired, or already-used code |

---

**`POST /api/auth/guest` — No request body**

**Response**
```json
{"token": "...", "user_id": 99, "display_name": "guest_a3f9k2", "is_guest": true}
```

Guest tokens expire after 30 days. Guest proposals can later be claimed by a registered user.

| Status | `error` key | Meaning |
|--------|-------------|---------|
| `200` | — | Guest JWT issued |
| `500` | `internal_error` | Could not generate a unique guest name |

---

**Using the JWT**

Include the token in the `Authorization` header on all authenticated requests:
```
Authorization: Bearer <token>
```

Endpoints decorated with `@require_auth` return `401` if the token is missing or invalid.
Endpoints decorated with `@optional_auth` work without a token but have richer behaviour when authenticated.

---

### Feedback ⚠️ NOT YET IMPLEMENTED

> Stubbed — returns `501 Not Implemented`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/feedback` | Submit feedback on a model parameter |

**`POST /api/feedback` — Request body**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `param_key` | string | ✓ | Parameter key e.g. `"track_infra:DE:tac_eur_train_km"` |
| `message` | string | ✓ | Feedback text |
| `attachment` | object | — | Optional data attachment |

---

### Scenarios ⚠️ NOT YET IMPLEMENTED

> Stubbed — returns `501 Not Implemented`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/scenario` | Save a new scenario (always inserts, never updates) |
| `GET` | `/api/scenarios` | List current scenarios (id, name, summary metrics) |
| `POST` | `/api/scenarios` | Filtered list of scenarios with pagination |
| `GET` | `/api/scenario/<id>` | Load a saved scenario by ID |

**`POST /api/scenario` — Request body**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | ✓ | Scenario name |
| `route` | object | ✓ | `Route.to_dict()` output |
| `evaluation` | object | ✓ | `EvaluationResult.to_dict()` output |

**`POST /api/scenarios` — Request body (filtered list)**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `limit` | int | — | Max results: 10, 20, or 50. Default 10 |
| `offset` | int | — | Pagination offset. Default 0 |

---

### Input Parameters

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/params/StopInfrastructures` | All stops with id, name, country, coordinates |
| `GET` | `/api/params/compositions` | All composition types with full parameters |
| `GET` | `/api/params/TrackInfrastructures` | All country track infrastructure parameters |

No request body — all are read-only GET endpoints.

**`GET /api/params/StopInfrastructures` — Response fields (per stop)**

| Field | Type | Description |
|-------|------|-------------|
| `stop_id` | string | Unique stop identifier |
| `name` | string | Display name |
| `country_code` | string | ISO 3166-1 alpha-2 |
| `lat` | float | WGS-84 latitude |
| `lon` | float | WGS-84 longitude |
| `stop_charge_eur` | field object | Station access charge — may be resolved from country/global default, see field object structure below |

Parameter field object structure — used for `stop_charge_eur` and all track infrastructure fields. Identity/location fields (`stop_id`, `name`, `country_code`, `lat`, `lon`) are always plain values and never defaulted:

| Field | Type | Description |
|-------|------|-------------|
| `value` | number | The resolved parameter value |
| `is_default` | bool | `true` if this value was resolved from `track_infrastructure_defaults` or `stop_infrastructure_defaults` because the country/stop-specific value was NULL |
| `version` | int | DB row version of the source — from the country/stop row if `is_default=false`, from the defaults table if `is_default=true` |
| `source.source_id` | string | Data source identifier |
| `source.source_description` | string | Human-readable source description |
| `source.source_url` | string | URL to source document |
| `description` | string | Column description from DB |

**`GET /api/params/compositions` — Response fields (per composition)**

| Field | Type | Description |
|-------|------|-------------|
| `comp_id` | string | Unique composition identifier |
| `description` | string | Human-readable description |
| `operator_id` | string | Operating company ID |
| `routing.total_weight_t` | float | Gross train weight in tonnes |
| `routing.max_speed_kmh` | float | Maximum operational speed |
| `routing.hsr_allowed` | bool | Whether HSR infrastructure may be used |
| `routing.min_boarding_time_min` | int | Minimum dwell time at boarding stops (min) |
| `routing.min_alighting_time_min` | int | Minimum dwell time at alighting stops (min) |
| `routing.driver_factor` | float | Number of drivers required |
| `energy.factor_weight` | float | Energy regression: weight-distance coefficient |
| `energy.factor_speed` | float | Energy regression: speed-squared coefficient |
| `energy.factor_terrain` | float | Energy regression: terrain score coefficient |
| `capacity` | object | `{class_main: {places, density}}` per service class |
| `ebit_margin_per` | float | Required EBIT margin as share of revenue |
| `fixed_costs.*` | float | Amortisation, financing, cleaning, overhead (EUR/day) |
| `variable_km.*` | float | Maintenance rates (EUR/km) |
| `variable_hour.*` | float | Staff rates (EUR/h) and overhead hours |
| `variable_ticket.*` | object | Service stockings per place by class, var overhead rate |
| `indicative` | object or null | Pre-computed indicative KPIs from a reference trip — see below. `null` if no reference row exists |

**Indicative KPIs** (computed at load time using the same model as `/api/evaluation/calc`, based on a reference trip stored in `input_params.composition_references`):

| Field | Unit | Description |
|-------|------|-------------|
| `cost_eur_per_seat_km` | €/seat-km | Total cost per available seat-km on reference trip |
| `cost_eur_per_place_km` | €/place-km | Total cost per density-weighted place-km on reference trip |
| `subsidy_eur_per_pax_km` | €/pax-km | Estimated subsidy needed per sold passenger-km at reference load |
| `breakeven_load_factor` | 0.0–1.0 | Load factor needed to break even at reference fares |

**`GET /api/params/TrackInfrastructures` — Response fields (per country)**

| Field | Type | Description |
|-------|------|-------------|
| `country_code` | string | ISO 3166-1 alpha-2 |
| `tac_eur_train_km` | field object | Track access charge (EUR/train-km) |
| `energy_price_eur_kwh` | field object | Traction electricity price (EUR/kWh) |
| `parking_eur_day` | field object | Overnight stabling fee (EUR/day) |
| `terrain_category` | field object | Flat / Hilly / Mountainous |
| `terrain_score` | field object | Numerical terrain difficulty (energy model input) |
| `hsr_allowed` | field object | Whether HSR infrastructure may be used |
| `min_boarding_time_min` | field object | Infrastructure minimum boarding dwell (min) |
| `min_alighting_time_min` | field object | Infrastructure minimum alighting dwell (min) |
| `buffer_quota_per` | field object | Schedule buffer quota (share of driving time) |

Each field is a parameter field object — see structure in `StopInfrastructures` section above.
When `is_default=true`, the value, source, and version shown come from `track_infrastructure_defaults`
(for track fields) or `stop_infrastructure_defaults` (for stop charges) — not from the country/stop row.
The frontend can display this as e.g. "EU average default" with the defaults table's source and version.

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
| `stops` | array | ✓ for new route | Ordered stop list — see stop object below |
| `composition_id` | string | ✓ for new route | Composition key from `/api/params/compositions` |
| `departure_time` | string | — | Departure time `HH:MM` (supports `00:00`–`47:59` for overnight). Omit to keep existing |
| `route` | object | — | `Route.to_dict()` output from a previous call. Required for adjust; optional for plan with geometry change |
| `stop_type_changes` | object | — | `{stop_id: stop_type}` — update stop types without rerouting |

Stop object:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `stop_id` | string | ✓ | Stop key from `/api/params/StopInfrastructures` |
| `stop_type` | string | ✓ | `"boarding"`, `"alighting"`, or `"both"` |

**Response**

| Field | Type | Description |
|-------|------|-------------|
| `route_builder_version` | string | Route model version |
| `action_taken` | string | `"plan"` or `"adjust"` — what the backend decided to do |
| `route` | object | Full `Route` object — pass this to `/api/evaluation/calc` |

---

### Evaluation

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/evaluation/calc` | Run full cost and revenue evaluation |

**`POST /api/evaluation/calc` — Request body**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `route` | object | ✓ | `Route.to_dict()` output from `/api/route/planOrUpdate` |
| `route_demand` | object | ✓ | OD-pair demand — see structure below |
| `operating_days_year` | int | ✓ | Operating days per year (1–366) |

`route_demand` structure — keyed by `trip_id`:
```json
{
  "P1_V1_R1_D0_T1": {
    "od_pairs": [
      {
        "origin_stop_id":      "AT_WIEN_HBF",
        "destination_stop_id": "DE_HAMBURG_HBF",
        "class_main":          "Couchette",
        "places_sold":         40,
        "avg_price":           89.0
      }
    ]
  }
}
```

`od_pairs` item fields:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `origin_stop_id` | string | ✓ | Origin stop — must match a stop in the route |
| `destination_stop_id` | string | ✓ | Destination stop — must match a stop in the route |
| `class_main` | string | ✓ | `"Seat"`, `"Couchette"`, `"Sleeper"`, `"Capsule"`, or `"Catering"` |
| `places_sold` | int | ✓ | Number of places sold for this OD pair (≥ 0) |
| `avg_price` | float | ✓ | Average ticket price in EUR (≥ 0) |

**Response**

| Field | Type | Description |
|-------|------|-------------|
| `calc_version` | string | Calc model version |
| `calc_formulas` | object | `{key: {latex, description}}` — full formula registry |
| `model_versions` | object | `{model_name: version}` — all model versions used |
| `param_versions` | object | `{table:entity:field: {value, version, is_default, source, description}}` — full parameter provenance |
| `operating_days_year` | int | Operating days used for annual normalisation |
| `parking_eur` | float | Route-level parking cost per day |
| `summary` | object | Route-level normalised matrix |
| `by_trip` | array | Per-trip normalised matrices |
| `by_country` | object | Per-country normalised matrices (infrastructure costs only) |
| `by_od` | array | Per-OD-pair normalised matrices |

Each normalised matrix contains 10 views:
`per_day`, `per_year`, `per_trip`, `per_trip_km`,
`per_available_place_km`, `per_sold_place_km`,
`per_available_place_of_class`, `per_sold_place_of_class`,
`per_available_place_km_of_class`, `per_sold_place_km_of_class`

Each view contains the full cost/revenue breakdown with `calc_steps` (formula key + actual input values + result).

---

## Error responses

| Status | `error` key | Meaning |
|--------|-------------|---------|
| `400` | `bad_request` | Request body is not valid JSON |
| `400` | `validation_error` | Invalid fields — see `details` array |
| `401` | `unauthorized` | Missing or invalid JWT |
| `401` | `invalid_code` | Wrong, expired, or already-used OTP |
| `422` | `domain_error` | Valid request but pipeline failed (e.g. unknown stop, no route found) |
| `429` | `rate_limited` | Too many requests — wait and retry |
| `500` | `route_error` | Unexpected error in route builder |
| `500` | `calc_error` | Unexpected error in evaluation |
| `500` | `internal_error` | Unhandled exception |
| `501` | `not_implemented` | Endpoint exists but is not yet implemented |
| `502` | `email_failed` | OTP email could not be sent |
| `503` | `data_not_loaded` | Database not available |

All errors are logged to `admin.api_request_log`. 4xx and 5xx rows include the full request body as JSONB.