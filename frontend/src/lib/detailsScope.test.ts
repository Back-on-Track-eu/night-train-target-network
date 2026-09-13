import { describe, it, expect } from 'vitest'
import {
  DAILY_SCHEDULE,
  SCHEDULE_PRESETS,
  cateringSign,
  dirtyScopes,
  exampleFare,
  isAwaiting,
  operatingDaysPerYear,
  peakMonth,
  presetOf,
  scheduleFromRequest,
  scheduleRequest,
  supplyFigures,
  trainsetsFor,
} from './detailsScope'

const tariff = (over: Partial<Parameters<typeof dirtyScopes>[0]['tariff']> = {}) => ({
  faresPerKm: { Seat: 0.1, Couchette: 0.13, Sleeper: 0.18, Capsule: 0.12 },
  faresPerPax: { Seat: 8, Couchette: 12, Sleeper: 18, Capsule: 12 },
  servicesPerPax: { Seat: 1.5, Couchette: 2, Sleeper: 3, Capsule: 2 },
  cateringPerPax: { Seat: 1.2, Couchette: 1.2, Sleeper: 0.6, Capsule: 1.2 },
  ...over,
})

const inputs = (over: Partial<Parameters<typeof dirtyScopes>[0]> = {}) => ({
  months: [...DAILY_SCHEDULE],
  tariff: tariff(),
  ...over,
})

describe('the schedule grid', () => {
  it('counts a daily year as the backend does — 2032 is a leap year', () => {
    expect(operatingDaysPerYear(DAILY_SCHEDULE)).toBe(366)
  })

  it('counts only the months a seasonal service runs', () => {
    // May–September: 31 + 30 + 31 + 31 + 30.
    expect(operatingDaysPerYear(SCHEDULE_PRESETS.summer)).toBeCloseTo(153, 6)
  })

  it('names the preset a grid matches, and calls anything else custom', () => {
    expect(presetOf(DAILY_SCHEDULE)).toBe('daily')
    expect(presetOf(SCHEDULE_PRESETS.three)).toBe('three')
    expect(presetOf(SCHEDULE_PRESETS.summer)).toBe('summer')
    expect(presetOf([7, 7, 5, 5, 7, 7, 7, 7, 7, 5, 5, 7])).toBe('custom')
  })

  it('sends no month map for a flat seven', () => {
    // An untouched proposal has to hash to the family it always did.
    expect(scheduleRequest(DAILY_SCHEDULE)).toEqual({
      schedule_mode: 'alwaysDaily',
      schedule: null,
    })
  })

  it('sends all twelve months for anything else', () => {
    const { schedule_mode, schedule } = scheduleRequest(SCHEDULE_PRESETS.once)
    expect(schedule_mode).toBe('custom')
    expect(Object.keys(schedule ?? {})).toHaveLength(12)
    expect(schedule?.['1']).toBe(1)
    expect(schedule?.['12']).toBe(1)
  })

  it('round-trips through the request echo', () => {
    const months = [7, 7, 5, 5, 7, 7, 7, 7, 7, 5, 5, 7]
    expect(scheduleFromRequest(scheduleRequest(months).schedule)).toEqual(months)
  })

  it('reads an absent echo as the daily default', () => {
    expect(scheduleFromRequest(null)).toEqual(DAILY_SCHEDULE)
    expect(scheduleFromRequest(undefined)).toEqual(DAILY_SCHEDULE)
  })

  it('names the busiest month only when there is one', () => {
    expect(peakMonth(DAILY_SCHEDULE)).toBeNull()
    expect(peakMonth([1, 1, 1, 1, 7, 1, 1, 1, 1, 1, 1, 1])).toBe(4)
  })
})

describe('the fleet', () => {
  it('sizes to the busiest month', () => {
    expect(trainsetsFor(DAILY_SCHEDULE, 2)).toBe(2)
    expect(trainsetsFor(SCHEDULE_PRESETS.three, 2)).toBe(1)
    expect(trainsetsFor([3, 3, 3, 3, 7, 7, 7, 3, 3, 3, 3, 3], 2)).toBe(2)
  })

  it('needs no rake for a train that never runs', () => {
    expect(trainsetsFor(Array(12).fill(0), 2)).toBe(0)
  })

  it('declines to guess without a cycle from the last result', () => {
    // The cycle is a property of the timetable; only the backend can redo it.
    expect(trainsetsFor(DAILY_SCHEDULE, null)).toBeNull()
  })
})

describe('the supply figures a schedule change previews', () => {
  const figures = supplyFigures(DAILY_SCHEDULE, 2160, 260, 2)

  it('derives departures, train-km and place-km from the grid', () => {
    expect(figures.operatingDays).toBe(366)
    expect(figures.departures).toBe(732)
    expect(figures.trainKm).toBe(366 * 2160)
    expect(figures.placesOffered).toBe(732 * 260)
    expect(figures.placeKmOffered).toBe(260 * 366 * 2160)
  })

  it('scales linearly with the operating days', () => {
    const half = supplyFigures(Array(12).fill(3.5), 2160, 260, 2)
    expect(half.trainKm).toBeCloseTo(figures.trainKm / 2, 6)
  })
})

describe('the change-scope rule', () => {
  it('is quiet when nothing has been touched', () => {
    expect(dirtyScopes(inputs(), inputs())).toEqual(new Set())
  })

  it('is quiet before anything has been computed', () => {
    expect(dirtyScopes(inputs(), null)).toEqual(new Set())
  })

  it('marks the schedule alone when the grid moves', () => {
    const dirty = dirtyScopes(inputs({ months: SCHEDULE_PRESETS.three }), inputs())
    expect([...dirty]).toEqual(['schedule'])
  })

  it('marks prices for any of the four tariff parts', () => {
    const changes = [
      tariff({ faresPerKm: { ...tariff().faresPerKm, Sleeper: 0.25 } }),
      tariff({ faresPerPax: { ...tariff().faresPerPax, Sleeper: 25 } }),
      tariff({ servicesPerPax: { ...tariff().servicesPerPax, Seat: 4.5 } }),
      tariff({ cateringPerPax: { ...tariff().cateringPerPax, Sleeper: -0.8 } }),
    ]
    for (const changed of changes) {
      expect([...dirtyScopes(inputs({ tariff: changed }), inputs())]).toEqual(['prices'])
    }
  })

  it('clears itself when the edit is reverted', () => {
    const committed = inputs()
    const edited = inputs({ months: SCHEDULE_PRESETS.once })
    expect(dirtyScopes(edited, committed).size).toBe(1)
    expect(dirtyScopes(inputs(), committed).size).toBe(0)
  })

  it('makes a panel wait only for the scopes it depends on', () => {
    const priceOnly = new Set<'schedule' | 'prices'>(['prices'])
    // Cost does not depend on what a ticket sells for.
    expect(isAwaiting(['schedule'], priceOnly)).toBe(false)
    // The comparison table's subsidy column does.
    expect(isAwaiting(['schedule', 'prices'], priceOnly)).toBe(true)
  })
})

describe('the price panel', () => {
  it('prices an example journey as the fixed part plus the distance part', () => {
    expect(exampleFare(8, 0.1, 1080)).toBeCloseTo(116, 6)
    expect(exampleFare(8, 0.1, 75)).toBeCloseTo(15.5, 6)
  })

  it('charges the fixed part on the shortest journey too', () => {
    // The whole point of the two-part tariff: a berth has a price of
    // admission a short journey pays as surely as a long one.
    expect(exampleFare(8, 0.1, 0)).toBe(8)
  })

  it('reads the catering contribution by its sign', () => {
    expect(cateringSign(1.2)).toBe('positive')
    expect(cateringSign(-0.8)).toBe('negative')
    expect(cateringSign(0)).toBe('neutral')
  })
})
