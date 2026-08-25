import { describe, it, expect } from 'vitest'
import { formatClock, dayOffset } from './tripClock'

describe('formatClock', () => {
  it('formats a plain time', () => {
    expect(formatClock(1200)).toBe('20:00')
    expect(formatClock(0)).toBe('00:00')
  })

  it('wraps an overnight value onto a real clock face', () => {
    // GTFS overnight convention: 1920 min = 08:00 the next day.
    expect(formatClock(1920)).toBe('08:00')
    expect(formatClock(2880)).toBe('00:00')
  })

  it('wraps a negative value (mirrored return trip)', () => {
    expect(formatClock(-30)).toBe('23:30')
  })

  it('passes null/undefined through', () => {
    expect(formatClock(null)).toBeNull()
    expect(formatClock(undefined)).toBeNull()
  })
})

describe('dayOffset', () => {
  it('is 0 for the departure itself', () => {
    expect(dayOffset(1200, 1200)).toBe(0)
  })

  it('is 0 for a same-day later stop', () => {
    expect(dayOffset(1380, 1200)).toBe(0) // 23:00 after a 20:00 departure
  })

  it('is 1 for an arrival after midnight', () => {
    expect(dayOffset(1920, 1200)).toBe(1) // 08:00 next day after 20:00
    expect(dayOffset(1440, 1200)).toBe(1) // exactly midnight
  })

  it('counts multiple days', () => {
    expect(dayOffset(3000, 1200)).toBe(2)
  })

  it('does not mark every row a day late when the trip starts before midnight', () => {
    // Mirrored return trip: departs 23:30 as -30, arrives 07:00 as 420.
    // floor(420/1440) - floor(-30/1440) = 0 - (-1) = 1 — correct, one day on.
    expect(dayOffset(420, -30)).toBe(1)
    // ...and a stop still on the departure evening stays at 0.
    expect(dayOffset(-10, -30)).toBe(0)
  })

  it('never reports a negative offset for non-monotonic times', () => {
    expect(dayOffset(100, 1920)).toBe(0)
  })

  it('is 0 when either end is missing', () => {
    expect(dayOffset(null, 1200)).toBe(0)
    expect(dayOffset(1920, null)).toBe(0)
  })
})
