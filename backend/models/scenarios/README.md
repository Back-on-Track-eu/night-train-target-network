# Scenarios

What a scenario is, which ones exist, and how the values that distinguish
them were arrived at.

A scenario is a complete, self-contained pin: one version of each of the
five versioned `input_params` infrastructure tables, plus the routing
graph. Nothing is inherited or diffed between scenarios — see
`db/README.md` for the versioning contract and `db/schema.py`
(`scenario.scenarios`) for the columns. This document is about *meaning*,
not mechanics: what each scenario claims about the world, and how
defensible that claim is.

Scenario rows are seeded in `db/dev/seed.py` ("scenario" section), which
applies the two operating-condition levers — `_with_hsr_allowed()` and
`_with_optimized_timetable()`. The HSR lever is a flag; the
optimised-timetable values are calibrated in `calib/` and read from its
seed CSV, so the seeder derives nothing.

---

## Measures — the third axis, not a fourth scenario

A scenario says what the infrastructure *is*. It deliberately does not
say what the state *does* about it: whether night train fares are exempt
from VAT, whether traction electricity is exempt from energy tax,
whether track access is charged at direct cost only. Those are political
measures, and they are orthogonal — any measure can apply on any
network under any operating condition.

Expressing them as scenario rows would multiply the grid by every
combination and hide the orthogonality, so they live in their own table
(`scenario.measure_sets`) and the two multiply into
`scenario.scenario_variants`, the axis the API and the frontend address
(`db/README.md`, `db/schema.py`). A variant is one (scenario, measure
set) pair.

One measure set is seeded, `none` — no lever pulled. It is what every
evaluation before this existed implicitly ran under, so its three
factors are 1.0 and adding it changed no number anywhere (CALC 0.9.26,
`models/params.py` `MeasureSet`). WP17 seeds the rates and the versioned
table behind them; the direct-cost regime in particular is not a
discount on the full charge but a different component selection, so it
lands inside `models/infrastructure/tac/calc_tac.py` rather than as a
wider factor.

---

## The two axes

Every scenario is a point on two axes.

**Infrastructure** — which physical network. This is the routing graph
(`routing_graph_key`), because it determines every distance and travel
time. `infra_2026` is today's network; `infra_2032` is the upgraded
network built from Jasper's manipulated OSM extract, imported and
verified on 2026-08-31 (`models/route/routing/README.md`, "Bringing up a
second graph"). Each runs as its own OpenRailRouting instance.

**Operating conditions** — what night trains are permitted and how well
they are scheduled on that network. Two levers, cumulative:

- *NT on HSR* — whether night trains may use high-speed lines
  (`track_hsr_allowed`). A policy decision by infrastructure managers, not
  a construction project.
- *Optimised timetables (OPT TT)* — whether night trains receive
  well-designed paths rather than the residual ones they get today
  (`track_buffer_quota_per`).

**The two levers are independent.** Better pathing is a planning decision
by the infrastructure manager; it does not depend on whether night trains
may use high-speed lines. So the grid is 2x2 per network, eight scenarios:

| | Infra 2026 | Infra 2032 |
|---|---|---|
| baseline | `infra-2026` (v1) | `infra-2032` (v5) |
| + NT on HSR | `infra-2026-hsr` (v2) | `infra-2032-hsr` (v6) |
| + OPT TT | `infra-2026-opt-tt` (v8) | `infra-2032-opt-tt` (v9) |
| + both | `infra-2026-hsr-opt-tt` (v3) | `infra-2032-hsr-opt-tt` (v7) |

The version number in each cell is the single number that scenario pins
across all five versioned tables. Version 4 is outside the grid: it is
the superseded `infra-2026` revision. `infra-2026` remains the live
default (`is_current_base`); the other seven are current lineage heads.

Versions 8 and 9 were seeded on 2026-09-09. Until then the key convention
nested the suffixes (`infra-<network>[-hsr[-opt-tt]]`), which made
optimised timetables inexpressible without the high-speed permission and
so kept a perfectly seedable combination out of the grid — an artefact of
the key format, never a modelling claim. The suffixes are independent
now (`infra-<network>[-hsr][-opt-tt]`); the six older keys parse
unchanged. It is also what lets the frontend's two switches move
independently: `lib/scenarioAxes.ts` enables a toggle exactly when the
state it would produce exists as a scenario.

**The two columns are identical in the database.** Every value in all
five versioned tables is copied unchanged from the 2026 column to the
2032 one. That is not laziness — it is where the difference lives. An
upgraded network is new track, track determines distance and travel time,
and both come from the routing graph. A 2032 scenario that also moved a
tariff would confound two effects in one comparison, which is the thing
the full-snapshot design exists to prevent (`db/README.md`).

**"2026" names the network, not the price year.** Every monetary parameter
stays on the calibrated 2032 evaluation-year basis in all three scenarios
(`EUR at 2032 prices`, see `db/schema.py`). A scenario that also moved
prices would confound two effects in one comparison, which is exactly what
the full-snapshot design exists to prevent.

---

## The eight seeded scenarios

### 1. Infra 2026 — `infra-2026`

The live default (`is_current_base = TRUE`). Today's network, conventional
lines only, and the schedule supplement real night trains carry today.
The realistic baseline: what a night train would cost and how long it
would take if it started running this year.

### 2. Infra 2026 + NT on HSR — `infra-2026-hsr`

Identical to 1 except `track_hsr_allowed = True` for every country.
Journeys shorten wherever a high-speed line parallels the conventional
route and the composition's own `hsr_allowed` permits it — the route
builder ANDs the two flags, so a 160 km/h loco-hauled rake gains nothing
from the permission.

Note what does *not* change: track access charges. `track_tac_*` is
calibrated per country, not per line class, so this scenario does not
price the premium an infrastructure manager would plausibly levy for
high-speed paths. That is a known gap, not a modelling claim.

### 3. Infra 2026 + NT on HSR + optimised timetables — `infra-2026-hsr-opt-tt`

Scenario 2 with a reduced schedule supplement. The optimised-timetable
section below is about how much reduction, and why the baseline it applies
to is currently provisional.

### 4. Infra 2026 + optimised timetables — `infra-2026-opt-tt`

Scenario 1 with the reduced schedule supplement and today's rules on
high-speed lines. It isolates what better planning alone is worth, which
scenario 3 cannot show because it bundles the two levers: on a corridor
where a high-speed line parallels the conventional route, most of
scenario 3's saving is the permission, not the pathing.

### 5, 6, 7, 8. The Infra 2032 quartet

`infra-2032`, `infra-2032-hsr`, `infra-2032-hsr-opt-tt`,
`infra-2032-opt-tt` — scenarios 1 to 4 asked of the upgraded network. The operating conditions and every
tariff are unchanged; what differs is `routing_graph_key`, and therefore
every distance and travel time.

The Hamburg → København corridor is the clearest illustration and was the
acceptance check for the graph itself: 504.4 km / 226 min on `infra_2026`
via Jutland, 350.1 km / 148 min on `infra_2032` across the Fehmarn fixed
link. That is the shape of what these three scenarios add — journeys that
take a long detour today become direct, and the operating-condition
levers then apply on top.

Read `infra-2032-hsr-opt-tt` as the upper bound of the eight: everything
currently under construction or firmly committed, plus both operating
improvements. It is not a forecast, and it inherits scenario 3's
provisional schedule supplement.

**Known gap — crossing charges.** `passage_charges` versions 5–7 are
copies of 1–3, so they hold the crossings that exist today (Storebælt,
Øresund, the Channel Tunnel) and nothing else. Every fixed link the 2032
network adds is therefore priced as if traversing it were free, and 2032
costs are understated by exactly that toll — on Fehmarn, on the very
corridor that makes the network different. This is the same class of
admission as the HSR track-access gap in scenario 2: a known omission,
not a modelling claim. Closing it needs a sourced tariff per new
crossing (Femern A/S publishes assumptions), then a new version pair and
new scenario rows — never an edit to versions 5–7, which are pinned.

**Deployment coupling.** These four cannot be computed by a deployment
that does not run an OpenRailRouting instance for `infra_2032`. The API
answers `503 routing_graph_not_configured` rather than falling back to
another graph (`api/helpers/dependencies.py`, `api/proposal_calc.py`).
Enabling the instance is three lines in `backend/docker/.env`; CI
deliberately does not, so the suite covers these rows by reading them,
never by computing them.

---

## The optimised-timetable reduction

The values live in `calib/`, like every other calibrated domain:

```
calib/opt_tt_calibration.py     the rule, its sources, and the rejected
                                alternatives (module docstring)
calib/OPT_TT_CALIBRATION.md     the numbers it produced — generated
calib/seed/                     opt_tt_buffer_reduction.csv — generated,
                                gitignored, rebuilt at container start
```

`db/dev/seed.py` reads the CSV and applies it; it derives nothing.
Re-run the calibration with:

```
uv run python models/scenarios/calib/opt_tt_calibration.py
```

### What `track_buffer_quota_per` actually holds

Not a timetable buffer. `models/infrastructure/route_context/calib/ROUTE_CONTEXT_CALIBRATION.md`
§3 is explicit that the split between "planners' margin" and "router
optimism" was abandoned deliberately: per country there is one
measurement and two unknowns, and no second observable separates them.
What is seeded is a single **schedule supplement** — everything that makes
a real timetable slower than the router's passage time:

1. construction and pathing allowances the infrastructure manager applies;
2. margin because a night train does not hold priority;
3. speed the train cannot sustain — curves, junctions, restrictions;
4. acceleration and braking the dynamics model misses.

Values run 0.113 (AT) to 0.385 (UK), European prior 0.239, France fixed
at 0.250 as a documented exception (re-calibrated 2026-09-05 as a
**minimum driving time** — the lower quartile of the leg-level residual
rather than its time-weighted mean, which had been carrying the operators'
arrival-hour stretching; that stretching now lives in the timetable layer
as `slack_time_min` in the fixed-night timetable mode).

**Better timetabling acts on 1 and 2 only.** 3 is physics and 4 is our own
model error. This is the single most important fact about this scenario:
scaling the quota as a whole would "optimise away" the router's error and
produce trains that are fast in the tool and impossible in reality.

### How the reduction is built

A percentage-point cut off the country's own **theoretical** timetable
supplement, which is items 1 and 2 and nothing else:

```
opt_quota = quota − SUPPLEMENT_REDUCTION × timetable_buffer_theory_pct
```

with `SUPPLEMENT_REDUCTION = 0.375`. The theory column is
`4 + 2.5√(u/18.67) + 6(1−p)` over network utilisation and long-distance
punctuality, seeded by the route-context calibration and described there
as "precisely what a 'night trains receive improved priority' scenario
would move". Sizing the cut off it rather than off the measured quota is
what keeps the residual's known contamination out of the reduction.

**Why 0.375.** Three independent readings put a European running-time
supplement at 8–9 %, and one published case costs the feasible cut at
37.5 % of it.

- *UIC 451-1* (4th ed., 2000) recommends for loco-hauled passenger trains
  a fixed 1.5 min/100 km plus a speed- and weight-dependent percentage;
  a night-train rake over 500 t at 161–200 km/h sits at 6–7 %, and at
  ~100 km/h average the fixed part adds ~2.5 pp. Total 8–9 %.
- *Hansen & Pachl, Railway Timetabling & Operations* (2014): regular
  recovery time is 3–7 % of pure running time on European railways.
- *The theory column itself*: median 8.1 %, range 6.1–10.2, from an
  entirely different derivation. Three routes, one band.
- *Schittenhelm* (2011, DTU / Rail Net Denmark) then prices the cut. What
  IMs apply is higher than UIC — Rail Net Denmark's rules run 7–13 %
  against UIC's 3–5 %, and a real service carries 16.3 %. To meet the
  political travel-time target on Copenhagen–Odense the supplement has to
  fall from 16 % to 10 %, a 37.5 % cut, which he calls drastic and says
  needs a new philosophy for timetabling and operations. Going further, to
  bare UIC levels, he rejects as leaving a dangerously small margin.

So 0.375 is a national infrastructure manager's own assessment of the
outer edge. The scenario claims that and no more.

Effect on scheduled driving time: **−1.86 % to −3.11 %, median −2.42 %** —
per-country figures in `calib/OPT_TT_CALIBRATION.md`. Every country is
reduced, Austria included.

**What this replaced.** A benchmark rule: converge each country a quarter
of the way from its quota toward Austria's 0.12. Two defects. It gave the
largest absolute cut to the countries whose quota is *least* likely to be
timetable supplement (Sweden 23 %, UK 24 %) and none at all to Austria,
whose quota is 73 % supplement and so has the most headroom in
proportion — the rule punished it for being the floor. And that floor was
one country's calibrated value doing duty as a European constant.

### Why this is still PROVISIONAL

Not for anything in the reduction — for the baseline it applies to.

The route-context calibration's own discriminator is the pair of
correlations between implied supplement and the two drivers. On the
2026-08-17 run they came out `r = −0.12` against utilisation (expected
positive) and `r = +0.09` against punctuality (expected negative). The
document's rule for that outcome is unambiguous: the residual is mostly
router speed error, not buffer. Sizing the cut off the theory column
keeps that contamination out of the *reduction*, but the quota it is
subtracted from still carries it.

The benchmark also over-credited countries whose supplement is physical —
France and Sweden both run conventional networks a loco-hauled sleeper
cannot exploit. The theory-based rule is far less exposed to that, since
it never reads their quota, but the baseline still is.

### Re-calibrating — the procedure that settles it

The extraction predates the gauge-aware routing profiles, the stop catalog
widening to 1,053 stops, and several `ROUTE_BUILDER_VERSION` bumps. Every
one of those changes routed times, so the residual it measured is stale.

1. Rebuild `ontd.route_legs` against the current router and catalog
   (`db/ontd/projection.py`). Needs a loaded ONTD snapshot and a reachable
   routing instance.
2. Run `models/infrastructure/route_context/calib/01_source_extraction.ipynb`
   top to bottom — its last cell rewrites `sources/ontd_buffer_legs.csv`
   and `sources/ontd_buffer_by_country.csv`. Run notebooks from `backend/`
   via `uv run python -m jupyter nbconvert`.
3. Run `02_route_context_calibration.ipynb` to regenerate
   `ROUTE_CONTEXT_CALIBRATION.md`, the seed CSVs and `data/route_context.csv`.
4. **Read §3's two correlations before looking at any level.** This is the
   decision point, not a formality:
   - *Signs as expected* (implied rises with utilisation, falls with
     punctuality) — the residual is genuinely buffer. The theoretical
     formula can be refitted, the buffer component becomes identifiable
     per country, and `SUPPLEMENT_REDUCTION` can then be applied to a
     measured supplement rather than a modelled one.
   - *Signs still wrong* — the residual is still dominated by router speed
     error. Fix the passage-time model first. The theory-based rule stays,
     and stays provisional.
5. Re-run `models/scenarios/calib/opt_tt_calibration.py`, which reads both
   the seed quotas and `data/route_context.csv`, then reseed.
6. Predict before running (project rule): state the expected median
   supplement and the expected correlation signs before executing step 2.
   Every defect in batch work here has been caught this way.

Until step 4 resolves, the scenario answers "roughly how much is on the
table if night trains were pathed as well as published practice says is
achievable" — an order of magnitude, not a forecast.

## Adding a scenario

1. New full-table snapshot version in each of the five versioned tables
   (`db/dev/seed.py`) — a complete copy, never a partial diff. The
   version grid at the top of that file's scenario section is the one
   place the numbering lives; extend it there rather than adding another
   hand-written builder.
2. New `scenario.scenarios` row pinning those five versions plus a
   `routing_graph_key`.
3. A migration under `db/dev/sql/migrations/` doing the same to server
   databases, which are never reseeded (`db/migrate.py`). See
   `2026-08-31_infra_2032_scenarios.sql` for the pattern: copy forward
   with `INSERT ... SELECT` against the server's own rows and a column
   list read from `information_schema`, so a database whose calibration
   has moved on carries its own values rather than literals from the day
   the migration was written.
4. A user-facing `description`: what the scenario assumes, in plain
   language, without repository jargon. Someone who has just opened the
   platform reads these.
5. If the scenario pins a routing graph that is not already live, say so
   in the handover to deployment — a seeded scenario nobody can compute
   is a worse failure than a missing one.
6. Never repoint or edit a pinned version. Scenario rows are immutable;
   a changed value means a new version and a new scenario row.
