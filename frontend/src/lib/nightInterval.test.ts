import { describe, it, expect } from 'vitest'
import {
  NIGHT_END_MIN,
  NIGHT_START_MIN,
  inNightInterval,
  legIsNight,
  pruneNightInterval,
  reverseNightInterval,
  sameNightInterval,
  toggleNightStop,
  type NightInterval,
} from './nightInterval'

const A = 'osm:a'
const B = 'osm:b'
const C = 'osm:c'
const D = 'osm:d'
const STOPS = [A, B, C, D]

describe('pruneNightInterval', () => {
  it('keeps a legal interval and drops one whose stop is gone', () => {
    expect(pruneNightInterval([B, C], STOPS)).toEqual([B, C])
    expect(pruneNightInterval([B, C], [A, B, D])).toBeNull()
  })

  it('drops an interval whose ends were reordered past each other', () => {
    expect(pruneNightInterval([C, B], STOPS)).toBeNull()
    expect(pruneNightInterval(null, STOPS)).toBeNull()
  })
})

describe('reverse / same', () => {
  it('is the same night in either travel order', () => {
    const interval: NightInterval = [B, C]
    expect(reverseNightInterval(interval)).toEqual([C, B])
    expect(sameNightInterval(interval, reverseNightInterval(interval))).toBe(true)
    expect(sameNightInterval(interval, [A, C])).toBe(false)
    expect(sameNightInterval(null, null)).toBe(true)
    expect(sameNightInterval(interval, null)).toBe(false)
  })
})

describe('toggleNightStop', () => {
  const none = { interval: null, pending: null }

  it('takes two clicks, in either order, and puts the earlier stop first', () => {
    const first = toggleNightStop(none, C, STOPS)
    expect(first).toEqual({ interval: null, pending: C })
    expect(toggleNightStop(first, B, STOPS)).toEqual({ interval: [B, C], pending: null })
    expect(toggleNightStop(toggleNightStop(none, B, STOPS), C, STOPS)).toEqual({
      interval: [B, C],
      pending: null,
    })
  })

  it('cancels on the pending stop and clears on either end of an interval', () => {
    expect(toggleNightStop({ interval: null, pending: B }, B, STOPS)).toEqual(none)
    const set = { interval: [B, C] as NightInterval, pending: null }
    expect(toggleNightStop(set, B, STOPS)).toEqual(none)
    expect(toggleNightStop(set, C, STOPS)).toEqual(none)
  })

  it('starts a new interval from any other stop while one exists', () => {
    const set = { interval: [B, C] as NightInterval, pending: null }
    expect(toggleNightStop(set, A, STOPS)).toEqual({ interval: [B, C], pending: A })
  })
})

describe('inNightInterval', () => {
  it('includes both ends and nothing outside', () => {
    expect(inNightInterval([B, C], B, STOPS)).toBe(true)
    expect(inNightInterval([B, C], C, STOPS)).toBe(true)
    expect(inNightInterval([B, C], A, STOPS)).toBe(false)
    expect(inNightInterval(null, B, STOPS)).toBe(false)
  })
})

describe('legIsNight', () => {
  it('is true for any leg overlapping 00:00–05:00, false outside', () => {
    expect(legIsNight(20 * 60, 8 * 60 + 1440)).toBe(true) // 20:00 → 08:00+1
    expect(legIsNight(NIGHT_START_MIN - 60, NIGHT_START_MIN + 1)).toBe(true) // ends just past midnight
    expect(legIsNight(18 * 60, 23 * 60)).toBe(false) // evening only
    expect(legIsNight(NIGHT_END_MIN, NIGHT_END_MIN + 120)).toBe(false) // starts at 05:00
    expect(legIsNight(null, 100)).toBe(false)
  })
})
