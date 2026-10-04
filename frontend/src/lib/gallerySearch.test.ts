import { describe, expect, test } from 'vitest'
import {
  activePicks,
  anchorStopIds,
  cityOptions,
  searchFilter,
  type CityOption,
  type GallerySearchPicks,
} from './gallerySearch'
import type { Stop } from '@/types/api'

const stop = (
  stop_id: string,
  name: string,
  cc: string,
  lon: number,
  lat: number,
  city: { osm_id: number | null; name: string; names: Record<string, string> } | null,
): Stop => ({ stop_id, name, country_code: cc, lon, lat, city }) as unknown as Stop

const berlin = { osm_id: 240109189, name: 'Berlin', names: { en: 'Berlin', de: 'Berlin' } }
const wien = { osm_id: 17328659, name: 'Wien', names: { en: 'Vienna', de: 'Wien' } }
const stops: Stop[] = [
  stop('DE:BER', 'Berlin Hbf', 'DE', 13.37, 52.52, berlin),
  stop('DE:BSK', 'Berlin Südkreuz', 'DE', 13.37, 52.48, berlin),
  stop('AT:WIE', 'Wien Hbf', 'AT', 16.38, 48.19, wien),
  stop('DE:GOE', 'Göttingen', 'DE', 9.93, 51.54, null),
  stop('XX:NOID', 'Nowhere', 'XX', 0, 0, { osm_id: null, name: 'Nowhere', names: {} }),
]

describe('cityOptions', () => {
  test('groups stops by city, names in the UI locale, centroid of the stops', () => {
    const cities = cityOptions(stops, 'en')
    expect(cities.map((c) => c.name)).toEqual(['Berlin', 'Vienna'])
    const b = cities[0]
    expect(b.osm_id).toBe(240109189)
    expect(b.stop_ids).toEqual(['DE:BER', 'DE:BSK'])
    expect(b.country_code).toBe('DE')
    expect(b.lat).toBeCloseTo(52.5, 5)
    expect(b.names.de).toBe('Berlin')
  })

  // A stop without a resolved city (a rural halt) or without an OSM id cannot
  // be searched as a city; it stays reachable as a station.
  test('skips stops without a city or without an OSM id', () => {
    const cities = cityOptions(stops, 'de')
    expect(cities.flatMap((c) => c.stop_ids)).not.toContain('DE:GOE')
    expect(cities.flatMap((c) => c.stop_ids)).not.toContain('XX:NOID')
  })

  test('falls back through English to the local name', () => {
    expect(cityOptions(stops, 'it').map((c) => c.name)).toEqual(['Berlin', 'Vienna'])
  })
})

const [cityBerlin, cityWien] = cityOptions(stops, 'de') as [CityOption, CityOption]

const picks = (over: Partial<GallerySearchPicks>): GallerySearchPicks => ({
  tab: 'station',
  kind: 'via',
  stops: [null, null],
  cities: [null, null],
  countries: [null, null],
  ...over,
})

describe('activePicks', () => {
  test('reads one slot for via and both for fromTo, dropping empties', () => {
    const p = picks({ kind: 'via', countries: ['AT', 'DE'] })
    expect(activePicks(p, (x) => x.countries)).toEqual(['AT'])
    expect(activePicks({ ...p, kind: 'fromTo' }, (x) => x.countries)).toEqual(['AT', 'DE'])
    expect(
      activePicks({ ...p, kind: 'fromTo', countries: [null, 'DE'] }, (x) => x.countries),
    ).toEqual(['DE'])
  })
})

describe('searchFilter', () => {
  test('station via → stop_ids list; from→to → containment', () => {
    expect(searchFilter(picks({ stops: [stops[0], null] }))).toEqual({ stop_ids: ['DE:BER'] })
    expect(searchFilter(picks({ kind: 'fromTo', stops: [stops[0], stops[2]] }))).toEqual({
      stop_ids: { values: ['DE:BER', 'AT:WIE'], mode: 'all' },
    })
  })

  // One pick is the same query whatever the kind — 'all' over one value is
  // 'any' — so a half-filled pair sends the plain list.
  test('a half-filled from→to is a via search', () => {
    expect(searchFilter(picks({ kind: 'fromTo', stops: [null, stops[2]] }))).toEqual({
      stop_ids: ['AT:WIE'],
    })
  })

  test('city via → cities list; from→to → every city', () => {
    expect(searchFilter(picks({ tab: 'city', cities: [cityBerlin, null] }))).toEqual({
      cities: [240109189],
    })
    expect(
      searchFilter(picks({ tab: 'city', kind: 'fromTo', cities: [cityBerlin, cityWien] })),
    ).toEqual({ cities: { values: [240109189, 17328659], mode: 'all' } })
  })

  test('country via → countries; from→to → the stored relation token', () => {
    expect(searchFilter(picks({ tab: 'country', countries: ['DE', null] }))).toEqual({
      countries: ['DE'],
    })
    expect(
      searchFilter(picks({ tab: 'country', kind: 'fromTo', countries: ['DE', 'AT'] })),
    ).toEqual({ country_relations: ['AT__DE'] })
  })

  // A self-pair cannot name a relation; it is the single country.
  test('the same country twice is one country', () => {
    expect(
      searchFilter(picks({ tab: 'country', kind: 'fromTo', countries: ['DE', 'DE'] })),
    ).toEqual({ countries: ['DE'] })
  })

  test('nothing picked contributes nothing', () => {
    expect(searchFilter(picks({}))).toEqual({})
    expect(searchFilter(picks({ tab: 'city' }))).toEqual({})
    expect(searchFilter(picks({ tab: 'country' }))).toEqual({})
  })
})

describe('anchorStopIds', () => {
  test('stations anchor themselves, a city anchors all its stops, a country none', () => {
    expect(anchorStopIds(picks({ kind: 'fromTo', stops: [stops[0], stops[2]] }))).toEqual([
      'DE:BER',
      'AT:WIE',
    ])
    expect(anchorStopIds(picks({ tab: 'city', cities: [cityBerlin, null] }))).toEqual([
      'DE:BER',
      'DE:BSK',
    ])
    expect(anchorStopIds(picks({ tab: 'country', countries: ['DE', null] }))).toEqual([])
  })
})
