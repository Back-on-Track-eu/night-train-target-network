# Report a problem on every result panel; overlays on the comparison, the breakdown and the Details tabs — manifest and handover

Date: 2026-09-21 · Scope: **frontend + docs-site + one static list on the backend.**
Backend `0.5.4 → 0.5.5`. No model bump: `feedback_serialize.py` is not a gated file.

## What changed

**Report a problem — one icon per panel.** The same mechanics as the map pill's
report menu, one small icon in each panel header: the feedback page opens in
a new tab with the panel's topic preselected, the subject `<panel> · A → B`,
and the route's input parameters under the reader's words. Panels:

| Where | Topic alias | Sub-category (new, static) |
|---|---|---|
| Scenario and main figures | `kpis` | Scenario and main figures |
| Compare across scenarios | `compare` | Scenario comparison |
| Costs and revenue | `breakdown` | Cost and revenue breakdown |
| every box on a Details tab | `details-<tab>` | Details — Demand / Supply / Train operation / Infrastructure / Overhead |

All under the category *Evaluation — results / view*, which now lists the
eight panels after the internal views (`group: "Builder panel"`). The Details
boxes need no per-panel wiring: `DetailsSection` provides the active tab's
topic, `DetailPanel` reads it, and since the tabs render with `v-if` the
boxes on screen are exactly the active tab's; each box's own title goes into
the subject.

The icon renders only once a route is calculated — before that there is
nothing to report on. Inside the breakdown's `<summary>` the icon and the ⓘ
stop their clicks so they never toggle the section.

**Info overlays (≤ 4 lines, docs link):** the *Compare across scenarios*
headline (→ scenarios page), the *Costs and revenue* headline (→ net result),
and every Details tab pill on hover or focus (→ demand page for Demand and
Supply, operator total, infrastructure total, net result). `DetailPanel`'s
long-reserved `docPath` prop is now live: a Details box that passes it gets
the "read more" link on its ⓘ.

## Updates by file

| File | Change |
|---|---|
| `backend/api/helpers/feedback_serialize.py` | `_RESULT_PANEL_SUB_CATEGORIES`, appended to the results/view list. |
| `backend/tests/test_60_feedback_api.py` | View test filters on `group is None`; new test pins the eight panels. |
| `backend/api/README.md`, `backend/pyproject.toml` | Categories table; `0.5.5`. |
| **new** `frontend/src/composables/useReportContext.ts` | Provide/inject of `{ ends, context }` from `ProposalViewport` to every panel. |
| **new** `frontend/src/composables/useDetailsTabReport.ts` | Provide/inject of the active Details tab's topic. |
| **new** `frontend/src/components/ReportProblemLink.vue` | The icon: `topic` + optional `panel`; null href → not rendered. |
| `frontend/src/lib/feedbackLink.ts` | `ReportPanel` alias type. |
| `frontend/src/lib/docsLinks.ts` | `DOCS_NET_RESULT`, `DOCS_DETAILS_TAB`. |
| `frontend/src/components/ProposalViewport.vue` | `reportContext` computed (was inline in `reportHrefs`), provided; the pill's menu built from it. |
| `frontend/src/components/ProposalResults.vue`, `CompareSection.vue`, `CostRevenueBreakdown.vue` | Headline ⓘ / report icons. |
| `frontend/src/components/DetailsSection.vue` | Tab topic provider; tab hover overlays on one shared `InfoPopover`. |
| `frontend/src/components/details/DetailPanel.vue` | Report icon from the injected topic; `docPath` wired to the ⓘ. |
| `frontend/src/i18n/locales/en.json`, `de.json` | `report.panel`, `compare.titleHint`, `evaluation.sections.finance.hint`, `details.tabHints.*`. |
| `docs-site/.vitepress/theme/components/GeneralFeedbackForm.vue` | The eight panel topics, generated from one table. |

## Handover

- **Frontend.** A new result panel: add its alias to `ReportPanel`, its
  sub-category to `_RESULT_PANEL_SUB_CATEGORIES` and the form's table — three
  places, the test pins the backend one. A Details box that has a docs page
  passes `doc-path`.
- **Deployment.** API restart for the new sub-categories (`docker restart
  night-train-api` locally; the api container on the server) and the frontend
  image. No migration.

## Verification

Backend `ruff format --check` / `ruff check` clean; `test_60` needs the stack
— include in the next integration run. Frontend `vue-tsc`, `eslint`,
`prettier --check` clean · `vitest run` 370 passed · `vite build` OK · EN/DE in
parity, every new overlay ≤ 4 lines. Docs `vitepress build` OK.
