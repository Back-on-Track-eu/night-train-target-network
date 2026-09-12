# Frontend handover — Details (supply, train operation, overhead, demand)

**Date:** 2026-09-12, revision 2 — supersedes the 2026-09-12 handover of the same name
**Branch:** `backend-dev`
**Backend status:** phases 2–4 merged and green (875 passed, 2 skipped).
Four small backend additions are needed before the frontend starts (§6);
none of them touches the family key semantics already in place.
**Versions today:** `ROUTE_BUILDER_VERSION` 0.9.35 · `CALC_VERSION` 0.9.28 ·
`FAMILY_DOCUMENT_FORMAT` 3
**Design reference:** `docs/design/2026-09-12_details-sketch.html` — the
rendered, interactive sketch every layout decision below was taken on.
Open it next to this document; it is the picture, this is the contract.

This document folds the results of six sketch rounds (2026-09-12) into the
plan of `docs/2026-09-09_supply_settings_plan.md`. Where the two differ,
this one wins.

---

## 1. What changed since revision 1

Revision 1 asked for a "Detail settings" card with Supply and Demand tabs
and a composition panel that absorbed the overlay. The sketch rounds moved
it to this:

| | Revision 1 | Now |
|---|---|---|
| Card name | Detail settings | **Details** |
| Tabs | Supply · Demand | **Supply · Train operation · Infrastructure · Overhead · Demand** |
| Inputs | schedule, turnaround, fares (all on Supply) | **schedule, fares, catering** on Supply — turnaround is a displayed constant |
| Month control | sliders or steppers, open | **twelve vertical sliders**, presets every day / 3× per week / once per week / summer only / custom |
| Preview | open | **yes — the owning panel previews, every dependant panel greys out** (§3) |
| Composition panel | four sections | **three stacked receipts** (fleet, loco, staff), each a headline KPI + a per-trip Kassenzettel + trip → cycle → year strip |
| Unit costs | indicative €/train-km, ct/place-km from the catalog | **gone** — the comparison table shows this route's own figures |
| Density | in the composition panel | **columns in the comparison table** (m/place, t/place) |
| Cost share by class | in Places | **gone** from Supply |
| Catering | not modelled | **signed net contribution per passenger** (§4.1) |
| Overhead | not shown | **own tab**: variable overhead, fixed overhead, expected margin — model-accurate bases (§4.4) |
| Infrastructure | not shown | **own tab, sketched, not in the first implementation step** (§4.3) |
| ⓘ | every figure | **one per panel**, carrying the panel's whole explanation; `docPath` line reserved |
| "illustrative" / "last calculation" | — | **never shown to the user**; the change-scope rule replaces both |

Two things did *not* change and are worth restating: every HOW input goes
through `paramsStale` → one **Recalculate** for the whole card, and
**supply settings are saved with the proposal** (§5).

---

## 2. Structure

### 2.1 The card

Zone D is a collapsible card titled **Details** (`SettingsSection.vue`
renamed to `DetailsSection.vue`). Inside, top to bottom:

1. **The stale row** — the only place a Recalculate button lives. Shown
   only while an input differs from what the results were computed with.
   Text names what changed: "schedule and prices changed. Panels that
   depend on them wait for the recalculation."
2. **The tab bar** — five pill tabs; a tab whose pane holds a waiting
   panel shows an amber dot after its label.
3. **The pane.**

The card is available at the `lg` breakpoint and up (1,024 px). Below
that the mobile card stays as today. Every panel has `overflow: hidden`
and its tables sit in an `overflow-x: auto` wrapper, so nothing can run
out of a box at the narrow end of that range; the three operation panels
are stacked, not three abreast, for the same reason.

### 2.2 The panel

Every panel is the same shape: `border-primary-50/10 rounded-lg p-3`, an
`h4` title row with **exactly one** `InfoHint` and an optional
right-aligned caption, then content. A panel that shows results carries
an `awaiting recalculation` badge in its title row, hidden unless waiting.

Cost panels are **Kassenzettel**: a per-trip table (item · basis ·
€/trip · share of the panel's total), bold total row, then a strip:

```
Per trip                                     3,874 €
Per trip cycle (outbound + inbound)   × 2    7,749 €
Per year (× operating days)         × 366    2.84 M €
```

The strip is one component (`TripCycleYearStrip.vue`), used by every
receipt on Train operation, Infrastructure and Overhead. Strips that
carry a second quantity (loco hours, paid staff hours, kWh) show it in
small type before the euros.

### 2.3 Where every value comes from (verified 2026-09-12)

Three responses feed the card. Nothing comes from anywhere else.

| Source | Endpoint | Carries | Cost |
|---|---|---|---|
| **A · Family document** | `POST /api/proposal/family`, `GET …/family/<key>` | the request echo; per member a **`summary`** row only (annual totals: `operating_days_per_year`, `departures_per_year`, `train_km_per_year`, `available_place_km_per_year`, `sold_place_km_per_year`, `demand_trips_per_year`, `total_cost_eur`, `total_revenue_eur`, `net_eur`, `subsidy_eur_per_year`, `trainsets_physical`); compact routes. **No breakdown, no operations.** | once per family, ~1.5 s warm for 96 members |
| **B · Member views** | `GET …/family/<key>/members/<variant>/<composition>/views` | `{ views, operations }` for **one member**: the six Breakdown views (`route`, `per_trip_pair`, `per_trip_pair_per_country`, `per_trip_pair_per_od`, `per_trip_pair_per_section`, `per_trip_per_stop`) — every cost leaf per year incl. `var_overhead_eur`, `fix_overhead_eur`, `margin.ebit_margin_eur`, revenue by class — and `operations` (trainsets, loco hours, staffing, **per trip cycle**). | ~350 ms per member, member-cached; the viewport already fetches it for zone E (`proposalsApi.ts` 194) |
| **C · Stored proposal** | `GET /api/proposal/<id>` | `compute_request` + `{ views }` as computed at publish. **No `operations`, no summaries of other members.** | — |
| Catalog | `GET /api/params/compositions` (store) | places by class, density, purchase per coach, write-off years, crew factors, operator factors (`var_overhead_per`, `fix_overhead_quota_per`, `ebit_margin_per`, `financing_quota_per`), loco lease rate | loaded once |
| Models | `GET /api/models` | `demand.defaults` (fares, catering) | loaded once |

Panel by panel:

| Panel | A family | B member views | catalog / models |
|---|---|---|---|
| Supply · Schedule | operating days, departures, train-km, trainsets | — | — |
| Supply · Places and prices | place-km offered; fares from the request echo | — | places by class; defaults |
| Train operation · comparison table | **every member's** summary: places, €/train-km (`total_cost_eur ÷ train_km_per_year`), ct/place-km, subsidy, trainsets | — | density (m/place, t/place) |
| Train operation · fleet, loco, staff | — | `operations` + the `per_trip_pair` breakdown leaves (`coach_maintenance_eur`, `cleaning_eur`, `shunting_eur`, `coach_amortisation_eur`, `financing_eur`, `loco_eur`, `driver_eur`, `crew_eur`) | purchase, write-off, factors, lease rate |
| Overhead · all three | — | `var_overhead_eur`, `fix_overhead_eur`, `margin.ebit_margin_eur`, `operator.variable/fixed.total_eur` from the `per_trip_pair` view | the three shares |
| Demand | passengers (`demand_trips_per_year`), places sold, place-km sold, revenue | revenue by class | — |
| Infrastructure (later) | — | `per_trip_pair_per_country` (TAC, energy, station charges per country), `per_trip_per_stop` (station charge per stop) | — |

So: **A alone renders Supply and the comparison table**; the selected
composition panel, Overhead, Demand's class split and Infrastructure all
render from **B for the selected member**, which the viewport already
holds for zone E. Switching scenario or composition swaps B, exactly as
the cost panels do today. A stored proposal renders Supply from
`compute_request` (§5) and needs one B call after load — again, what the
viewport does already. Per-trip figures are per-year leaves ÷
`departures_per_year` from A; per-cycle figures are in `operations`.

---

## 3. The change-scope rule

This replaces "preview vs. last calculation" wording entirely and is the
one behaviour the whole card shares.

Two inputs change the calculation, both on Supply: the **schedule** and
the **prices** (fares and catering). Each is a *scope*. Every panel either
*owns* a scope or *depends* on one.

- **Owner, previewable** → the panel recomputes on the page. Its recomputed
  figures are marked (amber, italic) with one chip: *preview — estimated
  here, not calculated*. Schedule owns operating days, departures,
  train-km, trainsets (the cycle is a constant from the last result, so
  `max_m ceil(cycle_days × d_m / 7)` is exact), places offered, place-km
  offered. Prices own the two example-fare columns beside each fare field.
- **Dependant** → the panel keeps the figures it has, greys to 45 %, and
  lights its `awaiting recalculation` badge. Nothing shows a number that
  mixes previewed and calculated inputs.
- **Not dependent** → untouched. Change a price and Train operation,
  Infrastructure and Overhead stay lit (cost does not depend on price);
  change the schedule and everything but the price fields waits.

Dependency table:

| Panel | schedule | prices |
|---|---|---|
| Supply · Schedule | owner | — |
| Supply · Places and prices (per-year rows) | owner | — |
| Supply · Places and prices (example fares) | — | owner |
| Train operation · comparison table | waits | waits (subsidy column) |
| Train operation · fleet, loco, staff | waits | — |
| Infrastructure · all | waits | — |
| Overhead · variable overhead, expected margin | waits | waits |
| Overhead · fixed overhead | waits | — |
| Demand | waits | waits |

Implementation: `useChangeScope.ts` — `dirty: Set<'schedule'|'prices'>`
derived from `store` vs the committed request; panels declare
`data-await="schedule prices"`; a `v-await` directive (or a wrapper
component) toggles the class and badge. Recalculate commits, the set
empties, everything lights up. The tab dot is `pane.querySelector('.awaiting')`.

Minimum turnaround is **not** an input: it is displayed under Train
operation as "180 min" and is not editable. The request field stays
accepted by the backend; the UI does not send it.

---

## 4. Tabs

### 4.1 Supply — two panels

**Schedule.** Left: presets as pills (Every day · 3× per week · Once per
week · Summer only · Custom — Custom lights by itself when the grid
matches no preset) and twelve vertical PrimeVue `Slider`s, 0–7, value
above, month below, the busiest month's label in amber when the schedule
is not flat. Right, in the same panel: operating days, departures,
train-km, trainsets, with the preview chip above them and the preview
hint below ("Departures, train-km, places and place-km follow from the
grid; trainsets use the cycle of 2 days, which only the backend can
redo. Recalculate to apply the schedule to every other panel.").

Presets in request terms: every day = `alwaysDaily`; the others are
`custom` with the grid filled 3 / 1 / summer (May–Sep 7, else 0).

**Places and prices** — one table, one row per class:

| Class | Places | Share of train | € / km | Example fare, longest OD | Example fare, shortest OD | |
|---|---|---|---|---|---|---|
| ■ Seat | 96 | ▬ 37 % | `0.10` | 108.00 € | 7.50 € | default 0.10 · reset |
| … | | | | | | |
| All classes | 260 | 100 % | | | | |
| ■ Catering | *no places to sell* | | `−0.80` € / pax | *reading, see below* | | default 1.20 · reset |

The two example columns are headed with the pair and distance
("Berlin – Verona · 1,080 km", "Kufstein – Innsbruck · 75 km") and are
arithmetic on the field beside them, previewed live. The OD pairs come
from the route: longest = the terminals, shortest = the closest two
consecutive stops.

**Catering is a signed net contribution per passenger**, not a price and
not revenue. The restaurant is not modelled as a business of its own; one
figure carries its revenue less its costs. The field accepts negatives
(±0.10 steps); beside it a reading in words changes with the sign:

- `> 0` → "+1.20 € per passenger — the service covers its own costs and
  contributes" (yellow-green)
- `< 0` → "−0.80 € per passenger — the service is carried by the tickets
  it helps sell" (amber)
- `0` → "neither contributes nor costs"

The ⓘ says the usual night-train case is negative. Below the table:
places offered and place-km offered per year (schedule-owned, previewed).
The composition is chosen under Train operation; the caption says so.

### 4.2 Train operation

**Comparison table** (`SupplyTable.vue`, minus the ⓘ column and the
overlay): **Trainsets** first, then Composition · Places · €/train-km ·
**m/place · t/place** · ct/place-km · Fit to demand (coming soon) ·
Subsidy/year. Density comes from
`composition.capacity.avg_density_length_m_per_place` /
`avg_density_weight_t_per_place`. The selected row stays in sort order.

**Selected composition panel** (`SelectedComposition.vue`): amber border,
"Selected" tag, id, description, one ⓘ; the subline (strategy · coaches ·
length · weight · locos · speed · HSR · places · amenities · catering
text); the formation strip full width with the coach inspector line; then
three stacked panels, each `grid-cols-[15.5rem_1fr]` — KPI and facts on
the left, receipt on the right:

| Panel | Headline KPI | Facts | Receipt lines (per trip) |
|---|---|---|---|
| Composition fleet | **2** · 2.30 with reserve — *trainsets* | cycle per rake, sized by (month · d/week), minimum turnaround 180 min, coach availability, purchase per coach (write-off years), coaches incl. reserve | coach maintenance (€/km × km), cleaning (€/coach·d × coaches), shunting (events × €), coach amortisation, financing — the last two are per-year fleet figures ÷ departures, and the basis column says so |
| Locomotive leasing | **5,673** — *locomotive hours per year* | locos per train, type, lease rate, hours per trip cycle | running, at the terminals; total row "1 loco × 46.00 €/h" — strip carries hours |
| Staff | **6** · 6.19 weighted — *staff on board* | drivers, train chief (× 1.19), attendants, hours on train per trip | role · on board · × factor · h on train · roster · paid h · €/h · €/trip; total row shows the effective rate — strip carries paid hours |

The train chief reads **On board 1 · × factor 1.19**; the 1.19 is never
shown as a head count. Amortisation and financing follow the model:
`purchase_coach × n / amort_years` and `purchase_coach × q_fin × n` with
`n` = coaches × theoretical trainsets (7 × 2.30 = 16.1).

### 4.3 Infrastructure — sketched, not in the first step

Four panels plus a total, all Kassenzettel:

- **Track access charges**: country · km · **charged on** · €/train-km ·
  €/trip · share. "Charged on" is a plain-words list of the terms that
  country levies ("distance, 72 % at the night rate · gross weight ·
  administrative add-on · congestion, 5 % of the run at rush hour"); the
  formula lives in the ⓘ. A row for separately billed crossings
  ("none on this route" when absent).
- **Station access charges**: every stop with country, category, €/stop;
  strip header names stop events per cycle and per year.
- **Service facilities**: parking per stay at each arrival terminal; the
  per-trip line is one stay averaged over both ends.
- **Energy**: country · km · kWh/train-km · kWh/trip · €/kWh excl. VAT ·
  incl. VAT (with the rate) · €/trip excl. VAT; strip carries kWh.
- **Infrastructure per year**: four tiles + sum, each with €/train-km,
  and a share bar.

What it needs from the backend is in §6.5; do not start it before that.

### 4.4 Overhead — three panels, model-accurate

Same KPI + receipt shape as Train operation. **The bases are the model's
own (`models/evaluation/model.py`), not shares of the full cost:**

| Panel | KPI | Base | Formula |
|---|---|---|---|
| Variable overhead | **8 %** of ticket revenue | ticket revenue per trip (= per year ÷ departures) | `C_var,oh = Σ_od R_od × q_var,oh` |
| Fixed overhead | **12 %** of operator cost excl. variable overhead and infrastructure | staff + loco + maintenance + amortisation + financing + cleaning + shunting, listed with share of base | `C_fix,oh = q_fix,oh × (C_op,var − C_var,oh + C_op,fix)` |
| Expected margin | **10 %** of ticket revenue | ticket revenue per trip | `C_EBIT = Σ_od R_od × q_EBIT`; **deducted in the net result, not a cost paid to anyone** — the panel says so in a row of its own |

Catering is outside all three bases: it is already a net figure (its own
sales, service and overhead sit inside the per-passenger contribution),
so charging distribution overhead on it would double-count. The variable
overhead panel shows the contribution beside the base as context. The
factors come from the operator entry (`ebit_margin_per`,
`var_overhead_per`, `fix_overhead_quota_per`, `financing_quota_per` —
already served in the compositions catalog); the euros are
`Breakdown.operator.variable.var_overhead_eur`, `…fixed.fix_overhead_eur`,
`Breakdown.margin.ebit_margin_eur`. No Kassenzettel-total panel here —
that is zone E's job.

### 4.5 Demand

One results panel (waits on schedule and prices): passengers, places
sold, place-km sold, ticket revenue, **catering contribution** (signed,
coloured by sign), **revenue and contribution** as the total; then the
ticket-revenue-by-class bar in `CLASS_COLORS`. Beside it the placeholder
explanation that exists today, plus one line on what the tab becomes when
a demand model lands. Prices are set under Supply; the panel says so.

---

## 5. Saved with the proposal

Already true for what exists: the resolved request is persisted as
`compute_request` on the proposal row (`adapters/proposal/repository.py`)
and echoed by `GET /api/proposal/<id>`; the schedule and turnaround are
additionally on `proposals.routes` (`schedule_months`,
`min_turnaround_min`, `gtfs_store.py`). So `schedule_mode`, `schedule`,
`min_turnaround_min` and `fares_eur_per_km` survive publish and reload
today. Catering rides along the same way once it is a request field (§6.1).

What the frontend has to add: **`lib/proposalPrefill.ts` does not restore
any of these yet.** Loading a stored proposal must put `schedule_mode`,
`schedule`, `fares_eur_per_km` and `catering_eur_per_pax` from
`compute_request` into the store before the first evaluate, or the reload
recomputes with defaults and immediately reports stale. The gallery card
can show the schedule preset name from the same block.

---

## 6. Backend changes before the frontend starts

Small, additive, and all on the `operations` / request side. Version
bumps as noted; `FAMILY_DOCUMENT_FORMAT` stays 3 unless §6.3 changes the
family document (it should not — `operations` is on the member views).

### 6.1 `catering_eur_per_pax` — request field, signed (blocks Supply, Demand)

- Request: `catering_eur_per_pax: number` (may be negative), optional,
  default from the demand model. HOW field → family key, canonicalised in
  the echo like the fares.
- `GET /api/models` → `demand.defaults.catering_eur_per_pax: 1.20`
  (a documented stopgap, like the fares).
- Evaluation: `catering_contribution_eur = passengers_per_year ×
  catering_eur_per_pax`, entering `net_eur` beside `ticket_revenue_eur`.
  **Not** in `var_overhead_eur` or `ebit_margin_eur` bases — those stay
  on ticket revenue as written.
- Summary row gains `catering_contribution_eur`; Breakdown gains it under
  revenue as its own leaf (so zone E can show it signed).
- `CALC_VERSION` bump, formula entry `catering_contribution_eur` in
  `CALC_FORMULAS` for the ⓘ catalogue.

### 6.2 `roster_efficiency` on `operations.staffing.<role>` (blocks Staff)

Agreed in revision 1 §7.4. Read-only, per role: on-train hours ÷ paid
hours. With it, `paid_hours_per_trip` (or the frontend divides). No family
key change.

### 6.3 Per-trip loco and staff figures in `operations` (blocks Loco, Staff)

Checked: the **fleet receipt needs nothing** — its five lines are per-year
leaves of the `per_trip_pair` breakdown (`coach_maintenance_eur`,
`cleaning_eur`, `shunting_eur`, `coach_amortisation_eur`, `financing_eur`)
÷ `departures_per_year`, and coaches needed = coaches × the theoretical
trainsets already in `operations`. Fleet lines are symmetric by nature.

Loco and staff are not: `operations` reports them per **trip cycle**, and
the two trips of a pair differ (running time, crew duty boundaries). The
internal records already carry `trip_id` (`segment_costs`, `stop_costs`
in `_pair_operations`), so splitting is a serialisation change:

- `operations.trip_pairs[].trips[]` — two entries, each with
  `loco_hours { running, at_terminals, total }` and
  `staffing.<role> { on_board, factor, hours_on_train, roster_efficiency,
  paid_hours, eur }` (`roster_efficiency` and `paid_hours` are §6.2).
- `operations.route.operating_days_per_year` and `departures_per_year`,
  so the strips multiply with the number the backend used.

The per-cycle figures stay (additive). If the per-trip split is deferred,
the frontend can show cycle ÷ 2 with a caption "per trip, averaged over
both directions" — acceptable for a first release, not for the final one.

### 6.4 Verify the overhead fields reach `views` (Overhead tab)

`var_overhead_eur`, `fix_overhead_eur`, `margin.ebit_margin_eur` are in
`Breakdown` (`types/api.ts` 367 / 374 / 399). Confirm they are also in
the `per_trip_pair` view so the per-trip receipt reads them directly, and
that `operator.variable.total_eur` and `operator.fixed.total_eur` are
present to build the fixed-overhead base. Likely no change; a test that
pins it.

### 6.5 Infrastructure tab — later, but decide now

More exists than revision 2 first assumed: `per_trip_pair_per_country`
already attributes TAC, energy and station charges to the country that
levied them, and `per_trip_per_stop` has the station charge per stop
call. What is missing for the sketch:

- the **"charged on" list** per country — which TAC terms were non-zero
  (day/night distance, weight, place, admin add-on, congestion, stop fee,
  revenue share, crossings); `SegmentCost.tac` holds the component
  breakdown internally, so this is a view addition;
- **parking per terminal** (only a route total `parking_eur` today);
- **energy in kWh per country and the tariff excl./incl. VAT** (only
  euros per country today).

A view-shape addition, not a model change; schedule it after 6.1–6.3 and
after the first frontend step is live.

### 6.6 Nothing to do, but stated

- `min_turnaround_min` stays per proposal and accepted; the UI stops
  exposing it. Do not remove it from the request.
- `trainsets_physical` and `departures_per_year` on the summary — done.
- Density figures — in the compositions catalog already.
- Operator factors — in the compositions catalog already.

---

## 7. How to continue

### 7.1 Backend (one session, in this order)

1. **6.1 catering** — request field, family key, defaults, net result,
   summary + breakdown leaf, formula entry, tests
   (`test_21_schedule_and_trainsets.py` style: pin a positive and a
   negative value through publish → reload). `CALC_VERSION` bump.
2. **6.2 + 6.3 operations per trip** — extend `operations`, keep the
   cycle figures; tests on a symmetric and an asymmetric pair.
   `ROUTE_BUILDER_VERSION` bump.
3. **6.4** — one test pinning the overhead fields in the views.
4. Run the backend integration test locally, green CI (version bumps,
   model doc regeneration via `scripts/model_docs`), then regenerate the
   API shapes for §8 and hand over to the frontend — a short addendum to
   this document with the literal JSON, as revision 1 did.

Estimated: 6.1 half a day, 6.2/6.3 half a day (serialisation only), 6.4 an hour.

### 7.2 Frontend (after 7.1 lands; phases are each shippable)

**F1 — card, tabs, change scope.** Rename to `DetailsSection.vue`; five
tabs; stale row inside the card with the single Recalculate; tab dots;
`useChangeScope.ts` + `AwaitingBadge.vue`; the panel shell
(`DetailPanel.vue`: title, one `InfoHint`, caption slot, badge). Retire
`CompositionDetailOverlay.vue` and its trigger. Gates green with the
existing content reflowed into Supply and Train operation.

**F2 — Supply.** `SchedulePanel.vue` (`MonthSliders.vue` on PrimeVue
`Slider` vertical; presets; the four owned figures with preview),
`PlacesPricesPanel.vue` (one table; fare fields with default/reset; the
example-fare columns from the route's longest and shortest OD; catering
signed with the sign reading; places offered / place-km offered).
`proposalPrefill.ts` restores schedule, fares, catering from
`compute_request` (§5). Copy in `en.json` under `proposal.details.supply.*`.

**F3 — Train operation.** Comparison table columns (trainsets first,
density); `SelectedComposition.vue`; `TripCycleYearStrip.vue`;
`FleetPanel.vue`, `LocoPanel.vue`, `StaffPanel.vue` reading
`operations.trip_pairs[].trips[]` and `.fleet` (§6.3). A Y-route has more
than one pair: the panels take the pair of the selected direction and
say so in the caption; do not assume `[0]`.

**F4 — Overhead and Demand.** Three overhead receipts from the breakdown
and the operator factors; the demand panel with the signed contribution.

**F5 — Infrastructure.** After §6.5.

**F6 — `types/api.ts`.** Request: `catering_eur_per_pax`. Response:
`operations` per-trip shape, `catering_contribution_eur` on the summary
and breakdown, `roster_efficiency`. **Coordinate with Bjarne** — the
pending coordination batch in the project overview grows by this.

Each phase: `npm run ci; npm run build` (vite build, not only vue-tsc —
see revision 1 §5), vitest cases for the change-scope rule (owner
previews, dependant waits, recalc clears, tab dot follows), and the
handover addendum under `docs/`.

### 7.3 Copy that needs care (one ⓘ per panel, so each carries the lot)

- Schedule: weekday spread not modelled; 366-day evaluation year; how
  operating days, departures, train-km and trainsets are derived; fleet
  sized to the busiest month.
- Places and prices: fares are a placeholder demand model at 70 % flat
  utilisation (quote the model description); example fares are one-way
  arithmetic; catering is a net contribution, sign explained.
- Composition fleet: the cycle rule in David's words; physical vs.
  theoretical; turnaround is a constant.
- Staff: on board × factor, attendant-equivalents, roster efficiency,
  euros are the cost model's own.
- Variable overhead / expected margin: share of ticket revenue; margin is
  deducted in the net result, not paid to anyone; catering outside the
  bases and why.
- Fixed overhead: the base and its two exclusions.

---

## 8. API surface — what exists and what §6 adds

Existing (revision 1 §3 still accurate): `schedule_mode`, `schedule`,
`min_turnaround_min`, `fares_eur_per_km` on the request; `operations`
on the member views with `trainsets { physical, theoretical,
coach_avail_per, cycle_days, peak_month, min_turnaround_min }`,
`loco_hours { per_trip_cycle, per_year, n_locos }`, `staffing.<role>
{ on_board, hours_per_trip_cycle, effective_rate_eur_h,
eur_per_trip_cycle, eur_per_year }`; `departures_per_year` and
`trainsets_physical` on the summary; `demand.defaults.fares_eur_per_km`
on `GET /api/models`.

To be added by §6 (shapes final after 7.1, addendum to follow):

```jsonc
// request
"catering_eur_per_pax": -0.80

// GET /api/models → demand.defaults
"catering_eur_per_pax": 1.20

// summary
"catering_contribution_eur": -106560.0

// operations.trip_pairs[]
"trips": [{
  "direction": "outbound",
  "loco_hours": { "running": 6.0, "at_terminals": 1.75, "total": 7.75 },
  "staffing": {
    "drivers": { "on_board": 1, "factor": 1.0, "hours_on_train": 7.25,
                 "roster_efficiency": 0.885, "paid_hours": 8.19, "eur": 443.7 },
    "train_chief": { "on_board": 1, "factor": 1.19, … },
    "attendants":  { "on_board": 4, "factor": 1.0, … },
    "total": { … }
  }
}],
"fleet": {
  "coaches_needed": 16.1, "purchase_coach_eur": 3846642.86, "amort_years": 30,
  "financing_quota_per": 0.04,
  "per_trip": { "maintenance_eur": 7560, "cleaning_eur": 2548, "shunting_eur": 300,
                "amortisation_eur": 2817, "financing_eur": 3384 }
}

// operations.route
"operating_days_per_year": 366, "departures_per_year": 732
```

---

## 9. Open questions

1. **Longest / shortest OD for the example fares** — terminals and the
   closest consecutive stops, computed in the frontend from the route; or
   should the backend name them (it knows the OD table)? Frontend is
   simpler and enough for the first step.
2. **Y-routes** in the three receipts — pair of the selected direction,
   or a pair switcher in the panel caption? The sketch assumes one pair.
3. **Catering default 1.20** — stopgap value; David's remark that the
   usual case is negative suggests the default itself may be negative.
   Decide before 6.1 lands, it is one number.
4. **Fixed overhead base per trip** — the model computes it per year over
   the breakdown; the per-trip receipt divides. Fine for display; confirm
   nobody sums the per-trip lines back to a per-year total that differs
   from the breakdown by rounding.
5. **Stored proposals and `CALC_VERSION`** — a stored proposal renders
   from its `compute_request` plus one member-views call, which recomputes
   with the current model; its stored `views` may be older. The card
   should read everything from the fresh B response and leave the stored
   views to the gallery, as zone E does now. Confirm that is the intended
   rule before F2.
