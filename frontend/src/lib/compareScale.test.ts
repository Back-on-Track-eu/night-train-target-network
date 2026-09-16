import { describe, it, expect } from 'vitest'
import { chooseScale } from './compareScale'

describe('the compare axis', () => {
  it('zooms when the bars would otherwise look identical', () => {
    // The case that prompted this: four scenarios within 1 % of each other.
    const scale = chooseScale([1.34, 1.34, 1.35, 1.35])
    expect(scale.zoomed).toBe(true)
    expect(scale.baseline).toBeGreaterThan(1.3)
    expect(scale.top).toBeLessThan(1.4)
  })

  it('keeps the zero baseline when the spread is already visible', () => {
    const scale = chooseScale([1.0, 2.0, 3.0])
    expect(scale.zoomed).toBe(false)
    expect(scale.baseline).toBe(0)
    expect(scale.top).toBe(3)
  })

  it('never zooms across zero', () => {
    // "One needs a subsidy, another runs a surplus" is the comparison a
    // floating baseline would flatten.
    const scale = chooseScale([-0.2, 0.1, 0.15])
    expect(scale.zoomed).toBe(false)
    expect(scale.baseline).toBe(-0.2)
    expect(scale.top).toBeCloseTo(0.15, 6)
  })

  it('does not zoom on identical bars', () => {
    // Nothing to magnify but rounding.
    expect(chooseScale([2.5, 2.5, 2.5]).zoomed).toBe(false)
  })

  it('zooms negatives the same way it zooms positives', () => {
    const scale = chooseScale([-1.34, -1.35, -1.36])
    expect(scale.zoomed).toBe(true)
    expect(scale.baseline).toBeLessThan(-1.36)
    expect(scale.top).toBeGreaterThan(-1.34)
  })

  it('always leaves a usable range', () => {
    for (const values of [[], [0], [0, 0]]) {
      expect(chooseScale(values).range).toBeGreaterThan(0)
    }
  })

  it('leaves air at both ends when zoomed, so no bar touches an edge', () => {
    const scale = chooseScale([10, 11])
    expect(scale.baseline).toBeLessThan(10)
    expect(scale.top).toBeGreaterThan(11)
  })
})
