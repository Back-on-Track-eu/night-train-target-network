// The gallery's four range filters — distance, duration, average speed,
// stops — as one value: what the distribution panel edits
// (GalleryDistribution.vue), what Gallery.vue sends, and what the URL
// carries. Pure functions, so the panel's behaviour is testable without a
// component.
//
// A range is a pair of optional bounds; an absent measure or an empty pair
// means "no range". The position paper's yardstick is one particular value
// of this type (typicalNightTrainRanges), which is how "preset on" is simply
// "ranges equal the preset" and nothing has to remember a toggle.

import type { LocationQuery, LocationQueryRaw } from 'vue-router'
import type { ProposalsFilter, ProposalsRange } from '@/types/api'
import { TYPICAL_NIGHT_TRAIN } from './typicalNightTrain'

export const GALLERY_MEASURES = [
  'total_distance_km',
  'total_time_h',
  'avg_speed_kmh',
  'n_stops',
] as const
export type GalleryMeasure = (typeof GALLERY_MEASURES)[number]

export type Bounds = Pick<ProposalsRange, 'min' | 'max'>
export type GalleryRanges = Partial<Record<GalleryMeasure, Bounds>>

// The URL key per measure: short, since a shared link may carry all four.
const QUERY_KEYS: Record<GalleryMeasure, string> = {
  total_distance_km: 'km',
  total_time_h: 'h',
  avg_speed_kmh: 'kmh',
  n_stops: 'stops',
}
// Older links (the toggle era) said "preset off" this way; still honoured.
const TYPICAL_OFF_KEY = 'typical'

export function typicalNightTrainRanges(): GalleryRanges {
  return {
    total_distance_km: { ...TYPICAL_NIGHT_TRAIN.distanceKm },
    total_time_h: { ...TYPICAL_NIGHT_TRAIN.timeH },
    avg_speed_kmh: { ...TYPICAL_NIGHT_TRAIN.avgSpeedKmh },
  }
}

export function isEmptyBounds(bounds: Bounds | undefined): boolean {
  return !bounds || (bounds.min === undefined && bounds.max === undefined)
}

/** Drop empty pairs and undefined bounds, so two ranges that mean the same
 *  compare equal and the request body carries no `{}`. */
export function normalizeRanges(ranges: GalleryRanges): GalleryRanges {
  const out: GalleryRanges = {}
  for (const key of GALLERY_MEASURES) {
    const b = ranges[key]
    if (isEmptyBounds(b)) continue
    out[key] = {
      ...(b!.min !== undefined ? { min: b!.min } : {}),
      ...(b!.max !== undefined ? { max: b!.max } : {}),
    }
  }
  return out
}

export function sameRanges(a: GalleryRanges, b: GalleryRanges): boolean {
  const na = normalizeRanges(a)
  const nb = normalizeRanges(b)
  return GALLERY_MEASURES.every(
    (key) => na[key]?.min === nb[key]?.min && na[key]?.max === nb[key]?.max,
  )
}

export function isTypicalNightTrain(ranges: GalleryRanges): boolean {
  return sameRanges(ranges, typicalNightTrainRanges())
}

/** The filter keys the ranges set — what Gallery.vue merges into its own.
 *  Every one scoped to proposals: existing trains are never sieved. */
export function rangesToFilter(ranges: GalleryRanges): Pick<ProposalsFilter, GalleryMeasure> {
  const filter: Pick<ProposalsFilter, GalleryMeasure> = {}
  const clean = normalizeRanges(ranges)
  for (const key of GALLERY_MEASURES) {
    if (clean[key]) filter[key] = { ...clean[key], scope: 'proposal' }
  }
  return filter
}

// --- URL ---------------------------------------------------------------------
// The preset is the default a shared link need not spell out, so it writes
// nothing. Anything else is explicit: each bounded measure as `km=500-2000`
// (an open side empty: `kmh=50-`), and no bounds at all as `typical=0`.

export function rangesToQuery(ranges: GalleryRanges): LocationQueryRaw {
  if (isTypicalNightTrain(ranges)) return {}
  const clean = normalizeRanges(ranges)
  const query: LocationQueryRaw = {}
  for (const key of GALLERY_MEASURES) {
    const b = clean[key]
    if (b) query[QUERY_KEYS[key]] = `${b.min ?? ''}-${b.max ?? ''}`
  }
  if (!Object.keys(query).length) query[TYPICAL_OFF_KEY] = '0'
  return query
}

export function rangesFromQuery(query: LocationQuery): GalleryRanges {
  const ranges: GalleryRanges = {}
  let explicit = false
  for (const key of GALLERY_MEASURES) {
    const raw = query[QUERY_KEYS[key]]
    const value = Array.isArray(raw) ? raw[0] : raw
    if (typeof value !== 'string') continue
    explicit = true
    const bounds = parseBounds(value)
    if (bounds) ranges[key] = bounds
  }
  if (explicit) return ranges
  const typical = Array.isArray(query[TYPICAL_OFF_KEY])
    ? query[TYPICAL_OFF_KEY][0]
    : query[TYPICAL_OFF_KEY]
  return typical === '0' ? {} : typicalNightTrainRanges()
}

function parseBounds(value: string): Bounds | null {
  const dash = value.indexOf('-')
  if (dash < 0) return null
  const min = parseBound(value.slice(0, dash))
  const max = parseBound(value.slice(dash + 1))
  if (min === null && max === null) return null
  return { ...(min !== null ? { min } : {}), ...(max !== null ? { max } : {}) }
}

function parseBound(text: string): number | null {
  if (text === '') return null
  const n = Number(text)
  return Number.isFinite(n) && n >= 0 ? n : null
}
