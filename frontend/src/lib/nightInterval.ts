// The fixed-night interval: the builder's state for timetable_mode
// "simpleAutomaticWithFixedNight", and the pure functions around it.
//
// Backend contract (models/route/timetable.py, simple_automatic_fixed_night_
// timetable): `fixed_night_interval: [A, B]` names two stops, A before B in
// the posted stop order, and the timetable is positioned so the MIDPOINT of
// [departure at A, arrival at B] lands on 02:30 instead of the midpoint of
// the whole trip. A leaves by 23:59 at the latest, B arrives at 05:00 at
// the earliest; a section naturally shorter than that is stretched with
// slack. The return trip gets the interval reversed, server-side. Null (or
// no interval) is the ordinary automatic timetable — the special case
// A = first, B = last.
//
// Split out of ProposalViewport.vue like lib/expertTimetable.ts: components
// are never mounted in this project's tests, so anything worth testing lives
// in src/lib. Everything here is pure.

/** [start, end] stop ids, in the itinerary's current travel order. */
export type NightInterval = [string, string]

/** The night window on the service-day scale the API uses (0 = midnight of
 *  the departure day): 00:00 and 05:00 of the following morning. The same
 *  NIGHT_START_MIN / NIGHT_END_MIN the backend classifies stops with. */
export const NIGHT_START_MIN = 24 * 60
export const NIGHT_END_MIN = 29 * 60

/** The interval as it applies to the reversed itinerary. */
export function reverseNightInterval(interval: NightInterval): NightInterval {
  return [interval[1], interval[0]]
}

/**
 * The interval, or null once it no longer names a legal night section of
 * `stopIds`: a stop removed, or the two ends reordered so the start comes
 * after the end. The backend rejects either (400), and a night the user
 * placed on stops that are gone is not one they still asked for.
 */
export function pruneNightInterval(
  interval: NightInterval | null,
  stopIds: string[],
): NightInterval | null {
  if (interval === null) return null
  const a = stopIds.indexOf(interval[0])
  const b = stopIds.indexOf(interval[1])
  return a >= 0 && b >= 0 && a < b ? interval : null
}

/** True when the two mean the same night section — in either travel order,
 *  because flipping the itinerary reverses the interval without moving it. */
export function sameNightInterval(a: NightInterval | null, b: NightInterval | null): boolean {
  if (a === null || b === null) return a === b
  return (a[0] === b[0] && a[1] === b[1]) || (a[0] === b[1] && a[1] === b[0])
}

/** The selection in progress: an interval, and possibly one end already
 *  picked while the other is still to come. */
export interface NightSelection {
  interval: NightInterval | null
  pending: string | null
}

/**
 * One click on a stop's night marker. Two clicks make an interval — the
 * earlier stop of the two is its start, whichever was clicked first — so the
 * user never has to know which end they are placing. Clicking the pending
 * stop again cancels; clicking either end of an existing interval clears it
 * (back to the automatic night); clicking any other stop starts a new one.
 */
export function toggleNightStop(
  selection: NightSelection,
  stopId: string,
  stopIds: string[],
): NightSelection {
  const { interval, pending } = selection
  if (pending !== null) {
    if (pending === stopId) return { interval, pending: null }
    const a = stopIds.indexOf(pending)
    const b = stopIds.indexOf(stopId)
    if (a < 0 || b < 0) return { interval, pending: null }
    return { interval: a < b ? [pending, stopId] : [stopId, pending], pending: null }
  }
  if (interval !== null && (interval[0] === stopId || interval[1] === stopId)) {
    return { interval: null, pending: null }
  }
  return { interval, pending: stopId }
}

/** Whether a stop lies on the night section, ends included. */
export function inNightInterval(
  interval: NightInterval | null,
  stopId: string,
  stopIds: string[],
): boolean {
  if (interval === null) return false
  const i = stopIds.indexOf(stopId)
  const a = stopIds.indexOf(interval[0])
  const b = stopIds.indexOf(interval[1])
  return i >= 0 && a >= 0 && b >= 0 && a <= i && i <= b
}

/**
 * Whether a leg runs through the night window, judged on the clock the
 * backend classified the stops with: it does unless it is over before 00:00
 * or starts at or after 05:00. This is what colours the timeline between
 * two rows — and, on a two-stop route, is the only way to show the night at
 * all (its stops are boarding and alighting by position, not by time).
 */
export function legIsNight(
  departureMin: number | null | undefined,
  arrivalMin: number | null | undefined,
): boolean {
  if (departureMin == null || arrivalMin == null) return false
  return arrivalMin > NIGHT_START_MIN && departureMin < NIGHT_END_MIN
}
