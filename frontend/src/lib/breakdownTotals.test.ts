import { describe, it, expect } from 'vitest'
import { fundedCostEur } from './breakdownTotals'
import type { Breakdown } from '@/types/api'

// Only the four totals matter here; the leaves are irrelevant to the sum.
function breakdown(cost: number, margin: number, revenue: number): Breakdown {
  return {
    cost: {
      operator: {
        variable: {
          driver_eur: 0,
          crew_eur: 0,
          coach_maintenance_eur: 0,
          loco_eur: 0,
          svc_stockings_eur: 0,
          var_overhead_eur: 0,
          total_eur: 0,
        },
        fixed: {
          coach_amortisation_eur: 0,
          financing_eur: 0,
          fix_overhead_eur: 0,
          cleaning_eur: 0,
          shunting_eur: 0,
          total_eur: 0,
        },
        total_eur: cost,
      },
      infrastructure: {
        tac_eur: 0,
        energy_eur: 0,
        station_charge_eur: 0,
        parking_eur: 0,
        total_eur: 0,
      },
      total_eur: cost,
    },
    revenue: { ticket_revenue_eur: revenue, total_eur: revenue },
    margin: { ebit_margin_eur: margin, total_eur: margin },
    total_cost_eur: cost,
    total_revenue_eur: revenue,
    net_eur: revenue - cost - margin,
  }
}

describe('fundedCostEur', () => {
  it('adds the expected margin to the cost total', () => {
    expect(fundedCostEur(breakdown(44_540_000, 2_500_000, 24_990_000))).toBe(47_040_000)
  })

  it('reconciles with the subsidy the KPI strip shows beside it', () => {
    // The strip renders revenue, this total, and -net_eur as the subsidy —
    // funded cost minus revenue has to equal that subsidy, or the three
    // figures visibly fail to add up.
    const b = breakdown(44_540_000, 2_500_000, 24_990_000)
    expect(fundedCostEur(b) - b.total_revenue_eur).toBeCloseTo(-b.net_eur, 6)
  })

  it('equals the cost total when no margin is taken', () => {
    expect(fundedCostEur(breakdown(1_000, 0, 0))).toBe(1_000)
  })
})
