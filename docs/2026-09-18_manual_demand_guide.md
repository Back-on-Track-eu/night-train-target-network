# Manual demand inputs — implementation guide

Date: 2026-09-18 · Sketch: `docs/design/2026-09-18_details-sketch-round7.html` (rounds 7 – 7ac, all decisions confirmed by David on 2026-09-18) · Supersedes the demand part of `docs/2026-09-09_supply_settings_plan.md` and the phase-5 demand sketch of 2026-09-13.

## 1. What this is

V1 ships **without a demand model**. The Details card gets manual demand inputs instead: a potential demand per year, split into five traveller groups with class preferences, allocated onto every composition of the family by a fixed rule, and spread over the sellable OD pairs by a stop-weight matrix. The schedule loses its month grid and becomes one average frequency. Everything in the sketch is client-side arithmetic on the page; the backend has to reproduce it exactly, since the numbers a user sees while editing must be the numbers Recalculate returns.

The sketch is the specification for layout and arithmetic. This guide lists the decisions, the findings that came out of building the sketch, the request contract, and the implementation steps in the order to do them.

## 2. Decisions

### 2.1 Tabs and scope

| # | Decision |
|---|---|
| D1 | Tab order: **Demand · Supply · Train operation · Infrastructure · Overhead**. Demand opens first. |
| D2 | Change scope gains a third input: **demand**. Demand owns *Potential demand*, *Demand by traveller group*, *Utilisation by composition* and *Demand by OD pair* and previews them live. Train operation (subsidy column), Overhead (EBIT on revenue) and the *What follows* panel on Supply depend on demand and grey out (`awaiting recalculation`, tab dot) when it changes. Supply's *What follows* previews schedule and price edits live against the committed demand. |
| D3 | Demand tab panels, top to bottom: **Potential demand** and **Demand by traveller group** side by side, then **Utilisation by composition**, then **Demand by OD pair**. Nothing else. |
| D4 | **What follows** lives on the Supply tab, under Places and prices. Its table must fit without a horizontal scrollbar at ~900 px content width (group column without preference chains, "Places offered" as its own row, 11 px font). |

### 2.2 Schedule (Supply)

| # | Decision |
|---|---|
| D5 | The schedule is **one average frequency in days per week, 1 – 7, whole days**. No month grid, no seasonality, no "summer only". |
| D6 | Input control: a stepped horizontal bar with ticks 1 – 7 (drag, click, arrow keys), value label under it ("3 days per week", "7 days per week — every day", "1 day per week — once a week"), and the line "*n* operating days a year · which weekdays is not modelled". Presets are gone. |
| D7 | Figures in the panel: operating days, departures, train-km, trainsets. No explanatory paragraph in the figures column while the value is unsaved — the `preview` chip and italic amber figures are enough. |
| D8 | Arithmetic: `operating_days = days_in_year × f / 7` (the model's calendar year decides days_in_year; the sketch used 2032 = 366), `departures = operating_days × 2`, `train_km = operating_days × cycle_km`, `trainsets = ceil(cycle_days × f / 7)`. A month is a twelfth of the year everywhere. |
| D9 | The frequency is **only** a Supply input. The Utilisation by composition panel shows it in its caption ("at 3 days per week, 314 departures a year") as a link that switches to the Supply tab. |

### 2.3 Potential demand

| # | Decision |
|---|---|
| D10 | The fixed quantity is **passengers per year, both directions** ("Potential demand"). Per trip = per year ÷ departures; per month = per year ÷ 12. Fewer departures therefore fill each train fuller and turn demand into "not served". |
| D11 | Four **levels** as presets, one row of pills **S · M · L · XL · Custom**: Small 100 000, Medium 200 000, Large 300 000, Extra large 500 000 passengers per year. Any figure can be typed. |
| D12 | Levels are defaults, not a scenario switch. **The chosen level is saved with the proposal** (`demand.level`: `small | medium | large | xl | custom`); editing the figure after choosing a level makes it `custom`. |
| D13 | Under the field: "*Medium* · 638 per departure at 3 days a week · 245 % of NEW-BAL-7's places". |

### 2.4 Traveller groups and allocation

| # | Decision |
|---|---|
| D14 | Five groups, **in this order** (it is also the allocation order), with default shares of the total and their classes in order of preference: |

| Order | Group | Share | Classes, first to last |
|---|---|---|---|
| 1 | Leisure – comfort | 50 % | Sleeper › Capsule › Couchette |
| 2 | Leisure – group | 25 % | Couchette › Seat |
| 3 | Senior leisure | 10 % | Couchette › Sleeper |
| 4 | Leisure – budget | 10 % | Seat |
| 5 | Business | 5 % | Sleeper › Capsule |

| # | Decision |
|---|---|
| D15 | Input: a table — group, share % (editable), passengers per year (derived), per trip (derived), classes in order. Sum row turns amber when the shares do not add to 100; the groups then ask for `total × sum` (no auto-rebalancing, no locks). |
| D16 | **Allocation rule** (per composition, on the per-trip demand): four **rounds** releasing **50 / 20 / 20 / 10 %** of each group's demand. In each round every group, in order 1 → 5, seats what it released: **80 %** along its preference list, first class until full then the next; **20 %** spread evenly over the group's *other* listed classes (a single-class group has none, so Leisure – budget is 100 % Seat). Whatever the deviating 20 % cannot seat rejoins the rule-followers of the same round. |
| D17 | A group sits **only in the classes it lists**. Demand no listed class can seat is **not served** — no overflow into other classes (explicitly rejected), no spill between groups. |
| D18 | The 80/20 term is computed as **expected values**, not random draws, so a recalculation is reproducible. |
| D19 | Class preferences, group order, round shares and the 80 % rule share are **model constants** (DEMAND 0.1.0); only the total, the level and the shares are request inputs. |

### 2.5 Utilisation by composition (the ladder)

| # | Decision |
|---|---|
| D20 | One control row: **per trip · per month · per year** \| **Seat · Couchette · Sleeper · Capsule · All classes** \| **sort: capacity · utilisation · unserved**. Default: per trip, All classes, capacity. |
| D21 | One row per composition of the family. Grey bar = the composition's places in the unit shown; **fill = places served, in the class colour** (All classes: stacked by class); **utilisation % inside the fill** (just after it when the fill is too narrow); **the composition's place count after the bar end**, always. |
| D22 | **Not served**: a faint dashed line *under* the bar (40 % opacity, class colour; amber for All classes) from served to asked; the figure "*n* not served" only on the **selected** composition. In a single-class view no dashed line — "not served" is a property of a group, not of a class. Compositions without the class show "no Seat" etc. |
| D23 | The selected composition's row is tinted amber across name and track, like the selected row of the comparison table. Sorting keeps the tint. |
| D24 | Hovering a class fill shows which groups sit there (title). |

### 2.6 Demand by OD pair

| # | Decision |
|---|---|
| D25 | The spread over OD pairs is entered as **shares of the demand per pair**, in an **origin × destination matrix**: rows = boarding stops, columns = alighting stops, in route order; only sellable pairs are cells (boarding stop before alighting stop; night stops sell nothing and are not shown). Cell: share %, journey km below, shaded by share. Margins: what each stop boards / alights; total 100 %. |
| D26 | The matrix is **filled from one weight per stop** in the margins: `share(o,d) ∝ w_board(o) × w_alight(d)`, normalised over the sellable pairs. Default weight 1. Any weight can be typed. |
| D27 | Four **fill presets write the weights by position along the route** (0 = first, 1 = last of the boarding / alighting list; `w = 0.3 + 2.7·f`, one decimal): Even (all 1) · Long journeys (`f_board = 1−x`, `f_alight = x`) · Mid distance (`1 − |2x−1|` on both) · Short hops (`f_board = x`, `f_alight = 1−x`). Editing a weight drops the preset highlight; there is no separate distance curve and no sliders. |
| D28 | A cell can be **pinned** by clicking it and typing a share: the cell is pinned (●), and every other cell rescales so the total stays 100 %. Refilling from a preset or a weight touches only unpinned cells; "unpin all" clears the pins. |
| D29 | One matrix for all classes. |
| D30 | Default: even spread (all weights 1, no pins). |

### 2.7 Prices

| # | Decision |
|---|---|
| D31 | Base-fare defaults (replace DEMAND 0.0.5's 30/55/110/75 and 0.025/0.035/0.060/0.040): |

| Class | Fixed € / passenger | € / km |
|---|---|---|
| Seat | 10 | 0.06 |
| Couchette | 75 | 0.03 |
| Sleeper | 125 | 0.04 |
| Capsule ("Mini Cabin") | 75 | 0.03 |

Additional services and catering keep their 0.0.5 defaults. The Places and prices table, its example fares and the per-year strip stay as implemented.

### 2.8 Defaults of a new proposal

Medium (200 000 passengers / year), the group shares of D14, 3 days per week, even OD spread, the D31 tariff.

## 3. Findings from the sketch

These came out of building and reviewing the arithmetic; they are worth tests.

1. **Order effects are real.** With the groups walked in order, the first group can take a class outright before a later group with the same first preference gets a turn — Senior leisure lost 125 of 150 Sleeper wishes on REF-POD-14 in the first, single-pass version. The rounds (D16) are the fix: they interleave the groups. Keep the rounds; do not "optimise" the loop away.
2. **Strict lists dominate unserved demand.** On REF-POD-14 (no Seat, no Couchette) Leisure – group and Leisure – budget cannot sit at all: 35 % of any total is unserved before the Sleeper fills. This is intended (D17) and should show as such in the ladder.
3. **Per-year storage changes the meaning of frequency.** Halving the frequency doubles the per-trip load. At the defaults NEW-BAL-7 is 245 % loaded; at 7 days a week 105 %. The utilisation panel's frequency link (D9) exists because of this.
4. **Rounding.** Level totals split by shares can miss the total by a unit; the sketch lands the remainder on the last group. Backend: do the split in floats, never round per group.
5. **Even = weight 1.** The preset formula gives 3.0 for `f = 1`; Even is special-cased to 1 so the margins read naturally.
6. **Pins rescale the rest, including other pins,** by `(100 − v) / (100 − old)`. Unpinned cells follow automatically through the remainder. The sum stays 100 to floating-point precision.
7. **Places offered vs demand asked** are different columns in What follows; a "/ capacity" suffix inside a cell was confusing and got its own row.
8. **The 80/20 term matters mostly when a first choice is full** — at low load it moves a handful of passengers; at high load it decides which class serves whom.

Reference values at the defaults (Medium · 3 days/week · even · D31 tariff), for tests — the backend must reproduce them:

| Quantity | Value |
|---|---|
| Operating days / departures / train-km (366-day year) | 156.86 / 313.71 / 338 811 |
| Demand per departure | 637.5 (comfort 318.75 · group 159.375 · senior 63.75 · budget 63.75 · business 31.875) |
| NEW-BAL-7 served per trip by class | Seat 96 · Couchette 40 · Sleeper 40 · Capsule 84 = 260; not served 377.5 |
| NEW-BAL-7 by group | comfort: Couchette 35.38, Sleeper 40, Capsule 84, left 159.38 · group: Seat 75.07, Couchette 4.62, left 79.69 · senior: none, left 63.75 · budget: Seat 20.93, left 42.82 · business: none, left 31.88 |
| REF-POD-14 served per trip | Sleeper 230 · Capsule 152.51 = 382.5; not served 255.0 |
| NEW-BAL-14 served per trip | Seat 159.38 · Couchette 80 · Sleeper 80 · Capsule 168 = 487.4; not served 150.1 |
| Even OD share (17 pairs) | 5.882 % each; average journey 535.3 km |
| NEW-BAL-7 per year | 81 566 passengers; place-km sold 43 661 647; ticket revenue 6 840 558 €; catering 135 525 € |

## 4. Request contract

Fields added or changed on the proposal calculation request (`api/helpers/member_compute.py` resolves and validates; `models/family/key.py` lists the key fields):

```jsonc
"schedule": { "days_per_week": 3 }                    // replaces days_per_week_by_month
"demand": {
  "level": "medium",                                   // small | medium | large | xl | custom
  "passengers_per_year": 200000,
  "group_shares_pct": { "comfort": 50, "group": 25, "senior": 10, "budget": 10, "business": 5 },
  "od": {
    "preset": "even",                                  // even | long | mid | short | custom (informational)
    "stop_weights": { "board": { "<stop_id>": 1.0 }, "alight": { "<stop_id>": 1.0 } },
    "pinned_shares_pct": { "<origin_stop_id>>": { "<dest_stop_id>": 12.5 } }
  }
}
"fares_eur_per_pax": { "Seat": 10, "Couchette": 75, "Sleeper": 125, "Capsule": 75 }
"fares_eur_per_km":  { "Seat": 0.06, "Couchette": 0.03, "Sleeper": 0.04, "Capsule": 0.03 }
```

- `passengers_per_year`, `group_shares_pct`, `stop_weights`, `pinned_shares_pct` and `days_per_week` join `REQUEST_KEY_FIELDS` — a family is one demand against every composition, so any of them changes the family. `level` and `od.preset` are labels for the UI and stay **out** of the key.
- Stop weights and pins are keyed by stop id, not name. Drop a pin whose stop is no longer on the route or no longer sellable; keep weights for stops that remain. Say so in the response (`demand.dropped_pins`).
- Validation: shares ≥ 0 (a sum ≠ 100 is allowed and reflected, see D15); weights ≥ 0; pins in 0 – 100 with sum ≤ 100; `days_per_week` an integer 1 – 7.
- Response: per composition, `demand.by_group_by_class` (per trip and per year), `demand.not_served` per group, `demand.od_shares`, plus the existing per-class sold / place-km / revenue figures, so the frontend does not need the algorithm for committed figures — it only needs it for previews.

## 5. Versions

- `DEMAND_MODEL_VERSION` → **0.1.0**: the stopgap is replaced by the group allocation. Add the changelog entry with the constants of D14, D16, D31.
- `CALC_VERSION` → patch (`0.9.33`): every evaluation result changes.
- `ROUTE_BUILDER_VERSION` → patch: the schedule shape changes.
- `FAMILY_DOCUMENT_FORMAT` → 7: the family document gains the demand block.
- Stored proposals with `days_per_week_by_month`: migrate to the **rounded average** over the twelve months (a summer-only 7/0 pattern becomes 2); record the migration in the proposal's history note. Stored proposals without a demand block get the defaults of 2.8 on their next recalculation and are flagged stale by the version bump anyway.

## 6. Implementation steps

Phase by phase, one zip per phase, confirmation between phases (ways of working). Backend is `uv`-managed under `backend/`; ruff formatting; no serialization on domain objects.

### Phase A — Schedule: one frequency (backend)

1. `models/route/route.py`: replace `days_per_week_by_month` on `Schedule` by `days_per_week: int`; keep `operating_days_per_year` (uses the model's calendar year), `peak_days_per_week` becomes `days_per_week`; `trainsets` = `ceil(cycle_days × days_per_week / 7)`.
2. `api/helpers/route_serialize.py`, `member_compute.py` (validation 1 – 7 integer), `family_compute.py`, `models/family/key.py`: field rename.
3. Migration of stored proposals (average of months, rounded); a one-off script under `backend/scripts/`.
4. Tests: schedule arithmetic, request validation, migration; update fixtures that carry month grids.
5. Bump `ROUTE_BUILDER_VERSION` (patch); note in `models/route/model.py` changelog.

### Phase B — Demand model 0.1.0 (backend)

1. `models/demand/model.py`: constants — `DEMAND_LEVELS`, `TRAVELLER_GROUPS` (order, shares, prefs), `ROUNDS = (50, 20, 20, 10)`, `RULE_SHARE = 0.8`, `OD_PRESETS`, the D31 tariff defaults; changelog 0.1.0; description text.
2. New `models/demand/groups.py`: `allocate(places_by_class, demand_by_group) -> Allocation` — the rule of D16/D17, floats, deterministic; returns per group per class, per class totals, served, not served per group. Port the sketch's `allocate()` one-to-one and test against the reference table in §3.
3. New `models/demand/od_matrix.py`: sellable pairs from the route (reuse the stop-type rule already in `stopgap.py`), `preset_weights(route, preset)`, `od_shares(route, weights, pins)` with the pin rescale rule (finding 6), `pin(...)` for the frontend parity tests.
4. Rewrite `stopgap.distribute_demand()` → `demand/distribute.py`: per trip demand = per year ÷ departures; allocation per composition; places sold per OD pair = served per class × share; place-km, revenue and catering as today. Delete the uniform stopgap and `STOPGAP_UTILIZATION_PER`.
5. `member_compute.py`: resolve and validate the `demand` block with defaults; `family_compute.py` passes it through; `evaluation_serialize.py` emits the response fields of §4; `family_serialize.py` bumps the document format and stores the demand block.
6. `models/family/key.py`: add the key fields.
7. Tests: unit tests for `groups.py` and `od_matrix.py` (reference values), integration test for a family with the defaults, a pin, a weight and a level; the sum-≠-100 case; a route with a night stop.
8. Bump `CALC_VERSION`, `DEMAND_MODEL_VERSION`, `FAMILY_DOCUMENT_FORMAT`. Update `docs/MODEL.md` and `models/demand/README.md`.

### Phase C — Supply tab (frontend)

1. `SchedulePanel.vue`: replace `MonthSliders.vue` with a `FrequencyBar.vue` (stepped 1 – 7, keyboard, `aria-valuenow`); value label and operating-days line; figures column without the preview paragraph. Delete `MonthSliders.vue` and its tests.
2. `lib/detailsScope.ts`: `supplyFigures` on one frequency; a third scope `demand` in the dirty/awaiting logic; the tab-dot map of D2.
3. `PlacesPricesPanel.vue`: defaults from the backend's `defaults` response (already the pattern) — nothing to hard-code; check the example-fare columns still read.
4. New `WhatFollowsPanel.vue` under Supply: KPI column (passengers, places sold per departure, utilisation places / place-km, ticket revenue, catering, total) and the group × class table of D4; previews schedule and prices live against the committed demand (client-side `follows()` port), awaits on demand.
5. Types in `types/api.ts`, i18n keys, vitest for `detailsScope` and the frequency bar.

### Phase D — Demand tab (frontend)

1. `DemandTab.vue` becomes four panels (D3): `PotentialDemandPanel.vue` (pills S/M/L/XL/Custom, field, note), `TravellerGroupsPanel.vue` (table of D15), `UtilisationLadder.vue` (D20 – D24), `OdMatrixPanel.vue` (D25 – D30).
2. `lib/demandAllocation.ts`: a TypeScript port of `groups.py` (same reference tests) for live previews; `lib/odMatrix.ts` likewise. Parity tests against the JSON of the backend unit tests.
3. Frequency link in the ladder caption switches the tab (D9).
4. The stale banner names "the demand" as a third scope; Train operation and Overhead panels get `awaiting` on demand.
5. Responsive: the ladder's track column must survive 900 px; the matrix scrolls inside its own container beyond ~10 × 10.

### Phase E — Pipeline

1. Backend integration tests against the Docker stack (`uv run pytest`), `ruff format` + `ruff check`.
2. Frontend gates: `vue-tsc`, eslint, prettier, vitest, `vite build`.
3. Version bumps checked in CI (§5).
4. Handover docs under `docs/`: `FRONTEND_HANDOVER_DEMAND.md` (fields, response shape, parity tests) and a `DEPLOY_HANDOVER.md` addendum (migration script, reseed of families).
5. Commits: `feat` / `test` / `docs` split per phase.

## 7. Open items (not blocking; confirm when they come up)

1. UI label for `Capsule`: David writes "Mini Cabin"; the catalog says Capsule. The i18n key can carry either without touching the model.
2. Per-class OD matrices (Sleeper demand plausibly skews long) — the request shape allows a later `od.by_class`; not in V1.
3. Whether pins survive a route edit — the guide proposes dropping pins of stops that leave the route and reporting them (§4).
4. The model's calendar year for operating days (2032 in the sketch); use the scenario year the pipeline already carries.
