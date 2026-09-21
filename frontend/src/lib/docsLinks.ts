/**
 * Deep links from the builder's info overlays into the documentation site:
 * the route-planning page (docs-site/routing.md) and the scenarios page
 * (docs-site/scenarios.md). Absolute paths, not router links: /docs/ is a
 * separate static site served on this origin — the same reason
 * factorFeedback.ts builds its cost-page paths by hand.
 *
 * The fragments are heading ids — slugs on routing.md, explicit {#id}s on
 * scenarios.md. Either breaks silently when the heading changes (the page
 * opens at the top), so both pages carry a comment pointing back here.
 */

import type { CompareKpiKey } from './compareKpis'

const ROUTING = '/docs/routing'
const SCENARIOS = '/docs/scenarios'

/** Path, distance, average speed, countries — what the route stats panel shows. */
export const DOCS_ROUTE_FIGURES = `${ROUTING}#the-route-figures`
/** The 00:00–05:00 window and the boarding / night / alighting stops. */
export const DOCS_NIGHT = `${ROUTING}#the-night-and-its-stops`
/** What the expert timetable adds to the automatic one. */
export const DOCS_EXPERT_TIMETABLE = `${ROUTING}#expert-timetable`

/** What a scenario fixes — the panel header's overlay. */
export const DOCS_SCENARIO = `${SCENARIOS}#the-scenario`

/** One section per headline figure, in the tile grid's order. */
export const DOCS_KPI: Record<CompareKpiKey, string> = {
  journeyTime: `${SCENARIOS}#journey-time`,
  pax: `${SCENARIOS}#passenger-trips`,
  paxKm: `${SCENARIOS}#passenger-km`,
  subsidy: `${SCENARIOS}#necessary-subsidy`,
  shiftAir: `${SCENARIOS}#shifted-from-air`,
  shiftOther: `${SCENARIOS}#shifted-from-car-or-induced`,
  co2: `${SCENARIOS}#co2-saved`,
  subsidyPerT: `${SCENARIOS}#subsidy-per-t-co2`,
}
