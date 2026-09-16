import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { KpiFormatters } from '@/lib/compareKpis'
import { formatCount, formatEur, formatInt, formatMillionEur } from '@/lib/money'

// Formatters for the comparison surfaces (KPI tiles, bars, grid, supply
// table) and for zone D's panels. Locale-reactive; the arithmetic and the
// scale rules live in lib/money.ts so this and useEvaluationFormat cannot
// drift apart — they did, and the same annual figure was printed three ways
// on one screen.
export function useCompareFormat(): KpiFormatters & {
  signedPercent(value: number): string
  percent(value: number): string
  /** Euros, lib/money.ts's one rule. `eur2` is the same function under the
   *  name the receipts already use. */
  eur2(value: number): string
  eur(value: number): string
  /** A quantity with one decimal — hours, kWh, densities. Grouped like
   *  everything else, so 1,234.5 h and 1,234.50 € line up. */
  dec1(value: number): string
  dec2(value: number): string
  /** Three decimals — the per-km fare, which is tenths of a cent. */
  dec3(value: number): string
} {
  const { locale } = useI18n()
  const two = computed(
    () =>
      new Intl.NumberFormat(locale.value, { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
  )
  const three = computed(
    () =>
      new Intl.NumberFormat(locale.value, { minimumFractionDigits: 3, maximumFractionDigits: 3 }),
  )
  const one = computed(
    () =>
      new Intl.NumberFormat(locale.value, { minimumFractionDigits: 1, maximumFractionDigits: 1 }),
  )
  const int = computed(() => new Intl.NumberFormat(locale.value, { maximumFractionDigits: 0 }))
  return {
    millionEur: (v) => formatMillionEur(v, locale.value),
    count: (v) => formatCount(v, locale.value),
    int: (v) => formatInt(v, locale.value),
    hours: (v) => {
      const h = Math.floor(v)
      const m = Math.round((v - h) * 60)
      return `${h}:${String(m).padStart(2, '0')} h`
    },
    signedPercent: (v) => `${v > 0 ? '+' : ''}${one.value.format(v)} %`,
    percent: (v) => `${int.value.format(v)} %`,
    eur2: (v) => formatEur(v, locale.value),
    eur: (v) => formatEur(v, locale.value),
    dec1: (v) => one.value.format(v),
    dec2: (v) => two.value.format(v),
    dec3: (v) => three.value.format(v),
  }
}
