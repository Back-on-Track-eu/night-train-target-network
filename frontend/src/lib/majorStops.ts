import type { Stop } from '@/types/api'

// National-capital stops used to prefill the proposal-creation mask with
// sensible defaults instead of arbitrary random stops. Matched by a name
// substring against the capital city, since stops carry no importance/capital
// flag of their own (see backend/models/infrastructure/STOP_CLASSIFICATION.md
// for a not-yet-implemented tier system that could replace this). Local-
// language names, matching the naming convention already used by the stop
// catalogue (e.g. "Wien Hbf", "Praha hl.n.", not "Vienna"/"Prague"). Static
// for now, and best-effort beyond the curated dev seed (backend/db/dev/
// seed.py) — countries whose stops come from the gitignored ONTD catalogue
// couldn't be checked against real data, so an entry with no matching stop is
// simply never picked (harmless); extend/correct as new countries are added.
const CAPITAL_CITY_BY_COUNTRY: Record<string, string> = {
  DE: 'Berlin',
  AT: 'Wien',
  CH: 'Bern',
  FR: 'Paris',
  BE: 'Bruxelles',
  DK: 'Koebenhavn',
  SE: 'Stockholm',
  NL: 'Amsterdam',
  CZ: 'Praha',
  IT: 'Roma',
  RO: 'Bucuresti',
  PL: 'Warszawa',
  HU: 'Budapest',
  BG: 'Sofia',
  HR: 'Zagreb',
  SK: 'Bratislava',
  SI: 'Ljubljana',
  ES: 'Madrid',
  PT: 'Lisboa',
  LU: 'Luxembourg',
  NO: 'Oslo',
  FI: 'Helsinki',
  IE: 'Dublin',
}

/** The capital stop for a country, if the given list has one. Where a
 * country has multiple stations matching its capital's name, the first
 * match is used — one station per capital, not every match. */
export function capitalStopForCountry(stops: Stop[], countryCode: string): Stop | null {
  const cityName = CAPITAL_CITY_BY_COUNTRY[countryCode]
  if (!cityName) return null
  return stops.find((s) => s.country_code === countryCode && s.name.includes(cityName)) ?? null
}

/** Every recognized national capital's stop in the given list — at most one
 * per country. */
export function majorStops(stops: Stop[]): Stop[] {
  return Object.keys(CAPITAL_CITY_BY_COUNTRY)
    .map((code) => capitalStopForCountry(stops, code))
    .filter((s): s is Stop => s !== null)
}
