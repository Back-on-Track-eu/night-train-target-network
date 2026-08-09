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

  // Whole-number formatting with the locale's grouping separator.
  function formatInt(value: number): string {
    return integerFmt.value.format(value)
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

  return { locale, formatInt, countryName }
}
