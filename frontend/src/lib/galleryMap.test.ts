import { describe, expect, test } from 'vitest'
import {
  buildRelationToken,
  parseRelationToken,
  corridorBounds,
  corridorPresenceFilter,
  corridorWidthExpression,
  featureBounds,
  routeForRow,
  routeStopsCollection,
  anchorCollection,
  selectedCountriesCollection,
  stopMarkers,
  CORRIDOR_KINDS,
  CORRIDOR_WIDTH_STOPS,
  type CountryShapesCollection,
  type GalleryStopMarker,
} from './galleryMap'
import type {
  MapCorridorFeature,
  MapCorridorProperties,
  MapLinesSection,
  MapRouteFeature,
  Stop,
} from '@/types/api'

describe('buildRelationToken', () => {
  // The stored token is alphabetical, so the two selects must be interchangeable
  // — this is the whole reason the helper exists rather than a template string.
  test('orders the pair alphabetically regardless of pick order', () => {
    expect(buildRelationToken('DE', 'AT')).toBe('AT__DE')
    expect(buildRelationToken('AT', 'DE')).toBe('AT__DE')
  })

  test('uppercases the codes', () => {
    expect(buildRelationToken('at', 'de')).toBe('AT__DE')
  })

  test('is null until both codes are picked', () => {
    expect(buildRelationToken('AT', null)).toBeNull()
    expect(buildRelationToken(null, 'DE')).toBeNull()
    expect(buildRelationToken(null, null)).toBeNull()
  })

  // A relation always joins two different countries, so "AT__AT" is a token no
  // row can carry — filtering on it would silently return nothing.
  test('is null for a self-pair', () => {
    expect(buildRelationToken('AT', 'AT')).toBeNull()
    expect(buildRelationToken('at', 'AT')).toBeNull()
  })
})

describe('parseRelationToken', () => {
  test('round-trips a built token', () => {
    expect(parseRelationToken(buildRelationToken('DE', 'AT'))).toEqual(['AT', 'DE'])
  })

  test('rejects anything that is not a two-code token', () => {
    // A SINGLE underscore is not the separator — ISO codes never contain one,
    // but a malformed URL param might.
    expect(parseRelationToken('AT_DE')).toBeNull()
    expect(parseRelationToken('AT__DE__FR')).toBeNull()
    expect(parseRelationToken('AT__')).toBeNull()
    expect(parseRelationToken('')).toBeNull()
    expect(parseRelationToken(null)).toBeNull()
    expect(parseRelationToken(undefined)).toBeNull()
  })
})

describe('CORRIDOR_KINDS', () => {
  // Draw order, and the reason the array is ordered at all: proposals are the
  // thing the gallery collects, so they go on top of the trains already there.
  test('draws existing corridors before proposed ones', () => {
    expect(CORRIDOR_KINDS.indexOf('existing')).toBeLessThan(CORRIDOR_KINDS.indexOf('proposed'))
  })
})

describe('corridorPresenceFilter', () => {
  // One feature collection, two layers: each draws only the corridors its own
  // kind actually runs on, so a corridor carrying both is drawn twice.
  test('keeps only corridors carrying that kind of traffic', () => {
    expect(corridorPresenceFilter('proposed')).toEqual(['>', ['get', 'proposal_count'], 0])
    expect(corridorPresenceFilter('existing')).toEqual(['>', ['get', 'existing_count'], 0])
  })
})

describe('corridorWidthExpression', () => {
  // Per-kind counts, not total_count: with both layers on screen, thickness
  // must mean "proposed n times" / "served by n trains", not their sum.
  test("is a MapLibre interpolate over the kind's own count", () => {
    expect(corridorWidthExpression('proposed').slice(0, 3)).toEqual([
      'interpolate',
      ['linear'],
      ['get', 'proposal_count'],
    ])
    expect(corridorWidthExpression('existing').slice(0, 3)).toEqual([
      'interpolate',
      ['linear'],
      ['get', 'existing_count'],
    ])
  })

  // Thickness is the "proposed n times" signal, so the ramp must never dip.
  test('rises monotonically with the count', () => {
    const counts = CORRIDOR_WIDTH_STOPS.map(([count]) => count)
    const widths = CORRIDOR_WIDTH_STOPS.map(([, width]) => width)
    expect([...counts].sort((a, b) => a - b)).toEqual(counts)
    expect([...widths].sort((a, b) => a - b)).toEqual(widths)
  })
})

function props(over: Partial<MapCorridorProperties> = {}): MapCorridorProperties {
  return {
    stop_a: 'a',
    stop_b: 'b',
    proposal_count: 1,
    existing_count: 0,
    total_count: 1,
    avg_margin_eur_per_train_km: null,
    ...over,
  }
}

function corridor(
  coordinates: [number, number][],
  over: Partial<MapCorridorProperties> = {},
): MapCorridorFeature {
  return {
    type: 'Feature',
    geometry: { type: 'LineString', coordinates },
    properties: props(over),
  }
}

function section(features: MapCorridorFeature[]): MapLinesSection {
  return { type: 'FeatureCollection', features }
}

describe('corridorBounds', () => {
  test('spans every vertex of every corridor', () => {
    // Wien → Berlin and Paris → Milano, so the hull is wider than either.
    const bounds = corridorBounds(
      section([
        corridor([
          [16.37, 48.2],
          [13.37, 52.52],
        ]),
        corridor([
          [2.35, 48.86],
          [9.19, 45.46],
        ]),
      ]),
    )
    expect(bounds).toEqual([2.35, 45.46, 16.37, 52.52])
  })

  test('is null when there is nothing to frame', () => {
    expect(corridorBounds(null)).toBeNull()
    expect(corridorBounds(section([]))).toBeNull()
    expect(corridorBounds(section([corridor([])]))).toBeNull()
  })

  // A corridor whose geometry failed to serialise must not collapse the view to
  // null island.
  test('ignores non-finite coordinates', () => {
    const bounds = corridorBounds(
      section([
        corridor([
          [Number.NaN, Number.NaN],
          [16.37, 48.2],
          [13.37, 52.52],
        ]),
      ]),
    )
    expect(bounds).toEqual([13.37, 48.2, 16.37, 52.52])
  })
})

function route(
  coordinates: [number, number][][] | null,
  over: Partial<MapRouteFeature['properties']> = {},
): MapRouteFeature {
  return {
    type: 'Feature',
    geometry: coordinates ? { type: 'MultiLineString', coordinates } : null,
    properties: {
      source: 'proposal',
      proposal_id: 1,
      proposal_version: 1,
      route_id: null,
      ...over,
    },
  }
}

describe('routeForRow', () => {
  const features = [
    route([
      [
        [13.37, 52.52],
        [16.37, 48.2],
      ],
    ]),
    route([[[2.35, 48.86]]], { proposal_id: 2 }),
    route([[[9.19, 45.46]]], {
      source: 'existing',
      proposal_id: null,
      proposal_version: null,
      route_id: '73',
    }),
  ]

  test('finds a proposal row by numeric id', () => {
    expect(routeForRow(features, { kind: 'proposal', id: 2 })?.properties.proposal_id).toBe(2)
  })

  test('finds an existing row by string route_id', () => {
    expect(routeForRow(features, { kind: 'existing', id: '73' })?.properties.route_id).toBe('73')
  })

  // Proposal ids and ONTD route_ids are unrelated id spaces — 1 must never
  // match "1", in either direction.
  test('never matches across the two id spaces', () => {
    expect(routeForRow(features, { kind: 'existing', id: '1' })).toBeNull()
    expect(routeForRow(features, { kind: 'proposal', id: 73 })).toBeNull()
  })

  // The row is on this page but its routing failed, so there is nothing to
  // draw — must read the same as "not on this page" to the caller.
  test('is null for a row whose geometry is null', () => {
    const withoutGeometry = [route(null, { proposal_id: 9 })]
    expect(routeForRow(withoutGeometry, { kind: 'proposal', id: 9 })).toBeNull()
  })

  test('is null for a row that is not on this page, or no row at all', () => {
    expect(routeForRow(features, { kind: 'proposal', id: 999 })).toBeNull()
    expect(routeForRow(features, null)).toBeNull()
    expect(routeForRow([], { kind: 'proposal', id: 1 })).toBeNull()
  })
})

describe('featureBounds', () => {
  // Corridors are LineStrings, routes MultiLineStrings; the same fit path
  // frames both, so it has to walk one extra level for the latter.
  test('frames a MultiLineString route across all its parts', () => {
    const bounds = featureBounds([
      route([
        [
          [13.37, 52.52],
          [16.37, 48.2],
        ],
        [
          [2.35, 48.86],
          [9.19, 45.46],
        ],
      ]),
    ])
    expect(bounds).toEqual([2.35, 45.46, 16.37, 52.52])
  })

  test('skips features with no geometry', () => {
    expect(featureBounds([route(null)])).toBeNull()
    expect(
      featureBounds([
        route(null),
        route([
          [
            [1, 2],
            [3, 4],
          ],
        ]),
      ]),
    ).toEqual([1, 2, 3, 4])
  })
})

// --- Stops, pins and countries ------------------------------------------------

const stop = (stop_id: string, name: string, lon: number, lat: number): Stop =>
  ({ stop_id, name, lon, lat }) as Stop

const stopsById = new Map(
  [
    stop('DE:BER', 'Berlin Hbf', 13.37, 52.52),
    stop('DE:FRA', 'Frankfurt (Main) Hbf', 8.66, 50.11),
    stop('FR:PAR', 'Paris Est', 2.36, 48.88),
  ].map((s) => [s.stop_id, s]),
)

describe('stopMarkers', () => {
  test('keeps travel order and skips ids the catalogue no longer carries', () => {
    const markers = stopMarkers(['FR:PAR', 'XX:GONE', 'DE:FRA', 'DE:BER'], stopsById)
    expect(markers.map((m) => m.stop_id)).toEqual(['FR:PAR', 'DE:FRA', 'DE:BER'])
    expect(markers[0]).toEqual({ stop_id: 'FR:PAR', name: 'Paris Est', lon: 2.36, lat: 48.88 })
  })

  test('is empty while the store is empty', () => {
    expect(stopMarkers(['DE:BER'], new Map())).toEqual([])
  })
})

const markers: GalleryStopMarker[] = stopMarkers(['DE:BER', 'DE:FRA', 'FR:PAR'], stopsById)

describe('routeStopsCollection', () => {
  test('flags origin and terminus as endpoints and carries the source', () => {
    const fc = routeStopsCollection(markers, 'existing')
    expect(fc.features.map((f) => f.properties.endpoint)).toEqual([true, false, true])
    expect(fc.features.every((f) => f.properties.source === 'existing')).toBe(true)
    expect(fc.features[1].geometry).toEqual({ type: 'Point', coordinates: [8.66, 50.11] })
  })

  // The searched station carries a pin already; a dot underneath would blur it.
  test('leaves out the stops that are pinned', () => {
    const fc = routeStopsCollection(markers, 'proposal', new Set(['DE:FRA']))
    expect(fc.features.map((f) => f.properties.stop_id)).toEqual(['DE:BER', 'FR:PAR'])
  })

  test('a single stop is its own endpoint', () => {
    expect(
      routeStopsCollection(markers.slice(0, 1), 'proposal').features[0].properties.endpoint,
    ).toBe(true)
  })
})

describe('anchorCollection', () => {
  test('one point per searched station, named', () => {
    const fc = anchorCollection(markers.slice(1, 2))
    expect(fc.features).toHaveLength(1)
    expect(fc.features[0].properties).toEqual({ stop_id: 'DE:FRA', name: 'Frankfurt (Main) Hbf' })
  })
})

const shapes: CountryShapesCollection = {
  type: 'FeatureCollection',
  features: ['AT', 'DE'].map((country) => ({
    type: 'Feature',
    properties: { country },
    geometry: {
      type: 'MultiPolygon',
      coordinates: [
        [
          [
            [0, 0],
            [1, 0],
            [1, 1],
            [0, 0],
          ],
        ],
      ],
    },
  })),
}

describe('selectedCountriesCollection', () => {
  test('ranks the picks in order, so the second of a pair draws lighter', () => {
    const fc = selectedCountriesCollection(shapes, ['DE', 'AT'])
    expect(fc.features.map((f) => f.properties)).toEqual([
      { country: 'DE', rank: 0 },
      { country: 'AT', rank: 1 },
    ])
  })

  test('tolerates lower-case codes and drops codes without a shape', () => {
    const fc = selectedCountriesCollection(shapes, ['de', 'UNK'])
    expect(fc.features.map((f) => f.properties.country)).toEqual(['DE'])
  })

  test('is empty before the shapes have loaded', () => {
    expect(selectedCountriesCollection(null, ['DE']).features).toEqual([])
  })
})

describe('featureBounds over mixed grains', () => {
  test('frames points and polygons together with lines', () => {
    const bounds = featureBounds([
      ...anchorCollection(markers.slice(0, 1)).features,
      ...selectedCountriesCollection(shapes, ['AT']).features,
    ])
    expect(bounds).toEqual([0, 0, 13.37, 52.52])
  })
})
