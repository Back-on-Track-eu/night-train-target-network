import { describe, expect, it } from 'vitest'
import { compareKpi, goodness, isImprovement, relativeDelta, subsidyDisplay } from './compareKpis'

describe('subsidyDisplay', () => {
  it('reads the signed net: shortfall is a subsidy, positive is a surplus', () => {
    expect(subsidyDisplay({ co2_savings_t_per_year: 1, net_eur_per_year: -2_500_000 })).toEqual({
      kind: 'subsidy',
      millionEur: 2.5,
    })
    expect(subsidyDisplay({ co2_savings_t_per_year: 1, net_eur_per_year: 800_000 })).toEqual({
      kind: 'surplus',
      millionEur: 0.8,
    })
  })

  it('falls back to the clamped subsidy for pre-0.9.25 summaries', () => {
    expect(subsidyDisplay({ co2_savings_t_per_year: 1, subsidy_eur_per_year: 1_000_000 })).toEqual({
      kind: 'subsidy',
      millionEur: 1,
    })
    expect(subsidyDisplay({ co2_savings_t_per_year: 1 })).toEqual({ kind: 'unknown' })
  })
})

describe('compare KPIs', () => {
  it('signs the subsidy KPI as the net shortfall', () => {
    const kpi = compareKpi('subsidy')
    expect(kpi.value({ co2_savings_t_per_year: 1, net_eur_per_year: -3_000_000 })).toBe(3)
    expect(kpi.value({ co2_savings_t_per_year: 1, net_eur_per_year: 1_000_000 })).toBe(-1)
  })

  it('halves total_time_h for the one-direction journey time', () => {
    expect(compareKpi('journeyTime').value({ co2_savings_t_per_year: 1, total_time_h: 21 })).toBe(
      10.5,
    )
  })

  it('computes deltas and improvement direction', () => {
    expect(relativeDelta(90, 100)).toBe(-10)
    expect(relativeDelta(90, 0)).toBeNull()
    expect(isImprovement(compareKpi('subsidy'), -10)).toBe(true)
    expect(isImprovement(compareKpi('co2'), -10)).toBe(false)
  })

  it('pins zero to the middle of the subsidy scale when both signs occur', () => {
    const kpi = compareKpi('subsidy')
    expect(goodness(kpi, 0, -2, 4)).toBe(0.5)
    expect(goodness(kpi, 4, -2, 4)).toBe(0)
    expect(goodness(kpi, -2, -2, 4)).toBe(1)
    expect(goodness(compareKpi('co2'), 10, 0, 10)).toBe(1)
  })
})
