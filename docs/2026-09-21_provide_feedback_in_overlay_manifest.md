# "Provide feedback", inside the info overlay — manifest and handover

Date: 2026-09-21 · Scope: **frontend** plus one comment on the docs site.
No backend change, no version bump.

## What changed

- **Wording.** "Report a problem" is *Provide feedback* everywhere: the map
  pill's button, its two menu items (*Feedback on the route* / *Feedback on
  the timetable*), the panel link. DE: *Feedback geben*, *Feedback zur
  Strecke*, *Feedback zum Fahrplan*. The pill icon changes from the alert
  bubble to a plain message bubble to match.
- **Placement.** The second icon beside each panel's ⓘ is gone. The
  *Provide feedback* link — icon + text — now sits inside the ⓘ overlay,
  under *Read more in the documentation*, on every panel that had the icon:
  Scenario and main figures, Compare across scenarios, Costs and revenue,
  and every box on a Details tab. Same target, same context (topic, route
  ends, input parameters); it appears once a route is calculated, as before.

## Updates by file

| File | Change |
|---|---|
| `frontend/src/components/FeedbackLink.vue` (renamed from `ReportProblemLink.vue`) | Icon + text line styled like `DocsReadMore`; label `proposal.feedback.panel`; comment on why it lives in the overlay. |
| `frontend/src/components/InfoHint.vue` | Optional `feedbackTopic` / `feedbackPanel`; renders `FeedbackLink` under the docs line. |
| `frontend/src/components/ProposalResults.vue`, `CompareSection.vue`, `CostRevenueBreakdown.vue`, `details/DetailPanel.vue` | Standalone icon removed; topic passed to `InfoHint`. |
| `frontend/src/components/MapShareBar.vue` | Message-bubble icon. |
| `frontend/src/components/ProposalViewport.vue`, `composables/useDetailsTabReport.ts` | Comments only. ProposalViewport contains today's earlier changes — extract after those zips. |
| `frontend/src/i18n/locales/en.json`, `de.json` | `proposal.share.report/reportRoute/reportTimetable` reworded; `proposal.report.panel` → `proposal.feedback.panel`. 899 keys each, in parity. |
| `docs-site/.vitepress/theme/components/GeneralFeedbackForm.vue` | Comment only. |

## Not renamed

Code identifiers (`ReportPanel`, `useReportContext`, `reportContext`, the
feedback-link `topic` aliases) keep their names — they are internal and the
URL aliases are a contract with links already in the wild.

## Deployment handover

Frontend image only (docs bundle included). No environment variable, no
migration, no cache flush.

## Verification (Node 22)

`vue-tsc --noEmit` clean · `eslint .` clean · `prettier --check` clean ·
`vitest run` **376 passed** · `vite build` OK.

## Commit split

- `feat(builder): "Provide feedback" as a link inside each panel's info overlay` — components, composable, locales, docs-site comment.
- `docs: provide-feedback manifest` — this file.
