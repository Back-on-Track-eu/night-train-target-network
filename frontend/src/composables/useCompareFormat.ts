import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { KpiFormatters } from '@/lib/compareKpis'

// Formatters for the comparison surfaces (KPI tiles, bars, grid, supply
// table). Locale-reactive like useEvaluationFormat; separate because these
// figures are already scaled (M €, kt) and need fixed decimals to line up in
// a table rather than compact notation.
export function useCompareFormat(): KpiFormatters & {
  signedPercent(value: number): string
  percent(value: number): string
  eur2(value: number): string
} {
  const { locale } = useI18n()
  const two = computed(
    () =>
      new Intl.NumberFormat(locale.value, { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
  )
  const one = computed(() => new Intl.NumberFormat(locale.value, { maximumFractionDigits: 1 }))
  const int = computed(() => new Intl.NumberFormat(locale.value, { maximumFractionDigits: 0 }))
  const compact = computed(
    () => new Intl.NumberFormat(locale.value, { notation: 'compact', maximumFractionDigits: 1 }),
  )
  return {
    millionEur: (v) => `${two.value.format(v)} M €`,
    count: (v) => (Math.abs(v) >= 10_000 ? compact.value.format(v) : int.value.format(v)),
    int: (v) => int.value.format(v),
    hours: (v) => {
      const h = Math.floor(v)
      const m = Math.round((v - h) * 60)
      return `${h}:${String(m).padStart(2, '0')} h`
    },
    signedPercent: (v) => `${v > 0 ? '+' : ''}${one.value.format(v)} %`,
    percent: (v) => `${int.value.format(v)} %`,
    eur2: (v) => `${two.value.format(v)} €`,
  }
}
