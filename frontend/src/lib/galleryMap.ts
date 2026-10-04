// Pure helpers for the gallery's corridor map and its relation filter. Kept out
// of Gallery.vue / GalleryMap.vue so they can be unit-tested (the frontend test
// setup never mounts components — see the project's testing note).

import type { MapLinesSection, MapRouteFeature, ProposalSourceKind, Stop } from '@/types/api'

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

/** The two kinds of traffic a corridor can carry, in DRAW ORDER: existing
 *  first, proposals last and therefore on top. A corridor carrying both is no
 *  longer resolved to one state — it is drawn twice, once per kind, so the
 *  suggestion the gallery exists to collect always sits in front of the train
 *  that already runs there. */
export const CORRIDOR_KINDS = ['existing', 'proposed'] as const
export type CorridorKind = (typeof CORRIDOR_KINDS)[number]

export const CORRIDOR_COLORS: Record<CorridorKind, string> = {
  /** At least one real ONTD train runs here — orange (blue/orange is the
   *  colour-vision-safe pair). */
  existing: '#e07b39',
  /** Proposals run here — brand blue. */
  proposed: '#2271b3',
}

/** The count each kind's thickness and stacking read from. Per-kind rather
 *  than `total_count`: the two layers now share the map, so a corridor
 *  proposed twice must be two proposals thick, not two-plus-its-trains. */
export const CORRIDOR_COUNT_PROPERTIES: Record<CorridorKind, string> = {
  existing: 'existing_count',
  proposed: 'proposal_count',
}

/** Below 1 so crossing corridors still read as two lines. The proposal layer
 *  is the more opaque of the two: where both run, it has to stay legible over
 *  the orange underneath it rather than blending into it. */
export const CORRIDOR_OPACITY: Record<CorridorKind, number> = {
  existing: 0.65,
  proposed: 0.95,
}

/** Whether a corridor carries this kind of traffic at all — the filter that
 *  splits one feature collection across the two layers. */
export function corridorPresenceFilter(kind: CorridorKind): unknown[] {
  return ['>', ['get', CORRIDOR_COUNT_PROPERTIES[kind]], 0]
}

/**
 * How the corridors recede while a card is hovered: receded rather than hidden
 * (decided 2026-10-04), so the isolated route keeps its context — the reader
 * still sees where the rest of the result set runs — but in a neutral grey at
 * low opacity rather than their own colours dimmed. Dimming alone did not
 * work (David, 2026-10-04): with ~1,000 proposals the blue corridors overdraw
 * each other back to full strength wherever they share track, and the hovered
 * route, drawn in the same blue, vanished into them. Grey leaves hue to the one
 * route that matters; the opacity is flat for both kinds because, receded,
 * neither has anything left to say about which traffic it carried.
 */
export const CORRIDOR_RECEDED_COLOR = '#aeb6c0'
export const CORRIDOR_RECEDED_OPACITY = 0.16

/** Width of the isolated route while a card is hovered. Flat, because with one
 *  route on screen the count ramp has nothing to compare against — varying
 *  thickness along a single itinerary would imply a difference that isn't there. */
export const CORRIDOR_ISOLATED_WIDTH = 3.5

/** The white casing drawn under the isolated route: a band `ROUTE_CASING_PAD`
 *  px wider than the route on each side, so the line keeps a clear edge where
 *  it runs over the receded corridors and the basemap's own railways. */
export const ROUTE_CASING_COLOR = '#ffffff'
export const ROUTE_CASING_PAD = 2.5
export const ROUTE_CASING_WIDTH = CORRIDOR_ISOLATED_WIDTH + 2 * ROUTE_CASING_PAD

/**
 * Width ramp keyed on a corridor count. Deliberately ABSOLUTE rather than scaled to
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

/** `line-width` as a MapLibre interpolate expression over the kind's own
 *  count. Both layers share the ramp, so a corridor proposed five times and
 *  one served by five trains are the same weight in their own colour. */
export function corridorWidthExpression(kind: CorridorKind): unknown[] {
  return [
    'interpolate',
    ['linear'],
    ['get', CORRIDOR_COUNT_PROPERTIES[kind]],
    ...CORRIDOR_WIDTH_STOPS.flatMap(([count, width]) => [count, width]),
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

// --- Stops and stations on the map -------------------------------------------

/** A stop placed on the map: the row's own stops while its card is hovered,
 *  or the station(s) the active search targets. */
export interface GalleryStopMarker {
  stop_id: string
  name: string
  lon: number
  lat: number
  /** A searched CITY rather than a station: pinned at the city's centroid
   *  and drawn a step larger. Its id is not a stop id, so the hovered
   *  route's own stops in that city keep their dots. */
  city?: boolean
}

/** The searched station's pin — sapphire, the app's own ground colour, so it
 *  reads as "yours" against both route colours. */
export const ANCHOR_COLOR = '#1d1e33'
export const ANCHOR_HALO = '#ffffff'

/** Circle radii in px: the hovered route's stops, its two endpoints a step
 *  larger, and the searched station's pin above both. */
export const STOP_RADIUS = 4.5
export const STOP_END_RADIUS = 6
export const ANCHOR_RADIUS = 7.5
export const ANCHOR_CITY_RADIUS = 9

/** A selected country's tint. Its own hue — teal, away from both route
 *  colours — because a blue outline read as one more proposal line (David,
 *  2026-10-04): the country is an area, and its colour must not compete
 *  with anything drawn as a line. */
export const COUNTRY_COLOR = '#2a9d8f'

/** Fill opacity of a selected country: the first pick, and the second of a
 *  country pair a shade lighter so the two stay tellable apart. */
export const COUNTRY_FILL_OPACITY: readonly [first: number, second: number] = [0.22, 0.12]

/**
 * Resolve stop ids against the stops store, keeping travel order and skipping
 * ids the catalogue no longer carries (a retired stop on an old proposal) —
 * one unknown id must not cost the row its other markers.
 */
export function stopMarkers(
  stopIds: readonly string[],
  stopsById: Map<string, Stop>,
): GalleryStopMarker[] {
  const markers: GalleryStopMarker[] = []
  for (const id of stopIds) {
    const stop = stopsById.get(id)
    if (stop) markers.push({ stop_id: id, name: stop.name, lon: stop.lon, lat: stop.lat })
  }
  return markers
}

export interface StopPointProperties {
  stop_id: string
  name: string
  /** Origin or terminus — drawn larger and labelled in bold. */
  endpoint: boolean
  source: ProposalSourceKind
}

export interface PointFeature<P> {
  type: 'Feature'
  geometry: { type: 'Point'; coordinates: [number, number] }
  properties: P
}

export interface PointCollection<P> {
  type: 'FeatureCollection'
  features: PointFeature<P>[]
}

const pointFeature = <P>(marker: GalleryStopMarker, properties: P): PointFeature<P> => ({
  type: 'Feature',
  geometry: { type: 'Point', coordinates: [marker.lon, marker.lat] },
  properties,
})

/**
 * The hovered row's stops as point features. `exclude` is the searched
 * station(s): they already carry a pin, and a dot underneath would only
 * blur it.
 */
export function routeStopsCollection(
  stops: readonly GalleryStopMarker[],
  source: ProposalSourceKind,
  exclude: ReadonlySet<string> = new Set(),
): PointCollection<StopPointProperties> {
  const last = stops.length - 1
  return {
    type: 'FeatureCollection',
    features: stops.flatMap((stop, i) =>
      exclude.has(stop.stop_id)
        ? []
        : [
            pointFeature(stop, {
              stop_id: stop.stop_id,
              name: stop.name,
              endpoint: i === 0 || i === last,
              source,
            }),
          ],
    ),
  }
}

export interface AnchorPointProperties {
  stop_id: string
  name: string
  city: boolean
}

/** The searched station(s) or city/cities as point features for the pin layers. */
export function anchorCollection(
  stops: readonly GalleryStopMarker[],
): PointCollection<AnchorPointProperties> {
  return {
    type: 'FeatureCollection',
    features: stops.map((stop) =>
      pointFeature(stop, { stop_id: stop.stop_id, name: stop.name, city: stop.city ?? false }),
    ),
  }
}

// --- Countries ---------------------------------------------------------------

/** One land outline per country from `assets/country_shapes.json` (built by
 *  `scripts/build_country_shapes.mjs`). LAND, not the backend's EEZ union: the
 *  gallery filters on the maritime attribution and draws the coastline. */
export interface CountryShapeFeature {
  type: 'Feature'
  geometry: { type: 'MultiPolygon'; coordinates: [number, number][][][] }
  properties: { country: string }
}

export interface CountryShapesCollection {
  type: 'FeatureCollection'
  features: CountryShapeFeature[]
}

export interface SelectedCountryProperties {
  country: string
  /** Position in the pick order: 0 for the (first) country, 1 for the second
   *  of a pair — the fill opacity reads from it. */
  rank: number
}

export type SelectedCountryFeature = Omit<CountryShapeFeature, 'properties'> & {
  properties: SelectedCountryProperties
}

/**
 * The selected country codes' outlines, ranked in pick order. A code without
 * a shape (an unattributed "UNK", or a country outside the asset) is simply
 * absent — the filter still applies, there is just nothing to tint.
 */
export function selectedCountriesCollection(
  shapes: CountryShapesCollection | null,
  codes: readonly string[],
): { type: 'FeatureCollection'; features: SelectedCountryFeature[] } {
  const features: SelectedCountryFeature[] = []
  if (shapes) {
    codes.forEach((code, rank) => {
      const shape = shapes.features.find((f) => f.properties.country === code.toUpperCase())
      if (shape)
        features.push({ ...shape, properties: { country: shape.properties.country, rank } })
    })
  }
  return { type: 'FeatureCollection', features }
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

type AnyGeometry =
  | { type: 'Point'; coordinates: [number, number] }
  | { type: 'LineString'; coordinates: [number, number][] }
  | { type: 'MultiLineString'; coordinates: [number, number][][] }
  | { type: 'Polygon'; coordinates: [number, number][][] }
  | { type: 'MultiPolygon'; coordinates: [number, number][][][] }

interface AnyFeature {
  geometry: AnyGeometry | null
}

/** Every vertex of a geometry, whatever its nesting — the one walker all the
 *  bounds helpers share. */
function* vertices(geometry: AnyGeometry): Generator<[number, number]> {
  switch (geometry.type) {
    case 'Point':
      yield geometry.coordinates
      break
    case 'LineString':
      yield* geometry.coordinates
      break
    case 'MultiLineString':
    case 'Polygon':
      for (const line of geometry.coordinates) yield* line
      break
    case 'MultiPolygon':
      for (const polygon of geometry.coordinates) for (const ring of polygon) yield* ring
      break
  }
}

/** [west, south, east, north] over every vertex, or null when there is nothing
 *  framable. Accepts every grain the map draws — corridor LineStrings, route
 *  MultiLineStrings, stop Points and country MultiPolygons — and a null
 *  geometry on any of them. */
export function featureBounds(
  features: readonly AnyFeature[],
): [number, number, number, number] | null {
  let west = Infinity
  let south = Infinity
  let east = -Infinity
  let north = -Infinity

  for (const feature of features) {
    if (!feature.geometry) continue
    for (const [lon, lat] of vertices(feature.geometry)) {
      if (!Number.isFinite(lon) || !Number.isFinite(lat)) continue
      if (lon < west) west = lon
      if (lon > east) east = lon
      if (lat < south) south = lat
      if (lat > north) north = lat
    }
  }
  return west === Infinity ? null : [west, south, east, north]
}

export function corridorBounds(
  section: MapLinesSection | null,
): [number, number, number, number] | null {
  return featureBounds(section?.features ?? [])
}
