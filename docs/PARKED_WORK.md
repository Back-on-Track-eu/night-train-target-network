# Parked work

Designs that are agreed and worked out but **not implemented**, kept out of
the live READMEs so those describe only what exists. Nothing here is
scheduled; nothing here gates anything else.

Retired from `docs/PROPOSALS_DESIGN.md` when that document was folded into
[`backend/adapters/proposal/README.md`](../backend/adapters/proposal/README.md)
(2026-08-07). `PROPOSALS_DESIGN.md` itself was deleted on 2026-08-29 once it
had been superseded for three weeks; this file is what survived it.

| Item | Status | Blocked by |
|---|---|---|
| Bundle analyze endpoint | Designed 2026-08-04, postponed 2026-08-07 | Nothing — the compute cache prerequisite is done |
| Connection pooling / intra-worker concurrency | Scoped, not started | Nothing |
| `input_params` schema split | **Dropped** 2026-08-07 | — |

---

## 1. Bundle analyze endpoint

Designed 2026-08-04 as work package 15; postponed 2026-08-07 without being
started. Its hard prerequisite — the compute cache (`adapters/proposal/README.md`
§2.3) — has since landed, so this is unblocked whenever it is picked up.

Locked decisions 18–22 in `adapters/proposal/README.md` §9 govern it and
remain in force; the design below is the detail behind them.

### 1.1 `POST /api/proposals/analyze` — bundle analysis

Compare (`adapters/proposal/README.md` §7.3) answers "line vs line". Analyze answers the network-level
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
      // "filter": {"user_ids": [7]}    // any `adapters/proposal/README.md` §7.1 filter shape ("all proposals by user 7")
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
side-level one. Member resolution is exactly `adapters/proposal/README.md` §7.3's: any effective
override → ephemeral compute (`published: false`, never persisted,
through the compute cache `adapters/proposal/README.md` §2.3), none → stored load; every anchor runs
the `adapters/proposal/README.md` §4.2 on-load refresh first. Compare is the degenerate case of one
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
(`adapters/proposal/README.md` §5.5), never a compare/analyze side.

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
  the `map_lines` machinery is a noted v2 candidate, not v1.

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
  ephemeral-and-recomputable reasoning as the compute cache (`adapters/proposal/README.md` §2.3).
  `JSON` not `JSONB` for the stored result (key order, established
  convention).
- v1 executor: one in-process background worker, FIFO queue, one job at
  a time — matches the self-hosted process model; a real queue
  (RQ/Celery) is the documented escalation path, not v1. Each member
  compute goes through `compute_proposal()`, so the compute cache does the
  heavy lifting for the dominant workflow (toggling scenarios over the
  same bundle). The compute cache is a hard prerequisite (**done**);
  connection pooling (§2 below) helps but doesn't gate.

**Response (`result`).** Per side: `bundle_summary` (`n_proposals`,
`total_distance_km`, `annual_train_km`, distinct `n_stops`, `countries`,
weighted `avg_speed_kmh`, derived cost/revenue/margin per train-km,
subsidy per chosen pooling + mode echo, summed demand/CO2 KPIs,
`subsidy_eur_per_t_co2`), per-member `adapters/proposal/README.md` §5.4-shaped summaries (`published`
flags, `overrides` echo — compare's member shape), and the aggregated
route-view cost tree (`per_year` summed, `per_train_km` derived). With
two sides additionally `diff`: bundle-summary deltas and aggregated-tree
deltas in compare's `{a, b, abs, rel}` leaf shape, plus **member-level
summary diffs paired by anchor `proposal_id`** (same anchor both sides =
paired, regardless of overrides) with unpaired members listed under
`members_unmatched: {a_only, b_only}` — `adapters/proposal/README.md` §7.3's `views_unmatched`
symmetry, so "same network, two scenarios" gets full per-line deltas and
heterogeneous bundles degrade gracefully to aggregate-only.
`detail: "full"` additionally embeds each member's complete
compute-response shape (route + evaluation) — a large payload, tolerable
because results are fetched once from a finished job, but `summaries`
stays the default.

---

---

## 2. Connection pooling / intra-worker concurrency

Scoped but not started. Independent of everything above; touches the whole
app rather than proposals specifically, which is why it was repeatedly
deferred.

**The gap.** Production runs `gunicorn --workers 4`, and
`api/helpers/dependencies.py`'s `init()` builds one long-lived connection
per singleton per worker process. That already gives **inter**-process
parallelism for free: N concurrent requests landing on N different workers
run fully in parallel, and raising `--workers` scales it further, cheaply.

What is missing is **intra**-worker concurrency. One worker process handles
exactly one request at a time (sync worker model), so a slow live-routing
`/calc` blocks a quick `/like` toggle that happens to land on the same
worker.

**What closing it needs**

1. Every singleton in `dependencies.py` (`DBDataLoader`,
   `ProposalRepository`, `ProposalEngagementRepository`,
   `FeedbackRepository`, `AuthRepository`, `ComputeCacheRepository`)
   switched from "one connection held for the process's life" to a
   **connection pool** — borrow per request, return after.
2. Gunicorn's worker class switched from sync to `gthread`/`gevent`, so a
   process can actually interleave requests while one blocks on DB/HTTP I/O.
3. An audit of every adapter's `_cursor()`/commit/rollback pattern for
   pool-borrowed-connection correctness. Today's `self._conn` assumption
   throughout `adapters/*.py` stops holding once a connection isn't
   exclusively owned by one long-lived object.

**Testable by**: a concurrent integration test issuing a slow `/calc` and a
fast `/like` simultaneously against a single worker, asserting the fast one
doesn't wait on the slow one; plus connection-pool exhaustion behaviour
under load.

**Partial precedent already in the tree.** `scripts/refresh_proposals.py`
parallelizes only its live-routing step: `compute_proposal()` takes optional
`loader=`/`router=` arguments so each worker thread gets its own
`DBDataLoader` (cheap — one connection, no heavy precompute) while sharing
the one process-wide `RailRouter` (a pooled `requests.Session`, explicitly
built for concurrent use). DB writes stay sequential on the single
repository connection, which is not thread-safe. That is the narrow version
of this work; the item above is the general one.

---

## 3. `input_params` schema split — dropped

Considered 2026-08-04, **dropped 2026-08-07**. The idea was to split the
`input_params` schema along the `models/` package structure (infrastructure,
compositions, demand, emissions, …) so params tables sit next to their model
domain, and to migrate the flat mode emission factors out of
`models/emissions` constants into an emissions params table at the same
time.

Consequence of dropping it: the flat per-mode emission factors stay
constants in `models/emissions` indefinitely — which locked decision 24
already permits as the single source. Nothing else depended on the split.
