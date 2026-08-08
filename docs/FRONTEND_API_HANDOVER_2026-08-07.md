# Frontend API handover — proposals refactor

**Date:** 2026-08-07 · **Audience:** frontend (Bjarne) · **Backend branch:** `backend-dev`

Everything the backend refactor changed, from a frontend perspective, organised
by endpoint. Nothing here is a proposal for future work — it is all live on
`backend-dev` today.

**Full endpoint reference** (exact request/response bodies, error codes):
[`../backend/api/README.md`](../backend/api/README.md). This document is the
*diff*; that one is the *spec*.
**Design rationale** (why things are shaped this way, locked decisions):
[`../backend/adapters/proposal/README.md`](../backend/adapters/proposal/README.md).

---

## 0. TL;DR — what breaks

| Was | Is | Status in `frontend/` |
|---|---|---|
| `POST /api/route/plan` | `POST /api/proposal/calc` | ✅ migrated 2026-08-07 |
| `POST /api/evaluation/calc` | `POST /api/proposal/calc` (same call) | ✅ migrated 2026-08-07 |
| — | `POST /api/proposal/publish` | ❌ not built |
| `GET/POST /api/proposals` (flat) | `POST /api/proposals` (sectioned) | ❌ not built |
| — | `POST /api/proposals/compare` | ❌ not built |
| `GET /api/proposal/<id>/likes` | *removed* → `GET …/engagements` | ❌ not built |
| `POST`/`DELETE /api/proposal/<id>/likes` | `POST`/`DELETE …/like` | ❌ not built |
| `GET /api/proposal/<id>/comments` | *removed* → `GET …/engagements` | ❌ not built |
| `POST /api/proposal/<id>/comments` | `POST …/comment` | ❌ not built |
| `PATCH`/`DELETE …/comments/<cid>` | `PATCH`/`DELETE …/comment/<cid>` | ❌ not built |

The two retired endpoints are **removed, not deprecated** — they 404.

The ✅ rows were fixed in a narrow pass that only restored the pre-existing
build/evaluate flow. Everything marked ❌ is greenfield: the backend is ready,
the UI does not exist yet.

**Cross-cutting renames** (§6) apply everywhere, including to endpoints you
haven't touched yet.

---

## 1. `POST /api/proposal/calc` — the merged compute endpoint

Replaces both `/api/route/plan` and `/api/evaluation/calc`. One stateless call
returns route **and** evaluation. No persistence, no auth, no side effects.

### Request

Identical to the old plan request, minus persistence identity — there are no
server-side drafts, so `proposal_id`/`proposal_version` don't exist here.

```jsonc
{
  "stops":                ["stop_id", "..."],   // required, min 2
  "composition_id":       "REF-BAL-9",          // required
  "scenario_id":          4,                    // optional; omitted = current base
  "timetable_mode":       "simpleAutomatic" | "simpleAutomaticWithFixedNight",
  "fixed_night_interval": ["stop_id", "stop_id"], // required for, and only valid with,
                                                  // ...WithFixedNight
  "schedule_mode":        "alwaysDaily",
  "routing_mode":         "simpleRouting" | "fullRouting",
  "auto_stop_addition":   "off" | "add" | "suggest"
}
```

Note `auto_stop_addition` is a **three-value enum** — `"add"` inserts
candidate stops automatically, `"suggest"` reports them without inserting.
Per-stop `stop_type` is gone: boarding/alighting is derived from the timetable.

### Response

```jsonc
{
  "route_builder_version": "0.9.15",
  "calc_version":          "0.9.11",     // two separate version tracks — always
  "route_fingerprint":     "sha256:…",
  "cache_hit":             false,        // served from the server-side compute cache
  "request":               { … },        // RESOLVED request: defaults applied,
                                         // scenario_id concrete. Keep this — it is
                                         // what publish takes as compute_request
  "suggested_stops":       [ … ],        // ONLY when auto_stop_addition="suggest"
  "summary":               { … },        // gallery KPI row for this result
  "route":                 { … },
  "evaluation": {
    "models": { "route_builder": {…}, "energy": {…}, "evaluation": {…}, "emissions": {…} },
    "input":  { "parameters": {…} },     // NOTE: no "route" key — see gotcha 7.1
    "views":  { … }
  }
}
```

### What to watch

- **`request` is the handle for everything else.** Scenario/composition
  switching = take `request`, change one field, POST again. Publishing = pass
  `request` as `compute_request`. There is no other state to track.
- **`cache_hit`** is telemetry, not correctness. A hit is a byte-identical
  replay of the same compute — the only field that differs.
- **`summary`** is new: the same KPI row shape the gallery returns, for the
  result you just computed. Useful for showing headline KPIs without a second
  call.
- **`models.emissions`** carries `factors` (per-mode `g_per_pax_km` + source)
  rather than `formulas` — the emissions model is a set of sourced constants,
  not calculation steps.

---

## 2. `POST /api/proposal/publish` — the only user write path

**Not built in the frontend.** Requires auth (guest floor is fine).

```jsonc
{
  "compute_request":       { … },   // the exact resolved `request` from /calc
  "name":                  "Berlin–Roma via Brenner",
  "mode":                  "new" | "overwrite",
  "proposal_id":           123,     // overwrite only; forbidden for "new"
  "based_on_proposal_id":  456      // optional, informational
}
```

Three rules that shape the publish dialog:

1. **The server never persists client-supplied results.** You send *inputs*;
   the server recomputes and stores what it computed. Don't try to post the
   `/calc` response body — it isn't accepted.
2. **Published proposals are always on the current base scenario.** A
   `compute_request` whose `scenario_id` isn't the current base is rejected
   **422 `scenario_not_base`**. If the user has been exploring a what-if, the
   publish flow must re-compute on base first. What-ifs are an analysis
   dimension, never a stored artifact.
3. **The acting user is never in the request body.** Identity comes from the
   JWT. Don't send `user_id`.

`mode: "overwrite"` needs ownership (403/404 otherwise) and replaces the stored
state wholesale — route, composition, evaluation, whatever changed. There is no
version history to browse; exactly one state exists per proposal at a time.

Response = the published proposal in the same shape as `GET /api/proposal/<id>`,
including the server-assigned `proposal_id`. Adopt that id as the loaded
proposal so the next save is an ordinary `overwrite`.

**Duplicates are allowed and never checked for.** "Same route with couchettes
*and* with seaters" = two `mode: "new"` publishes, deliberately two gallery
items.

---

## 3. `GET /api/proposal/<id>` — load

Returns **exactly the `/calc` response shape** plus proposal metadata (id,
owner, name, versions, timestamps). So one renderer handles both.

Two things to know:

- **It may be slow on first load.** If the proposal is outdated (version bump
  or base scenario moved), it refreshes inline before returning. Show a loading
  state.
- **The response is structurally identical to the original compute, not
  byte-identical.** The route is reconstructed from GTFS + sidecar tables and
  the parameters rebuilt from the scenario pin. Don't diff raw JSON to detect
  change; compare `route_fingerprint`.

There is no variants section and no staleness flag — the system keeps every
proposal current on its own, so there is nothing for the client to display or
act on.

---

## 4. `POST /api/proposals` — gallery + map

**Not built in the frontend.** Replaces the old flat `{total, proposals}`
envelope with a **sectioned** response. `GET /api/proposals` still exists as
the empty-filter, summaries-only convenience.

```jsonc
{
  "filter": {
    "sources":         ["proposal", "existing"],  // default ["proposal"]
    "proposal_ids":    [int],  "user_ids": [int],
    "countries":       ["DE","IT"],               // or {"values":[…],"mode":"any"|"all"}
    "stop_ids":        ["…"],                     // same two shapes
    "composition_ids": ["REF-BAL-9"],
    "name":            "brenner",                 // substring, case-insensitive
    "total_distance_km":       {"min": 800, "max": 1500},
    "margin_eur_per_train_km": {"min": 0},        // any numeric KPI column likewise
    "likes_count":             {"min": 1},
    "comments_count":          {"min": 1},
    "created_at":              {"min": "2026-01-01T00:00:00+00:00"},
    "trip_windows": [                             // timetable filter
      {"stop_id": "…berlin-hbf", "departure": {"from": "20:00", "to": "23:00"}},
      {"stop_id": "…roma-ti",    "arrival":   {"from": "07:00", "to": "09:30",
                                               "day_offset": 1}}
    ],
    "bbox": [w, s, e, n]
  },
  "sort":    [{"by": "<any filterable column>", "dir": "asc"|"desc"}],
  "limit":   int, "offset": int,
  "include": ["summaries", "map_lines", "map_stop_counts", "map_country_counts"]
}
```

**Filter rules**, so you can build the UI generically:

- every **numeric** column takes `{min, max}` (either bound optional);
  `created_at`/`updated_at` the same with ISO 8601 strings
- every **scalar categorical** column takes a value list — always OR
- `countries`/`stop_ids` are arrays: plain list = `mode: "any"` (overlap);
  `{"values": […], "mode": "all"}` = containment
- `name` is a case-insensitive substring
- everything filterable is also sortable, plus `route_fingerprint`
- **not filterable**: `scenario_id`, `route_builder_version`, `calc_version` —
  internal, and every row is always on the current base by construction

**`trip_windows`** matches when a **single trip** satisfies all entries — so
"depart Berlin 20:00–23:00 *and* arrive Roma 07:00–09:30 next day" means one
train doing both. Pass wall-clock times with an optional `day_offset`; the
backend handles the GTFS overnight convention.

### Response sections (`include` picks which run)

- **`summaries`** — paginated rows + windowed `total`. Each row carries
  `source`, `likes_count`, `comments_count`.
- **`map_lines`** — GeoJSON, one feature per **corridor** (stop pair,
  direction-collapsed), not per proposal. Carries `proposal_count` (drive line
  thickness off this), `proposal_ids`, `avg_margin_eur_per_train_km`. Filtered
  but **not paginated** — the map gets the whole filtered set.
- **`map_stop_counts`** — `[{stop_id, lat, lon, n}]`.
- **`map_country_counts`** — GeoJSON per country, `properties: {country, n}`
  plus the country's own border geometry, so no second lookup is needed for a
  choropleth. `geometry: null` for unmatched codes like `"UNK"`.

### Two row shapes

`sources` can include existing (ONTD) night-train routes. **These rows are not
the same shape as proposals** and the UI must handle both:

| | `source: "proposal"` | `source: "existing"` |
|---|---|---|
| Financial KPIs | ✅ | **`null`** |
| Demand / CO2-savings KPIs | ✅ (placeholder-flagged) | **`null`** |
| `likes_count` / `comments_count` | ✅ | **`null`** |
| `user_id`, engagement | ✅ | **absent** |
| Descriptive (distance, time, speed, stops, countries) | ✅ | ✅ |
| `composition_id` | ✅ | sometimes (curated only) |
| `co2_g_per_pax_km` | ✅ | ✅ (per-route, from ONTD) |
| `ontd_url` | — | ✅ deep link to the source record |

This is deliberate policy, not missing data: existing routes are **never**
rated financially. They are also **excluded from compare** (and from the parked
analyze endpoint) — gallery and map context only.

---

## 5. Engagement — `GET …/engagements` + five singular writes

**Not built in the frontend.** Biggest path change in the refactor: five
endpoints moved, two disappeared (see §0 table).

```
GET    /api/proposal/<id>/engagements     likes + comments + timeline
POST   /api/proposal/<id>/like            auth, idempotent
DELETE /api/proposal/<id>/like            auth, idempotent
POST   /api/proposal/<id>/comment         auth
PATCH  /api/proposal/<id>/comment/<cid>   auth, author-only
DELETE /api/proposal/<id>/comment/<cid>   auth, author-only
```

One read returns three sections: `likes` (`{count, liked_by_me}`), `comments`
(`{count, items}`, oldest first), and `timeline`.

### Timeline semantics — read this before building the feed

The timeline is a **projection of current state**, not an audit trail. Concretely:

- unliking is a hard delete — a withdrawn like leaves **no trace**
- a deleted comment vanishes everywhere: thread, count, and timeline
- an edited comment **moves** to its edit time, flagged `detail.edited: true`

So the order a user sees can change retroactively. Don't cache the timeline as
if it were append-only, and don't assume an event you rendered will still be
there next fetch.

Each event carries `event`, `at`, `proposal_version` (the state counter *after*
it), `actor`, and an event-specific `detail`.

**`actor: null` means the system acted** — a version bump or base-scenario move
(`recalculated`), as opposed to a user `overwritten`. Render these differently.
A deleted *account* is not a system event: it comes through as
`{"user_id": null, "user_name": "[deleted]"}`.

`is_deleted` **is gone from the comment shape** — it was always `false` on the
wire (a deleted comment is now returned by nothing). It survives internally
only so `comment_id` stays stable and a second `PATCH`/`DELETE` answers 404
rather than resurrecting the row.

No pagination — deliberately. Revisit if a proposal ever accumulates thousands
of likes.

### Rate limiting

**`429` is a possible response on every engagement write**, limited per
authenticated user. Handle it in the UI — the current limits live in
`backend/api/config.py`.

### Counts on gallery rows

`likes_count` and `comments_count` come back on every `POST /api/proposals`
summary row, so a list view never calls this endpoint per row. Bodies and the
timeline stay here.

---

## 6. `POST /api/proposals/compare`

**Not built in the frontend.** Two sides, each anchored on one proposal, with
optional overrides:

```jsonc
{
  "sides": [
    {"proposal_id": 123, "scenario_id": 4},
    {"proposal_id": 456, "scenario_id": 4}
  ]
}
```

Overridable: `scenario_id`, `composition_id`. Same anchor both sides = variant
compare on one route; different anchors = cross-proposal compare.

**A side with any override is computed live and marked `published: false`** —
even if the override value equals the stored one (deterministic, no
equality special-casing). That compute can be slow on a cache miss: **the UI
needs a per-side loading state.**

Response per side: the full compute-response shape, **plus a `summary` block on
both side kinds** — so you can diff the same headline KPIs the gallery shows,
regardless of side kind. Plus a `diff` section, **side B minus side A**
throughout:

- per-KPI `{a, b, abs, rel}` over the gallery KPI columns
- a generic structured diff over the shared `views` trees — every cost
  category, view, normalisation and class key, so you can show *which* component
  moved. `rel` is `null` on a zero base.
- keys present on only one side (different countries, ODs, stops, coach
  classes) are collected as dotted paths under **`views_unmatched`** rather than
  half-diffed — render these as "not comparable", not as zero.
- route context via the two fingerprints (identical route or not).

---

## 7. Cross-cutting renames and shape changes

These affect code you may already have written. Audit `frontend/src/types/api.ts`
end to end.

| Change | Where |
|---|---|
| `comp_id` → **`composition_id`** | `/api/params/compositions`, evaluation `input.parameters.compositions[]`, everywhere else |
| `per_trip_km` → **`per_train_km`** | evaluation normalisation key |
| new view key **`per_trip_pair_per_section`** | evaluation `views` |
| `general_parameters` per trip | route `trip_pairs[].outbound/return_trip` — `trip_km`, `route_duration_min`, `average_speed_kmh`, `timetable_warnings` |
| `fix_overhead_eur` formula changed | evaluation values shift; shape unchanged |
| `auto_stop_addition` is a 3-value enum | `/calc` request |
| `suggested_stops` at top level | `/calc` response, suggest mode only |
| new: `cache_hit`, `summary`, `route_fingerprint` | `/calc` response |
| new: `source`, `demand_kpis_placeholder`, `comments_count` | gallery rows |
| `is_deleted` removed | comment shape |
| emissions: per-mode reference factors | `/calc` `evaluation.models.emissions.factors`, gallery rows, compare deltas |

### 7.1 The route appears exactly once

`evaluation.input` has **no `route` key** — the route is a top-level sibling of
`evaluation`. The old calc response carried a copy only because it was a
standalone endpoint.

If you have code that scopes parameters via `input.route` (as
`costFactorRates.ts` does), re-attach the top-level route when assembling the
object you pass down. That's what `ProposalViewport.applyPlan()` now does.

### 7.2 `demand_kpis_placeholder`

Demand, modal-shift and CO2-savings KPIs are **deterministic fakes** until the
demand model lands — stable across recomputes and plausible in magnitude, but
not real. Every response carrying them also carries
`demand_kpis_placeholder: true`. **Badge these values in the UI.** When the real
model lands the flag flips with no shape change.

Financial KPIs (cost/revenue/margin per train-km, subsidy per year) are real
now.

### 7.3 Subsidy definition

`subsidy_eur_per_year` = `max(0, -net_eur)` — the **gap to the target margin**,
not to break-even, since `net_eur` is already after the EBIT margin target. Label
it accordingly.

---

## 8. Gotchas worth internalising

1. **No server-side drafts.** Unsaved exploration dies with the session.
   Client-side draft caching and warn-on-navigate are frontend concerns and are
   not built.
2. **No delete API.** Proposals cannot be removed through the UI at all;
   cleanup is manual DB work.
3. **Ephemeral vs published is a hard line.** `/calc` writes nothing. Only
   publish creates a proposal.
4. **Two version tracks.** `route_builder_version` and `calc_version` move
   independently. Don't collapse them into one "version" field.
5. **Proposals silently change under you.** A version bump or base-scenario move
   re-computes every stored proposal server-side. A proposal loaded yesterday can
   legitimately return different KPIs today, with no flag saying so — by design.
6. **Neutral vs prefixed IDs.** `/calc` returns structural IDs (`R1`, `T1`, …);
   published proposals carry `P{id}_V{n}_…`. Don't persist or compare raw IDs
   across the boundary — use `route_fingerprint`.
7. **Guest auth exists.** Engagement writes and publish need a token, but the
   guest floor is enough — no registration wall for basic participation.

---

## 9. Where to look next

| You need | Read |
|---|---|
| Exact bodies, error codes, examples | `backend/api/README.md` |
| Why a shape is the way it is; the 28 locked decisions | `backend/adapters/proposal/README.md` |
| What each evaluation view/normalisation means | `backend/models/evaluation/README.md` |
| Existing-network (ONTD) row semantics | `backend/db/ontd/README.md` |
| Designed but unbuilt (analyze endpoint) | `docs/PARKED_WORK.md` |

Questions on anything above: ask before building around a guess — several of
these shapes encode policy decisions (existing-route KPIs, publish integrity,
timeline semantics) that aren't obvious from the JSON alone.
