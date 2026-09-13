// The arithmetic and the dirty-tracking behind zone D's "Details" card, kept
// out of the SFCs so it can be tested without mounting anything (vitest runs
// in node, no jsdom — see AGENTS.md).
//
// Two inputs change the calculation, both on the Supply tab: the SCHEDULE and
// the PRICES (fares and the catering contribution). Each is a scope. A panel
// either OWNS a scope — it recomputes here, on the page, and says so — or
// DEPENDS on one, in which case it keeps the figures it has, greys out, and
// waits for the backend. Nothing ever shows a number that mixes a previewed
// input with a calculated one.

/** Days in each month of the evaluation year. 2032 is a leap year, so the
 *  year has 366 days — the same calendar the backend counts operating days
 *  on (models/route/model.py EVALUATION_YEAR). */
const DAYS_IN_MONTH = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31] as const

export const MONTH_KEYS = [
  'jan',
  'feb',
  'mar',
  'apr',
  'may',
  'jun',
  'jul',
  'aug',
  'sep',
  'oct',
  'nov',
  'dec',
] as const

export type SchedulePreset = 'daily' | 'three' | 'once' | 'summer' | 'custom'

/** The preset grids, in the order the pills are shown. "custom" is not here:
 *  it is what a grid matching none of these is called. */
export const SCHEDULE_PRESETS: Record<Exclude<SchedulePreset, 'custom'>, number[]> = {
  daily: Array(12).fill(7),
  three: Array(12).fill(3),
  once: Array(12).fill(1),
  // May to September inclusive.
  summer: [0, 0, 0, 0, 7, 7, 7, 7, 7, 0, 0, 0],
}

export const DAILY_SCHEDULE: number[] = SCHEDULE_PRESETS.daily

export function sameSchedule(a: number[], b: number[]): boolean {
  return a.length === b.length && a.every((d, i) => d === b[i])
}

/** Which preset a grid is, or "custom". The pill lights by itself. */
export function presetOf(months: number[]): SchedulePreset {
  for (const [name, grid] of Object.entries(SCHEDULE_PRESETS)) {
    if (sameSchedule(months, grid)) return name as SchedulePreset
  }
  return 'custom'
}

/** The request pair for a grid: a flat seven is the backend's own default
 *  mode and sends no month map at all, so an untouched proposal keeps
 *  hashing to the same family as one that never knew about the grid. */
export function scheduleRequest(months: number[]): {
  schedule_mode: string
  schedule: Record<string, number> | null
} {
  if (sameSchedule(months, DAILY_SCHEDULE)) {
    return { schedule_mode: 'alwaysDaily', schedule: null }
  }
  const schedule: Record<string, number> = {}
  months.forEach((days, i) => (schedule[String(i + 1)] = days))
  return { schedule_mode: 'custom', schedule }
}

/** The grid a resolved request echo describes — what the figures on screen
 *  were computed with. An echo without a month map is the daily default. */
export function scheduleFromRequest(schedule: Record<string, number> | null | undefined): number[] {
  if (!schedule) return [...DAILY_SCHEDULE]
  return MONTH_KEYS.map((_, i) => Number(schedule[String(i + 1)] ?? 0))
}

export function operatingDaysPerYear(months: number[]): number {
  return months.reduce((sum, days, i) => sum + (DAYS_IN_MONTH[i] * days) / 7, 0)
}

/** Index (0-based) of the month the fleet is sized to, or null when the grid
 *  is flat — in which case naming a "busiest" month would be arbitrary. */
export function peakMonth(months: number[]): number | null {
  const max = Math.max(...months)
  if (max === Math.min(...months)) return null
  return months.indexOf(max)
}

/** Physical rakes: the cycle length in days times the busiest month's
 *  days-per-week, rounded up (ROUTE_BUILDER 0.9.35). Exact on the page —
 *  the cycle itself is a constant of the timetable, which only the backend
 *  can redo, so it is taken from the last result. */
export function trainsetsFor(months: number[], cycleDays: number | null): number | null {
  if (cycleDays === null || cycleDays <= 0) return null
  if (Math.max(...months) === 0) return 0
  return Math.max(...months.map((days) => Math.ceil((cycleDays * days) / 7)))
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
 * The four schedule-owned figures plus the two place figures, from the grid.
 *
 * cycleDistanceKm is the route's own total over BOTH directions (the
 * summary's total_distance_km), so one operating day is one cycle: the
 * backend's train_km_per_year is cycle km × operating days and its
 * departures_per_year is operating days × 2 per pair.
 */
export function supplyFigures(
  months: number[],
  cycleDistanceKm: number,
  places: number,
  cycleDays: number | null,
  tripPairs = 1,
): SupplyFigures {
  const operatingDays = operatingDaysPerYear(months)
  const departures = operatingDays * 2 * tripPairs
  const trainKm = operatingDays * cycleDistanceKm
  return {
    operatingDays,
    departures,
    trainKm,
    placesOffered: departures * places,
    placeKmOffered: places * trainKm,
    trainsets: trainsetsFor(months, cycleDays),
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

export type Scope = 'schedule' | 'prices'

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

export interface DetailsInputs {
  months: number[]
  tariff: Tariff
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

/** Which scopes differ from what the figures were computed with. Reverting an
 *  edit clears its scope by itself — this is a comparison, not a latch, the
 *  same rule the composition and scenario selections follow. */
export function dirtyScopes(current: DetailsInputs, committed: DetailsInputs | null): Set<Scope> {
  const dirty = new Set<Scope>()
  if (committed === null) return dirty
  if (!sameSchedule(current.months, committed.months)) dirty.add('schedule')
  if (!sameTariff(current.tariff, committed.tariff)) dirty.add('prices')
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
