import { describe, it, expect } from 'vitest'
import { UI_LANGUAGES, availableLanguages } from '@/lib/uiLanguages'

describe('uiLanguages', () => {
  it('lists English first and German second', () => {
    expect(UI_LANGUAGES.map((lang) => lang.code).slice(0, 2)).toEqual(['en', 'de'])
  })

  it('covers the seven back-on-track.eu languages without duplicates', () => {
    const codes = UI_LANGUAGES.map((lang) => lang.code)
    expect(codes).toEqual(['en', 'de', 'fr', 'nl', 'it', 'es', 'pl'])
    expect(new Set(codes).size).toBe(codes.length)
  })

  it('marks only the locales we ship translations for as available', () => {
    expect(availableLanguages().map((lang) => lang.code)).toEqual(['en'])
  })

  it('names every language by its endonym', () => {
    expect(UI_LANGUAGES.every((lang) => lang.name.trim().length > 0)).toBe(true)
    expect(UI_LANGUAGES.find((lang) => lang.code === 'de')?.name).toBe('Deutsch')
  })
})
