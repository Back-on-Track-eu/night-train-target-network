import { describe, expect, test } from 'vitest'
import { EMPTY_SEED, seedFromQuery, seedToQuery, resolvePrefillStops } from './proposalPrefill'
import { cityOptions } from './gallerySearch'
import type { Stop } from '@/types/api'

const stop = (
  stop_id: string,
  name: string,
  cc: string,
  city: { osm_id: number; name: string; names: Record<string, string> } | null,
): Stop => ({ stop_id, name, country_code: cc, lon: 0, lat: 0, city }) as unknown as Stop

const berlin = { osm_id: 240109189, name: 'Berlin', names: { en: 'Berlin' } }
const wien = { osm_id: 17328659, name: 'Wien', names: { en: 'Vienna' } }
const stops: Stop[] = [
  stop('DE:BER', 'Berlin Hbf', 'DE', berlin),
  stop('DE:BSK', 'Berlin Südkreuz', 'DE', berlin),
  stop('AT:WIE', 'Wien Hbf', 'AT', wien),
  stop('CZ:PRA', 'Praha hl.n.', 'CZ', null),
]
const cities = cityOptions(stops, 'en')
const cityBerlin = cities.find((c) => c.name === 'Berlin')!
const cityWien = cities.find((c) => c.name === 'Vienna')!

describe('seedToQuery / seedFromQuery', () => {
  test('round-trips a station pair', () => {
    const seed = { ...EMPTY_SEED, kind: 'fromTo' as const, stops: [stops[0], stops[2]] as const }
    const query = seedToQuery(seed)
    expect(query).toEqual({ tab: 'station', kind: 'fromTo', a: 'DE:BER', b: 'AT:WIE' })
    expect(seedFromQuery(query, stops, cities)).toEqual(seed)
  })

  test('round-trips a city pick and a country pair', () => {
    const city = { ...EMPTY_SEED, tab: 'city' as const, cities: [cityBerlin, null] as const }
    expect(seedToQuery(city)).toEqual({ tab: 'city', kind: 'via', a: '240109189' })
    expect(seedFromQuery(seedToQuery(city), stops, cities)).toEqual(city)

    const pair = {
      ...EMPTY_SEED,
      tab: 'country' as const,
      kind: 'fromTo' as const,
      countries: ['AT', 'DE'] as const,
    }
    expect(seedToQuery(pair)).toEqual({ tab: 'country', kind: 'fromTo', a: 'AT', b: 'DE' })
    expect(seedFromQuery(seedToQuery(pair), stops, cities)).toEqual(pair)
  })

  // The second slot is only part of a pair: a "via" link never carries b,
  // and a b in a via link is ignored rather than silently widening the search.
  test('b belongs to from→to only', () => {
    const seed = { ...EMPTY_SEED, stops: [stops[0], stops[2]] as const }
    expect(seedToQuery(seed)).toEqual({ tab: 'station', kind: 'via', a: 'DE:BER' })
    expect(
      seedFromQuery({ tab: 'station', kind: 'via', a: 'DE:BER', b: 'AT:WIE' }, stops, cities),
    ).toEqual({ ...EMPTY_SEED, stops: [stops[0], null] })
  })

  test('a "to" picked alone keeps its slot', () => {
    const seed = { ...EMPTY_SEED, kind: 'fromTo' as const, stops: [null, stops[2]] as const }
    expect(seedToQuery(seed)).toEqual({ tab: 'station', kind: 'fromTo', b: 'AT:WIE' })
    expect(seedFromQuery(seedToQuery(seed), stops, cities)).toEqual(seed)
  })

  test('unknown ids resolve to empty picks, unknown tab/kind to the defaults', () => {
    expect(seedFromQuery({ tab: 'station', a: 'XX:GONE' }, stops, cities)).toEqual(EMPTY_SEED)
    expect(seedFromQuery({ tab: 'planet', kind: 'sideways' }, stops, cities)).toEqual(EMPTY_SEED)
    expect(seedFromQuery({}, stops, cities)).toEqual(EMPTY_SEED)
  })

  // Links shared before 2026-10-04 used ?mode&from&to&station&country&relFrom&relTo.
  test('reads the legacy query shape', () => {
    expect(seedFromQuery({ mode: 'aToB', from: 'DE:BER', to: 'AT:WIE' }, stops, cities)).toEqual({
      ...EMPTY_SEED,
      kind: 'fromTo',
      stops: [stops[0], stops[2]],
    })
    expect(seedFromQuery({ mode: 'byStation', station: 'AT:WIE' }, stops, cities)).toEqual({
      ...EMPTY_SEED,
      stops: [stops[2], null],
    })
    expect(seedFromQuery({ mode: 'byCountry', country: 'de' }, stops, cities)).toEqual({
      ...EMPTY_SEED,
      tab: 'country',
      countries: ['DE', null],
    })
    expect(
      seedFromQuery({ mode: 'byRelation', relFrom: 'DE', relTo: 'AT' }, stops, cities),
    ).toEqual({ ...EMPTY_SEED, tab: 'country', kind: 'fromTo', countries: ['DE', 'AT'] })
  })
})

describe('resolvePrefillStops', () => {
  test('a station pair is taken as is, in order', () => {
    const seed = { ...EMPTY_SEED, kind: 'fromTo' as const, stops: [stops[2], stops[0]] as const }
    expect(resolvePrefillStops(seed, stops)).toEqual([stops[2], stops[0]])
  })

  test('a city resolves to its capital-listed stop', () => {
    const seed = {
      ...EMPTY_SEED,
      tab: 'city' as const,
      kind: 'fromTo' as const,
      cities: [cityBerlin, cityWien] as const,
    }
    expect(resolvePrefillStops(seed, stops)).toEqual([stops[0], stops[2]])
  })

  test('a country pair resolves to the two capitals in pick order', () => {
    const seed = {
      ...EMPTY_SEED,
      tab: 'country' as const,
      kind: 'fromTo' as const,
      countries: ['AT', 'DE'] as const,
    }
    expect(resolvePrefillStops(seed, stops)).toEqual([stops[2], stops[0]])
  })

  test('one known stop is paired with another major stop', () => {
    const pair = resolvePrefillStops({ ...EMPTY_SEED, stops: [stops[2], null] }, stops)
    expect(pair?.[0]).toBe(stops[2])
    expect(pair?.[1].stop_id).not.toBe('AT:WIE')
  })

  test('an empty bar gives two distinct stops', () => {
    const pair = resolvePrefillStops(null, stops)
    expect(pair).not.toBeNull()
    expect(pair![0].stop_id).not.toBe(pair![1].stop_id)
  })
})
