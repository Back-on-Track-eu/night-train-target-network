import { describe, expect, it } from 'vitest'
import { entersAtGallery, GALLERY_HASH, queryNamesAFilter } from './galleryEntry'

describe('queryNamesAFilter', () => {
  it('ignores the keys the gallery always writes', () => {
    expect(queryNamesAFilter({})).toBe(false)
    expect(queryNamesAFilter({ tab: 'station', kind: 'via', sort: 'date', dir: 'desc' })).toBe(
      false,
    )
  })

  it('sees a station, a country, a range, a scenario or a legacy mode link', () => {
    expect(queryNamesAFilter({ tab: 'station', kind: 'via', a: 'osm:n1' })).toBe(true)
    expect(queryNamesAFilter({ tab: 'country', a: 'DE' })).toBe(true)
    expect(queryNamesAFilter({ km: '500-2000' })).toBe(true)
    expect(queryNamesAFilter({ scenario: '3' })).toBe(true)
    expect(queryNamesAFilter({ mode: 'byCountry', country: 'FR' })).toBe(true)
    expect(queryNamesAFilter({ mine: '1' })).toBe(true)
  })
})

describe('entersAtGallery', () => {
  it('is the hash or a filter — a plain entry stays on the pitch', () => {
    expect(entersAtGallery('', {})).toBe(false)
    expect(entersAtGallery('', { tab: 'station', kind: 'via', sort: 'date', dir: 'desc' })).toBe(
      false,
    )
    expect(entersAtGallery(GALLERY_HASH, {})).toBe(true)
    expect(entersAtGallery('', { a: 'osm:n1' })).toBe(true)
    expect(entersAtGallery('#other', {})).toBe(false)
  })
})
