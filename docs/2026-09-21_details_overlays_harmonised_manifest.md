# Details card: every overlay in one shape — manifest and handover

Date: 2026-09-21 · Scope: **frontend + documentation site.** No backend
change, no version bump.

## What changed

The seventeen ⓘ overlays on the Details tabs ranged from four to
twenty-two lines and none linked to the documentation. Every one is now the
builder's standard overlay: **one short paragraph (four lines or fewer at
the overlay width, EN and DE), _Read more in the documentation_ to the
section that explains the box, and _Provide feedback_** prefilled with the
tab's topic and the box's title (already wired through `DetailPanel`).

The detail the overlays lost moved to the docs, so nothing is gone:

- `docs-site/demand.md` gains a section _The Details card, panel by panel_
  with one anchored subsection per box of the Demand and Supply tabs
  (`#schedule`, `#prices`, `#potential-demand`, `#traveller-groups`,
  `#od-matrix`, `#utilisation`, `#what-follows`) carrying the former long
  texts as prose.
- `docs-site/methodology/compositions.md` gains _The selected composition on
  a route_ (`#selected-composition`) and _Comparing compositions on one
  route_ (`#composition-comparison`).
- Overhead and Infrastructure boxes link to the cost pages that already
  exist for their formula.

## The overlays (EN)

| Box | Overlay | Docs |
|---|---|---|
| Supply › Schedule | How often the train runs, as one average over the year. Departures, train-km and place-km follow from it; trainsets are the rakes the cycle needs at this frequency. | `/docs/demand#schedule` |
| Supply › Places and prices | What the train offers and charges, per class: a base fare with a fixed and a distance term, additional services, and a net catering contribution. Fares do not change demand. | `/docs/demand#prices` |
| Demand › Potential demand | Passengers per year over both directions who would take this route. Four levels give a starting figure; any figure can be typed. What a train cannot seat is not served. | `/docs/demand#potential-demand` |
| Demand › Traveller groups | How the demand splits into traveller groups and which classes each group books, in order. Allocated in rounds by a fixed rule, so a recalculation reproduces the same figures. | `/docs/demand#traveller-groups` |
| Demand › OD matrix | The share of the demand each boarding–alighting pair gets, from one weight per stop: a preset or your own, cells pinnable. It moves place-km and revenue, not heads. | `/docs/demand#od-matrix` |
| Demand › Utilisation by composition | The same demand on every composition of the family, read as a utilisation per train. The dashed tail is demand no listed class could seat. Click a composition to select it. | `/docs/demand#utilisation` |
| Demand › What follows | What the schedule and prices earn with the committed demand: passengers, place-km sold, utilisation and revenue per year. Demand edits show only after a recalculation. | `/docs/demand#what-follows` |
| Train operation › Selected composition | The composition the figures were computed with, and what one trip costs to run: the rakes and their upkeep, the locomotive hours and the people on board. | `/docs/methodology/compositions#selected-composition` |
| Train operation › Comparison | Every composition of the catalogue evaluated on this route under the selected scenario, so the figures compare with each other and with nothing else. | `/docs/methodology/compositions#composition-comparison` |
| Overhead › Variable | The operator's selling costs, charged as a share of ticket revenue rather than of the full cost. Catering is outside the base: its contribution is already net of overhead. | `/docs/cost/var-overhead` |
| Overhead › Fixed | The operator's running of itself, charged as a share of its other operating costs — not of variable overhead, and not of the infrastructure charges paid to somebody else. | `/docs/cost/fix-overhead` |
| Overhead › Margin | The operating profit the operator is expected to keep, as a share of ticket revenue. Nobody receives it: it is subtracted in the net result, so a route can need a subsidy with all bills paid. | `/docs/cost/ebit-margin` |
| Infrastructure › Track access | What each infrastructure manager charges for the run over its network, country by country, on the terms that country levies: distance, weight, places, stops, revenue share. | `/docs/cost/tac` |
| Infrastructure › Station charges | One charge per stop call, levied by the station's own infrastructure manager at that country's rate. Every stop of the trip is a call, the terminals included. | `/docs/cost/station-charge` |
| Infrastructure › Shunting and stabling | Stabling between arrival and the next departure at each terminal, on the basis that country prices, plus the power drawn while standing. One stay per location and day. | `/docs/cost/parking` |
| Infrastructure › Traction energy | Traction energy for the run, country by country: the kWh drawn over its kilometres at its tariff, day and night rate where it has a night band, plus any catenary charge. | `/docs/cost/energy` |
| Infrastructure › The year | The four infrastructure lines of the cost breakdown per year, each with its cost per train-kilometre and its share of the total — the same figures as under Costs and revenue. | `/docs/cost/infrastructure-total` |

## Updates by file

| File | Change |
|---|---|
| `frontend/src/lib/docsLinks.ts` | `DOCS_DETAIL_PANEL` — one entry per box. |
| `frontend/src/components/details/*.vue` (10 files), `DetailsSection.vue` | `:doc-path` on every `DetailPanel`; `OverheadTab` maps its three receipts. |
| `frontend/src/i18n/locales/en.json`, `de.json` | 17 `info` texts rewritten. 910 keys each, in parity. |
| `docs-site/demand.md`, `docs-site/methodology/compositions.md` | The new sections, with the anchor comment tying them to `docsLinks.ts`. |

## Handover

Docs anchors are a contract: nine explicit `{#id}`s across the two pages;
change one only together with `docsLinks.ts`.

## Deployment handover

Frontend image only (docs bundle included).

## Verification (Node 22)

Frontend: `vue-tsc --noEmit` clean · `eslint .` clean · `prettier --check`
clean · `vitest run` **376 passed** · `vite build` OK.
Docs site: `prettier --check` clean · `vitepress build` OK, all nine
anchors present.

## Commit split

- `docs(site): the Details card panel by panel; composition sections` — docs-site files.
- `feat(details): one overlay shape — short text, docs link, feedback` — frontend files.
- `docs: details overlays manifest` — this file.
