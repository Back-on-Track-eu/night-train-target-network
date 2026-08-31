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

Scenario rows are seeded in `db/dev/seed.py` ("scenario" section). The
values that differ between them are built there too — `_with_hsr_allowed()`
and `_with_optimized_timetable()`.

---

## The two axes

Every scenario is a point on two axes.

**Infrastructure** — which physical network. This is the routing graph
(`routing_graph_key`), because it determines every distance and travel
time. `infra_2026` is today's network. `infra_2032` will be the upgraded
network from Jasper's manipulated OSM extract; it arrives with its own
routing instance (`models/route/routing/README.md`, "Multiple Graphs").

**Operating conditions** — what night trains are permitted and how well
they are scheduled on that network. Two levers, cumulative:

- *NT on HSR* — whether night trains may use high-speed lines
  (`track_hsr_allowed`). A policy decision by infrastructure managers, not
  a construction project.
- *Optimised timetables (OPT TT)* — whether night trains receive
  well-designed paths rather than the residual ones they get today
  (`track_buffer_quota_per`).

Three operating conditions per network, so three scenarios today and six
once the 2032 graph exists:

| | Infra 2026 | Infra 2032 |
|---|---|---|
| baseline | `infra-2026` ✅ | pending graph |
| + NT on HSR | `infra-2026-hsr` ✅ | pending graph |
| + NT on HSR + OPT TT | `infra-2026-hsr-opt-tt` ✅ | pending graph |

**"2026" names the network, not the price year.** Every monetary parameter
stays on the calibrated 2032 evaluation-year basis in all three scenarios
(`EUR at 2032 prices`, see `db/schema.py`). A scenario that also moved
prices would confound two effects in one comparison, which is exactly what
the full-snapshot design exists to prevent.

---

## The three seeded scenarios

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

Scenario 2 with a reduced schedule supplement. The rest of this document
is about how much reduction, and why that number is currently provisional.

---

## The optimised-timetable reduction

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

Values run 0.346 (AT) to 0.706 (FR), European mean 0.506.

**Better timetabling acts on 1 and 2 only.** 3 is physics and 4 is our own
model error. This is the single most important fact about this scenario:
scaling the quota as a whole would "optimise away" the router's error and
produce trains that are fast in the tool and impossible in reality.

### How the reduction is built

Convergence toward a best-practice benchmark, not a flat cut:

```
opt_quota = benchmark + (quota − benchmark) × (1 − reduction)      if quota > benchmark
opt_quota = quota                                                  otherwise
```

with, in `db/dev/seed.py`:

```
OPT_TT_BENCHMARK_QUOTA  = 0.35
OPT_TT_EXCESS_REDUCTION = 0.25
```

**Why 0.35.** Austria measures 0.346 over 56 ONTD legs — the lowest value
with strong evidence behind it. It represents a network where night trains
are already well-pathed *and* where the router models line speeds well.
Nothing below it is reachable by timetabling alone, so it is a floor
rather than a target.

**Why 25% of the excess.** Two independent derivations land in the same
band:

*Bottom-up.* The theoretical formula in the calibration document
(`4 + 2.5√(u/18.67) + 6(1−p)`) is the pure timetable supplement the two
RMMS drivers predict. Recomputed for a prioritised night path — night-window
utilisation at ~40% of the daily average, punctuality at a 0.90 target —
the median country falls from 7.5 pp to 6.0 pp: a **1.5 pp** cut. This is
the part we can defend from the drivers alone, and the calibration document
anticipates exactly this use ("precisely what a 'night trains receive
improved priority' scenario would move").

*From published practice.* UIC 451-1 puts the pathing and construction
allowance at 3–5 pp. A prioritised night path plausibly halves it: ~2 pp.
Added to the 1.5 pp above: **~3.5 pp**.

*What the rule produces.* A median cut of **3.9 pp** — the two agree.

Effect per country:

| | AT | NL | DE | EU default | IT | PL | SE | FR |
|---|---|---|---|---|---|---|---|---|
| base quota | 0.346 | 0.421 | 0.489 | 0.506 | 0.536 | 0.570 | 0.678 | 0.706 |
| OPT TT quota | 0.346 | 0.403 | 0.454 | 0.467 | 0.490 | 0.515 | 0.596 | 0.617 |
| journey time | −0% | −1.2% | −2.3% | −2.6% | −3.0% | −3.5% | −4.9% | −5.2% |

A 12-hour pure passage time is scheduled at 17h52 in scenario 1 and 17h27
in scenario 3, using the German quota.

### Why these two numbers are PROVISIONAL

Two reasons, and the second is the blocking one.

**The benchmark over-credits countries whose supplement is physical.**
France at 0.706 and Sweden at 0.678 both run conventional networks a
loco-hauled sleeper cannot exploit, alongside high-speed lines it is not
built for. Some of their excess is item 3 above — physics — and the rule
credits all of it to timetabling. The calibration document flags Great
Britain and Spain as the same profile, currently hidden because they have
no ONTD legs and sit at the European mean.

**The current measurement cannot identify the buffer component at all.**
The calibration's own discriminator is the pair of correlations between
implied supplement and the two drivers. On the 2026-08-17 run they came
out `r = −0.12` against utilisation (expected positive) and `r = +0.09`
against punctuality (expected negative). The document's rule for that
outcome is unambiguous: the residual is mostly router speed error, not
buffer. While that holds, any reduction is an assumption dressed as a
calibration.

### Re-calibrating — the procedure that settles them

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
   `ROUTE_CONTEXT_CALIBRATION.md` and the seed CSVs.
4. **Read §3's two correlations before looking at any level.** This is the
   decision point, not a formality:
   - *Signs as expected* (implied rises with utilisation, falls with
     punctuality) — the residual is genuinely buffer. The theoretical
     formula can be refitted, the buffer component becomes identifiable
     per country, and OPT TT should be rebuilt on it directly rather than
     on a benchmark. `OPT_TT_BENCHMARK_QUOTA` / `OPT_TT_EXCESS_REDUCTION`
     are then replaced by that derivation.
   - *Signs still wrong* — the residual is still dominated by router speed
     error. Fix the passage-time model first. The benchmark rule stays,
     and stays provisional.
5. Predict before running (project rule): state the expected median
   supplement and the expected correlation signs before executing step 2.
   Every defect in batch work here has been caught this way.

Until step 4 resolves, scenario 3 answers "roughly how much is on the
table if night trains were scheduled as well as the best networks manage
today" — an order of magnitude, not a forecast. Its description avoids
claiming precision, and this document is the honest version.

---

## Adding a scenario

1. New full-table snapshot version in each of the five versioned tables
   (`db/dev/seed.py`) — a complete copy, never a partial diff.
2. New `scenario.scenarios` row pinning those five versions plus a
   `routing_graph_key`.
3. A user-facing `description`: what the scenario assumes, in plain
   language, without repository jargon. Someone who has just opened the
   platform reads these.
4. Never repoint or edit a pinned version. Scenario rows are immutable;
   a changed value means a new version and a new scenario row.
