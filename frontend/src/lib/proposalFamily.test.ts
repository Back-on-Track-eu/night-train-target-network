import { describe, expect, it } from 'vitest'
import { inflateRoute, isOk, memberFailure, memberKey, routeFor } from './proposalFamily'
import type { CompactRoute, FamilyDocument, FamilyMemberError } from '@/types/api'

const stop = (id: string, dep: number | null, arr: number | null) => ({
  stop_id: id,
  stop_name: id.toUpperCase(),
  country_code: 'DE',
  lat: 52,
  lon: 13,
  arrival_time_min: arr,
  departure_time_min: dep,
  auto_added: false,
})

const compactRoute: CompactRoute = {
  route_id: 'R1',
  scenario_id: 1,
  schedule: { seasonal_schedules: [] },
  parkings: [],
  shuntings: [],
  trip_pairs: [
    {
      composition_id: 'NEW-BAL-7',
      outbound: {
        trip_id: 'R1_D0_T1',
        direction: 0,
        general_parameters: { trip_km: 500 },
        stops: [stop('a', 1200, null), stop('b', 1300, 1290), stop('c', null, 1500)],
        segments: [
          { from: 0, to: 1, geometry_id: 'g:1', country_distance_shares: { DE: 1 } },
          {
            from: 1,
            to: 2,
            geometry_id: 'g:2',
            country_distance_shares: { DE: 1 },
            addon_time_min: 5,
          },
        ],
      },
      return_trip: {
        trip_id: 'R1_D1_T1',
        direction: 1,
        general_parameters: { trip_km: 500 },
        stops: [stop('c', 1200, null), stop('b', 1310, 1300), stop('a', null, 1500)],
        segments: [
          { from: 0, to: 1, geometry_id: 'g:3', country_distance_shares: { DE: 1 } },
          { from: 1, to: 2, geometry_id: 'g:1', country_distance_shares: { DE: 1 } },
        ],
      },
    },
  ],
}

const document: FamilyDocument = {
  family_key: 'sha256:x',
  route_builder_version: '0.9.34',
  calc_version: '0.9.26',
  request: { stops: ['a', 'b', 'c'] },
  axes: { scenario_variants: [], compositions: ['NEW-BAL-7'] },
  presented: { scenario_variant_id: 1, composition_id: 'NEW-BAL-7' },
  geometries: {
    'g:1': [
      [13, 52],
      [14, 52],
    ],
    'g:2': [
      [14, 52],
      [15, 52],
    ],
    'g:3': [
      [15, 52],
      [14, 52],
    ],
  },
  routes: { 'r:1:NEW-BAL-7': compactRoute },
  members: [
    {
      scenario_variant_id: 1,
      composition_id: 'NEW-BAL-7',
      status: 'ok',
      route_ref: 'r:1:NEW-BAL-7',
      summary: { co2_savings_t_per_year: 1 },
    },
  ],
  stats: {
    n_members: 1,
    n_ok: 1,
    n_error: 0,
    n_routes: 1,
    n_geometries: 3,
    elapsed_s: 0.1,
    cache_hit: false,
  },
}

describe('memberKey', () => {
  it('is the variant and the composition', () => {
    expect(memberKey(7, 'NEW-BAL-7')).toBe('7:NEW-BAL-7')
  })
})

describe('inflateRoute', () => {
  const route = inflateRoute(document, compactRoute)

  it('inlines both ends of every segment from the trip stop list', () => {
    const out = route.trip_pairs[0].outbound
    expect(out.segments.map((s) => [s.from_stop.stop_id, s.to_stop.stop_id])).toEqual([
      ['a', 'b'],
      ['b', 'c'],
    ])
    // The intermediate stop is the SAME object on both sides — as the
    // backend's route_to_dict() shares it — so times read identically.
    expect(out.segments[0].to_stop).toBe(out.segments[1].from_stop)
    expect(out.segments[0].to_stop.arrival_time_min).toBe(1290)
  })

  it('keeps every other segment and trip field verbatim', () => {
    const out = route.trip_pairs[0].outbound
    expect(out.segments[1].addon_time_min).toBe(5)
    expect(out.segments[1].geometry_id).toBe('g:2')
    expect(out.general_parameters).toEqual({ trip_km: 500 })
    expect(out.trip_id).toBe('R1_D0_T1')
    expect(route.route_id).toBe('R1')
    expect(route.scenario_id).toBe(1)
  })

  it('rebuilds geometries[] from the pool, once per distinct id', () => {
    const ids = route.geometries.map((g) => g.id).sort()
    expect(ids).toEqual(['g:1', 'g:2', 'g:3'])
    expect(route.geometries.find((g) => g.id === 'g:1')?.coords).toEqual([
      [13, 52],
      [14, 52],
    ])
  })

  it('does not touch the compact route it was given', () => {
    expect('from_stop' in compactRoute.trip_pairs[0].outbound.segments[0]).toBe(false)
  })
})

describe('routeFor / isOk', () => {
  it('resolves an ok member to its route', () => {
    const member = document.members[0]
    expect(isOk(member)).toBe(true)
    if (isOk(member)) expect(routeFor(document, member)).toBe(compactRoute)
  })
  it('is false for undefined and for an error member', () => {
    expect(isOk(undefined)).toBe(false)
    expect(
      isOk({
        scenario_variant_id: 1,
        composition_id: 'x',
        status: 'error',
        error: 'routing_error',
        message: 'no',
      }),
    ).toBe(false)
  })
})

describe('memberFailure', () => {
  const error = (code: string): FamilyMemberError => ({
    scenario_variant_id: 1,
    composition_id: 'NEW-BAL-7',
    status: 'error',
    error: code,
    message: 'Stop x supports 1520 mm only',
  })

  it("maps the user's-input codes to bad_input with the backend's message", () => {
    for (const code of ['gauge_mismatch', 'routing_error', 'domain_error']) {
      expect(memberFailure(error(code))).toEqual({
        kind: 'bad_input',
        status: 422,
        slug: code,
        message: 'Stop x supports 1520 mm only',
      })
    }
  })

  it("maps the deployment's missing graph to unavailable", () => {
    expect(memberFailure(error('routing_graph_not_configured'))).toEqual({
      kind: 'unavailable',
      status: 503,
      slug: 'routing_graph_not_configured',
    })
  })

  it('treats an unknown code as a server failure', () => {
    expect(memberFailure(error('calc_error'))).toEqual({
      kind: 'server',
      status: 500,
      slug: 'calc_error',
    })
  })
})
