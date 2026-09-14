// The language bar's content: which languages we advertise, in which order,
// and which of them actually have a translation behind them today. Only
// languages with a locale file in i18n/locales/ are listed at all — an
// announced language the bar cannot deliver is a promise, not a feature.
//
// Names are endonyms (each language written in its own language) and are never
// translated — the same convention back-on-track.eu uses.
import type { Locale } from '@/lib/localeStorage'

// Available entries carry a `Locale`, so switching needs no cast; the announced
// ones are labels only and stay inert until their locale file lands.
export type UiLanguage =
  | { code: Locale; name: string; available: true }
  | { code: string; name: string; available: false }

// English first, German next, matching back-on-track.eu's site order. The
// `available: false` branch (and LanguageSwitch's greyed-out rendering of it)
// stays for the next locale that is announced before its file lands.
export const UI_LANGUAGES: readonly UiLanguage[] = [
  { code: 'en', name: 'English', available: true },
  { code: 'de', name: 'Deutsch', available: true },
]

export function availableLanguages(): Extract<UiLanguage, { available: true }>[] {
  return UI_LANGUAGES.filter(
    (lang): lang is Extract<UiLanguage, { available: true }> => lang.available,
  )
}
