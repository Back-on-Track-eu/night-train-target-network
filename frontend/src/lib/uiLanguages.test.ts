import { describe, it, expect } from 'vitest'
import { UI_LANGUAGES, availableLanguages } from '@/lib/uiLanguages'

describe('uiLanguages', () => {
  it('lists English first and German second', () => {
    expect(UI_LANGUAGES.map((lang) => lang.code).slice(0, 2)).toEqual(['en', 'de'])
  })

  it('lists the shipped locales without duplicates', () => {
    const codes = UI_LANGUAGES.map((lang) => lang.code)
    expect(codes).toEqual(['en', 'de'])
    expect(new Set(codes).size).toBe(codes.length)
  })

  // The bar advertises nothing it cannot deliver, so every entry is live. The
  // `available: false` branch stays supported for a locale announced early.
  it('marks every listed language as available', () => {
    expect(availableLanguages().map((lang) => lang.code)).toEqual(['en', 'de'])
  })

  it('names every language by its endonym', () => {
    expect(UI_LANGUAGES.every((lang) => lang.name.trim().length > 0)).toBe(true)
    expect(UI_LANGUAGES.find((lang) => lang.code === 'de')?.name).toBe('Deutsch')
  })
})
