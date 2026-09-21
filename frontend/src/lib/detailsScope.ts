// The arithmetic and the dirty-tracking behind zone D's "Details" card, kept
// out of the SFCs so it can be tested without mounting anything (vitest runs
// in node, no jsdom — see AGENTS.md).
//
// Three inputs change the calculation: the SCHEDULE and the PRICES on the
// Supply tab, the DEMAND on the Demand tab (docs/2026-09-18_manual_demand_
// guide.md D2). Each is a scope. A panel either OWNS a scope — it recomputes
// here, on the page, and says so — or DEPENDS on one, in which case it keeps
// the figures it has, greys out, and waits for the backend. Nothing ever
// shows a number that mixes a previewed input with a calculated one.

/** Days of the evaluation year — 2032 is a leap year, the same calendar the
 *  backend counts operating days on (models/route/model.py EVALUATION_YEAR).
 *  A month is a twelfth of it everywhere. */
export const DAYS_IN_YEAR = 366

/** The frequency a new proposal starts at — the backend's own
 *  DEFAULT_DAYS_PER_WEEK (models/route/model.py, ROUTE_BUILDER 0.9.40). */
export const DEFAULT_DAYS_PER_WEEK = 3
export const MIN_DAYS_PER_WEEK = 1
export const MAX_DAYS_PER_WEEK = 7

export function clampDaysPerWeek(value: number): number {
  return Math.min(MAX_DAYS_PER_WEEK, Math.max(MIN_DAYS_PER_WEEK, Math.round(value)))
}

/** The request block for a frequency: one figure, which the backend expands
 *  onto its twelve months, so a request that posts it and one that posts the
 *  spelled-out month map hash to the same family. */
export function scheduleRequest(daysPerWeek: number): { schedule: { days_per_week: number } } {
  return { schedule: { days_per_week: clampDaysPerWeek(daysPerWeek) } }
}

/** The frequency a resolved request echo describes — what the figures on
 *  screen were computed with. The echo always carries the month map; a flat
 *  map reads back exactly, a seasonal one (stored before the one-frequency
 *  UI, or written by a later seasonal UI) as its rounded average over the
 *  year, which is what one figure can say about it. */
export function daysPerWeekFromRequest(
  schedule: Record<string, number> | null | undefined,
): number {
  if (!schedule) return DEFAULT_DAYS_PER_WEEK
  const months = Array.from({ length: 12 }, (_, i) => Number(schedule[String(i + 1)] ?? 0))
  const average = months.reduce((sum, d) => sum + d, 0) / 12
  return clampDaysPerWeek(average)
}

export function operatingDaysPerYear(daysPerWeek: number): number {
  return (DAYS_IN_YEAR * daysPerWeek) / 7
}

/** Physical rakes: the cycle length in days times the days per week, rounded
 *  up (ROUTE_BUILDER 0.9.35). Exact on the page — the cycle itself is a
 *  constant of the timetable, which only the backend can redo, so it is
 *  taken from the last result. */
export function trainsetsFor(daysPerWeek: number, cycleDays: number | null): number | null {
  if (cycleDays === null || cycleDays <= 0) return null
  return Math.ceil((cycleDays * daysPerWeek) / 7)
}

export interface SupplyFigures {
  operatingDays: number
  departures: number
  trainKm: number
  placesOffered: number
  placeKmOffered: number
  trainsets: number | null
}

/**
 * The four schedule-owned figures plus the two place figures, from the
 * frequency.
 *
 * cycleDistanceKm is the route's own total over BOTH directions (the
 * summary's total_distance_km), so one operating day is one cycle: the
 * backend's train_km_per_year is cycle km × operating days and its
 * departures_per_year is operating days × 2 per pair.
 */
export function supplyFigures(
  daysPerWeek: number,
  cycleDistanceKm: number,
  places: number,
  cycleDays: number | null,
  tripPairs = 1,
): SupplyFigures {
  const operatingDays = operatingDaysPerYear(daysPerWeek)
  const departures = operatingDays * 2 * tripPairs
  const trainKm = operatingDays * cycleDistanceKm
  return {
    operatingDays,
    departures,
    trainKm,
    placesOffered: departures * places,
    placeKmOffered: places * trainKm,
    trainsets: trainsetsFor(daysPerWeek, cycleDays),
  }
}

/** One of the two journeys the price table prices a fare on: the route's
 *  longest OD pair (its terminals) and its shortest (the closest two
 *  consecutive stops). €/km alone is too abstract to judge a fare by. */
export interface ExampleOd {
  name: string
  km: number
}

/** One line of a Kassenzettel. Lives here rather than in the component
 *  because `<script setup>` cannot export types, and three panels build
 *  these arrays. */
export interface ReceiptLine {
  label: string
  /** What the figure was computed on — "7.00 €/km", "4 × terminal event". */
  basis?: string | null
  eur: number
  /** A note row: printed across the table in muted type, no euros and no
   *  share. For the sentences a receipt needs to stay honest — catering
   *  being outside a base, a margin nobody is actually paid. */
  note?: boolean
}

// --- the change-scope rule ---------------------------------------------------

export type Scope = 'schedule' | 'prices' | 'demand'

/** Which scopes each tab has a panel waiting on — the dot beside the tab
 *  label (D2). Supply's What-follows panel waits on the demand; Train
 *  operation (the subsidy column) and Overhead (EBIT on revenue) on all
 *  three; Infrastructure only on the schedule; Demand owns its scope and
 *  previews, so it never waits. */
export const TAB_AWAITS: Record<
  'demand' | 'supply' | 'operation' | 'infrastructure' | 'overhead',
  readonly Scope[]
> = {
  demand: [],
  supply: ['demand'],
  operation: ['schedule', 'prices', 'demand'],
  infrastructure: ['schedule'],
  overhead: ['schedule', 'prices', 'demand'],
}

/** The tariff, per class_main. Four maps since CALC 0.9.30: the base fare
 *  has a fixed and a distance term, the services sold with a ticket are
 *  their own revenue, and catering differs by class because the classes
 *  differ in what their base fare already includes. */
export interface Tariff {
  faresPerKm: Record<string, number>
  faresPerPax: Record<string, number>
  servicesPerPax: Record<string, number>
  cateringPerPax: Record<string, number>
}

/** The manual demand as the Demand tab edits it and the request posts it
 *  (DEMAND 0.1.0, guide §4). Weights and pins are keyed by stop id. */
export interface DemandInputs {
  level: string
  passengersPerYear: number
  groupSharesPct: Record<string, number>
  od: {
    preset: string
    stopWeights: { board: Record<string, number>; alight: Record<string, number> }
    pinnedSharesPct: Record<string, Record<string, number>>
  }
}

export interface DetailsInputs {
  daysPerWeek: number
  tariff: Tariff
  demand: DemandInputs | null
}

export const TARIFF_PARTS = [
  'faresPerPax',
  'faresPerKm',
  'servicesPerPax',
  'cateringPerPax',
] as const

export type TariffPart = (typeof TARIFF_PARTS)[number]

/** The request field each part is posted as. */
export const TARIFF_REQUEST_FIELDS: Record<TariffPart, string> = {
  faresPerKm: 'fares_eur_per_km',
  faresPerPax: 'fares_eur_per_pax',
  servicesPerPax: 'services_eur_per_pax',
  cateringPerPax: 'catering_eur_per_pax',
}

/** Only catering may be negative — a restaurant can be carried by the
 *  tickets it helps sell; nobody is paid to travel or to bring a bike. The
 *  backend validates the same way, so the field should not let you type
 *  something it will reject. */
export function partIsSigned(part: TariffPart): boolean {
  return part === 'cateringPerPax'
}

function sameMap(a: Record<string, number>, b: Record<string, number>): boolean {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)])
  return [...keys].every((k) => a[k] === b[k])
}

export function sameTariff(a: Tariff, b: Tariff): boolean {
  return TARIFF_PARTS.every((part) => sameMap(a[part], b[part]))
}

/** The tariff a resolved request echo describes, with an empty map for any
 *  part the echo predates — an old stored request has no fares_eur_per_pax,
 *  and comparing against {} makes every class read as changed, which is the
 *  truth: those figures were computed without it. */
export function tariffFromRequest(request: Record<string, unknown> | null): Tariff {
  const read = (field: string) => (request?.[field] as Record<string, number>) ?? {}
  return {
    faresPerKm: read('fares_eur_per_km'),
    faresPerPax: read('fares_eur_per_pax'),
    servicesPerPax: read('services_eur_per_pax'),
    cateringPerPax: read('catering_eur_per_pax'),
  }
}

/** The four request fields, ready to spread into a family request. */
export function tariffRequest(tariff: Tariff): Record<string, Record<string, number>> {
  const out: Record<string, Record<string, number>> = {}
  for (const part of TARIFF_PARTS) out[TARIFF_REQUEST_FIELDS[part]] = tariff[part]
  return out
}

/** The demand block a resolved request echo describes; null on an echo
 *  written before DEMAND 0.1.0 (its figures came from the stopgap and no
 *  demand input can be said to match them). */
export function demandFromRequest(request: Record<string, unknown> | null): DemandInputs | null {
  const block = request?.demand as Record<string, unknown> | undefined
  if (!block) return null
  const od = (block.od ?? {}) as Record<string, unknown>
  const weights = (od.stop_weights ?? {}) as Record<string, Record<string, number>>
  return {
    level: String(block.level ?? 'custom'),
    passengersPerYear: Number(block.passengers_per_year ?? 0),
    groupSharesPct: { ...((block.group_shares_pct as Record<string, number>) ?? {}) },
    od: {
      preset: String(od.preset ?? 'custom'),
      stopWeights: { board: { ...(weights.board ?? {}) }, alight: { ...(weights.alight ?? {}) } },
      pinnedSharesPct: Object.fromEntries(
        Object.entries((od.pinned_shares_pct as Record<string, Record<string, number>>) ?? {}).map(
          ([o, row]) => [o, { ...row }],
        ),
      ),
    },
  }
}

/** The request block, ready to spread into a family request. */
export function demandRequest(demand: DemandInputs): { demand: Record<string, unknown> } {
  return {
    demand: {
      level: demand.level,
      passengers_per_year: demand.passengersPerYear,
      group_shares_pct: demand.groupSharesPct,
      od: {
        preset: demand.od.preset,
        stop_weights: demand.od.stopWeights,
        pinned_shares_pct: demand.od.pinnedSharesPct,
      },
    },
  }
}

function samePins(
  a: Record<string, Record<string, number>>,
  b: Record<string, Record<string, number>>,
): boolean {
  const origins = new Set([...Object.keys(a), ...Object.keys(b)])
  return [...origins].every((o) => sameMap(a[o] ?? {}, b[o] ?? {}))
}

/** Same demand as far as the numbers go — the level and the preset are
 *  labels the backend leaves out of the family key, so they are left out
 *  here too: choosing "Medium" over a typed 200 000 changes nothing. */
export function sameDemand(a: DemandInputs | null, b: DemandInputs | null): boolean {
  if (a === null || b === null) return a === b
  return (
    a.passengersPerYear === b.passengersPerYear &&
    sameMap(a.groupSharesPct, b.groupSharesPct) &&
    sameMap(a.od.stopWeights.board, b.od.stopWeights.board) &&
    sameMap(a.od.stopWeights.alight, b.od.stopWeights.alight) &&
    samePins(a.od.pinnedSharesPct, b.od.pinnedSharesPct)
  )
}

/** Which scopes differ from what the figures were computed with. Reverting an
 *  edit clears its scope by itself — this is a comparison, not a latch, the
 *  same rule the composition and scenario selections follow. */
export function dirtyScopes(current: DetailsInputs, committed: DetailsInputs | null): Set<Scope> {
  const dirty = new Set<Scope>()
  if (committed === null) return dirty
  if (current.daysPerWeek !== committed.daysPerWeek) dirty.add('schedule')
  if (!sameTariff(current.tariff, committed.tariff)) dirty.add('prices')
  if (!sameDemand(current.demand, committed.demand)) dirty.add('demand')
  return dirty
}

/** Does a panel declaring `awaits` have to wait? Owning a scope is not the
 *  same as depending on it: the Schedule panel owns "schedule" and previews
 *  it, while every cost panel depends on it and waits. */
export function isAwaiting(awaits: readonly Scope[], dirty: ReadonlySet<Scope>): boolean {
  return awaits.some((scope) => dirty.has(scope))
}

/** What one passenger of a class pays for a journey of this length: the
 *  fixed part of the base fare plus the distance part. The two example
 *  columns beside the fare fields — arithmetic on the fields themselves, so
 *  they preview as they are typed. Services and catering are deliberately
 *  NOT in it: the example is the fare for the berth, not the whole basket. */
export function exampleFare(eurPerPax: number, eurPerKm: number, km: number): number {
  return eurPerPax + eurPerKm * km
}

/** How a signed catering contribution reads in words. The sign carries the
 *  meaning: a restaurant can pay for itself or be carried by the tickets it
 *  helps sell, and the usual night-train case is the second. */
export function cateringSign(value: number): 'positive' | 'negative' | 'neutral' {
  if (value > 0) return 'positive'
  if (value < 0) return 'negative'
  return 'neutral'
}
