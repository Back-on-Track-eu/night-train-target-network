import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  appendBounded,
  correctionFactor,
  expectFamilyWait,
  legKeys,
  modelMs,
  recordFamilyWait,
  RATIO_MAX,
  RATIO_WINDOW,
  SLOW_FLOOR_MS,
  slowThresholds,
} from './calcExpectation'

function memoryStorage(): Storage {
  const data = new Map<string, string>()
  return {
    get length() {
      return data.size
    },
    clear: () => data.clear(),
    getItem: (k) => data.get(k) ?? null,
    key: (i) => [...data.keys()][i] ?? null,
    removeItem: (k) => void data.delete(k),
    setItem: (k, v) => void data.set(k, String(v)),
  }
}

beforeEach(() => vi.stubGlobal('localStorage', memoryStorage()))
afterEach(() => vi.unstubAllGlobals())

describe('modelMs', () => {
  // The bench's own measurements (2026-09-21), wall time over HTTP. The
  // model is a fit with rounded coefficients, so these hold to its worst
  // residual — 0.8 s, on the single-leg route.
  it.each([
    ['wien-paris-2 cold', 96, 1, false, 4_980],
    ['paris-berlin-4 cold', 96, 3, false, 5_120],
    ['wien-paris-11 cold', 96, 10, false, 10_550],
    ['wien-paris-11 narrow', 2, 10, false, 2_260],
  ])('%s', (_label, members, legs, newRoute, measured) => {
    expect(Math.abs(modelMs(members, legs, newRoute) - measured)).toBeLessThan(800)
  })

  it('adds the routing allowance only for a new route', () => {
    expect(modelMs(96, 3, true) - modelMs(96, 3, false)).toBe(5_000)
  })
})

describe('legKeys', () => {
  it('is direction-free, like the segment cache', () => {
    expect(legKeys(['b', 'a', 'c'])).toEqual(['a|b', 'a|c'])
    expect(legKeys(['c', 'a', 'b'])).toEqual(legKeys(['b', 'a', 'c']).reverse())
  })
})

describe('correctionFactor', () => {
  it('is 1 before anything was measured', () => {
    expect(correctionFactor([])).toBe(1)
  })
  it('takes the median, so one freak build does not move it', () => {
    expect(correctionFactor([1, 1.1, 9])).toBe(1.1)
    expect(correctionFactor([1, 2])).toBe(1.5)
  })
  it('is clamped', () => {
    expect(correctionFactor([50, 60])).toBe(RATIO_MAX)
    expect(correctionFactor([0.01])).toBe(0.5)
  })
})

describe('slowThresholds', () => {
  it('never escalates before the floor', () => {
    expect(slowThresholds(2_000)).toEqual({ slowMs: SLOW_FLOOR_MS, verySlowMs: 25_000 })
  })
  it('scales with the expected time beyond it', () => {
    expect(slowThresholds(12_000)).toEqual({ slowMs: 18_000, verySlowMs: 36_000 })
  })
})

describe('appendBounded', () => {
  it('moves repeats to the end and keeps the newest', () => {
    expect(appendBounded(['a', 'b', 'c'], ['a', 'd'], 3)).toEqual(['c', 'a', 'd'])
  })
})

describe('expectFamilyWait / recordFamilyWait', () => {
  const stops = ['s1', 's2', 's3', 's4']

  it('counts a route as new until its legs have come back once', () => {
    expect(expectFamilyWait({ stopIds: stops, members: 96, suggest: false }).newRoute).toBe(true)
    recordFamilyWait({
      stopIds: stops,
      members: 96,
      newRoute: true,
      wallMs: 10_000,
      cacheHit: false,
    })
    expect(expectFamilyWait({ stopIds: stops, members: 96, suggest: false }).newRoute).toBe(false)
    // Reversed is the same legs.
    const back = [...stops].reverse()
    expect(expectFamilyWait({ stopIds: back, members: 96, suggest: false }).newRoute).toBe(false)
  })

  it('always allows for routing in suggest mode', () => {
    recordFamilyWait({
      stopIds: stops,
      members: 96,
      newRoute: true,
      wallMs: 10_000,
      cacheHit: true,
    })
    expect(expectFamilyWait({ stopIds: stops, members: 96, suggest: true }).newRoute).toBe(true)
  })

  it('learns a slower server and scales the thresholds with it', () => {
    const before = expectFamilyWait({ stopIds: stops, members: 96, suggest: false })
    for (let i = 0; i < 3; i++) {
      recordFamilyWait({
        stopIds: stops,
        members: 96,
        newRoute: false,
        wallMs: 2 * modelMs(96, 3, false),
        cacheHit: false,
      })
    }
    const after = expectFamilyWait({ stopIds: stops, members: 96, suggest: false })
    expect(after.expectedMs).toBeCloseTo(2 * modelMs(96, 3, false))
    expect(after.thresholds.slowMs).toBeGreaterThan(before.thresholds.slowMs)
  })

  it('does not learn from a document-cache hit', () => {
    recordFamilyWait({ stopIds: stops, members: 96, newRoute: false, wallMs: 300, cacheHit: true })
    recordFamilyWait({ stopIds: stops, members: 96, newRoute: false, wallMs: 300, cacheHit: true })
    const e = expectFamilyWait({ stopIds: stops, members: 96, suggest: false })
    expect(e.expectedMs).toBe(modelMs(96, 3, false))
  })

  it('keeps only the last few ratios', () => {
    for (let i = 0; i < RATIO_WINDOW; i++) {
      recordFamilyWait({
        stopIds: stops,
        members: 2,
        newRoute: false,
        wallMs: 1e9,
        cacheHit: false,
      })
    }
    for (let i = 0; i < RATIO_WINDOW; i++) {
      recordFamilyWait({
        stopIds: stops,
        members: 2,
        newRoute: false,
        wallMs: modelMs(2, 3, false),
        cacheHit: false,
      })
    }
    expect(expectFamilyWait({ stopIds: stops, members: 2, suggest: false }).expectedMs).toBe(
      modelMs(2, 3, false),
    )
  })

  it('works without storage at all', () => {
    vi.stubGlobal('localStorage', undefined)
    recordFamilyWait({
      stopIds: stops,
      members: 96,
      newRoute: true,
      wallMs: 5_000,
      cacheHit: false,
    })
    const e = expectFamilyWait({ stopIds: stops, members: 96, suggest: false })
    expect(e.newRoute).toBe(true)
    expect(e.expectedMs).toBe(modelMs(96, 3, true))
  })
})
