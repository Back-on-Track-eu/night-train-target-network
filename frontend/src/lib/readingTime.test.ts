import { describe, expect, it } from 'vitest'
import { READING_FLOOR_MS, readingDwellMs, wordCount } from './readingTime'

describe('readingDwellMs', () => {
  it('counts words, not whitespace', () => {
    expect(wordCount('  one\ttwo\n three  ')).toBe(3)
  })

  it('gives a short text the floor', () => {
    expect(readingDwellMs('Night trains.')).toBe(READING_FLOOR_MS)
  })

  it('grows with length: the longest fact (38 words) gets 12.5 s', () => {
    expect(readingDwellMs(Array(38).fill('word').join(' '))).toBe(12_500)
  })
})
