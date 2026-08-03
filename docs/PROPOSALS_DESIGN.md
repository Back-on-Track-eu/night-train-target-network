# Proposals — Storage, Identity, Gallery & Compare Design

Status: agreed design, pre-implementation (2026-07-31)
Scope: compute/publish APIs, `proposals` schema, gallery/map/compare, ONTD integration
Suggested location in repo: `docs/PROPOSALS_DESIGN.md`

---

## 1. Purpose

Design of the proposal lifecycle and storage for the public tool, supporting:

- a public gallery view with SQL-backed filtering, sorting, pagination —
  showing by default **one item per proposal family, evaluated on the
  current base scenario**
- map views (route lines, stop/country heat aggregates) driven by the same filters
- a compare view across variants (composition/scenario) of one route family
  or across different proposals
- the KPI set required by the political target audience (cost/revenue/margin
  per train-km, subsidy need, demand, modal shift, CO2 — the
  demand-dependent ones faked until the demand model exists)
- inclusion of existing night train routes (ONTD) in gallery and map,
  clearly marked, without financial KPIs
- multi-user public operation

Two architecture decisions (2026-07-31) supersede the earlier
persist-on-calc concept and shape everything below:

1. **Merged compute API.** Route planning and evaluation are one endpoint
   (`POST /api/proposal/calc`), one pipeline, one response. There are no
   half-states: a result always contains route *and* evaluation.
2. **Ephemeral compute, explicit publish.** Computing writes nothing to the
   database. Proposals come into existence only through an explicit
   `POST /api/proposal/publish`. The database contains deliberate artifacts,
   not exploration states.

---

## 2. Compute / publish architecture

### 2.1 `POST /api/proposal/calc` — ephemeral compute

One stateless request → route + evaluation, no side effects:

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
  "scenario_id":        4,                         // optional; omitted = current base

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
  "route_fingerprint":     "sha256:…",             // §3.1, for family reasoning

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
calc response only carried one because it was a standalone endpoint), which
also removes the former reinject-on-read rule: stored and computed
responses share one shape with the route appearing exactly once.

Further notes:

- **IDs**: compute responses carry neutral structural IDs (`R1`, `T1`, …,
  no proposal prefix). Prefixed IDs (`P{id}_V{n}_…`) exist only on
  published proposals; publish assigns them. The fingerprint
  canonicalization strips prefixes anyway (§3.1), so fingerprints agree
  between ephemeral and published forms.
- **No persistence decisions.** No actions (`created`/`loaded`/
  `unchanged`/`branched`), no family lookups, no dispatch matrix. Request
  in, result out, forget.

The frontend holds the current result in memory; unsaved exploration dies
with the session. Mitigation (frontend concern, coordination item WP13):
draft caching in the client, warn-on-navigate for unsaved changes.

### 2.2 `POST /api/proposal/publish` — the only user write path

```jsonc
{
  "compute_request": { … },            // the exact request of §2.1
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
result itself and persists what it computed. v1 simply recomputes on
publish (publishing is rare; one routing run is acceptable). Optimization
later: the compute cache (§2.3) lets publish reuse a server-computed result
by request hash — same guarantee, no recompute. For a public, politically
consumed gallery this is non-negotiable: no path may exist by which
manipulated KPIs enter the database.

**The publish handler.** All case distinctions of persisting live in one
component behind this endpoint (e.g. `api/helpers/publish_dispatch.py`) —
the successor of the former plan/calc dispatch matrix, now with a fraction
of its cases. Family membership is pure backend logic; from the user's
perspective there is only *one* proposal, so the handler keeps the family
consistent silently — no confirmation round-trips, no extra parameters:

| Case | Handling |
|---|---|
| `mode: "new"` | insert under the calling user (guest or registered); `proposal_id` must be absent. If the fingerprint matches an existing own family, the proposal is simply a new member of it — no constraint prevents duplicates (§3.2). `update_log` 'published' (+ the informational `branched_from`/`branched_to` pair when `based_on_proposal_id` is given — this replaces the old branch machinery: building on a foreign proposal is loading it, exploring ephemerally, publishing as new) |
| `mode: "overwrite"`, fingerprint unchanged | replace the stored state of the *owned* proposal: state counter +1, previous state hard-deleted in the same transaction (GTFS/sidecar rows by ID prefix, summary row upserted), `update_log` 'overwritten' |
| `mode: "overwrite"`, fingerprint changed | as above, **plus**: any other members of the old family are hard-deleted in the same transaction (`update_log` 'discarded' each). They were internal variants of a route that no longer exists in this form — keeping them would surface stale states. The user never sees or confirms this; it is the backend keeping its own representation consistent |

Ownership is checked in both overwrite cases (403/404 for foreign or
unknown ids). **The acting user is never part of the request body**: identity
comes exclusively from the auth layer (JWT → `user_id` via the existing
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
settings back and forth — hits routing only once per distinct input state.
Strictly a performance layer: invisible to the data model, never a source
of truth, safe to flush at any time.

**Level 1 — full results.** Key: hash of the canonical resolved compute
request + `ROUTE_BUILDER_VERSION` + `CALC_VERSION`. Value: the complete
compute response. Serves repeat `POST /api/proposal/calc` calls and the
publish path (§2.2): a publish whose request hash hits the cache persists
the cached server-computed result without recomputing — the integrity
guarantee holds because only server-computed results ever enter the cache.

**Level 2 (optional extension) — route stage.** Key: hash of only the
routing-relevant subset of the request (stops, composition, scenario,
timetable/routing settings). Value: the built route before evaluation.
Lets a change of evaluation-only inputs skip the expensive routing stage
and re-run just the (sub-second) evaluation — closing the one efficiency
gap the merged API opened.

Correctness of the key: scenario rows are immutable snapshots (edits create
new `scenario_id`s), so `scenario_id` inside the request is a sound key
component and base-scenario moves invalidate naturally by changing the id;
version constants in the key invalidate on every bump. Assumption to verify
in implementation: all parameter tables feeding evaluation (compositions,
infrastructure, …) are reachable through the scenario pin — anything that
is not must join the key.

**Storage**: shared across gunicorn workers, so not per-process memory. To
avoid new infrastructure, an `UNLOGGED` PostgreSQL table (key, response
JSON, created_at) with TTL cleanup on write is sufficient; a memory store
(e.g. Redis) stays a drop-in upgrade if response sizes or traffic ever
demand it.

### 2.4 What this removes (vs. the persist-on-calc design)

- the first-level dispatch handler and its decision matrix
- family copy on foreign interaction (loading foreign proposals is just
  reading; publishing as new is the "copy")
- `loaded` / `unchanged` / `already_exists` response actions
- half-states: every stored proposal has route **and** evaluation —
  `calc_version` and `evaluation_output` become NOT NULL, the
  `has_evaluation` gallery filter disappears, evaluation-to-route-state
  matching is by construction
- stale-sibling cascades on every edit (now one silent consolidation
  inside the publish handler)
- guest exploration hygiene (ephemeral compute leaves nothing behind)

---

## 3. Identity model

### 3.1 Route fingerprint

A route's uniqueness is defined by its **resolved outputs**, not its request
settings:

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

Consequence (accepted): request settings (`timetable_mode`,
`fixed_night_interval`, `routing_mode`, `schedule_mode`,
`auto_stop_addition`) are *state*, but when a setting change alters the
resolved times/stops/geometry, the fingerprint changes with it. The
fingerprint always describes what the route *is*, not how it was requested.

### 3.2 Proposal identity, families, variant coordinates

Three distinct concepts, in descending scope:

- **Proposal identity = `proposal_id`.** Nothing else. The editor's load
  semantics guarantee it: a user loads (or computes and publishes) a
  proposal and all editing targets that one proposal until a different one
  is loaded or created; overwrite-vs-new is the user's explicit choice at
  publish time.
- **Family key = `(user_id, route_fingerprint)`** — a pure grouping of one
  user's *published* proposals sharing a route, discovered by indexed
  lookup (`idx_summaries_family`, §5.4), never enforced by a constraint.
- **Variant coordinate = `(composition_id, scenario_id)`** — addresses a
  member *within* a family: the cells of the variants matrix (§7.2), the
  sides of a compare (§7.3), the default member (§3.3). Within a family the
  fingerprint is shared, so the coordinate is the only distinguishing part;
  it has no meaning as a global key.

**Families are strictly single-user** — trivially now: only publishes
create proposals, and a publish always creates/overwrites a proposal of the
calling user. Interacting with a foreign proposal is reading; making it
yours is publishing as new.

**No deduplication.** The same route — and even the same variant coordinate
within a family — may exist more than once (same or different users):
publish never searches for an existing match. The only deliberate lookup of
existing proposals is the family matrix (§7.2); coordinate collisions there
resolve to the most recently updated member.

Families contain only what users deliberately published (plus system
materializations, §3.3). There is no lazy sibling materialization concept
anymore: an unexplored variant coordinate is simply computed ephemerally
when someone wants to see it, and becomes a family member only if published.

### 3.3 Default family member

The gallery and the proposal editor need one canonical variant per family
to present, and its KPIs must reflect the **current base scenario** — a
proposal's headline numbers in a public gallery must never come from a
superseded or what-if parameter state by default.

**Default member** of a family: the member with `scenario_id = ` the
current base scenario (`scenario.scenarios` row with `is_current_base`),
with the composition of the family's most recently updated member.
Determined by query, not by a stored flag:
`DISTINCT ON (route_fingerprint, user_id) … ORDER BY (scenario is current
base) DESC, updated_at DESC`, supported by `idx_summaries_family`.

When the base scenario moves (data change → new scenario row, old
`is_current_base = FALSE` — scenario rows themselves are never rewritten),
the current-base member of a family does not exist yet. Rules:

- the **version-refresh batch** (§4.2) materializes the new default members
  proactively — the one case besides refresh where the system publishes
  without a user action, always **under the family owner's `user_id`**
  (`update_log` with `user_id NULL`)
- until then, the gallery falls back to the previously newest member,
  flagged `scenario_outdated: true` (derived by joining
  `scenario.scenarios`, not stored)
- on load with `?resolve=default` (§7.2), a missing default member is
  materialized on demand, same ownership rule

Old-scenario members are kept as pinned snapshots (that is what scenario
pinning is for); they are simply never the default.

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

States are pruned and siblings can be discarded, while likes/comments stamp
state numbers — an append-only event log preserves the timeline ("comment
on state 3, route overwritten afterwards, then recalculated with a new calc
version"):

```sql
CREATE TABLE proposals.update_log (
    log_id            SERIAL PRIMARY KEY,
    proposal_id       INTEGER NOT NULL,          -- soft ref, same convention as likes/comments
    proposal_version  INTEGER NOT NULL,          -- state counter AFTER the event
    user_id           INTEGER REFERENCES admin.users(user_id) ON DELETE SET NULL,
                                                 -- NULL for system events (refresh,
                                                 -- default-member materialization)
    event             TEXT NOT NULL,             -- 'published' | 'overwritten'
                                                 -- | 'recalculated' | 'discarded'
                                                 -- | 'branched_from' | 'branched_to'
    detail            JSONB,                     -- branch: {"source_proposal_id":…}
                                                 -- recalculated: {"trigger":"calc_version"
                                                 --   |"route_builder_version"
                                                 --   |"default_materialization","from":…,"to":…}
                                                 -- discarded: {"cause":"overwrite_discard",
                                                 --   "edited_proposal_id":…}
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

### 4.2 Version refresh — published proposals always at the newest calculation state

Users never republish because of a version change; the system keeps the
stored artifacts current. Triggers:

- `ROUTE_BUILDER_VERSION` bump → recompute (route + evaluation) all proposals
- `CALC_VERSION` bump → recompute evaluations
- **base scenario moved** → materialize missing default members (§3.3)

Mechanisms, in order of preference:

1. **Batch script** (`backend/scripts/refresh_proposals.py`): scans for
   outdated proposals / missing default members, re-runs the compute
   pipeline per proposal, overwrites/creates in place (owner kept,
   `update_log` 'recalculated' with `user_id NULL`). Run after every
   version bump / base scenario move; idempotent, resumable, dry-run mode,
   **configurable concurrency limit** (routing capacity; first beneficiary
   of a future routing cluster — parked topic).
2. **On-load fallback**: `GET /api/proposal/<id>` detects an outdated
   proposal or missing default member and refreshes/materializes before
   returning — correctness for anything the batch hasn't reached, at the
   cost of one slow load.

A refresh may change the fingerprint (new routing graph). Unlike an
overwrite-publish, a refresh never discards family members: a graph change
affects all members of a family equally, so each member's own refresh moves
it to the same new fingerprint — the family converges on its own, and
discarding would delete proposals that are about to become valid members
again.

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
- **irreducible evaluation data**: the entire calc output (`models`,
  `input` parameters, `views`) — not reconstructible from anything

Read path: `route_dict_from_gtfs()` (new, in `api/helpers/`, the read-side
counterpart of the GTFS insert) rebuilds a route dict that deep-equals the
original compute result and hashes to the same fingerprint;
`input.parameters` is rebuilt alongside it via the scenario pin. Both are
enforced by round-trip tests. The former verbatim-byte guarantee is replaced by this
**deterministic reconstruction** guarantee. The JSON-not-JSONB rationale
continues to apply to the evaluation output column (key order must
survive).

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
    route_fingerprint      TEXT NOT NULL,
    composition_id         TEXT NOT NULL,
    scenario_id            INTEGER NOT NULL,        -- pinned; never rewritten (§4.2).
                                                    -- Lineage/currentness derived by joining
                                                    -- scenario.scenarios, not stored here.
    route_builder_version  TEXT NOT NULL,
    calc_version           TEXT NOT NULL,           -- always evaluated (§2.4)
    compute_request        JSON NOT NULL,           -- resolved compute request, verbatim
    evaluation_output      JSON NOT NULL,           -- models + views only (§5.1)
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_proposals_variant
    ON proposals.proposals (user_id, route_fingerprint, composition_id, scenario_id);
```

Plain (non-unique) index for family and variant-coordinate lookups (§3.2,
§7.2). Duplicates are expected and allowed; proposal identity is the
`proposal_id` alone.

Dropped vs. the current implementation: `is_current` + partial unique index
(one row per proposal), `change_log` (superseded by `update_log`),
`route_body` (route lives in GTFS + sidecars), the `input.route` copy
and `input.parameters` inside the evaluation JSON (both rebuilt on read,
§5.1), and nullable `calc_version`/evaluation (no half-states).

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
    route_fingerprint       TEXT NOT NULL,
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

CREATE INDEX idx_summaries_family      ON proposals.proposal_summaries
    (route_fingerprint, user_id, updated_at DESC);   -- family + default-member resolution (§3.3)
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
`views.*.per_train_km` normalisation; annual totals from `per_year`.

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

*Create:* compute (ephemeral, as often as wanted) → publish `new` → one
transaction writes GTFS + sidecars, evaluation output, summary row,
`update_log` 'published'. The proposal is immediately complete (route +
evaluation + KPIs).

*Edit:* load own proposal → compute edits ephemerally → publish `overwrite`
→ state counter +1, previous state pruned. If the route changed, the
publish handler silently deletes any other members of the old family in the
same transaction (§2.2) — from the user's perspective there is only one
proposal; family consistency is backend business.

*Variant:* load own proposal → switch composition/scenario in the editor →
compute ephemerally → publish `new` → new member of the same family
(fingerprint unchanged).

*Build on foreign:* load foreign proposal (read-only) → explore ephemerally
→ publish `new` (optionally with `based_on_proposal_id` for the timeline).
No copy machinery, no branch semantics in storage.

*Compare:* per-side resolution (§7.3): published members load; missing
coordinates are computed **ephemerally and not persisted** — the response
marks such sides `published: false`. Publishing a computed side afterwards
is an ordinary publish.

*Version bump / base scenario move:* refresh batch recomputes / materializes
default members (§4.2); on-load fallback covers the gap.

---

## 7. API design

All list/filter/sort/aggregate work runs in SQL against
`proposal_summaries` (+ `ontd.route_summaries`).

### 7.1 `POST /api/proposals` — gallery + map in one endpoint

One filter model drives both gallery and map. The response is sectioned;
the caller picks sections via `include`.

**The gallery shows exclusively default members** (§3.3): one item per
family, KPIs always on the current base scenario. Items whose default
member is not materialized yet fall back to the newest member, flagged
`scenario_outdated: true`. There is no mode that lists all variants —
variant-level browsing lives in the variants matrix on
`GET /api/proposal/<id>` (§7.2) and in compare (§7.3), where other
scenarios are a first-class dimension.

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

- optional `?resolve=default`: resolves and returns the family's **default
  member** (§3.3), materializing it if missing — the standard way the
  editor opens a proposal from the gallery ("always land on current base")
- performs the on-load version-refresh fallback (§4.2)
- returns exactly the compute-response shape (§2.1) — reconstructed route
  dict, evaluation with `input.parameters` rebuilt via the scenario pin,
  route appearing once — plus proposal metadata (id, owner, name, versions,
  timestamps)
- `variants` section: the family matrix
  `{composition_id × scenario_id → proposal_id | null}`, scoped to the
  proposal owner's family, from one indexed query. Cells with more than one
  candidate (duplicates are allowed) show the most recently updated one. A
  null cell is not stored — the frontend computes it ephemerally via
  `POST /api/proposal/calc` and offers publishing.

### 7.3 `POST /api/proposals/compare`

Each side is anchored on **exactly one family member**, with optional
coordinate overrides resolved within that side's own family. Same anchor on
both sides = within-family compare (e.g. TAC scenario A vs B on one route);
different anchors = cross-proposal compare (e.g. your proposal vs someone
else's, each on a chosen scenario):

```jsonc
{
  "sides": [
    {"proposal_id": 123, "scenario_id": 4},        // side A: my proposal, scenario 4
    {"proposal_id": 456, "scenario_id": 4}         // side B: other user's proposal,
  ]                                                //   same scenario for a fair diff.
                                                   // Omitted coordinate = the anchor's
                                                   // own; a bare {"proposal_id": …} side
                                                   // is simply that proposal as stored.
}
```

Stored members load; a missing coordinate is **computed ephemerally** from
the anchor's compute request with the overridden coordinate — nothing is
persisted, the side is marked `published: false`, and no ownership question
arises (this replaces the former system-materialization rule for compare).
Response per side: full route dict + evaluation output (+ summary row for
published sides); plus a `diff` section with per-KPI absolute and relative
deltas and a structured diff over the shared `views` trees (same view keys
→ per-leaf deltas), so the compare view can show *which* cost component
moved; plus family context (same or different fingerprint, which
coordinates differ). Ephemeral sides share the compute latency of the
editor — the UI needs a loading state.

Two sides for now; the shape allows more later.

### 7.4 No delete API

The silent discard inside the publish handler (§2.2) covers the one in-flow
removal need; anything else is manual/script work directly on the database.
(Guest-hygiene retention job: not needed — ephemeral compute leaves no
drafts behind.)

### 7.5 `GET /api/proposal/<id>/timeline`

Chronological merge of `update_log`, `comments`, and `likes` for one
proposal. Natural home: `api/proposal_engagement.py`.

### 7.6 Replaced endpoints

`POST /api/route/plan` and `POST /api/evaluation/calc` are replaced by
`POST /api/proposal/calc` + `POST /api/proposal/publish`. Removal, not
deprecation — the frontend migrates in the same coordination batch (WP13);
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
seasonal frequency, recheck identity — frequency is not part of the
fingerprint (stops/geometry/times only), so proposals differing only in
frequency would share a family coordinate. Harmless under no-dedupe, but it
should be a conscious decision then.

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
   proposals exist only through publish (plus system refresh /
   default-member materialization). Unsaved exploration is a frontend
   concern (draft caching, warn-on-navigate).
3. **Publish integrity**: the server never persists client-supplied
   results — publish carries inputs, the server computes what it stores,
   either freshly or from the server-side compute cache (§2.3), which only
   ever holds server-computed results.
4. **Overwrite vs new is the user's explicit choice** at publish; all
   further case handling lives in the publish handler. Families are backend
   logic invisible to users: an overwrite that changes the route silently
   deletes the old family's other members in the same transaction. System
   refreshes never discard (members converge via their own refresh).
5. Hard delete of previous states, in-transaction; `update_log` preserves
   the timeline for comments/likes. One row per proposal — no `is_current`
   flag, no `change_log` column.
6. Route stored **once**: GTFS + sidecar tables, reconstructed on read;
   evaluation output stored as `models` + `views` only — route and
   `input.parameters` are rebuilt on read (parameters exactly recoverable
   through the immutable scenario pin).
7. **Proposal identity is `proposal_id` alone; no deduplication.**
   Fingerprint and variant coordinate `(composition_id, scenario_id)` only
   group and address members within a family; `(user_id,
   route_fingerprint, composition_id, scenario_id)` is a plain index, not
   a constraint.
8. **Families are strictly single-user**; building on a foreign proposal is
   loading + ephemeral exploration + publish-as-new
   (`based_on_proposal_id` optional, timeline-informational only).
9. The gallery shows **exclusively default members** — one item per
   family (current base scenario × most recently updated composition),
   `scenario_outdated` fallback until materialized. Variant-level browsing
   happens only in the variants matrix and in compare.
10. Scenario pins on proposals are never rewritten; base scenario moves are
    handled by materializing new default members (batch + on-load) under
    the family owner.
11. Version bumps are handled by the system (batch refresh + on-load
    fallback), logged in `update_log`.
12. Subsidy = gap to target margin (`max(0, -net_eur)`).
13. Route identity for fingerprinting = resolved stop lists + geometries +
    exact trip schedules; request settings are state.
14. ONTD stays in its own schema; union at API level with explicit `source`
    marking and no KPIs for existing routes.
15. Demand-dependent KPIs faked with an explicit placeholder flag until the
    demand model exists.
16. Compare takes one family-member anchor per side; missing coordinates
    are computed ephemerally, never persisted.
17. No delete API, no guest-hygiene job.

---

## 10. Implementation plan — work packages

Sized so each can be worked off in its own chat thread. Dependencies noted;
every WP ends with the standard closing steps (README sweep, sanity check,
feat/test/docs commits, full suite green from `backend/` via
`uv run --extra dev pytest`).

**WP1 — Schema migration** *(no dependencies)*
Migration under `backend/db/dev/sql/migrations/` + `create_proposal_schema.sql`
rewrite: slimmed `proposals.proposals` (§5.3, NOT NULL evaluation/calc
columns, `compute_request`, dropped `is_current`/`change_log`/`route_body`),
sidecar tables (§5.2), `update_log`, `proposal_summaries` (financial KPIs
NOT NULL) with all indexes, rewritten table/column comments. Verify PostGIS
geometry column on the dev DB.

**WP2 — Merged compute endpoint** *(parallel to WP1 — no persistence involved)*
`POST /api/proposal/calc`: orchestrate route building + evaluation in one
pipeline (API boundary only — `models/route` and `models/evaluation` stay
untouched and separate); neutral structural IDs; merged request validation
(verified: calc carried no extra inputs beyond the scenario override);
response shape per §2.1 incl. the **resolved** request echo (fingerprint
wiring completed after WP4). Remove persist hooks from the pipeline. Update
`test_stub_endpoints_return_501` and API README.

**WP3 — Route decomposition + reconstruction serializer** *(after WP1)*
GTFS + sidecar insert (write side, prefix assignment at publish); new
`api/helpers/route_gtfs_serialize.py` with `route_dict_from_gtfs()`
rebuilding the exact route dict (composition/track_infrastructure reloaded
via loader, `general_parameters` recomputed) and the `input.parameters`
rebuild helper (scenario-pin → `params_serialize.py`). Round-trip tests:
compute result → store → reconstruct → deep-equal, parameters included.

**WP4 — Fingerprint & projection module** *(after WP3)*
`adapters/proposal_projection.py`: canonical route extract + SHA-256
fingerprint (§3.1 rules incl. prefix stripping and coordinate rounding);
summary-row builder (route metrics, KPI extraction, geometry concatenation
+ simplification, placeholder KPI filler + flag). Tests: identical routes
in ephemeral vs published form and original-vs-reconstructed routes produce
equal fingerprints. Wire fingerprint into the WP2 compute response.

**WP5 — Publish endpoint & repository** *(after WP2 + WP4; the core WP)*
`POST /api/proposal/publish`: recompute-on-publish, `mode` new/overwrite,
ownership check, publish handler (`api/helpers/publish_dispatch.py`)
with its case table incl. silent sibling discard on route change,
`based_on_proposal_id` timeline entries, prefixed-ID assignment;
`adapters/proposal_repository.py` rewritten around single-transaction
publish (proposal row + GTFS/sidecars + summary + update_log; prune on
overwrite; `FOR UPDATE` serialization). Integration tests: create, edit
with/without discard, variant publish, build-on-foreign, concurrent
publishes.

**WP6 — Gallery/map endpoint** *(after WP5)*
`api/proposals.py` + `api/helpers/proposal_serialize.py`: SQL-pushed
filters (generic range/list/substring over all summary columns), default-
member resolution via DISTINCT ON + `scenario_outdated` fallback, the
`trip_windows` stop-time filter (GTFS overnight-time convention), sorting,
windowed count, `include` sections; `bbox` optional/deferrable. Remove
Python-side filtering.

**WP7 — Load endpoint** *(after WP5, parallel to WP6)*
`GET /api/proposal/<id>`: reconstructed response shape, `variants` section,
`?resolve=default` with default-member materialization under the family
owner (§3.3).

**WP8 — Version-refresh mechanism** *(after WP5, parallel to WP6/7)*
`backend/scripts/refresh_proposals.py` (batch: outdated versions + missing
default members, recompute/materialize in place, owner kept, `update_log`
'recalculated', idempotent, dry-run, concurrency limit) + the on-load
refresh fallback.

**WP9 — Compare endpoint** *(after WP7, uses WP8's on-load refresh)*
`POST /api/proposals/compare`: per-side anchored resolution, ephemeral
compute for missing coordinates (`published: false`), full sides + KPI
deltas + structured `views` diff + family context.

**WP10 — ONTD integration** *(after WP6; independent of WP7–9)*
`ontd.route_summaries` projection built in the seed pipeline
(`backend/db/dev/`); `sources` filter + union in `POST /api/proposals`
(summaries and map sections); `source` marking throughout.

**WP11 — Timeline endpoint** *(after WP5; small)*
`GET /api/proposal/<id>/timeline` in `api/proposal_engagement.py` merging
`update_log` + comments + likes.

**WP12 — Data migration & backfill** *(after WP5)*
Script (under `backend/scripts/`) migrating existing stored proposals:
decompose stored `route_body` into sidecars, reduce stored evaluations to
`models` + `views`, **evaluate route-only proposals** (no half-states
allowed anymore), compute fingerprints, build summary rows, seed
`update_log` with synthetic 'published' events, prune historical versions.
Idempotent; dry-run mode.

**WP13 — Frontend coordination batch (Bjarne)** *(rolling, before staging PR)*
The largest contract change so far: `/api/route/plan` +
`/api/evaluation/calc` → `/api/proposal/calc` + `/api/proposal/publish`
(incl. the publish dialog: name, overwrite-vs-new, based_on); client-side draft caching / warn-on-navigate for unsaved
exploration; restructured `POST /api/proposals` (generic filters, `trip_windows`,
sections, `scenario_outdated`); `variants` + `?resolve=default` on
`GET /api/proposal/<id>`; compare (`published: false` sides need a loading
state) and timeline endpoints; `source` and `demand_kpis_placeholder`
fields; reconstructed-response note (byte-identity not guaranteed,
structure identical). Audit `frontend/src/types/api.ts` end to end.

**WP14 — Compute cache** *(after WP2; independent of WP3–13)*
Level-1 full-result cache (§2.3): canonical request hashing shared with the
publish path, `UNLOGGED` PostgreSQL cache table + TTL cleanup, wire-in for
`POST /api/proposal/calc` and reuse in `POST /api/proposal/publish` once
WP5 lands; configurable TTL (default 3 h). Verify the key-correctness
assumption (all evaluation inputs reachable via the scenario pin). Level 2
(route-stage cache) as a follow-up in the same module if profiling shows
evaluation-only tweaks matter.
