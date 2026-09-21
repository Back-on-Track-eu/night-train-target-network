// The stepped 1–7 bar's arithmetic, out of the SFC so it can be tested
// without mounting anything: where a pointer lands, what an arrow key does,
// where a tick sits.

import { clampDaysPerWeek, MAX_DAYS_PER_WEEK, MIN_DAYS_PER_WEEK } from '@/lib/detailsScope'

export const FREQUENCY_TICKS = Array.from(
  { length: MAX_DAYS_PER_WEEK - MIN_DAYS_PER_WEEK + 1 },
  (_, i) => MIN_DAYS_PER_WEEK + i,
)

/** Position of a value along the track, 0 … 1. */
export function frequencyPosition(daysPerWeek: number): number {
  return (daysPerWeek - MIN_DAYS_PER_WEEK) / (MAX_DAYS_PER_WEEK - MIN_DAYS_PER_WEEK)
}

/** The step a pointer at x (0 … width) lands on — the nearest tick. */
export function frequencyFromPointer(x: number, width: number): number {
  if (width <= 0) return MIN_DAYS_PER_WEEK
  return clampDaysPerWeek(MIN_DAYS_PER_WEEK + (x / width) * (MAX_DAYS_PER_WEEK - MIN_DAYS_PER_WEEK))
}

/** Arrow keys step by one; Home/End jump; anything else is left alone. */
export function frequencyFromKey(key: string, current: number): number | null {
  switch (key) {
    case 'ArrowRight':
    case 'ArrowUp':
      return clampDaysPerWeek(current + 1)
    case 'ArrowLeft':
    case 'ArrowDown':
      return clampDaysPerWeek(current - 1)
    case 'Home':
      return MIN_DAYS_PER_WEEK
    case 'End':
      return MAX_DAYS_PER_WEEK
    default:
      return null
  }
}

/** Which qualifier the value label carries: every day, once a week, or none. */
export function frequencyQualifier(daysPerWeek: number): 'everyDay' | 'onceAWeek' | null {
  if (daysPerWeek >= MAX_DAYS_PER_WEEK) return 'everyDay'
  if (daysPerWeek <= MIN_DAYS_PER_WEEK) return 'onceAWeek'
  return null
}
