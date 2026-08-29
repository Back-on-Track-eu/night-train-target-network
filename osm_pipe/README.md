# osm_pipe — the rail network as of a future date

Build a GraphHopper graph cache containing the whole European rail network
*plus* the changes we expect between today and a date you choose. The app then
routes on it, and the economic model runs against a future network.

Two programs, deliberately separate:

| | |
| --- | --- |
| **`osm-pipe`** | the build pipeline: download → extract → transform → stitch → import. Needs `osmium` and `pyyaml`. |
| **`osm-survey`** | reads OSM and works out what the catalogue should say. Never runs as part of a build; prints YAML for a human to paste. Needs the `survey` extra. |

---

## Why this exists

A GraphHopper custom model filters and weights edges that already exist. It can
never create one — and `railway=construction` ways are not merely unweighted at
import, they are **never imported**: OpenRailRouting's `RailAccessParser`
admits only `rail`, `light_rail`, `tram`, `subway` and `narrow_gauge` and
returns `CAN_SKIP` for everything else.

So there is no request-time switch for a future network. The only lever is the
`.pbf` handed to the import, which is what this pipeline produces.
[`docs/current_pipe.md`](docs/current_pipe.md) documents the import as it works
today, and is the thing to read first.

## The idea in one page

The graph is always the **whole** network — every existing `railway=rail` way
is imported regardless. What the pipeline adds is a **delta**: the corridors
that open between now and a horizon.

That delta lives in `catalogue/europe.yml`, which holds every construction
project we know about **at every horizon**, each with an opening date and a
source. A target picks a date, and the date selects:

```bash
osm-pipe projects 2032                    # what that date selects, and why
osm-pipe build    2032                    # build it
osm-pipe build    2032 --as-of 2040-12-31 # same catalogue, later network
osm-pipe build    2032 --as-of 2026-08-29 # same catalogue, today's network
```

Two consequences worth knowing up front:

- **There is no baseline target.** The baseline is `--as-of` today: no project
  has opened, no rule fires, and the transform is the identity. `diff` between
  two dates is then the natural comparison.
- **Nothing changes unless a project asks for it.** A corridor nobody
  catalogued does not appear, however clearly OSM marks it as planned. That is
  the point — it is what makes a 2032 journey time attributable — and it is
  also the main way to be wrong. Run `all-planned` and diff against it to see
  exactly what the catalogue is missing.

## Pipeline

```
        data/raw/<dataset>-latest.osm.pbf        Geofabrik, merged and clipped
                    │
   ① download       │  curl + md5 + osmium merge
                    ▼
   ② extract        │  osmium tags-filter          35 GB -> 0.26 GB
                    ▼
        data/interim/rail-<dataset>.osm.pbf
                    │
   ③ transform      │  catalogue + as_of -> tag rewrites
                    ▼
        data/interim/<target>.<dataset>.transformed.osm.pbf
                    │
   ④ stitch         │  connectors/<name>.yml — hand-authored junctions
                    ▼
        data/interim/<target>.<dataset>.osm.pbf
                    │
   ⑤ import         │  the backend's own docker-openrailrouting image
                    ▼
        data/graph-caches/<target>.<dataset>/ + network.json
                    │
        ┌───────────┴───────────┐
   ⑥ serve                 osm-pipe install
        │                        │
   ⑦ verify              the app routes on it
```

Stages are independently re-runnable and skip themselves when their output
exists; `--overwrite` forces a rebuild.

### What it costs

Measured on full Europe, MacBook Pro:

| stage | time | note |
| --- | --- | --- |
| ② extract | ~3 min | 34.8 GB → 260 MB, four passes by `osmium` |
| ③ transform | **~10 min** | the expensive one, and it prints a heartbeat every 2 M objects so it is not mistaken for a hang |
| ④ stitch | seconds | a hardlink when there is nothing to weld |
| ⑤ import | ~3 min | ~6 GB heap, against the 24 GB the app's own unfiltered import needs |

Transform dominates because **every scope in the shipped catalogue is a
bbox**, and a bbox needs the object's coordinates — so the pass carries a
`flex_mem` node-location index over the whole extract (~400 MB resident). Way
ids need no index at all: a target scoped entirely by `scope.ways` is *faster*
than an unscoped one, because most rules never reach their tag matcher. That is
the real payoff from `osm-survey corridors`, beyond attribution.

On a country dataset the whole chain is under a minute, which is why `-d
fehmarn` and `-d austria` are where you iterate.

### ② extract is the stage that makes this practical

The app's own import hands GraphHopper the entire 35 GB and indexes half a
billion nodes before the access parser discards everything that is not railway
— which is where its 24 GB heap and 20–40 minutes go. Filtering first leaves
0.26 GB, and the same import then runs in ~6 GB and ~3 minutes.

### ③ transform: what a project does to the data

Four mechanisms, in the order a corridor needs them.

**Promote the lifecycle value.** Move the value from the lifecycle key onto
`railway`, so the way survives `RailAccessParser`. A rename, not an invention —
OSM's scheme means the truth is already in the data.

**Lift the namespace.** OSM moves every attribute the router reads under the
prefix: `construction:gauge`, `construction:electrified`. The parsers read bare
keys only, so renaming `railway` alone yields an edge with no gauge and no
electrification. It survives the profile by luck (an absent gauge encodes as 0,
which is allowed) and reads as diesel to the energy model.

Order is fixed and load-bearing: **rename, unset, set, default**. Defaults land
last, which is what makes "real mapped data wins" true rather than aspirational.

**Reopen what is closed for rebuilding — but only where that is true.** When a
line closes for reconstruction OSM correctly retags the old alignment `disused`
while the new one appears as `construction`. Promote only construction and the
corridor still has holes. But `railway=disused` Europe-wide is thousands of
kilometres of lifted branch line nobody is rebuilding, so promoting it is
refused without a scope.

**Weld the missing junctions.** Promotion changes tags, not topology. See ④.

### ④ stitch: the junctions OSM does not have

Mappers draw a planned alignment as a standalone way whose endpoint sits *on
top of* an existing junction without being the same node. GraphHopper joins
ways that share a node id and nothing else, so the promoted line becomes its own
component, falls below `prepare.min_network_size: 200`, and is deleted at
import — silently, at every layer.

A connector is one way referencing two node ids that **already exist**. Both
ends being real nodes is the entire mechanism: the new way is welded to
whatever ways those nodes belong to, with no snapping and no ambiguity. A
connector with placeholder ids or bare coordinates joins nothing while looking
perfectly correct on a map, so `stitch` aborts on an id it cannot find rather
than warning. A connector over 500 m is reported as invented track.

### ⑦ verify: did any route actually change?

Each project carries a probe: two stations whose best path should move once it
opens, plus the box the new path must pass through. `via_bbox` is what makes it
a test rather than a stopwatch — a route can get faster for unrelated reasons,
but it can only pass *through* the new corridor if the corridor is in the graph.

| verdict | meaning |
| --- | --- |
| `PASS` | the target route passes through the corridor and the baseline does not |
| `ALREADY` | the baseline already goes this way — an open project, or a wide box |
| `SAME` | both routes identical: the promotion had no effect. **A failure.** |
| `FAIL` | the target has no route where the baseline had one — a change broke something |
| `NO ROUTE` | neither side routes — off-region, or probe coordinates snapping to nothing |
| `BASELINE ERROR` | the baseline server is down or still loading |

`SAME` counts as a failure on purpose: a silent no-op is the exact thing this
stage exists to catch. `--allow-same` opts out.

`NO ROUTE` does **not** count. On a country extract it is the normal answer for
every project outside the region — Bordeaux does not route on a Danish graph —
and counting it would make the gate useless exactly where it is cheapest to
run. It is reported separately, and on `-d europe` the same line is a real
finding.

One caveat on the numbers: `verify` sends **no custom model**, while the
backend builds one per request. These are the graph's own times, not the
model's — the right isolation for a data test, but they will not match the app.

---

## Setup

```bash
brew install osmium-tool          # apt install osmium-tool on Debian
cd osm_pipe
uv sync --extra dev --extra survey
```

Pinned to Python 3.12: pyosmium 3.7 publishes no wheels past cp312, and on a
newer interpreter `uv` falls back to a source build needing CMake and Boost. If
you see `RuntimeError: CMake must be installed`, run `uv python pin 3.12` and
re-sync.

The OpenRailRouting image must exist before stage ⑤:

```bash
cd backend/models/route/routing/docker && docker compose build
```

## Datasets

`-d/--dataset` names a file in `datasets/` and flows through every path, so a
country test and the full run coexist safely.

| dataset | download | rail extract | what it is for |
| --- | --- | --- | --- |
| `fehmarn` | 706 MB | 3.8 MB | DK + Schleswig-Holstein + Hamburg. The benchmark: Hamburg–København should stop going via Jutland. |
| `austria` | 808 MB | 14 MB | **Koralm is the control** — it opened Dec 2025, so it must route at *every* date. Semmering is the date test. |
| `europe` | 34.8 GB | ~260 MB | the real thing |

Start with `fehmarn` or `austria`, not the 35 GB download.

### The date test, end to end

One catalogue, one extract, two dates. Semmering opens 2030:

```bash
osm-pipe download austria
osm-pipe build 2032 -d austria --as-of 2029-12-31 --skip-graph   # 9 projects
osm-pipe build 2032 -d austria --as-of 2031-12-31 --skip-graph   # 14 projects
osm-survey diff 2032 -d austria --as-of 2031-12-31 --baseline-as-of 2029-12-31
```

At 2029 Semmering is out; at 2031 it promotes 9 ways. And the diff says
something useful straight away:

```
                 baseline       target        delta
network           9,353.1      9,353.1         +0.0
island              211.3        266.9        +55.6
planned           2,624.3      2,568.6        -55.6

promoted out of `planned`              55.6 km
  ...joined the network                 0.0 km
  ...became an island                  55.6 km

project                         network     island     pruned
semmering-base-tunnel               0.0       55.6        0.0
```

55.6 km promoted, **none of it reachable**. It landed in `island` rather than
`pruned` — the component is large enough to survive `min_network_size`, so
GraphHopper keeps it and simply never routes over it. Either way no route
moves, and `verify` would report `SAME` with nothing to explain why.

The survey then said why:

```bash
osm-survey project 2032 semmering-base-tunnel -d austria
```

```
# --- corridor 394410141 ---
#   135 01
#   58.1 km over 23 way(s); attached at 6 node(s)
#   stage: constructionx15, proposedx6, abandonedx2
#   ! mixes 3 lifecycle stages — likely several different things
#   operator: ÖBB-Infrastruktur AG   opening_date: 2027
```

The corridor is *not* uniformly `railway=construction`. Promoting only
construction left the six proposed segments alone, which severed the chain.
Adding `- promote: proposed` to the catalogue entry:

```
promote: construction         55.6 km promoted,  0.0 joined the network
+ promote: proposed           56.8 km promoted, 56.8 joined the network
```

Worth internalising: this looked exactly like a missing-junction problem and
was not one. No connector would have fixed it — the corridor was severed by
its own tagging. **Check the lifecycle mix before reaching for
`osm-survey connectors`.**

## Authoring the catalogue

Every `scope:` in `catalogue/europe.yml` is currently a bbox, and a bbox is
coarse: any single node inside it puts a whole way in scope. `osm-survey` turns
one into an exact way list.

```bash
osm-survey project 2032 fehmarn-belt -d fehmarn
osm-survey corridors austria --bbox 47.55,15.60,47.75,15.90
```

It groups lifecycle-tagged ways into connected chains, measures each, reports
whether it touches routable track, and prints a `scope:` block to paste. It
prints and never writes — which ways belong to a named project is a claim about
the world.

## When a target changes no route

The normal failure, and a silent one. Work through it in this order.

```bash
osm-survey diff 2032 -d fehmarn        # where did the promoted track go?
```

`diff` reports how much track left `planned` and whether it landed in
`network` — or in `island` / `pruned`, which means GraphHopper deleted it at
import. Four causes, in order of how often they have actually bitten:

1. **The project promoted only some of the corridor's tagging.** By far the
   commonest, and the least obvious, because the corridor is *mostly* there.
   A chain is only continuous in the graph if **every** spelling and **every**
   lifecycle stage in it was promoted. Two live examples:
   - Semmering is 15 `construction` + 6 `proposed`. Promoting construction
     alone severed it and stranded all 55.6 km as an island.
   - The Vogelfluglinie has 25 ways using the bare `railway=disused` spelling
     with no sub-tag. `promote:` skips those unless you write
     `- promote: {lifecycle: disused, untyped: true}`, and skipping them broke
     the corridor at the Fehmarn Sound — a 12 km hop that routed 648 km round
     via Jutland.

   `osm-survey project <target> <id>` prints the stage and spelling
   histograms and now warns about both cases outright.
2. **Stranded.** The promoted line touches nothing. `osm-survey corridors`
   says `NOT attached to routable track`; `osm-survey connectors` ranks the
   missing junctions and prints entries to weld.
3. **Promoted to an invisible value.** A rule yielding `railway=light_rail`
   drops the way from both the map and the router. Watch the `total` row.
4. **In the graph, but not chosen.** `diff` shows it under `network` and
   `verify` still says `SAME` — the router prefers another path. Check
   `maxspeed` on the promoted ways.

Cause 1 is worth internalising because it *looks* exactly like cause 2 and no
connector will fix it. **Check the lifecycle and spelling mix before reaching
for `osm-survey connectors`.** A useful sanity probe is to walk the corridor
station by station against the running router — a 12 km hop coming back as
648 km localises the break in one shot, which the gap list cannot do when the
two sides are not a pair of near-touching dangling ends.

```bash
osm-survey connectors 2032 -d fehmarn --project fehmarn-hinterland-de
#   ...review each one, keep the real ones, write a reason...
osm-pipe build 2032 -d fehmarn --overwrite
```

A useful trick while debugging: set `--min-network-size 5` on the survey **and**
`--gh-set prepare.min_network_size=5` on the build, re-import, and confirm the
edges exist at all before going hunting for a missing junction.

## Serving it to the app

```bash
osm-pipe install 2032 -d europe
docker compose -f backend/docker/docker-compose.yml up -d --force-recreate openrailrouting
osm-pipe install --restore     # put the stock cache back
```

`install` symlinks the built cache to the path compose mounts. The container's
entrypoint checks for `properties.txt` before downloading the stock 5–10 GB
cache, so it finds ours and skips the download.

Three things to watch:

- **One network at a time.** There is no request-time switch. Compare by
  running two servers (`osm-pipe serve`) rather than by swapping the mount.
- **A country-scoped cache fails everywhere else.** Install `2032.europe`, not
  `2032.fehmarn`, unless every stop pair is inside Denmark or Schleswig-Holstein.
- **Nothing records which graph produced a stored route.** `osm-pipe` writes
  `network.json` beside every cache, but the backend does not read it, and
  `ROUTE_BUILDER_VERSION` does not know the network changed. **Do not publish a
  proposal from a scenario cache** until that is wired up.

## Layout

```
osm_pipe/
├── docs/current_pipe.md   how the graph cache is built today
├── datasets/              which Geofabrik regions to fetch and merge
├── catalogue/             every project, at every horizon, with sources
├── targets/               a date, a dataset, and the judgement calls
├── changes/library.yml    what `promote:` and `drop_oneway` mechanically do
├── connectors/            hand-authored junctions, reviewed in a PR
├── src/osm_pipe/          the build pipeline
├── src/osm_survey/        the separate analysis
└── data/                  gitignored — raw/ interim/ graph-caches/
```

## Known limits

- **Nothing here can invent a line OSM does not draw.** Every rewrite operates
  on existing geometry, and a connector joins nodes that already exist. An
  alignment with no OSM geometry — CPK's, in places — needs a hand-drawn `.osm`
  patch merged with `osmium merge`. That stage does not exist.
- **Every scope is still a bbox.** No corridor has been surveyed yet, so
  per-project attribution is approximate. Rail Baltica's box is the worst
  offender: five degrees of latitude, and its 1435 mm default applied to
  unrelated track would silently make the wrong network routable.
- **Route relations are not usable as a scope.** A PBF is nodes, then ways,
  then relations, so member lists arrive after every way is written; scoping by
  relation needs a first pass. And a `route=railway` relation usually traces
  the live alignment, not the construction ways we want.
- **`pyosmium` is pinned `<4`, which pins Python to 3.12.**
