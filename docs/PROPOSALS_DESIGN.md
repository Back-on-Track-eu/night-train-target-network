# Proposals — Storage, Gallery & Compare Design

Status: agreed design, pre-implementation (2026-08-01)
Scope: compute/publish APIs, `proposals` schema, gallery/map/compare, ONTD integration
Location in repo: `docs/PROPOSALS_DESIGN.md`

---

## 1. Purpose

Design of the proposal lifecycle and storage for the public tool, supporting:

- a public gallery view with SQL-backed filtering, sorting, pagination —
  every stored proposal is a gallery item, **always evaluated on the
  current base scenario**
- map views (route lines, stop/country heat aggregates) driven by the same filters
- a compare view across scenarios/compositions of one proposal or across
  different proposals
- the KPI set required by the political target audience (cost/revenue/margin
  per train-km, subsidy need, demand, modal shift, CO2 — the
  demand-dependent ones faked until the demand model exists)
- inclusion of existing night train routes (ONTD) in gallery and map,
  clearly marked, without financial KPIs
- multi-user public operation

Three architecture decisions supersede the earlier persist-on-calc concept
and shape everything below:

1. **Merged compute API** (2026-07-31). Route planning and evaluation are
   one endpoint (`POST /api/proposal/calc`), one pipeline, one response.
   There are no half-states: a result always contains route *and*
   evaluation.
2. **Ephemeral compute, explicit publish** (2026-07-31). Computing writes
   nothing to the database. Proposals come into existence only through an
   explicit `POST /api/proposal/publish`. The database contains deliberate
   artifacts, not exploration states.
3. **One stored state per route artifact** (2026-08-01). A proposal is a
   route with a composition, always evaluated on the current base scenario.
   There are no stored scenario/composition variants ("family members") —
   variant exploration is ephemeral compute, accelerated by the compute
   cache (§2.3). This dissolves the earlier family/variant-coordinate/
   default-member machinery entirely.

---

## 2. Compute / publish architecture

### 2.1 `POST /api/proposal/calc` — ephemeral compute

One stateless request → route + evaluation, no side effects.

**Request** — the former plan request minus all persistence identity
(`proposal_id`/`proposal_version` are publish concerns; drafts do not exist
server-side). Verified against the current endpoints: `/api/evaluation/calc`
carried **no** evaluation-only user inputs beyond the route and an optional
`scenario_id` override, so the merged request is exactly this. Proposal
*metadata* (name, provenance) is **not** part of the compute request — it
belongs to publish (§2.2).

```jsonc
{
  // WHAT to compute
  "stops":              ["stop_id", "..."],        // required, min 2, plain IDs
  "composition_id":     "REF-BAL-9",               // required
  "scenario_id":        4,                         // optional; omitted = current base.
                                                   // Any scenario is computable —
                                                   // what-ifs live here and in compare;
                                                   // only PUBLISH is base-restricted (§2.2)

  // HOW to compute (all optional, defaults + validation rules as today)
  "timetable_mode":       "simpleAutomatic" | "simpleAutomaticWithFixedNight",
  "fixed_night_interval": ["stop_id", "stop_id"],  // required for, and only allowed
                                                   // with, ...WithFixedNight
  "schedule_mode":        "alwaysDaily",
  "routing_mode":         "simpleRouting" | "fullRouting",
  "auto_stop_addition":   "off" | "add" | "suggest"
}
```

**Response** — the merged plan + calc result:

```jsonc
{
  "route_builder_version": "0.9.13",
  "calc_version":          "0.9.10",               // both version tracks stay separate
  "route_fingerprint":     "sha256:…",             // §3.1, informational + compare context

  "request": { … },                                // the RESOLVED request: defaults
                                                   // applied, scenario_id concrete.
                                                   // Canonical form — what publish takes
                                                   // as compute_request, what the cache
                                                   // (§2.3) hashes, what §5.3 stores

  "suggested_stops": [ … ],                        // ONLY when auto_stop_addition="suggest"

  "route": { … },                                  // today's route_to_dict shape,
                                                   // neutral structural IDs

  "evaluation": {
    "models": { "route_builder": {…}, "energy": {…}, "evaluation": {…} },
    "input":  { "parameters": { "track_infrastructures": {…},
                                "stop_infrastructures":  {…},
                                "compositions":          {…} } },
    "views":  { "route": {…}, "per_trip_pair": {…},
                "per_trip_pair_per_country": {…}, "per_trip_pair_per_od": {…},
                "per_trip_pair_per_section": {…}, "per_trip_per_stop": {…} }
  }
}
```

**Provenance placement** — each section documents what *it* used, at two
deliberate depths:

- under `route`: resolved `scenario_id`, per-trip-pair `composition`, and
  per-country `track_infrastructure` — the **physics-relevant subsets**
  (all `*_eur*` cost fields deliberately excluded; the old "no monetary
  values in the plan response" principle becomes "no monetary values under
  `route`"). Informational only — never read back, rebuilt from DB via the
  scenario pin.
- under `evaluation`: `models` (static model documentation — versions,
  descriptions, formulas) and `input.parameters` — the **full sourced
  parameter sets** via `params_serialize.py`, every field with
  description, source, and `is_default`. Costing provenance in full depth.

Tracks and composition therefore appear twice at different depths — kept
deliberately, each section stays self-describing. There is **no route copy
under `evaluation.input`** anywhere (the route is a sibling key; the old
calc response only carried one because it was a standalone endpoint):
stored and computed responses share one shape with the route appearing
exactly once.

Further notes:

- **IDs**: compute responses carry neutral structural IDs (`R1`, `T1`, …,
  no proposal prefix). Prefixed IDs (`P{id}_V{n}_…`) exist only on
  published proposals; publish assigns them. The fingerprint
  canonicalization strips prefixes anyway (§3.1), so fingerprints agree
  between ephemeral and published forms.
- **No persistence decisions.** No actions, no lookups. Request in, result
  out, forget.

The frontend holds the current result in memory; unsaved exploration dies
with the session. Mitigation (frontend concern, coordination item WP12):
draft caching in the client, warn-on-navigate for unsaved changes.

### 2.2 `POST /api/proposal/publish` — the only user write path

```jsonc
{
  "compute_request": { … },            // the exact resolved request of §2.1
  "name": "Berlin–Roma via Brenner",
  "mode": "new" | "overwrite",
  "proposal_id": 123,                  // overwrite only: the owned proposal to replace.
                                       // Forbidden for "new" — IDs are server-assigned
                                       // (SERIAL); the response returns the new id.
  "based_on_proposal_id": 456          // optional provenance, informational only
}
```

**Integrity rule: the server never persists client-supplied results.** The
publish request carries *inputs*, not outputs; the server computes the
result itself and persists what it computed — freshly or from the compute
cache (§2.3), which only ever holds server-computed results. For a public,
politically consumed gallery this is non-negotiable: no path may exist by
which manipulated KPIs enter the database.

**Base-scenario rule: published proposals are always evaluated on the
current base scenario.** A `compute_request` whose `scenario_id` is not the
current base is rejected (422, `scenario_not_base`) — what-if scenarios are
an *analysis* dimension (compute, compare), never an *artifact* dimension.
This is what keeps the gallery's promise ("KPIs always on the current
parameter reality") structural rather than conventional. The frontend's
publish flow re-computes on base first if the user explored under a
what-if.

**The publish handler** (e.g. `api/helpers/publish_dispatch.py`) — all
persisting case distinctions in one small component:

| Case | Handling |
|---|---|
| `mode: "new"` | insert under the calling user (guest or registered); `proposal_id` must be absent. Duplicates of existing routes — own or foreign — are allowed and never checked for (§3.2). `update_log` 'published' (+ the informational `branched_from`/`branched_to` pair when `based_on_proposal_id` is given: building on a foreign proposal is loading it, exploring ephemerally, publishing as new) |
| `mode: "overwrite"` | replace the stored state of the *owned* proposal — route, composition, evaluation, whatever changed: state counter +1, previous state hard-deleted in the same transaction (GTFS/sidecar rows by ID prefix, summary row upserted), fingerprint/composition columns updated, `update_log` 'overwritten' |

That is the whole table: with one stored state per artifact there are no
sibling discards, no family lookups, no fingerprint-dependent branches.
Ownership is checked for overwrite (403/404 for foreign or unknown ids).
**The acting user is never part of the request body**: identity comes
exclusively from the auth layer (JWT → `user_id` via the existing
middleware, guests included) — a client-supplied `user_id` would be an
impersonation vector, the same class of input the integrity rule above
bans.

Response: the published proposal in full (as `GET /api/proposal/<id>`
returns it), including the server-assigned `proposal_id` and prefixed row
IDs — the frontend adopts this id as its loaded proposal, so a follow-up
save is an ordinary `overwrite` against it.

### 2.3 Compute cache

A server-side, TTL-bounded cache (default 3 h, configurable) over compute
results, so that "playing around" — toggling scenarios, compositions, and
settings back and forth, in the editor **and** in compare — hits routing
only once per distinct input state. With stored variants gone (§1,
decision 3), this cache is the designated home of every non-base,
non-published result. Strictly a performance layer: invisible to the data
model, never a source of truth, safe to flush at any time.

**Fed by every compute path**: direct `POST /api/proposal/calc` calls and
the ephemeral computes inside `POST /api/proposals/compare` (§7.3) go
through the same compute function and the same cache — comparing warms the
editor and vice versa.

**Cache identity of a computed result =
`(route_fingerprint, scenario_id, composition_id)`.** The fingerprint alone
is not sufficient: the same physical route under two scenarios (identical
infrastructure in both) or two same-speed compositions hashes identically
but evaluates differently, so scenario and composition stay in the triple.

Because the fingerprint is only known **after** routing, the cache is two
small maps:

1. **Pointer map**: `request_hash → (fingerprint, scenario_id,
   composition_id)` — written the first time a distinct resolved request
   is computed; tiny rows. Request-*specific* response parts (the resolved
   `request` echo, `suggested_stops` in suggest mode) belong on this side
   / are assembled at response time — the shared result core must never
   carry another request's echo, since publish reads it.
2. **Result map**: `(fingerprint, scenario_id, composition_id) → route +
   evaluation core` — the payload, stored **once per distinct result** no
   matter how many requests converge on it (settings that do not change
   the output, independent users planning the same route).

Lookup: hash the resolved request → pointer hit → result fetch, zero
compute. Pointer miss → compute → write both. Compare sides (§7.3) and
publish (§2.2) resolve through the same two maps.

**No version constants in the key.** With a TTL of hours, guarding keys
against events that happen every few weeks is backwards: instead the cache
is **flushed on every `ROUTE_BUILDER_VERSION`/`CALC_VERSION` bump** — an
explicit first step of the version-bump procedure, natural home in the
refresh script (§4.2). Base-scenario moves need no flush at all: the new
base has a new `scenario_id`, so old entries never match again and age out
via TTL.

The compute response carries a `cache_hit: bool` meta field — directly
assertable in tests and useful frontend telemetry.

Key correctness: scenario rows are immutable snapshots (edits create new
`scenario_id`s), so `scenario_id` is a sound key component. Assumption to
verify in implementation: all parameter tables feeding evaluation are
reachable through the scenario pin — anything that is not must join the
key. Optional future extension: a route-stage cache keyed by the
routing-relevant request subset, relevant only if evaluation-only inputs
ever exist.

**Storage**: shared across gunicorn workers, so not per-process memory. To
avoid new infrastructure, two `UNLOGGED` PostgreSQL tables (pointer,
result; created_at + TTL cleanup on write) are sufficient; a memory store
(e.g. Redis) stays a drop-in upgrade if response sizes or traffic ever
demand it.

**Implementation (agreed 2026-08-03; tables land in WP1, logic in WP13)**

```sql
CREATE UNLOGGED TABLE proposals.compute_cache_pointer (
    request_hash       TEXT PRIMARY KEY,
    route_fingerprint  TEXT NOT NULL,
    scenario_id        INTEGER NOT NULL,
    composition_id     TEXT NOT NULL,
    resolved_request   JSON NOT NULL,   -- request echo, request-specific
    suggested_stops    JSON,            -- suggest-mode only, request-specific
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNLOGGED TABLE proposals.compute_cache_result (
    route_fingerprint  TEXT NOT NULL,
    scenario_id        INTEGER NOT NULL,
    composition_id     TEXT NOT NULL,
    payload            JSON NOT NULL,   -- route + evaluation core, shared
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (route_fingerprint, scenario_id, composition_id)
);

CREATE INDEX idx_cache_pointer_created ON proposals.compute_cache_pointer (created_at);
CREATE INDEX idx_cache_result_created  ON proposals.compute_cache_result (created_at);
```

No FKs on either table — both key off value tuples
(`route_fingerprint`/`scenario_id`/`composition_id`, `request_hash`), never
off a `proposals.proposals` row, so the usual logged/unlogged FK
restriction doesn't come up. The `created_at` indexes exist for the
cleanup sweep below, not for lookups.

**Read path.** Canonicalize the resolved compute request (sorted keys,
stable number formatting) → `request_hash`. Look up
`compute_cache_pointer`:
- **miss** → run the compute pipeline, which yields `(fingerprint,
  scenario_id, composition_id, payload)`
- **hit** → fetch `compute_cache_result` by the pointer row's
  `(route_fingerprint, scenario_id, composition_id)`; assemble the
  response from that shared `payload` plus the pointer row's
  request-specific `resolved_request`/`suggested_stops`; set
  `cache_hit: true`

**Write path**, both inserts after a successful compute, result before
pointer:

```sql
INSERT INTO compute_cache_result (route_fingerprint, scenario_id, composition_id, payload)
VALUES (...)
ON CONFLICT (route_fingerprint, scenario_id, composition_id) DO NOTHING;

INSERT INTO compute_cache_pointer (request_hash, route_fingerprint, scenario_id, composition_id, resolved_request, suggested_stops)
VALUES (...)
ON CONFLICT (request_hash) DO NOTHING;
```

`DO NOTHING` on the result insert is what makes "stored once per distinct
result" hold under concurrency: two requests converging on the same route
at nearly the same time just have the second write no-op rather than
duplicate or error. Result rows are write-once — a cache **hit** never
touches `created_at` again (no LRU-style refresh-on-read); a hot result
that ages past the TTL is simply recomputed and re-written cheaply by the
next miss. This keeps the write path free of any read-then-update
branching.

**TTL cleanup — opportunistic, not a scheduled job.** Attached to the
write path, run probabilistically on **1% of writes** (not every write, to
avoid paying a `DELETE` scan per request), in the same transaction as the
write:

```sql
DELETE FROM compute_cache_pointer WHERE created_at < now() - INTERVAL '3 hours';
DELETE FROM compute_cache_result  WHERE created_at < now() - INTERVAL '3 hours';
```

TTL value (default 3 h) and the 1% sampling rate are both config constants,
overridable via env for tests. No pg_cron, no external scheduler — the
table self-bounds in size purely from ordinary traffic.

**Flush on version bump.** No version constants in the cache key (see
above), so a `ROUTE_BUILDER_VERSION`/`CALC_VERSION` bump just
`TRUNCATE`s both tables as the first step of `refresh_proposals.py`
(§4.2, WP8) — a full flush, not a TTL-aware partial one.

### 2.4 What this removes (vs. the persist-on-calc design)

- the first-level dispatch handler and its decision matrix
- families, variant coordinates, default-member resolution, the variants
  matrix, `?resolve=default`, sibling discards, family copies
- `loaded` / `unchanged` / `already_exists` response actions
- half-states: every stored proposal has route **and** evaluation —
  `calc_version` and `evaluation_output` are NOT NULL, evaluation always
  belongs to its route by construction
- guest exploration hygiene (ephemeral compute leaves nothing behind)

---

## 3. Identity model

### 3.1 Route fingerprint

A route's uniqueness (for fingerprinting) is defined by its **resolved
outputs**, not its request settings:

> stop lists, route geometries, and trip schedules (exact departure and
> arrival times) for each trip in the proposal

`route_fingerprint` = SHA-256 over a canonical extract of the computed
route: per trip pair, per trip (outbound and return), the ordered list of
`(stop_id, arrival_time_min, departure_time_min)` plus the trip's geometry
coordinates.

Canonicalization rules:

- extract from the **built route** (post `auto_stop_addition`), never the request
- strip all ID prefixes before hashing (ephemeral results carry neutral
  IDs, published ones `P{id}_V{n}_…` — identical routes must hash
  identically in both forms)
- round geometry coordinates to 5 decimals (~1 m) to absorb float noise
- preserve list order (trip pair order, stop order, coordinate order);
  serialize with a fixed canonical JSON dump before hashing
- the fingerprint of a reconstructed route (§5.1) must equal the
  fingerprint of the original compute result — enforced by round-trip tests

No **persistence** logic depends on the fingerprint: no lookup, index,
uniqueness rule, or handler branch. It is computed by the projection,
stored as a column, returned by compute, and used by compare (§7.3) to
state route context ("identical route, different composition/scenario").
Its productive uses are elsewhere: as the core of the compute-cache
result identity `(fingerprint, scenario_id, composition_id)` (§2.3 —
deduplicating results across requests that converge on the identical
route) and as the natural clustering key for route-level analytics ("how
often was this exact route proposed", corridor duplication across users).

### 3.2 Proposal identity

- **Proposal identity = `proposal_id`.** Nothing else. The editor's load
  semantics guarantee it: a user loads (or computes and publishes) a
  proposal and all editing targets that one proposal until a different one
  is loaded or created; overwrite-vs-new is the user's explicit choice at
  publish time.
- **A proposal is a route with a composition, evaluated on the current base
  scenario.** Scenario is not an identity dimension: the stored
  `scenario_id` records *which base snapshot* the stored evaluation ran
  under (provenance + staleness signal, system-managed via refresh §4.2),
  never a user choice. Composition is simply the proposal's current
  composition — an overwrite-publish may change it like any other input.
- **No deduplication.** The same route may exist more than once (same or
  different users, same or different composition): publish never searches
  for an existing match. Wanting "this route with couchettes" *and* "this
  route with seaters" as two gallery items = two proposals via
  `mode: "new"` — deliberate, visible duplication.
- **Variant exploration is ephemeral.** Scenario/composition switching in
  the editor and in compare is pure compute (cache-backed, §2.3); nothing
  of it is stored unless the user publishes — and publishing pins to base
  (§2.2), so a what-if result can inform an artifact but never *be* one.

---

## 4. Stored-state model — update log, version refresh

`proposal_version` is an internal **state counter** on published proposals:
bumped by every overwrite-publish and every system refresh, embedded in all
row-ID prefixes (`P{id}_V{n}_…`), and stamped by likes/comments so the
timeline can show what state an engagement referred to. It is not a
versioning concept — exactly one state per proposal exists at any time; the
previous state is hard-deleted in the overwrite transaction. `SELECT … FOR
UPDATE` on the single proposal row serializes concurrent writes (two
overwrite-publishes, or a publish racing the refresh batch).

### 4.1 `proposals.update_log`

States are pruned while likes/comments stamp state numbers — an append-only
event log preserves the timeline ("comment on state 3, route overwritten
afterwards, then recalculated with a new calc version"):

```sql
CREATE TABLE proposals.update_log (
    log_id            SERIAL PRIMARY KEY,
    proposal_id       INTEGER NOT NULL,          -- soft ref, same convention as likes/comments
    proposal_version  INTEGER NOT NULL,          -- state counter AFTER the event
    user_id           INTEGER REFERENCES admin.users(user_id) ON DELETE SET NULL,
                                                 -- NULL for system events (refresh)
    event             TEXT NOT NULL,             -- 'published' | 'overwritten'
                                                 -- | 'recalculated'
                                                 -- | 'branched_from' | 'branched_to'
    detail            JSONB,                     -- branch: {"source_proposal_id":…}
                                                 -- recalculated: {"trigger":"calc_version"
                                                 --   |"route_builder_version"
                                                 --   |"base_scenario_moved","from":…,"to":…}
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_update_log_proposal ON proposals.update_log (proposal_id, created_at);
```

Rows are written inside the same transaction as the publish. The
`branched_*` pair is written only when `based_on_proposal_id` was given —
**purely informational timeline content** ("user X built on this"); nothing
in the system navigates from a proposal to its source. The frontend
timeline is the chronological merge of `update_log` + `comments` + `likes`
(§7.5).

### 4.2 Version refresh — proposals always at the newest calculation state

Users never republish because of a version or parameter change; the system
keeps the stored artifacts current. Triggers:

- `ROUTE_BUILDER_VERSION` bump → recompute (route + evaluation) all proposals
- `CALC_VERSION` bump → recompute evaluations
- **base scenario moved** (parameter data change → new scenario row, old
  one drops `is_current_base`; scenario rows themselves are never
  rewritten) → recompute **all** proposals under the new base and update
  their stored `scenario_id`. This deliberately revises the earlier
  "scenario pins are never rewritten" rule — that rule protected pinned
  variant artifacts, which no longer exist; under the artifact contract
  "always evaluated on current base" (§2.2), moving the pin *is* the
  feature. `update_log` 'recalculated' with trigger `base_scenario_moved`.

Mechanisms, in order of preference:

1. **Batch script** (`backend/scripts/refresh_proposals.py`): on a
   version bump, **first flushes the compute cache** (§2.3), then scans for
   proposals with outdated versions or a non-current-base `scenario_id`,
   re-runs the compute pipeline, overwrites in place (owner kept,
   `update_log` 'recalculated' with `user_id NULL`). Run after every
   version bump / base scenario move; idempotent, resumable, dry-run mode,
   **configurable concurrency limit** (routing capacity; first beneficiary
   of a future routing cluster — parked topic).
2. **On-load fallback**: `GET /api/proposal/<id>` detects an outdated
   proposal and refreshes before returning — correctness for anything the
   batch hasn't reached, at the cost of one slow load.

Between a base move and a proposal's refresh, gallery and load flag the row
`scenario_outdated: true` (derived by joining `scenario.scenarios`, not
stored). A refresh may change the fingerprint (new routing graph, new
infrastructure) — it simply updates the column.

---

## 5. Storage layout — route stored once

### 5.1 Principle: no double data state

The route is stored **once**, as GTFS + sidecar tables; the evaluation
output is stored as JSON reduced to **`models` + `views`** — neither a
route copy nor `input.parameters`. The parameters live in the
scenario-versioned tables and scenario rows are immutable snapshots, so the
exact sourced parameter set is rebuilt on read via the proposal's
`scenario_id` pin (same `params_serialize.py` path as at compute time);
storing it per proposal would duplicate the params tables into every row —
double data state. `models` stays stored: it is tiny and must remain
faithful to the calc version that actually ran (regenerating it from
running code could mismatch in the window between a version bump and the
refresh batch). Rationale for the route side (verified against
`route_serialize.py`):

- **rebuilt from DB anyway**: `composition` and `track_infrastructure`
  sections — `route_from_dict()` never reads them back, it reloads both via
  `scenario_id`/`composition_id`; purely informational in the JSON
- **derived**: `general_parameters` (trip_km, duration, avg speed) —
  recomputable from segments
- **genuinely irreducible route data**: per-segment physics (distance,
  driving/dynamics/buffer/slack times, energy, country distance/time
  shares, per-segment geometry), OD pairs (places_sold, avg_price,
  class_main), parkings, shuntings, timetable warnings, seasonal schedule,
  per-stop classification (`stop_type` — not losslessly encoded in GTFS
  pickup/drop_off: "night" and "both" both map to (0,0)), and the compute
  request
- **irreducible evaluation data**: the computed `models` + `views`

Read path: `route_dict_from_gtfs()` (new, in `api/helpers/`, the read-side
counterpart of the GTFS insert) rebuilds a route dict that deep-equals the
original compute result and hashes to the same fingerprint;
`input.parameters` is rebuilt alongside it via the scenario pin. Both are
enforced by round-trip tests. The former verbatim-byte guarantee is
replaced by this **deterministic reconstruction** guarantee. The
JSON-not-JSONB rationale continues to apply to the evaluation output column
(key order must survive).

Accepted coupling: the sidecar schema evolves together with the route dict
/ `ROUTE_BUILDER_VERSION`. The version-refresh mechanism (§4.2) mitigates
this — after a builder bump, all proposals are re-persisted under the new
structure, so reconstruction never needs to support old shapes for long.

### 5.2 GTFS + sidecar tables

Existing GTFS tables unchanged in role (`services`, `calendar`,
`calendar_dates`, `routes`, `trips`, `stop_times`, `shapes`). Changes and
additions:

- `stop_times.stop_type TEXT` — lossless classification
  (boarding/alighting/night/both) as a GTFS extension column; pickup/
  drop_off stay derived for export compatibility
- `shapes` stores **per-segment** geometries (referenced from
  `segments.shape_id`); the per-trip concatenated shape is produced on GTFS
  export instead of stored (removes another duplication)
- `proposals.segments` — trip_id, segment_sequence, from/to stop_id,
  shape_id, distance_m, driving/dynamics/buffer/slack_time_min, energy_kwh,
  country_distance_shares JSONB, country_time_shares JSONB
- `proposals.od_pairs` — trip-pair-scoped demand inputs: origin/destination
  stop_id, class_main, trip_id, places_sold, avg_price
- `proposals.parkings`, `proposals.shuntings` — stop_id, stop_name,
  country_code, trip_id(s)
- `proposals.timetable_warnings` — trip_id, code, interval, speeds, ratio
- `proposals.seasonal_schedules` — route_id, season, frequency (calendar
  alone only covers the daily case)

### 5.3 `proposals.proposals` (slimmed container)

```sql
CREATE TABLE proposals.proposals (
    proposal_id            SERIAL PRIMARY KEY,      -- one row per proposal, always current
    proposal_version       INTEGER NOT NULL DEFAULT 1,  -- internal state counter (§4)
    user_id                INTEGER REFERENCES admin.users(user_id) ON DELETE SET NULL,
    name                   TEXT NOT NULL,           -- see WP5 implementation note below
    route_fingerprint      TEXT NOT NULL,           -- informational (§3.1)
    composition_id         TEXT NOT NULL,
    scenario_id            INTEGER NOT NULL,        -- the base snapshot the stored
                                                    -- evaluation ran under; system-managed
                                                    -- via refresh (§4.2). Currentness
                                                    -- derived by joining scenario.scenarios.
    route_builder_version  TEXT NOT NULL,
    calc_version           TEXT NOT NULL,           -- always evaluated (§2.4)
    compute_request        JSON NOT NULL,           -- resolved compute request, verbatim
    evaluation_output      JSON NOT NULL,           -- models + views only (§5.1)
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**Deviation from the original locked shape (decided during WP5
implementation):** `name` was added to the container. The design as
originally written omitted it — only `proposal_summaries` (§5.4) carried
`name`, on the theory that identity/metadata belonged with the other
container columns but display fields belonged with the projection. In
practice that made `name` the one piece of proposal identity a load
(`GET /api/proposal/<id>`) couldn't return without joining the
"derived, not a source of truth, rebuildable at any time" summary table
— i.e. the container would depend on the projection for its own identity
data, backwards from §5.4's own stated relationship between the two
tables. `name` is genuinely proposal metadata (what the user called it),
not a derived metric, so it stays on the container; `proposal_summaries.
name` remains a denormalized copy for gallery listing, kept in sync by
`publish()`'s single-transaction write, same as every other identity
column duplicated across the two tables (`route_fingerprint`,
`composition_id`, `scenario_id`, version fields).

No family/variant indexes — nothing looks proposals up by fingerprint or
coordinate. Proposal identity is the `proposal_id` alone.

Dropped vs. the current implementation: `is_current` + partial unique index
(one row per proposal), `change_log` (superseded by `update_log`),
`route_body` (route lives in GTFS + sidecars), the route copy and
`input.parameters` inside the evaluation JSON (both rebuilt on read, §5.1),
and nullable `calc_version`/evaluation (no half-states).

### 5.4 `proposals.proposal_summaries` (derived projection)

One row per proposal. **Not** a source of truth: a pure projection written
in the same transaction as every publish/refresh, rebuildable at any time
by a backfill script. Explicitly not the pre-2026-07-08 wide evaluation
table returning — that one *was* the storage; this one is an index/cache
over it.

```sql
CREATE TABLE proposals.proposal_summaries (
    proposal_id             INTEGER PRIMARY KEY,
    proposal_version        INTEGER NOT NULL,
    user_id                 INTEGER,
    route_fingerprint       TEXT NOT NULL,           -- informational (§3.1)
    composition_id          TEXT NOT NULL,
    scenario_id             INTEGER NOT NULL,
    name                    TEXT NOT NULL,
    route_builder_version   TEXT NOT NULL,
    calc_version            TEXT NOT NULL,

    -- route metrics
    total_distance_km       NUMERIC(8,1) NOT NULL,
    total_time_h            NUMERIC(6,2) NOT NULL,
    avg_speed_kmh           NUMERIC(5,1) NOT NULL,
    n_stops                 SMALLINT NOT NULL,
    countries               TEXT[] NOT NULL,
    stop_ids                TEXT[] NOT NULL,
    geom_simplified         geometry(MultiLineString, 4326),

    -- financial KPIs (always present — every proposal is evaluated)
    cost_eur_per_train_km       NUMERIC(10,2) NOT NULL,
    revenue_eur_per_train_km    NUMERIC(10,2) NOT NULL,
    margin_eur_per_train_km     NUMERIC(10,2) NOT NULL,
    subsidy_eur_per_year        NUMERIC(14,2) NOT NULL,  -- max(0, -net_eur): gap to target margin

    -- demand KPIs (placeholder-faked until the demand model exists — §8)
    demand_trips_per_year       NUMERIC(12,0),
    demand_trip_km_per_year     NUMERIC(16,0),
    shift_air_trips_per_year    NUMERIC(12,0),
    shift_air_trip_km_per_year  NUMERIC(16,0),
    shift_car_trips_per_year    NUMERIC(12,0),
    shift_car_trip_km_per_year  NUMERIC(16,0),
    co2_savings_t_per_year      NUMERIC(12,1),
    subsidy_eur_per_t_co2       NUMERIC(10,2),
    demand_kpis_placeholder     BOOLEAN NOT NULL DEFAULT TRUE,

    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_summaries_countries   ON proposals.proposal_summaries USING GIN (countries);
CREATE INDEX idx_summaries_stop_ids    ON proposals.proposal_summaries USING GIN (stop_ids);
CREATE INDEX idx_summaries_geom        ON proposals.proposal_summaries USING GIST (geom_simplified);
-- btree indexes on sortable KPI columns added as query patterns settle
```

`geom_simplified`: per-segment shapes concatenated and simplified
(Douglas-Peucker, tolerance tuned for gallery-map zoom levels) — small
enough to ship all proposals in one map response for a long time; the GiST
index enables bbox/viewport filtering when that stops being true.

The extraction function `(route dict, evaluation output) → summary row` is
a pure module `adapters/proposal_projection.py` (called by the repository
during publish, so it cannot live under `api/helpers/` without inverting
the dependency direction). Route metrics computed as today's
`proposal_summary_to_dict`; per-train-km KPIs from the existing
`views.*.per_train_km` normalisation; annual totals from `per_year`; the
fingerprint (§3.1) computed here.

### 5.5 ONTD summaries (projection at seed time)

Existing night train routes stay in the `ontd` schema — deliberately **not**
the proposals schema. For gallery/map union they get their own thin
projection, built at seed time (ONTD is script-loaded, so no runtime
maintenance): `ontd.route_summaries` with the shared *subset* of the summary
shape — name, stop_ids, countries, total_distance_km, geom_simplified — and
no financial or demand KPIs (which also implements the "no rating of
existing routes" policy at schema level, not by convention).

---

## 6. Lifecycle flows end to end

*Create:* compute (ephemeral, as often as wanted, cache-backed) → publish
`new` on the current base scenario → one transaction writes GTFS +
sidecars, evaluation output, summary row, `update_log` 'published'. The
proposal is immediately complete (route + evaluation + KPIs).

*Edit:* load own proposal → compute edits ephemerally → publish `overwrite`
→ state counter +1, previous state pruned. Route, composition, settings —
whatever changed is simply the new state; there is nothing else to keep
consistent.

*Explore variants:* load any proposal → switch scenario/composition in the
editor → ephemeral compute (cache-backed) — nothing stored. Publishing a
composition variant the user wants to *keep* is `mode: "new"` (a second
gallery item) or `overwrite` (the proposal now uses that composition), the
user's choice. Scenario variants are never publishable (§2.2) — they live
in exploration and compare.

*Build on foreign:* load foreign proposal (read-only) → explore ephemerally
→ publish `new` (optionally with `based_on_proposal_id` for the timeline).

*Compare:* per-side resolution (§7.3): a side without overrides is the
stored proposal; any override → ephemeral compute (cache-backed), marked
`published: false`. Publishing a computed side afterwards is an ordinary
publish (base-scenario rule applies).

*Version bump / base scenario move:* refresh batch recomputes all affected
proposals in place (§4.2); `scenario_outdated` flags + on-load fallback
cover the gap.

---

## 7. API design

All list/filter/sort/aggregate work runs in SQL against
`proposal_summaries` (+ `ontd.route_summaries`).

### 7.1 `POST /api/proposals` — gallery + map in one endpoint

One filter model drives both gallery and map. The response is sectioned;
the caller picks sections via `include`.

**Every stored proposal is a gallery item**, always representing the
current base scenario (or flagged `scenario_outdated: true` between a base
move and its refresh, derived by joining `scenario.scenarios`). There is no
variant-level mode — scenario browsing happens in compare (§7.3), where
other scenarios are a first-class dimension.

**Filter rule**: every **numeric** summary column (§5.4) accepts a
`{"min": …, "max": …}` range (either bound optional); every **categorical**
column accepts a value list; `name` accepts a case-insensitive substring.
Every summary column is sortable. The example below is not exhaustive — it
shows one filter of each kind:

```jsonc
{
  "filter": {
    "sources":         ["proposal", "existing"],       // default ["proposal"]
    "user_ids":        [int, ...],                     // e.g. "my proposals"
    "countries":       [str, ...],
    "stop_ids":        [str, ...],
    "composition_ids": [str, ...],
    "name":            "brenner",                      // substring, case-insensitive
    "total_distance_km":   {"min": 800, "max": 1500},
    "total_time_h":        {"min": 8,   "max": 14},
    "avg_speed_kmh":       {"min": 70},
    "n_stops":             {"max": 12},
    "margin_eur_per_train_km": {"min": 0},             // any KPI column likewise
    "subsidy_eur_per_year":    {"max": 5000000},

    "trip_windows": [                                  // timetable filter, see below
      {"stop_id": "OSM-...-berlin-hbf", "departure": {"from": "20:00", "to": "23:00"}},
      {"stop_id": "OSM-...-roma-ti",    "arrival":   {"from": "07:00", "to": "09:30", "day_offset": 1}}
    ],

    "bbox": [w, s, e, n]                               // optional, see below
  },
  "sort":    [{"by": <any summary column>, "dir": "asc"|"desc"}],
  "limit":   int, "offset": int,
  "include": ["summaries", "map_lines", "map_stop_counts", "map_country_counts"]
}
```

**`trip_windows`** — the one filter that reaches past the summary table
into the stored timetables (`stop_times` + sidecars): each entry constrains
the departure and/or arrival time at one stop; a proposal matches when a
**single trip** satisfies all entries (so "depart Berlin 20:00–23:00 and
arrive Roma 07:00–09:30 next day" means one train doing both, not two
different trips). Times follow the GTFS overnight convention internally
(arrival next day 08:30 = 32:30); the API accepts wall-clock times with an
optional `day_offset` and converts. Implemented as a join against
`stop_times` — costlier than summary filters, acceptable because it is
only evaluated when present.

**`bbox`** — matches proposals whose route **intersects** the box
(`ST_Intersects` on `geom_simplified`, GiST-indexed): map viewport loading
("only fetch what is visible while panning") and regional filtering.
Optional and deferrable — with the whole filtered set shipped to the map
anyway (below), it becomes relevant only at volumes we do not have yet.

Response sections:

- `summaries`: paginated summary rows + `total` (windowed count), each row
  carrying `source: "proposal" | "existing"` and `scenario_outdated`. ONTD
  rows have KPI fields null and no user/engagement metadata.
- `map_lines`: GeoJSON FeatureCollection of `geom_simplified` with minimal
  properties (id, source, name, one colorable KPI) — filtered but **not**
  paginated (the map shows the whole filtered set).
- `map_stop_counts`: `[{stop_id, lat, lon, n}]` — routes touching each stop
  (unnest over `stop_ids`, coordinates joined from the stop catalog).
- `map_country_counts`: `{country: n}` — for the coverage choropleth
  ("which countries have no proposals yet").

`GET /api/proposals` stays as the empty-filter, summaries-only
convenience.

### 7.2 `GET /api/proposal/<id>` — load

- performs the on-load version-refresh fallback (§4.2), so a load always
  returns the current-base state (or the freshly refreshed one)
- returns exactly the compute-response shape (§2.1) — reconstructed route
  dict, evaluation with `input.parameters` rebuilt via the scenario pin,
  route appearing once — plus proposal metadata (id, owner, name, versions,
  timestamps, `scenario_outdated` when the refresh fallback was skipped or
  deferred)

Scenario/composition switching from a loaded proposal is a frontend concern:
it takes the returned resolved `request`, changes the field, and calls
`POST /api/proposal/calc` (cache-backed) — no stored variants exist to
enumerate, so there is no variants section.

### 7.3 `POST /api/proposals/compare`

Each side is anchored on one **proposal**, with optional overrides computed
within that side. Same anchor on both sides = variant compare on one route
(e.g. TAC scenario A vs B); different anchors = cross-proposal compare
(e.g. your proposal vs someone else's, each on a chosen scenario):

```jsonc
{
  "sides": [
    {"proposal_id": 123, "scenario_id": 4},        // side A: my proposal under scenario 4
    {"proposal_id": 456, "scenario_id": 4}         // side B: other user's proposal,
  ]                                                //   same scenario for a fair diff.
                                                   // Omitted override = the proposal as
                                                   // stored; a bare {"proposal_id": …}
                                                   // side is simply that proposal.
                                                   // Overridable: scenario_id,
                                                   // composition_id.
}
```

A side without overrides loads the stored proposal. A side **with**
overrides is computed ephemerally — the anchor's stored `compute_request`
with the overridden fields, through the ordinary compute function (which
both reads and feeds the compute cache, §2.3) — never persisted, marked
`published: false`, no ownership questions. Response per side: full
compute-response shape (+ summary row for stored sides); plus a `diff`
section with per-KPI absolute and relative deltas and a structured diff
over the shared `views` trees (same view keys → per-leaf deltas), so the
compare view can show *which* cost component moved; plus route context via
the fingerprints (identical route or not, which inputs differ). Ephemeral
sides share the compute latency of the editor on a cache miss — the UI
needs a loading state.

Two sides for now; the shape allows more later.

### 7.4 No delete API

With one stored state per artifact there is no in-flow removal at all;
cleanup is manual/script work directly on the database. (Guest-hygiene
retention job: not needed — ephemeral compute leaves no drafts behind.)

### 7.5 `GET /api/proposal/<id>/timeline`

Chronological merge of `update_log`, `comments`, and `likes` for one
proposal. Natural home: `api/proposal_engagement.py`.

### 7.6 Replaced endpoints

`POST /api/route/plan` and `POST /api/evaluation/calc` are replaced by
`POST /api/proposal/calc` + `POST /api/proposal/publish`. Removal, not
deprecation — the frontend migrates in the same coordination batch (WP12);
`test_stub_endpoints_return_501` and the API README change accordingly.

---

## 8. KPI definitions & placeholder policy

| KPI | Source (real) | Status |
|---|---|---|
| cost / revenue / margin per train-km | `views.route.per_train_km` | available now |
| subsidy per year | `max(0, -net_eur)` from `views.route.per_year` — **gap to target margin** (net_eur is after the EBIT margin target), locked decision | available now |
| demand per year (trips, trip-km) | `views.route.per_year` demand values (§8.1) | **placeholder** |
| shift air→NT, car→NT (trips, trip-km) | `views.route.per_year` demand values (§8.1) | **placeholder** |
| CO2 savings per year | `views.route.per_year.co2_savings_t` = shifted trip-km × per-mode emission factors (scenario-versioned params table — details deferred to demand-model work) | **placeholder** |
| subsidy per t CO2 | subsidy / CO2 savings — the one cross-value ratio, computed in the **projection**, not in views | **placeholder** |

### 8.1 Where demand outputs live

The demand model (post-calibration work) introduces **no new storage
location** — its outputs split along the operative/analytical line the
architecture already draws:

- **Operative demand** — what revenue calculation consumes: per-OD,
  per-class, per-trip passengers and prices. This is exactly what `ODPair`
  holds today (`places_sold`, `avg_price`, `class_main`, `trip_id`),
  currently filled by the stopgap `distribute_demand()`. The demand model
  slots into the merged pipeline at that same point — route build →
  **demand model** → evaluation — replacing the stopgap as the source and
  writing the route's od_pairs in place. Stored in the `proposals.od_pairs`
  sidecar, shape unchanged. E.g. "X passengers in couchette per trip" =
  od_pairs rows with `class_main = couchette` for that trip. The
  fingerprint is untouched: demand never changes route identity.
- **Analytical demand** — reporting that nothing downstream computes with:
  modal shift and CO2. These become new **value keys in the existing
  views** (`pax`, `pax_km`, `shift_air_pax`, `shift_air_pax_km`,
  `shift_car_*`, `co2_savings_t`) across the existing matrices —
  `views.route` for totals, `per_trip_pair`, and `per_trip_pair_per_od`
  (where "shifted from airplane on Berlin→Roma" naturally sits, next to
  that OD's revenue) — flowing through the existing normalisations, so
  `per_year` variants exist for free. Plus: a `demand` entry in `models`
  (the slot `ModelVersions` already reserves), and demand parameters
  (elasticities, emission factors, catchment data) in scenario-versioned
  params tables, surfacing under `evaluation.input.parameters` via the
  rebuild-on-read path (§5.1).
- **Gallery**: the summary projection extracts the demand columns (§5.4)
  from `views.route.per_year`, exactly as it extracts the financial KPIs —
  and computes the `subsidy_eur_per_t_co2` ratio itself.

Forward-looking note: if a demand-*aware* `schedule_mode` ever varies
seasonal frequency, recheck fingerprinting — frequency is not part of the
fingerprint (stops/geometry/times only).

Placeholder policy (first implementation, to get API + frontend running):
the projection fills demand-dependent columns with **deterministic fakes
derived from route metrics** (stable across recomputes, plausible orders of
magnitude for UI development) and sets `demand_kpis_placeholder = TRUE`. The
flag is carried through every API response so the frontend can badge the
values. When the demand model lands (next step after calibration), it
adds its values per §8.1, the projection extracts real numbers, the flag
flips, and the version-refresh batch (§4.2) re-runs everything — no special
backfill path needed.

---

## 9. Locked decisions

1. **Merged compute API**: route planning + evaluation are one endpoint,
   one pipeline, one response; no half-states exist anywhere. Both version
   tracks (`ROUTE_BUILDER_VERSION`, `CALC_VERSION`) remain separate
   constants.
2. **Ephemeral compute, explicit publish**: computing never writes;
   proposals exist only through publish (plus system refresh). Unsaved
   exploration is a frontend concern (draft caching, warn-on-navigate).
3. **One stored state per route artifact**: no stored scenario/composition
   variants, no families, no variant coordinates, no default-member
   resolution. Variant exploration is ephemeral compute backed by the
   compute cache, which is fed by both `/calc` and compare.
4. **Published proposals are always on the current base scenario**: publish
   rejects non-base `scenario_id` (422). What-if scenarios are an analysis
   dimension (compute, compare), never an artifact dimension. The refresh
   batch re-bases all proposals when the base moves — this deliberately
   revises the earlier "pins are never rewritten" rule, whose purpose
   (protecting pinned variant artifacts) no longer exists.
5. **Publish integrity**: the server never persists client-supplied
   results — publish carries inputs, the server computes what it stores,
   freshly or from the compute cache, which only ever holds
   server-computed results. The acting user comes exclusively from the
   auth layer, never the request body.
6. **Overwrite vs new is the user's explicit choice** at publish; the
   publish handler has exactly these two cases. Hard delete of the
   previous state in-transaction; one row per proposal — no `is_current`
   flag, no `change_log` column; `update_log` preserves the timeline for
   comments/likes.
7. Route stored **once**: GTFS + sidecar tables, reconstructed on read;
   evaluation output stored as `models` + `views` only — route and
   `input.parameters` are rebuilt on read (parameters exactly recoverable
   through the immutable scenario pin).
8. **Proposal identity is `proposal_id` alone; no deduplication.** The
   route fingerprint is informational (compare context, analytics) — no
   lookup, index, or handler branch depends on it.
9. Building on a foreign proposal = loading + ephemeral exploration +
   publish-as-new (`based_on_proposal_id` optional,
   timeline-informational only).
10. Every stored proposal is a gallery item; `scenario_outdated` flags the
    window between a base move and the proposal's refresh.
11. Version bumps and base moves are handled by the system (batch refresh +
    on-load fallback), logged in `update_log`.
12. Subsidy = gap to target margin (`max(0, -net_eur)`).
13. Fingerprint identity = resolved stop lists + geometries + exact trip
    schedules; request settings are state.
14. ONTD stays in its own schema; union at API level with explicit `source`
    marking and no KPIs for existing routes.
15. Demand-dependent KPIs faked with an explicit placeholder flag until the
    demand model exists.
16. Compare takes one proposal anchor per side; overridden sides are
    computed ephemerally (cache-backed), never persisted.
17. No delete API, no guest-hygiene job.

---

## 10. Implementation plan — work packages

Sized so each can be worked off in its own chat thread, and sequenced so
that **the full test suite is green after every single WP** — each WP ships
its own tests, script updates, and README adjustments. The one structural
device making this possible is the **two-phase schema migration**: WP1 is
purely additive (old code keeps running), and WP5 is the single cutover PR
that finalizes the schema atomically with the code that requires it. Every
WP ends with the standard closing steps (README sweep, sanity check,
feat/test/docs commits, full suite green from `backend/` via
`uv run --extra dev pytest`).

**WP1 — Schema migration, phase 1 (additive only)** *(no dependencies)*
Migration under `backend/db/dev/sql/migrations/`: new tables — sidecars
(§5.2), `update_log`, `proposal_summaries`, the two compute-cache
tables `compute_cache_pointer` + `compute_cache_result` (exact DDL and
read/write/cleanup algorithm finalized in §2.3, 2026-08-03) —
plus new **nullable** columns on `proposals.proposals`
(`route_fingerprint`, `compute_request`, `stop_times.stop_type`). Nothing
dropped, no constraint the existing persist-on-calc code violates. The
cache tables' read/write/cleanup logic itself (request hashing, the 1%
opportunistic TTL sweep, the version-bump flush) is WP13 — WP1 only lands
the tables and indexes.
*Testable by*: migration applies on a fresh dev DB + schema-assertion
checks extending `backend/tests/test_02_db_seed.py` (information_schema
table/column existence, PostGIS geometry column on
`proposal_summaries.geom_simplified`). *Green because*: strictly
additive — existing endpoints and tests untouched.

**WP2 — Merged compute endpoint (additive)** *(parallel to WP1)*
`POST /api/proposal/calc`: orchestrate route building + evaluation in one
pipeline (API boundary, with one deliberate additive exception —
`RouteProvenance` (`models/route/route_factory.py`) now also carries
`compositions`/`stop_infra` alongside `tracks`, so the merged endpoint
reuses what `plan_route()` already builds internally instead of a second
`loader.build_all_compositions()`/`build_all_stops()` call; existing
callers unaffected, no behaviour change, see `RouteProvenance`'s
docstring. This is a general principle for the whole refactor, not a
WP2-only carve-out: **prefer reuse over parallel reload whenever an
additive, non-behaviour-changing extension is available — a duplicate
load is only acceptable as a genuinely temporary stopgap, not a default.**
`models/evaluation` stays untouched); neutral structural IDs; merged
request validation (verified: calc carried no extra inputs beyond the
scenario override); response shape per §2.1 incl. the **resolved** request
echo and `cache_hit` meta (fingerprint wiring completed after WP4). The
old `/api/route/plan` and `/api/evaluation/calc` **stay in place until
WP5** — no persist hooks are touched here. *Testable by*: stateless
endpoint tests over the merged response shape, reusing the existing
plan/calc fixtures. *Green because*: purely additive endpoint plus a
purely additive provenance extension — no existing caller's behaviour
changes.

**WP3 — Route decomposition + reconstruction serializer** *(after WP1)* ✅
*implemented 2026-08-03.* GTFS + sidecar insert (write side, prefix
assignment as at publish); new `api/helpers/route_gtfs_serialize.py` with
`insert_route_gtfs()` (write) and `route_dict_from_gtfs()` (read —
composition/track_infrastructure reloaded via loader, `general_parameters`
recomputed by reconstructing domain objects and handing off to the
existing `route_to_dict()` rather than reimplementing its serialization)
and `input_parameters_from_scenario()` (scenario-pin → `params_serialize.py`,
reused via `evaluation_serialize.input_to_dict(..., include_route=False)`).
Standalone from `adapters/proposal_repository.py`'s old `_insert_gtfs()`,
which stays untouched and in use until WP5's cutover.

One additive schema gap found and closed during implementation: `phase 1`
missed a column for `Stop.auto_added` — not derivable after the fact, so
`migrations/2026-08-03_proposal_schema_phase1b_auto_added.sql` adds
`stop_times.auto_added BOOLEAN NOT NULL DEFAULT FALSE` alongside `stop_type`.
Also confirmed, not a bug: `proposals.od_pairs.avg_price NUMERIC(10,2)`
genuinely rounds `distribute_demand()`'s raw stopgap fare output (which
carries far more than 2 decimals) on storage — correct precision for a
EUR column; the round-trip tests' expectations account for this rather
than the schema being loosened to avoid it.

*Testable by*: standalone round-trip tests
(`tests/test_36_proposal_gtfs_roundtrip.py`) — WP2 compute responses as
fixtures, written under real `proposal_id`s (allocated from the live
`proposals.proposals` sequence — no separate test-ID range needed),
reconstructed, deep-equal (parameters included). No publish endpoint
needed. *Green because*: new module + phase 1b's one additive column
only; old persist path untouched — 411 passed, 0 failed on the full suite
after landing.

**WP4 — Fingerprint & projection module** *(after WP3)* ✅ *implemented
2026-08-03.* `adapters/proposal_projection.py`: canonical route extract +
SHA-256 fingerprint (§3.1); summary-row builder (route metrics, KPI
extraction, geometry concatenation + simplification, placeholder KPI
filler + flag). Fingerprint + `cache_hit` wired into the WP2 compute
response (`cache_hit` hardcoded `false` — no cache exists until WP13;
adding the field now means WP13 is a pure logic swap, not a response-shape
change).

Two implementation-time refinements over the plan text: (1) "prefix
stripping" turned out to be unnecessary rather than a rule to implement —
the canonical extract never reads `route_id`/`trip_id`/`geometry_id` in
the first place, only `stop_id` (a stable, unprefixed reference), so
ephemeral and published forms hash identically by construction; a
dedicated test (`TestFingerprint.test_ignores_id_prefix`) asserts this
directly rather than relying on it as an implicit consequence. (2)
`total_time_h` in the summary row is read from each trip's
`general_parameters.route_duration_min` rather than re-summed from
segments the way the pre-refactor `proposal_summary_to_dict` does — that
helper's manual sum silently omits `slack_time_min`; the trip-level field
is already correct and avoids re-deriving it.

*Testable by*: pure-function tests on compute fixtures
(`tests/test_37_proposal_projection.py`); equal-fingerprint assertions for
ephemeral vs prefixed and original vs reconstructed forms
(`tests/test_36_proposal_gtfs_roundtrip.py`'s `TestFingerprintRoundtrip`);
projection rows asserted against `proposal_summaries` via a direct test
insert (schema conformance ahead of WP5's real writer). *Green because*:
additive module; the only touched endpoint (WP2's) gains two fields — no
existing test's assertions narrowed the response shape. Confirmed: 425
passed, 1 skipped (the pre-existing
`test_per_available_place_km_divisor_is_unweighted` xfail — unrelated to
this WP) on the full suite via `uv run --extra dev pytest tests/ -v`.

**WP5 — Cutover: publish endpoint, repository, schema phase 2** *(after
WP2 + WP4; the core WP — the one deliberately large one)* ✅ *implemented
2026-08-05.* The single PR where old and new worlds swap, atomically:
`POST /api/proposal/publish` (base-scenario validation 422
`scenario_not_base`, ownership check, publish handler
`api/helpers/publish_dispatch.py` with its two cases, `based_on` timeline
entries, prefixed-ID assignment); `adapters/proposal_repository.py`
rewritten around single-transaction `publish()` (proposal row + GTFS/sidecars
+ summary + update_log; prune on overwrite; `FOR UPDATE` serialization);
**minimal** `GET /api/proposal/<id>` (compute-response shape via WP3
reconstruction) and **minimal** `POST/GET /api/proposals` (plain summaries
list, pagination — full filters follow in WP6); removal of
`/api/route/plan` + `/api/evaluation/calc` and all persist-on-calc code;
**finalizing migration** (drop `route_body`/`evaluation_body`/
`is_current`/`change_log`, enforce NOT NULLs — see data note below);
complete rewrite of the persist test suite. *Testable by*: integration
tests — create, edit, composition change via overwrite and via new,
build-on-foreign, non-base rejection, load round-trips (concurrent
publishes covered structurally by `FOR UPDATE` serialization in
`publish()`, not by a dedicated threaded test — see the deviations note
below). *Green because*: everything depending on the old world is
replaced within this one PR.

Several deviations/decisions made during implementation, none changing
the locked design, one amending it:

1. **`models/pipeline.py` (new layer, not in the original plan).** Domain
   orchestration (plan → distribute demand → evaluate → build views) was
   pulled out of `api/proposal_calc.py` into a new `models/pipeline.py`
   module, with `api/helpers/proposal_compute.py` left as a thin
   serialization wrapper around it. Rationale: pipeline *sequencing* is
   domain-level composition, not serialization, so it belongs in
   `models/` under this project's existing layering rule
   (`models/` = domain, `api/helpers/` = serialization, `adapters/` = DB)
   — keeping it in `api/helpers/` (as the original WP2 code had it) was
   an artifact of not yet having a publish path that needed to reuse it.
   Both `POST /api/proposal/calc` and `publish_dispatch.py` now call the
   same `compute_proposal()` (`api/helpers/proposal_compute.py`), which
   calls `models.pipeline.run_compute()` — the two paths can't drift
   apart, and WP13's compute cache has a natural insertion point at the
   `proposal_compute.py` level.
2. **`name` added to `proposals.proposals`** — see §5.3's own note; the
   locked container shape omitted it, WP5 added it back for the reason
   documented there.
3. **Compute-or-cache in the design text was compute-only in practice.**
   §2.2's "freshly or from the compute cache" always resolves to "freshly"
   right now, since WP13 (the cache) hasn't landed — `dispatch_publish()`
   calls `compute_proposal()` unconditionally. No code changes needed
   when WP13 lands: the integrity rule ("never persist a client-supplied
   result") holds either way, and the cache is designed to be a
   transparent lookup ahead of the same compute call.
4. **Concurrent-publish testing scope.** The design's "testable by" list
   named concurrent publishes explicitly; `publish()`'s `FOR UPDATE` row
   lock on overwrite provides the actual serialization, but the test
   suite doesn't exercise it with real concurrent threads/connections —
   only sequential overwrite/ownership/not-found cases. Flagged as a gap
   rather than silently dropped; a genuine concurrency test (two
   overwrite-publishes racing against the same `proposal_id`) is
   reasonable follow-up work, not part of this PR.
5. **Test suite: `test_20_route_plan_api.py` and
   `test_30_evaluation_api.py` deleted** (their HTTP contract coverage
   for the removed endpoints is superseded by `test_35`); their
   *content*-level coverage was not simply dropped, though — see below.
6. **`test_21`/`test_31`/`test_40` converted, not deleted.** These test
   route-building and evaluation *content*, not HTTP contract, so they
   were repointed to the surviving endpoints/model layer instead of
   removed: `test_21` now drives route-building through
   `POST /api/proposal/calc`; `test_31`/`test_40` call the model layer
   directly (`tests/helpers.py:compute_evaluation_domain()` —
   `route_from_dict()` → `add_directional_domain_demand()` →
   `evaluate_route()` → views) since `POST /api/proposal/calc` has no way
   to inject custom demand into an already-built route the way the old
   `POST /api/evaluation/calc` did (a real capability gap, not a
   like-for-like replacement — flagged and confirmed before proceeding).
   `test_20`'s `TestFixedNightMode`/`TestModeSwitches`/scenario-handling
   classes (behavioral content, not contract) were ported into `test_21`
   for the same reason, after initially being dropped by mistake and
   caught on a later cross-reference sweep — see `test_21`'s module
   docstring for the full port rationale.
7. **`test_50_proposals_api.py` is a full rewrite**, per the design's own
   call — the old persist-on-calc contract (created/unchanged/versioned/
   branched) has no shape in common with publish's new/overwrite pair.
8. **`db/dev/seed.py`'s example proposal now carries a real evaluation.**
   The pre-WP5 seed published a route with no demand/evaluation (a
   half-state the old schema allowed). WP5's "no half-states" rule
   (§2.4) makes that impossible, so `seed_example_proposal()` now runs
   its hand-crafted route through the real evaluation pipeline
   (`_compute_example_proposal()` — deliberately *not* through
   `models.pipeline.run_compute()`, to avoid a live-OpenRailRouting
   dependency at DB-seed time; the route's physics stay hand-crafted,
   only demand/cost/revenue are newly real) before calling `publish()`
   directly.
9. **Four standalone dev scripts under `scripts/`** (`test_route_plan.py`,
   `test_evaluation_calc.py`, `test_scenario_comparison_paris_berlin.py`,
   `test_timetable_comparison_hamburg_copenhagen.py`) referenced the
   removed endpoints. Three were repointed to `/api/proposal/calc`
   (mechanical URL/response-shape updates); `test_evaluation_calc.py`'s
   whole premise (costing an arbitrary pre-built route under injected
   demand) has no HTTP successor, so it was retired with a notice
   pointing at the same model-layer pattern `test_31`/`test_40` use.

*Testable by* confirmed via: `ruff format`/`ruff check` clean on every
changed file; full-tree `py_compile`; real (non-DB) import of every new/
changed module including `main.py`; and constructing a live Flask app
with the actual blueprints registered to confirm the URL map has no
route collisions (`/api/proposal/calc`, `/api/proposal/publish`,
`/api/proposal/<id>`, engagement routes all coexist as expected). Full
integration-test execution against the live Docker stack (the suite's
normal green-bar check) was not run as part of this implementation pass
— the usual `uv run --extra dev pytest tests/ -v` from `backend/` is the
next step before merging.

*Data strategy (decided)*: **drop and recreate, no row migration.** The
finalizing migration is an ordinary migration SQL through the standard
`db/migrate.py` process that drops all old proposal-storage tables
(`proposals.proposals` + the old GTFS decomposition) and creates the final
shape — current stored proposals are pre-launch test artifacts.
Engagement tables and `update_log` use soft references, so they survive
structurally; their stale pre-cutover rows are truncated in the same
migration for a clean start. Nothing to reseed: proposals are
user-generated content, and the params/ONTD/scenario schemas are
untouched.

**WP6 — Gallery/map endpoint (full)** *(after WP5)*
Extends WP5's minimal list to the full §7.1 contract: generic
range/list/substring filters over all summary columns,
`scenario_outdated` derivation, `trip_windows` stop-time filter (GTFS
overnight-time convention), sorting, windowed count, `include` sections;
`bbox` optional/deferrable. *Testable by*: endpoint tests over seeded
published proposals per filter class.

**WP7 — Load endpoint completion** *(after WP5, parallel to WP6; small)*
Extends WP5's minimal load to the full §7.2 contract: proposal metadata
block, `scenario_outdated`, response-contract tests against the §2.1
shape. *Testable by*: contract tests on published fixtures.

**WP8 — Version-refresh mechanism** *(after WP5, parallel to WP6/7)*
`backend/scripts/refresh_proposals.py` (batch: outdated versions +
non-current-base scenario pins, recompute + re-base in place, owner kept,
`update_log` 'recalculated', idempotent, dry-run, concurrency limit) + the
on-load refresh fallback in WP7's endpoint. *Testable by*: publish under
current base → move base scenario in test fixtures → batch run assertions
(re-based scenario_id, update_log rows, summary refresh); on-load fallback
test.

**WP9 — Compare endpoint** *(after WP7, uses WP8's on-load refresh)*
`POST /api/proposals/compare`: per-side resolution (stored vs override →
ephemeral compute through the cache), full sides + KPI deltas + structured
`views` diff + fingerprint-based route context. *Testable by*: two
published fixtures + override sides; `published: false` marking; diff
assertions.

**WP10 — ONTD integration** *(after WP6; independent of WP7–9)*
`ontd.route_summaries` projection built in the seed pipeline
(`backend/db/dev/`); `sources` filter + union in `POST /api/proposals`;
`source` marking throughout. *Testable by*: seeded ONTD rows appearing in
gallery/map sections with null KPIs.

**WP11 — Timeline endpoint** *(after WP5; small)*
`GET /api/proposal/<id>/timeline` in `api/proposal_engagement.py` merging
`update_log` + comments + likes. *Testable by*: publish → comment →
overwrite sequence asserted in order.

**WP12 — Frontend coordination batch (Bjarne)** *(rolling; heads-up
before WP5 lands, full audit before the staging PR)*
The largest contract change so far: `/api/route/plan` +
`/api/evaluation/calc` → `/api/proposal/calc` + `/api/proposal/publish`
(incl. the publish dialog: name, overwrite-vs-new, based_on; publish
re-computes on base if the user explored a what-if); client-side draft
caching / warn-on-navigate; scenario/composition switching as pure compute
calls (no variants section); restructured `POST /api/proposals` (generic
filters, `trip_windows`, sections, `scenario_outdated`); compare
(`published: false` sides need a loading state) and timeline endpoints;
`source`, `demand_kpis_placeholder`, `cache_hit` fields;
reconstructed-response note (byte-identity not guaranteed, structure
identical). Audit `frontend/src/types/api.ts` end to end.

**WP13 — Compute cache** *(after WP2 + WP4 for the fingerprint;
independent of WP5–12 — worth doing early, it speeds up every later WP's
integration tests)*
The two-map design of §2.3: pointer map (request_hash → result identity,
holding request-specific parts) + result map (`(fingerprint, scenario_id,
composition_id)` → route + evaluation core, one entry per distinct
result); canonical request hashing shared with the publish path; TTL
cleanup (default 3 h, configurable); flush hook for the version-bump
procedure (wired into WP8's refresh script once it lands); `cache_hit`
semantics; wire-in for `POST /api/proposal/calc`, reuse in publish (WP5)
and compare (WP9) once those land. Verify the key-correctness assumption
(all evaluation inputs reachable via the scenario pin). *Testable by*:
`cache_hit` on repeated identical requests; hit via a **different** request
converging on the same result (pointer→shared result); miss on any
output-changing field; response `request` echo always matches the actual
request; TTL expiry; flush empties both maps.
