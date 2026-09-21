import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

// Locale-aware number and region formatting. Every formatter reads the active
// vue-i18n locale reactively, so figures follow local conventions (English
// 1,234.5 vs German 1.234,5) and country names render in the active language.
// Must be called from within a component's `setup` (it uses `useI18n`).
export function useLocaleFormat() {
  const { locale } = useI18n()

  const integerFmt = computed(
    () => new Intl.NumberFormat(locale.value, { maximumFractionDigits: 0 }),
  )
  const regionNames = computed(() => new Intl.DisplayNames([locale.value], { type: 'region' }))
  // Day precision: every timestamp the UI shows is an authoring date, where the
  // hour is noise ("12 Sep 2026" / "12. Sep. 2026").
  const dateFmt = computed(
    () =>
      new Intl.DateTimeFormat(locale.value, { year: 'numeric', month: 'short', day: 'numeric' }),
  )

  // Whole-number formatting with the locale's grouping separator.
  function formatInt(value: number): string {
    return integerFmt.value.format(value)
  }

  // An ISO 8601 timestamp as a localized short date; empty for an unparseable
  // value, so a bad row degrades to no date rather than "Invalid Date".
  function formatDate(iso: string): string {
    const date = new Date(iso)
    return Number.isNaN(date.getTime()) ? '' : dateFmt.value.format(date)
  }

  // Localized country name for an ISO 3166-1 alpha-2 code; falls back to the
  // raw code when Intl has no entry (Intl ships no bundled data guarantees).
  function countryName(code: string): string {
    try {
      return regionNames.value.of(code.toUpperCase()) ?? code
    } catch {
      return code
    }
  }

  return { locale, formatInt, formatDate, countryName }
}
