// The language bar's content: which languages we advertise, in which order,
// and which of them actually have a translation behind them today.
//
// Names are endonyms (each language written in its own language) and are never
// translated — the same convention back-on-track.eu uses.
import type { Locale } from '@/lib/localeStorage'

// Available entries carry a `Locale`, so switching needs no cast; the announced
// ones are labels only and stay inert until their locale file lands.
export type UiLanguage =
  { code: Locale; name: string; available: true } | { code: string; name: string; available: false }

// English first (the only live locale), German next (the one being translated),
// then the remaining back-on-track.eu languages in their site order.
export const UI_LANGUAGES: readonly UiLanguage[] = [
  { code: 'en', name: 'English', available: true },
  { code: 'de', name: 'Deutsch', available: false },
  { code: 'fr', name: 'Français', available: false },
  { code: 'nl', name: 'Nederlands', available: false },
  { code: 'it', name: 'Italiano', available: false },
  { code: 'es', name: 'Español', available: false },
  { code: 'pl', name: 'Polski', available: false },
]

export function availableLanguages(): Extract<UiLanguage, { available: true }>[] {
  return UI_LANGUAGES.filter(
    (lang): lang is Extract<UiLanguage, { available: true }> => lang.available,
  )
}
