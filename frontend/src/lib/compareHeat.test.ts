import { describe, expect, it } from 'vitest'
import { buildHeatScale } from './compareHeat'
import { compareKpi } from './compareKpis'

const subsidy = compareKpi('subsidy')
const co2 = compareKpi('co2')

// "rgb(r,g,b)" -> rough perceived brightness, for asserting the one property
// the whole design rests on: brighter means better.
function luma(css: string): number {
  const [r, g, b] = css.match(/\d+/g)!.map(Number)
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}
function hueIsGreen(css: string): boolean {
  const [r, g, b] = css.match(/\d+/g)!.map(Number)
  return g > r && g > b
}

describe('buildHeatScale', () => {
  describe('signed KPI with both signs present', () => {
    // subsidy values are signed: positive needs money, negative is a surplus.
    const scale = buildHeatScale(subsidy, [3.65, 0.71, -5.23, -18.62])

    it('diverges and puts break-even inside the legend', () => {
      expect(scale.diverging).toBe(true)
      expect(scale.zeroAt).toBeGreaterThan(0)
      expect(scale.zeroAt).toBeLessThan(1)
    })

    it('separates the two signs by hue', () => {
      expect(hueIsGreen(scale.color(-5))).toBe(true)
      expect(hueIsGreen(scale.color(3))).toBe(false)
    })

    it('makes the best cell the brightest in the grid', () => {
      const best = luma(scale.color(-18.62))
      for (const v of [3.65, 0.71, -5.23, 0]) {
        expect(best).toBeGreaterThan(luma(scale.color(v)))
      }
    })

    it('never lets a large subsidy outshine a surplus', () => {
      // The failure the old single ramp had: two cells a few percent apart in
      // colour meaning opposite things.
      expect(luma(scale.color(3.65))).toBeLessThan(luma(scale.color(-0.01)))
    })

    it('gets brighter monotonically from worst to best, across zero', () => {
      // The property that makes "which is best" answerable by eye. Sorted
      // worst-first: for subsidy that is descending, since lower is better.
      const sorted = [3.65, 2.7, 0.71, 0.14, -0.5, -2.03, -5.23, -18.62]
      const lumas = sorted.map((v) => luma(scale.color(v)))
      for (let i = 1; i < lumas.length; i++) {
        expect(lumas[i]).toBeGreaterThan(lumas[i - 1])
      }
    })

    it('reports the best and worst values for the legend', () => {
      expect(scale.best).toBe(-18.62)
      expect(scale.worst).toBe(3.65)
    })
  })

  it('stays sequential when every route needs a subsidy', () => {
    const scale = buildHeatScale(subsidy, [1, 2, 3])
    expect(scale.diverging).toBe(false)
    expect(scale.zeroAt).toBeNull()
    expect(scale.best).toBe(1)
  })

  it('is sequential for an unsigned KPI, brighter for more', () => {
    const scale = buildHeatScale(co2, [10, 20, 30])
    expect(scale.diverging).toBe(false)
    expect(scale.best).toBe(30)
    expect(luma(scale.color(30))).toBeGreaterThan(luma(scale.color(10)))
  })

  it('survives an empty grid', () => {
    const scale = buildHeatScale(co2, [])
    expect(scale.best).toBeNull()
    expect(scale.color(0)).toMatch(/^rgb\(/)
  })
})
