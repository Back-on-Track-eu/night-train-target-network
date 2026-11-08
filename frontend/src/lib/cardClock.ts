/**
 * The clock times a gallery card heads its route with. The summary carries
 * them as "HH:MM" with hours NOT wrapped at 24 (the GTFS overnight
 * convention: "30:43" is 06:43 the next day), so a card shows the time on a
 * 24-hour clock plus how many days after the departure day it falls.
 */

const DAY_MIN = 24 * 60

export interface CardClock {
  /** "06:43" — always on a 24-hour clock. */
  time: string
  /** Days after the departure's day: 0 the same day, 1 the next. */
  dayOffset: number
}

/** Minutes after the service day's midnight, or null if unreadable. */
export function clockMinutes(hhmm: string | null | undefined): number | null {
  const match = /^(\d+):(\d{2})$/.exec(hhmm ?? '')
  return match ? Number(match[1]) * 60 + Number(match[2]) : null
}

function at(minutes: number, dayOffset: number): CardClock {
  const inDay = ((minutes % DAY_MIN) + DAY_MIN) % DAY_MIN
  const hh = String(Math.floor(inDay / 60)).padStart(2, '0')
  const mm = String(inDay % 60).padStart(2, '0')
  return { time: `${hh}:${mm}`, dayOffset }
}

/** Departure and arrival as the card shows them; either is null when the
 *  summary has no time for it. The arrival's day counts from the
 *  departure's, so a train leaving at 25:10 and arriving at 31:00 is a
 *  same-day 01:10 → 07:00. Not every timetable keeps the convention (some
 *  ONTD rows wrap at 24:00), so an arrival before the departure is read as
 *  the next day. */
export function endpointClocks(
  departure: string | null | undefined,
  arrival: string | null | undefined,
): { departure: CardClock | null; arrival: CardClock | null } {
  const dep = clockMinutes(departure)
  const arr = clockMinutes(arrival)
  const depDay = dep === null ? 0 : Math.floor(dep / DAY_MIN)
  let arrAbs = arr
  while (arrAbs !== null && dep !== null && arrAbs < dep) arrAbs += DAY_MIN
  return {
    departure: dep === null ? null : at(dep, 0),
    arrival: arrAbs === null ? null : at(arrAbs, Math.floor(arrAbs / DAY_MIN) - depDay),
  }
}
