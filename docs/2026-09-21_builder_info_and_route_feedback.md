# Builder info overlays, route feedback, saved line — manifest and handover

Date: 2026-09-21 · Scope: **frontend + documentation site.** No backend change,
no version bump — the routing feedback uses the existing
`Route or timetable` / `Routing / track geometry` pair.

## What changed, by feedback item

1. **Expert timetable** — hovering or focusing the pill opens the tool-row
   overlay with what expert mode adds over the automatic timetable, and a link
   to *Route planning › Expert timetable*.
2. **Night legend** — an ⓘ after "alighting" explains the 00:00–05:00 window,
   the three stop kinds and why night stops sell nothing, linking to
   *› The night and its stops*.
3. **Route stats** — an ⓘ beside the panel title explains the routed path,
   distance, countries and what average speed includes, linking to
   *› The route figures*.
4. **Report a routing problem** — a third button in the map pill, after
   share. It opens `/docs/feedback?topic=routing&q=<A → B>&context=…` in a new
   tab: the form preselects the category, titles the report `Routing: A → B`,
   opens with a sentence asking what looks wrong, and carries the route's
   input parameters below a separator — stops with ids, scenario, train,
   timetable mode (automatic / expert / fixed night between X and Y), the
   result (km, average km/h, countries), the proposal link and the route
   builder version. Built from the **committed** state: the report is about
   the route that was drawn, not edits waiting for a recalculation. English
   regardless of UI language — it is data for the working group.
5. **"Proposal was saved automatically"** — dropped. Its only case without
   another signal was the silent composition auto-save, and the ownership
   line above the builder already says every change is saved automatically;
   an explicit save still toasts. A **failed** save keeps its inline alert,
   which has no substitute.

## Updates by file

| File | Change |
|---|---|
| **new** `frontend/src/lib/docsLinks.ts` | The three `/docs/routing#…` deep links. |
| **new** `frontend/src/components/DocsReadMore.vue` | The overlay's "read more in the documentation" line — one wording and look for every hand-over. |
| `frontend/src/components/InfoHint.vue` | Optional `docsHref`, rendered with `DocsReadMore` below the text. |
| `frontend/src/lib/feedbackLink.ts` (+ test) | `FEEDBACK_TOPIC_ROUTING`, a `context` parameter on `docsFeedbackUrl()` (capped at 1,500 chars), and `routingFeedbackContext()`, which formats a `RoutingReport` one labelled line per input and leaves out what is unknown. |
| `frontend/src/components/MapShareBar.vue` | `feedbackHref` prop; a report link after share when there is a route. |
| `frontend/src/components/ProposalViewport.vue` | Tool hint gains an optional docs link (`showToolHint(event, text, docs)`); expert pill wired to it; `InfoHint`s on the night legend and route stats; `routingFeedbackHref` computed and passed to the pill; the saved line, the `saved` ref and its `mdiCheckCircle` import removed, and the comment on the silent selection save updated. |
| `frontend/src/i18n/locales/en.json`, `de.json` | `proposal.docsReadMore`, `expert.toggleHint`, `night.legendHint`, `routeStatsHint`, `share.reportRoute`. EN/DE in parity. |
| `docs-site/routing.md` | Three new sections — *The route figures*, *The night and its stops*, *Expert timetable* — with a comment that their slugs are linked from `docsLinks.ts`. |
| `docs-site/.vitepress/theme/components/GeneralFeedbackForm.vue` | `TOPICS` entries carry a `lead` (replacing the missing-stop special case keyed on its subject), the `routing` topic, and a `context` URL parameter appended to the message under "— What this is about —". |

## Frontend handover

- **Docs anchors are a contract.** The three headings in `docs-site/routing.md`
  are linked by slug; renaming one opens the page at the top without an error.
  The comment above them says so.
- **Feedback topics are a contract too.** The aliases (`missing-stop`,
  `routing`) live in `lib/feedbackLink.ts` and in the form's `TOPICS`; add a
  new one in both.
- **`InfoHint` with a link** stays open while the cursor is inside the overlay
  (InfoPopover's hover intent), so the link is reachable by mouse.

## Deployment handover

Frontend image only (the docs bundle is built into it). No environment
variable, no migration, no cache flush.

## Verification (Node 22)

Frontend: `vue-tsc`, `eslint`, `prettier --check` clean · `vitest run`
**368 passed** (5 new) · `vite build` OK.
Docs site: `vitepress build` OK with dead-link checking on; the built
`routing.html` carries all three anchors; `prettier --check` clean on both
touched files.

## Commit split

- `feat(builder): explain expert mode, the night and the route figures; report a route` — all non-test files.
- `test(builder): routing feedback context` — `feedbackLink.test.ts`.
- `docs: builder info overlays manifest` — this file.
