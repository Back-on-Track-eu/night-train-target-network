# Night Train — Backend API Reference

Base URL: `http://localhost:5000`

API versions are not tracked in this document — they are reported live in the
responses themselves: `route_builder_version` (`models/route/version.py`),
`calc_version` (`models/evaluation/version.py`), and the energy model version
inside `models.energy` (`models/energy/version.py`). Each `version.py` carries
its own changelog.

**Related documentation:** domain model & pipeline —
[`../models/README.md`](../models/README.md) · evaluation model, views &
allocation — [`../models/evaluation/README.md`](../models/evaluation/README.md)
· database schemas & versioning — [`../db/README.md`](../db/README.md) ·
integration tests per endpoint — [`../tests/README.md`](../tests/README.md)

**Worked examples:** real request/response pairs for the main endpoints are
checked in under [`../scripts/data/`](../scripts/data/), produced by the
manual test scripts in [`../scripts/`](../scripts/) against a locally running
stack. Each endpoint section below links its own example files.

## Table of Contents

- [Health](#health)
- [Auth](#auth)
- [Feedback](#feedback)
  - [`POST /api/feedback`](#post-feedback) — submit feedback
  - [`GET /api/feedback/categories`](#feedback-categories) — suggested category/sub_category values
- [Proposals](#proposals) — persisted automatically by plan/calc (persist-on-calc)
  - [`GET` / `POST /api/proposals`](#list-proposals) — list proposals
  - [`GET /api/proposal/<id>`](#get-proposal) — load a proposal
- [Input Parameters](#input-parameters)
- [Scenarios](#scenarios)
  - [`GET /api/scenarios`](#get-scenarios) — list all scenarios, grouped by current status
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
| `GET` | `/api/data/status` | Whether the DB data loader initialised at startup |

<details>
<summary>Request &amp; response details</summary>

**`GET /api/health` response**
```json
{"status": "ok"}
```

**`GET /api/data/status` response** — `loaded_at` (ISO 8601) only present
once loading succeeded; `error` only present if it failed:
```json
{"loaded": true, "loaded_at": "2026-07-12T08:00:00+00:00"}
```

</details>

---

<a id="auth"></a>

## Auth

Dual-plane model, normalized to one trust ladder
(`guest < OTP-contributor < SSO-operator`, exposed as `g.trust_level`):

- **Local plane (these endpoints)** — email-OTP login + anonymous guest
  sessions for public contributors. Users live in `admin.users`; JWTs are
  HS256, signed with `JWT_SECRET`. OTP mail goes through
  `adapters/mailer.py` (BoT SMTP; `AUTH_EMAIL_DEV_MODE=true` logs codes
  instead for local dev). Rate limits per client IP (`api/limiter.py`).
- **Operator plane ("Sign in with BoT account")** — Keycloak OIDC tokens,
  validated against the realm's JWKS (`api/auth_oidc.py`). **Dormant until
  `KEYCLOAK_ISSUER_URL` + `KEYCLOAK_CLIENT_ID` are set** — activates by
  configuration when BoT's central identity goes live, no code change. On
  first sign-in the operator gets an email-matched `admin.users` row so
  proposals/feedback keep working.

Endpoint protection: decorators in `api/auth_middleware.py`
(`@require_auth`, `@optional_auth`, `@require_trust(level)`).
`POST /api/route/plan`, `POST /api/evaluation/calc`, and `POST
/api/feedback` run `@optional_auth`. Since persist-on-calc (2026-07-16)
the bearer identity decides persistence: authenticated plan/calc calls
(guest token is enough) persist their responses as proposals, tokenless
calls compute only. The intended frontend flow is guest-first — obtain a
guest JWT on first visit, send it on every plan/calc, and merge on
registration (below).

**Guest → registered merge:** calling `POST /api/auth/verify` **with the
guest session's JWT attached as the bearer** reassigns everything that
guest owns (proposals, feedback) to the verified account in one atomic
transaction and marks the guest row (`admin.users.merged_into_user_id`).
The old guest token is rejected from then on with an explicit
account-merged `401`. This covers both registering as the last step after
playing around and logging in to an existing account from a guest
session; an absent or unusable bearer never blocks the verification
itself (`merged_guest` is simply `null`).

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/auth/request-code` | Register/login: send OTP to email (`5/hour` per IP) |
| `POST` | `/api/auth/verify` | Verify OTP → `{token, user_id, display_name, is_guest, merged_guest}` — guest bearer attached triggers the merge (see above) |
| `POST` | `/api/auth/guest` | Anonymous guest session → guest JWT (`20/hour` per IP) |

Config (see `docker/.env.example`): `JWT_SECRET` (required),
`AUTH_EMAIL_DEV_MODE`, `SMTP_*` (shared with feedback mail),
`KEYCLOAK_ISSUER_URL` / `KEYCLOAK_CLIENT_ID` / `KEYCLOAK_JWKS_URL`
(optional operator plane), `TESTING=true` disables rate limits.

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

List and load night train proposals. **There is no save endpoint** — since
persist-on-calc (2026-07-16), `POST /api/route/plan` and `POST
/api/evaluation/calc` persist their own responses for any authenticated
caller (a guest token is enough; tokenless calls compute only). Every user
can see and load every proposal.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/proposals` | List current proposal versions |
| `POST` | `/api/proposals` | Filtered/sorted/paginated list |
| `GET` | `/api/proposal/<id>` | Load the current version of a proposal |

The route — and, once evaluated, its evaluation — are stored twice:
verbatim as JSON (deliberately **not** JSONB — JSONB does not preserve key
order; see `db/README.md`) for an exact, cheap round-trip back to the
frontend, and, for the route, decomposed into GTFS tables
(`proposals.routes`/`trips`/`stop_times`/`shapes`/`services`/`calendar`,
for future export/interop). This duplication is deliberate for now — see
`db/README.md`. Only fully daily schedules (`schedule_mode:
"alwaysDaily"`, the only mode `/api/route/plan` currently supports) can be
persisted.

<a id="persistence"></a>

### Persistence semantics (persist-on-calc)

Both pipelines report what they did in a trailing `proposal` block:
`{persisted, action, proposal_id, proposal_version, user_id}` (the ID
fields absent where meaningless, e.g. `unauthenticated`). The stored
bodies are exactly the responses minus this block. A persistence failure
never fails the computation itself (`action: "error"`).

**`POST /api/route/plan`** — the posted `proposal_id` (optional) and the
resolved setup (stops, composition, all modes, scenario, builder version)
decide the outcome; version rows are appended, never updated:

| Condition | Action | Result |
|-----------|--------|--------|
| No token | `unauthenticated` | Compute only — draft placeholder IDs (≥1e9), nothing stored |
| No/unknown `proposal_id` | `created` | New `proposal_id` (sequence), version 1, IDs rewritten to `P{id}_V1_` |
| Known `proposal_id`, identical resolved setup (any owner) | `unchanged` | Nothing written — response IDs reference the stored current version |
| Known `proposal_id`, changed setup, caller owns current version | `versioned` | Same `proposal_id`, version + 1, `is_current` flipped |
| Known `proposal_id`, changed setup, foreign owner | `branched` | New `proposal_id`, version 1, owned by the caller |

On any persisted outcome the response's IDs (`route_id`, trip IDs,
geometry IDs, `od_pairs`/`shuntings`/`parkings` references) are already
rewritten to the real `P{proposal_id}_V{version}_` prefix — `route_id` is
final from the first response on.

**`POST /api/evaluation/calc`** — the posted route's `route_id` decides
where the evaluation lands:

| Condition | Action | Result |
|-----------|--------|--------|
| No token | `unauthenticated` | Compute only |
| Version row missing (draft/foreign route JSON) | `unpersisted_route` | Compute only |
| Version exists but is not current | `historical_version` | Compute only — history is never mutated |
| Posted route ≠ stored route (hand-edited) | `route_mismatch` | Compute only |
| Version has no evaluation yet, caller owns it | `filled` | `evaluation_body` filled **in place** on that version — the one sanctioned in-place write on the otherwise append-only table |
| Evaluation stored under identical inputs (same route incl. demand, same resolved scenario, same calc version) | `unchanged` | Nothing written — the result is deterministic |
| Changed inputs (scenario override, new calc version), caller owns current | `versioned` | New version, route_body carried over, this evaluation attached |
| Changed inputs / empty evaluation, foreign owner | `branched` | New `proposal_id` owned by the caller, evaluation attached |

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
excluded. Financials appear once a version has been evaluated
(persist-on-calc fills them — see [Persistence semantics](#persistence)). `countries` includes transit-only countries (derived from
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
| `GET` | `/api/params/StopInfrastructures` | All stops with location and per-stop charges |
| `GET` | `/api/params/compositions` | All composition types with full parameters, plus their operators |
| `GET` | `/api/params/TrackInfrastructures` | All country track infrastructure parameters |

All three accept an optional `scenario_id` **query parameter** pinning which
version of every parameter table to read; omit it for the live
`is_current_base` scenario (same semantics as everywhere else — see
[Scenarios](#scenarios)).

Example responses: [`params_stops_output.json`](../scripts/data/params_stops_output.json) ·
[`params_compositions_output.json`](../scripts/data/params_compositions_output.json) ·
[`params_tracks_output.json`](../scripts/data/params_tracks_output.json)
(produced by [`../scripts/test_params.py`](../scripts/test_params.py)).

<details>
<summary>Request &amp; response details</summary>

No request body. All three responses share the same envelope pattern —
documentation and sources appear **once**, not repeated per entity:

| Key | Description |
|---|---|
| `descriptions` | Table + per-field documentation from the DB (`{table, fields}`), identical for every entity so emitted once |
| `sources` | Every referenced source, keyed by `source_id` — `{source_id, source_description, source_url, source_date}`. Fields reference these by id |
| `count` | Number of entities in the list below |

**`StopInfrastructures`** adds `default_stops` (`global` fallback +
`by_country` overrides for the stop charge) and `stops` — one entry per stop:
`{stop_id, name, country_code, lat, lon, stop_charge_eur}`, where
`stop_charge_eur` is a *field object* (see below).

**`TrackInfrastructures`** adds `default_track_infra` (the single EU-average
fallback row, `{value, source_id}` per field) and `track_infrastructures` —
one entry per country: `country_code` plus a field object for each of
`tac_eur_train_km`, `parking_eur_day`, `shunting_eur_event`,
`energy_price_eur_kwh`, `terrain_score`, `terrain_category`, `hsr_allowed`,
`min_boarding_time_min`, `min_alighting_time_min`, `buffer_quota_per`.

**Field object** — every individually versioned parameter value is wrapped as:

| Field | Type | Description |
|-------|------|-------------|
| `value` | number/string/bool | Resolved parameter value |
| `is_default` | bool | `true` if resolved from the defaults table rather than the country's own row |
| `version` | int | DB row version of the source row |
| `source_id` | int or null | Key into the top-level `sources` map — not an inline source object |

**`compositions`** returns `compositions`, `operators`, `classes` and
`coach_types` (redesigned 2026-07-22 — real-coach catalog, see
`models/compositions/calib/CALIBRATION.md`). Composition fields are
grouped by concern:
`routing` (weight, **total_length_m**, speed, HSR, dwell minima,
**n_locos**), `staff` (driver/crew factors incl. the
**zugchef_crew_factor** — total = Σ coach factors + Zugchef — and
**costs_per_hour** with the combined `total_staff_eur_h`), `capacity`
(**total_places**, the full-composition **average densities**
`avg_density_length_m_per_place` / `avg_density_weight_t_per_place`
— service areas included — and **by_class** per `class_main`:
`{places, density_length_m_per_place, density_weight_t_per_place}` from
real section geometry), `equipment` (amenity OR-aggregations incl.
**has_wifi**, plus the **food_and_beverages** catering concept),
`coaches` (`{count, list}` — the ordered formation referencing the
top-level **coach_types** catalog), `fixed_costs`, `variable_km`,
**cost_allocation** (`by_class_main`: each class's blended cost
proportion — the workbook cost_acc columns; identical to the
evaluation's by_class_main hardware basis; sums to 1), and `indicative`
(seeded calibration KPIs + basis via `descriptions`, may be `null`).
The energy regression factors are not exposed (pending the energy model
calibration).

**`coach_types`** (top-level, keyed by `coach_type_id`): physicals
incl./excl. service areas (a dining car has zero revenue space), crew
factor, places, equipment, `class_ids` referencing **`classes`**, own
`source_ids`. **`classes`** groups every `class_id`
("<coach_type_id> - <section label>") by `class_main` with carrying
coach type and places. Each composition and operator carries a
`source_ids` **list** referencing the shared `sources` map.

</details>

How parameter tables, defaults, and row versions are structured in the
database is documented in [`../db/README.md`](../db/README.md).

---

<a id="scenarios"></a>

## Scenarios

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/scenarios` | All scenarios, grouped by current status, with a count per group |

<details>
<summary>Request &amp; response details</summary>

No request body, no query params — always returns every row of
`scenario.scenarios`. Example response:
[`scenarios_output.json`](../scripts/data/scenarios_output.json)
(produced by [`../scripts/test_scenarios.py`](../scripts/test_scenarios.py)).

`scenario.scenarios` carries two independent "current" flags (see
`db/dev/sql/create_scenario_schema.sql` and [`../db/README.md`](../db/README.md)): `is_current_base` (exactly one
row in the whole table — the live default used when an API call omits
`scenario_id`) and `is_current_scenario` (exactly one row per
`scenario_key` — the head of that what-if lineage). A flat
`is_current=true/false` split would collapse that distinction, so the
response is split into three groups instead, each with its own `count`:

```json
{
  "total_count": 12,
  "current_base": {
    "count": 1,
    "scenarios": [ { "scenario_id": 1, "scenario_key": "base", "scenario_name": "2027 base", "description": "...", "change_log": "...", "editor": "david", "created_at": "2026-06-01T10:00:00+00:00", "is_current_base": true, "is_current_scenario": true, "track_infrastructures_version": 3, "track_infrastructure_defaults_version": 1, "stop_infrastructures_version": 2, "stop_infrastructure_defaults_version": 1 } ]
  },
  "current_scenarios": {
    "count": 3,
    "scenarios": [ { "scenario_id": 7, "scenario_key": "2032-baseline-hsr-allowed", "scenario_name": "2032 Base Line + Night Trains on HSR allowed", "...": "..." } ]
  },
  "historical_scenarios": {
    "count": 8,
    "scenarios": [ { "scenario_id": 4, "scenario_key": "2026-baseline", "is_current_scenario": false, "...": "..." } ]
  }
}
```

Every scenario appears in exactly one group. `current_base` holds zero
rows only if the database is not correctly seeded.

</details>

---

<a id="route"></a>

## Route

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/route/plan` | Plan a route — stateless, always a full build (no in-place adjust) |

<a id="route-plan"></a>

### `POST /api/route/plan`

**Persists itself** for authenticated callers (guest token is enough) and
appends a trailing `proposal` block —
`{"persisted": true, "action": "created", "proposal_id": 5,
"proposal_version": 1, "user_id": 3}` — see
[Persistence semantics](#persistence) for the full
created/unchanged/versioned/branched contract. Tokenless requests compute
only (`{"persisted": false, "action": "unauthenticated"}`) and keep the
draft placeholder IDs.

How the route builder pipeline works internally (routing, timetabling,
auto-stop addition, mode switches) is documented in
[`../models/README.md`](../models/README.md).

Worked example — Berlin – Dresden – Wien with `auto_stop_addition="add"`:
request [`tc_1_route_input.json`](../scripts/data/tc_1_route_input.json),
full response [`tc_1_route_input_output.json`](../scripts/data/tc_1_route_input_output.json)
(produced by [`../scripts/test_route_plan.py`](../scripts/test_route_plan.py),
which also writes a QGIS-ready `tc_1_route_input_lines.geojson` +
`tc_1_route_input_stops.geojson` pair alongside it — stops carry
`auto_added` so caller-supplied vs. auto-added stops can be styled
differently). A `"suggest"`-mode request lives alongside it as
[`tc_2_route_input_suggest.json`](../scripts/data/tc_2_route_input_suggest.json),
which additionally produces a `tc_2_route_input_suggest_suggested_stops.geojson`
layer of candidate stops tagged with `added_time_min`.

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
| `fixed_night_interval` | array of string | (✓) | Exactly 2 distinct stop IDs from `stops`, start before end in outbound travel order — required for, and only allowed with, `timetable_mode="simpleAutomaticWithFixedNight"` (400 otherwise). May span several legs; applied reversed to the return trip automatically |
| `schedule_mode` | string | — | Default `"alwaysDaily"` — see **Mode switches** below |
| `auto_stop_addition` | string | — | `"off"` / `"add"` / `"suggest"`, default `"add"` — see **Mode switches** below. String enum since route builder 0.9.5; booleans are rejected with 400 |

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
  "auto_stop_addition": "add"
}
```

**Mode switches**

`routing_mode` — controls how much routing complexity is applied:

| Value | Description |
|---|---|
| `"fullRouting"` (default) | Speed capped at the composition's `max_speed_kmh` everywhere, plus HSR avoidance: track segments whose *permitted* track speed exceeds `HSR_TRACK_SPEED_THRESHOLD_KMH` (strictly above 230 km/h — i.e. dedicated new-build high-speed lines only, upgraded conventional lines up to 230 stay usable; see `models/route/version.py`) are heavily penalized in every country where HSR is not allowed — allowed only when BOTH the composition's `hsr_allowed` AND that country's track-infrastructure `hsr_allowed` are true, evaluated for every country incl. transited-without-stop ones. Conventional lines are never penalized. Every leg additionally carries a per-stop traction-dynamics surcharge — the accel/brake time loss computed from composition weight plus an assumed standard locomotive against the link speeds before/after each stop (see `TRACTION_*` in `models/route/version.py`) — in its own `dynamics_time_min` field, kept separate from the raw router `driving_time_min`; `buffer_time_min` carries the country quota applied to driving and to dynamics (physics first, buffer after). Two-pass routing (snap pass, then custom-model pass) when a custom model applies. |
| `"simpleRouting"` | Bypasses all of that — single-pass, no speed cap, no HSR avoidance, no traction dynamics. Cheap and fast, but not representative of real physics. Intended for quick manual sanity checks only. |

`timetable_mode` — controls how departure time and per-stop classification are derived. Classification is the same three-way rule for every mode (route builder 0.9.10, thresholds `NIGHT_START_MIN`/`NIGHT_END_MIN` in `models/route/version.py`): a stop **departing strictly before 00:00** is `boarding`, one **arriving at/after 05:00** is `alighting`, anything between is a `night` stop (operationally identical to `both` for dwell, but excluded from demand OD pairs). First stop is always boarding and last always alighting regardless of clock time — termini by position, not by the threshold rule. Outbound and return are scheduled independently, so their times can differ (e.g. asymmetric HSR avoidance changes duration).

| Value | Description |
|---|---|
| `"simpleAutomatic"` (default) | Routes once, then mirrors the resulting trip duration around a fixed 02:30 constant (`MIRROR_MIN`) to get the departure time. |
| `"simpleAutomaticWithFixedNight"` | Requires `fixed_night_interval` `[A, B]`. Instead of the whole trip, the **interval's** midpoint (departure at `A` → arrival at `B`) is centered on 02:30 — so demand-strong feeder sections outside the interval keep sensible evening/morning clock times (e.g. Munich–Berlin–Hamburg as an evening feeder into a Hamburg–Copenhagen night section). Hard constraints: the interval must depart `A` by 23:59 and arrive at `B` at 05:00 or later. A naturally shorter interval (< 5h01) is stretched to exactly that window by distributing `slack_time_min` across the interval's segments proportionally to leg time (pinning dep 23:59 / arr 05:00 in the minimal-stretch case — minimal stretch wins over exact midpoint symmetry). If stretching drops the interval's timetable speed below `FIXED_NIGHT_MIN_SPEED_RATIO` (0.7) of its routing speed, the trip carries a `fixed_night_stretch_slow` entry in `general_parameters.timetable_warnings` — a warning, never an error. The return trip applies the interval reversed automatically. |

`schedule_mode` — controls the route's seasonal operating frequency:

| Value | Description |
|---|---|
| `"alwaysDaily"` (default, only value) | Daily frequency in both seasons, regardless of actual demand. Reserved: a future demand-aware strategy can be added without changing this request shape. |

`auto_stop_addition` — whether to propose additional stops along the routed path:

| Value | Description |
|---|---|
| `"off"` | Returns exactly the caller's own stop list, unmodified — no candidate search at all. |
| `"add"` (default) | Looks for stops from the full stop catalog that sit close to the routed path (on the line or nearby), and greedily adds any that fit within a fixed detour time budget — cheapest detour first, stopping at the first candidate that would exceed the budget. Added stops come back with `auto_added: true` on their `Stop` in the response (see below) so the frontend can render them differently. |
| `"suggest"` | Routes exactly like `"off"` (nothing added, nothing rerouted), but runs the same candidate search + costing as `"add"` and returns every costed candidate in a top-level `suggested_stops` list, placed between `request` and `route` in the response (see **Response** below) — each with the `added_time_min` the stop would cost if implemented. The detour budget is deliberately **not** applied: suggestion is informational, selection is the caller's. Present even when empty (a real "searched, found nothing" answer). |

For `"add"` and `"suggest"`: the candidate search prefilters the stop catalog
to countries the routed legs actually pass through (attribution the router
already computed), buffer distance and max detour % are fixed constants in
`models/route/version.py` (`AUTO_STOP_BUFFER_M`, `AUTO_STOP_MAX_DETOUR_PER`),
not request fields, and the search only runs once per `TripPair`, against the
outbound direction — for `"add"` the return trip always adds the same stops
(reversed), rather than running its own independent search against its own
budget; each direction still gets its own real routed physics for the shared
stop list.

**Response**

```json
{
  "route_builder_version": "0.9.9",
  "request": { "...": "the request body above, echoed back unchanged" },
  "suggested_stops": [
    { "...": "ONLY for auto_stop_addition=\"suggest\" — see below; absent for \"off\"/\"add\"" }
  ],
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
        "outbound": {
          "trip_id": "P..._D0_T1",
          "direction": 0,
          "general_parameters": { "trip_km": 353.2, "route_duration_min": 267, "average_speed_kmh": 79.4, "timetable_warnings": [] },
          "segments": [ "...Segment, see below..." ]
        },
        "return_trip": {
          "trip_id": "P..._D1_T1",
          "direction": 1,
          "general_parameters": { "trip_km": 353.2, "route_duration_min": 271, "average_speed_kmh": 78.2, "timetable_warnings": [] },
          "segments": [ "..." ]
        }
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

`od_pairs` comes back populated: `plan_route()` itself leaves it empty
(demand is not part of planning), but the endpoint then runs a stopgap
demand distribution (`distribute_demand()`, flat utilization and per-km
fares — see `OPEN_TODOS["demand_model"]` in `models/route/version.py`) so
that a subsequent `POST /api/evaluation/calc` returns non-zero revenue. `route_id`/`trip_id` follow
`P{proposal_id}_V{version}_R1[_D{direction}_T{pair_index}]`.

**`suggested_stops[]`** — only present for `auto_stop_addition="suggest"`
(even when empty), placed between `request` and `route`. Every costed
candidate the search found near the routed path, in geographic order along
the route:

| Field | Type | Description |
|---|---|---|
| `stop_id`, `stop_name`, `country_code`, `lat`, `lon` | | Identity/location of the candidate stop |
| `added_time_min` | float | Full trip-time increase (detour + dwell) this stop would cost if implemented — the same figure `"add"` mode budgets against, 1 decimal |

**`outbound`/`return_trip`.`general_parameters`** — headline physics
stats for that trip, for quick manual reading rather than deriving them from
`segments[]` yourself (emitted as `stats` by mistake in 0.9.4 code, fixed to
the documented `general_parameters` key in 0.9.5), plus derived timetable
quality warnings (0.9.10):

| Field | Type | Description |
|---|---|---|
| `trip_km` | float | Total trip distance for that direction, km (`distance_m` summed across segments, /1000, 1 decimal) |
| `route_duration_min` | int | Full elapsed time, departure → arrival — driving + dynamics + buffer + slack + dwell at intermediate stops (`Trip.total_time_min`) |
| `average_speed_kmh` | float | `trip_km` ÷ (`route_duration_min` / 60), 1 decimal. Uses elapsed time, not pure driving time — a different, unimplemented formula (`avg_speed` in `ROUTE_FORMULAS`) uses driving time only |
| `timetable_warnings` | array | Derived timetable quality annotations — `[]` for most trips. Currently only `fixed_night_stretch_slow` (fixed-night mode, interval stretched too slow): `{code, interval: [start_id, end_id], timetable_speed_kmh, routing_speed_kmh, ratio}` with `ratio` = timetable ÷ routing speed, below `FIXED_NIGHT_MIN_SPEED_RATIO` |

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
| `places_by_class` | Capacity, keyed by class_main |
| `density_by_class_main_length`, `density_by_class_main_weight` | Derived densities (m and t per place) from real section geometry — replace the retired `density_by_class` (2026-07-22) |
| `total_length_m` | Composition length (m) |

**`segments[]`** (on `outbound`/`return_trip`) — one entry per leg between two consecutive stops:

| Field | Type | Description |
|---|---|---|
| `from_stop`, `to_stop` | object | `Stop`, see below |
| `geometry_id` | string | References an entry in `route.geometries` — see below |
| `distance_m` | int | Leg distance |
| `driving_time_min`, `dynamics_time_min`, `buffer_time_min` | int | Leg duration components: raw router time (constant-cruise passage), per-stop accel/brake time loss (traction dynamics), and schedule buffer — the country quota applied to driving and to dynamics (the dynamics cruise speed is always derived from raw driving time first, buffer never feeds the physics) |
| `slack_time_min` | int | Deliberate schedule padding beyond routing physics — non-zero only on legs inside a stretched fixed-night interval (see `timetable_mode`). Total leg time = driving + dynamics + buffer + slack, and stop-to-stop elapsed times always match that sum |
| `energy_kwh` | float | Currently a flat 28.0 kWh/km dummy factor — not calibrated yet |
| `country_distance_shares`, `country_time_shares` | object | `{country_code: share}`, each sums to 1.0. Includes transit-only countries the leg crosses without stopping |

**`Stop`** (embedded in every `from_stop`/`to_stop`):

| Field | Type | Description |
|---|---|---|
| `stop_id`, `stop_name`, `country_code`, `lat`, `lon` | | Identity/location |
| `stop_type` | string | `"boarding"`, `"night"`, `"alighting"`, or `"both"` — see `timetable_mode` above. `night` (0.9.10): departs at/after 00:00 and arrives before 05:00; dwells like `both`, excluded from demand OD pairs |
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

**Persists itself** for authenticated callers and appends a trailing
`proposal` block (see [Persistence semantics](#persistence) — filled in
place on the version it was computed for, `unchanged` under identical
inputs, a new version under changed ones). The response also carries a
top-level `scenario_id`: the scenario the evaluation actually ran under,
override applied — the posted route's own embedded `scenario_id` is NOT
updated by an override, so this field is the authoritative one.

Worked example: request
[`tc_1_evaluation_input.json`](../scripts/data/tc_1_evaluation_input.json)
(the route from the route/plan example, demand injected), full response
[`tc_1_evaluation_input_output.json`](../scripts/data/tc_1_evaluation_input_output.json)
(produced by [`../scripts/test_evaluation_calc.py`](../scripts/test_evaluation_calc.py)).

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
    "per_trip_pair_per_section":  {"description": "...", "normalisations": {"...": "..."}, "data": {"<pair_key>": {"<section_key>": {"filter": {"...": "..."}, "values": {"...": "..."}}}, "all": { "...": "..." }}},
    "per_trip_per_stop":          {"description": "...", "normalisations": {"...": "..."}, "data": {"<trip_id>": {"<stop_id>": {"filter": {"...": "..."}, "values": {"...": "..."}}}, "all": { "...": "..." }}}
  }
}
```

`views.route.data` holds the normalised breakdown directly (no filter
dimension — it's the whole-route aggregate). The other five views nest a
`{filter, values}` pair per key, where `values` holds the same normalised
breakdown shape, plus an `"all"` entry aggregating across that view's
dimension.

Each cell contains the same breakdown under five **normalisations** (not to be confused with the six *views* above — a view selects *what scope* the money belongs to, a normalisation selects *what unit* it is expressed in). All per-unit denominators are annual, matching the €/year leaves; route-section cells divide by the section's own annual physics:

| Key | Unit | Description |
|-----|------|-------------|
| `per_year` | €/year | Annual totals |
| `per_operating_day` | €/operating-day | Per day the service runs |
| `per_train_km` | €/train-km | Per annual train-km (cycle distance × operating days; a section's own distance for section cells) |
| `per_available_place_km` | €/available-place-km | Per capacity × distance |
| `per_sold_place_km` | dict per class_main, €/sold-place-km | Each class's allocated cost ÷ its OWN sold place-km (CALC 0.9.8) — 50% occupancy doubles the per-sold cost; classes without sales omitted; `null` only for scopes without per-class data |
| `by_class_main` | dict per class_main, same units as the cell | The full breakdown split by the class allocation model — per-class cells sum back to the cell total |

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

See [`../models/evaluation/README.md`](../models/evaluation/README.md) for full
documentation of the evaluation model, cost allocation rules, and view
semantics — including a plain-language explanation of what each view displays
and which frontend filter selection maps to which view
([Views, explained for display](../models/evaluation/README.md#views-explained-for-display)).

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
| `500` | `proposal_error` | Unexpected error saving/loading a proposal |
| `500` | `feedback_error` | Feedback storage failed (mail failure alone never triggers this) |
| `503` | `infrastructure_error` | DB unreachable or unknown composition ID |
| `501` | `not_implemented` | Endpoint exists but is not yet implemented |