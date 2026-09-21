# Manual demand inputs — Phase D delivery manifest

Date: 2026-09-20 · Guide: `docs/2026-09-18_manual_demand_guide.md` §6 Phase D ·
Scope: **Demand tab (frontend).** Builds on Phase C (the ports in `lib/demandAllocation.ts`
and `lib/odMatrix.ts`, the demand scope, the store's `demand` state).

## What changed

| # | File | Change |
|---|---|---|
| 1 | `frontend/src/components/details/DemandTab.vue` | Rewritten as the container of the four panels (D3): Potential demand and Demand by traveller group side by side, then Utilisation by composition, then Demand by OD pair. Owns the demand scope: every edit replaces `store.demand` whole; nothing on the tab waits. The old revenue/KPI content is gone. |
| 2 | **new** `details/PotentialDemandPanel.vue` | S · M · L · XL · Custom pills from the registry's levels (D11), the passengers-per-year field (D10), the level saved with the proposal and turned `custom` by a typed figure (D12), the note "*Medium* · 638 per departure at 3 days a week · 245 % of NEW-BAL-7's places" (D13). |
| 3 | **new** `details/TravellerGroupsPanel.vue` | The table of D15: group, editable share %, per year, per trip, classes in order (colour dots + chain); the sum row and note turn amber when the shares do not add to 100 — no rebalancing (D14–D16). |
| 4 | **new** `details/UtilisationLadder.vue` | D20–D24: control row (per trip · per month · per year \| classes · All \| sort capacity · utilisation · unserved), one row per composition with the grey places bar, the fill in class colour (stacked for All), utilisation inside the fill or just after it, the place count after the bar, the dashed not-served line under the bar with the figure on the selected composition, `no Seat` for a missing class, group tooltips on the fills; the selected row tinted amber; clicking a row selects the composition; the caption's frequency link switches to Supply (D9). Live allocation per composition from the catalog's places at the frequency as the bar has it (finding 3). |
| 5 | **new** `details/OdMatrixPanel.vue` | D25–D30: boarding × alighting matrix over the sellable pairs (structure, names and journeys from the backend's committed demand block), shares live from the margin weights, cell shading by share, margin weight fields, the four presets (active preset detected from the weights), click-to-pin cells (● marker, Enter/Escape), unpin all, row/column sums, the figures column (sellable pairs, pinned, average journey, longest/shortest share, busiest stops) and the dropped-pins note from the last calculation. Scrolls inside its own container past ~10 × 10. |
| 6 | `DetailsSection.vue` | Tab order Demand · Supply · Train operation · Infrastructure · Overhead (D1); the tab's props (compositions, selected composition, committed block, frequency, current departures); `goToSupply`. |
| 7 | `stores/store.ts` | The Details card opens on Demand. |
| 8 | `i18n/locales/en.json`, `de.json` | `details.potential.*`, `details.groupsPanel.*`, `details.ladder.*`, `details.od.*`; the old `details.demand.*` block removed; `supply.fitHint` now points at the ladder. |

No backend change. `lib/*` and their parity tests are unchanged from Phase C.

## Verification (Node 22)

`vue-tsc` clean · `eslint` clean · `prettier --check` clean · `vitest run` 325 passed · `vite build` OK (with the local fonts).

## Behaviour to check by hand

1. New proposal: the card opens on Demand at Medium; the ladder shows every composition of the family at 3 days/week; NEW-BAL-7 selected reads 260 served / 378 not served per trip in the All view (the §3 reference); switching to *per year* multiplies by 314.
2. Editing the total, a share, a weight or a cell turns the four panels' figures amber, lights the dots on Supply (What follows), Train operation and Overhead, and the stale row names "the demand". Reverting the edit clears it. Recalculate commits it; the backend's `evaluation.demand` then matches the preview.
3. OD matrix: *Long journeys* writes 3.0 … 0.3 into the margins; typing a share into Berlin – Verona pins it (●) and the other cells rescale so the sums stay 100 %; *unpin all* releases them. A pin on a pair the route stops selling shows up in the dropped-pins note after the next calculation.
4. The frequency link in the ladder caption switches to Supply.

## Commit split

- `feat(details): Demand tab — potential demand, traveller groups, utilisation ladder, OD matrix (manual demand inputs, phase D)` — files 1–8.
- `docs: phase D manifest` — this file.
