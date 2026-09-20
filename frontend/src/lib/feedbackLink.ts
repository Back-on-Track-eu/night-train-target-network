/**
 * feedbackLink.ts
 * ===============
 * Deep links into the documentation site's general feedback page, where a
 * reader can tell the working group what the app could not give them.
 *
 * Absolute, and deliberately not a vue-router link — the same reason
 * factorFeedback.ts builds its docs paths by hand: /docs/ is a separate
 * static site served by nginx on this origin, not a route this SPA owns.
 *
 * The link carries a short ALIAS rather than the protocol strings the
 * feedback API expects. The page (docs-site GeneralFeedbackForm.vue) holds
 * the alias → (category, sub_category) map, so the backend can reword its
 * taxonomy without breaking a link someone has already sent on. Renaming an
 * alias, on the other hand, means changing it in both places.
 */

/** Something the stop catalogue does not have. */
export const FEEDBACK_TOPIC_MISSING_STOP = 'missing-stop'

/** Mirrors the form's own QUERY_MAX: what is cut here is cut there anyway,
 *  and a search box can hold a paragraph if someone pastes one. */
const QUERY_MAX = 120

/**
 * The feedback page with a topic preselected, and optionally the text the
 * user was searching for — which the page turns into the subject line and
 * the first sentence of the message, so the report arrives with its context
 * already in it.
 */
export function docsFeedbackUrl(topic: string, query?: string): string {
  const params = new URLSearchParams({ topic })
  const trimmed = query?.trim()
  if (trimmed) params.set('q', trimmed.slice(0, QUERY_MAX))
  return `/docs/feedback?${params.toString()}`
}
