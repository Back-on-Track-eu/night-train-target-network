# "No stops found" → suggest the missing stop — delivery manifest

Date: 2026-09-21 · Scope: **frontend only**, no backend change, no version bump.
Builds on the `/docs/feedback` page delivered the same day.

A search that matches nothing is the one moment the catalogue's gaps are
visible to the person who can name them. It now offers the way to report one,
carrying what they searched for.

## What changed

| # | File | Change |
|---|---|---|
| 1 | **new** `frontend/src/lib/feedbackLink.ts` | `docsFeedbackUrl(topic, query?)` and `FEEDBACK_TOPIC_MISSING_STOP`. Absolute, not a router link — `/docs/` is a separate static site on this origin, the same reason `factorFeedback.ts` builds its paths by hand. The URL carries a short **alias**, not the feedback API's category strings: the page holds the alias → (category, sub_category) map, so the taxonomy can be reworded without breaking a link already in the wild. `query` is trimmed and capped at 120 characters, mirroring the form's own `QUERY_MAX`. |
| 2 | **new** `frontend/src/lib/feedbackLink.test.ts` | Five cases: the bare topic, the query, escaping (`&`, `#` — a station name with an ampersand is not exotic, and an unescaped one would end the parameter), the empty and whitespace query, the pasted paragraph. |
| 3 | `frontend/src/components/StopSelect.vue` | The empty-result branch becomes two lines: "No stops found", then the prompt and a link to `/docs/feedback?topic=missing-stop&q=…` in a second tab (`rel="noopener noreferrer"` — the itinerary being built in this one is not saved). The query goes over **as typed**, not as the lowercased haystack term, so the form quotes it back. Only this branch changes: "still loading", "failed to load" and "the catalogue is empty" keep their own wording. |
| 4 | `frontend/src/i18n/locales/en.json`, `de.json` | `proposal.missingStopHint`, `proposal.missingStopLink`. |

## Behaviour

Typing a station the catalogue does not have into Add stop now shows, under
"No stops found": *Is a station missing from the catalogue? **Suggest it***.
The link opens `/docs/feedback` in a new tab with "Route or timetable" /
"Missing stop / suggest new stop" preselected, the subject line reading
`Missing stop: <what was typed>`, and the message opening with the sentence
that says so. The reader adds where it is and why it matters, and sends.

## Verification (Node 22)

`vue-tsc --noEmit` clean · `eslint .` clean · `prettier --check` clean ·
`vitest run` **337 passed** (332 + the five new) · `vite build` OK.

## Commit split

- `feat(stops): offer the feedback page when a stop search finds nothing` — files 1, 3, 4.
- `test(stops): the feedback deep link` — file 2.
- `docs: missing-stop link manifest` — this file.
