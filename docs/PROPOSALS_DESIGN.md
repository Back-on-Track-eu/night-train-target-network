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
   version bump / base scenario move; idempotent, resumable, dry-run mode.
   The live-routing compute step is parallelized across a configurable
   `--concurrency` worker threads (each with its own `DBDataLoader` —
   cheap, no heavy precompute — sharing the one process-wide `RailRouter`,
   already built for concurrent use); DB writes stay sequential on the
   single `ProposalRepository` connection, which is not thread-safe (see
   WP14, §10, for pooling every connection properly).
2. **On-load fallback**: `GET /api/proposal/<id>` detects an outdated
   proposal (`outdated_trigger()`) and refreshes before returning —
   correctness for anything the batch hasn't reached, at the cost of one
   slow load.

Both mechanisms share one staleness check
(`adapters/proposal/repository.py`'s `outdated_trigger()`, checked in
priority order `route_builder_version` → `calc_version` →
`base_scenario_moved`): purely internal, server-side — **no user-facing
staleness flag exists** (an earlier revision surfaced `scenario_outdated`
on gallery/load rows; removed, WP7/8, since the system keeps every
proposal current on its own and there was nothing for a reader of that
flag to actually do with it). A refresh may change the route fingerprint
(new routing graph, new infrastructure) — `refresh_proposal()` simply
stores whatever the recompute produced, same as any other write.

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

    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),  -- set once, never touched by overwrite (WP6.1)
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

### 5.5 ONTD integration (revised 2026-08-04, WP10 kickoff)

Existing night train routes stay in the `ontd` schema — deliberately **not**
the proposals schema. WP10 splits the `ontd` schema into two table classes
with different lifecycles:

**Refreshed tables** — the 11 canonical ONTD mirrors (`agencies`, `stops`,
`routes`, `trips`, `trip_stop`, `calendar`, `calendar_dates`, `classes`,
`translations`, `routes_inactive`, `trips_inactive`) plus the derived
`route_summaries` projection. TRUNCATEd and reloaded on every half-yearly
ONTD refresh. Note the schema has never been created or loaded in any
environment before WP10 (`seed.py` deliberately doesn't know it) — the
loader bootstraps its own DDL by applying `create_ontd_schema.sql` at the
start of every run, which is destructive only to refreshed tables
(curated tables are `CREATE TABLE IF NOT EXISTS`, never dropped). The
loader reads the workbook directly from a public Google link (no API
key/credentials; link-shared "Viewer") for full traceability. Which workbook is
configured in `backend/docker/.env` (`ONTD_WORKBOOK_ID` /
`ONTD_WORKBOOK_KIND`, documented in `.env.example`), resolved by
`xlsx_utils.workbook_url()`. **Since 2026-08-05 the ONTD source is an uploaded
.xlsx in Drive rather than the live native sheet**, because the stop
coordinate fixes were applied to a copy — so a refresh now reads a
frozen snapshot and no longer picks up the editors' ongoing changes.
Point the registry back at the native sheet once those fixes are merged
upstream. There is a
local `--xlsx` fallback for offline dev. Sheet artifacts handled on
import: Chatbase/AutoCrat trailer
columns on `trips`, the leading `train_stop_id` column on `trip_stop`,
case-insensitive header mapping (`UID`), column-name-intersection mapping
for the inactive tables (their sheet columns diverge from the active
twins), and `HH:MM` serialization for duration/time cells that come back
as timedelta/time objects.

**Curated tables** — `coach_classes`, `coachtypes`, `coachtype_classes`,
`compositions`, `composition_coaches`, `route_compositions` (route →
composition assignment). Imported **once** from the target-network
workbook (`db/ontd/composition_loader.py`), after which the DB is the
source of truth and updates happen by hand in the DB (new coach material,
missing data); the importer refuses to overwrite non-empty curated tables
unless `--replace` is given. `coach_classes` exists because the
catalog's taxonomy is *not* a finer cut of the refreshed `ontd.classes`
as first assumed — measured overlap is 7 of 26 ids — so the two lists
are stored separately and joined only via the coarse `class_main`
grouping. `occupancy_rate` was dropped from the source workbook before
the import ran, so it is hand-maintained (NULL on import). Excluded from the refresh TRUNCATE; they reference
refreshed tables only via **soft references** (route_id, agency_id,
class_id — no FKs across the lifecycle boundary, same convention as
input_params soft references), so a refresh can never cascade into
curation. After each refresh the loader reports assignments whose
route_id no longer exists.

**`ontd.route_summaries`** — the gallery/map projection, rebuilt by the
loader after every refresh, one row per **active** route:

- descriptive: name, stop_ids, n_stops, countries, total_distance_km,
  total_time_h (average over the two directional trips), avg_speed_kmh,
  composition_id (nullable — only where curated; 151 of 204 active routes
  at import time),
- emissions: co2_g_per_pax_km from `ontd.trips.co2_per_km` (296 of 408
  active trips carry it),
- `ontd_url`: deep link to the route's public ONTD page
  (`back-on-track.eu/nighttrains/?route_id=<id>`), so the gallery can
  point an existing route back at its source record. A GENERATED column,
  not loader-written — the URL is a pure function of `route_id`, so a
  stored copy could only drift; and since the table is rebuilt on every
  refresh, changing the pattern is a DDL edit with no migration.
- geometry: geom_simplified, produced by routing each active route
  through OpenRailRouting (`simpleRouting` — no composition physics
  needed for geometry) at projection-build time, concatenated and
  simplified like proposal geometries; per-route straight-line fallback
  between consecutive stops when routing fails (snap failures on exotic
  stops), flagged via `geometry_routed`.

**`ontd.route_legs`** — a second, separate table: per-leg router output
(driving / dynamics / buffer split, distance, country time and distance
shares) beside the real timetable's running time for the same stop pair.
It is **not** a gallery projection and feeds no API; it is the input
dataset for calibrating country buffer quotas in a later work package.
Grain is the stop pair because buffer is calibrated per country — a
route crosses several, so a route-level total cannot be attributed to
any of them, while a leg carries `country_time_shares` and sits mostly
in one country. The two sides are comparable by construction:
`scheduled_running_min` is departure(from) → arrival(to), i.e. running
time with no dwell, and the router components are in-motion only, so
dwell never enters either side (verified: legs + dwell reconcile exactly
to wall-clock duration). Midnight rollover is resolved by walking the
stop sequence with a day offset, since ONTD times are HH:MM with no
date. Written only where routing succeeded — a straight-line fallback
has no component split, and storing zeros would quietly bias the
calibration.

**No financial or demand KPIs** — the reduced column set implements the
"no rating of existing routes" policy at schema level, not by
convention. Engagement (likes/comments) does not apply to ONTD rows
either.

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
proposals in place (§4.2); the on-load fallback covers anything the batch
hasn't reached yet — both purely server-side, no client-visible flag.

---

## 7. API design

All list/filter/sort/aggregate work runs in SQL against
`proposal_summaries` (+ `ontd.route_summaries`).

### 7.1 `POST /api/proposals` — gallery + map in one endpoint

One filter model drives both gallery and map. The response is sectioned;
the caller picks sections via `include`.

**Every stored proposal is a gallery item**, always representing the
current base scenario — the system (batch refresh + the load endpoint's
on-load fallback, §4.2) keeps it that way on its own, so there's no
transient-state flag to expose here. There is no variant-level mode —
scenario browsing happens in compare (§7.3), where other scenarios are a
first-class dimension. Because every row is always on the current base by
construction, `scenario_id` is **not** a filter — there is essentially
only one value to filter on at any moment. `route_builder_version`/
`calc_version` are likewise not filters: internal/analytical version
tracking, not a gallery-facing dimension.

**Filter rule**: every **numeric** summary column (§5.4) accepts a
`{"min": …, "max": …}` range (either bound optional) — `created_at`/
`updated_at` the same shape with ISO 8601 strings, and `likes_count`
(live-joined from `proposals.likes`, not a stored summary column — a like
changes independently of publish/refresh, so storing it would go stale)
likewise. Every scalar categorical column (`proposal_id`, `user_id`,
`composition_id`, `demand_kpis_placeholder`) accepts a value list — always
OR, since a proposal has exactly one value. `countries`/`stop_ids`
(`TEXT[]` columns — a proposal can carry several) accept either a plain
list (`mode: "any"`, OR/overlap `&&` — the default) or `{"values": [...],
"mode": "all"}` (AND/containment `@>`). `name` accepts a case-insensitive
substring. Every filterable column is sortable, plus `route_fingerprint`.
The example below is not exhaustive — it shows one filter of each kind:

```jsonc
{
  "filter": {
    "sources":         ["proposal", "existing"],       // default ["proposal"]
    "proposal_ids":    [int, ...],
    "user_ids":        [int, ...],                     // e.g. "my proposals"
    "countries":       [str, ...],                     // or {"values": [...], "mode": "any"|"all"}
    "stop_ids":        [str, ...],                     // or {"values": [...], "mode": "any"|"all"}
    "composition_ids": [str, ...],
    "name":            "brenner",                      // substring, case-insensitive
    "total_distance_km":   {"min": 800, "max": 1500},
    "total_time_h":        {"min": 8,   "max": 14},
    "avg_speed_kmh":       {"min": 70},
    "n_stops":             {"max": 12},
    "margin_eur_per_train_km": {"min": 0},             // any KPI column likewise
    "subsidy_eur_per_year":    {"max": 5000000},
    "likes_count":              {"min": 1},
    "created_at":               {"min": "2026-01-01T00:00:00+00:00"},
    "updated_at":               {"min": "2026-01-01T00:00:00+00:00"},

    "trip_windows": [                                  // timetable filter, see below
      {"stop_id": "OSM-...-berlin-hbf", "departure": {"from": "20:00", "to": "23:00"}},
      {"stop_id": "OSM-...-roma-ti",    "arrival":   {"from": "07:00", "to": "09:30", "day_offset": 1}}
    ],

    "bbox": [w, s, e, n]                               // optional, see below
  },
  "sort":    [{"by": <any filterable column>, "dir": "asc"|"desc"}],
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
  carrying `source: "proposal" | "existing"` and `likes_count`. ONTD rows
  have KPI fields null and no user/engagement metadata.
- `map_lines`: GeoJSON FeatureCollection, one feature per distinct
  stop-pair **corridor** (direction-agnostic — outbound and return share a
  corridor) rather than one per proposal, so a client can drive line
  *thickness* off `proposal_count` and look up which proposals share a
  corridor via `proposal_ids`; `avg_margin_eur_per_train_km` is the mean
  across exactly those proposals, for optional colouring — filtered but
  **not** paginated (the map shows the whole filtered set).
- `map_stop_counts`: `[{stop_id, lat, lon, n}]` — routes touching each stop
  (unnest over `stop_ids`, coordinates joined from the stop catalog).
- `map_country_counts`: GeoJSON FeatureCollection, one feature per country
  touched by the filtered set, carrying both the proposal count and the
  country's own border geometry (`input_params.countries.country_geom`) so
  the frontend doesn't need a second lookup for the choropleth
  ("which countries have no proposals yet") — `geometry: null` for a
  country code with no matched border (e.g. `"UNK"`, an unattributed
  segment).

`GET /api/proposals` stays as the empty-filter, summaries-only
convenience.

### 7.2 `GET /api/proposal/<id>` — load

- performs the on-load version-refresh fallback (§4.2), so a load always
  returns the current-base, current-version state
- returns exactly the compute-response shape (§2.1) — reconstructed route
  dict, evaluation with `input.parameters` rebuilt via the scenario pin,
  route appearing once — plus proposal metadata (id, owner, name, versions,
  timestamps)

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
`published: false`, no ownership questions. Any override key present
routes the side through the compute path, even if its value equals the
stored one (deterministic, no equality special-casing). Every side's
anchor runs the on-load refresh (§4.2) first — for override sides this
matters just as much as for stored ones, since they replay the anchor's
stored `compute_request`, whose `scenario_id` only reliably means
"current base" after the refresh has run.

Response per side: full compute-response shape, plus a **summary block on
both side kinds** — the stored side's gallery row (likes included), the
computed side's built on the fly by the same projection publish runs
(geometry and DB-only fields omitted) — so the compare view diffs the
same headline KPIs the gallery shows, whichever kind the side is. Plus a
`diff` section, **side B minus side A** throughout: per-KPI `{a, b, abs,
rel}` deltas over the gallery-KPI columns, and a generic structured diff
over the shared `views` trees (same view keys → per-leaf deltas across
every cost category and normalisation; keys present on only one side are
collected as paths under `views_unmatched` rather than half-diffed), so
the compare view can show *which* cost component moved; plus route
context via the fingerprints (identical route or not, which resolved
request fields differ). Ephemeral sides share the compute latency of the
editor on a cache miss — the UI needs a loading state.

Two sides for now; the shape allows more later. Bundle-level analysis —
each side a **set** of proposals — is not a compare extension but its
own endpoint, `POST /api/proposals/analyze` (§7.7, WP15): compare stays
the per-pair deep dive the analyze view drills down into.

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

### 7.7 `POST /api/proposals/analyze` — bundle analysis (designed 2026-08-04, WP15)

Compare (§7.3) answers "line vs line". Analyze answers the network-level
question — "what does this **set** of proposals cost/earn/save under
scenario X, and how does that change under scenario Y" — which is the
advocacy question the tool ultimately exists for. It is a **distinct
endpoint**, deliberately KPI-level: analyze returns bundle and member
*summaries* plus one aggregated cost tree per side; the full per-pair
deep dive (complete `views` diff, routes, geometries) stays on
`/compare`, which the frontend drills down into from an analyze row.
Compare's contract is unaffected.

**Sides.** One or two. One side = "calculate this bundle" (no diff
section); two sides = bundle comparison, diff = **side B minus side A**,
same as compare. Each side:

```jsonc
{
  "sides": [
    {
      "scenario_id": 4,                 // optional — fixed for ALL members of the side
      "composition_id": "REF-BAL-9",    // optional side-level override, applies to every member
      "proposals": [                     // explicit member list …
        {"proposal_id": 12},
        {"proposal_id": 17, "composition_id": "REF-BUD-6"}   // member-level wins over side-level
      ]
      // … XOR a filter-defined side:
      // "filter": {"user_ids": [7]}    // any §7.1 filter shape ("all proposals by user 7")
    },
    { ... }                              // optional side B
  ],
  "parameters": {
    "subsidy_pooling": "per_line",       // "per_line" (default) | "pooled" — see below
    "detail": "summaries"                // "summaries" (default) | "full"
  }
}
```

Scenario is a **side-level** property only — one policy world per side,
never per member. Composition may vary per member (a network is not
homogeneous rolling stock); member-level `composition_id` overrides the
side-level one. Member resolution is exactly §7.3's: any effective
override → ephemeral compute (`published: false`, never persisted,
through the compute cache §2.3), none → stored load; every anchor runs
the §4.2 on-load refresh first. Compare is the degenerate case of one
member per side — internally both endpoints share one member-resolution
code path.

**Filter-defined sides** are resolved **once at submission** through the
ordinary gallery machinery (`filter_builder`) into an explicit member
list — snapshot semantics: proposals published after job submission
don't join a running job. Member-level overrides are unavailable on a
filter side (there is no member to address); side-level
`scenario_id`/`composition_id` still apply to every resolved member. An
empty resolution is a 422.

**Bundle constraints.** Duplicate `proposal_id` within one side is
rejected (400) — it would double-count a corridor and break member
pairing; "one corridor, two service variants in one network" is a
deferred member-key concept, not v1. Bundle size is capped by server
configuration (`ANALYZE_MAX_BUNDLE_SIZE`, default **12**, applied after
filter resolution — 422 with the count when exceeded, telling the caller
to narrow).

**ONTD is excluded from both compare and analyze** — a political
decision (2026-08-04): existing-network rows are gallery/map context
(§5.5, WP10), never a compare/analyze side, even after WP10 lands.

**Aggregation semantics** — the part naive summation gets wrong:

- **Extensive quantities sum** across members: every `per_year` leaf of
  the route view (cost categories, revenue, net), annual train-km,
  demand trips / trip-km, CO2 savings. Each side carries one
  **aggregated route-view cost tree**: the `per_year` normalisation
  summed leaf-wise across members.
- **Intensive quantities are re-derived, never averaged**: every
  `per_train_km` leaf of the aggregated tree = the summed `per_year`
  leaf / Σ annual train-km; likewise the bundle's
  cost/revenue/margin-per-train-km headline KPIs and
  `subsidy_eur_per_t_co2`. Σ annual train-km is derived per member at
  analyze time from the route dict via the existing model constants
  (operating days × season weeks × distances) — never back-derived from
  rounded KPI ratios.
- **Sets union**: `countries`; `n_stops` = **distinct** stations served
  (network reach). `avg_speed_kmh` = Σ distance / Σ time (a
  train-km-weighted network speed — defined, not averaged).
- `total_distance_km` = Σ member route-km, with a documented caveat that
  overlapping corridors double-count; *distinct corridor km* via the
  WP6.1 `map_lines` machinery is a noted v2 candidate, not v1.

**Subsidy pooling is a request parameter** (default `per_line`):
`per_line` = Σ per-member `max(0, -net)` (each line subsidized
individually — the per-route PSO-contract world); `pooled` =
`max(0, -Σ net)` (profitable lines cross-subsidize within the network —
the one-network-operator world). The response echoes the mode used. The
gap between the two numbers is itself an advocacy argument; a caller
wanting both runs the cheap second request (cache-hit for every member).

**Async job pattern.** An override side is one live compute **per
member** — two sides × 12 members can be tens of computes, minutes not
seconds. Analyze is therefore a **job**, not a synchronous call:

- `POST /api/proposals/analyze` → validates, resolves filter sides,
  canonicalizes + hashes the request. `202 {job_id, status}`. Submission
  is `@require_auth` (guest floor — jobs need an identity to rate-limit
  against) and **strictly rate-limited** per user (exact quota at
  implementation; fresh job starts count, dedup/cache returns don't).
- **Dedup/result cache**: a submission whose canonical hash matches a
  queued/running job, or a completed one that is still current (same
  code versions, same base scenario, within TTL), returns that existing
  `job_id` — idempotent start, results cached.
- `GET /api/proposals/analyze/<job_id>` →
  `{status: queued|running|done|failed, progress: {members_done,
  members_total}, result?, error?}`. Progress advances per member
  computed. `job_id` is an unguessable UUID; GET is unauthenticated
  (capability URL — the underlying data is public anyway).
- Storage: `proposals.analyze_jobs`, `UNLOGGED` + TTL janitor — same
  ephemeral-and-recomputable reasoning as the compute cache (§2.3).
  `JSON` not `JSONB` for the stored result (key order, established
  convention).
- v1 executor: one in-process background worker, FIFO queue, one job at
  a time — matches the self-hosted process model; a real queue
  (RQ/Celery) is the documented escalation path, not v1. Each member
  compute goes through `compute_proposal()`, so WP13's cache does the
  heavy lifting for the dominant workflow (toggling scenarios over the
  same bundle). **WP13 is a hard prerequisite; WP14 (pooling/worker
  concurrency) helps but doesn't gate.**

**Response (`result`).** Per side: `bundle_summary` (`n_proposals`,
`total_distance_km`, `annual_train_km`, distinct `n_stops`, `countries`,
weighted `avg_speed_kmh`, derived cost/revenue/margin per train-km,
subsidy per chosen pooling + mode echo, summed demand/CO2 KPIs,
`subsidy_eur_per_t_co2`), per-member §5.4-shaped summaries (`published`
flags, `overrides` echo — compare's member shape), and the aggregated
route-view cost tree (`per_year` summed, `per_train_km` derived). With
two sides additionally `diff`: bundle-summary deltas and aggregated-tree
deltas in compare's `{a, b, abs, rel}` leaf shape, plus **member-level
summary diffs paired by anchor `proposal_id`** (same anchor both sides =
paired, regardless of overrides) with unpaired members listed under
`members_unmatched: {a_only, b_only}` — §7.3's `views_unmatched`
symmetry, so "same network, two scenarios" gets full per-line deltas and
heterogeneous bundles degrade gracefully to aggregate-only.
`detail: "full"` additionally embeds each member's complete
compute-response shape (route + evaluation) — a large payload, tolerable
because results are fetched once from a finished job, but `summaries`
stays the default.

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
| GHG g/pax-km by mode (night train + air/car references) | flat per-mode factors in `models/emissions` (single source — also replaces the projection's former placeholder CO2 constants); the proposal night-train value is the flat factor until an energy-based, country-resolved model enriches it (energy_kwh per segment × country grid intensity ÷ sold places). ONTD rows carry their own per-route value from `ontd.trips.co2_per_km` | available now (flat) |

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
10. Every stored proposal is a gallery item, always representing the
    current base scenario — kept that way entirely by the system (see 11),
    with no client-visible staleness flag (WP7/8 revision: an earlier
    `scenario_outdated` field was removed as unneeded).
11. Version bumps and base moves are handled by the system (batch refresh +
    on-load fallback), logged in `update_log`.
12. Subsidy = gap to target margin (`max(0, -net_eur)`).
13. Fingerprint identity = resolved stop lists + geometries + exact trip
    schedules; request settings are state.
14. ONTD stays in its own schema; union at API level with explicit `source`
    marking and no **financial or demand** KPIs for existing routes
    (amended by 23 — descriptive + emission KPIs are shown).
15. Demand-dependent KPIs faked with an explicit placeholder flag until the
    demand model exists.
16. Compare takes one proposal anchor per side; overridden sides are
    computed ephemerally (cache-backed), never persisted.
17. No delete API, no guest-hygiene job.
18. **Analyze is a distinct, KPI-level endpoint** (§7.7): bundle +
    member summaries and one aggregated cost tree per side; the per-pair
    deep dive stays on compare. One or two sides; scenario is side-level
    only, composition may vary per member; sides are explicit lists XOR
    §7.1 filters (resolved once at submission).
19. **Bundle aggregation**: extensive quantities sum, intensive
    quantities are re-derived from Σ annual train-km (never averaged),
    sets union; member pairing for diffs by anchor `proposal_id`, with
    `members_unmatched`; duplicate anchors within a side rejected;
    bundle size capped by configuration (default 12).
20. **Subsidy pooling is a request parameter** — `per_line` (default,
    Σ per-member gaps) vs `pooled` (`max(0, -Σ net)`); the response
    echoes the mode.
21. **Analyze is an async job**: `202` + progress polling + cached,
    deduplicated results (`UNLOGGED` jobs table, TTL); submission is
    authenticated and strictly rate-limited; WP13 (compute cache) is a
    hard prerequisite.
22. **ONTD is excluded from compare and analyze** (political decision,
    2026-08-04) — existing routes are gallery/map context only, even
    after WP10.
23. **Existing routes carry a reduced, descriptive KPI set** (WP10,
    2026-08-04): composition (where curated), duration, distance,
    average speed, and GHG g/pax-km by mode — never financial, demand,
    or engagement values.
24. **Mode emission factors are flat g/pax-km constants in
    `models/emissions`** — the single source for night-train, air, and
    car values, replacing the projection's placeholder CO2 constants.
    The proposal night-train value uses the flat factor until an
    energy-based, country-resolved model enriches it. Factors migrate
    into a params table with the WP16 schema split, not before.
25. **ONTD geometry is routed at import time** (OpenRailRouting).
    Revised 2026-08-05: **`fullRouting`**, not `simpleRouting` — the
    same custom model, speed cap and HSR avoidance the live tool uses,
    because existing routes share the gallery map with proposals and
    must obey identical routing rules. Straight-line fallback per route
    on routing failure, flagged in the summary row.
27. **Router output serves geometry only in the gallery** (2026-08-05):
    every existing-route KPI comes from ONTD itself, for a uniform
    appearance alongside proposals. The router's *times* are retained
    separately in `ontd.route_legs` purely as calibration input — never
    surfaced as a KPI, since an uncalibrated "router says 11.2 h,
    timetable says 12.8 h" pair invites questions the model cannot yet
    answer.
26. **ONTD imports read the Google Sheets directly** via the public
    whole-workbook export link (`export?format=xlsx`, no API
    key/credentials — both sheets link-shared "Viewer") for
    traceability; the compositions workbook is imported once, then
    the DB's curated tables are source of truth. Curated tables are
    excluded from the refresh TRUNCATE and use soft references across
    the lifecycle boundary; the loader reports orphaned route
    assignments after each refresh.

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
range/list/substring filters over all summary columns, `trip_windows`
stop-time filter (GTFS overnight-time convention), sorting, windowed
count, `include` sections; `bbox` optional/deferrable. *Testable by*:
endpoint tests over seeded published proposals per filter class.

**WP7 — Load endpoint completion** *(after WP5, parallel to WP6; small)*
✅ *implemented 2026-08-04, combined with WP8.* Extends WP5's minimal load
to the full §7.2 contract: proposal metadata block (id, owner, name,
versions, timestamps — including a genuine `created_at` on publish
responses, previously missing), response-contract tests against the §2.1
shape. *Testable by*: contract tests on published fixtures.

**WP8 — Version-refresh mechanism** *(after WP5, parallel to WP6/7)*
✅ *implemented 2026-08-04, combined with WP7 — see §14 "WP7/WP8
implementation notes" below (not to be confused with the WP14 work
package above, a different numbering scheme).*
`backend/scripts/refresh_proposals.py` (batch: outdated versions +
non-current-base scenario pins, recompute + re-base in place, owner kept,
`update_log` 'recalculated', idempotent, dry-run, concurrent compute step)
+ the on-load refresh fallback in WP7's endpoint. *Testable by*: publish
under current base → move base scenario in test fixtures → batch run
assertions (re-based scenario_id, update_log rows, summary refresh);
on-load fallback test.

**WP9 — Compare endpoint** *(after WP7, uses WP8's on-load refresh)* ✅
*implemented 2026-08-04 — see §15 "WP9 implementation notes" below.*
`POST /api/proposals/compare`: per-side resolution (stored vs override →
ephemeral compute through the cache), full sides + KPI deltas + structured
`views` diff + fingerprint-based route context. *Testable by*: two
published fixtures + override sides; `published: false` marking; diff
assertions.

*Open follow-up (found 2026-08-05, deferred to a WP9 follow-up):* the
`views` diff matches dict keys verbatim, but published trip ids carry
the `P{proposal_id}_V{version}_` prefix — so the pair-keyed data dicts
(`per_trip_pair`, `..._per_country`, `..._per_od`, `..._per_section`,
`per_trip_per_stop`) can never match between two different proposals.
Their cells fall out into `views_unmatched` on both sides and only the
`"all"` entry is actually diffed; harmless on a single-pair route, silently
lossy on a multi-pair one. Fix: strip the prefix on both sides before
diffing (the same `rewrite_id_prefix()` the calc response already uses) —
the fingerprint proves the trips correspond.

**WP10 — ONTD integration** *(after WP6; independent of WP7–9;
scope expanded 2026-08-04 — see §5.5, decisions 23–26)*
(a) Schema: curated composition tables (`ontd.coachtypes`,
`coachtype_classes`, `compositions`, `composition_coaches`,
`route_compositions`), extended `ontd.route_summaries`, and
`proposal_summaries.co2_g_per_pax_km`.
(b) `models/emissions`: flat per-mode g/pax-km factors (sourced
constants), wired into calc response, projection, and the former
placeholder CO2 constants' call sites.
(c0) **ONTD is seed data, not a manual chore** (corrected 2026-08-05):
`db/ontd/bootstrap.py` runs the three loaders in order from the API
container's entrypoint, right after `seed.py`. Guarded on
`ontd.route_summaries` being empty so restarts are free; soft-failing so
a Drive outage or unready router cannot keep the API down;
`ONTD_BOOTSTRAP=auto|force|off`. Started in the background so the API is up in seconds, with routing inside the projection run concurrently (`ONTD_ROUTING_WORKERS`, default 8 — routes are independent HTTP round-trips, and the DB writes stay single-threaded afterwards so transaction semantics are unchanged). On an existing server database the same command is the migration step. The deploy stacks' Postgres init-script
mount of `create_ontd_schema.sql` was removed — `loader.py` applies that
DDL itself, so the mount was a second owner of the same file.
(c) `db/ontd/loader.py` rework: public whole-workbook export-link source
(no credentials; + `--xlsx` /
`--local` fallbacks), sheet-artifact handling, TRUNCATE set excluding
curated tables, orphaned-assignment report.
(d) One-time composition importer
(`db/ontd/composition_loader.py`) from the target-network workbook,
incl. wide-slot unpivot and dangling-coachtype handling. ✅ Imports 26
coach classes, 163 coach types (208 class rows), 130 compositions (885
coach slots) and 151 route assignments — the workbook's other 216
assignments are target-network routes with no ONTD counterpart and are
skipped by design. Two source gaps reported, not silently absorbed:
class `Sleeper (2-berth)` is used but undefined (stored anyway — soft
reference), coach type `WLABmz (MÁV-START)` is referenced by a
composition but undefined (slot skipped — real FK).
Workbook read/coercion shared with `db/ontd/loader.py` via
`db/ontd/xlsx_utils.py`. Source is the Drive-hosted workbook
(`drive.usercontent.google.com/download`), *not* the Sheets export
endpoint: it was uploaded as a binary .xlsx rather than converted to a
native sheet, so its values are frozen at upload — acceptable because
this import runs once and the file doubles as the archival record of
what was imported.
(e) Projection builder: `route_summaries` rebuild after every load,
incl. routed geometry (`simpleRouting`, straight-line fallback). ✅
`db/ontd/projection.py`, invoked at the end of `db/ontd/loader.py` and
runnable standalone (`--no-geometry` for a metadata-only rebuild).
Geometry uses the same `RailRouter.route()` path as the live tool —
**`fullRouting`**, custom model, speed cap and HSR avoidance (decision
25 revised 2026-08-05). Existing routes and proposals share one gallery
map, so routing them by different rules would draw the same physical
night train on different tracks depending on which table it came from.
Only the shape is kept; the per-leg physics is discarded, since existing
routes are never evaluated (decision 23). The ONTD catalog carries no
speed/HSR data of its own (`ontd.compositions` is descriptive — places
and weight), so one reference composition stands in for every existing
route; `route()` reads only `max_speed_kmh` and `hsr_allowed` off it.
That reference is **resolved from the live catalog at runtime**, not
hardcoded: composition ids are a calibration output and do rot — the id
still used across `api/README.md` and the `scripts/` comparison tools
(`STD-7.1`) had already been dropped from the catalog by the time this
ran. `ROUTING_MATERIAL_STRATEGY = "refurbished"` picks the family that
matches what existing night trains actually run, taking the first such
composition by id (deterministic, so successive rebuilds stay
comparable); `--composition-id` overrides. Infrastructure comes from the
`is_current_base` scenario at its pinned `track_infra_version`, so
per-country `hsr_allowed` binds on both the composition and the track
side — including countries a route only transits. `route_legs` is
therefore only valid against that version; a base-scenario version move
means rebuilding before recalibrating (risk accepted, 2026-08-05). Simplified with the same
Douglas-Peucker tolerance as the proposal projection — both feed one
map. This reintroduces a params-DB dependency (tracks, compositions,
country index) that geometry-only routing avoided; the straight-line
fallback covers an unseeded or unreachable environment.
Two PK fixes came out of the first real load (2026-08-04): the schema
had never met data before, and `calendar_dates PRIMARY KEY (service_id,
date)` rejected 40 of 59 rows (PK columns are implicitly NOT NULL, but
the sheet legitimately carries `date_from`/`date_until` period
exceptions with `date` empty) while `translations`' PK on the
`#REF!`-broken `record_id` rejected 75 of 91. Both now use surrogate
keys. `translations.record_id` still needs fixing at source before those
rows can join back to `ontd.stops`.
(f) `POST /api/proposal/calc` gains an emissions section (CALC_VERSION
bump); projection writes `co2_g_per_pax_km`; compare KPI deltas
extended (proposal sides only — decision 22 unchanged). ✅ *implemented
2026-08-05 (step 5, CALC_VERSION 0.9.11):* `models/emissions/factors.py`
is the single source (decision 24; EEA TERM 2020 EU-average 2018:
night train 33 / air 160 / car 143 g CO2e/pax-km, sourced per mode) and
also hosts the placeholder `MODE_SHIFT_SHARES` (§8.1 — moves to
`models/demand/` with the real model). The §5.4 KPI derivation
(`build_summary_row()` + helpers) moved from
`adapters/proposal/projection.py` to `models/evaluation/summary.py` so
the calc response, the compare sides, and the publish path share one
function without `api/helpers/` importing from `adapters/`; the
projection keeps `route_fingerprint()` and the DB-shaped
`build_summary_db_row()` (= shared row + `geom_simplified`). The calc
response gains a `summary` block (between `suggested_stops` and `route`)
carrying the full proposal gallery KPI set — deliberately **without**
`geom_simplified` (the response already carries full per-segment
geometry) — and `evaluation.models` gains an `emissions` entry
(`factors` instead of `formulas`: sourced constants, the per-mode
reference values for the gallery's mode comparison). Gallery summary
rows, the compare summaries, and `SUMMARY_KPI_FIELDS` carry
`co2_g_per_pax_km`. Placeholder `co2_savings_t_per_year` values shift:
sourced factors replace the former unsourced ones (air 200/car 70), and
savings now subtract the night train's own emissions per shifted km.

(g) Gallery union groundwork ✅ *implemented 2026-08-05 (step 6a — ONTD
side; the union queries themselves are step 6b):* **Interim stop-id
bridge** — `ontd.stop_mappings` (CURATED lifecycle, like
route_compositions) maps every active-route ONTD stop to a Target
Network id, built automatically by `db/ontd/stop_mapping.py` on each
projection run: coordinate match (≤500 m) against the current base
scenario's pinned `stop_infrastructures` snapshot first, else a new stop
is MINTED into that snapshot (curated-style transliteration Ü→UE/ø→OE
→ `{CC}_{NAME}`, `stop_charge_eur` NULL → country/global default,
provenance in `change_log`) and becomes an ordinary plannable catalog
stop. `match_method='manual'`/`verified` rows are never overwritten —
the table doubles as the seed of the harmonization deliverable
(Giovanni ↔ David alignment task) and is replaced wholesale by the
OSM-id stop list (~2 weeks out). Unmapped (documented gap): stops
without coordinates or in countries outside `input_params.countries`
(NOT NULL FK) — those keep raw ONTD ids. `route_summaries.stop_ids` now
stores TN ids. **Corridor pieces** (decision B, option 3) — new
refreshed `ontd.route_corridors`: per consecutive stop pair of each
active route, that leg's own router geometry (straight-line fallback
included), TN ids, direction-collapsed — the exact grain the proposal
side aggregates `proposals.segments` into, so existing trains and
proposals thicken shared corridors on one map layer. **Dev bootstrap** —
seed.py creates the (empty) ontd schema when absent, guarded against
re-application (the DDL drops refreshed tables), so step 6b's union has
tables to query in every environment. `test_02`'s stop count became a
minimum (minting legitimately grows the pinned snapshot). Step 6b
decisions locked: `sources` DEFAULTS TO BOTH (revises §7.1's
`["proposal"]` default — no working gallery frontend yet, Bjarne adapts
once there), timestamps NULL on existing rows with `NULLS LAST`
ordering, financial/demand filters exclude existing rows via SQL NULL
semantics.

**Step 6a-fix** ✅ *implemented 2026-08-06, before step 6b started —
fallout from testing step 6a against real data (517 minted stops,
574-row catalog vs the 58-row seed everything before this had been
tested against):*

- **Auto-stop-addition costing made analytic** (`ROUTE_BUILDER_VERSION`
  0.9.15, `models/route/timetable.py`/`version.py`). The 10x catalog
  growth turned `auto_stop_addition="add"`'s candidate costing into the
  dominant cost of planning a route: candidates went from ~1 to ~11 on a
  3-stop Berlin–Wien request, and each was priced with a real 3-point
  router mini-reroute (~1.5s), pushing one `test_20_route_content.py`
  class from 5s to 48s. A first fix (0.9.14, since reverted) batched
  candidates into fewer multi-stop router calls; measurement showed the
  batch partition degenerating to one full-trip call per candidate on
  few-stop requests (13-19s per costing pass, worse than before) — and
  that every accepted candidate's routed cost resolved to essentially
  dwell + the dynamics model's own accel/brake pair, i.e. the router
  re-measuring what the model already knew. 0.9.15 costs analytically
  instead: `dwell_min()` + `routing/dynamics.py`'s `stop_time_loss_s()`
  at the host leg's cruise speed + an out-and-back detour term — zero
  router calls — for candidates within the new `AUTO_STOP_ANALYTIC_DETOUR_M`
  (100m) of the routed geometry, or already over the trip's detour
  budget on that analytic lower bound (mode "add" could never accept
  them regardless, so routing them for precision buys nothing). Only
  genuinely off-path candidates get a real mini-reroute. `AUTO_STOP_BUFFER_M`
  widened 3km→10km alongside it, since a real (curated, post-calibration)
  stop catalog will include stations the initial routing bypasses on
  parallel/bypass tracks — the search needs the wider net once costing
  no longer scales with candidate count. Net effect on the same
  benchmark: 48s → 18s (remaining time is real routing — initial route +
  final reroute — not costing). **Behavioural consequences, not just
  performance:** on-path candidate times are model-derived estimates
  rather than router measurements (identical to the model's own
  precision elsewhere); `auto_stop_addition="suggest"` no longer
  guarantees the same stop set as "add" — suggest ignores the detour
  budget by design, so at the wider buffer it surfaces strictly more
  candidates than "add" actually inserts (a subset relation, not
  equality — `test_20_route_content.py` re-pinned accordingly, both
  docstring and assertion). auto-add selection became measurably
  composition-dependent (heavier trains cost every candidate more via
  the mass-dependent accel/brake term, so afford fewer marginal stops
  within the same 5% budget) — three route-invariance tests
  (`test_distance_independent_of_composition`,
  `test_energy_independent_of_composition`, and implicitly the gallery
  corridor-sharing test) had to pin `auto_stop_addition="off"` to
  isolate the routing/energy-model property they actually test from the
  now-legitimately-divergent selection layer above it.
- **Minting fixed to preserve the full-table-snapshot invariant**
  (`db/ontd/stop_mapping.py`) — minted stops previously landed only in
  the base scenario's pinned `stop_infra_version`, silently breaking
  §3.1's guarantee that every version holds an identical stop set (the
  historical/HSR snapshots stayed at 58 stops while base grew to 575).
  Now inserted into every existing version. Caught by
  `test_02_db_seed.py`'s
  `test_stop_infrastructure_values_unchanged_by_hsr_scenario` — the
  first time that test ran against post-minting data.
- **Transliteration extended to Cyrillic and Greek**
  (`db/ontd/stop_mapping.py`) — the Latin-diacritic-only table minted
  ids like `BG_ПОДУЯНЕ` verbatim for Bulgarian/Greek station names
  instead of folding them into the curated Latin namespace; found via a
  live-data run (562 coordinate-matched, 0 minted — the mapping was
  stable, but a stale earlier partial run's Cyrillic-id row surfaced
  the gap on inspection).
- **Per-field default-resolution logging demoted WARNING→DEBUG**
  (`adapters/data_loader_from_db.py`) — `StopInfrastructure[...].stop_charge_eur
  is None` and the equivalent `TrackInfrastructure[...]` line are the
  *expected* NULL-resolves-to-default path (§4, decision on
  provenance), not anomalies, but logging one WARNING per field per
  entity per catalog build meant ~800 lines per build once 517 stops
  had NULL charges by construction. This was the actual cause of a
  reported "everything got slower" — unrelated to routing or auto-stop
  costing at all: `test_10_params_api.py` (no routing, pure DB reads)
  dropped from tens of seconds to 0.31s once the log volume was cut.
  Aggregate counts moved to the existing per-build INFO summary lines
  (`Built 575 stops (562 charges resolved via defaults)`) instead of
  being lost. **Lesson for future large-catalog work:** per-entity
  logging inside a hot loop is invisible at seed scale (58 stops) and a
  measurable request-latency cost at real scale (575+) — worth an
  explicit check whenever a WARNING/INFO call sits inside a per-row loop
  before the next data volume jump (stop calibration, full compositions
  import).
(g) `sources` filter + union in `POST /api/proposals`; `source`
marking + `"existing"` summary row shape; ONTD rows in the map
sections. ✅ *implemented 2026-08-06 (step 6b):* one `gallery` UNION
CTE (repository.py) over `proposal_summaries_with_likes` and
`ontd.route_summaries`, compiled from only the requested
`filter.sources` branch(es) — a `["proposal"]` request produces exactly
the pre-6b plan and never touches the ontd schema. Existing rows carry
NULL in every proposal-only column, which is the entire integration
mechanism: every generic filter_builder fragment works unchanged
(financial/likes/timestamp filters exclude existing rows via SQL NULL
semantics per the locked decision; trip_windows' EXISTS is never true
for a NULL proposal_id; bbox works because both `geom_simplified`
columns are the same PostGIS type), and `build_order_by()` appends
`NULLS LAST` everywhere so the default newest-first keeps the existing
catalog after every proposal instead of Postgres's DESC-NULLS-FIRST
floating it on top. Existing summary rows serialize as the reduced
descriptive shape (route_id, name, ontd composition_id, shared metrics,
`geometry_routed`, `ontd_url`) with proposal-only keys OMITTED, not
null-padded. Map sections merged at their natural grains — corridors
via `ontd.route_corridors` (built at the segment grain for exactly
this), stops/countries via unnest over the union — and **every map
section always carries the per-source split AND the total** (decision
2026-08-06): `proposal_count`/`existing_count`/`total_count` +
`proposal_ids`/`existing_route_ids` per corridor feature,
`n_proposals`/`n_existing`/`n` per stop and per country. Corridor
`avg_margin` stays proposals-only (NULL when only existing trains serve
it); corridor geometry prefers a proposal shape, falls back to the
existing corridor's own. Namespace notes carried into api/README.md
§7.1: `stop_ids` is shared (step 6a), `composition_id` is NOT (curated
vs ontd ids — a filter matches literally across both). test_52 gained a
committed-fixture pair of fake existing routes (CI's ontd schema is
empty — seed.py only creates it) plus a TestSourceUnion class; the
pre-existing test_52 assertions were audited against the new BOTH
default and survive because every exact-shape assertion sits behind an
identity filter that NULL-excludes existing rows.
(h) Last step: audit `GET /api/params/compositions` against the new
ontd composition tables (naming/shape drift) and restructure
`api/README.md` (especially the first table).
*Testable by*: seeded ONTD rows in gallery/map with the descriptive KPI
set; `sources` filter combinations; emission KPIs on
calc/publish/summary/compare; `"existing"` still rejected by
compare/analyze.

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
filters, `trip_windows`, sections); compare
(`published: false` sides need a loading state) and timeline endpoints;
`source`, `demand_kpis_placeholder`, `cache_hit` fields;
reconstructed-response note (byte-identity not guaranteed, structure
identical). From WP10: the `sources` filter goes live, summary rows come
in two shapes (`source: "proposal"` vs the reduced `"existing"` shape,
§5.5), and emission fields land on the calc response, summary rows, and
compare deltas (per-mode reference values included in the responses).
Audit `frontend/src/types/api.ts` end to end.

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

**WP14 — Connection pooling / intra-worker concurrency** *(independent;
worth doing once enough endpoints exist to make the tradeoff concrete —
parked during WP7/8, 2026-08-04)*
Scoped out of WP7/8 deliberately: those touch proposals specifically,
this touches the whole app. Today's production process model (`gunicorn
--workers 4`, `api/helpers/dependencies.py`'s `init()`) already gives
**inter**-process parallelism for free — every worker is a separate OS
process with its own `DBDataLoader`/`ProposalRepository`/etc. connection,
so N concurrent client requests landing on N different workers already
run fully in parallel with zero code changes; scaling `--workers` scales
this further, cheaply. What's missing is **intra**-worker concurrency: one
worker process handles exactly one request at a time (sync worker model),
so a slow live-routing `/calc` blocks a quick `/likes` toggle that happens
to land on the same worker. Closing that gap needs: (1) every singleton
in `dependencies.py` (`DBDataLoader`, `ProposalRepository`,
`ProposalEngagementRepository`, `FeedbackRepository`, `AuthRepository`)
switched from "one connection held for the process's life" to a
**connection pool** (borrow-per-request, return-after); (2) gunicorn's
worker class switched from sync to `gthread`/`gevent` so a process can
actually interleave requests while one is blocked on DB/HTTP I/O; (3) an
audit of every adapter's `_cursor()`/commit/rollback pattern for
pool-borrowed-connection correctness (today's `self._conn` assumption
throughout `adapters/*.py` no longer holds once a connection isn't
exclusively owned by one long-lived object). *Testable by*: concurrent
integration test issuing a slow `/calc` and a fast `/likes` simultaneously
against a single worker, asserting the fast one doesn't wait on the slow
one; connection-pool exhaustion behaviour under load.

**WP15 — Bundle analyze endpoint** *(designed 2026-08-04, §7.7 — parked;
after WP13 (hard prerequisite: every member compute rides the cache);
WP14 helps but doesn't gate; independent of WP10–11)*
`POST /api/proposals/analyze` + `GET /api/proposals/analyze/<job_id>`
per §7.7 and locked decisions 18–22. Deliverables: `proposals.
analyze_jobs` migration (`UNLOGGED`, TTL janitor alongside the compute
cache's); analyze blueprint + helpers **reusing compare's member
resolver** (one member-resolution/diff code path across §7.3/§7.7 —
refactor `api/helpers/proposal_compare.py`'s `resolve_side()` into the
shared member resolver rather than duplicating); an aggregation module
(extensive sums / derived intensives / set unions, incl. per-member
annual-train-km derivation from the route dict); filter-side resolution
via `filter_builder`; the in-process FIFO worker + progress writes;
auth + rate limit on submission; dedup/result caching by canonical
request hash; `ANALYZE_MAX_BUNDLE_SIZE` config (default 12);
`subsidy_pooling`/`detail` parameters. WP12 ledger: new frontend
contract (job submit/poll flow, progress UI, bundle vs member views,
drill-down into compare). *Testable by*: single-side bundle calculation
(aggregates verified against hand-summed member values, intensives
against Σ train-km, distinct-stop union); two-side diff with pairing +
`members_unmatched`; per_line vs pooled subsidy on a bundle containing
one profitable member; duplicate anchor → 400; cap → 422; filter side
snapshot semantics; job dedup on identical resubmission; progress
monotonicity; rate limit; ONTD exclusion.

**WP16 — input_params schema split** *(independent; noted 2026-08-04
during WP10 kickoff)*
Split the `input_params` schema along the `models/` package structure
(infrastructure, compositions, demand, emissions, …) so params tables
live next to their model domain. The flat mode emission factors migrate
from `models/emissions` constants into the emissions params schema at
that point (decision 24) — until then, constants are the single source.

---

## 11. Post-WP5 consolidation pass (2026-08-03) ✅

A dedicated cleanup PR between WP5 and WP6, resolving the inefficiencies
the "full suite green after every WP" premise deliberately accumulated
(code kept alive for mechanisms scheduled for later shutdown). No
behaviour change — response shapes, stored data, and all computed numbers
are identical; `ROUTE_BUILDER_VERSION` bumped to 0.9.13 solely for the CI
version-check contract (files under its watch were touched).

- **Adapters restructured**: proposal persistence grouped into the
  `adapters/proposal/` package — `repository.py`, `gtfs_store.py`
  (moved from `api/helpers/route_gtfs_serialize.py`: it executes SQL, so
  it belongs in adapters per "all DB access in adapters/"; this also
  removes the adapters→api/helpers inversion `projection.py`'s own
  docstring warned against), `projection.py`, `engagement_repository.py`,
  and the new `id_prefix.py` (`rewrite_id_prefix()`, shared by the /calc
  prefix strip and publish's prefix mint). Layering rule refined in
  `AGENTS.md`: adapters may import the Flask-free pure serializers from
  `api/helpers/`, never blueprint files or `dependencies.py`.
- **`models/demand/` created**: the stopgap demand model
  (`distribute_demand()`, its STOPGAP_* standard values, the
  `demand_model` TODO) moved out of `models/route/` into the package the
  real demand model will land in. `DEMAND_MODEL_VERSION` placeholder
  established on its own track.
- **Pipeline deduplicated**: `models/evaluation/views.py` gained
  `ViewsBundle` + `build_all_views()`; `models/pipeline.py` gained
  `evaluate_and_build_views()` (the post-routing half). The six-view
  assembly previously duplicated across the pipeline, `db/dev/seed.py`'s
  example proposal, and `tests/helpers.py` now has one implementation.
  `views_to_dict()` takes the bundle directly.
- **Validation relocated**: `validate_calc_body()` moved from the
  `api/proposal_calc.py` view module into
  `api/helpers/proposal_compute.py`, so `publish_dispatch.py` no longer
  imports from a blueprint file.
- **`RailRouter` is a startup singleton** (`dependencies.py`,
  `get_rail_router()`) — the per-request construction rebuilt a
  `requests.Session` + 64-connection pool on every compute, starting each
  request on a cold pool; `Session` is safe for concurrent use, so one
  warm shared instance strictly improves concurrency.
- **Dead code removed**: `route_factory.adjust_route()` (unreachable
  since the cutover, ~150 lines), `route_serialize.validate_route_dict()`,
  `parse_route_id()`, `ProposalRepository.get_user()` (the
  `FeedbackRepository` copy with the only caller survives),
  `tests/helpers.py`'s dict-based demand helpers
  (`inject_demand`/`directional_od`/`replicated_od`),
  `scripts/test_evaluation_calc.py` (tombstone) +
  `scripts/data/tc_1_evaluation_input.json`.
  `adapters/data_loader_from_spreadsheet.py` — retained at the time on
  the assumption it would become the ONTD import's basis, but removed
  during WP10 (2026-08-04): its premise (gspread + service-account auth,
  bit-rotted against `models/params.py`) was superseded by the simpler
  public-export-link mechanism decision 26 settled on, and it had no
  callers to preserve.
- **Tests renumbered** to close the cutover's deletion scars:
  `test_21_route_plan_content.py` → `test_20_route_content.py`,
  `test_31_evaluation_content.py` → `test_30_evaluation_content.py`.
- **Docs**: full stale-reference sweep (removed endpoints, moved modules)
  across all module docstrings and READMEs; `db/README.md`'s proposals
  section rewritten to the post-cutover storage model; `AGENTS.md` API
  surface/blueprint list/layering updated; `tests/README.md` gained the
  missing `test_37`/`test_70`/`test_71` sections.

---

## 12. WP6 implementation notes (2026-08-03) ✅

Delivers the full §7.1 contract on top of WP5-minimal's one-filter list.
No schema change — everything runs against the existing
`proposal_summaries` table and its GIN/GiST indexes (§5.4); `sources:
["existing"]` (the ONTD union) still 400s until WP10.

- **`adapters/proposal/filter_builder.py`** (new): the single column-kind
  registry (RANGE/LIST/ARRAY/SUBSTRING) driving both SQL generation
  (`build_where()`, `build_order_by()`) and structural validation, so a
  column's filter/sort behaviour is declared once. `trip_windows` is a
  correlated `EXISTS` over `proposals.trips`/`stop_times` (one join per
  window entry, all sharing `t.trip_id` so a single trip must satisfy
  every entry); the trip's owning proposal is resolved via the
  `P{proposal_id}_V{proposal_version}_R1` route_id convention rather than
  a stored link. `bbox` is `ST_Intersects` against `geom_simplified`
  (GiST-indexed) — implemented now rather than deferred, since the SQL is
  trivial once the filter builder exists.
- **`models/utils.py`** gained `min_to_interval()`, promoted out of
  `gtfs_store.py`'s previously-private copy — one HH:MM↔INTERVAL
  convention shared by the GTFS write path and the new `trip_windows`
  filter.
- **`adapters/proposal/repository.py`**: `list_summaries()` rewritten for
  the full filter/sort/pagination contract; three new methods —
  `map_lines()`, `map_stop_counts()` (joined to the *current base*
  scenario's pinned `stop_infrastructures` snapshot for coordinates),
  `map_country_counts()` — all sharing `filter_builder.build_where()` so
  every section reflects the same filtered set. `scenario_outdated`
  (§4.2) is a derived subquery against `scenario.scenarios WHERE
  is_current_base`, never stored, selected alongside every summary row.
- **`api/proposals.py`**: `POST /api/proposals` response is now
  **sectioned** — `include` (default `["summaries"]`) picks which of
  `summaries`/`map_lines`/`map_stop_counts`/`map_country_counts` the
  response carries, and only requested sections run their query. This
  replaces WP5-minimal's flat `{total, proposals}` envelope — a breaking
  response-shape change flagged for WP12's Bjarne-coordination batch
  (`frontend/src/types/api.ts` audit).
- **Tests**: `test_50_proposals_api.py`'s `TestList` updated for the new
  envelope; `test_52_proposals_gallery_api.py` (new) covers one filter of
  each kind, `trip_windows` match/no-match, `bbox` hit/miss, sort, the
  windowed `total`, every `include` section, and `scenario_outdated`
  (via a direct `proposal_summaries.scenario_id` mutation in the test —
  no production code path rewrites this column outside publish/refresh).
- **Docs**: `api/README.md`'s `GET`/`POST /api/proposals` section
  rewritten to the full §7.1 request/response shape.
- **Not yet done**: `scripts/test_proposals_gallery.py` (manual
  seed+demo script) exists but isn't yet part of the standard WP closing
  checklist — added ad hoc after WP6 landed, not audited against the
  "every WP updates its own script" convention the other WPs follow.

---

## 13. WP6.1 revision (2026-08-04) ✅

A round of feedback on WP6 landed as its own follow-up pass rather than
re-opening WP6 — the two live-tested findings (orphaned `proposal_summaries`
rows from `purge_saved_proposals()` never cleaning them up; the total
count this exposed) plus a design revision to `map_lines`, five filter
changes, and a new `likes_count` dimension. §7.1 and §5.4 above are
updated in place to the revised contract; this section is the changelog.

**Filter/sort changes**:
- `route_builder_version`/`calc_version`/`scenario_id` are **no longer
  filterable** — internal/analytical, and every gallery row is always on
  the current base scenario by construction (the `sources`/`scenario_id`
  discussion in §7.1 already covered why). Still plain summary fields.
- **`proposal_ids`** added (OR-only list, same shape as `user_ids`).
- **`created_at`/`updated_at`** range filters added — required adding
  `created_at` to `proposal_summaries` itself (§5.4), since §7.1's own
  "all filter/sort work runs against `proposal_summaries`" principle
  rules out joining `proposals.proposals.created_at` at query time
  instead. Migration: `db/dev/sql/migrations/
  2026-08-04_proposal_summaries_created_at.sql`, backfilled from
  `proposals.proposals.created_at` (not defaulted to `now()`).
  `adapters/proposal/repository.py`'s `_upsert_summary()` sets it once at
  INSERT and excludes it from the `ON CONFLICT` `UPDATE`, so an
  overwrite-publish doesn't reset it.
- **`countries`/`stop_ids` gained an any/all mode** — a plain list stays
  `mode: "any"` (OR, array overlap `&&`, the pre-revision behaviour);
  `{"values": [...], "mode": "all"}` is AND (containment `@>`). Every
  other list filter stays OR-only by construction (a proposal has
  exactly one `composition_id`/`user_id`/etc., so AND could never match).
- **`likes_count`** added as a range filter/sort — not a
  `proposal_summaries` column (a like changes independently of publish/
  refresh, so storing it would go stale the same way any cached count
  would); `adapters/proposal/repository.py` now builds every gallery/map
  query on top of a `proposal_summaries_with_likes` CTE (`proposal_
  summaries` LEFT JOIN a `proposals.likes` count-per-proposal subquery,
  `COALESCE`d to 0) instead of the bare table, so `filter_builder.py`'s
  generic `likes_count >= %s` resolves against a real column of the
  CTE's output — the same mechanism every other section (not just
  `summaries`) filters through, so a `likes_count` filter narrows
  `map_lines`/`map_stop_counts`/`map_country_counts` consistently too.

**`map_lines` redesign** — the original WP6 shape (one GeoJSON feature
per proposal, coloured by that proposal's own margin) didn't match the
actual use case: line *thickness* by how many proposals run along a
given physical corridor. Now one feature per distinct stop-pair corridor
(`stop_a`/`stop_b`, direction collapsed via `LEAST`/`GREATEST` — outbound
and return share a corridor), carrying `proposal_count` (thickness),
`proposal_ids` (the assignment), and `avg_margin_eur_per_train_km`
(mean across those proposals, for optional colouring). Grouping by stop
pair rather than by geometry match is exact, not approximate: routing
between two fixed stops is deterministic (same routing graph) regardless
of which proposal or composition asks, so two proposals sharing a
stop pair are guaranteed to share the exact geometry too. Implemented as
a walk over `proposals.trips`/`proposals.segments` per filtered proposal
(via the same `P{proposal_id}_V{proposal_version}_R1` route_id
convention `trip_windows` already uses), grouped, then joined to one
representative `proposals.shapes.geometry` per corridor (already stored
as GeoJSON — no `ST_AsGeoJSON` needed).

**`map_country_counts` gained geometry** — was `{country: n}`; is now a
GeoJSON FeatureCollection, one feature per country, `properties: {country,
n}` and `geometry` the country's own border polygon
(`input_params.countries.country_geom`, `LEFT JOIN`ed so an unmatched
code like `"UNK"` still gets a row with `geometry: null`) — the frontend
choropleth no longer needs a second lookup to render it.

**Bug fix (found while live-testing WP6, not a WP6 regression)**:
`tests/helpers.py`'s `purge_saved_proposals()` deleted
`proposals.proposals`/`routes`/`shapes`/`services`/`likes`/`comments` but
never `proposals.proposal_summaries` — which has no FK to
`proposals.proposals` (§5.4, deliberate: a derived, rebuildable
projection, not authoritative data), so nothing cascaded the cleanup.
Every pytest run that published-then-purged left orphaned summary rows
behind, invisible until WP6's `total` was the first thing to actually
count and surface them. Fixed in `purge_saved_proposals()`; `api/
README.md`'s manual-deletion note for `GET /api/proposal/<id>` corrected
to say the same applies to any manual production deletion.

**Tests**: `test_52_proposals_gallery_api.py` gained
`test_proposal_ids_filter`, `test_array_filter_any_vs_all_mode` (+ invalid-
mode rejection), `test_created_at_range_filter`, `test_updated_at_range_
filter`, `test_version_and_scenario_filters_no_longer_accepted`, and a new
`TestLikesCount` class (`likes_count` appears in `summaries`, is
filterable, is sortable); `test_map_lines_geojson`/`test_map_country_
counts` rewritten for the new shapes; a new `test_map_lines_thickness_
reflects_shared_corridor` publishes a second proposal on the identical
corridor and asserts both land on the same `map_lines` feature.

**Docs**: §7.1's filter/sort/response prose and JSON examples rewritten
in place (not just this changelog); §5.4's `CREATE TABLE` example gained
`created_at`; `api/README.md`'s section rewritten to match, including a
filterable/sortable column reference table; `db/README.md` gained a
changelog entry for the new migration.

---

## 14. WP7/WP8 implementation notes (2026-08-04) ✅

Combined into one pass — reviewing WP7's load-endpoint contract surfaced
that its one real gap (§4.2 staleness) only makes sense alongside the
mechanism that actually keeps proposals current, so WP8 was pulled
forward rather than done separately per §10's original split.

**Scope change, decided before implementation**: the original WP6/WP6.1
design surfaced a per-row `scenario_outdated` flag on gallery and load
responses. Reconsidered here — the system (batch refresh + on-load
fallback) keeps every proposal current on its own; nothing in the product
consumes a staleness signal (the batch script queries the DB directly,
never the API), so the flag had no reader. **Removed** rather than
extended to load: `adapters/proposal/repository.py`'s
`_SCENARIO_OUTDATED_EXPR`/`list_summaries()`, `adapters/proposal/
filter_builder.py`'s `SORTABLE_COLUMNS`, `api/helpers/proposal_
serialize.py`'s `summary_row_to_dict()`, `api/README.md`, and `scripts/
test_proposals_gallery.py` all lost the field; `tests/
test_52_proposals_gallery_api.py`'s `TestScenarioOutdated` removed.
§4.2/§6/§7.1/§7.2/§9 (locked decision 10) above are updated in place to
match — this section is the changelog, per the convention §13 set.

**WP7 — load endpoint**: the gap turned out smaller than scoped —
`GET /api/proposal/<id>` already returned the full metadata block (id,
owner, name, versions, timestamps) via the existing `proposal_meta_to_
dict()`. The one genuine defect: `publish()`'s response never carried
`created_at` (only `updated_at`) — `_insert_container()`/
`_update_container()` now `RETURNING created_at, updated_at` instead of
just the latter, so both callers' return dicts, and therefore both
publish and load responses, carry a real value. `tests/
test_50_proposals_api.py` gained a `TestLoad` class: a top-level key-set
contract test (mirroring `test_35`'s pattern) and a check that both
timestamp fields are well-formed on publish and load.

**WP8 — refresh mechanism** (§4.2): `adapters/proposal/repository.py`'s
`publish()` had its "write the state" middle section (prefix rewrite,
GTFS write, summary upsert) factored out into `_write_state()`, shared
with the new `refresh_proposal()` — the system-triggered counterpart with
no ownership check, owner/name kept as stored, `update_log` event
`'recalculated'` carrying a `detail` dict (`_write_update_log()` gained a
`detail` parameter for the primary event row, previously only available
on the `branched_*` pair). `outdated_trigger()` (module-level, pure — no
DB access) is the one staleness check both the batch script and the
on-load fallback run, checked in priority order (`route_builder_version`
→ `calc_version` → `base_scenario_moved`) since a recompute fixes all
three regardless of which fired; `list_outdated()` is the batch script's
SQL-level work queue; `get_container()` gained an internal (non-API)
`current_base_scenario_id` column so the on-load path can call
`outdated_trigger()` on the row it already fetched, no second query.
`flush_compute_cache()` TRUNCATEs the (still-empty, pre-WP13)
`compute_cache_pointer`/`_result` tables per §4.2's "first flushes the
compute cache" rule — a correct no-op today.

`api/proposals.py`'s `get_proposal()` runs the fallback inline: on a
trigger, it recomputes via `api/helpers/proposal_compute.py`'s
`compute_proposal()` (with `scenario_id` forced back to `None` so it
re-resolves against whatever base is current *now*, regardless of which
trigger fired — never replays the stored, possibly-stale, scenario_id),
calls `refresh_proposal()`, then re-fetches the container before building
the response (`refresh_proposal()`'s return dict is deliberately minimal,
mirroring `publish()`'s — it doesn't carry the extra fields
`proposal_to_response_dict()` needs).

`backend/scripts/refresh_proposals.py` (new): direct in-process, not
HTTP — a refresh has no owner/auth concept, the same reason `db/dev/
seed.py`'s example-proposal seed talks to `ProposalRepository` directly.
`--dry-run`/`--limit`/`--concurrency` flags; idempotent by construction
(`list_outdated()` re-derives the work queue fresh every run). Caught by
live testing, two rounds: (1) `main.py` never needs host-vs-container
env handling because it only ever runs inside the API container, where
Docker Compose's `env_file` already injects the right values; this
script, meant to also run standalone from the host (a real test run
surfaced this immediately), doesn't have that luxury. (2)
`backend/docker/.env` itself was the wrong fix for that — its
`POSTGRES_HOST=postgres`/`OPENRAILROUTING_URL=http://openrailrouting:8989`
are Docker Compose **network hostnames**, meaningless (and actively
wrong) from the host. `run()` instead sets the same host-side defaults
`tests/conftest.py`'s own `DB_CONFIG` already uses
(`POSTGRES_HOST=localhost` etc., via `os.environ.setdefault()` — inert
wherever a container already injected the compose-network values);
`OPENRAILROUTING_URL` is left alone entirely — `RailRouter` (`models/
route/routing/rail_router.py`) already falls back to
`http://localhost:8989` on its own when unset, which is exactly right
for the host case.

**Concurrency (Option B, scoped down from full WP14)**: only the
live-routing compute step is parallelized. `api/helpers/proposal_
compute.py`'s `compute_proposal()` gained optional `loader=`/`router=`
parameters (defaulting to the existing singletons — every other caller
is unaffected) so the script can hand each worker thread its own
`DBDataLoader` (cheap — one `psycopg2` connection, no heavy precompute)
while sharing the one process-wide `RailRouter`, already built for
concurrent use (pooled `requests.Session` — see `api/helpers/
dependencies.py`'s docstring). DB writes (`refresh_proposal()`) stay
sequential on the main thread against the single `ProposalRepository`
connection, which is not thread-safe — writes were never the bottleneck.
Full connection pooling across every adapter, for genuine intra-worker
request concurrency app-wide, is scoped out as **WP14** (§10) — a
cross-cutting change well beyond proposals.

**Tests**: `tests/test_53_proposal_refresh.py` (new) — on-load fallback
(mutate a published proposal's `route_builder_version` directly, `GET`,
assert the version was corrected, `proposal_version` bumped, and an
`update_log` `'recalculated'` row with the right `detail`) and batch
script idempotency (`run()` twice against a proposal mutated the same
way; the second run finds nothing outdated).

---

## 15. WP9 implementation notes (2026-08-04) ✅

Delivers the full §7.3 contract. §7.3 above is updated in place to the
implemented shape; this section is the changelog, per the convention §13
set. New files: `api/proposal_compare.py` (thin blueprint),
`api/helpers/proposal_compare.py` (validation, per-side resolution, diff
building), `api/helpers/proposal_load.py` (see below);
`tests/test_54_proposal_compare_api.py`;
`scripts/test_proposal_compare.py` (seed/demo, same conventions as the
WP6 gallery script).

- **On-load refresh extracted into a shared helper.** The §4.2 fallback
  previously lived inline in `GET /api/proposal/<id>`; WP9's "uses WP8's
  on-load refresh" made it two-caller code, so it moved verbatim into
  `api/helpers/proposal_load.py`'s `load_current_container()`, used by
  both the load endpoint and every compare side. **Computed sides
  refresh too** — an override side replays the anchor's stored
  `compute_request`, whose `scenario_id` only reliably means "current
  base" after the refresh has run; this is the concrete reason WP9 was
  sequenced after WP8.
- **Summary blocks on computed sides (design amendment).** The original
  §7.3 text said "+ summary row for stored sides" only; the compare
  view's requirement to diff the gallery-KPI columns for *every* side
  kind (user requirement, 2026-08-04) extends this: computed sides get
  an on-the-fly summary via the same pure
  `adapters/proposal/projection.py:build_summary_row()` publish runs —
  identical KPI semantics on both side kinds, minus `geom_simplified`
  and the DB-only identity/engagement fields. Stored sides fetch their
  row through `list_summaries(filters={"proposal_ids": [...]})` — the
  ordinary gallery machinery, so `likes_count` comes via the same CTE as
  everywhere else, no new SQL.
- **Diff shape.** Leaves carry `{a, b, abs, rel}` (not deltas alone) so
  the frontend renders a diff table without cross-referencing the sides;
  `abs = b - a` rounded to 6dp (absorbs binary-float noise on
  already-rounded EUR values), `rel = abs / |a|`, `null` on a zero base.
  The views diff is one generic recursive walk — dicts recurse over
  shared keys, non-numeric content (descriptions, filter labels,
  normalisation metadata) is skipped and empty branches pruned, so every
  cost category / view / normalisation / class key is covered with zero
  per-field maintenance (demand keys, §8.1, will diff automatically when
  they land). Keys present on only one side (cross-proposal compares:
  different trip pairs, countries, ODs, stops) are collected as dotted
  paths under `views_unmatched` instead of half-diffing. The summary
  diff runs over an explicit `SUMMARY_KPI_FIELDS` tuple (gallery column
  order) rather than "every numeric field" — identity/engagement numbers
  (proposal_id, likes_count, ...) are not KPIs and a delta over them
  would be noise.
- **"Any override present → computed side"**, even when the override
  value equals the stored one — deterministic, no equality
  special-casing; the result is identical either way, only
  published/summary provenance differs. Locked-in by a dedicated test
  (identical fingerprint, every delta zero, `published: false`).
- **`cache_hit: false` on computed sides** until WP13 — same
  stable-shape-ahead-of-the-logic-swap rule as `/calc`; the compute goes
  through `compute_proposal()`, so WP13's cache wires in with zero
  compare-specific code.
- **Error mapping**: 400 validation (side count, unknown keys, types),
  404 unknown anchor (message names the side index), 422 domain error
  from an override compute (side-index-prefixed), mirroring `/calc`'s
  vocabulary.
- **Docs housekeeping found and closed**: `tests/README.md` had never
  gained its `test_52`/`test_53` sections (WP6/WP7-8 closing gap) —
  backfilled alongside the new `test_54` section.
