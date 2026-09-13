# Viewport rearrangement — sketch documentation (2026-09-06)

The design notes that shipped with the HTML mock `viewport-rearrangement-sketch.html` (kept outside the repo). The zone A–E components under `frontend/src/components/` implement these rules; decisions taken since (measures toggles disabled, fit-to-demand not selectable, Infra 2032 as "coming soon", the scenario × composition grid in place of the measures heatmap) are in `docs/FRONTEND_HANDOVER.md`.

---

# Proposal viewport — rearrangement target vision (sketch)

Status: design sketch, 2026-09-06. Not code to ship. All figures are mock data.
Open `viewport-rearrangement-sketch.html` in a browser — no build, no server.

## Why we rearrange

- Put the scenario comparison front and centre: main KPIs and a scenario chart before anything else.
- Move the discussion up so people engage with it.
- Separate "what every user wants to see" from expert/edit actions: settings and the full Kassenzettel become collapsible sections at the bottom.
- Make the supply section a place to *compare and choose* compositions, not just pick one.
- Leave room for the demand model and price settings.

## Page structure (top to bottom)

1. **Ownership line** (next to Gallery): "Your proposal · changes are saved automatically" or "Juri's proposal · any change you make is saved as your own copy". Follows the existing copy-on-edit mechanism, no extra button.
2. **Route time table + map** — unchanged. Route stats: distance, avg speed, stops, countries (flags). "Runs" removed.
3. **Zone A — Scenario switches + main KPIs** (gold card). Three axes:
   - Rail network: segmented control Infra 2026 / Infra 2032.
   - Operating conditions: toggle "night trains may use high-speed lines", toggle "optimised timetables" (disabled until HSR is on — it does not exist without HSR in the scenario grid).
   - Price & regulatory measures: toggles "VAT exemption on tickets", "energy tax exemption", "track access at direct costs only".
   - **Baseline = everything off and Infra 2026.** Every combination maps to one scenario (6 network×condition rows × 8 measure combinations = 48).
   - Scenario description + "Measures: …" line, then an "Evaluated with <composition> · <frequency> — change ↓" line with the stale-results marker.
   - KPI grid (4 × 2): necessary subsidy (gold, headline), CO₂ saved, subsidy per t CO₂, passenger trips, passenger-km, shifted from air, shifted from car, journey time. Each with a delta vs. baseline.
4. **Zone B — Compare across scenarios.** KPI picker + two views:
   - *Current measures*: six bars (2026 baseline / +HSR / +HSR+opt tt, same for 2032), selected scenario highlighted gold.
   - *All 48 combinations*: heatmap, rows = network × condition, columns = measure combination (with V/E/T chips), colour = worse→better, selected cell ringed; clicking a cell sets all switches above.
5. **Zone C — Discussion** with comment count, likes, Like and Share buttons, comment list, composer.
6. Divider "Detail settings and the full cost breakdown".
7. **Zone D — Settings** (collapsible, tabs Supply / Demand).
   - Supply: formation drawing of the selected composition (to-scale vehicles, class bands with place counts, loco dark, bistro grey — same idea as `CompositionFormation.vue`); filters (All / New fleet / Refurbished / HSR-capable); sort by subsidy, €/train-km, €/place-km, fit to demand, utilisation, demand covered (dropdown or click column header); sortable table with the selected row pinned under the sticky header. Columns: composition (with class-mix bar), places, €/train-km, €/place-km, fit to demand, subsidy/yr, ⓘ (opens the existing detail overlay).
   - Fit-to-demand cell reads both ways: bar = the train; blue = demand seated, grey = empty places, red stub past the end = demand turned away. Text: "100 % of demand · 53 % load" (too big) or "84 % of demand · train full" (too small). Green ring = covers demand at ≥ 90 % load.
   - Sidebar "Frequency & supply": Daily / 3× week; per year both directions: departures, train-km, places offered, place-km offered; fleet: train sets needed, demand covered.
   - Demand tab: placeholder describing what the numbers rest on (demand source, prices, competing modes). Should not ship empty.
8. **Zone E — Costs and revenue in detail** (collapsible Kassenzettel). Existing filters; then two breakdown bars on one shared scale (cost: operator variable/fixed, track access, station charges, energy; revenue: sleepers/couchettes/seats) with a dashed outline on the shorter bar marking the gap (gold "necessary subsidy" or green "revenue exceeds cost"); then the two ledgers and the summary row.

## Surplus handling (revenue > cost)

Consistent rule everywhere: no negative subsidy shown to lay users.
- KPI: "Necessary subsidy → none · surplus X M €/year"; "Subsidy per t CO₂ → 0 € / t · no subsidy".
- Bar chart: dashed zero line; subsidy bars above in blue, surplus bars below in green, labelled "surplus X".
- Heatmap: "surplus" label in the cell; colour scale pins zero in the middle (blues need subsidy, greens surplus).
- Composition table: "none / surplus X M €".
- Kassenzettel: dashed green surplus outline on the cost bar; summary cell switches to "Surplus".

## Mobile (≤ 640 px)

Settings, Kassenzettel, the divider, the 48-combination view and the sticky context bar are not available. A short card replaces them: "Settings and the full cost breakdown need a bigger screen — evaluated with <composition>, <frequency>." Scenario axes stack, KPIs go 2-column, bar labels shorten (Base / HSR / HSR+tt).

## Sketch aids (not product features)

- Zone chips (A–E) mapping blocks to the NEW diagram — "Hide zone labels" bottom-right.
- "flip" next to the ownership line toggles own / someone else's proposal.
- "Sketch: show revenue > cost case" (toolbar and Kassenzettel header) applies a mock revenue uplift and selects Infra 2032 + HSR.
- Sticky context bar (route · scenario · train · frequency · "change ↓") appears after scrolling past the map — open question whether it is too much chrome.

## Implementation notes / open points

- Scenario axes map to `scenario_id` via a lookup; measures are scenarios from the user's perspective. Backend decides reroute vs. KPI-only recalculation (cache; `proposals/calc/matrix` endpoint in progress). The comparison views need results for 6 (bars) or 48 (heatmap) scenarios — compute lazily on first open.
- Supply table needs evaluation figures per composition for the current route/scenario (routing unchanged, only evaluation reruns).
- Bar-chart axis: zero-based bars make 10–15 % differences look flat; decide zero-based vs. truncated with a clear marker.
- "None" vs. signed negative subsidy for expert readers — one-line change per component.
- Class-mix filter for the composition table once the catalogue passes ~20 entries.
- Ledgers in the surplus flip are static in the sketch.
