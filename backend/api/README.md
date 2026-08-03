# Night Train — Backend API Reference

Base URL: `http://localhost:5050`

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

**Worked examples:** request fixtures for the main endpoints are checked
in under [`../scripts/data/`](../scripts/data/); the matching
`*_output.json` response files linked below are generated locally by
running the manual test scripts in [`../scripts/`](../scripts/) against a
running stack (they are not checked in). Each endpoint section below links
its own example files.

## Table of Contents

- [Health](#health)
- [Auth](#auth)
- [Feedback](#feedback)
  - [`POST /api/feedback`](#post-feedback) — submit feedback
  - [`GET /api/feedback/categories`](#feedback-categories) — suggested category/sub_category values
- [Proposals](#proposals) — publish, list, and load
  - [`POST /api/proposal/publish`](#proposal-publish) — publish a computed proposal, the only write path
  - [`GET` / `POST /api/proposals`](#list-proposals) — list proposals
  - [`GET /api/proposal/<id>`](#get-proposal) — load a proposal
- [Proposal Engagement](#proposal-engagement) — likes and comments
  - [`GET` / `POST` / `DELETE /api/proposal/<id>/likes`](#proposal-likes) — like/unlike a proposal
  - [`GET` / `POST /api/proposal/<id>/comments`](#proposal-comments) — read/add comments
  - [`PATCH` / `DELETE /api/proposal/<id>/comments/<cid>`](#proposal-comment-item) — edit/delete own comment
- [Input Parameters](#input-parameters)
- [Scenarios](#scenarios)
  - [`GET /api/scenarios`](#get-scenarios) — list all scenarios, grouped by current status
- [Proposal Compute (merged)](#proposal-compute) — route + evaluation in one call, stateless
  - [`POST /api/proposal/calc`](#proposal-calc) — plan a route and evaluate it
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

<a id="proposals"></a>

## Proposals

Publish, list, and load night train proposals — the public proposal
tool's storage layer (`docs/PROPOSALS_DESIGN.md` §2.2, §7). Computing
(`POST /api/proposal/calc`, above) never writes anything; a proposal only
comes into existence through an explicit publish.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/proposal/publish` | Publish a computed proposal — the only user write path |
| `GET` | `/api/proposals` | List proposals, newest first |
| `POST` | `/api/proposals` | Filtered/paginated list |
| `GET` | `/api/proposal/<id>` | Load a proposal |

Every proposal is stored **once**: the route decomposed into GTFS tables
(`proposals.routes`/`trips`/`stop_times`/`shapes`/`services`/`calendar` +
sidecar tables), the evaluation's `models`+`views` as JSON
(`input.parameters` is never stored — rebuilt on read from the
`scenario_id` pin). No half-states: every stored proposal has both a
route and an evaluation. There is exactly one state per proposal at any
time — publishing again (`mode: "overwrite"`) replaces it in place; the
previous state is hard-deleted in the same transaction. See
`db/README.md` and `docs/PROPOSALS_DESIGN.md` §5 for the full storage
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

<a id="list-proposals"></a>

### `GET` / `POST /api/proposals`

`GET` returns every proposal as a summary, newest first. `POST` accepts
filters and pagination. This is the WP5-minimal contract — full
range/list/substring filters over every summary column, map sections,
and the `trip_windows` timetable filter land in WP6.

<details>
<summary>Request &amp; response details</summary>

**Request body** (`POST` only, all fields optional)
```json
{
  "filter": { "user_ids": [1] },
  "limit": 50,
  "offset": 0
}
```

**Response**
```json
{
  "total": 12,
  "proposals": [
    {
      "proposal_id": 5, "proposal_version": 2, "user_id": 1,
      "name": "Berlin Hbf – Wien Hbf",
      "route_fingerprint": "sha256:...", "composition_id": "NEW-BAL-7",
      "scenario_id": 1, "route_builder_version": "0.9.13", "calc_version": "0.9.10",
      "total_distance_km": 683.4, "total_time_h": 9.0, "avg_speed_kmh": 76.0,
      "n_stops": 3, "countries": ["AT", "DE"], "stop_ids": ["DE_BERLIN_HBF", "..."],
      "cost_eur_per_train_km": 12.4, "revenue_eur_per_train_km": 14.1,
      "margin_eur_per_train_km": 1.7, "subsidy_eur_per_year": 0.0,
      "demand_trips_per_year": 4200, "demand_trip_km_per_year": 2870000,
      "shift_air_trips_per_year": 1470, "shift_air_trip_km_per_year": 1004000,
      "shift_car_trips_per_year": 840, "shift_car_trip_km_per_year": 574000,
      "co2_savings_t_per_year": 210.4, "subsidy_eur_per_t_co2": null,
      "demand_kpis_placeholder": true,
      "updated_at": "2026-08-04T12:00:00+00:00"
    }
  ]
}
```
Every row is a straight read off `proposals.proposal_summaries` — see
`docs/PROPOSALS_DESIGN.md` §5.4. `demand_*`/`shift_*`/`co2_*` are
deterministic placeholder figures (`demand_kpis_placeholder: true`) until
the demand model lands — see §8.

</details>

<a id="get-proposal"></a>

### `GET /api/proposal/<id>`

Reconstructed compute-response shape (§2.1) plus proposal metadata — the
route is rebuilt from GTFS + sidecar tables, `evaluation.input.parameters`
rebuilt fresh via the `scenario_id` pin (never stored verbatim, §5.1).

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

No delete endpoint (`docs/PROPOSALS_DESIGN.md` §7.4) — proposals are
removed manually in the database if ever needed.

---

## Proposal Engagement

Thumbs-up likes and a flat comment thread per proposal. Both key on the
stable `proposal_id`, not a specific `proposal_version` — a like or a
comment is about the proposal as an ongoing discussion and survives it
being edited into a new version (see `db/README.md` for the soft-reference
rationale). `GET`s are open, same as loading a proposal; writes need at
least a guest token (`@require_auth`, `TRUST_GUEST`) — the same floor a
guest already clears to save a proposal.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/proposal/<id>/likes` | Like count + whether the caller liked it |
| `POST` | `/api/proposal/<id>/likes` | Like (idempotent) |
| `DELETE` | `/api/proposal/<id>/likes` | Unlike (idempotent) |
| `GET` | `/api/proposal/<id>/comments` | Flat comment thread, oldest first |
| `POST` | `/api/proposal/<id>/comments` | Add a comment |
| `PATCH` | `/api/proposal/<id>/comments/<cid>` | Edit own comment |
| `DELETE` | `/api/proposal/<id>/comments/<cid>` | Soft-delete own comment |

<a id="proposal-likes"></a>

### `GET` / `POST` / `DELETE /api/proposal/<id>/likes`

<details>
<summary>Request &amp; response details</summary>

No request body on any of the three. `liked_by_me` reflects the caller's
own token — always `false` for an unauthenticated `GET`. `POST`/`DELETE`
are idempotent: liking twice or unliking when no like exists both just
return the current state rather than erroring.

**Response** (all three)
```json
{"count": 4, "liked_by_me": true}
```

`404 not_found` if `proposal_id` doesn't exist.

</details>

<a id="proposal-comments"></a>

### `GET` / `POST /api/proposal/<id>/comments`

<details>
<summary>Request &amp; response details</summary>

**Request body** (`POST` only)
```json
{"body": "This routing through Zürich adds a lot of dwell time — have you compared the Basel alternative?"}
```
`body` is required, non-empty, max 4000 characters.

**Response** (`GET`)
```json
{
  "proposal_id": 5,
  "comments": [
    {
      "comment_id": 12, "proposal_id": 5, "proposal_version": 2,
      "user_id": 3, "user_name": "Bjarne",
      "body": "This routing through Zürich adds a lot of dwell time — have you compared the Basel alternative?",
      "is_deleted": false,
      "created_at": "2026-07-29T09:12:00+00:00",
      "updated_at": "2026-07-29T09:12:00+00:00"
    }
  ]
}
```
`proposal_version` is a context stamp — the version that was current when
the comment was posted, not re-derived on later versions. A soft-deleted
comment (`is_deleted: true`) keeps its place in the list with `body`
cleared server-side. `user_name` is `"[deleted]"` when `user_id` is
`null` (the author's account was later deleted). `POST` returns the new
comment (`201`); `404 not_found` if `proposal_id` doesn't exist.

</details>

<a id="proposal-comment-item"></a>

### `PATCH` / `DELETE /api/proposal/<id>/comments/<cid>`

<details>
<summary>Request &amp; response details</summary>

Author-only — `403 forbidden` if the caller didn't write the comment.
`404 not_found` if `comment_id` doesn't exist under that `proposal_id`,
or is already soft-deleted.

**Request body** (`PATCH` only)
```json
{"body": "Updated: compared both, Basel is 12 min faster."}
```
Same validation as `POST`. Returns the updated comment (`200`).

`DELETE` soft-deletes (clears `body`, sets `is_deleted`) and returns `204`
with no body.

</details>

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

<a id="proposal-compute"></a>

## Proposal Compute (merged)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/proposal/calc` | Plan a route **and** evaluate it in one call — stateless, no persistence |

<a id="proposal-calc"></a>

### `POST /api/proposal/calc`

The merged compute endpoint (`docs/PROPOSALS_DESIGN.md` §2.1, WP2). One
request → route + evaluation, one response, no side effects: it never
writes to the database and never touches `admin.users` identity, so
there is no `proposal` block in the response and no auth header has any
effect. This is the sole route-planning-and-costing entry point —
the former two-call `POST /api/route/plan` + `POST /api/evaluation/calc`
pair was removed in the WP5 cutover (`docs/PROPOSALS_DESIGN.md` §10).

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
  "calc_version": "0.9.10",
  "route_fingerprint": "sha256:3f9a1c...",
  "cache_hit": false,
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

Four things worth calling out explicitly (`docs/PROPOSALS_DESIGN.md` §2.1):

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
   `adapters/proposal_projection.py`; it agrees between ephemeral and
   published forms of the identical route by construction (the canonical
   extract never reads `route_id`/`trip_id`/`geometry_id`). `cache_hit`
   is always `false` for now — no compute cache exists yet (WP13 wires
   the real lookup; the field is added early so that lands as a pure
   logic swap, not a response-shape change).

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
| `comp_id`, `comp_description`, `operator_id` | Identity |
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
  "evaluation":      {"version": "...", "description": "...", "formulas": {"...": "..."}}
}
```

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
dimension — it's the whole-route aggregate). The other five views nest a
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
| `per_sold_place_km` | dict per class_main, €/sold-place-km | Each class's allocated cost ÷ its OWN sold place-km — 50% occupancy doubles the per-sold cost; classes without sales omitted; `null` only for scopes without per-class data |
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
the field the proposal summary/list endpoints read as `margin_eur_per_train_km`'s
`net_eur` counterpart (see [Proposals](#proposals)).

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