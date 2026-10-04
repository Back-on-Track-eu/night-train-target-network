# models/family — the proposal family (layer L5)

A **family** is every member of one stop list + HOW under the current
pins: one member per (scenario variant, composition), all built on one
shared context, served as one document. It is what the builder's scenario
and composition switches read from without another request, and it is
computed, cached and never edited — a pure function of its inputs
(`adapters/family/README.md` for the persistence side, the wire shape
under "Proposal Family" in `api/README.md`; the design decisions are
summarised at the end of this file).

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
trip build, timetable, demand and evaluation together. So:

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
it from `compute_member()`), and does not run the full `views_to_dict`
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

## Vocabulary and layers

The layer letters appear in comments and docstrings across `models/`,
`adapters/` and `db/` (`member_compute.py`, `db/schema.py`, …). They name
*what is shared at which level*, not packages:

| term | layer | is |
|---|---|---|
| **parameters** | P | calibrated catalogs (`input_params`), scenario pins, measure sets, scenario variants |
| **legs** | L1 | geometry + raw driving time per stop pair on one graph with one resolved custom model (`route_cache`) |
| **trip / timetable** | L2 | trips built from legs: buffer, dynamics, dwell, padding, expert overrides, energy |
| **demand** | L3 | the demand set on the route, seated per OD and class |
| **evaluation** | L4 | cost / revenue / emissions and their views |
| **member** | L1–L4 | one (scenario variant, composition) for one stop list + HOW: route + summary; views on demand |
| **family** | L5 | every member for one stop list + HOW under the current pins — computed, cached, never edited |
| **scenario variant** | P | the flattened axis the frontend addresses: scenario × measure set |
| **proposal** | S | identity + ownership + presentation: stop list, HOW, presented member, name, author, discussion |
| **presented member** | S | what a published proposal shows in the gallery: current base scenario × the author's composition |

A single member is a **1 × 1 family** (`scenario_variant_ids` /
`composition_ids` filters on the family body); there is no single-member
endpoint. `compute_member()` remains the *function* publish, refresh and
the views path run.

## Design decisions (WP18, September 2026)

The decision numbers are cited as "D<n>" in comments of `api/helpers/`,
`api/proposal_family.py` and `member_compute.py`. (The demand model has its
own D-numbers, D1–D31, in `models/demand/README.md`; a bare "D9" in demand
code is one of those.)

| # | decision, as built |
|---|---|
| **D1** | `POST /api/proposal/calc` and `/calc/matrix` are gone. `api/helpers/member_compute.py::compute_member()` is the L1–L4 primitive with the member cache, called by the views path, publish, the on-load fallback and `refresh_proposals.py`. Tests fetch a member as a 1 × 1 family. |
| **D2** | No `route_variants` table. L1 persists per leg in `route_cache.route_segments`, shared across proposals; the family shares built legs in memory (D4). |
| **D3** | Family persistence = one row per key in `family.documents` with the member cache's TTL; nothing per published proposal beyond `proposals` + `proposal_summaries`. |
| **D4** | Route + timetable + demand are built once per (scenario, composition); measure sets multiply evaluation only. Sharing via `FamilyContext` (`MemoLoader`, `MemoRouter`) — `route_factory.py` / `pipeline.run_compute()` unchanged. |
| **D5** | `auto_stop_addition` is `off \| suggest`; the former `add` path is deleted (ROUTE_BUILDER 0.9.34). A family always builds on the input stop list; `suggest` runs once on the presented member and its suggestions ride on the document. |
| **D6** | `POST /api/proposal/publish` `mode: new \| overwrite \| copy` (`copy` = `new` with `based_on_proposal_id`). Load stays `GET /api/proposal/<id>`. |
| **D7** | `scenario.measure_sets` + `scenario.scenario_variants` (materialised); `GET /api/scenarios` exposes both; the family axis and the frontend address `scenario_variant_id`. |
| **D8** | `evaluate_route(…, measures: MeasureSet)` threads identity factors on ticket revenue, energy cost and track access, recorded in the result (CALC 0.9.26). |
| **D9** | Views on the fly: `GET …/views` = `compute_member()` for that member (member-cache hit or one build, then cached). No LRU; the builder never writes every member into the member cache. |
| **D10** | Config: `FAMILY_MAX_MEMBERS`, `FAMILY_WORKERS` (`backend/docker/.env.example`); the `CALC_MATRIX_*` settings are gone. |
| **D11** | Wire contracts carry no provenance, no parameter blocks, no models registry and no duplicated geometry. Static things have their own endpoints: `GET /api/models` (formula/version registry), `GET /api/params/*` (parameters with sources, per scenario). |
| **D12** | `proposals.likes` / `comments` stay in the `proposals` schema (user state *about* a proposal). |
| **D13** | The route fingerprint is not part of the family document (no consumer there); publish gets it from `compute_member()`. |
