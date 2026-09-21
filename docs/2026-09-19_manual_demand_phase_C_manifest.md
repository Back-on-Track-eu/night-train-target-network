# Manual demand inputs — Phase C delivery manifest

Date: 2026-09-20 · Guide: `docs/2026-09-18_manual_demand_guide.md` §6 Phase C ·
Scope: **Supply tab (frontend).** Builds on Phases A and B (ROUTE_BUILDER 0.9.40,
DEMAND 0.1.0, CALC 0.9.34, FAMILY_DOCUMENT_FORMAT 7).

Decisions applied: one frequency on the wire (the backend keeps its month grid; a
seasonal echo reads as its rounded average); the demand scope compares the numbers,
not the labels, exactly like the family key; a committed echo without a demand block
(computed before DEMAND 0.1.0) counts as changed until the first Recalculate.

## What changed

### Arithmetic and scope (`frontend/src/lib/`)

| # | File | Change |
|---|---|---|
| 1 | `detailsScope.ts` | Schedule half rewritten for one frequency: `DAYS_IN_YEAR`, `DEFAULT_DAYS_PER_WEEK = 3`, `clampDaysPerWeek`, `scheduleRequest` → `{schedule: {days_per_week}}`, `daysPerWeekFromRequest` (rounded average of the echoed month map), `operatingDaysPerYear`, `trainsetsFor`, `supplyFigures`. Third scope `demand`: `DemandInputs`, `demandFromRequest`, `demandRequest`, `sameDemand`; `DetailsInputs` gains `demand`; `dirtyScopes` compares all three; `TAB_AWAITS` is D2's tab-dot map. Month presets, `MONTH_KEYS`, `presetOf`, `peakMonth` removed. |
| 2 | **new** `demandAllocation.ts` | `allocate()`, `splitByGroup()` and the rule's constants — one-to-one port of the sketch, mirror of `models/demand/groups.py`. |
| 3 | **new** `odMatrix.ts` | `sellablePairs`, `boarding/alightingStopIds`, `presetWeights`, `resolveWeights`, `odShares`, `pinPair`, `unpinPair`, `averageDistanceKm` — mirror of `models/demand/od_matrix.py`. |
| 4 | **new** `whatFollows.ts` | `follows()` — passengers, place-km, utilisation, ticket and catering per class and total from an allocation and the OD spread's average journey. |
| 5 | **new** `frequencyBar.ts` | Pointer → step, arrow/Home/End keys, tick positions, the value qualifier. |
| 6 | `compareKpis.ts` | `shiftCar` → `shiftOther` (`shift_other_trips_per_year`). |

### Tests (`frontend/src/lib/*.test.ts`) — vitest, node, no jsdom

| # | File | Change |
|---|---|---|
| 7 | **new** `demandAllocation.test.ts`, `odMatrix.test.ts`, `whatFollows.test.ts` | Parity with the backend: read `backend/tests/fixtures/demand_reference.json` (written by `tests/test_83_demand_units.py`) and match every allocation, share, pin step and per-year figure to 9–12 decimals; the guide's §3 table to the cent. |
| 8 | **new** `frequencyBar.test.ts` | Snapping, clamping, keys, qualifiers. |
| 9 | `detailsScope.test.ts` | Rewritten: frequency, fleet, supply figures at 3 days/week, the demand block round trip, `sameDemand`, the three scopes, the tab dots. |

### Components (`frontend/src/components/`)

| # | File | Change |
|---|---|---|
| 10 | **new** `details/FrequencyBar.vue` | Stepped bar 1–7 (D6): drag, click, arrow keys, `role="slider"` with `aria-valuenow/valuetext`; value label with "every day" / "once a week"; the operating-days line. |
| 11 | `details/SchedulePanel.vue` | One frequency; figures column without the preview paragraph (D7); committed figures from the operations block's exact annualisers. |
| 12 | **deleted** `details/MonthSliders.vue` | — |
| 13 | **new** `details/WhatFollowsPanel.vue` | Under Places and prices (D4): KPI column (passengers, sold per departure "of n asked", utilisation places / place-km, ticket revenue, catering ±, total), the group × class table with Served / Not served, Places offered / Utilisation / Ticket revenue rows, the revenue bar; previews schedule and price edits against the committed demand (the backend's `demand.od.average_distance_km` for the selected composition), awaits on a demand edit. 11 px table, no preference chains in the cells. |
| 14 | `DetailsSection.vue` | Three scopes; `TAB_AWAITS` dots; `committedBlock` from the family member's `demand`; What-follows wired; Train operation and Overhead also wait on demand. |
| 15 | `details/PlacesPricesPanel.vue` | `daysPerWeek` prop; comments. |
| 16 | `details/SelectedComposition.vue` | Fleet "Sized by" shows the frequency instead of a month; `MONTH_SHORT` removed. |
| 17 | `ProposalViewport.vue` | Always posts `schedule: {days_per_week}` and the `demand` block; restores both from the echo; `detailsChanged` covers demand. |
| 18 | `ProposalResults.vue` | Frequency label from the one figure. |
| 19 | `SupplyTable.vue` | Comments: the Fit column fills with the ladder in Phase D. |

### State, types, i18n

| # | File | Change |
|---|---|---|
| 20 | `stores/store.ts` | `scheduleMonths` → `scheduleDaysPerWeek` (3); `demand` seeded from the registry's `demand.defaults` (`defaultDemand()`), reset with the tariff. |
| 21 | `types/api.ts` | `DemandModelSection` (defaults incl. levels/shares, `constants`), `DemandBlock`, `FamilyMemberOk.demand`, `FamilyViewsResponse.demand`, `EvaluationResponse.demand`, `FamilyRequest.schedule/min_turnaround_min/demand`, `CompactRoute.schedule` month map, `shift_other_*`. |
| 22 | `i18n/locales/en.json`, `de.json` | Schedule keys (caption, info, `daysPerWeek`, `qualifier`, `operatingDaysNote`; presets/months/hints removed), `scopes.demand`, `groups.*`, `follows.*`, prices info sentence, `compare.kpis.shiftOther`, `restsOnInfo`; `compare.customSchedule` removed. |

Not touched, deliberately: `DemandTab.vue` and the tab order (D1, D3 — Phase D), the
Fit-to-demand column (fills with the ladder in D), `docs/FRONTEND_HANDOVER_DEMAND.md` (E).

## Verification (run here on Node 22)

- `npx vue-tsc --noEmit` clean · `npx eslint .` clean · `npx prettier --check .` clean.
- `npx vitest run`: **325 passed** (302 before, 45 new, 22 retired with the month grid).
- `npx vite build` succeeds (with the Mark Pro fonts in `src/assets/fonts/`, which the snapshot does not ship).
- The three parity suites fail loudly if `backend/tests/fixtures/demand_reference.json` is regenerated with different constants.

## Behaviour to check by hand

1. New proposal: Supply opens at 3 days per week; the figures column shows the committed 157 operating days / 314 departures after the first calculation; dragging the bar previews amber figures and lights the dots on Train operation, Infrastructure and Overhead — not on Supply.
2. What follows: with the reference tariff and Medium demand on NEW-BAL-7 it reads 81 566 passengers, 260 of 638 sold per departure, 6.84 M € ticket revenue; a fare edit moves it live (amber), a demand edit (Phase D) greys it.
3. Loading a proposal stored before this work: the schedule bar shows its rounded frequency, the stale row says "the demand changed", and the first Recalculate commits the default demand.

## Commit split

- `feat(details): one frequency, the demand scope and the What-follows panel (manual demand inputs, phase C)` — files 1–6, 10–22.
- `test(details): parity with the backend demand fixture, frequency bar, three scopes` — files 7–9.
- `docs: phase C manifest` — this file.
