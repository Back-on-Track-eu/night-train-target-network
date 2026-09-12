import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { formatCount as count, formatEur as money } from '@/lib/money'

// Number formatting shared by the evaluation panel's sub-components (KPI /
// cost / revenue / demand figures, cost-factor rate table). Every formatter
// reads the active vue-i18n locale reactively. Must be called from within a
// component's `setup` (it uses `useI18n`).
export function useEvaluationFormat() {
  const { locale } = useI18n()

  const fmtSmall = computed(
    () => new Intl.NumberFormat(locale.value, { maximumSignificantDigits: 3 }),
  )
  const fmtPct = computed(
    () => new Intl.NumberFormat(locale.value, { style: 'percent', maximumFractionDigits: 1 }),
  )

  // Delegates to lib/money.ts so this panel and zone D print the same figure
  // the same way. The one thing kept from the old local rule: a rate below a
  // euro needs significant digits, or a €0.004/place-km leaf reads as "0 €".
  function formatEur(value: number): string {
    if (Math.abs(value) < 1 && value !== 0) return `${fmtSmall.value.format(value)} €`
    return money(value, locale.value)
  }

  function formatShare(share: number | null): string {
    return share === null ? '' : fmtPct.value.format(share)
  }

  function formatCount(value: number): string {
    return count(value, locale.value)
  }

  return { formatEur, formatShare, formatCount }
}
