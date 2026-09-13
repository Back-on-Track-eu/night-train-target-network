import { describe, it, expect } from 'vitest'
import { formatCount, formatEur, formatMillionEur } from './money'

describe('money', () => {
  it('prints millions with M', () => {
    expect(formatEur(7_190_000, 'en')).toBe('7.19 M €')
    expect(formatEur(1_000_000, 'en')).toBe('1.00 M €')
  })

  it('prints thousands with k', () => {
    expect(formatEur(5_404.42, 'en')).toBe('5.40 k €')
    expect(formatEur(565_148, 'en')).toBe('565.15 k €')
    expect(formatEur(1_000, 'en')).toBe('1.00 k €')
  })

  it('prints anything smaller to the cent', () => {
    expect(formatEur(443.7, 'en')).toBe('443.70 €')
    expect(formatEur(0, 'en')).toBe('0.00 €')
  })

  it('keeps the sign', () => {
    expect(formatEur(-132_811, 'en')).toBe('-132.81 k €')
  })

  it('formats a figure already in millions the same way', () => {
    expect(formatMillionEur(1.34, 'en')).toBe('1.34 M €')
    // …including one that has dropped below a million.
    expect(formatMillionEur(0.25, 'en')).toBe('250.00 k €')
  })

  it('counts share the thresholds, minus the unit', () => {
    expect(formatCount(1_200_000, 'en')).toBe('1.20 M')
    expect(formatCount(200_300, 'en')).toBe('200.3 k')
    expect(formatCount(732, 'en')).toBe('732')
  })
})
