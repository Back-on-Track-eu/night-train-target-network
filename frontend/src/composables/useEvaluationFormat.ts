import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { RateRow } from '@/lib/costFactorRates'

// Number formatting shared by the evaluation panel's sub-components (KPI /
// cost / revenue / demand figures, cost-factor rate table). Every formatter
// reads the active vue-i18n locale reactively. Must be called from within a
// component's `setup` (it uses `useI18n`).
export function useEvaluationFormat() {
  const { locale } = useI18n()

  const fmtCompact = computed(
    () => new Intl.NumberFormat(locale.value, { notation: 'compact', maximumFractionDigits: 2 }),
  )
  const fmtInt = computed(() => new Intl.NumberFormat(locale.value, { maximumFractionDigits: 0 }))
  const fmtSmall = computed(
    () => new Intl.NumberFormat(locale.value, { maximumSignificantDigits: 3 }),
  )
  const fmtPct = computed(
    () => new Intl.NumberFormat(locale.value, { style: 'percent', maximumFractionDigits: 1 }),
  )
  const fmtRate = computed(() => new Intl.NumberFormat(locale.value, { maximumFractionDigits: 4 }))

  // Monetary figures — compact once large, integer above 100, else a few
  // significant digits so small fares/charges don't collapse to "0 €".
  function formatEur(value: number): string {
    const abs = Math.abs(value)
    if (abs >= 100_000) return `${fmtCompact.value.format(value)} €`
    if (abs >= 100) return `${fmtInt.value.format(value)} €`
    return `${fmtSmall.value.format(value)} €`
  }

  function formatShare(share: number | null): string {
    return share === null ? '' : fmtPct.value.format(share)
  }

  // Plain counts (trips, pax-km, tonnes) — compact once large, integer below so
  // per-operating-day figures don't collapse to "0.1K".
  function formatCount(value: number): string {
    return Math.abs(value) >= 10_000 ? fmtCompact.value.format(value) : fmtInt.value.format(value)
  }

  // Quota fields are stored as fractions (0.1) but described in "%" — render
  // them as a percentage for readability; other units are shown verbatim.
  function formatRateValue(row: RateRow): string {
    const value = row.unit.startsWith('%') ? row.value * 100 : row.value
    return fmtRate.value.format(value)
  }

  return { formatEur, formatShare, formatCount, formatRateValue }
}
