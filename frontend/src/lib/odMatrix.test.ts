import { readFileSync } from 'node:fs'
import { describe, it, expect } from 'vitest'
import {
  alightingStopIds,
  averageDistanceKm,
  boardingStopIds,
  odShares,
  pinPair,
  presetWeights,
  sellablePairs,
  unpinPair,
  type OdPreset,
  type PinMap,
} from './odMatrix'

const fixture = JSON.parse(
  readFileSync(
    new URL('../../../backend/tests/fixtures/demand_reference.json', import.meta.url),
    'utf8',
  ),
)

const KIND = { B: 'BOARDING', A: 'ALIGHTING', X: 'BOTH', N: 'NIGHT' } as Record<string, string>
const stops = fixture.stops.map((s: { stop_id: string; kind: string }) => ({
  stop_id: s.stop_id,
  stop_type: KIND[s.kind],
}))
const segmentKm = fixture.stops
  .slice(1)
  .map((s: { km: number }, i: number) => s.km - fixture.stops[i].km)
const pairs = sellablePairs(stops, segmentKm)
const pinsOf = (steps: [string[], number][]): PinMap => {
  const out: PinMap = {}
  for (const [[o, d], v] of steps) (out[o] ??= {})[d] = v
  return out
}

describe('the OD spread (parity with models/demand/od_matrix.py)', () => {
  it('finds the same sellable pairs in the same order', () => {
    expect(pairs.map((p) => [p.originStopId, p.destinationStopId, p.distanceKm])).toEqual(
      fixture.sellable_pairs.map(
        (p: { origin_stop_id: string; destination_stop_id: string; distance_km: number }) => [
          p.origin_stop_id,
          p.destination_stop_id,
          p.distance_km,
        ],
      ),
    )
    expect(boardingStopIds(stops)).toEqual(fixture.boarding_stop_ids)
    expect(alightingStopIds(stops)).toEqual(fixture.alighting_stop_ids)
  })

  it('writes the same preset weights', () => {
    for (const preset of Object.keys(fixture.presets) as OdPreset[]) {
      const { board, alight } = presetWeights(
        fixture.boarding_stop_ids,
        fixture.alighting_stop_ids,
        preset,
      )
      expect(board).toEqual(fixture.presets[preset][0])
      expect(alight).toEqual(fixture.presets[preset][1])
    }
  })

  it('spreads evenly to the same shares and average journey', () => {
    const { board, alight } = presetWeights(
      fixture.boarding_stop_ids,
      fixture.alighting_stop_ids,
      'even',
    )
    const shares = odShares(pairs, board, alight)
    shares.forEach((s, i) => expect(s).toBeCloseTo(fixture.even_shares[i], 12))
    expect(averageDistanceKm(pairs, shares)).toBeCloseTo(fixture.average_distance_km, 9)
    expect(shares.reduce((a, b) => a + b, 0)).toBeCloseTo(1, 12)
  })

  it('pins and rescales exactly as the backend', () => {
    const { board, alight } = presetWeights(
      fixture.boarding_stop_ids,
      fixture.alighting_stop_ids,
      'even',
    )
    let pins: PinMap = {}
    for (const step of fixture.pin_steps) {
      pins = pinPair(pairs, board, alight, pins, step.pin[0], step.pin[1], step.value_pct)
      expect(pins).toEqual(pinsOf(step.pins_after))
      const shares = odShares(pairs, board, alight, pins)
      shares.forEach((s, i) => expect(s).toBeCloseTo(step.shares_after[i], 12))
    }
  })

  it('clamps a pin to 100 and leaves nothing negative', () => {
    const { board, alight } = presetWeights(
      fixture.boarding_stop_ids,
      fixture.alighting_stop_ids,
      'even',
    )
    const pins = pinPair(pairs, board, alight, {}, 'Berlin', 'Verona', 140)
    const shares = odShares(pairs, board, alight, pins)
    expect(pins.Berlin.Verona).toBe(100)
    expect(shares.every((s) => s >= 0)).toBe(true)
    expect(shares.reduce((a, b) => a + b, 0)).toBeCloseTo(1, 12)
  })

  it('unpins a pair back into the remainder', () => {
    const pins = pinsOf([
      [['Berlin', 'Verona'], 20],
      [['Leipzig', 'Verona'], 10],
    ])
    expect(unpinPair(pins, 'Berlin', 'Verona')).toEqual({ Leipzig: { Verona: 10 } })
    expect(unpinPair({ Berlin: { Verona: 20 } }, 'Berlin', 'Verona')).toEqual({})
  })

  it('sells nothing rather than dividing by zero when every weight is 0', () => {
    expect(odShares(pairs, {}, {})).toEqual(pairs.map(() => 0))
  })
})
