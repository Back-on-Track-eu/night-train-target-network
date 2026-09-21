import { describe, expect, it } from 'vitest'
import { bridgeRemovedStops, type LegGeometry } from './suggestShape'

const stop = (id: string, x: number) => ({ stopId: id, lon: x, lat: 0 })
// Four stops on a line, each leg routed with a midpoint so a leg's coords are
// telling: a → b → c → d.
const leg = (a: string, ax: number, b: string, bx: number): LegGeometry => ({
  from: stop(a, ax),
  to: stop(b, bx),
  coords: [
    [ax, 0],
    [(ax + bx) / 2, 0.5],
    [bx, 0],
  ],
})
const legs = [leg('a', 0, 'b', 1), leg('b', 1, 'c', 2), leg('c', 2, 'd', 3)]

describe('bridgeRemovedStops', () => {
  it('nothing removed: one stitched run, no bridge', () => {
    const { routed, bridges } = bridgeRemovedStops(legs, new Set())
    expect(routed).toHaveLength(1)
    expect(routed[0]).toHaveLength(9)
    expect(bridges).toEqual([])
  })

  it('a middle stop removed: its two legs go, the neighbours are bridged', () => {
    const { routed, bridges } = bridgeRemovedStops(legs, new Set(['b']))
    expect(routed).toEqual([legs[2].coords])
    expect(bridges).toEqual([
      [
        [0, 0],
        [2, 0],
      ],
    ])
  })

  it('two adjacent stops removed: one bridge across both', () => {
    const { routed, bridges } = bridgeRemovedStops(legs, new Set(['b', 'c']))
    expect(routed).toEqual([])
    expect(bridges).toEqual([
      [
        [0, 0],
        [3, 0],
      ],
    ])
  })

  it('a removed origin drops its leg without a bridge', () => {
    const { routed, bridges } = bridgeRemovedStops(legs, new Set(['a']))
    expect(routed).toEqual([[...legs[1].coords, ...legs[2].coords]])
    expect(bridges).toEqual([])
  })

  it('a removed destination drops its leg without a bridge', () => {
    const { routed, bridges } = bridgeRemovedStops(legs, new Set(['d']))
    expect(routed).toEqual([[...legs[0].coords, ...legs[1].coords]])
    expect(bridges).toEqual([])
  })

  it('two separate gaps give two bridges; a leg touching a removed stop is gone', () => {
    const five = [...legs, leg('d', 3, 'e', 4)]
    const { routed, bridges } = bridgeRemovedStops(five, new Set(['b', 'd']))
    expect(routed).toEqual([])
    expect(bridges).toEqual([
      [
        [0, 0],
        [2, 0],
      ],
      [
        [2, 0],
        [4, 0],
      ],
    ])
  })
})
