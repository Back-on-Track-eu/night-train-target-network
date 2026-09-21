# "2032 prices" on the euro KPIs and the comparison; comparison hint reworded — manifest

Date: 2026-09-21 · Scope: **frontend only.** No backend change, no version
bump. Builds on the price-basis sticker delivered earlier today.

## What changed

- The **Necessary subsidy** and **Subsidy per t CO₂e** tiles carry the
  *2032 prices* sticker beside their ⓘ (feedback topic `kpis`).
- **Compare across scenarios** carries it next to the title **while a euro
  figure is selected** — necessary subsidy or subsidy per tonne — and not
  for journey time, passengers or CO₂e (feedback topic `compare`).
- **Comparison overlay reworded** (four lines, EN/DE): *Compare the figures
  across scenarios and compositions: the selected train in every scenario,
  every train in the selected one, on a figure of your choice. The baseline
  is marked.* / *Vergleiche die Zahlen über Szenarien und Zugbildungen: der
  gewählte Zug in jedem Szenario, jeder Zug im gewählten, für eine Kennzahl
  Deiner Wahl. Basis markiert.*

## Updates by file

| File | Change |
|---|---|
| `frontend/src/lib/compareKpis.ts` | `isMoney` on the KPI definition, set for `subsidy` and `subsidyPerT` — one flag, read by both places, so a new euro KPI gets its sticker by declaration. |
| `frontend/src/components/MainKpiGrid.vue` | Sticker on money tiles. |
| `frontend/src/components/CompareSection.vue` | Sticker in the headline while the picked KPI is money. |
| `frontend/src/i18n/locales/en.json`, `de.json` | `compare.titleHint`. 910 keys each, in parity. |

## Deployment handover

Frontend image only.

## Verification (Node 22)

`vue-tsc --noEmit` clean · `eslint .` clean · `prettier --check` clean ·
`vitest run` **376 passed** · `vite build` OK.

## Commit split

- `feat(builder): 2032-prices sticker on the euro KPIs and the comparison` — components + lib.
- `chore(i18n): comparison overlay starts with what it is for` — locales.
- `docs: manifest` — this file.
