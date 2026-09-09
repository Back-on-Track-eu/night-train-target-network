# Frontend handover — David → Bjarne

**Living document.** Backend changes that reach the API contract or change
what the UI should show, in one place. Updated after each change.

Last update 2026-09-07. Covers 2026-08-17 → 2026-09-07:
`ROUTE_BUILDER_VERSION` 0.9.23 → 0.9.33, `CALC_VERSION` 0.9.22 → 0.9.25,
the scenario restructure, and the calc matrix (§12 — **start there if you
are looking at the viewport rearrangement**).

> **FYI 2026-09-06 — existing night trains all dashed.** Backend-only
> bootstrap bug (the routing step of the ONTD load never ran on persisted
> databases); your dashed rendering of `geometry_routed = false` was
> correct and stays as it is. After the fix most existing routes come back
> solid; the ones still dashed are genuine data gaps (ONTD coordinate
> defects, Sicily until the ferry edge lands). The reason is stored per
> route in `ontd.route_summaries.routing_status` / `routing_error` but
> not exposed on `POST /api/proposals` — say if a tooltip would be
> useful and it joins the next `api.ts` batch. No type change now.

**If you read one section:** §6 is the only one with a decision in it. §1–§5
are mostly "this field now exists, show it if you want".

| | | Action |
|---|---|---|
| §1 | New stop catalog and the search it needs | done your side, one gap |
| §2 | Layover, and what parking now costs | optional display |
| §3 | Standard composition + field order | needs your call |
| §4 | Track gauge routing | new field + new error code |
| §5 | Scenarios and two routing graphs | new field, names changed |
| §6 | `api.ts` audit — the actual to-do list | **start here** |
| §7 | `uic_ref` can hold more than one code | no type change |
| §8 | Routes now prefer electrified track | no type change, results move |
| §9 | Expert timetable mode | new request block + 2 new fields |
| §12 | Calc matrix, scenario `dimensions`, five summary KPIs, the viewport rearrangement | **implemented in `frontend/` on this branch — review, not to-do** |

---

## `Formula.summary` on every documented formula — CALC 0.9.24 / route builder 0.9.31 / energy 1.1.1

`models.evaluation.formulas[key]` gained a **`summary`** field: one
self-contained sentence naming what the value is. `latex` and
`description` are unchanged and still shipped.

It exists because the cost-breakdown popover has no room for the full
description (`tac_eur`'s runs eight lines). The popover now renders
`summary` plus a link to `/docs/cost/<slug>` and nothing else — the
formula, the input legend and the rates table moved to the documentation
site.

**Deep-link contract:** the slug is the formula key with a trailing
`_eur` dropped and underscores turned to hyphens (`tac_eur` →
`/docs/cost/tac`). Implemented in `frontend/src/lib/factorFeedback.ts`
and in `backend/scripts/model_docs/render_site.py::cost_slug`, with tests
pinning the emitted page names. Changing one without the other is a 404
on every popover.

**Also on the API:** `POST /api/feedback` is now rate-limited
(`config.FEEDBACK_RATE_LIMIT`, default `5 per minute;20 per hour`, per
gunicorn worker) and can return **429**. A new `Documentation` category
exists for docs-page feedback, with the page path as `sub_category`.

**When this stops applying:** never for the summary field — it is
required on the dataclass. The docs-link contract stops applying only if
the site's page-per-node layout changes.


## 1. New stop catalog and the search it needs

**Backend: `ROUTE_BUILDER_VERSION` 0.9.25 (2026-08-18), extended since.**

The stop catalog was replaced wholesale. `db/dev/seed.py`'s 58 curated stops
and the ONTD-derived seed CSV both gave way to the stop classification
pipeline's export (`backend/models/infrastructure/stops`), which is now
roughly a thousand stops keyed on OSM ids.

Two consequences you already felt:

**Stop ids changed shape.** `DE_BERLIN_HBF` became `osm:n3856100103`. Any
stored id — in a bookmark, a share link, a test fixture — predates the
catalog and no longer resolves.

**The list got big enough that a dropdown stopped working.** That is what
`StopSelect.vue` now solves, and the approach there is right: one lowercase
haystack per stop built once per load, covering display name, Latin/ASCII
transliterations, and city and country names in *every* catalog language.
That last part matters — a German user typing "Prag" and a Czech user typing
"Praha" both need to find the same station.

The `status` prop distinguishing loading / failed / genuinely-empty is the
detail I would have got wrong, and it is worth keeping that discipline
elsewhere: an empty array means three different things.

**The one gap:** stops carry `gauges_mm` (see §4) and a `provenance`
category the catalog exposes but the UI never surfaces. Not urgent — flagged
because gauge is now the reason some stop pairs are unroutable, and a user
who cannot see it has no way to understand the error in §4.

**Ongoing:** the catalog is Drive-hosted, republished as a new version of
the same file, and the seed log prints the count it loaded. If a stop you
expect is missing, the catalog version is the first thing to check, not the
API.

---

## 2. Layover, and what parking now costs

**Backend: `ROUTE_BUILDER_VERSION` 0.9.23 (2026-08-17).**

A route now reports its **scheduled layover** — the gap between the arrival
that ends one trip at a terminal and the departure that starts the next,
wrapped forward a day where the return departs earlier in clock terms than
the inbound arrived.

The route always knew this and never reported it. The facility calibration
needs it because Europe prices stabling per started hour, per started 24h
period, or per occupation — and because a free allowance longer than the
layover zeroes the charge entirely. So layover is not a display curiosity;
it is an input that visibly moves the parking cost line.

Where it appears: each entry in `route.parkings[]` carries `hours`.

Two behaviours worth knowing before you render it:

- A route with no second trip to depart again reports `0.0` rather than a
  guess. Zero means "nothing to stable", not "missing data".
- Payloads stored before 0.9.23 carry no layover at all. Those stay
  evaluable and simply price no stabling — understated, and visibly so.

If you show a parking breakdown, showing the layover hours next to it makes
the number explicable. Optional, but it is the difference between "€340" and
"€340, because the train sits for 9 hours in Oslo".

---

## 3. Standard composition and the field order

**This one needs your judgement, not just an implementation.**

The composition picker currently sits high in `ComputeInputsPanel.vue`,
above the fold, with equal visual weight to the stops. That ordering made
sense when there were two trains and picking one was half the exercise.

It no longer matches how people actually use the tool. From the InnoTrans
testing sessions, users think about *where the train goes* first and *what
train it is* second — and most never change the composition at all. Having
it high implies a decision they do not want to make yet, and the interviews
suggested it reads as a required step rather than an optional refinement.

**What I would like:**

1. A **standard composition** — one sensible default, preselected, so a
   proposal computes without touching the picker at all.
2. The composition field **moved down**, below the route inputs, framed as a
   refinement rather than a prerequisite.

**The backend piece is not done yet.** There is no `is_standard` flag on
`input_params.compositions` today. Before I add one, I would rather know
which shape helps you: a boolean on each composition, or a single
`standard_composition_id` alongside the list. The boolean is more flexible;
the single id is harder to get into an inconsistent state. Your call, since
you consume it.

Until then you can hardcode a default id, but tell me and I will treat the
flag as blocking rather than nice-to-have.

---

## 4. Track gauge routing

**Backend: `ROUTE_BUILDER_VERSION` 0.9.27 and 0.9.28 (2026-08-29).**

Routes are now gauge-aware. Each trip resolves **one** track gauge from its
stops' `gauges_mm` and routes on that gauge's own routing profile.

**What newly works.** Broad-gauge trips that used to fail as opaque snap
errors now route: Rovaniemi–Helsinki, Kyiv–Lviv, Dublin–Cork,
Madrid–Lisboa. If you have test fixtures asserting those fail, they are now
wrong in the good direction.

**New field.** `general_parameters.track_gauge_mm` on each trip — which
profile carried it. It is 1435 across the whole network west of the
break-of-gauge lines, so it is informative exactly where routes were
impossible before. Worth showing on Iberian, Irish, Finnish and Ukrainian
routes; noise everywhere else.

**New error you must handle: `422 gauge_mismatch`.** When a stop pairing no
single gauge can serve is requested, it fails *before* any router call and
names every stop's gauges in the response. This is a domain answer, not a
failure — "Helsinki and Berlin cannot be one train" is true and the UI
should say so in those terms rather than showing a generic routing error.
It is the one error in the system where the right message is an explanation,
not an apology.

**Resolution rules**, so your message can be accurate: the gauge is the set
intersection of the stops' gauges; a stop with unknown gauge does not
constrain the trip; ties prefer 1435. Auto-added stops are filtered to the
trip's gauge, and gauge-unknown stops are never auto-added.

**One naming quirk.** 1520 and 1524 mm are treated as one family — 4 mm
apart, historically the same gauge, interoperable in practice, but tagged
separately in OSM. Finnish trips therefore report `1520`, not `1524`. If you
label gauges, label that one carefully; a Finnish user seeing "1520" will
notice.

**Also, quietly:** Belarus and Russia are excluded from routing entirely.
That is a political decision, not a technical one. No route will cross them
in any mode.

---

## 5. Scenarios and two routing graphs

**Backend: 2026-08-31.**

### The scenario names changed

The old set is gone. "2032 Base Line" was misleading — "2032" named the
price year, not the network, which became untenable once the network itself
became a choice. Three scenarios now, all on today's network:

| key | name |
|---|---|
| `infra-2026` | Infra 2026 — the live base |
| `infra-2026-hsr` | + night trains on high-speed lines |
| `infra-2026-hsr-opt-tt` | + optimised timetables |

Your store already reads `current_base` + `current_scenarios` and ignores
`historical_scenarios`, which is exactly right — there is now a superseded
revision in that group that must not appear in the picker.

**Each scenario has a `description`** written for someone who has just
opened the platform, and the picker currently shows only `scenario_name`.
Those descriptions are the difference between three cryptic labels and a
comprehensible choice; surfacing them (tooltip, subtitle, info popover — your
call) is the highest-value small change on this list.

**What actually differs when a user switches:**

- *+ NT on HSR* changes routing — but only if the selected composition's own
  `hsr_allowed` is true. On a 160 km/h loco-hauled rake the two scenarios
  return identical routes. That looks like a bug and is not, so the UI
  should probably not promise a difference it cannot deliver.
- *+ optimised timetables* changes **durations, not geometry**. The map is
  identical; the journey time drops by roughly 2–5% depending on country. If
  you are diffing scenarios visually, diff the times, not the shape.

**Unchanged:** publish still requires the base scenario. Computing and
comparing under scenarios 2 and 3 works; publishing them returns
`422 scenario_not_base`, by design.

### Two routing graphs

Scenarios now pin which routing graph they run on
(`routing_graph_key`, e.g. `infra_2026`). A second graph — the 2032 upgraded
network from Jasper — is prepared but not running yet.

**Nothing to build now.** It is on this list so the eventual six-scenario
picker is not a surprise: the same three operating conditions on two
networks. When the 2032 graph lands, that becomes a two-axis choice
(network × conditions) and the picker probably needs to stop being a flat
list. Worth thinking about before it arrives rather than after.

---

## 6. `api.ts` audit — the actual to-do list

Checked `frontend/src/types/api.ts` against the current backend. Already
present and correct: `gauges_mm` on stops, `composition_id`,
`suggested_stops`. Missing:

| Field | Where | Why |
|---|---|---|
| `general_parameters` | per trip | Whole object absent from the types. Carries `trip_km`, `route_duration_min`, `average_speed_kmh`, `track_gauge_mm`, `timetable_warnings`. |
| `track_gauge_mm` | inside above | §4 |
| `timetable_warnings` | inside above | Derived quality annotations, e.g. `fixed_night_stretch_slow`. Empty for most trips. |
| `hours` | `parkings[]` | §2, the layover |
| `routing_graph_key` | `Scenario` | §5. **Done on this branch (§12).** |

Also worth a look, though not a type change: the `422 gauge_mismatch`
handler (§4), and whether `provenance` on stops is worth surfacing (§1).

---

## 7. `uic_ref` can hold more than one code

**Backend: schema only, no version bump — 2026-09-05.**

`stop.uic_ref` is OSM's tag copied verbatim, and that tag is multi-valued:
a station registered in two referentials carries both codes in one string,
semicolon-separated. Paris CDG 2 TGV returns `"8727149;8700147"` — the
first is the SNCF code, the second the one Transilien uses for the same
platform.

**No type change.** It stays `string | null` in `api.ts`; nothing to do
unless the UI treats the value as a single code. One stop in the current
catalogue of 783 coded stops is affected, so this is a display edge case,
not a data model change: if you ever render or link on `uic_ref`, split on
`;` and take the first code rather than showing the raw string.

The column was `VARCHAR(12)` and this value aborted the seed; it is now
`VARCHAR(120)`. Whether multi-value eventually becomes a real array
(`string[]`) is deferred to the station-charge calibration, which is the
first thing that will actually join on the code — if it does, it arrives
as one contract change in a §6 batch rather than on its own.

---

## 8. Routes now prefer electrified track

**Backend: `ROUTE_BUILDER_VERSION` 0.9.31 — 2026-09-05. OUTPUT CHANGE, no
contract change.**

Every routing request now penalizes track that OSM tags
`electrified=no`. Background: the router was free to send a night train
down unelectrified branch lines, which is unrealistic and also mispriced —
every locomotive in the catalog is electric, and the energy model bills
catenary electricity on every kilometre.

It is a 10x priority penalty, not a block. An unelectrified alignment
loses to any reasonable electrified alternative, but is still used where
the alternative is absurd or does not exist — so no trip that routed
before starts failing. Track with **no** `electrified` tag is not
penalized at all: unknown is not treated as forbidden.

**Nothing in `api.ts` changes.** No new field, no removed field, no changed
type. What changes is the numbers behind the existing ones.

**What you will see.** On affected trips, geometry, `trip_km`,
`route_duration_min` and therefore every cost and revenue figure move. The
map line moves too. Fully electrified corridors — most of the flagship
routes — are unaffected; the movement is concentrated on regional and
branch alignments and on routes through less-electrified networks.

**One thing to check your side:** any golden-file or snapshot test that
pins a routed distance, duration or geometry will fail and needs
re-baselining. Same for screenshots in the gallery if you compare them
pixel-wise.

**Stored proposals.** They keep their stored numbers until refreshed, as
always — `scripts/refresh_proposals.py` on the backend side. A proposal
computed before 0.9.31 and one computed after can legitimately differ for
the same input; the version is on the payload if you need to explain it to
a user.

---

## 9. Expert timetable mode — a request block and one new segment field

**Backend: `ROUTE_BUILDER_VERSION` 0.9.32 (2026-09-06).** Full contract in
`backend/api/README.md` → "Expert timetable".

The compute request may now carry an optional `expert_timetable` block that
overrides the first departure of a direction and adds minutes to individual
legs. **Send nothing and nothing changes** — every existing request computes
exactly as before, which is why this is additive rather than a new mode.

**New in `api.ts`:**

- `segments[].addon_time_min: number` — manual minutes on that leg. 0 on
  every automatic timetable, so it is safe to read unconditionally. Total
  leg time is now driving + dynamics + buffer + slack + **addon**; if you
  sum the components anywhere, add it.
- `general_parameters.manual_addon_min: number` — the same, summed per
  direction, so you do not have to.
- The request type gains `expert_timetable`, all parts optional:
  `{outbound?: {departure?: {mode: "absolute", time_min} | {mode: "shift",
  shift_min}, segment_addons?: [{from_stop_id, to_stop_id, add_min}]},
  return?: {mirror_outbound: true} | <same shape as outbound>}`.

**Three rules the UI has to respect**, each a 400 otherwise:

1. `add_min` is an integer **≥ 1**. A leg can be padded, never shortened —
   the control should not offer a negative value at all.
2. An add-on names two stops that are **adjacent, in that order, in
   `stops`**. When the user edits the itinerary, prune the add-ons whose
   legs stopped existing before you post.
3. `return` either mirrors (`{"mirror_outbound": true}` — the default, and
   what an omitted block means: outbound's add-ons with each pair reversed)
   or carries its own overrides. Never both.

**The reroute rule, and how to reconcile.** An add-on survives a recompute
only if its stop pair is still adjacent in the *final* stop list. The one
case you cannot predict client-side is `auto_stop_addition: "add"` inserting
a stop between the pair server-side; that add-on is dropped. There is no new
response field for it and none is needed: rebuild your add-on list from
`route.trip_pairs[].outbound.segments[]` after every calc — each segment
carries its stop pair and its `addon_time_min` — exactly the way the builder
already rebuilds the itinerary from the route it gets back. Anything you
sent that is missing from that reconstruction was dropped, which is the
message worth showing.

**Two consequences worth expecting.** An overridden departure re-runs stop
classification, so `stop_type` can change (a stop shifted past 00:00 becomes
`night`); and costs move with the clock, because track-access and
electricity night bands are placed on stop times. Neither is a bug to
report — both are what a manual timetable means.

`POST /api/proposals/compare` takes `expert_timetable` as a side override,
so `{"proposal_id": 123, "expert_timetable": null}` on one side is a
ready-made "with vs without the manual timetable" comparison.

---

## 10. Four more compositions in the catalog (COMPOSITIONS 0.9.4)

`GET /api/params/compositions` now returns twelve compositions instead of
eight: `REF-NOR-7`, `REF-ROOM-14`, `REF-POD-7`, `REF-POD-14`. No shape
change — same keys, same class taxonomy. Two things to expect:

- **Capsule-only trains exist now.** `REF-ROOM-14` carries 504 places, all
  `Capsule`, and no `Seat` at all. Anything that assumes every composition
  has a seat class (fare fallbacks, "from €" labels keyed on Seat,
  formation legends) needs the same "class may be absent" handling the
  refurbished sleepers already needed for Capsule.
- **All twelve compositions stay on the two existing speed tiers** (200
  refurbished / 230 new) — no third tier was introduced. `REF-NOR-7`'s real
  Norwegian sleeper is speed-limited below that in reality, but that's a
  backend modelling note, not something the API surfaces or the frontend
  needs to branch on.

Nine new `coach_type_id` values appear in formations (`B5-3`, `B5-7`,
`BC5-3`, `FR5-1`, `WLAB-2`, `NOX-36`, `LR-SEATPOD-66`, `LR-HOTELPOD-31`,
`LR-HOTELPOD-42`). `FR5-1` is a service coach (bistro) with no classes,
like `ARkimmbz`. Coach `remarks` now carry the coach description and its
source ids instead of a fixed workbook note.

The catalog itself moved from notebook literals to
`backend/models/compositions/calib/catalog/*.csv`; if you ever need to
look up a coach, that is the place.

---

## 11. Cost parameters re-calibrated (COMPOSITIONS 0.9.5)

No shape change, but **every evaluation result moves**: operator costs drop
~45% fleet-wide (maintenance, cleaning, overhead, crew rate and staffing rule), and the
required-revenue gross-up drops from 1.22 to 1.149 (EBIT target 10% → 5%).
Stored proposals evaluated before this reseed are not comparable to ones
evaluated after; gallery KPIs and compare views will show the shift. Nothing
to change on your side beyond expecting different numbers — `CALC_VERSION`
is unchanged because no formula changed, only parameters.

---

## 12. Calc matrix + viewport rearrangement — CALC 0.9.25, backend 0.4.0

This one is different from the entries above: the frontend side is already
on the branch (`ProposalResults.vue` and the zone components, see
`frontend/README.md`), so what you have is a review and the `api.ts`
ownership question, not a to-do. Everything below is what the backend now
serves and what the branch does with it.

### 12.1 `Scenario.dimensions` (GET /api/scenarios)

Every scenario carries `dimensions: {network: "2026"|"2032", hsr_allowed,
optimised_timetable} | null`, derived server-side from `scenario_key` +
`routing_graph_key`. `frontend/src/lib/scenarioAxes.ts` maps the three
switches of the new scenario card onto `scenario_id` and back; which
switch is enabled is data-driven (a switch state without a scenario is
disabled — today "optimised timetables" only exists with HSR on). Also
now typed: `passage_charges_version`, `routing_graph_key` (closes the §6
row).

### 12.2 Five new summary KPIs (calc `summary`, GET /api/proposal/<id>, gallery rows)

| Field | What |
|---|---|
| `net_eur_per_year` | **signed** annual net after the target margin — negative is the shortfall `subsidy_eur_per_year` already reports, positive is a surplus |
| `operating_days_per_year` | from the seasonal schedule |
| `train_km_per_year` | both directions, all pairs — the `per_train_km` divisor |
| `available_place_km_per_year` | capacity place-km — the `per_available_place_km` divisor |
| `sold_place_km_per_year` | from the OD loads; sold / available is the utilisation |

The surplus rule the branch applies everywhere (`lib/compareKpis.ts`
`subsidyDisplay`): a profitable route reads "none · surplus X M €", never a
negative subsidy. Stored proposals read the five columns as 0 until
Giovanni's `refresh_proposals.py` run — the branch treats 0/absent as
"unknown" (a dash), not as a surplus.

### 12.3 `POST /api/proposal/calc/matrix`

Full contract in `backend/api/README.md`. The short version: stops + the
`/calc` HOW fields, optional `composition_ids` / `scenario_ids` (null =
default axes: 6 current scenarios × the whole catalog), `detail`
`"summary"` (default) | `"full"`. With `Accept: application/x-ndjson` the
response streams one record per line — `header`, then cells in completion
order (baseline first), `shared` blocks before the first cell referencing
them (full only), `done` last. Types: `MatrixRecord`, `MatrixHeader`,
`MatrixCell` (`ok | error` union), `MatrixDocument` in `api.ts`.

What the branch does with it (`composables/useCalcMatrix.ts`): after every
successful calc `ProposalViewport` requests **two** grids for the route on
screen, both as JSON documents, both keyed on route fingerprint + HOW fields
+ axes, both reset when the itinerary is edited:

| grid | axes | detail | feeds |
|---|---|---|---|
| `gridMatrix` | offered scenarios × every composition | summary | zone B bars + combination grid, zone D supply table |
| `scenarioMatrix` | offered scenarios × the composition on screen | **full** | zone A deltas — and a **scenario switch with no API call at all** |

The full cells carry route, views and parameters, so switching scenario is
served entirely from memory: `cellAsCalcResponse()` (`lib/calcMatrix.ts`)
rebuilds the cell into the `/calc` response it is equivalent to and hands it
to the existing `applyPlan()`, which commits the new scenario — so the stale
flag never appears and nothing is recomputed. Composition switches still go
through `/calc` (36 full evaluations would be megabytes), but land on a cache
entry `gridMatrix` has already created. Error cells (a scenario this
deployment cannot route) simply leave that switch position on the ordinary
Recalculate path.

The endpoint also speaks NDJSON and streams cells as they complete; the
client asks for the document instead, so the call goes through `apiRequest`
with the same classification, budget, health tracking and cancel semantics as
every other request. `lib/calcMatrix.ts` keeps the reader (`readNdjson`,
`foldMatrixRecords`) for the day a grid is big enough that progressive
rendering beats one response.

### 12.4 What is deliberately disabled

* **Price & regulatory measures** (VAT exemption, energy-tax exemption, TAC
  at direct cost): rendered as greyed toggles with a "coming soon" hint in
  `ScenarioSwitches.vue`; `VITE_FEATURE_MEASURES=off` hides the row. The
  backend does not model them — `docs/PARKED_WORK.md` §3.
* **Fit to demand** column in the supply table: header present, not
  selectable, "coming soon" — the demand stopgap gives every composition
  the same utilisation.
* **Infra 2032**: shown in the network picker, not selectable, with a
  "coming soon" chip beside (not inside) the segmented control and an ⓘ
  hover hint (`InfoHint.vue`). The routing instance and its graph cache run and the backend
  evaluates against 2032 scenarios fine — the infrastructure data behind
  them is simply not at publishable quality yet. Frontend-only:
  `PREVIEW_NETWORKS` in `lib/scenarioAxes.ts`, overridable with
  `VITE_PREVIEW_NETWORKS` (empty string = release everything). While a
  network is held back, its scenarios are also left out of the comparison
  bars/grid **and** the matrix request's `scenario_ids`, so the grid is
  3 × 12 instead of 6 × 12 — releasing 2032 doubles the matrix cost, which
  is the moment to re-check `CALC_MATRIX_WORKERS` (DEPLOY_HANDOVER §4c).

### 12.5 For you specifically

* `api.ts` — the additions are yours to review: `Scenario` (3 fields),
  `ProposalCalcSummary` (route/financial/supply fields typed), the
  `Matrix*` block. Nothing was renamed or removed.
* `en.json` — new namespaces `proposal.compare`, `proposal.supply`,
  `proposal.settings`, `proposal.breakdown`, `proposal.ownership`.
* Retired: `ComputeInputsPanel.vue`, `EvaluationPanel.vue`,
  `EffectPanel.vue`, `CompositionPanel.vue` (their pieces live on in
  `ProposalResults.vue`, `MainKpiGrid.vue`, `SupplyTable.vue`,
  `CostRevenueBreakdown.vue`; `ViewRow`, `CostBreakdownPanel`,
  `CompositionFormation`, `CompositionDetailOverlay` unchanged).
* This joins the pending `backend-dev → staging` contract batch; the
  summary columns need Giovanni's refresh (DEPLOY_HANDOVER §4c) before the
  supply figures show on stored proposals.

## 13. Measure sets, the variant axis, and `GET /api/models` — CALC 0.9.26

WP18 phase A. Additive: nothing is removed, nothing changes shape, no
number moves. This lands ahead of the proposal family (phase B), which is
what the variant axis exists for — §13 gets rewritten when that ships, so
treat what follows as the pieces you can already type against, not as the
final family contract.

### 13.1 `GET /api/scenarios` gains two keys

Beside the three existing groups the body now carries `measure_sets` and
`scenario_variants`:

```ts
interface MeasureSet {
  measure_set_id: number
  key: string                 // 'none' is the only seeded one today
  description: string | null
  vat_exempt: boolean
  energy_tax_exempt: boolean
  tac_direct_cost: boolean
  factors: { ticket_revenue: number; energy_cost: number; track_access: number }
}

interface ScenarioVariant {
  scenario_variant_id: number
  scenario_id: number
  measure_set_id: number
  // inlined from the variant's scenario, so a switch renders from this
  // list alone — the same fields as the matrix axis entry you have:
  scenario_key: string
  scenario_name: string
  is_current_base: boolean
  routing_graph_key: string
  dimensions: ScenarioDimensions | null
}
```

A **scenario** pins what the infrastructure is; a **measure set** says what
the state does about it (VAT, energy tax, direct-cost track access); a
**scenario variant** is the flattened cross product — one value instead of
two. One measure set is seeded (`none`, every factor `1.0`), so today there
is exactly one variant per scenario and `scenario_variant_id` is
effectively an alias for `scenario_id`. Do not rely on that: it stops
being true with WP17, which is the reason the id exists at all.

What this means now: `lib/scenarioAxes.ts` can start mapping the three
switches onto `scenario_variant_id` instead of `scenario_id`, and the
family endpoint (phase B) addresses members by that id. Nothing forces the
change yet.

### 13.2 `GET /api/models` — new

The `models` block every calc response inlines under `evaluation.models`
is now also its own endpoint:

```ts
GET /api/models -> { models: Record<string, ModelEntry> }

interface ModelEntry {
  version: string
  description: string
  formulas?: Record<string, Formula>   // route_builder, energy, evaluation
  factors?: Record<string, unknown>    // emissions
}
```

Same content, same formula keys the breakdown rows already map to
(`lib/factorFeedback.ts`). It is static — the response carries
`Cache-Control: max-age=3600` — so fetch it once per session.

Why it matters before phase B: a family of 72 members would otherwise
carry ~26 KB of identical registry per member. Phase B drops `models` (and
`evaluation.input.parameters`) from the per-member payload entirely, so a
`useModels()` composable fetched once is the shape to move to. The calc
response still inlines it today; nothing breaks if you wait.

### 13.3 CALC 0.9.26 — no value changes

`evaluate_route()` now takes a measure set and records it. Every factor is
1.0 under `none`, so every KPI, breakdown and summary is byte-identical to
0.9.25. The bump is for the signature. If a number moves after this
deploy, it is not this change — tell me.

### 13.4 `api.ts`

Additive only: `MeasureSet`, `ScenarioVariant`, the two new arrays on the
scenario list response, and `ModelsResponse`. No existing type changes.

---

## 14. `auto_stop_addition: "add"` is gone — ROUTE_BUILDER 0.9.34

WP18 phase B1. The mode where the backend added stops of its own is
removed. `auto_stop_addition` is now `"off" | "suggest"`, the API-boundary
default moved from `"add"` to `"off"`, and posting `"add"` gets a 400 like
any unknown mode.

**You are almost certainly unaffected.** `requestCalc` /
`recomputeWithSelection` only ever send `"suggest"` then `"off"`, so the
running client never used the removed mode and never relied on the old
default. What to do:

- `types/api.ts`: narrow the union to `'off' | 'suggest'`.
- Anywhere you rely on the default by omitting the field: it now means
  "build exactly my stops" instead of "add what you think fits". That is
  the behaviour the builder already wanted; nothing to change, but it is
  the one silent difference.
- `Stop.auto_added` stays in the response and is now always `false`. Keep
  reading it: proposals published before 0.9.34 are stored with
  auto-added stops and still come back with the flag set. If any UI
  renders those stops differently, that rendering is still correct for
  old proposals and simply never fires for new ones.

Suggestions are unchanged: same candidate search, same `added_time_min`,
same `suggested_stops` block. What changed is that accepting one is now
the only way a catalog stop joins a route — which is what the builder's
suggestion flow already does.

Why: a route the user did not ask for is not the user's route, and a
proposal family (phase B2) compares one stop list across every scenario
and composition, which it cannot do if each member may pick its own stops
within its own detour budget.

---

## Maintaining this document

One file, updated in the same PR as the backend change. Each entry says
which version introduced it, so you can tell whether a stored proposal
predates it.

When something here is done on your side, delete the entry rather than
marking it done — git history is the archive, and a list of completed items
buries the live ones.

The version constants are the anchor: `ROUTE_BUILDER_VERSION` and
`CALC_VERSION` both carry a full changelog in
`backend/models/route/model.py` and `backend/models/evaluation/model.py`.
Anything marked OUTPUT CHANGE there is something a stored proposal will
compute differently after — which is usually the moment the frontend needs
to know.
