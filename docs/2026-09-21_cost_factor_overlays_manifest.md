# Costs and revenue: factor overlays streamlined — manifest

Date: 2026-09-21 · Scope: **frontend only.** No backend change, no version
bump.

## What changed

The ⓘ on every row of the cost tree and the revenue ledger opened a wider
overlay of its own kind: a large heading, an open-in-new icon beside it and
the summary underneath. It now has the same shape as every other overlay in
the builder — one short paragraph (the row's label leading the backend's
one-sentence summary), *Read more in the documentation* (the row's own
`/docs/cost/<factor>` page, as before) and *Provide feedback*, prefilled
with the *Cost and revenue breakdown* topic and the row's label in the
subject (e.g. `Driver · Luxembourg → Bratislava`). The section title's ⓘ
already had this shape.

## Updates by file

| File | Change |
|---|---|
| `frontend/src/components/FactorInfoPopover.vue` | Overlay content rebuilt on `DocsReadMore` + `FeedbackLink`, width and type as `InfoHint`; icon-link, heading and the i18n dependency removed. |
| `frontend/src/i18n/locales/en.json`, `de.json` | `proposal.evaluation.info.readMore` removed (no user left). 897 keys each, in parity. |

## Deployment handover

Frontend image only.

## Verification (Node 22)

`vue-tsc --noEmit` clean · `eslint .` clean · `prettier --check` clean ·
`vitest run` **376 passed** · `vite build` OK.

## Commit split

- `feat(breakdown): one overlay shape for the cost and revenue rows` — component + locales.
- `docs: cost factor overlays manifest` — this file.
