# Breakdown views: overlays for Full route / By country / By route section / By stop — manifest and handover

Date: 2026-09-21 · Scope: **frontend + documentation site.** No backend
change, no version bump.

## What changed

- **A new documentation page, _Views of costs and revenue_** (`/docs/views`),
  in the sidebar under _The model_ after _Demand and revenue_. It explains,
  slice by slice, where each euro of the breakdown lands: the full route
  (plain summation, plus the trip-pair case), by country (costs where the
  train drives or the event happens, revenue where the passengers sit, with
  the per-item table), by route section (physical piece of track, both
  directions, km-share of everyone on board, why sections do not add up),
  by stop (boarding and alighting passengers only, half-origin / half-
  destination split of the fleet costs), and the units (per-km figures
  divide by the slice's own kilometres, hence comparable but not additive;
  the class switch). Written from `backend/models/evaluation/README.md`
  layers 1–3 for a reader who has never seen a share table.
- **Hover overlays on the four view tabs** of _Costs and revenue_ (five
  with _By trip pair_, when a route has several pairs), in the standard
  shape: one short description (≤ 4 lines at the overlay width, EN and DE),
  _Read more in the documentation_ to the matching section of the new page,
  and _Provide feedback_ under the _Cost and revenue breakdown_ topic with
  the view's name in the subject (e.g. `By country · Luxembourg →
  Bratislava`).

## Updates by file

| File | Change |
|---|---|
| **new** `docs-site/views.md` | The page; explicit `{#id}` anchors with the comment tying them to `docsLinks.ts`. |
| `docs-site/.vitepress/config.ts` | Sidebar entry. |
| `frontend/src/lib/docsLinks.ts` | `DOCS_VIEW: Record<ViewKey, string>` — a new view without a docs section is a type error. |
| `frontend/src/components/ViewRow.vue` | One shared `InfoPopover` under the tab row, opened on hover/focus of a tab (the Details card's pattern), with `DocsReadMore` and `FeedbackLink`. |
| `frontend/src/i18n/locales/en.json`, `de.json` | `proposal.evaluation.viewHints.*` (5 keys). 902 keys each, in parity. |

## Handover

- **Docs anchors are a contract** (`full-route`, `by-country`,
  `by-route-section`, `by-stop`, `units`): change one only together with
  `docsLinks.ts`.
- The docs page describes the allocation rules as of CALC 0.9.34; a change
  to `views.py` allocation should be mirrored there (the README is the
  source, the page its reader-facing version).

## Deployment handover

Frontend image only (the docs bundle is built into it). No environment
variable, no migration, no cache flush.

## Verification (Node 22)

Frontend: `vue-tsc --noEmit` clean · `eslint .` clean · `prettier --check`
clean · `vitest run` **376 passed** · `vite build` OK.
Docs site: `prettier --check` clean · `vitepress build` OK, `/views` renders
with all five anchors.

## Commit split

- `docs(site): views of costs and revenue — how each slice is accounted` — docs-site files.
- `feat(breakdown): overlays on the view tabs with docs and feedback links` — frontend files.
- `docs: breakdown view overlays manifest` — this file.
