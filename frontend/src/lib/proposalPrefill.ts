import type { Stop } from '@/types/api'
import { majorStops, capitalStopForCountry } from './majorStops'

export type GallerySearchMode = 'aToB' | 'byStation' | 'byCountry' | 'byRelation'

const SEARCH_MODES: GallerySearchMode[] = ['aToB', 'byStation', 'byCountry', 'byRelation']

/** The Gallery search bar's state at the moment "Suggest a new route" is
 * clicked — used to prefill the new proposal's itinerary instead of two
 * arbitrary stops. */
export interface GallerySearchSeed {
  mode: GallerySearchMode
  fromStop: Stop | null
  toStop: Stop | null
  stationStop: Stop | null
  countryCode: string | null
  // byRelation's country pair. Kept as two separate codes rather than the
  // stored "AT__DE" token because the token is alphabetically ordered, which
  // would silently swap the user's two selects on reload.
  relationFrom: string | null
  relationTo: string | null
}

// Query-string shape for Gallery's own URL sync (?mode&from&to&station&
// country&relFrom&relTo[&sort&dir]) — /proposal-builder's prefill seed travels
// off-URL via store.pendingProposalSeed instead (see ProposalWorkspace.vue), so
// these only round-trip Gallery's own search bar now.
type SeedQuery = Partial<
  Record<'mode' | 'from' | 'to' | 'station' | 'country' | 'relFrom' | 'relTo', string>
>

export function seedToQuery(seed: GallerySearchSeed): SeedQuery {
  const query: SeedQuery = { mode: seed.mode }
  if (seed.fromStop) query.from = seed.fromStop.stop_id
  if (seed.toStop) query.to = seed.toStop.stop_id
  if (seed.stationStop) query.station = seed.stationStop.stop_id
  if (seed.countryCode) query.country = seed.countryCode
  if (seed.relationFrom) query.relFrom = seed.relationFrom
  if (seed.relationTo) query.relTo = seed.relationTo
  return query
}

// Reads a single query value regardless of vue-router normalizing repeated
// keys into an array — only the first occurrence is meaningful here. Exported
// for Gallery's own URL sync (sort/dir query params, outside the seed shape).
export function queryString(value: unknown): string | null {
  if (Array.isArray(value)) return typeof value[0] === 'string' ? value[0] : null
  return typeof value === 'string' ? value : null
}

export function seedFromQuery(query: Record<string, unknown>, stops: Stop[]): GallerySearchSeed {
  const modeParam = queryString(query.mode)
  const mode: GallerySearchMode = SEARCH_MODES.includes(modeParam as GallerySearchMode)
    ? (modeParam as GallerySearchMode)
    : 'aToB'
  const byId = new Map(stops.map((s) => [s.stop_id, s]))
  const fromId = queryString(query.from)
  const toId = queryString(query.to)
  const stationId = queryString(query.station)
  return {
    mode,
    fromStop: fromId ? (byId.get(fromId) ?? null) : null,
    toStop: toId ? (byId.get(toId) ?? null) : null,
    stationStop: stationId ? (byId.get(stationId) ?? null) : null,
    countryCode: queryString(query.country),
    relationFrom: queryString(query.relFrom),
    relationTo: queryString(query.relTo),
  }
}

function pickRandom<T>(pool: T[]): T | null {
  if (pool.length === 0) return null
  return pool[Math.floor(Math.random() * pool.length)]
}

// Prefer a major (capital) stop distinct from `exclude`, falling back to any
// other stop if fewer than one major is available to pick from.
function pickOtherStop(stops: Stop[], exclude: Stop): Stop | null {
  const rest = stops.filter((s) => s.stop_id !== exclude.stop_id)
  return pickRandom(majorStops(rest)) ?? pickRandom(rest)
}

// Two distinct major stops, falling back to any two stops if fewer than two
// majors are loaded — the no-seed / empty-search-bar default.
function defaultPair(stops: Stop[]): [Stop, Stop] | null {
  const majors = majorStops(stops)
  const first = pickRandom(majors.length >= 2 ? majors : stops)
  if (!first) return null
  const second = pickOtherStop(stops, first)
  return second ? [first, second] : null
}

/**
 * Resolve the two stops to prefill the proposal-creation mask with, honoring
 * whatever the Gallery search bar had selected when "Suggest a new route" was
 * clicked:
 *  - aToB with both fields filled: exactly those two stops, in order.
 *  - aToB with only one field filled, or byStation: that one stop first, a
 *    random major stop second.
 *  - byCountry: that country's capital first, a random (different) major
 *    stop second.
 *  - byRelation with both countries picked: the two capitals, in the order the
 *    user picked them (NOT the alphabetical order the filter token uses).
 *  - anything else (empty search bar, or a pick with no resolvable capital):
 *    two random major stops.
 */
export function resolvePrefillStops(
  seed: GallerySearchSeed | null,
  stops: Stop[],
): [Stop, Stop] | null {
  if (seed?.mode === 'aToB' && seed.fromStop && seed.toStop) {
    return [seed.fromStop, seed.toStop]
  }

  const knownStop =
    seed?.mode === 'byStation'
      ? seed.stationStop
      : seed?.mode === 'aToB'
        ? (seed.fromStop ?? seed.toStop)
        : null
  if (knownStop) {
    const other = pickOtherStop(stops, knownStop)
    return other ? [knownStop, other] : null
  }

  if (seed?.mode === 'byRelation' && seed.relationFrom && seed.relationTo) {
    const origin = capitalStopForCountry(stops, seed.relationFrom)
    const destination = capitalStopForCountry(stops, seed.relationTo)
    if (origin && destination && origin.stop_id !== destination.stop_id) {
      return [origin, destination]
    }
  }

  if (seed?.mode === 'byCountry' && seed.countryCode) {
    const capital = capitalStopForCountry(stops, seed.countryCode)
    if (capital) {
      // Always capital → another capital here — no falling back to just any
      // stop, unlike pickOtherStop's use above for a single known station.
      const other = pickRandom(majorStops(stops).filter((s) => s.stop_id !== capital.stop_id))
      if (other) return [capital, other]
    }
  }

  return defaultPair(stops)
}
