/**
 * Deep links from the builder's info overlays into the documentation site:
 * the route-planning page (docs-site/routing.md), the scenarios page
 * (docs-site/scenarios.md), the views page (docs-site/views.md), and the
 * cost and demand pages the Details tabs and the breakdown hand over to. Absolute paths, not router links: /docs/ is a
 * separate static site served on this origin — the same reason
 * factorFeedback.ts builds its cost-page paths by hand.
 *
 * The fragments are heading ids — slugs on routing.md, explicit {#id}s on
 * scenarios.md and views.md. Either breaks silently when the heading changes (the page
 * opens at the top), so both pages carry a comment pointing back here.
 */

import type { CompareKpiKey } from './compareKpis'
import type { ViewKey } from '@/types/api'

const ROUTING = '/docs/routing'
const SCENARIOS = '/docs/scenarios'
const VIEWS = '/docs/views'

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

/** The cost/revenue breakdown headline: revenue minus cost minus margin. */
export const DOCS_NET_RESULT = '/docs/cost/net'

/** Every euro is 2032 money except the rolling stock purchase — the sticker's page. */
export const DOCS_PRICE_BASIS = '/docs/price-basis'

/** One section per box on the Details tabs — each box's ⓘ hands over to it. */
export const DOCS_DETAIL_PANEL = {
  schedule: '/docs/demand#schedule',
  prices: '/docs/demand#prices',
  potential: '/docs/demand#potential-demand',
  groups: '/docs/demand#traveller-groups',
  od: '/docs/demand#od-matrix',
  ladder: '/docs/demand#utilisation',
  follows: '/docs/demand#what-follows',
  selectedComposition: '/docs/methodology/compositions#selected-composition',
  compositionComparison: '/docs/methodology/compositions#composition-comparison',
  overheadVariable: '/docs/cost/var-overhead',
  overheadFixed: '/docs/cost/fix-overhead',
  overheadMargin: '/docs/cost/ebit-margin',
  tac: '/docs/cost/tac',
  stations: '/docs/cost/station-charge',
  facilities: '/docs/cost/parking',
  energy: '/docs/cost/energy',
  infrastructureYear: '/docs/cost/infrastructure-total',
} as const

/** How each slice of the breakdown is accounted — the view tabs' overlays.
 *  Keyed by ViewKey so a new view without a docs section is a type error. */
export const DOCS_VIEW: Record<ViewKey, string> = {
  route: `${VIEWS}#full-route`,
  per_trip_pair: `${VIEWS}#full-route`,
  per_trip_pair_per_country: `${VIEWS}#by-country`,
  per_trip_pair_per_section: `${VIEWS}#by-route-section`,
  per_trip_per_stop: `${VIEWS}#by-stop`,
}

/** One page per Details tab — the tab's hover overlay hands over to it. */
export const DOCS_DETAILS_TAB: Record<
  'demand' | 'supply' | 'operation' | 'infrastructure' | 'overhead',
  string
> = {
  demand: '/docs/demand',
  // The tariff the Supply tab's prices panel edits is described with the
  // demand it meets, on the same page.
  supply: '/docs/demand',
  operation: '/docs/cost/operator-total',
  infrastructure: '/docs/cost/infrastructure-total',
  // The three overhead panels are the operator's own shares and its margin —
  // the net-result page is where all three come together.
  overhead: '/docs/cost/net',
}
