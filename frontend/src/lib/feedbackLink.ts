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
/** A computed route whose path looks wrong — detour, line, border, distance. */
export const FEEDBACK_TOPIC_ROUTING = 'routing'
/** A computed route whose timetable looks wrong — times, speeds, the night. */
export const FEEDBACK_TOPIC_TIMETABLE = 'timetable'

/** Both mirror the form's own caps: what is cut here is cut there anyway,
 *  and a search box can hold a paragraph if someone pastes one. */
const QUERY_MAX = 120
const CONTEXT_MAX = 1_500

/**
 * The feedback page with a topic preselected. `query` becomes part of the
 * subject line (the search text, the route's two ends); `context` is appended
 * to the message below the reader's own words, so the report arrives with
 * what it is about already in it.
 */
export function docsFeedbackUrl(topic: string, query?: string, context?: string): string {
  const params = new URLSearchParams({ topic })
  const trimmed = query?.trim()
  if (trimmed) params.set('q', trimmed.slice(0, QUERY_MAX))
  const block = context?.trim()
  if (block) params.set('context', block.slice(0, CONTEXT_MAX))
  return `/docs/feedback?${params.toString()}`
}

/** Everything a route or timetable report needs to reproduce what it is about. */
export interface RoutingReport {
  stops: { name: string; id: string }[]
  scenario: string | null
  composition: string | null
  /** Expert overrides (departures, leg minutes, own return times) in effect. */
  expert: boolean
  /** The two stops the night is fixed between, by name; null = automatic. */
  nightBetween: [string, string] | null
  km: number | null
  kmh: number | null
  countries: string[]
  /** First departure → last arrival per direction, as shown in the builder
   *  ("19:30 Budapest-Déli → 09:31 (+1) Bruxelles-Midi"); null before a route. */
  times: { outbound: string; return: string } | null
  proposalUrl: string | null
  routeBuilderVersion: string | null
}

/**
 * The input parameters of a computed route, one labelled line each — the
 * block both report topics carry under the reader's description. One block
 * for both: a timetable problem is often a routing one in disguise, and the
 * working group should not have to ask for the other half.
 * English regardless of the UI language: it is data for the working group,
 * which reads the reports, and labels that change with the reader's locale
 * would make them harder to compare.
 */
export function routingFeedbackContext(report: RoutingReport): string {
  const timetable = [
    report.expert ? 'expert (edited departures or leg minutes)' : 'automatic, centred on 02:30',
    ...(report.nightBetween
      ? [`night fixed between ${report.nightBetween[0]} and ${report.nightBetween[1]}`]
      : []),
  ].join('; ')
  const result = [
    report.km !== null ? `${Math.round(report.km)} km` : null,
    report.kmh !== null ? `${Math.round(report.kmh)} km/h average` : null,
    report.countries.length ? `through ${report.countries.join(', ')}` : null,
  ].filter((part): part is string => part !== null)
  const lines = [
    `Stops: ${report.stops.map((s) => `${s.name} (${s.id})`).join(' → ')}`,
    report.scenario ? `Scenario: ${report.scenario}` : null,
    report.composition ? `Train: ${report.composition}` : null,
    `Timetable: ${timetable}`,
    result.length ? `Result: ${result.join(', ')}` : null,
    report.times ? `Outbound: ${report.times.outbound}` : null,
    report.times ? `Return: ${report.times.return}` : null,
    report.proposalUrl ? `Proposal: ${report.proposalUrl}` : null,
    report.routeBuilderVersion ? `Route builder: ${report.routeBuilderVersion}` : null,
  ]
  return lines.filter((line): line is string => line !== null).join('\n')
}
