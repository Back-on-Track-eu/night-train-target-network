# Proposals subsystem — architecture & storage

Reference for the proposal lifecycle: how a proposal is computed, published,
stored, kept current, and read back. This is the **source of truth** for the
subsystem's design decisions — §9's locked decisions in particular are
settled, and the doc-first convention applies: amend this document before
changing the behaviour it describes.

**Successor to `docs/PROPOSALS_DESIGN.md`** (retired 2026-08-07, after the
WP1–WP13 refactor completed). Section numbering is preserved from that
document, so existing `§2.1` / `§5.4` / `decision 24` citations throughout
the codebase still resolve. Removed in the move: the work-package
implementation plan and the per-WP implementation notes (scaffolding for
work now finished, and preserved in git history), plus the parked
`/api/proposals/analyze` design — see `docs/PARKED_WORK.md`.

**Related documentation**

| Topic | Where |
|---|---|
| Live endpoint contracts (request/response, errors) | [`../../api/README.md`](../../api/README.md) |
| Table DDL, migrations, schema overview | [`../../db/README.md`](../../db/README.md) |
| Evaluation views, normalisations, KPI formulas | [`../../models/evaluation/README.md`](../../models/evaluation/README.md) |
| Existing-network (ONTD) import & projection | [`../../db/ontd/README.md`](../../db/ontd/README.md) |
| Domain pipeline, separation of concerns | [`../../models/README.md`](../../models/README.md) |
| Frontend migration guide | [`../../../docs/FRONTEND_API_HANDOVER_2026-08-07.md`](../../../docs/FRONTEND_API_HANDOVER_2026-08-07.md) |
| Parked designs (analyze endpoint, pooling) | [`../../../docs/PARKED_WORK.md`](../../../docs/PARKED_WORK.md) |

**Modules in this package**

| File | Role |
|---|---|
| `repository.py` | `ProposalRepository` — publish, refresh, load, gallery/map queries, `outdated_trigger()` |
| `projection.py` | Pure `(route, evaluation) → summary row`; `route_fingerprint()`; `GEOM_SIMPLIFY_TOLERANCE_DEG` |
| `gtfs_store.py` | Route ⇄ GTFS + sidecar tables (write and read-back) |
| `compute_cache.py` | `ComputeCacheRepository` — the §2.3 two-map cache (`lookup`/`store`/`sweep`/`flush`). Underneath it, routing itself is cached per stop pair in `adapters/route_segment_repository.py` (`route_cache` schema) — a miss here no longer means re-routing every unchanged leg |
| `engagement_repository.py` | Likes, comments, and the `UNION ALL` timeline merge |
| `filter_builder.py` | Column-kind registry driving gallery SQL generation + validation, and the aggregate SELECT list behind §7.7's statistics |
| `id_prefix.py` | `P{id}_V{n}_` prefix rewriting between neutral and published ID forms |

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
  "composition_id":     "REF-BAL-9",               // optional; omitted = the standard
                                                   // composition (DEFAULT_COMPOSITION_ID,
                                                   // models/route/model.py)
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
- **Errors** (all JSON, `{"error", "message", …}`): `400 bad_request` /
  `400 validation_error` (malformed request), `422 gauge_mismatch` (no
  single track gauge serves every stop — carries `conflicting_stops:
  {stop_id: [gauges]|null}` for every stop of the trip so the client can
  mark them; 0.9.27), `422 routing_error` (the routing engine cannot serve
  the request — no path on the trip's gauge network, a stop that will not
  snap; an answer about the request, not a server fault), `422
  domain_error` (any other model-level rejection, e.g. country coverage),
  `500 calc_error` (genuinely unexpected).
- **No persistence decisions.** No actions, no lookups. Request in, result
  out, forget.

The frontend holds the current result in memory; unsaved exploration dies
with the session. Mitigation (frontend concern):
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

**Implementation** (agreed 2026-08-03)

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

**Read path** *(revised 2026-08-07)*. Canonicalize the resolved
compute request (sorted keys, stable number formatting) → `request_hash`.
Look up `compute_cache_pointer`, **TTL-filtered on both rows** — an
expired-but-not-yet-swept row reads as a miss, never as a stale hit, so
correctness never depends on the sweep having run (the sweep below is
disk hygiene only). A hit additionally requires the stored payload's
version constants to match the running `ROUTE_BUILDER_VERSION`/
`CALC_VERSION` — defense in depth for a forgotten version-bump flush; a
mismatch reads as a miss and the recompute overwrites the stale rows.
- **miss** → run the compute pipeline, which yields `(fingerprint,
  scenario_id, composition_id, payload)`
- **hit** → fetch `compute_cache_result` by the pointer row's
  `(route_fingerprint, scenario_id, composition_id)`; assemble the
  response from that shared `payload` plus the pointer row's
  request-specific `resolved_request`/`suggested_stops`; set
  `cache_hit: true`

**Write path** *(revised 2026-08-07 — upsert, not the original
`DO NOTHING`)*, both writes after a successful compute, result before
pointer:

```sql
INSERT INTO compute_cache_result (route_fingerprint, scenario_id, composition_id, payload)
VALUES (...)
ON CONFLICT (route_fingerprint, scenario_id, composition_id)
DO UPDATE SET payload = EXCLUDED.payload, created_at = now();

INSERT INTO compute_cache_pointer (request_hash, route_fingerprint, scenario_id, composition_id, resolved_request, suggested_stops)
VALUES (...)
ON CONFLICT (request_hash)
DO UPDATE SET route_fingerprint = EXCLUDED.route_fingerprint, ...,
              created_at = now();
```

The original draft said `DO NOTHING` on both; the read-side TTL filter
above forced the revision: with `DO NOTHING`, an expired row would
permanently block its own key — every recompute's write would no-op
against it, so that request/result could never re-prime until a sweep
happened to delete the corpse. `DO UPDATE` refreshing `created_at` fixes
that and is equally race-safe under concurrent identical computes (last
write wins with identical content). The design's essential property is
preserved: **no refresh-on-READ** — a cache hit never touches
`created_at` (no LRU semantics); only a write after a miss does. A hot
result that ages past the TTL is simply recomputed and re-primed by the
next miss, keeping the read path free of any read-then-update branching.

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
(§4.2) — a full flush, not a TTL-aware partial one.

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
served by `GET /api/proposal/<id>/engagements` (§7.5). `update_log` is the
only append-only source of the three: likes and comments contribute their
*current* rows, so this table is what keeps a superseded state's history
alive at all.

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
   `docs/PARKED_WORK.md` for pooling every connection properly).
2. **On-load fallback**: `GET /api/proposal/<id>` detects an outdated
   proposal (`outdated_trigger()`) and refreshes before returning —
   correctness for anything the batch hasn't reached, at the cost of one
   slow load.

Both mechanisms share one staleness check
(`adapters/proposal/repository.py`'s `outdated_trigger()`, checked in
priority order `route_builder_version` → `calc_version` →
`base_scenario_moved`): purely internal, server-side — **no user-facing
staleness flag exists** (an earlier revision surfaced `scenario_outdated`
on gallery/load rows; removed 2026-08-04, since the system keeps every
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
- **derived**: `general_parameters` (trip_km, duration, avg speed,
  `track_gauge_mm` — the gauge profile the trip was routed on, 0.9.27) —
  recomputable from segments (the gauge from the stops)
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
    name                   TEXT NOT NULL,           -- see the note below
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

**Deviation from the original locked shape (decided during
implementation, 2026-08-03):** `name` was added to the container. The design as
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

    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),  -- set once, never touched by overwrite
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

### 5.5 ONTD integration (revised 2026-08-04)

Existing night train routes stay in the `ontd` schema — deliberately **not**
the proposals schema. The `ontd` schema splits into two table classes
with different lifecycles:

**Refreshed tables** — the 11 canonical ONTD mirrors (`agencies`, `stops`,
`routes`, `trips`, `trip_stop`, `calendar`, `calendar_dates`, `classes`,
`translations`, `routes_inactive`, `trips_inactive`) plus the derived
`route_summaries` projection. TRUNCATEd and reloaded on every half-yearly
ONTD refresh. Note the schema has never been created or loaded in any
environment before the ONTD import landed (`seed.py` deliberately doesn't know it) — the
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
  "include": ["summaries", "map_lines", "map_routes",
              "map_stop_counts", "map_country_counts"]
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
  *thickness* off `proposal_count`; `avg_margin_eur_per_train_km` is the
  mean across exactly those proposals, for optional colouring — filtered
  but **not** paginated (the map shows the whole filtered set). Geometry
  is simplified for overview zoom at query time. The contributing
  `proposal_ids` / `existing_route_ids` are deliberately not returned —
  unbounded in proposal count, and superseded by `map_routes`.
- `map_routes`: GeoJSON FeatureCollection, one feature per **listed** row
  (the projections' stored `geom_simplified`) — the only map section that
  IS paginated, sharing `summaries`' exact filter/sort/limit/offset so the
  two always describe the same rows. Fixed in size at the page size.
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
own endpoint, `POST /api/proposals/analyze` — **designed but not built**;
the design is parked in `docs/PARKED_WORK.md`. Compare stays the per-pair
deep dive that view would drill down into.

### 7.4 No delete API

With one stored state per artifact there is no in-flow removal at all;
cleanup is manual/script work directly on the database. (Guest-hygiene
retention job: not needed — ephemeral compute leaves no drafts behind.)

### 7.5 Engagement — one aggregate read, singular writes

Restructured 2026-08-06. The engagement surface is one read
endpoint and five writes, all in `api/proposal_engagement.py`:

```
GET    /api/proposal/<id>/engagements     likes + comments + timeline
POST   /api/proposal/<id>/like            @require_auth, idempotent
DELETE /api/proposal/<id>/like            @require_auth, idempotent
POST   /api/proposal/<id>/comment         @require_auth
PATCH  /api/proposal/<id>/comment/<cid>   @require_auth, author-only
DELETE /api/proposal/<id>/comment/<cid>   @require_auth, author-only
```

This replaces the earlier `GET/POST/DELETE …/likes`,
`GET/POST …/comments`, `PATCH/DELETE …/comments/<cid>` set *and* the
`GET …/timeline` endpoint this section originally specified — the
timeline was never built separately, because the aggregate read
subsumes it. Removal, not deprecation (same treatment as §7.6).

`engagements` returns three sections: `likes` (`{count, liked_by_me}`),
`comments` (`{count, items}`, oldest first), and `timeline` — the
chronological merge of `update_log` + `likes` + live `comments`, built
as one `UNION ALL` in `adapters/proposal/engagement_repository.py` so
the database does the merge and the ordering. Each event carries
`event`, `at`, `proposal_version` (the state counter *after* it),
`actor`, and an event-specific `detail`.

`actor: null` means the **system** acted — a version bump or base
scenario move (§4.2). That is what separates a system `recalculated`
from a user `overwritten`, and it is why `update_log.user_id` being
nullable matters. A deleted account is not a system event: it renders
as `{"user_id": null, "user_name": "[deleted]"}`, the same placeholder
the comment thread uses.

**The timeline is a projection of current state, not an audit trail**
(locked decision 28). Only `update_log` is genuinely append-only.
Engagement contributes its *current* rows:

- unliking is a hard `DELETE`, so a withdrawn like leaves no trace;
- a deleted comment is excluded everywhere — thread, `comments.count`,
  and timeline. `comments.is_deleted` survives as an internal tombstone
  only, so `comment_id` stays stable and a second `PATCH`/`DELETE`
  answers `404` rather than resurrecting the row;
- an edited comment appears at its `updated_at` with
  `detail.edited: true`, not at its post time.

So the sequence a reader sees can change retroactively. That is the
right trade for a discussion feed and the wrong one for an audit log —
which is exactly why the publish/refresh events live in their own
append-only table rather than being derived from current state too.

No pagination: an unbounded merge was accepted deliberately (the
per-proposal row counts are small, and a `limit` parameter would
complicate the frontend's "full aggregate" model for no present gain).
Revisit if a proposal ever accumulates thousands of likes.

**Counts on gallery rows.** `likes_count` and `comments_count` are
live-joined onto every `POST /api/proposals` summary row (§7.1) so a
list view never calls this endpoint per row; bodies and the timeline
stay here. Both are ordinary `RANGE_COLUMNS` entries in
`filter_builder.py`, hence filterable and sortable like any numeric
column, and both are `NULL` on ONTD rows (locked decision 23).

**Rate limiting.** Writes are limited per authenticated user
(`api/config.py` holds the numbers, `api/auth_middleware.py`'s
`rate_limit_key()` the bucket key — Flask-Limiter evaluates the key
function in a `before_request` hook, before `@require_auth` has set
`g.user_id`, so the token is resolved there instead).

### 7.6 Replaced endpoints

`POST /api/route/plan` and `POST /api/evaluation/calc` are replaced by
`POST /api/proposal/calc` + `POST /api/proposal/publish`. Removal, not
deprecation — see `docs/FRONTEND_API_HANDOVER_2026-08-07.md`;
`test_stub_endpoints_return_501` and the API README change accordingly.

### 7.7 `GET /api/proposals/stats` — descriptive statistics

Counts, KPI aggregates, and the top/flop rankings over countries and
country-to-country relations. Deliberately the cheap end of analysis:
read-only over the stored gallery rows, one round trip, no recompute, no
scenario override. Compare (§7.3) answers "line vs line"; the parked
analyze endpoint answers "what does this *set* of lines do as a
network"; stats answers "what has been proposed so far, and where are
the gaps".

That boundary is what keeps the aggregates honest. `avg` on a rate
column is the unweighted mean of per-route figures — a typical
proposal's cost per train-km, not the cost per train-km of the whole
set. Deriving the second needs annual train-km per route as a weight,
which `proposal_summaries` does not carry and which the analyze design
derives per member at compute time. Sums are therefore emitted only for
**extensive** columns (`filter_builder.ADDITIVE_COLUMNS`), never for
rates, and network reach is reported as distinct stops and countries
rather than as a sum of `n_stops` that would double-count every shared
station.

**Scopes.** Every statistic comes in three: `proposal`, `existing`,
`all` — the gallery's own `source` vocabulary. Existing (ONTD) rows are
NULL in every proposal-only column, so the `existing` and `all` scopes
report only the shared metric subset
(`filter_builder.SHARED_SOURCE_COLUMNS`). Reporting financials under
`all` would put a proposals-only number under a label implying 142 rows
contributed when 42 did.

**Relations (the ranking dimension).** A relation is a pair of countries
one train connects **boarding-to-alighting**, not a pair of countries it
touches. On the proposal side it comes from `od_pairs`, which the demand
model already builds under exactly that rule; on the existing side from
the ONTD timetable's `no_entry`/`no_exit` flags plus the route builder's
own night-window classification. Both write the same sorted `"AA__BB"`
keys into a `country_relations` array column on their summary
projection, so one `unnest` ranks both sources together.

The candidate set they are ranked against is
`input_params.country_relations` (`db/README.md`), built at seed time:

1. **Reference station per country** — the catalog stop closest to that
   country's own stop centroid. Not `ST_Centroid(countries.country_geom)`:
   that geometry is the Marine Regions EEZ union (land *plus* maritime
   zones, which is what attributes belt and strait crossings correctly),
   so its centroid sits offshore for any country with a large sea area.
2. **Prefilter** on great-circle distance × a rail detour factor, purely
   to decide whether routing the pair is worth an HTTP call.
3. **Route** the survivors on real track and keep only those whose
   **routed** distance is under `PROPOSALS_STATS_RELATION_MAX_KM`.

Step 3 is the one that earns its keep. A straight-line threshold admits
Italy–Greece (~1000 km apart across the Mediterranean, 1900+ km by track
around the Adriatic) and every Finnish pair (no through path at all —
Gulf of Bothnia plus a 1524mm gauge break). Routing removes both without
a maintained exception list.

Two consequences are reported rather than hidden. Pairs dropped as too
far or unroutable are **counted** in the response; countries with no
stops in the catalog yet have no reference station, so they rank under
`countries` but appear in `unresolved_countries` and contribute no
relations. That list shrinks on its own as stop coverage grows — the
catalog currently covers a subset of the seeded countries.

**Flop ordering.** Zeros dominate both rankings while proposal volume is
low, so the tie-break carries the information: relations sort by
distance ascending within the zeros, putting the nearest unserved pair —
the most plausible missing night train — first. Alphabetical would be
noise.

**Not filterable, on purpose.** Only `user_id` is a request parameter.
Ranking lengths and the distance ceiling live in `api/config.py`: they
define what "top" and "flop" mean, and a per-request definition would
make two callers' numbers incomparable. The repository methods take the
ordinary gallery `filters` dict, though, so a future
`POST /api/proposals/stats` accepting the full §7.1 filter model
("statistics over exactly what the gallery is showing") is a blueprint
change with no SQL behind it.

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
    with no client-visible staleness flag (2026-08-04 revision: an earlier
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
18. **Analyze is a distinct, KPI-level endpoint** (designed, not built —
    `docs/PARKED_WORK.md`): bundle +
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
    authenticated and strictly rate-limited; the compute cache (§2.3)
    is a hard prerequisite.
22. **ONTD is excluded from compare and analyze** (political decision,
    2026-08-04) — existing routes are gallery/map context only, even
    context only.
23. **Existing routes carry a reduced, descriptive KPI set**
    (2026-08-04): composition (where curated), duration, distance,
    average speed, and GHG g/pax-km by mode — never financial, demand,
    or engagement values.
24. **Mode emission factors are flat g/pax-km constants in
    `models/emissions`** — the single source for night-train, air, and
    car values, replacing the projection's placeholder CO2 constants.
    The proposal night-train value uses the flat factor until an
    energy-based, country-resolved model enriches it. Factors migrate
    into a params table if the `input_params` schema is ever split
    along model domains (considered and dropped, 2026-08-07).
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
28. **Engagement is one aggregate read plus singular writes**
    (2026-08-06): `GET /api/proposal/<id>/engagements` returns
    likes, comments and the merged timeline together; writes are
    `POST/DELETE …/like` and `POST/PATCH/DELETE …/comment[/<cid>]`.
    The timeline is a **projection of current state** merged with the
    append-only `update_log`, not an audit trail — withdrawn likes and
    deleted comments vanish, an edited comment moves to its edit time,
    and `actor: null` means the system acted. Gallery rows carry
    `likes_count` + `comments_count`; bodies and events do not. Comment
    writes are rate limited per authenticated user, with the limits (and
    every other HTTP-shaping limit) in `api/config.py`.
26. **ONTD imports read the Google Sheets directly** via the public
    whole-workbook export link (`export?format=xlsx`, no API
    key/credentials — both sheets link-shared "Viewer") for
    traceability; the compositions workbook is imported once, then
    the DB's curated tables are source of truth. Curated tables are
    excluded from the refresh TRUNCATE and use soft references across
    the lifecycle boundary; the loader reports orphaned route
    assignments after each refresh.

---
