// The KPIs the comparison views (Zone A grid, Zone B bars and grid) can show,
// each read off a matrix cell's summary block. One registry so the KPI
// picker, the bars, the grid and the delta arrows agree on direction and
// formatting. Surplus rule: a subsidy of 0 with a positive net is a SURPLUS
// and is worded as one — no negative subsidy reaches a lay user (see
// subsidyDisplay).

import type { ProposalCalcSummary } from '@/types/api'

export type CompareKpiKey =
  'subsidy' | 'co2' | 'subsidyPerT' | 'pax' | 'paxKm' | 'shiftAir' | 'shiftCar' | 'journeyTime'

export interface CompareKpi {
  key: CompareKpiKey
  /** i18n key under proposal.compare.kpis */
  labelKey: CompareKpiKey
  /** Lower is better for costs and time; higher for everything else. */
  lowerIsBetter: boolean
  /** Signed value: for `subsidy` this is the NET shortfall (negative net →
   *  positive subsidy; positive net → negative, i.e. surplus). */
  value(summary: ProposalCalcSummary): number | null
  /** Formats a value for a compact label. */
  format(value: number, fmt: KpiFormatters): string
  /** i18n unit key under proposal.compare.units, if any. */
  unitKey?: string
}

export interface KpiFormatters {
  millionEur(value: number): string
  count(value: number): string
  int(value: number): string
  hours(value: number): string
}

const M = 1_000_000

export const COMPARE_KPIS: readonly CompareKpi[] = [
  {
    key: 'subsidy',
    labelKey: 'subsidy',
    lowerIsBetter: true,
    value: (s) => (s.net_eur_per_year == null ? null : -s.net_eur_per_year / M),
    format: (v, f) => f.millionEur(v),
    unitKey: 'millionEurYear',
  },
  {
    key: 'co2',
    labelKey: 'co2',
    lowerIsBetter: false,
    value: (s) => (s.co2_savings_t_per_year == null ? null : s.co2_savings_t_per_year / 1000),
    format: (v, f) => f.millionEur(v).replace(' €', ''),
    unitKey: 'ktYear',
  },
  {
    key: 'subsidyPerT',
    labelKey: 'subsidyPerT',
    lowerIsBetter: true,
    value: (s) => s.subsidy_eur_per_t_co2 ?? null,
    format: (v, f) => f.int(v),
    unitKey: 'eurPerT',
  },
  {
    key: 'pax',
    labelKey: 'pax',
    lowerIsBetter: false,
    value: (s) => s.demand_trips_per_year ?? null,
    format: (v, f) => f.count(v),
    unitKey: 'perYear',
  },
  {
    key: 'paxKm',
    labelKey: 'paxKm',
    lowerIsBetter: false,
    value: (s) => s.demand_trip_km_per_year ?? null,
    format: (v, f) => f.count(v),
    unitKey: 'kmYear',
  },
  {
    key: 'shiftAir',
    labelKey: 'shiftAir',
    lowerIsBetter: false,
    value: (s) => s.shift_air_trips_per_year ?? null,
    format: (v, f) => f.count(v),
    unitKey: 'perYear',
  },
  {
    key: 'shiftCar',
    labelKey: 'shiftCar',
    lowerIsBetter: false,
    value: (s) => s.shift_car_trips_per_year ?? null,
    format: (v, f) => f.count(v),
    unitKey: 'perYear',
  },
  {
    key: 'journeyTime',
    labelKey: 'journeyTime',
    lowerIsBetter: true,
    // Journey time of ONE direction: total_time_h sums both trips of the pair.
    value: (s) => (s.total_time_h == null ? null : s.total_time_h / 2),
    format: (v, f) => f.hours(v),
  },
]

export function compareKpi(key: CompareKpiKey): CompareKpi {
  return COMPARE_KPIS.find((k) => k.key === key) ?? COMPARE_KPIS[0]
}

/** Signed relative change of `value` against `baseline`, in percent, or null
 *  when the baseline is zero/missing. */
export function relativeDelta(value: number | null, baseline: number | null): number | null {
  if (value == null || baseline == null || baseline === 0) return null
  return ((value - baseline) / Math.abs(baseline)) * 100
}

/** Whether a change is an improvement for this KPI. */
export function isImprovement(kpi: CompareKpi, delta: number): boolean {
  return kpi.lowerIsBetter ? delta < 0 : delta > 0
}

export type SubsidyDisplay =
  | { kind: 'subsidy'; millionEur: number }
  | { kind: 'surplus'; millionEur: number }
  | { kind: 'unknown' }

/** The one rule every surface follows for a route's net position. */
export function subsidyDisplay(summary: ProposalCalcSummary): SubsidyDisplay {
  const net = summary.net_eur_per_year
  if (net == null) {
    const subsidy = summary.subsidy_eur_per_year
    return subsidy == null ? { kind: 'unknown' } : { kind: 'subsidy', millionEur: subsidy / M }
  }
  return net < 0
    ? { kind: 'subsidy', millionEur: -net / M }
    : { kind: 'surplus', millionEur: net / M }
}

/** Colour scale position 0..1 (0 = worst, 1 = best) for a grid cell. For the
 *  subsidy KPI with both signs present zero is pinned to the middle so
 *  "needs subsidy" and "surplus" never blend. */
export function goodness(kpi: CompareKpi, value: number, min: number, max: number): number {
  if (kpi.key === 'subsidy' && min < 0 && max > 0) {
    return value >= 0 ? 0.5 * ((max - value) / max) : 0.5 + 0.5 * (value / min)
  }
  const range = max - min || 1
  return kpi.lowerIsBetter ? (max - value) / range : (value - min) / range
}
