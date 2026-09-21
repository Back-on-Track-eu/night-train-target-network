# Compare across scenarios: no horizontal scroll on a full-width screen — manifest

Date: 2026-09-21 · Scope: **frontend only.** No backend change, no version
bump, no i18n change.

## What changed

The "all combinations" grid's row labels read *Infrastructure 2026 · HSR +
TT OPT* on every row — about the width of two cells — which, with twelve
compositions, pushed the table into a horizontal scroll bar even at full
width. The label is now the operating condition alone (*Base*, *TT OPT*,
*HSR*, *HSR + TT OPT*), and the network is named once in small muted text
above the first row of its group. When a second network (Infra 2032) is
released, its rows form a second labelled group the same way.

## Updates by file

| File | Change |
|---|---|
| `frontend/src/components/ScenarioCompositionGrid.vue` | Row model gains `startsGroup`; row header renders the network label only on a group's first row, the condition beneath; comment explains the width reason. |

## Deployment handover

Frontend image only.

## Verification (Node 22)

`vue-tsc --noEmit` clean · `eslint .` clean · `prettier --check` clean ·
`vitest run` **376 passed** · `vite build` OK.

## Commit split

- `fix(compare): condition-only row labels so twelve compositions fit without scrolling` — component.
- `docs: compare grid manifest` — this file.
