// Pure helpers for the gallery's corridor map and its relation filter. Kept out
// of Gallery.vue / GalleryMap.vue so they can be unit-tested (the frontend test
// setup never mounts components — see the project's testing note).

import type { MapCorridorFeature, MapLinesSection, MapRouteFeature } from '@/types/api'

// --- Country relations -------------------------------------------------------

/** The separator the backend stores country relations with: "AT__DE", two ISO
 *  codes joined by a DOUBLE underscore (backend/api/README.md §7.1). */
const RELATION_SEPARATOR = '__'

/**
 * The `country_relations` token for a pair of ISO country codes. The stored
 * token is alphabetically ordered and direction-agnostic, so the two selects
 * are interchangeable — picking AT/DE and DE/AT must produce the same filter.
 *
 * Returns null when the pair cannot name a relation: either code missing, or
 * both the same (a relation always joins two DIFFERENT countries, so a
 * self-pair would filter for a token that exists on no row).
 */
export function buildRelationToken(a: string | null, b: string | null): string | null {
  if (!a || !b) return null
  const from = a.toUpperCase()
  const to = b.toUpperCase()
  if (from === to) return null
  return [from, to].sort().join(RELATION_SEPARATOR)
}

/** Split a stored token back into its two codes; null if it isn't one. */
export function parseRelationToken(token: string | null | undefined): [string, string] | null {
  if (!token) return null
  const parts = token.split(RELATION_SEPARATOR)
  if (parts.length !== 2 || !parts[0] || !parts[1]) return null
  return [parts[0], parts[1]]
}

// --- Corridor styling --------------------------------------------------------

/** The two states a corridor can be in. Deliberately only two: a corridor that
 *  is both proposed AND already served reads as EXISTING, because "a train
 *  already runs here" is a fact about the corridor that a proposal on top of it
 *  does not change — and it is the signal the map exists to show. */
export const CORRIDOR_COLORS = {
  /** Only proposals run here — brand blue. */
  proposed: '#2271b3',
  /** At least one real ONTD train runs here — orange (blue/orange is the
   *  colour-vision-safe pair). */
  existing: '#e07b39',
} as const

/** Width of the isolated route while a card is hovered. Flat, because with one
 *  route on screen the count ramp has nothing to compare against — varying
 *  thickness along a single itinerary would imply a difference that isn't there. */
export const CORRIDOR_ISOLATED_WIDTH = 3

/**
 * Width ramp keyed on `total_count`. Deliberately ABSOLUTE rather than scaled to
 * the current result set: a corridor proposed five times must look the same
 * whether the gallery is filtered or not, otherwise thickness would silently
 * re-mean itself on every query. Saturates at 20 so one very popular corridor
 * cannot flatten the rest of the ramp.
 */
export const CORRIDOR_WIDTH_STOPS: readonly (readonly [count: number, width: number])[] = [
  [1, 1.6],
  [2, 2.6],
  [5, 4],
  [10, 6],
  [20, 8],
]

/** `line-width` as a MapLibre interpolate expression over total_count. */
export function corridorWidthExpression(): unknown[] {
  return [
    'interpolate',
    ['linear'],
    ['get', 'total_count'],
    ...CORRIDOR_WIDTH_STOPS.flatMap(([count, width]) => [count, width]),
  ]
}

/** `line-color` as a MapLibre case expression: any existing service wins. */
export function corridorColorExpression(): unknown[] {
  return [
    'case',
    ['>', ['get', 'existing_count'], 0],
    CORRIDOR_COLORS.existing,
    CORRIDOR_COLORS.proposed,
  ]
}

/**
 * `line-color` for the isolated single route, driven off the feature's own
 * `source` rather than set imperatively per hover. That matters: setting the
 * paint property alongside the data let MapLibre render a frame with the new
 * geometry and the previous colour, so an orange existing route flashed blue
 * for the length of the fly-to.
 */
export function routeColorExpression(): unknown[] {
  return [
    'case',
    ['==', ['get', 'source'], 'existing'],
    CORRIDOR_COLORS.existing,
    CORRIDOR_COLORS.proposed,
  ]
}

/** Dash pattern for a route drawn from the ONTD catalogue's straight-line
 *  fallback rather than real routing. In line-width units, so it scales with
 *  CORRIDOR_ISOLATED_WIDTH. */
export const ROUTE_DASH_PATTERN = [2, 1.5]

/** Split the isolated-route layers: anything not explicitly unrouted draws
 *  solid (proposals carry null, and a proposal is routed by construction). */
export const ROUTED_FILTER = ['!=', ['get', 'geometry_routed'], false]
export const UNROUTED_FILTER = ['==', ['get', 'geometry_routed'], false]

/**
 * Which state a corridor is in. Shared by the legend and by the tests that pin
 * the expression above to the same rule.
 */
export function corridorState(props: {
  proposal_count: number
  existing_count: number
}): keyof typeof CORRIDOR_COLORS {
  return props.existing_count > 0 ? 'existing' : 'proposed'
}

// --- Rows on a corridor ------------------------------------------------------

/** Which gallery row a corridor belongs to. Proposals are keyed by numeric id,
 *  existing (ONTD) routes by their string route_id — the two id spaces are
 *  unrelated, hence the discriminated union rather than a bare id. */
export type GalleryRowRef = { kind: 'proposal'; id: number } | { kind: 'existing'; id: string }

/** The row's own route from the `map_routes` section, or null when this page
 *  carries no geometry for it — either the row is not on a loaded page, or its
 *  routing failed (ONTD routes with `geom_simplified` NULL come back as a
 *  feature with a null geometry, which is why the geometry is checked too). */
export function routeForRow(
  features: MapRouteFeature[],
  row: GalleryRowRef | null,
): MapRouteFeature | null {
  if (!row) return null
  const match = features.find((f) =>
    row.kind === 'proposal'
      ? f.properties.source === 'proposal' && f.properties.proposal_id === row.id
      : f.properties.source === 'existing' && f.properties.route_id === row.id,
  )
  return match?.geometry ? match : null
}

// --- Bounds ------------------------------------------------------------------

/** [west, south, east, north] over every vertex, or null when there is nothing
 *  framable. Accepts both grains the map draws: corridor features carry a
 *  LineString, route features a MultiLineString, and either may be null. */
export function featureBounds(
  features: (MapCorridorFeature | MapRouteFeature)[],
): [number, number, number, number] | null {
  let west = Infinity
  let south = Infinity
  let east = -Infinity
  let north = -Infinity

  const extend = ([lon, lat]: [number, number]) => {
    if (!Number.isFinite(lon) || !Number.isFinite(lat)) return
    if (lon < west) west = lon
    if (lon > east) east = lon
    if (lat < south) south = lat
    if (lat > north) north = lat
  }

  for (const feature of features) {
    const geometry = feature.geometry
    if (!geometry) continue
    if (geometry.type === 'LineString') geometry.coordinates.forEach(extend)
    else for (const line of geometry.coordinates) line.forEach(extend)
  }
  return west === Infinity ? null : [west, south, east, north]
}

export function corridorBounds(
  section: MapLinesSection | null,
): [number, number, number, number] | null {
  return featureBounds(section?.features ?? [])
}
