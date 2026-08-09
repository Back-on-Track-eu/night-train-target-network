import type { Stop } from '@/types/api'
import { majorStops, capitalStopForCountry } from './majorStops'

export type GallerySearchMode = 'aToB' | 'byStation' | 'byCountry'

/** The Gallery search bar's state at the moment "Suggest a new route" is
 * clicked — used to prefill the new proposal's itinerary instead of two
 * arbitrary stops. */
export interface GallerySearchSeed {
  mode: GallerySearchMode
  fromStop: Stop | null
  toStop: Stop | null
  stationStop: Stop | null
  countryCode: string | null
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
 *  - anything else (empty search bar, or a byCountry pick with no resolvable
 *    capital): two random major stops.
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
