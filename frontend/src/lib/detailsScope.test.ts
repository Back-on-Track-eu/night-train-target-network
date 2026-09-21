import { describe, it, expect } from 'vitest'
import {
  DEFAULT_DAYS_PER_WEEK,
  TAB_AWAITS,
  cateringSign,
  daysPerWeekFromRequest,
  demandFromRequest,
  demandRequest,
  dirtyScopes,
  exampleFare,
  isAwaiting,
  operatingDaysPerYear,
  sameDemand,
  scheduleRequest,
  supplyFigures,
  trainsetsFor,
  type DemandInputs,
} from './detailsScope'

const tariff = (over: Partial<Parameters<typeof dirtyScopes>[0]['tariff']> = {}) => ({
  faresPerKm: { Seat: 0.1, Couchette: 0.13, Sleeper: 0.18, Capsule: 0.12 },
  faresPerPax: { Seat: 8, Couchette: 12, Sleeper: 18, Capsule: 12 },
  servicesPerPax: { Seat: 1.5, Couchette: 2, Sleeper: 3, Capsule: 2 },
  cateringPerPax: { Seat: 1.2, Couchette: 1.2, Sleeper: 0.6, Capsule: 1.2 },
  ...over,
})

const demand = (over: Partial<DemandInputs> = {}): DemandInputs => ({
  level: 'medium',
  passengersPerYear: 200000,
  groupSharesPct: { comfort: 50, group: 25, senior: 10, budget: 10, business: 5 },
  od: { preset: 'even', stopWeights: { board: {}, alight: {} }, pinnedSharesPct: {} },
  ...over,
})

const inputs = (over: Partial<Parameters<typeof dirtyScopes>[0]> = {}) => ({
  daysPerWeek: DEFAULT_DAYS_PER_WEEK,
  tariff: tariff(),
  demand: demand(),
  ...over,
})

const flat = (d: number) =>
  Object.fromEntries(Array.from({ length: 12 }, (_, i) => [String(i + 1), d]))

describe('the frequency', () => {
  it('counts a daily year as the backend does — 2032 is a leap year', () => {
    expect(operatingDaysPerYear(7)).toBe(366)
  })

  it("counts three days a week as the guide's 156.86 operating days", () => {
    expect(operatingDaysPerYear(3)).toBeCloseTo(156.857, 3)
  })

  it('posts one figure, clamped to 1..7 whole days', () => {
    expect(scheduleRequest(3)).toEqual({ schedule: { days_per_week: 3 } })
    expect(scheduleRequest(9)).toEqual({ schedule: { days_per_week: 7 } })
    expect(scheduleRequest(2.6)).toEqual({ schedule: { days_per_week: 3 } })
  })

  it('reads a flat echo back exactly', () => {
    expect(daysPerWeekFromRequest(flat(5))).toBe(5)
  })

  it('reads a seasonal echo as its rounded average over the year', () => {
    const summerOnly = { ...flat(0), '5': 7, '6': 7, '7': 7, '8': 7, '9': 7 }
    // 35 / 12 = 2.9 → 3
    expect(daysPerWeekFromRequest(summerOnly)).toBe(3)
    // never below one: a stored plan that ran at all is at least once a week
    expect(daysPerWeekFromRequest({ ...flat(0), '7': 1 })).toBe(1)
  })

  it('reads an absent echo as the default', () => {
    expect(daysPerWeekFromRequest(null)).toBe(DEFAULT_DAYS_PER_WEEK)
    expect(daysPerWeekFromRequest(undefined)).toBe(DEFAULT_DAYS_PER_WEEK)
  })
})

describe('the fleet', () => {
  it('rounds the cycle times the frequency up', () => {
    expect(trainsetsFor(7, 2)).toBe(2)
    expect(trainsetsFor(4, 2)).toBe(2)
    expect(trainsetsFor(3, 2)).toBe(1)
    expect(trainsetsFor(1, 2)).toBe(1)
    expect(trainsetsFor(7, 3)).toBe(3)
  })

  it('declines to guess without a cycle from the last result', () => {
    expect(trainsetsFor(7, null)).toBeNull()
    expect(trainsetsFor(7, 0)).toBeNull()
  })
})

describe('the supply figures a schedule change previews', () => {
  const figures = supplyFigures(7, 2160, 260, 2)

  it('derives departures, train-km and place-km from the frequency', () => {
    expect(figures.operatingDays).toBe(366)
    expect(figures.departures).toBe(732)
    expect(figures.trainKm).toBe(366 * 2160)
    expect(figures.placesOffered).toBe(732 * 260)
    expect(figures.placeKmOffered).toBe(260 * 366 * 2160)
  })

  it("matches the guide's reference at three days a week", () => {
    const three = supplyFigures(3, 2160, 260, 2)
    expect(three.departures).toBeCloseTo(313.714, 3)
    expect(Math.round(three.trainKm)).toBe(338811)
    expect(three.trainsets).toBe(1)
  })
})

describe('the demand block', () => {
  it('round-trips through the request echo', () => {
    const d = demand({
      level: 'custom',
      passengersPerYear: 123456,
      od: {
        preset: 'long',
        stopWeights: { board: { a: 3 }, alight: { z: 0.3 } },
        pinnedSharesPct: { a: { z: 12.5 } },
      },
    })
    const echo = demandRequest(d).demand as Record<string, unknown>
    expect(echo.passengers_per_year).toBe(123456)
    expect(demandFromRequest({ demand: echo })).toEqual(d)
  })

  it('reads an echo without a demand block as none', () => {
    expect(demandFromRequest({})).toBeNull()
    expect(demandFromRequest(null)).toBeNull()
  })

  it('compares the numbers, not the labels', () => {
    expect(sameDemand(demand({ level: 'medium' }), demand({ level: 'custom' }))).toBe(true)
    expect(sameDemand(demand(), demand({ od: { ...demand().od, preset: 'long' } }))).toBe(true)
    expect(sameDemand(demand(), demand({ passengersPerYear: 200001 }))).toBe(false)
    expect(
      sameDemand(demand(), demand({ groupSharesPct: { ...demand().groupSharesPct, budget: 11 } })),
    ).toBe(false)
    expect(
      sameDemand(demand(), demand({ od: { ...demand().od, pinnedSharesPct: { a: { b: 5 } } } })),
    ).toBe(false)
    expect(sameDemand(null, null)).toBe(true)
    expect(sameDemand(demand(), null)).toBe(false)
  })
})

describe('the change-scope rule', () => {
  it('is quiet when nothing has been touched', () => {
    expect(dirtyScopes(inputs(), inputs())).toEqual(new Set())
  })

  it('is quiet before anything has been computed', () => {
    expect(dirtyScopes(inputs(), null)).toEqual(new Set())
  })

  it('marks the schedule alone when the frequency moves', () => {
    const dirty = dirtyScopes(inputs({ daysPerWeek: 7 }), inputs())
    expect([...dirty]).toEqual(['schedule'])
  })

  it('marks the demand alone when a demand figure moves', () => {
    const dirty = dirtyScopes(inputs({ demand: demand({ passengersPerYear: 300000 }) }), inputs())
    expect([...dirty]).toEqual(['demand'])
  })

  it('treats a committed echo without a demand block as changed', () => {
    // Figures computed by the stopgap cannot be said to match any demand
    // input, so the first Recalculate after the upgrade is due.
    expect([...dirtyScopes(inputs(), inputs({ demand: null }))]).toEqual(['demand'])
  })

  it('lights the tab dots as D2 says', () => {
    const dirty = new Set(['demand'] as const)
    expect(isAwaiting(TAB_AWAITS.demand, dirty)).toBe(false)
    expect(isAwaiting(TAB_AWAITS.supply, dirty)).toBe(true)
    expect(isAwaiting(TAB_AWAITS.operation, dirty)).toBe(true)
    expect(isAwaiting(TAB_AWAITS.infrastructure, dirty)).toBe(false)
    expect(isAwaiting(TAB_AWAITS.overhead, dirty)).toBe(true)
    const prices = new Set(['prices'] as const)
    expect(isAwaiting(TAB_AWAITS.supply, prices)).toBe(false)
    expect(isAwaiting(TAB_AWAITS.infrastructure, prices)).toBe(false)
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
    const edited = inputs({ daysPerWeek: 1 })
    expect(dirtyScopes(edited, committed).size).toBe(1)
    expect(dirtyScopes(inputs(), committed).size).toBe(0)
  })

  it('makes a panel wait only for the scopes it depends on', () => {
    const priceOnly = new Set<'schedule' | 'prices' | 'demand'>(['prices'])
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
