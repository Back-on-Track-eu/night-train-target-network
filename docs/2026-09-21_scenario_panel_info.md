# Scenario panel info overlays, CO₂ unit fix — manifest and handover

Date: 2026-09-21 · Scope: **frontend + documentation site.** No backend change,
no version bump.

## What changed

- **Overlays.** An ⓘ beside *Scenario and main figures* and beside each of the
  eight KPI labels, each with a short explanation and a link to its section of
  a new documentation page, *Scenarios and main figures*. Every overlay text
  was checked for wrap at the overlay's 288 px width with Arial metrics (wider
  than Mark Pro): all fit in **four lines or fewer**, in both languages. The
  three overlays from the previous round (expert timetable, night legend, route
  stats) were shortened to the same rule — their detail now lives in the docs
  sections they link to.
- **CO₂ tile unit — a real bug.** The tile divided tonnes by 1,000 and then
  formatted the result as millions of euros with the euro sign removed, so
  43,660 t read **"43.66 M kt / year"** — a factor of a million too high, on
  the headline climate figure. It now reads tonnes through a new
  `formatTonnes()` that folds the scale into the unit: **"43.66 kt / year"**.
  The same registry feeds the scenario bars and the grid, which are fixed with
  it. (The value itself was right: 116.42 M pkm × (389 − 14) g = 43.66 kt.)
- **Emissions page brought current.** `docs-site/emissions.md` still described
  EMISSIONS 0.1.x — EEA factors 33 / 160 / 143 g and a flat 35 % air / 20 % car
  shift. It now states what 0.2.0 computes: Back-on-Track 2022 factors 14 / 389
  / 132 g incl. aviation's non-CO₂ warming, and the distance-based source split
  with half car / half induced.

## Updates by file

| File | Change |
|---|---|
| **new** `docs-site/scenarios.md` | *The scenario* (network, operating conditions, measures, baseline — from the seeded scenario descriptions) and one section per KPI, with explicit `{#id}` anchors and a comment tying them to `docsLinks.ts`. |
| `docs-site/emissions.md` | Factors and mode-shift sections rewritten to EMISSIONS 0.2.0 / DEMAND 0.1.0; links to *CO₂ saved*. |
| `docs-site/.vitepress/config.ts` | Sidebar: *Scenarios and main figures* first under *The model*. |
| `frontend/src/lib/docsLinks.ts` | `DOCS_SCENARIO` and `DOCS_KPI`, keyed by `CompareKpiKey` so a new KPI without a docs link is a type error. |
| `frontend/src/components/ProposalResults.vue` | ⓘ on the panel title. |
| `frontend/src/components/MainKpiGrid.vue` | ⓘ on every KPI label; header comment tidied. |
| `frontend/src/lib/money.ts` (+ test) | `formatTonnes()`: t / kt / Mt on the existing thresholds. |
| `frontend/src/lib/compareKpis.ts` (+ test) | `KpiFormatters.tonnes`; the CO₂ KPI reads tonnes and formats them once. |
| `frontend/src/composables/useCompareFormat.ts` | Provides `tonnes`. |
| `frontend/src/i18n/locales/en.json`, `de.json` | `compare.scenarioHint`, `compare.kpiHints.*` (8); `expert.toggleHint`, `night.legendHint`, `routeStatsHint` shortened; unused `compare.units.ktYear` removed. EN/DE in parity. |

## Frontend handover

- **Overlay texts stay at four lines.** The detail belongs in the linked docs
  section; the overlay says what the figure is and one thing that shapes it.
- **Docs anchors are a contract.** `scenarios.md` uses explicit `{#id}`s, so a
  reworded heading keeps its link; changing an id means changing
  `docsLinks.ts` with it.
- **Tonnes, not "M kt".** Anything that shows CO₂ as an amount should use
  `formatTonnes()` (or `fmt.tonnes`), which picks t, kt or Mt itself.

## Deployment handover

Frontend image only (the docs bundle is built into it). No environment
variable, no migration, no cache flush.

## Verification (Node 22)

Frontend: `vue-tsc`, `eslint`, `prettier --check` clean · `vitest run`
**370 passed** (2 new) · `vite build` OK.
Docs site: `vitepress build` OK with dead-link checking on; all nine anchors
present in the built `scenarios.html`.

## Commit split

- `fix(kpis): CO₂ saved read a million times too high` — `money.ts`, `compareKpis.ts`, `useCompareFormat.ts`, the removed `ktYear` unit (in the i18n files, which go with the next commit).
- `feat(builder): explain the scenario panel and every KPI` — the rest.
- `test(kpis): tonnes formatting and the CO₂ tile` — the two test files.
- `docs: scenarios page, emissions page current, manifest`.
