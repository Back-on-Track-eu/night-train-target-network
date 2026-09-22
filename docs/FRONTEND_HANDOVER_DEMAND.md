# Frontend handover — manual demand inputs (Details card)

Date: 2026-09-20 · Specification: `docs/2026-09-18_manual_demand_guide.md` (D1–D31),
sketch `docs/design/2026-09-18_details-sketch-round7.html` · Backend contract:
`backend/api/README.md` ("schedule", "demand"), `backend/models/demand/README.md`.
Supersedes the schedule half of `docs/FRONTEND_HANDOVER_SUPPLY_SETTINGS.md`.

Versions this pairs with: ROUTE_BUILDER 0.9.40 · DEMAND 0.1.0 · CALC 0.9.34 ·
EMISSIONS 0.2.0 · FAMILY_DOCUMENT_FORMAT 7.

---

## 1. What the card does now

Five tabs, opening on **Demand** (D1): Demand · Supply · Train operation ·
Infrastructure · Overhead. Three inputs change the calculation — the
**schedule** and the **prices** on Supply, the **demand** on Demand — and
each is a *scope*. A panel that OWNS a scope previews its figures on the page
(amber, italic, `preview` chip); every panel that DEPENDS on one keeps its
figures, greys to 45 % and lights its `awaiting recalculation` badge; the tab
carries a dot when one of its panels waits (`lib/detailsScope.ts::TAB_AWAITS`,
D2):

| Tab | waits on |
|---|---|
| Demand | nothing — owns `demand` |
| Supply | `demand` (the What-follows panel) |
| Train operation | `schedule` · `prices` · `demand` |
| Infrastructure | `schedule` |
| Overhead | `schedule` · `prices` · `demand` |

The stale row at the top of the card names the changed scopes and carries the
only Recalculate inside the card. `ProposalViewport.vue::detailsChanged` greys
zones A, B and E for the same three scopes.

## 2. State and request

All three inputs live in the Pinia store (`stores/store.ts`) because they ride
in every family request and are saved with the proposal:

| Store | Request field | Restored from the echo by |
|---|---|---|
| `scheduleDaysPerWeek` (1–7, default 3) | `schedule: {days_per_week}` | `daysPerWeekFromRequest` — the echo carries the backend's month map; a flat map reads back exactly, a seasonal one as its rounded average |
| `faresEurPerKm/PerPax`, `servicesEurPerPax`, `cateringEurPerPax` | the four tariff maps | `tariffFromRequest` |
| `demand: DemandInputs` (seeded from `GET /api/models` → `demand.defaults`) | `demand: {level, passengers_per_year, group_shares_pct, od: {preset, stop_weights, pinned_shares_pct}}` | `demandFromRequest`; an echo without the block (computed before DEMAND 0.1.0) leaves the defaults in place and the card reports "the demand changed" until the first Recalculate |

`ProposalViewport.vue::familyRequest` always posts `schedule` and, once the
registry has seeded it, `demand`. Level and OD preset are labels: the
backend leaves them out of the family key and `sameDemand()` ignores them.

## 3. Components

```
components/details/
├── FrequencyBar.vue          stepped 1–7 bar, role="slider", keyboard (lib/frequencyBar.ts)
├── SchedulePanel.vue         bar + the four figures; owns `schedule`
├── PlacesPricesPanel.vue     the tariff table (unchanged shape); owns `prices`
├── WhatFollowsPanel.vue      what schedule + prices earn against the COMMITTED demand;
│                             previews on schedule/prices, waits on demand (D4)
├── DemandTab.vue             container of the four demand panels; owns `demand`
├── PotentialDemandPanel.vue  S/M/L/XL/Custom, the passengers-per-year field, the note (D10–D13)
├── TravellerGroupsPanel.vue  shares table, amber sum row (D14–D16)
├── UtilisationLadder.vue     every composition at the current frequency (D20–D24)
└── OdMatrixPanel.vue         boarding × alighting matrix, weights, presets, pins (D25–D30)
```

`DetailsSection.vue` owns the scope logic, hands each panel what it needs and
passes `committedBlock` — the backend's demand block for the selected
composition (`members[].demand` on the family document, `evaluation.demand`
on the views response, type `DemandBlock` in `types/api.ts`). Two panels read
it: What-follows takes `od.average_distance_km` (the committed OD spread's
journey length), the OD matrix takes the structure — `boarding_stop_ids`,
`alighting_stop_ids`, `pairs[]` with names and journeys, `dropped_pins`.

## 4. Arithmetic — the ports and their parity tests

The previews are one-to-one TypeScript ports of the sketch's functions, and
the backend's `models/demand/` is the same arithmetic in Python:

| `lib/` | mirrors | port of |
|---|---|---|
| `demandAllocation.ts` — `allocate`, `splitByGroup`, the constants | `models/demand/groups.py` | `allocate()` |
| `odMatrix.ts` — `sellablePairs`, `presetWeights`, `odShares`, `pinPair`, `unpinPair` | `models/demand/od_matrix.py` | `odShares()`, `pinPair()`, `presetWeights()` |
| `whatFollows.ts` — `follows` | `distribute.py` + `evaluation` | `follows()` |

`demandAllocation.test.ts`, `odMatrix.test.ts` and `whatFollows.test.ts`
read `backend/tests/fixtures/demand_reference.json` — written by
`backend/tests/test_83_demand_units.py` from the Python code — and match
every allocation, share, pin step and per-year figure to 9–12 decimals. When
a constant changes on either side, `test_83` rewrites the fixture and the
frontend tests fail until the port is updated: **change the rule in both
places, run both suites, commit the fixture.** The rule's constants are
also served in `GET /api/models` → `demand.constants` for reference; the
ports carry their own copies deliberately, so a preview never depends on a
registry fetch.

Reference values at the defaults (Berlin – Verona, 3 days/week, Medium, even
spread, D31 tariff): NEW-BAL-7 seats 260 of 637.5 per departure, 377.5 not
served; 81 566 passengers and 6 840 558 € ticket revenue a year. What the
page previews and what Recalculate commits agree to the cent.

## 5. Display rules

- Previewed figures: amber + italic (`.preview-value`), with the `preview`
  chip on the panel; never mix a previewed figure with a calculated one in
  one number.
- Rounding for display (backend keeps floats): passengers, places and place-km
  as integers (`fmt.int`, `fmt.count`), shares and utilisation to one
  decimal / whole percent, euros via `fmt.eur` (M € / k € thresholds). The
  operations block's `departures_per_year` is exact (313.71) and shown as 314.
- Ladder: grey = places, fill = served in class colour (stacked for All),
  utilisation inside the fill or just after it, place count after the bar,
  dashed not-served line with the figure on the selected composition only,
  `no Seat` where a class is absent; the selected row is tinted amber.
- OD matrix: `share ∝ board × alight` over the sellable pairs, cells shaded by
  share, ● = pinned; night stops are not shown.

## 6. Known limits and the two improvement rounds

- The ladder and the matrix are drawn at the frequency as the Supply bar has
  it (a Supply preview leaks into the Demand tab's per-trip figures by
  design — D9 names it in the caption).
- The OD matrix needs a committed block; before the first calculation it
  shows a one-line note.
- A committed echo without a `demand` block reads as changed (deliberate).
- `SupplyTable.vue`'s "Fit to demand" column is still a placeholder header —
  the ladder is that comparison now; remove or wire the column in the
  frontend round.
- One OD matrix for all classes (D29); per-class matrices, a derived
  potential demand and elasticities are the analytical round.
- Component tests: vitest runs in node without jsdom, so the SFCs are
  untested; everything with arithmetic is in `lib/` and tested there.
