# Night Train — Backend API Reference

**V.901.5** — Base URL: `http://localhost:5000`

## Table of Contents

- [Health](#health)
- [Auth](#auth) ⚠️ not yet implemented
- [Feedback](#feedback)
  - [`POST /api/feedback`](#post-feedback) — submit feedback
  - [`GET /api/feedback/categories`](#feedback-categories) — suggested category/sub_category values
- [Proposals](#proposals)
  - [`POST /api/proposal`](#post-proposal) — save a proposal
  - [`GET` / `POST /api/proposals`](#list-proposals) — list proposals
  - [`GET /api/proposal/<id>`](#get-proposal) — load a proposal
- [Input Parameters](#input-parameters)
- [Route](#route)
  - [`POST /api/route/plan`](#route-plan) — plan a route
- [Evaluation](#evaluation)
  - [`POST /api/evaluation/calc`](#evaluation-calc) — cost/revenue evaluation
- [Error responses](#error-responses)

---

<a id="health"></a>

## Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Liveness check — returns 200 if API process is running |

<details>
<summary>Request &amp; response details</summary>

**Response**
```json
{"status": "ok"}
```

</details>

---

<a id="auth"></a>

## Auth ⚠️ NOT YET IMPLEMENTED

> These endpoints are stubbed and return `501 Not Implemented`.
> Phase 5 will implement OTP/magic-link JWT auth.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/auth/request-code` | Send OTP to email address |
| `POST` | `/api/auth/verify` | Verify OTP and return JWT token |

---

<a id="feedback"></a>

## Feedback

No auth yet — a submission identifies its author either by `user_id`
(logged-in) or `email` (anonymous). Every submission is mailed to
`targetnetwork-wg@back-on-track.eu` and stored in `admin.feedback`
either way; mail delivery never blocks storage (see
`adapters/mailer.py`).

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/feedback` | Submit feedback |
| `GET` | `/api/feedback/categories` | Suggested category/sub_category values for the form |

<a id="post-feedback"></a>

### `POST /api/feedback`

<details>
<summary>Request &amp; response details</summary>

**Request body**
```json
{
  "user_id": 1,
  "email": null,
  "subject": "TAC rate for DE looks stale",
  "category": "Infrastructure",
  "sub_category": "tac_eur_train_km",
  "message": "The current DE track access charge doesn't match the 2026 tariff sheet."
}
```
- `user_id` (int) — required unless `email` is given. Must exist in `admin.users`; returns `422 domain_error` otherwise.
- `email` (str) — required unless `user_id` is given. Used as the mail `Reply-To` and, for anonymous submissions, stored on the row.
- `subject` (str, required, max 200 chars)
- `category` (str, required) — free text; see `GET /api/feedback/categories` for suggested values, not a closed enum.
- `sub_category` (str, required) — free text; same rationale as `category`.
- `message` (str, required) — the feedback text.

**Response (201)**
```json
{
  "feedback_id": 42,
  "created_at": "2026-07-10T14:32:00+00:00",
  "email_sent": true
}
```
`email_sent` reflects only whether the notification mail succeeded — the
feedback row is stored regardless (SMTP misconfiguration or an outage
never loses a submission).

**Errors:** `400 bad_request` (missing body) · `400 validation_error`
(missing/invalid field — see `details`) · `422 domain_error` (`user_id`
doesn't exist) · `500 feedback_error` (storage failed).

</details>

<a id="feedback-categories"></a>

### `GET /api/feedback/categories`

<details>
<summary>Request &amp; response details</summary>

Suggested values for the feedback form's category/sub_category fields —
not a validation source, `POST /api/feedback` accepts any non-empty
string for both. Nine categories, four with a `sub_categories` list
derived live from the model's own definitions rather than hand-copied:

| Category | sub_categories source |
|---|---|
| `Infrastructure` | Live — `TrackInfrastructures` + `StopInfrastructures` fields (same collections `GET /api/params/*` serves) |
| `Compositions` | Live — composition/operator/coach fields (`CompositionCollection`) |
| `Evaluation — calculation method` | Live — every leaf of the evaluation model's cost/revenue/margin breakdown (`models/evaluation/views.py:Breakdown`) |
| `Evaluation — results / view` | Live — the five output views `POST /api/evaluation/calc` produces (`models/evaluation/views.py:VIEW_META`) |
| `Route or timetable` | Static — no single schema object maps cleanly onto "route concepts" |
| `General functionality` | Static |
| `Bug report` / `Feature request` / `Other` | None — free text |

`Infrastructure` feedback (a rate looks wrong) is deliberately distinct
from `Evaluation — calculation method` feedback (the rate is *applied*
wrong, e.g. to the wrong distance).

**Query params**
| Param | Type | Description |
|---|---|---|
| `scenario_id` | int (optional) | Pins the parameter versions the `Infrastructure`/`Compositions` lists are built from; omit for the live `is_current_base` scenario. No effect on the other categories. |

**Response (200)**
```json
{
  "categories": [
    {
      "category": "Infrastructure",
      "sub_categories": [
        {"parameter": "tac_eur_train_km", "description": "...", "group": "TrackInfrastructures"},
        {"parameter": "stop_charge_eur", "description": "...", "group": "StopInfrastructures"}
      ]
    },
    {
      "category": "Compositions",
      "sub_categories": [
        {"parameter": "routing.max_speed_kmh", "description": "...", "group": "Compositions"}
      ]
    },
    {
      "category": "Evaluation — calculation method",
      "sub_categories": [
        {"parameter": "cost.operator.variable.driver_eur", "description": "Costs scaling with usage — hours, km, tickets sold.", "group": "cost"},
        {"parameter": "revenue.ticket_revenue_eur", "description": null, "group": "revenue"},
        {"parameter": "margin.ebit_margin_eur", "description": "Target EBIT carve-out — neither cost nor revenue.", "group": "margin"}
      ]
    },
    {
      "category": "Evaluation — results / view",
      "sub_categories": [
        {"parameter": "route", "description": "Whole-route annual totals...", "group": null},
        {"parameter": "per_trip_pair", "description": "...", "group": null}
      ]
    },
    {
      "category": "Route or timetable",
      "sub_categories": [
        {"parameter": "Stops / stations", "description": null, "group": null}
      ]
    },
    {"category": "General functionality", "sub_categories": [{"parameter": "Usability / UX", "description": null, "group": null}]},
    {"category": "Bug report", "sub_categories": []},
    {"category": "Feature request", "sub_categories": []},
    {"category": "Other", "sub_categories": []}
  ]
}
```

</details>

---

<a id="proposals"></a>

## Proposals

Save, list, and load night train proposals. No auth yet — requests carry
`user_id` directly. Every user can see and load every proposal; a save
either creates a new proposal, adds a version to one you own, or branches
a new proposal from one you don't (see below).

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/proposal` | Save a proposal (create / new version / branch) |
| `GET` | `/api/proposals` | List current proposal versions |
| `POST` | `/api/proposals` | Filtered/sorted/paginated list |
| `GET` | `/api/proposal/<id>` | Load the current version of a proposal |

The route — and, if included, its evaluation — are stored twice: verbatim
as JSONB (for an exact, cheap round-trip back to the frontend) and, for
the route, decomposed into GTFS tables
(`proposals.routes`/`trips`/`stop_times`/`shapes`/`services`/`calendar`,
for future export/interop). This duplication is deliberate for now — see
`db/README.md`. Only fully daily schedules (`schedule_mode: "alwaysDaily"`,
the only mode `/api/route/plan` currently supports) can be saved; a
non-daily frequency fails with `422 domain_error`.

**Save posts whole API responses, not hand-picked fields.** `POST
/api/proposal` takes the *entire* `POST /api/route/plan` response
(`route_builder_version` + `request` + `route`, all three) as
`route_body`, and, optionally, the *entire* `POST
/api/evaluation/calc` response (`calc_version` + `route_id` + `models` +
`input` + `views`, all five) as `evaluation_body`. Nothing is
stripped or trimmed before storing — that's why `evaluation_body`
ends up containing a second copy of the route under `input.route`, next
to the one already in `route_body.route`. The server validates
both are structurally complete (every section present, not a partial
object) and, if both are given, that `evaluation_body` genuinely
describes the same route as `route_body` — exact deep equality
of `evaluation_body.input.route` against `route_body.route`,
not just a `route_id` match. A save is rejected with `400
validation_error` if either check fails.

<a id="post-proposal"></a>

### `POST /api/proposal`

**Save semantics** — the posted `route_body.route`'s own
`route_id` (`P{proposal_id}_V{version}_R1`) decides the outcome; rows are
always appended, never updated in place:

| Condition | Action | Result |
|-----------|--------|--------|
| `proposal_id` is a draft placeholder (≥1e9, from `/api/route/plan`) or unknown | `created` | New `proposal_id` (from the sequence), version 1 |
| `proposal_id` exists and `user_id` owns the current version | `versioned` | Same `proposal_id`, version + 1, `is_current` flipped |
| `proposal_id` exists and belongs to a different `user_id` | `branched` | New `proposal_id`, version 1 |

All IDs inside the posted route (`route_id`, trip IDs, geometry IDs, and
every trip reference in `od_pairs`/`shuntings`/`parkings`) share the prefix
`P{proposal_id}_V{version}_` and are rewritten together to the real
`proposal_id`/version — in both `route_body.route` and, if given,
`evaluation_body` (which embeds the same IDs under `input.route` and
as dict keys in several of its `views`). Use the `route_id` returned in
the response from here on, not the one you posted.

<details>
<summary>Request &amp; response details</summary>

**Request body**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `user_id` | int | ✅ | `admin.users` identity of the saver — must already exist |
| `route_body` | object | ✅ | The **entire** `POST /api/route/plan` response — `{route_builder_version, request, route}`, not just `route` |
| `change_log` | string | — | What changed in this version |
| `evaluation_body` | object | — | The **entire** `POST /api/evaluation/calc` response — `{calc_version, route_id, models, input, views}`. Must describe the exact same route as `route_body.route` (see above) — stored as a point-in-time snapshot, not re-derived |

The frontend can spread the `POST /api/route/plan` response straight into
`route_body`, and the `POST /api/evaluation/calc` response
straight into `evaluation_body` if one was run — no field-picking on
either side. A proposal can be saved without `evaluation_body` — its
financial fields are simply null everywhere until a version with one is
saved.

**Response `201`**
```json
{
  "action": "created",
  "proposal": {
    "proposal_id": 5,
    "proposal_version": 1,
    "is_current": true,
    "user_id": 1,
    "user_name": "David",
    "change_log": "initial save",
    "created_at": "2026-07-08T12:00:00+00:00"
  },
  "route_id": "P5_V1_R1"
}
```

</details>

<a id="list-proposals"></a>

### `GET` / `POST /api/proposals`

`GET` returns every current proposal as a summary, newest first. `POST`
accepts filters/sort/pagination.

<details>
<summary>Request &amp; response details</summary>

**Request body** (`POST` only, all fields optional)
```json
{
  "filter": {
    "user_ids": [1],
    "countries": ["CH"],
    "stop_ids": ["CH_ZUERICH_HB"]
  },
  "sort": [{"by": "total_distance_km", "dir": "asc"}],
  "limit": 50,
  "offset": 0
}
```
`sort.by` is one of `created_at`, `total_distance_km`, `total_time_h`,
`total_revenue_eur`, `total_cost_eur`, `margin_eur`. The last three read
from the saved evaluation snapshot (`views.route.data.per_year` — see
`db/README.md`); proposals saved without one report `null` financial
fields and sort as if they were `0` on a financial key, rather than being
excluded. `countries` includes transit-only countries (derived from
segment-level `country_distance_shares`, same as the route response).

**Response**
```json
{
  "total": 12,
  "proposals": [
    {
      "proposal_id": 5, "proposal_version": 2, "is_current": true,
      "user_id": 1, "user_name": "David", "change_log": "...",
      "created_at": "2026-07-08T12:00:00+00:00",
      "name": "Berlin Hbf – Wien Hbf",
      "total_distance_km": 683.4, "total_driving_time_h": 8.3,
      "total_time_h": 9.0, "countries": ["AT", "DE"],
      "stops": [{"stop_id": "DE_BERLIN_HBF", "stop_name": "Berlin Hbf"}, "..."],
      "total_revenue_eur": 45000.0, "total_cost_eur": 32000.0,
      "margin_eur": 13000.0, "margin_per": 0.2889
    }
  ]
}
```
`total_revenue_eur`/`total_cost_eur`/`margin_eur`/`margin_per` are `null`
for any proposal saved without an evaluation. `margin_eur` is the bottom
line after cost, revenue, and the EBIT margin target (`net_eur` in the
evaluation response), not the raw EBIT target itself.

</details>

<a id="get-proposal"></a>

### `GET /api/proposal/<id>`

Always the current version (no history endpoint yet).

<details>
<summary>Request &amp; response details</summary>

No request body. Returns the two stored envelopes directly — the exact
payloads originally posted to `POST /api/route/plan` and `POST
/api/evaluation/calc` (after draft-ID rewriting), unchanged:
```json
{
  "proposal": { "proposal_id": 5, "proposal_version": 1, "...": "..." },
  "route_body": {
    "route_builder_version": "...",
    "request": { "...": "..." },
    "route": { "route_id": "P5_V1_R1", "...": "..." }
  },
  "evaluation_body": {
    "calc_version": "...",
    "route_id": "P5_V1_R1",
    "models": { "...": "..." },
    "input": { "route": { "...": "same content as route_body.route" }, "parameters": { "...": "..." } },
    "views": { "...": "..." }
  }
}
```
`evaluation_body` is `null` if the proposal was saved without one.
`404 not_found` if the `proposal_id` doesn't exist.

</details>

No delete endpoint — proposals are removed manually in the database if
ever needed.

---

<a id="input-parameters"></a>

## Input Parameters

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/params/StopInfrastructures` | All stops with id, name, country, coordinates |
| `GET` | `/api/params/compositions` | All composition types with full parameters |
| `GET` | `/api/params/TrackInfrastructures` | All country track infrastructure parameters |

<details>
<summary>Request &amp; response details</summary>

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

</details>

---

<a id="route"></a>

## Route

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/route/plan` | Plan a route — stateless, always a full build (no in-place adjust) |

<a id="route-plan"></a>

### `POST /api/route/plan`

<details>
<summary>Request &amp; response details</summary>

**Request body**

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
| `auto_stop_addition` | bool | — | Default `true` — see **Mode switches** below |

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
  "auto_stop_addition": true
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
| `true` (default) | Looks for stops from the full stop catalog that sit close to the routed path (on the line or nearby), and greedily adds any that fit within a fixed detour time budget — cheapest detour first, stopping at the first candidate that would exceed the budget. Added stops come back with `auto_added: true` on their `Stop` in the response (see below) so the frontend can render them differently. Buffer distance and max detour % are fixed constants in `models/route/timetable.py` (`AUTO_STOP_BUFFER_M`, `AUTO_STOP_MAX_DETOUR_PER`), not request fields. The search only runs once per `TripPair`, against the outbound direction — the return trip always adds the same stops (reversed), rather than running its own independent search against its own budget; each direction still gets its own real routed physics for the shared stop list. |
| `false` | Returns exactly the caller's own stop list, unmodified. |

**Response**

```json
{
  "route_builder_version": "0.9.3",
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
excluded — see [Evaluation](#evaluation) for those):

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
| `auto_added` | bool | `true` if `auto_stop_addition` inserted this stop — always `false` for stops the caller supplied directly |

**`route.track_infrastructure[]`** — one entry per country the route's stops
and transited legs actually touch (not every country in the DB), physics-relevant
subset of `TrackInfrastructure` (cost fields like `tac_eur_train_km` excluded):

| Field | Type | Description |
|---|---|---|
| `country_code` | string | |
| `defaulted_fields` | array of string | Which of the fields below came from the EU-average default rather than this country's own seeded data. Empty if all real. A route through a country with **no row at all** in `track_infrastructures` is rejected outright with a `422 domain_error` — see [Error responses](#error-responses) — so `defaulted_fields` only ever reflects individual missing columns on an existing row, never a whole missing country |
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

</details>

---

<a id="evaluation"></a>

## Evaluation

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/evaluation/calc` | Run full cost and revenue evaluation |

<a id="evaluation-calc"></a>

### `POST /api/evaluation/calc`

<details>
<summary>Request &amp; response details</summary>

**Request body**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `route` | object | ✓ | Route JSON from `/api/route/plan`, `od_pairs` populated if you want revenue (a route with empty `od_pairs` still evaluates — cost only, zero revenue) |
| `scenario_id` | int | — | Overrides the route's own embedded `scenario_id` for this evaluation. Omit to cost the route under the same scenario it was planned with |

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

All top-level keys, no wrapper object:

```json
{
  "calc_version": "...",
  "route_id": "P1_V1_R1",
  "models": {
    "route_builder": {"version": "...", "description": "...", "formulas": {"...": "..."}},
    "energy":         {"version": "...", "description": "...", "formulas": {"...": "..."}},
    "evaluation":      {"version": "...", "description": "...", "formulas": {"...": "..."}}
  },
  "input": {
    "route": { "...": "the posted route, verbatim" },
    "parameters": { "...": "every track/stop/composition parameter actually used, same shape as /api/params/*" }
  },
  "views": {
    "route":                     {"description": "...", "normalisations": {"...": "..."}, "data": { "<normalised breakdown>": "see below" }},
    "per_trip_pair":              {"description": "...", "normalisations": {"...": "..."}, "data": {"<pair_key>": {"filter": {"...": "..."}, "values": { "<normalised breakdown>": "see below" }}, "all": { "...": "..." }}},
    "per_trip_pair_per_country":  {"description": "...", "normalisations": {"...": "..."}, "data": {"<pair_key>": {"<country_code>": {"filter": {"...": "..."}, "values": {"...": "..."}}}, "all": { "...": "..." }}},
    "per_trip_pair_per_od":       {"description": "...", "normalisations": {"...": "..."}, "data": {"<pair_key>": {"<od_key>": {"filter": {"...": "..."}, "values": {"...": "..."}}}, "all": { "...": "..." }}},
    "per_trip_per_stop":          {"description": "...", "normalisations": {"...": "..."}, "data": {"<trip_id>": {"<stop_id>": {"filter": {"...": "..."}, "values": {"...": "..."}}}, "all": { "...": "..." }}}
  }
}
```

`views.route.data` holds the normalised breakdown directly (no filter
dimension — it's the whole-route aggregate). The other four views nest a
`{filter, values}` pair per key, where `values` holds the same normalised
breakdown shape, plus an `"all"` entry aggregating across that view's
dimension.

Each normalised breakdown contains five views:

| Key | Unit | Description |
|-----|------|-------------|
| `per_year` | €/year | Annual totals |
| `per_operating_day` | €/operating-day | Per day the service runs |
| `per_trip_km` | €/km | Per km of total trip distance (both directions) |
| `per_available_place_km` | €/available-place-km | Per capacity × distance |
| `per_sold_place_km` | €/sold-place-km | Per actual passenger × distance |

Each of those five is itself a nested cost/revenue/margin breakdown:

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

`net_eur` = `total_revenue_eur` − `total_cost_eur` − `margin.total_eur` —
the actual bottom line after the EBIT margin target is deducted. This is
the field `proposals.proposals`' list/sort endpoints read as `margin_eur`
(see [Proposals](#proposals)).

`od_key` format: `"{origin_stop_id}__{destination_stop_id}__{class_main}"`

See `models/evaluation/README.md` for full documentation of the evaluation model,
cost allocation rules, and view semantics.

</details>

---

<a id="error-responses"></a>

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