# The input format

Four kinds of file describe a build. They are separate because they change for
different reasons and are reviewed by different people.

| file | answers | changes when |
| --- | --- | --- |
| `datasets/<name>.yml` | which OSM to fetch | you add a test region |
| `catalogue/<name>.yml` | what will be built, and why | a project's date or scope is researched |
| `targets/<name>.yml` | which network to build | you pick a horizon, or disagree with a date |
| `changes/library.yml` | how a rewrite is mechanically performed | you learn something new about OSM tagging |
| `connectors/<name>.yml` | which junctions OSM is missing | a survey finds one and someone verifies it |

The split that matters most is catalogue vs. changes. `railway=construction →
railway=rail` is mechanics that apply identically everywhere. "The Brenner Base
Tunnel opens in 2032" is a claim about the world that needs a citation. Putting
them in one file is how the previous version ended up promoting 24,500 ways
Europe-wide while claiming to describe 19 named projects.

---

## `targets/<name>.yml`

```yaml
name: 2032
description: European rail network as assumed complete by the end of 2032
dataset: europe            # datasets/europe.yml
catalogue: europe          # catalogue/europe.yml
as_of: 2032-12-31          # THE SELECTOR
date_basis: latest         # official | latest   (default: latest)

force_in:
  - id: brenner-base-tunnel
    reason: >-             # required
      Official target is 2032 and the tunnel is ~90% excavated.
force_out: []

connectors: 2032           # connectors/2032.yml
all_projects: false        # ignore dates entirely — see all-planned.yml
extra_rules: []            # raw rules, for what-ifs that are not projects

graphhopper:
  xmx: 6g
  config: {}               # merged over the backend's own config.yml
```

### `as_of` and `date_basis`

A project is in the network when its opening date is on or before `as_of`.
`--as-of DATE` overrides the file, and produces a *separate* extract and graph
cache (the slug becomes `<name>@<date>.<dataset>`), so two horizons off one file
cannot overwrite each other.

`date_basis: latest` uses the most recent reported date; `official` uses the
operator's own target. Megaprojects slip late and rarely early, so `latest` is
the defensible default and `official` is the optimistic scenario.

**There is no baseline target.** The baseline is `--as-of` today: nothing has
opened, no rule fires, and the transform is the identity (it hardlinks rather
than rewriting a gigabyte).

### `force_in` / `force_out`

Not symmetric, deliberately.

`force_out` is unconditional. Excluding a project can only make a network more
conservative, never wrong.

`force_in` means **"believe this project's official date rather than the
pessimistic one"**. It is not unconditional: a project whose *official* date is
also after `as_of` stays out, and says so. An unconditional include would drop a
2032 tunnel into the baseline the moment anyone ran `--as-of` today — and the
baseline is what every other date is measured against. If you want a project in
ahead of both its own dates, its catalogue dates are wrong; fix them there,
where the sources are.

Both require a `reason`. Overriding a dated, sourced entry is a modelling
decision and this is the only record of it.

---

## `catalogue/<name>.yml`

```yaml
- id: fehmarn-belt                   # unique, stable; used by connectors
  name: Fehmarn Belt Fixed Link
  corridor: Puttgarden (DE) – Rødbyhavn (DK)
  countries: [DE, DK]
  impact: new-link
  opening:
    official: "2029-06"              # required
    latest: "2031"                   # defaults to official
    note: >-
      Femern A/S confirmed in January 2026 that ...
  scope:
    ways: [976707770, 304926270]     # precise — from `osm-survey`
    bbox: [54.30, 10.90, 54.80, 11.65]
  changes:
    - promote: construction
    - promote: disused
    - drop_oneway
  osm:
    lifecycle: [construction, disused]
    failure_modes: [lifecycle-value, namespaced-attrs]
    verified: "2026-08-16"
    note: >- ...
  probe:
    from: { name: Hamburg Hbf, lat: 53.5528, lon: 10.0065 }
    to:   { name: København H, lat: 55.6727, lon: 12.5641 }
    via_bbox: [54.30, 10.90, 54.80, 11.65]
    baseline: Jutland and the Great Belt, roughly 470 km
  sources:
    - title: ...
      url: ...
```

`changes: []` is legal and means "already `railway=rail`, nothing to rewrite".
Those entries earn their place by carrying a probe: they are control cases that
must route at every date, so a failure points at a stale extract or a broken
import rather than at the tagging.

### Dates

`YYYY`, `YYYY-MM`, `YYYY-MM-DD`, resolved to the **last day** of the period. So
`"2032"` is 2032-12-31 and is in a 2032 network.

Approximate forms — `2033+`, `mid-2030s` — are refused. Which year to model is
a decision for the entry, with a source, not for a parser guessing at a suffix.

### `scope`

Where the changes apply. **Way ids win when both are given**; the bbox is then
documentation.

| | precision | cost |
| --- | --- | --- |
| `ways:` | exact | a hash lookup — *cheaper* than no scope at all |
| `bbox:` | coarse: **any single node** inside the box puts the whole way in scope | forces a node-location index over the whole pass |

Every scope in the shipped catalogue is still a bbox. `osm-survey project
<target> <id>` turns one into a way list.

### `changes`

Named entries from `changes/library.yml`, opted into per project:

```yaml
- promote: construction                                  # lifecycle
- promote: { lifecycle: proposed, untyped: true }        # + the weak spelling
- promote: { lifecycle: disused, scope: { bbox: [...] } } # per-change scope
- drop_oneway
- default: { maxspeed: "200" }
- set: { usage: main }
```

**Order within a project does not matter.** Expansion runs in a fixed phase
order — promote, drop_oneway, set, default — because `drop_oneway` keys off the
marker the promotions write, and requiring authors to remember that would be a
footgun whose failure is silent (the rule simply matches nothing).

**Order *between* projects does matter, where their scopes overlap.** Rules
chain, and a promotion rewrites `railway` away from the lifecycle value it
matched on — so once one project has promoted a way, a later project's rule no
longer matches it. A way in two overlapping bboxes is attributed to whichever
project appears first in the catalogue, and the second reports `0 <-- matched
nothing` for that rule.

This is the right behaviour (nothing is promoted twice) but it makes
attribution first-come-first-served, and it is the strongest practical argument
for `scope.ways` over `scope.bbox`: an explicit way list cannot overlap by
accident. When a project you expect to fire reports zero, check whether a
neighbour with an overlapping box got there first before assuming the bbox is
wrong.

`promote` handles all three OSM spellings:

| spelling | tags | opted in by |
| --- | --- | --- |
| prefixed | `railway=construction` + `construction:railway=rail` | always |
| short | `railway=construction` + `construction=rail` | always |
| untyped | `railway=construction` alone | `untyped: true` |

`disused`, `abandoned` and `razed` **refuse to run without a scope**.
Europe-wide, `railway=disused` is thousands of kilometres of lifted branch line
nobody is rebuilding; inside a project's scope it means the corridor is shut
*because* it is being rebuilt. They also skip anything with a `service` tag,
which keeps yards, sidings and harbour track out.

### Markers

Every rewritten way carries:

```
ntn:project=fehmarn-belt
ntn:change=promote:construction
ntn:opening=2031-12-31
ntn:oneway-dropped=yes          (where it applied)
ntn:connector=<id>              (on stitched ways)
```

So a computed route is auditable per project *and* per date — a route through
track opening in 2031 can be told from one that only needs what is already
built.

---

## `datasets/<name>.yml`

```yaml
name: fehmarn
description: Fehmarn Belt corridor
regions:                          # Geofabrik paths, merged with osmium
  - europe/denmark
  - europe/germany/schleswig-holstein
  - europe/germany/hamburg
clip: [53.3, 8.0, 56.2, 13.0]     # optional, applied after the merge
```

`osm-pipe download` fetches each region resumably, verifies it against
Geofabrik's published `.md5`, merges, clips, and writes a provenance record
with the URLs, hashes and the OSM snapshot timestamp — which is what makes a
graph cache's `network.json` mean anything, given GraphHopper records
`datareader.data.date=1970-01-01`.

---

## `connectors/<name>.yml`

```yaml
connectors:
  - id: grossenbrode-throat
    project: fehmarn-hinterland-de   # must exist in the catalogue
    reason: >-                       # required by review, not by the parser
      Promoted track ends 11 m short of the live line; drawn by two mappers
      and never merged. Checked against the 2029 track plan.
    a: 9573947076                    # real OSM node ids, and a != b
    b: 1621074811
    via: [[54.37, 11.02]]            # optional interior shape points
    tags: { maxspeed: "160" }
```

Both endpoints must be node ids that **already exist in the extract**. That
shared id is the entire mechanism — GraphHopper joins ways that share a node
and nothing else. A connector with placeholder ids or bare coordinates joins
nothing while looking perfectly correct on a map, so `stitch` aborts on an id
it cannot find rather than warning.

A connector over 500 m is reported as invented track. Still allowed; said out
loud.

---

## `changes/library.yml`

The mechanics: which attributes `promote` lifts out of the lifecycle namespace,
which defaults it fills where OSM is silent, which lifecycles require a scope.
Editing it changes every project at once, which is exactly why no project edits
it.
