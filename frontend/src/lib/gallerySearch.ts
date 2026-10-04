// The gallery's search bar as data: one TAB (what kind of place), one KIND
// (one place, or two), two picks. Pure, so the filter mapping and the city
// grouping are unit-tested here rather than in Gallery.vue (the frontend test
// setup never mounts components).
//
//   tab      kind      backend filter
//   station  via       stop_ids: [a]
//   station  fromTo    stop_ids: {values: [a, b], mode: 'all'}
//   city     via       cities: [a]
//   city     fromTo    cities: {values: [a, b], mode: 'all'}
//   country  via       countries: [a]
//   country  fromTo    country_relations: ["A__B"]
//
// "From → to" means both places are touched, in either direction — not that
// they are the end points. The backend has no ordering predicate, and the
// gallery has always read it this way (decided 2026-10-04).

import type { ProposalsFilter, Stop } from '@/types/api'
import { buildRelationToken } from '@/lib/galleryMap'

export type GallerySearchTab = 'station' | 'city' | 'country'
export type GallerySearchKind = 'via' | 'fromTo'

export const SEARCH_TABS: readonly GallerySearchTab[] = ['station', 'city', 'country']
export const SEARCH_KINDS: readonly GallerySearchKind[] = ['via', 'fromTo']

/** A city as the search bar offers it: the stops that belong to it (the
 *  catalogue's StopCity, keyed by its OSM place node — the backend's
 *  `cities` filter takes that id) and where to put its pin. */
export interface CityOption {
  osm_id: number
  /** Display name in the UI locale, falling back through English to the
   *  on-the-ground name. */
  name: string
  /** Every catalogue-language name, for the picker's search text. */
  names: Record<string, string>
  country_code: string
  stop_ids: string[]
  /** Centroid of the city's stops — where the map pins the city. */
  lon: number
  lat: number
}

/**
 * Group the stops store by city. Stops without a resolved city (rural halts,
 * or a catalogue row that never got one) are not reachable through this tab —
 * they remain reachable by station. Sorted by name for the picker.
 */
export function cityOptions(stops: readonly Stop[], locale: string): CityOption[] {
  const byId = new Map<number, CityOption & { lonSum: number; latSum: number }>()
  for (const stop of stops) {
    const city = stop.city
    if (!city || city.osm_id === null) continue
    let entry = byId.get(city.osm_id)
    if (!entry) {
      entry = {
        osm_id: city.osm_id,
        name: city.names[locale] || city.names.en || city.name,
        names: { ...city.names, local: city.name },
        country_code: stop.country_code,
        stop_ids: [],
        lon: 0,
        lat: 0,
        lonSum: 0,
        latSum: 0,
      }
      byId.set(city.osm_id, entry)
    }
    entry.stop_ids.push(stop.stop_id)
    entry.lonSum += stop.lon
    entry.latSum += stop.lat
  }
  return [...byId.values()]
    .map(({ lonSum, latSum, ...city }) => ({
      ...city,
      lon: lonSum / city.stop_ids.length,
      lat: latSum / city.stop_ids.length,
    }))
    .sort((a, b) => a.name.localeCompare(b.name))
}

/** The picks of the active tab, as the backend keys them: stop ids, city
 *  OSM ids or ISO country codes. `b` is only read for kind 'fromTo'. */
export interface GallerySearchPicks {
  tab: GallerySearchTab
  kind: GallerySearchKind
  stops: readonly [Stop | null, Stop | null]
  cities: readonly [CityOption | null, CityOption | null]
  countries: readonly [string | null, string | null]
}

/** The active tab's picks that are filled, in pick order — one for 'via',
 *  up to two for 'fromTo'. */
export function activePicks<T>(
  picks: GallerySearchPicks,
  select: (p: GallerySearchPicks) => readonly [T | null, T | null],
): T[] {
  const [a, b] = select(picks)
  const chosen = picks.kind === 'fromTo' ? [a, b] : [a]
  return chosen.filter((v): v is T => v !== null)
}

/**
 * The search bar's contribution to the request filter. One pick is the same
 * query whichever kind is on — 'all' over a single value equals 'any' — so a
 * half-filled "from → to" is sent as the plain list.
 */
export function searchFilter(picks: GallerySearchPicks): Partial<ProposalsFilter> {
  if (picks.tab === 'station') {
    const ids = activePicks(picks, (p) => p.stops).map((s) => s.stop_id)
    if (!ids.length) return {}
    return { stop_ids: ids.length > 1 ? { values: ids, mode: 'all' } : ids }
  }
  if (picks.tab === 'city') {
    const ids = activePicks(picks, (p) => p.cities).map((c) => c.osm_id)
    if (!ids.length) return {}
    return { cities: ids.length > 1 ? { values: ids, mode: 'all' } : ids }
  }
  const codes = activePicks(picks, (p) => p.countries)
  if (!codes.length) return {}
  // Two countries are a stored relation ("AT__DE", direction-agnostic). A
  // self-pair cannot name one, so it falls back to the single country.
  const token = codes.length > 1 ? buildRelationToken(codes[0], codes[1]) : null
  return token ? { country_relations: [token] } : { countries: [codes[0]] }
}

/** Stop ids the search targets — the cards underline them and the map pins
 *  them (a city pins once, at its centroid, but anchors all its stops). */
export function anchorStopIds(picks: GallerySearchPicks): string[] {
  if (picks.tab === 'station') return activePicks(picks, (p) => p.stops).map((s) => s.stop_id)
  if (picks.tab === 'city') return activePicks(picks, (p) => p.cities).flatMap((c) => c.stop_ids)
  return []
}
