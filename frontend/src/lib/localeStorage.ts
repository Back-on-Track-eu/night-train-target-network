// Persists the user's chosen UI language across visits. Unlike auth (see
// authCookie.ts), this never needs to reach the backend, so localStorage is
// enough — no cookie, no expiry.
export type Locale = 'en' | 'de'

const STORAGE_KEY = 'nt_locale'
const SUPPORTED: Locale[] = ['en', 'de']

export function readLocale(): Locale | null {
  const raw = localStorage.getItem(STORAGE_KEY)
  return SUPPORTED.includes(raw as Locale) ? (raw as Locale) : null
}

export function writeLocale(locale: Locale): void {
  localStorage.setItem(STORAGE_KEY, locale)
}
