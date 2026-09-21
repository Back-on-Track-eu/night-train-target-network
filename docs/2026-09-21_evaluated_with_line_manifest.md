# "Evaluated with …" line: demand level instead of fares — manifest

Date: 2026-09-21 · Scope: **frontend only.** No backend change, no version
bump.

## What changed

The inputs line above the KPI grid read *Evaluated with NEW-BAL-7 · 3 days
per week · fares 0.030–0.060 €/km · catering 1.00 €–2.00 €/passenger*. Fares
have no influence on demand in the current model, so naming them next to the
passenger figures suggested an elasticity that is not there. The line now
reads **Evaluated with NEW-BAL-7 · 3 days per week · Medium demand** (the
T-shirt size of the potential-demand level, or *Custom demand*), then
*change ↓* as before. DE: *Ausgewertet mit NEW-BAL-7 · 3 Tage pro Woche ·
Nachfrage Mittel*.

## Updates by file

| File | Change |
|---|---|
| `frontend/src/components/ProposalResults.vue` | `priceLabel` (fares + catering) replaced by `demandLabel` from `demandFromRequest()`; the compare-format import it needed is gone; comment says why fares are left out. |
| `frontend/src/i18n/locales/en.json`, `de.json` | `compare.evaluatedWith` gains `{demand}`; new `compare.demandPart`; `compare.pricePart` and `compare.cateringPart` removed (no user left). 898 keys each, in parity. |

## Deployment handover

Frontend image only.

## Verification (Node 22)

`vue-tsc --noEmit` clean · `eslint .` clean · `prettier --check` clean ·
`vitest run` **376 passed** · `vite build` OK.

## Commit split

- `fix(builder): inputs line names the demand level, not the fares` — component + locales.
- `docs: evaluated-with manifest` — this file.
