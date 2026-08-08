# Night Train — Backend API Reference

Base URL: `http://localhost:5050`

API versions are not tracked in this document — they are reported live in the
responses themselves: `route_builder_version` (`models/route/version.py`),
`calc_version` (`models/evaluation/version.py`), and the energy model version
inside `models.energy` (`models/energy/version.py`). Each `version.py` carries
its own changelog.

**Related documentation:** proposals architecture, storage & locked design
decisions — [`../adapters/proposal/README.md`](../adapters/proposal/README.md)
· domain model & pipeline — [`../models/README.md`](../models/README.md) ·
evaluation model, views & allocation —
[`../models/evaluation/README.md`](../models/evaluation/README.md) · database
schemas & versioning — [`../db/README.md`](../db/README.md) · integration tests
per endpoint — [`../tests/README.md`](../tests/README.md) · frontend migration
guide —
[`../../docs/FRONTEND_API_HANDOVER_2026-08-07.md`](../../docs/FRONTEND_API_HANDOVER_2026-08-07.md)

**Worked examples:** request fixtures for the main endpoints are checked
in under [`../scripts/data/`](../scripts/data/); the matching
`*_output.json` response files linked below are generated locally by
running the manual test scripts in [`../scripts/`](../scripts/) against a
running stack (they are not checked in). Each endpoint section below links
its own example files.

## Table of Contents

- [Health](#health)
- [Auth](#auth)
- [Input Parameters](#input-parameters)
- [Proposal Compute (merged)](#proposal-compute) — route + evaluation in one call, stateless
  - [`POST /api/proposal/calc`](#proposal-calc) — plan a route and evaluate it
- [Scenarios](#scenarios)
  - [`GET /api/scenarios`](#scenarios) — list all scenarios, grouped by current status
- [Proposals](#proposals) — publish and load
  - [`POST /api/proposal/publish`](#proposal-publish) — publish a computed proposal, the only write path
  - [`GET /api/proposal/<id>`](#get-proposal) — load a proposal
- [Gallery](#gallery) — browse proposals and existing trains
  - [`GET` / `POST /api/proposals`](#list-proposals) — filter/sort/paginate + map sections, proposals ∪ ONTD existing routes
- [Analytics](#analytics)
  - [`POST /api/proposals/compare`](#compare-proposals) — compare two sides, stored or what-if
- [Engagement](#engagement) — likes, comments and the event timeline
  - [`GET /api/proposal/<id>/engagements`](#proposal-engagements) — likes + comments + timeline
  - [`POST` / `DELETE /api/proposal/<id>/like`](#proposal-like) — like/unlike a proposal
  - [`POST /api/proposal/<id>/comment`](#proposal-comment) — add a comment
  - [`PATCH` / `DELETE /api/proposal/<id>/comment/<cid>`](#proposal-comment-item) — edit/delete own comment
- [Feedback](#feedback)
  - [`POST /api/feedback`](#post-feedback) — submit feedback
  - [`GET /api/feedback/categories`](#feedback-categories) — suggested category/sub_category values
- [Error responses](#error-responses)

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
`POST /api/proposal/calc` runs **no** auth decorator at all — it never
persists anything, so there is no bearer identity to branch on and an
`Authorization` header has no effect. `POST /api/proposal/publish` (the
only write path — [below](#proposal-publish)) runs `@require_auth` at the
`TRUST_GUEST` floor: a guest token is enough to publish, and the acting
user always comes from the token, never the request body. The intended
frontend flow is guest-first — obtain a guest JWT on first visit, send it
on every publish, and merge on registration (below).

**Guest → registered merge:** calling `POST /api/auth/verify` **with the
guest session's JWT attached as the bearer** reassigns everything that
guest owns (proposals, feedback, likes, comments — see `db/README.md`'s
Proposal Engagement note for the one extra step likes need) to the
verified account in one atomic transaction and marks the guest row
(`admin.users.merged_into_user_id`). The old guest token is rejected from
then on with an explicit account-merged `401`. This covers both
registering as the last step after playing around and logging in to an
existing account from a guest session; an absent or unusable bearer never
blocks the verification itself (`merged_guest` is simply `null`).

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/auth/request-code` | Register/login: send OTP to email (`5/hour` per IP). No display name here — a new email creates a pending, unverified account (placeholder name) and the name is chosen at verify |
| `POST` | `/api/auth/verify` | Verify OTP → `{token, user_id, display_name, is_guest, merged_guest}` — guest bearer attached triggers the merge (see above). A first-time (never-verified) account must send `display_name` as a second step: verify without one replies `200 {"needs_display_name": true}` and leaves the code unconsumed, so the client re-submits the same code with the chosen name |
| `POST` | `/api/auth/guest` | Anonymous guest session → guest JWT (`20/hour` per IP) |

Config (see `docker/.env.example`): `JWT_SECRET` (required),
`AUTH_EMAIL_DEV_MODE`, `SMTP_*` (shared with feedback mail),
`KEYCLOAK_ISSUER_URL` / `KEYCLOAK_CLIENT_ID` / `KEYCLOAK_JWKS_URL`
(optional operator plane), `TESTING=true` disables rate limits.

---
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
`models/compositions/calib/CALIBRATION.md`). Each composition is
identified by **`composition_id`** — the same name the calc request,
gallery rows, `composition_ids` filter and compare overrides use
(renamed from `comp_id` 2026-08-07). Composition fields are
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

<a id="proposal-compute"></a>

## Proposal Compute (merged)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/proposal/calc` | Plan a route **and** evaluate it in one call — stateless, no persistence |

<a id="proposal-calc"></a>

### `POST /api/proposal/calc`

The merged compute endpoint (`adapters/proposal/README.md` §2.1). One
request → route + evaluation, one response, no side effects: it never
writes to the database and never touches `admin.users` identity, so
there is no `proposal` block in the response and no auth header has any
effect. This is the sole route-planning-and-costing entry point —
the former two-call `POST /api/route/plan` + `POST /api/evaluation/calc`
pair was removed in the 2026-08-03 cutover.

To persist a computed result as a proposal, take this endpoint's
`request` block unchanged and post it as `compute_request` to
[`POST /api/proposal/publish`](#proposal-publish) below — the server
recomputes it itself rather than trusting anything client-supplied
(§2.2's integrity rule).

How the route builder pipeline works internally (routing, timetabling,
auto-stop addition, mode switches) is documented in
[`../models/README.md`](../models/README.md); the evaluation model, cost
allocation rules, and view semantics in
[`../models/evaluation/README.md`](../models/evaluation/README.md).

Worked example — Berlin – Dresden – Wien with `auto_stop_addition="add"`:
request [`tc_1_route_input.json`](../scripts/data/tc_1_route_input.json),
full response [`tc_1_route_input_output.json`](../scripts/data/tc_1_route_input_output.json)
(produced by [`../scripts/test_proposal_calc.py`](../scripts/test_proposal_calc.py),
which also prints/validates the evaluation block and writes a QGIS-ready
`tc_1_route_input_lines.geojson` + `tc_1_route_input_stops.geojson` pair
alongside it — stops carry `auto_added` so caller-supplied vs. auto-added
stops can be styled differently). A `"suggest"`-mode request lives alongside it as
[`tc_2_route_input_suggest.json`](../scripts/data/tc_2_route_input_suggest.json),
which additionally produces a `tc_2_route_input_suggest_suggested_stops.geojson`
layer of candidate stops tagged with `added_time_min`.

<details>
<summary>Request &amp; response details</summary>

**Request body**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `stops` | array of string | ✓ | Ordered list of stop IDs, min 2 — plain strings, e.g. `["DE_BERLIN_HBF", "AT_WIEN_HBF"]`. No per-stop type or time; both are derived automatically, see `timetable_mode` |
| `composition_id` | string | ✓ | From `/api/params/compositions` |
| `scenario_id` | int | — | Pins which version of every parameter table to use. Omit for the current live base scenario |
| `routing_mode` | string | — | Default `"fullRouting"` — see **Mode switches** below |
| `timetable_mode` | string | — | Default `"simpleAutomatic"` — see **Mode switches** below |
| `fixed_night_interval` | array of string | (✓) | Exactly 2 distinct stop IDs from `stops`, start before end in outbound travel order — required for, and only allowed with, `timetable_mode="simpleAutomaticWithFixedNight"` (400 otherwise). May span several legs; applied reversed to the return trip automatically |
| `schedule_mode` | string | — | Default `"alwaysDaily"` — see **Mode switches** below |
| `auto_stop_addition` | string | — | `"off"` / `"add"` / `"suggest"`, default `"add"` — see **Mode switches** below. String enum since route builder 0.9.5; booleans are rejected with 400 |

There is deliberately no `proposal_id`/`proposal_version` field — those
are publish-only concerns (`POST /api/proposal/publish`) that have no
meaning for a call that never persists.

**Example request**
```json
{
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
  "route_builder_version": "0.9.13",
  "calc_version": "0.9.11",
  "route_fingerprint": "sha256:3f9a1c...",
  "cache_hit": false,            // true when served from the compute cache (§2.3)
  "request": {
    "stops": ["DE_BERLIN_HBF", "DE_DRESDEN_HBF", "AT_WIEN_HBF"],
    "composition_id": "NEW-BAL-7",
    "scenario_id": 1,
    "timetable_mode": "simpleAutomatic",
    "fixed_night_interval": null,
    "schedule_mode": "alwaysDaily",
    "auto_stop_addition": "add"
  },
  "suggested_stops": [
    { "...": "ONLY for auto_stop_addition=\"suggest\" — see above; absent for \"off\"/\"add\"" }
  ],
  "summary": {
    "total_distance_km": 683.4, "total_time_h": 9.0, "avg_speed_kmh": 76.0,
    "n_stops": 3, "countries": ["AT", "DE"], "stop_ids": ["DE_BERLIN_HBF", "..."],
    "cost_eur_per_train_km": 12.4, "revenue_eur_per_train_km": 14.1,
    "margin_eur_per_train_km": 1.7, "subsidy_eur_per_year": 0.0,
    "demand_trips_per_year": 4200, "demand_trip_km_per_year": 2870000,
    "shift_air_trips_per_year": 1470, "shift_air_trip_km_per_year": 1004000,
    "shift_car_trips_per_year": 840, "shift_car_trip_km_per_year": 574000,
    "co2_savings_t_per_year": 210.4, "subsidy_eur_per_t_co2": null,
    "demand_kpis_placeholder": true, "co2_g_per_pax_km": 33.0
  },
  "route": {
    "route_id": "R1",
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
        "od_pairs": [ { "...": "populated automatically by the stopgap demand model, see below" } ],
        "outbound": {
          "trip_id": "R1_D0_T1",
          "direction": 0,
          "general_parameters": { "trip_km": 353.2, "route_duration_min": 267, "average_speed_kmh": 79.4, "timetable_warnings": [] },
          "segments": [ "...Segment, see below..." ]
        },
        "return_trip": {
          "trip_id": "R1_D1_T1",
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
      { "id": "R1_D0_T1_L0", "coords": [[13.366, 52.523, "..."]] }
    ]
  },
  "evaluation": {
    "models": { "...": "static model documentation — see below" },
    "input": { "parameters": { "...": "every track/stop/composition parameter actually used — see below" } },
    "views": { "...": "cost/revenue breakdown, six views — see below" }
  }
}
```

`od_pairs` comes back populated: `plan_route()` itself leaves it empty
(demand is not part of planning), but the endpoint then runs a stopgap
demand distribution (`distribute_demand()`, flat utilization and per-km
fares — see `OPEN_TODOS["demand_model"]` in `models/route/version.py`) so
that `evaluation` carries non-zero revenue. There is no way to supply
custom demand through this endpoint — it always builds fresh from
`stops`/`composition_id` and runs the stopgap model internally. `route_id`/`trip_id`
carry no `P{proposal_id}_V{version}_` prefix here — see point 2 below.

Five things worth calling out explicitly (`adapters/proposal/README.md` §2.1):

1. **`request` is resolved, not echoed raw** — every optional field is
   present with its default applied and `scenario_id` is always a
   concrete int, so an omitted field and an explicitly-posted default
   compare equal. This is exactly the shape `compute_request` expects on
   [`POST /api/proposal/publish`](#proposal-publish).
2. **IDs are neutral** — `route_id`/`trip_id`/`geometry_id` (and the
   evaluation views' dict keys that reuse `trip_id`, e.g.
   `views.per_trip_pair.data`) carry no `P{id}_V{version}_` prefix here;
   `route_id` is simply `"R1"`. Prefixed IDs only exist on published
   proposals — publish assigns them (`P{proposal_id}_V{proposal_version}_R1`).
3. **No duplicate route** — `evaluation.input` has no `route` key. The
   route already appears once, as a sibling of `evaluation`.
4. **`route_fingerprint` and `cache_hit`** — `route_fingerprint` (§3.1) is
   a SHA-256 over the route's resolved stops/times/geometry, computed by
   `adapters/proposal/projection.py`; it agrees between ephemeral and
   published forms of the identical route by construction (the canonical
   extract never reads `route_id`/`trip_id`/`geometry_id`). `cache_hit`
   is `true` when the response was served from the §2.3 compute cache
   (WP13): identical resolved requests within the cache TTL (default
   3 h) skip routing and evaluation entirely and return the byte-
   identical stored result. The cache is invisible otherwise — a hit and
   the compute it replays differ in no other field. Every compute path
   shares it (`/calc`, both compare sides, publish, the on-load refresh),
   so e.g. comparing warms the editor and vice versa.
5. **`summary` is the gallery row's KPI set** (WP10 step 5) — built by
   the exact same `models/evaluation/summary.py: build_summary_row()`
   the publish projection uses, so everything a `source: "proposal"`
   gallery row shows is retrievable straight from this response. The two
   shapes are deliberately non-identical in one respect: `summary` here
   carries **no `geom_simplified`** (this response already has full
   per-segment geometry under `route.geometries`; the gallery row needs
   the simplified copy precisely because it has no segments) and none of
   the DB-side identity/engagement fields (`proposal_id`, `name`,
   `likes_count`, `comments_count`, timestamps).

**Errors:** `400 bad_request` / `400 validation_error` (see
[Error responses](#error-responses)), `422 domain_error` (route or
evaluation domain failure — e.g. a route through a country with **no
row at all** in `track_infrastructures`), `500 calc_error` (unexpected
pipeline failure).

**`outbound`/`return_trip`.`general_parameters`** — headline physics
stats for that trip, for quick manual reading rather than deriving them from
`segments[]` yourself, plus derived timetable quality warnings:

| Field | Type | Description |
|---|---|---|
| `trip_km` | float | Total trip distance for that direction, km (`distance_m` summed across segments, /1000, 1 decimal) |
| `route_duration_min` | int | Full elapsed time, departure → arrival — driving + dynamics + buffer + slack + dwell at intermediate stops (`Trip.total_time_min`) |
| `average_speed_kmh` | float | `trip_km` ÷ (`route_duration_min` / 60), 1 decimal. Uses elapsed time, not pure driving time |
| `timetable_warnings` | array | Derived timetable quality annotations — `[]` for most trips. Currently only `fixed_night_stretch_slow` (fixed-night mode, interval stretched too slow): `{code, interval: [start_id, end_id], timetable_speed_kmh, routing_speed_kmh, ratio}` with `ratio` = timetable ÷ routing speed, below `FIXED_NIGHT_MIN_SPEED_RATIO` |

**`route.trip_pairs[].composition`** — physics-relevant subset of the composition
used, not the full object (cost fields like `driver_costs_eur_h` are deliberately
excluded — see the `evaluation` block below for those):

| Field | Description |
|---|---|
| `composition_id`, `description`, `operator_id` | Identity (renamed from `comp_id`/`comp_description` 2026-08-07 — one wire name across the whole API; the enclosing `trip_pairs[]` entry already keys this object by `composition_id`) |
| `max_speed_kmh`, `hsr_allowed` | Routing inputs |
| `min_boarding_time_min`, `min_alighting_time_min` | Dwell time inputs |
| `energy_factor_weight`, `energy_factor_speed`, `energy_factor_terrain` | Energy model inputs |
| `total_weight_t`, `total_crew` | Physical properties |
| `places_by_class` | Capacity, keyed by class_main |
| `density_by_class_main_length`, `density_by_class_main_weight` | Derived densities (m and t per place) from real section geometry |
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
| `stop_type` | string | `"boarding"`, `"night"`, `"alighting"`, or `"both"` — see `timetable_mode` above. `night`: departs at/after 00:00 and arrives before 05:00; dwells like `both`, excluded from demand OD pairs |
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

**`evaluation.models`** — version + description + formula registry for
every model that contributed:

```json
{
  "route_builder": {"version": "...", "description": "...", "formulas": {"...": "..."}},
  "energy":         {"version": "...", "description": "...", "formulas": {"...": "..."}},
  "evaluation":      {"version": "...", "description": "...", "formulas": {"...": "..."}},
  "emissions":       {"version": "...", "description": "...", "factors": {
    "night_train": {"g_per_pax_km": 33.0,  "source": "..."},
    "air":          {"g_per_pax_km": 160.0, "source": "..."},
    "car":          {"g_per_pax_km": 143.0, "source": "..."}
  }}
}
```

The `emissions` entry carries `factors` instead of `formulas` — the
model is a set of sourced per-mode constants (`models/emissions`,
decision 24), not calculation steps. These are the reference values the
frontend renders next to a proposal's night-train `co2_g_per_pax_km`.

**`evaluation.views`** — six views, each `{description, normalisations,
data}`:

```json
{
  "route":                     {"description": "...", "normalisations": {"...": "..."}, "data": { "<normalised breakdown>": "see below" }},
  "per_trip_pair":              {"description": "...", "normalisations": {"...": "..."}, "data": {"<pair_key>": {"filter": {"...": "..."}, "values": { "<normalised breakdown>": "see below" }}, "all": { "...": "..." }}},
  "per_trip_pair_per_country":  {"description": "...", "normalisations": {"...": "..."}, "data": {"<pair_key>": {"<country_code>": {"filter": {"...": "..."}, "values": {"...": "..."}}}, "all": { "...": "..." }}},
  "per_trip_pair_per_od":       {"description": "...", "normalisations": {"...": "..."}, "data": {"<pair_key>": {"<od_key>": {"filter": {"...": "..."}, "values": {"...": "..."}}}, "all": { "...": "..." }}},
  "per_trip_pair_per_section":  {"description": "...", "normalisations": {"...": "..."}, "data": {"<pair_key>": {"<section_key>": {"filter": {"...": "..."}, "values": {"...": "..."}}}, "all": { "...": "..." }}},
  "per_trip_per_stop":          {"description": "...", "normalisations": {"...": "..."}, "data": {"<trip_id>": {"<stop_id>": {"filter": {"...": "..."}, "values": {"...": "..."}}}, "all": { "...": "..." }}}
}
```

`views.route.data` holds the normalised breakdown directly (no filter
dimension — it's the whole-route aggregate); the other five views nest a
`{filter, values}` pair per key, where `values` holds the same normalised
breakdown shape, plus an `"all"` entry aggregating across that view's
dimension. `od_key` format: `"{origin_stop_id}__{destination_stop_id}__{class_main}"`.

Each cell contains the same breakdown under five **normalisations** (not to be confused with the six *views* above — a view selects *what scope* the money belongs to, a normalisation selects *what unit* it is expressed in). All per-unit denominators are annual, matching the €/year leaves; route-section cells divide by the section's own annual physics:

| Key | Unit | Description |
|-----|------|-------------|
| `per_year` | €/year | Annual totals |
| `per_operating_day` | €/operating-day | Per day the service runs |
| `per_train_km` | €/train-km | Per annual train-km (cycle distance × operating days; a section's own distance for section cells) |
| `per_available_place_km` | €/available-place-km | Per capacity × distance |
| `per_sold_place_km` | €/sold-place-km | Each class's allocated cost ÷ its OWN sold place-km — 50% occupancy doubles the per-sold cost; classes without sales omitted |

**Every normalisation above is itself class-keyed** (CALC 0.9.9): each of
the five keys maps to `{"all": <breakdown>, <class_main>: <breakdown>, ...}`,
not a bare breakdown — `"all"` is the whole-cell aggregate, read it for a
total; each `class_main` key is that class's own share. For `per_year`/
`per_operating_day`/`per_train_km` the class cells sum back to `"all"`
exactly (the divisor is class-independent); for the two place-km
normalisations they don't (each divides by that class's own place-km).
So the actual bottom line for a route is
`evaluation.views.route.data.per_year.all.net_eur`, not
`...data.per_year.net_eur` — there is no bare-breakdown form at any level.
(There used to be a separate `by_class_main` normalisation key; it was
retired as redundant with `per_year`'s own class cells.)

Each `class_main` key (including `"all"`) under a normalisation holds this
nested cost/revenue/margin breakdown:

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
the field the proposal summary/list endpoints read as `margin_eur_per_train_km`'s
`net_eur` counterpart (see [Proposals](#proposals)).

See [`../models/evaluation/README.md`](../models/evaluation/README.md) for full
documentation of the evaluation model, cost allocation rules, and view
semantics — including a plain-language explanation of what each view displays
and which frontend filter selection maps to which view
([Views, explained for display](../models/evaluation/README.md#views-explained-for-display)).

</details>

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

<a id="proposals"></a>

## Proposals

Publish and load night train proposals — the public proposal tool's
storage layer (`adapters/proposal/README.md` §2.2, §7). Computing
(`POST /api/proposal/calc`, above) never writes anything; a proposal only
comes into existence through an explicit publish. Browsing lives in the
[Gallery](#gallery) section, comparison in [Analytics](#analytics).

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/proposal/publish` | Publish a computed proposal — the only user write path |
| `GET` | `/api/proposal/<id>` | Load a proposal |

Every proposal is stored **once**: the route decomposed into GTFS tables
(`proposals.routes`/`trips`/`stop_times`/`shapes`/`services`/`calendar` +
sidecar tables), the evaluation's `models`+`views` as JSON
(`input.parameters` is never stored — rebuilt on read from the
`scenario_id` pin). No half-states: every stored proposal has both a
route and an evaluation. There is exactly one state per proposal at any
time — publishing again (`mode: "overwrite"`) replaces it in place; the
previous state is hard-deleted in the same transaction. See
`db/README.md` and `adapters/proposal/README.md` §5 for the full storage
design.

<a id="proposal-publish"></a>

### `POST /api/proposal/publish`

The only user write path. `@require_auth` at the `TRUST_GUEST` floor — a
guest token is enough. The acting user always comes from the token, never
from the request body: **the server never persists a client-supplied
result** — `compute_request` carries inputs only, the server recomputes
it itself (via the exact same pipeline `POST /api/proposal/calc` uses)
and persists what it computed.

<details>
<summary>Request &amp; response details</summary>

**Request body**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `compute_request` | object | ✓ | The exact **resolved** `request` block from a `POST /api/proposal/calc` response — defaults applied, `scenario_id` concrete |
| `name` | string | ✓ | Proposal name, non-empty |
| `mode` | string | ✓ | `"new"` or `"overwrite"` |
| `proposal_id` | int | (✓) | Required for `mode: "overwrite"` (the owned proposal to replace); forbidden for `mode: "new"` (server-assigned) |
| `based_on_proposal_id` | int | — | Optional, informational only — timeline provenance ("built on this foreign proposal"), never used for lookup |

**Base-scenario rule**: `compute_request.scenario_id` must be the
*current* base scenario, or the request is rejected — published
proposals are always evaluated on the current parameter reality; what-if
scenarios are an analysis dimension (compute, compare), never an
artifact dimension. If the frontend explored under a what-if, it
recomputes on base before publishing.

**Response**: the published proposal in full — identical shape to
[`GET /api/proposal/<id>`](#get-proposal) below, including the
server-assigned `proposal_id` and prefixed row IDs
(`P{proposal_id}_V{proposal_version}_R1...`). The frontend adopts this id
as its loaded proposal, so a follow-up save is an ordinary `overwrite`
against it.

**Errors:**

| Status | `error` key | Meaning |
|--------|-------------|---------|
| `400` | `validation_error` | Malformed envelope or `compute_request` |
| `401` | — | Missing/invalid/expired token |
| `403` | `forbidden` | `mode: "overwrite"` on a `proposal_id` owned by someone else |
| `404` | `not_found` | `mode: "overwrite"` on an unknown `proposal_id` |
| `422` | `scenario_not_base` | `compute_request.scenario_id` isn't the current base |
| `422` | `domain_error` | Route or evaluation domain failure during recompute |
| `500` | `publish_error` | Unexpected pipeline/persistence failure |

</details>

<a id="get-proposal"></a>

### `GET /api/proposal/<id>`

Reconstructed compute-response shape (§2.1) plus proposal metadata — the
route is rebuilt from GTFS + sidecar tables, `evaluation.input.parameters`
rebuilt fresh via the `scenario_id` pin (never stored verbatim, §5.1).

**On-load refresh** (§4.2): if the stored proposal's `route_builder_
version`/`calc_version` has fallen behind the running code, or its
`scenario_id` is no longer the current base scenario, it's recomputed and
overwritten in place (`proposal_version` bumped, `update_log` gains a
`'recalculated'` row) before the response is built — transparent to the
caller beyond a slower response time; the returned proposal is always
current. `backend/scripts/refresh_proposals.py` (a periodic batch job) is
the primary mechanism — this fallback only matters for whatever it
hasn't reached yet.

<details>
<summary>Request &amp; response details</summary>

No request body.
```json
{
  "proposal_id": 5, "proposal_version": 1, "user_id": 1, "user_name": "David",
  "name": "Berlin Hbf – Wien Hbf",
  "created_at": "2026-08-04T12:00:00+00:00",
  "updated_at": "2026-08-04T12:00:00+00:00",
  "route_builder_version": "0.9.13", "calc_version": "0.9.10",
  "route_fingerprint": "sha256:...",
  "request": { "...": "the resolved compute_request this proposal was published from" },
  "route": { "route_id": "P5_V1_R1", "...": "identical shape to POST /api/proposal/calc's route block" },
  "evaluation": {
    "models": { "...": "..." },
    "input": { "parameters": { "...": "rebuilt fresh from the scenario_id pin" } },
    "views": { "...": "stored verbatim from publish time" }
  }
}
```
`404 not_found` if the `proposal_id` doesn't exist.

</details>

---

<a id="gallery"></a>

## Gallery

The browse surface of the proposal tool: one endpoint serving the
proposal list AND the map layers, over a union of user proposals and the
ONTD catalog of real, existing night trains (`adapters/proposal/README.md`
§7.1; WP10 step 6b).

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/proposals` | List, newest first (defaults) |
| `POST` | `/api/proposals` | Filter/sort/paginate + map sections, sources union |

<a id="list-proposals"></a>

### `GET` / `POST /api/proposals`

The gallery + map contract in one endpoint (`adapters/proposal/README.md`
§7.1). `GET` returns every proposal as a summary, newest first — the
empty-filter convenience case of `POST` below. `POST` accepts a generic
filter/sort/pagination model plus an `include` list that picks which
response **sections** to compute; a section not listed in `include`
doesn't run its query at all.

<details>
<summary>Request &amp; response details</summary>

**What can be filtered, and how**

| Filter key | Column | Kind | Shape |
|---|---|---|---|
| `sources` | — | source union | `["proposal"]`, `["existing"]`, or both — **default BOTH when omitted**. `"existing"` = the ONTD catalog of real night trains (`ontd.route_summaries`) |
| `proposal_ids` | `proposal_id` | list (OR) | `[int, ...]` |
| `user_ids` | `user_id` | list (OR) | `[int, ...]` |
| `composition_ids` | `composition_id` | list (OR) | `[str, ...]` |
| `demand_kpis_placeholder` | `demand_kpis_placeholder` | list (OR) | `[bool, ...]` |
| `countries` | `countries` (`TEXT[]`) | array, any/all | `[str, ...]` or `{"values": [...], "mode": "any"\|"all"}` |
| `stop_ids` | `stop_ids` (`TEXT[]`) | array, any/all | `[str, ...]` or `{"values": [...], "mode": "any"\|"all"}` |
| `name` | `name` | substring | case-insensitive `str` |
| `total_distance_km`, `total_time_h`, `avg_speed_kmh`, `n_stops` | same | range | `{"min": num, "max": num}` |
| `cost_eur_per_train_km`, `revenue_eur_per_train_km`, `margin_eur_per_train_km`, `subsidy_eur_per_year` | same | range | `{"min": num, "max": num}` |
| `demand_trips_per_year`, `demand_trip_km_per_year`, `shift_air_trips_per_year`, `shift_air_trip_km_per_year`, `shift_car_trips_per_year`, `shift_car_trip_km_per_year`, `co2_savings_t_per_year`, `subsidy_eur_per_t_co2` | same | range | `{"min": num, "max": num}` |
| `likes_count`, `comments_count` | live-joined from `proposals.likes` / `proposals.comments` | range | `{"min": num, "max": num}` |
| `created_at`, `updated_at` | same | range | `{"min": iso8601, "max": iso8601}` |
| `trip_windows` | reaches into `stop_times` | special | see below |
| `bbox` | `geom_simplified` | special | `[west, south, east, north]` |

**Not filterable**: `route_builder_version`/`calc_version` (internal/
analytical, not a gallery-facing dimension) and `scenario_id` (every
gallery row is always on the current base scenario by construction — the
system keeps it that way on its own, §4.2, with no client-visible flag
for the transient exception).

**What can be sorted by** — every column in the table above except the
three "special" rows (`sources`, `trip_windows`, `bbox`, none of which
are single-valued), plus `route_fingerprint`. `sort` is
`[{"by": <column>, "dir": "asc"|"desc"}]`; an unsortable `by` 400s.

**Array filter modes** (`countries`/`stop_ids` only — every other list
filter is OR-only by construction, since a proposal has exactly one
`composition_id`/`user_id`/etc.): a plain list is `mode: "any"`
(overlap `&&` — the proposal touches *at least one* of these); `{"values":
[...], "mode": "all"}` is containment (`@>` — the proposal touches
*every* one of these).

**`trip_windows`** reaches past the summary table into the stored
timetables: each entry constrains the departure and/or arrival time at
one stop, and a proposal matches only when a **single trip** satisfies
every entry. Times are wall-clock `"HH:MM"` with an optional integer
`day_offset` for next-day arrivals.

**`bbox`** is `[west, south, east, north]` — proposals whose
`geom_simplified` intersects the box (GiST-indexed).

`include` defaults to `["summaries"]` if omitted. `limit`/`offset` only
apply to the `summaries` section — `map_lines`/`map_stop_counts`/
`map_country_counts` always reflect the full filtered set (the map isn't
paginated).

```json
{
  "filter": {
    "sources":         ["proposal", "existing"],
    "proposal_ids":    [5],
    "user_ids":        [1],
    "countries":       {"values": ["DE", "AT"], "mode": "all"},
    "stop_ids":        ["DE_BERLIN_HBF"],
    "composition_ids": ["NEW-BAL-7"],
    "demand_kpis_placeholder": [true],
    "name": "wien",

    "total_distance_km":        { "min": 800, "max": 1500 },
    "total_time_h":              { "min": 8 },
    "avg_speed_kmh":              { "max": 90 },
    "n_stops":                    { "max": 12 },
    "cost_eur_per_train_km":      { "min": 0 },
    "revenue_eur_per_train_km":   { "min": 0 },
    "margin_eur_per_train_km":    { "min": 0 },
    "subsidy_eur_per_year":       { "max": 5000000 },
    "demand_trips_per_year":      { "min": 0 },
    "demand_trip_km_per_year":    { "min": 0 },
    "shift_air_trips_per_year":   { "min": 0 },
    "shift_air_trip_km_per_year": { "min": 0 },
    "shift_car_trips_per_year":   { "min": 0 },
    "shift_car_trip_km_per_year": { "min": 0 },
    "co2_savings_t_per_year":     { "min": 0 },
    "subsidy_eur_per_t_co2":      { "min": 0 },
    "likes_count":                 { "min": 1 },
    "created_at":                  { "min": "2026-01-01T00:00:00+00:00" },
    "updated_at":                  { "min": "2026-01-01T00:00:00+00:00" },

    "trip_windows": [
      { "stop_id": "DE_BERLIN_HBF", "departure": { "from": "20:00", "to": "23:00" } },
      { "stop_id": "AT_WIEN_HBF",   "arrival":   { "from": "07:00", "to": "09:30", "day_offset": 1 } }
    ],

    "bbox": [8.0, 45.0, 20.0, 55.0]
  },
  "sort":    [{ "by": "likes_count", "dir": "desc" }],
  "limit":   50,
  "offset":  0,
  "include": ["summaries", "map_lines", "map_stop_counts", "map_country_counts"]
}
```

**Response** — one key per requested `include` section:

```json
{
  "summaries": {
    "total": 12,
    "proposals": [
      {
        "source": "proposal",
        "proposal_id": 5, "proposal_version": 2, "user_id": 1,
        "name": "Berlin Hbf – Wien Hbf",
        "route_fingerprint": "sha256:...", "composition_id": "NEW-BAL-7",
        "scenario_id": 1, "route_builder_version": "0.9.13", "calc_version": "0.9.11",
        "total_distance_km": 683.4, "total_time_h": 9.0, "avg_speed_kmh": 76.0,
        "n_stops": 3, "countries": ["AT", "DE"], "stop_ids": ["DE_BERLIN_HBF", "..."],
        "cost_eur_per_train_km": 12.4, "revenue_eur_per_train_km": 14.1,
        "margin_eur_per_train_km": 1.7, "subsidy_eur_per_year": 0.0,
        "demand_trips_per_year": 4200, "demand_trip_km_per_year": 2870000,
        "shift_air_trips_per_year": 1470, "shift_air_trip_km_per_year": 1004000,
        "shift_car_trips_per_year": 840, "shift_car_trip_km_per_year": 574000,
        "co2_savings_t_per_year": 210.4, "subsidy_eur_per_t_co2": null,
        "demand_kpis_placeholder": true, "co2_g_per_pax_km": 33.0,
        "likes_count": 3,
        "created_at": "2026-08-01T09:00:00+00:00",
        "updated_at": "2026-08-04T12:00:00+00:00"
      },
      {
        "source": "existing",
        "route_id": "42",
        "name": "Nightjet Berlin – Wien",
        "composition_id": "NJ-STD",
        "total_distance_km": 705.0, "total_time_h": 10.5, "avg_speed_kmh": 67.0,
        "n_stops": 8, "countries": ["AT", "CZ", "DE"],
        "stop_ids": ["DE_BERLIN_HBF", "..."],
        "co2_g_per_pax_km": 33.0,
        "geometry_routed": true,
        "ontd_url": "https://back-on-track.eu/nighttrains/?route_id=42"
      }
    ]
  },
  "map_lines": {
    "type": "FeatureCollection",
    "features": [
      {
        "type": "Feature",
        "geometry": { "type": "LineString", "coordinates": ["..."] },
        "properties": {
          "stop_a": "AT_WIEN_HBF", "stop_b": "DE_BERLIN_HBF",
          "proposal_count": 2, "existing_count": 1, "total_count": 3,
          "proposal_ids": [5, 8], "existing_route_ids": ["42"],
          "avg_margin_eur_per_train_km": 0.9
        }
      }
    ]
  },
  "map_stop_counts": [
    { "stop_id": "DE_BERLIN_HBF", "lat": 52.525, "lon": 13.369,
      "n_proposals": 3, "n_existing": 1, "n": 4 }
  ],
  "map_country_counts": {
    "type": "FeatureCollection",
    "features": [
      {
        "type": "Feature",
        "geometry": { "type": "MultiPolygon", "coordinates": ["..."] },
        "properties": { "country": "DE", "n_proposals": 4, "n_existing": 2, "n": 6 }
      }
    ]
  }
}
```

`summaries` rows come in two shapes, discriminated by `source` (WP10
step 6b — the gallery is a UNION of `proposals.proposal_summaries` and
the ONTD catalog's `ontd.route_summaries`, defaulting to both).
`"proposal"` rows are a straight read off `proposals.proposal_summaries`
(`adapters/proposal/README.md` §5.4) plus `likes_count` and
`comments_count` (live-joined from `proposals.likes` /
`proposals.comments`, not summary columns — engagement changes
independently of publish/refresh, so storing it would go stale;
`comments_count` excludes deleted comments, matching
[`GET /api/proposal/<id>/engagements`](#proposal-engagements)).
The counts are here so a gallery card can show them without one
engagements call per row; comment bodies and the timeline are not. `"existing"` rows
carry the **reduced descriptive shape** shown above — identity, the
shared metric subset, `geometry_routed` (whether the drawn line is real
routing or a straight-line fallback), and `ontd_url` (deep link to the
route's public ONTD page); proposal-only fields are **omitted**, not
null-padded. Two namespace notes: `stop_ids` is the shared Target
Network namespace on both sides (step 6a's mapping — ONTD stops the
mapping couldn't cover keep raw ONTD ids), while `composition_id` is
**not** shared — proposal rows carry curated calibration ids, existing
rows carry the ONTD catalog's own ids, so a `composition_ids` filter
matches literally across both — filtering by a proposal composition id
therefore excludes every existing route from the list AND the map, with
no other signal. An existing row's `composition_id` is an **opaque
label**: no endpoint resolves it (`/api/params/compositions` serves the
curated calibration catalog only), by decision — see
`db/ontd/README.md`. Existing rows have NULL financials,
engagement counts, and timestamps — every range filter on those columns excludes
them via plain SQL NULL semantics (no `sources` filter needed), and the
default `updated_at DESC` sort places them after every proposal
(`NULLS LAST`).
`demand_*`/`shift_*`/`co2_savings_*` are deterministic placeholder
figures (`demand_kpis_placeholder: true`) until the demand model lands —
see §8. `co2_g_per_pax_km` is the flat night-train factor from
`models/emissions` (decision 24) until the energy-based,
country-resolved model enriches it per route; the per-mode air/car
reference values for the gallery's mode comparison come from the calc
response's `evaluation.models.emissions` entry, not from the row.

`map_lines` is **not** one feature per proposal or route — it's one
feature per distinct stop-pair **corridor** (direction-agnostic:
outbound and return share a corridor), and proposals and existing trains
over the same two stops land on **one** feature
(`ontd.route_corridors` was built at the same grain and in the same
Target Network stop namespace precisely for this). Every map section
carries the per-source split **and** the total — decision 2026-08-06:
all three, always — so a frontend drives thickness/size off the total
and colours or toggles by source without a second query: `map_lines`
features carry `proposal_count` / `existing_count` / `total_count` plus
`proposal_ids` / `existing_route_ids`; `map_stop_counts` rows and
`map_country_counts` features carry `n_proposals` / `n_existing` / `n`.
`avg_margin_eur_per_train_km` is the mean across the corridor's
proposals only (`null` on corridors served exclusively by existing
trains). Corridor geometry prefers a proposal shape and falls back to
the existing route's own. `map_country_counts` is one feature per
country touched by the filtered set, carrying the country's own border
geometry (`input_params.countries.country_geom`) so the frontend
doesn't need a second lookup for the choropleth — `geometry: null` for
a country code with no matched border (e.g. `"UNK"`, or an ONTD country
outside the 28-country catalog like `UA`/`TR`). Neither paginates.
`map_stop_counts` is one row per stop touched by the filtered set,
joined to the *current base* scenario's pinned `stop_infrastructures`
snapshot for coordinates — ONTD stops that kept raw (unmapped) ids
don't join the catalog and get no marker.

**Errors:** `400 validation_error` for an unknown filter/sort/include key,
a malformed range/list/array-mode/trip_windows/bbox shape, an unknown
`sources` value, or an empty `sources` list.

</details>

---

<a id="analytics"></a>

## Analytics

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/proposals/compare` | Compare two sides — stored proposals or what-if overrides |

<a id="compare-proposals"></a>

### `POST /api/proposals/compare`

Compare two sides (`adapters/proposal/README.md` §7.3). Each side is
anchored on one stored proposal and may override `scenario_id` and/or
`composition_id`. A side **without** overrides is the stored proposal
as-is (`published: true`); a side **with** any override is computed
ephemerally — the anchor's stored compute request with the overridden
fields, never persisted, `published: false`. Same anchor on both sides =
variant compare on one route (e.g. TAC scenario A vs B); different
anchors = cross-proposal compare. Overriding never touches the stored
proposal — publishing remains its own explicit act
(`POST /api/proposal/publish`, base-scenario rule applies).

Stateless and unauthenticated, same policy as `POST /api/proposal/calc`.
Each side's anchor runs the on-load refresh (§4.2) first, so stored
sides — and the stored compute requests that override sides replay —
are always at the current base scenario and current code versions.
Override sides run a live compute each (through the same pipeline as
`/calc` — cache-backed once WP13 lands), so responses can take as long
as a `/calc` call per overridden side; the UI needs a loading state.

<details>
<summary>Request &amp; response details</summary>

```json
{
  "sides": [
    {"proposal_id": 123},
    {"proposal_id": 123, "scenario_id": 4}
  ]
}
```

Exactly 2 sides (the shape allows more later). Per side: `proposal_id`
(required, the anchor), `scenario_id`/`composition_id` (optional
overrides) — no other keys. Any override key present routes the side
through the compute path, even if its value equals the stored one.

The **diff is side B minus side A** (`sides[1] - sides[0]`) throughout.

```json
{
  "sides": [
    {
      "published": true,
      "proposal_id": 123, "proposal_version": 1, "user_id": 1, "user_name": "David",
      "name": "Berlin Hbf – Wien Hbf",
      "created_at": "...", "updated_at": "...",
      "route_builder_version": "0.9.13", "calc_version": "0.9.10",
      "route_fingerprint": "sha256:...",
      "request": { "...": "the stored resolved compute_request" },
      "route": { "...": "..." },
      "evaluation": { "models": {}, "input": {}, "views": {} },
      "summary": { "...": "the proposal's gallery summary row, likes_count included" }
    },
    {
      "published": false,
      "proposal_id": 123,
      "overrides": {"scenario_id": 4},
      "route_builder_version": "0.9.13", "calc_version": "0.9.10",
      "route_fingerprint": "sha256:...",
      "cache_hit": false,   // true when this side rode the §2.3 compute cache
      "request": { "...": "the anchor's compute_request with the overrides applied, resolved" },
      "route": { "...": "..." },
      "evaluation": { "models": {}, "input": {}, "views": {} },
      "summary": { "...": "built on the fly by the same projection publish runs — no likes_count, no geometry" }
    }
  ],
  "diff": {
    "summary": {
      "cost_eur_per_train_km": {"a": 21.4, "b": 19.9, "abs": -1.5, "rel": -0.070093},
      "...": "every gallery KPI column (§5.4), gallery column order"
    },
    "views": {
      "route": { "data": { "per_year": { "all": { "cost": { "...": "..." } } } } },
      "...": "per-leaf {a, b, abs, rel} over the shared views trees — every view, every cost category, every normalisation"
    },
    "views_unmatched": {
      "a_only": ["per_trip_pair.data.T3"],
      "b_only": []
    }
  },
  "route_context": {
    "fingerprints": ["sha256:...", "sha256:..."],
    "route_identical": true,
    "differing_request_fields": ["scenario_id"]
  }
}
```

Each side is the full `POST /api/proposal/calc` response shape (stored
sides additionally carry the load endpoint's metadata block, computed
sides the anchor `proposal_id` + applied `overrides`), plus a `summary`
block so the compare view can render the same headline KPIs as the
gallery.

Diff semantics: numeric leaves become `{a, b, abs, rel}` with
`abs = b - a` and `rel = (b - a) / |a|` (`null` on a zero base);
non-numeric content (descriptions, filter labels, normalisation
metadata) never diffs. The diff runs on **structural ids**: a published
side's trip-keyed views (`per_trip_pair`, `..._per_country`,
`..._per_od`, `..._per_section`, `per_trip_per_stop`) are keyed by that
proposal's own `P{id}_V{n}_` prefix, so both sides are neutralised to
the bare `T1` form before diffing — otherwise no trip-keyed view could
match across two proposals. The sides themselves keep their real
prefixed ids; only the diff tree (and the `views_unmatched` paths) is
structural. Keys still present on only one side after that — genuinely
different countries, ODs, stops, trip counts, or **coach classes**
(comparing two different compositions puts each one's coach types here)
— are collected as dotted paths under `views_unmatched` rather than
half-diffed. `route_context` states whether the two sides are the same
physical route (§3.1 fingerprints) and which resolved compute-request
fields differ.

**Errors:** `400 validation_error` (side count, unknown keys, wrong
types); `404 not_found` when a side's anchor doesn't exist (the message
names which side); `422 domain_error` when an override compute fails
(unknown scenario/composition — message prefixed with the side index).

</details>

No delete endpoint (`adapters/proposal/README.md` §7.4) — proposals are
removed manually in the database if ever needed. `proposal_summaries` has
no FK to `proposals.proposals` (§5.4 — a derived, rebuildable
projection, not authoritative data), so nothing cascades a manual
delete: clean up `proposal_summaries` in the same statement/transaction
(`DELETE FROM proposals.proposal_summaries WHERE proposal_id = ...`) or
the gallery/map endpoint keeps returning an orphaned row for it.

---

<a id="engagement"></a>
<a id="proposal-engagement"></a>

## Engagement

Thumbs-up likes, a flat comment thread, and the event timeline for one
proposal. All three key on the stable `proposal_id`, not a specific
`proposal_version` — engagement is about the proposal as an ongoing
discussion and survives it being overwritten or refreshed into a new
state (see `db/README.md` for the soft-reference rationale).

Reading is one endpoint. `GET` is open, same as loading a proposal;
every write needs at least a guest token (`@require_auth`,
`TRUST_GUEST`) — the same floor a guest already clears to save a
proposal — and is rate limited per authenticated user (limits in
`api/config.py`; the per-user bucket key in `api/auth_middleware.py`,
falling back to the client address for anonymous or Keycloak callers).

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/proposal/<id>/engagements` | Likes, comments and the merged event timeline |
| `POST` | `/api/proposal/<id>/like` | Like (idempotent) |
| `DELETE` | `/api/proposal/<id>/like` | Unlike (idempotent) |
| `POST` | `/api/proposal/<id>/comment` | Add a comment |
| `PATCH` | `/api/proposal/<id>/comment/<cid>` | Edit own comment |
| `DELETE` | `/api/proposal/<id>/comment/<cid>` | Delete own comment |

For a list view, `likes_count` and `comments_count` come with every
gallery row on [`POST /api/proposals`](#list-proposals) — don't call this
endpoint per row.

<a id="proposal-engagements"></a>

### `GET /api/proposal/<id>/engagements`

<details>
<summary>Request &amp; response details</summary>

No request body. `liked_by_me` reflects the caller's own token — always
`false` for an unauthenticated read. `404 not_found` if `proposal_id`
doesn't exist.

**Response**
```json
{
  "proposal_id": 5,
  "likes": { "count": 4, "liked_by_me": true },
  "comments": {
    "count": 1,
    "items": [
      {
        "comment_id": 12, "proposal_id": 5, "proposal_version": 2,
        "user_id": 3, "user_name": "Bjarne",
        "body": "This routing through Zürich adds a lot of dwell time.",
        "created_at": "2026-07-29T09:12:00+00:00",
        "updated_at": "2026-07-29T09:12:00+00:00"
      }
    ]
  },
  "timeline": [
    { "event": "published", "at": "2026-07-28T14:03:11+00:00",
      "proposal_version": 1,
      "actor": { "user_id": 3, "user_name": "David" }, "detail": null },
    { "event": "commented", "at": "2026-07-29T09:12:00+00:00",
      "proposal_version": 2,
      "actor": { "user_id": 7, "user_name": "Bjarne" },
      "detail": { "comment_id": 12, "edited": false } },
    { "event": "recalculated", "at": "2026-08-01T02:00:00+00:00",
      "proposal_version": 3, "actor": null,
      "detail": { "trigger": "calc_version", "from": "0.9.10", "to": "0.9.11" } }
  ]
}
```

`comments.items` is the flat thread, oldest first, and `comments.count`
its length. `proposal_version` on a comment is a context stamp — the
state that was current when it was posted, not re-derived later.
`user_name` is `"[deleted]"` when `user_id` is `null` (the author's
account was deleted).

**Timeline events**, oldest first:

| `event` | Source | `detail` |
|---------|--------|----------|
| `published` | publish, `mode: "new"` | `null` |
| `overwritten` | publish, `mode: "overwrite"` | `null` |
| `recalculated` | system refresh | `{"trigger": "calc_version"\|"route_builder_version"\|"base_scenario_moved", "from": …, "to": …}` |
| `branched_from` | publish with `based_on_proposal_id` | `{"source_proposal_id": int}` — on the new proposal |
| `branched_to` | publish with `based_on_proposal_id` | `{"source_proposal_id": int}` — on the proposal it was built from |
| `liked` | a standing like | `null` |
| `commented` | a live comment | `{"comment_id": int, "edited": bool}` |

`proposal_version` on every event is the state counter **after** it.
`actor` is `null` **only** for a system event (a version-bump or
base-scenario refresh, `adapters/proposal/README.md` §4.2) — that is what
separates a system recalculation from a user overwrite. A deleted
account is not a system event: it renders as
`{"user_id": null, "user_name": "[deleted]"}`.

**The timeline is a projection of current state, not an audit trail.**
A withdrawn like and a deleted comment leave no trace, and an edited
comment appears at its edit time (`edited: true`) rather than its post
time — so the sequence a reader sees can change retroactively. Only the
publish/refresh events are genuinely append-only, which is what makes
"commented on state 3, route overwritten afterwards, then recalculated
on a new calc version" reconstructible at all.

</details>

<a id="proposal-like"></a>

### `POST` / `DELETE /api/proposal/<id>/like`

<details>
<summary>Request &amp; response details</summary>

No request body on either. Both are idempotent: liking twice or unliking
when no like exists returns the current state rather than erroring.
Unliking is a hard delete — the like leaves the timeline with it.

**Response** (both)
```json
{"count": 4, "liked_by_me": true}
```

`404 not_found` if `proposal_id` doesn't exist.

</details>

<a id="proposal-comment"></a>

### `POST /api/proposal/<id>/comment`

<details>
<summary>Request &amp; response details</summary>

**Request body**
```json
{"body": "This routing through Zürich adds a lot of dwell time — have you compared the Basel alternative?"}
```
`body` is required, non-empty, and capped at
`config.COMMENT_BODY_MAX_LEN` characters (default 4000).

Returns the new comment (`201`) in the same shape `comments.items`
uses above. `404 not_found` if `proposal_id` doesn't exist.

</details>

<a id="proposal-comment-item"></a>

### `PATCH` / `DELETE /api/proposal/<id>/comment/<cid>`

<details>
<summary>Request &amp; response details</summary>

Author-only — `403 forbidden` if the caller didn't write the comment.
`404 not_found` if `comment_id` doesn't exist under that `proposal_id`,
or was already deleted.

**Request body** (`PATCH` only)
```json
{"body": "Updated: compared both, Basel is 12 min faster."}
```
Same validation as `POST`. Returns the updated comment (`200`); its
timeline event moves to the edit time.

`DELETE` returns `204` with no body. The comment disappears from both
the thread and the timeline. Storage keeps a tombstone row so
`comment_id` stays stable, which is why a second `PATCH`/`DELETE` on it
is a `404` rather than a resurrection — but nothing surfaces it.

</details>

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
| `Evaluation — results / view` | Live — the five output views `POST /api/proposal/calc`'s evaluation section produces (`models/evaluation/views.py:VIEW_META`) |
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