/**
 * calcExpectation.ts
 * ==================
 * How long a proposal-family build should take, so the builder only says
 * "taking longer than usual" when it is.
 *
 * THE MODEL. A family evaluates every member over every leg, so its cost is
 * members × legs on top of a fixed part, plus live routing when the route has
 * legs the server has never routed (after that they sit in the shared
 * route-segment cache for good):
 *
 *   expected = base + perMember·m + perMemberLeg·m·legs  (+ newRoute)
 *
 * The coefficients are a least-squares fit of wall time over HTTP on the dev
 * stack (backend/scripts/bench_family_wait.py, 2026-09-21: 2- to 11-stop
 * routes, 2 and 96 members; worst residual 0.8 s). Refit with that script
 * after any performance change to the family build — it prints them in
 * these units.
 *
 * THE CORRECTION. The dev stack is not production. After every build that
 * was not a document-cache hit, actual ÷ predicted is stored; the median of
 * the last few scales the next prediction. A hit is skipped: it is not the
 * work the model describes, and its stats.elapsed_s is the original build's.
 *
 * NEW LEGS. Whether the server has a leg cached is unknowable from here, so
 * this browser remembers the legs of every family it has received. A leg
 * someone else routed first is then counted as new — the prediction runs
 * long and the message comes later, which is the safe direction.
 *
 * Everything persisted goes through localStorage and fails soft: no storage
 * (private mode, quota) just means the uncorrected model and every route
 * counted as new.
 */

import type { SlowThresholds } from './apiClient'

/** Fitted on the dev stack — see the header. Milliseconds. */
export const FAMILY_WAIT_MODEL = {
  baseMs: 2_100,
  perMemberMs: 15,
  perMemberLegMs: 6.8,
  /** Live routing of legs never routed before — roughly flat in leg count,
   *  because routing fans out over graphs in threads. The median of the
   *  bench's first-minus-cold premiums (3.2–6.2 s), leaving out the run's
   *  very first request, which also paid process warm-up (+12.6 s). */
  newRouteMs: 5_000,
} as const

/** The backend's default axes on the calibration stack — the member count
 *  assumed when a request leaves an axis to the backend and no document has
 *  told us its size yet. */
export const DEFAULT_FAMILY_MEMBERS = 96

/** "Longer than usual": half again the expected time, never before 10 s. */
export const SLOW_FACTOR = 1.5
export const SLOW_FLOOR_MS = 10_000
/** "Much longer, servers may be busy": three times, at least 15 s later. */
export const VERY_SLOW_FACTOR = 3
export const VERY_SLOW_GAP_MS = 15_000

/** How many recent actual ÷ predicted ratios the correction takes a median of. */
export const RATIO_WINDOW = 8
/** The correction is a calibration, not a license: a stuck tab or one freak
 *  build must not teach the builder that 2 minutes is normal. */
export const RATIO_MIN = 0.5
export const RATIO_MAX = 4
/** Legs remembered per browser, oldest dropped first. */
export const KNOWN_LEGS_CAP = 2_000

const RATIOS_KEY = 'calc.familyWaitRatios'
const LEGS_KEY = 'calc.knownLegs'

/** One key per consecutive stop pair, direction-free: the segment cache
 *  stores a pair once and serves both directions from it. */
export function legKeys(stopIds: string[]): string[] {
  return stopIds.slice(0, -1).map((id, i) => {
    const next = stopIds[i + 1]!
    return id < next ? `${id}|${next}` : `${next}|${id}`
  })
}

export function modelMs(members: number, legs: number, newRoute: boolean): number {
  const m = FAMILY_WAIT_MODEL
  return (
    m.baseMs +
    m.perMemberMs * members +
    m.perMemberLegMs * members * legs +
    (newRoute ? m.newRouteMs : 0)
  )
}

/** Median of the recorded ratios, clamped; 1 before there are any. */
export function correctionFactor(ratios: number[]): number {
  if (ratios.length === 0) return 1
  const sorted = [...ratios].sort((a, b) => a - b)
  const mid = sorted.length >> 1
  const median = sorted.length % 2 ? sorted[mid]! : (sorted[mid - 1]! + sorted[mid]!) / 2
  return Math.min(RATIO_MAX, Math.max(RATIO_MIN, median))
}

export function slowThresholds(expectedMs: number): SlowThresholds {
  const slowMs = Math.max(SLOW_FLOOR_MS, SLOW_FACTOR * expectedMs)
  return {
    slowMs: Math.round(slowMs),
    verySlowMs: Math.round(Math.max(slowMs + VERY_SLOW_GAP_MS, VERY_SLOW_FACTOR * expectedMs)),
  }
}

/** The newest `cap` entries of `list` followed by `items`, without repeats. */
export function appendBounded<T>(list: T[], items: T[], cap: number): T[] {
  const fresh = new Set(items)
  return [...list.filter((x) => !fresh.has(x)), ...items].slice(-cap)
}

function readList<T>(key: string): T[] {
  try {
    const raw = typeof localStorage === 'undefined' ? null : localStorage.getItem(key)
    const parsed: unknown = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? (parsed as T[]) : []
  } catch {
    return []
  }
}

function writeList<T>(key: string, list: T[]): void {
  try {
    if (typeof localStorage !== 'undefined') localStorage.setItem(key, JSON.stringify(list))
  } catch {
    // Quota or private mode: the model simply stays uncorrected.
  }
}

export interface FamilyWaitInput {
  stopIds: string[]
  members: number
  /** Suggest mode searches candidate stops as well — routing we cannot
   *  foresee, so it always carries the new-route allowance. */
  suggest: boolean
}

export interface FamilyWaitExpectation {
  expectedMs: number
  /** What was assumed about routing — record() needs the same assumption to
   *  judge the prediction it made. */
  newRoute: boolean
  thresholds: SlowThresholds
}

export function expectFamilyWait(input: FamilyWaitInput): FamilyWaitExpectation {
  const known = new Set(readList<string>(LEGS_KEY))
  const newRoute = input.suggest || legKeys(input.stopIds).some((k) => !known.has(k))
  const legs = Math.max(1, input.stopIds.length - 1)
  const expectedMs =
    modelMs(input.members, legs, newRoute) * correctionFactor(readList<number>(RATIOS_KEY))
  return { expectedMs, newRoute, thresholds: slowThresholds(expectedMs) }
}

export interface FamilyWaitOutcome {
  stopIds: string[]
  /** stats.n_members of the answer — exact, where the prediction had to guess. */
  members: number
  newRoute: boolean
  wallMs: number
  cacheHit: boolean
}

/** Learn from a finished build: its legs are now routed, and unless it was a
 *  document hit its wall time corrects the model. */
export function recordFamilyWait(outcome: FamilyWaitOutcome): void {
  writeList(
    LEGS_KEY,
    appendBounded(readList<string>(LEGS_KEY), legKeys(outcome.stopIds), KNOWN_LEGS_CAP),
  )
  if (outcome.cacheHit) return
  const legs = Math.max(1, outcome.stopIds.length - 1)
  const ratio = outcome.wallMs / modelMs(outcome.members, legs, outcome.newRoute)
  if (!Number.isFinite(ratio) || ratio <= 0) return
  writeList(RATIOS_KEY, [...readList<number>(RATIOS_KEY), ratio].slice(-RATIO_WINDOW))
}
