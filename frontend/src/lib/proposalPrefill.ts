import type { Stop } from '@/types/api'
import { majorStops, capitalStopForCountry } from './majorStops'
import {
  SEARCH_KINDS,
  SEARCH_TABS,
  activePicks,
  type CityOption,
  type GallerySearchKind,
  type GallerySearchPicks,
  type GallerySearchTab,
} from './gallerySearch'

/** The Gallery search bar's state at the moment "Suggest a new route" is
 * clicked — used to prefill the new proposal's itinerary instead of two
 * arbitrary stops, and to round-trip the bar through /gallery's URL. The
 * picks of every tab are kept, not only the active one, so switching tabs
 * and back does not lose a selection. */
export type GallerySearchSeed = GallerySearchPicks

export const EMPTY_SEED: GallerySearchSeed = {
  tab: 'station',
  kind: 'via',
  stops: [null, null],
  cities: [null, null],
  countries: [null, null],
}

// Query-string shape for Gallery's own URL sync: ?tab&kind&a&b, where a/b are
// the active tab's ids (stop id, city OSM id, ISO code). /proposal-builder's
// prefill seed travels off-URL via store.pendingProposalSeed instead (see
// ProposalWorkspace.vue), so these only round-trip Gallery's own search bar.
type SeedQuery = Partial<Record<'tab' | 'kind' | 'a' | 'b', string>>

export function seedToQuery(seed: GallerySearchSeed): SeedQuery {
  const query: SeedQuery = { tab: seed.tab, kind: seed.kind }
  // Slots are kept: a "to" picked alone stays "to", it does not slide into "from".
  const [a, b]: (string | null)[] =
    seed.tab === 'station'
      ? seed.stops.map((s) => s?.stop_id ?? null)
      : seed.tab === 'city'
        ? seed.cities.map((c) => (c ? String(c.osm_id) : null))
        : seed.countries
  if (a) query.a = a
  if (b && seed.kind === 'fromTo') query.b = b
  return query
}

// Reads a single query value regardless of vue-router normalizing repeated
// keys into an array — only the first occurrence is meaningful here. Exported
// for Gallery's own URL sync (sort/dir query params, outside the seed shape).
export function queryString(value: unknown): string | null {
  if (Array.isArray(value)) return typeof value[0] === 'string' ? value[0] : null
  return typeof value === 'string' ? value : null
}

// The pre-2026-10-04 query shape (?mode&from&to&station&country&relFrom&
// relTo), mapped onto tab/kind/a/b so shared links keep working. Dropped once
// those links have aged out.
function legacyQuery(query: Record<string, unknown>): SeedQuery | null {
  const mode = queryString(query.mode)
  if (!mode) return null
  const q = (k: string) => queryString(query[k]) ?? undefined
  switch (mode) {
    case 'aToB':
      return { tab: 'station', kind: 'fromTo', a: q('from'), b: q('to') }
    case 'byStation':
      return { tab: 'station', kind: 'via', a: q('station') }
    case 'byCountry':
      return { tab: 'country', kind: 'via', a: q('country') }
    case 'byRelation':
      return { tab: 'country', kind: 'fromTo', a: q('relFrom'), b: q('relTo') }
    default:
      return null
  }
}

export function seedFromQuery(
  query: Record<string, unknown>,
  stops: readonly Stop[],
  cities: readonly CityOption[],
): GallerySearchSeed {
  const raw: SeedQuery = {
    tab: queryString(query.tab) ?? undefined,
    kind: queryString(query.kind) ?? undefined,
    a: queryString(query.a) ?? undefined,
    b: queryString(query.b) ?? undefined,
    ...(queryString(query.tab) ? {} : legacyQuery(query)),
  }
  const tab: GallerySearchTab = SEARCH_TABS.includes(raw.tab as GallerySearchTab)
    ? (raw.tab as GallerySearchTab)
    : EMPTY_SEED.tab
  const kind: GallerySearchKind = SEARCH_KINDS.includes(raw.kind as GallerySearchKind)
    ? (raw.kind as GallerySearchKind)
    : EMPTY_SEED.kind
  const seed: GallerySearchSeed = { ...EMPTY_SEED, tab, kind }
  const b = kind === 'fromTo' ? raw.b : undefined
  if (tab === 'station') {
    const byId = new Map(stops.map((s) => [s.stop_id, s]))
    seed.stops = [raw.a ? (byId.get(raw.a) ?? null) : null, b ? (byId.get(b) ?? null) : null]
  } else if (tab === 'city') {
    const byId = new Map(cities.map((c) => [String(c.osm_id), c]))
    seed.cities = [raw.a ? (byId.get(raw.a) ?? null) : null, b ? (byId.get(b) ?? null) : null]
  } else {
    seed.countries = [raw.a?.toUpperCase() ?? null, b?.toUpperCase() ?? null]
  }
  return seed
}

function pickRandom<T>(pool: readonly T[]): T | null {
  if (pool.length === 0) return null
  return pool[Math.floor(Math.random() * pool.length)]
}

// Prefer a major (capital) stop distinct from `exclude`, falling back to any
// other stop if fewer than one major is available to pick from.
function pickOtherStop(stops: readonly Stop[], exclude: Stop): Stop | null {
  const rest = stops.filter((s) => s.stop_id !== exclude.stop_id)
  return pickRandom(majorStops(rest)) ?? pickRandom(rest)
}

// Two distinct major stops, falling back to any two stops if fewer than two
// majors are loaded — the no-seed / empty-search-bar default.
function defaultPair(stops: readonly Stop[]): [Stop, Stop] | null {
  const majors = majorStops(stops)
  const first = pickRandom(majors.length >= 2 ? majors : stops)
  if (!first) return null
  const second = pickOtherStop(stops, first)
  return second ? [first, second] : null
}

// A city's representative stop: its capital-listed stop if it has one (the
// Hauptbahnhof, by the naming the capital table relies on), else its first.
function stopForCity(stops: readonly Stop[], city: CityOption): Stop | null {
  const own = stops.filter((s) => city.stop_ids.includes(s.stop_id))
  return majorStops(own)[0] ?? own[0] ?? null
}

/**
 * Resolve the two stops to prefill the proposal-creation mask with, honoring
 * whatever the Gallery search bar had selected when "Suggest a new route" was
 * clicked:
 *  - station, both picks: exactly those two stops, in order; one pick: that
 *    stop first, a random major stop second.
 *  - city: each picked city's representative stop; one city: that stop
 *    first, a random (different) major stop second.
 *  - country, one pick: that country's capital first, a random (different)
 *    major stop second; two picks: the two capitals, in the order the user
 *    picked them (NOT the alphabetical order the relation token uses).
 *  - anything else (empty search bar, or a pick with no resolvable stop):
 *    two random major stops.
 */
export function resolvePrefillStops(
  seed: GallerySearchSeed | null,
  stops: readonly Stop[],
): [Stop, Stop] | null {
  const known: Stop[] = !seed
    ? []
    : seed.tab === 'station'
      ? activePicks(seed, (p) => p.stops)
      : seed.tab === 'city'
        ? activePicks(seed, (p) => p.cities)
            .map((c) => stopForCity(stops, c))
            .filter((s): s is Stop => s !== null)
        : activePicks(seed, (p) => p.countries)
            .map((code) => capitalStopForCountry(stops, code))
            .filter((s): s is Stop => s !== null)

  if (known.length >= 2 && known[0].stop_id !== known[1].stop_id) {
    return [known[0], known[1]]
  }
  if (known.length >= 1) {
    const first = known[0]
    // A country pick pairs capital with capital — no falling back to just
    // any stop, unlike a single known station.
    const other =
      seed?.tab === 'country'
        ? pickRandom(majorStops(stops).filter((s) => s.stop_id !== first.stop_id))
        : pickOtherStop(stops, first)
    return other ? [first, other] : null
  }
  return defaultPair(stops)
}
