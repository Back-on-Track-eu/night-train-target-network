import type { Breakdown } from '@/types/api'

/**
 * What the route has to be paid, in €/year: operating costs plus the
 * operator's expected margin.
 *
 * The backend keeps margin as a third sibling to cost and revenue — it is a
 * profit carve-out, not a cost, and `Breakdown.cost.total_eur` therefore
 * excludes it (see backend/models/evaluation/views.py). The subsidy figure
 * does include it: `net_eur = revenue - cost - margin`. Showing bare
 * `cost.total_eur` next to that subsidy leaves the KPI strip short by exactly
 * the margin, so both the strip and the cost tree total use this instead.
 */
export function fundedCostEur(breakdown: Breakdown): number {
  return breakdown.cost.total_eur + breakdown.margin.total_eur
}
