# models/family — the proposal family (layer L5)

A **family** is every member of one stop list + HOW under the current
pins: one member per (scenario variant, composition), all built on one
shared context, served as one document. It is what the builder's scenario
and composition switches read from without another request, and it is
computed, cached and never edited — a pure function of its inputs
(`adapters/family/README.md` for the persistence side,
`docs/2026-09-09_wp18_proposal_family_plan.md` for the design).

The pipeline underneath is unchanged. `models/pipeline.py::run_compute()`
builds one member exactly as it always has; this package only decides
*which* members to build and *what they share*.

| file | does |
|---|---|
| `key.py` | `family_key()` — which pins enter a family's identity: the resolved request (stops + HOW), the resolved axes, the two model versions, and the document's shape version (passed in by the serializer). Nothing about presentation or the caller. |
| `context.py` | `FamilyContext` — a `MemoLoader` (catalogs once per scenario) and one `MemoRouter` per routing graph (raw legs once per variant, copies handed out). Both memos are single-flight, so a fan-out never repeats a computation. `prewarm()` fills them in parallel. |
| `builder.py` | `run_family()` — prewarm, then the presented member (the one whose `suggest` runs), then every other member serially, variants outer, compositions inner. Variants of one scenario share the route and only re-evaluate. Every failure is an error member. |

## Why the shape is what it is

`scripts/bench_member.py` (2026-09-09, Berlin–Wien): a member costs
~238 ms on the plain loader and router, of which ~208 ms is reloading the
five catalogs `run_compute()` touches (stops twice) and ~35 ms is fetching
legs from `route_cache`. Once both are shared, a member is **4 ms** —
trip build, timetable, stopgap demand and evaluation together. So:

- **Prewarm is the only threaded phase.** It is the I/O: one catalog load
  per scenario and one `route()` per distinct leg variant (12 on
  Berlin–Wien across 72 members). `FAMILY_WORKERS` sizes it.
- **The member loop is serial.** 72 × 4 ms of pure Python; threads there
  only contend for the GIL, and the bench measured them losing to serial.
- **The memos are single-flight.** With a naive memo, four threads starting
  cold each loaded the same catalog. A caller of a key in flight waits for
  the owner instead.
- **Legs are copied out of the memo.** `route_trip()` writes buffer and
  dynamics onto the legs it is given and `calc_energy_consumption()`
  writes energy; a shared list would carry one member's physics into the
  next. Shallow copies suffice — only scalar fields are ever written
  (verified across `models/`).
- **Catalogs are shared by reference.** Read-only collections; nothing
  downstream writes to them.

## What a member does not do

It does not serialise (`api/helpers/family_serialize.py`), does not
compute its fingerprint (D13 — no consumer in the document; publish gets
it from `compute_proposal()`), and does not run the full `views_to_dict`
(the summary needs only the whole-route view,
`evaluation_serialize.route_view_to_dict`, at ~3 ms instead of ~50). The
full views of one member are `GET …/members/<sv>/<comp>/views`, computed
on demand and member-cached — a builder never writes 72 members into a
cache the client will read one of.

## Measure sets

Only the evaluate half of the pipeline reads a measure set
(`models/pipeline.py`). The builder therefore keys routes on
(scenario, composition) and, when several variants share a scenario,
builds the route once and calls `evaluate_and_build_views()` per variant.
With the single seeded set (`none`) that path never runs; it is what
WP17 multiplies.
