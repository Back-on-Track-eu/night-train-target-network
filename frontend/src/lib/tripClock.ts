// Clock formatting for timetable rows. The API sends minutes from the SERVICE
// day's midnight, GTFS-style, so an overnight leg legitimately exceeds 1439:
// backend models/utils.py::min_to_hhmm renders 1920 as "08:00 (+1d)". The
// mirror-around-02:30 return timetable can also push a value below 0.
//
// Extracted from ProposalViewport.vue so this arithmetic is unit-testable
// without mounting the component (see the frontend test note in AGENTS.md).

const MINUTES_PER_DAY = 1440

/** Minutes-from-service-midnight -> "HH:MM", wrapping any value onto a real
 *  clock face so an overnight 1920 shows "08:00" rather than "32:00". */
export function formatClock(min: number | null | undefined): string | null {
  if (min === null || min === undefined) return null
  const wrapped = ((min % MINUTES_PER_DAY) + MINUTES_PER_DAY) % MINUTES_PER_DAY
  const h = Math.floor(wrapped / 60)
  const m = wrapped % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}

/**
 * How many calendar days after the trip's FIRST departure a given time falls —
 * the "+1" a night train's arrival needs, since "20:00 → 08:00" otherwise reads
 * as a twelve-hour journey backwards through the day.
 *
 * Measured as a difference of day indices rather than `floor(min / 1440)` on its
 * own: that absolute form is right for a trip departing before midnight, but the
 * mirrored return trip can carry a negative first departure (23:30 as -30),
 * where the absolute form would mark every subsequent row a day late.
 *
 * Never returns a negative: a non-monotonic pair of times means we cannot tell,
 * and silently showing no marker is the safe direction to be wrong in — a
 * spurious "+1" is a claim about the timetable, a missing one is just quiet.
 */
export function dayOffset(
  min: number | null | undefined,
  baseMin: number | null | undefined,
): number {
  if (min === null || min === undefined || baseMin === null || baseMin === undefined) return 0
  const days = Math.floor(min / MINUTES_PER_DAY) - Math.floor(baseMin / MINUTES_PER_DAY)
  return Math.max(days, 0)
}
