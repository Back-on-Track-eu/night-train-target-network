import { describe, expect, test } from 'vitest'
import shapes from '@/assets/country_shapes.json'
import type { CountryShapesCollection } from './galleryMap'

// The asset is generated (scripts/build_country_shapes.mjs) and committed, so
// these guard the contract the gallery relies on rather than the generator.

// backend/scripts/export_country_geoms.py::_COUNTRY_CODE_TO_ISO3 — every
// country the tool models. A code the search bar can offer must have an outline.
const CATALOGUE_CODES = [
  'AL',
  'AT',
  'BA',
  'BY',
  'BE',
  'BG',
  'CH',
  'CZ',
  'DE',
  'DK',
  'EE',
  'ES',
  'FI',
  'FR',
  'GB',
  'GR',
  'HR',
  'HU',
  'IE',
  'IT',
  'LI',
  'LT',
  'LU',
  'LV',
  'MD',
  'ME',
  'MK',
  'NL',
  'NO',
  'PL',
  'PT',
  'RO',
  'RS',
  'RU',
  'SE',
  'SI',
  'SK',
  'TR',
  'UA',
]
// backend/scripts/export_country_geoms.py::_CLIP_BBOX
const CLIP_BBOX = [-25, 34, 45, 72]

const collection = shapes as CountryShapesCollection

describe('country_shapes.json', () => {
  test('has an outline for every catalogue country', () => {
    const present = new Set(collection.features.map((f) => f.properties.country))
    expect(CATALOGUE_CODES.filter((c) => !present.has(c))).toEqual([])
  })

  test('is keyed by unique upper-case ISO-2 codes', () => {
    const codes = collection.features.map((f) => f.properties.country)
    expect(new Set(codes).size).toBe(codes.length)
    expect(codes.every((c) => /^[A-Z]{2}$/.test(c))).toBe(true)
  })

  test('every vertex lies inside the backend clip bbox', () => {
    for (const f of collection.features) {
      expect(f.geometry.type).toBe('MultiPolygon')
      for (const polygon of f.geometry.coordinates)
        for (const ring of polygon)
          for (const [lon, lat] of ring) {
            expect(lon).toBeGreaterThanOrEqual(CLIP_BBOX[0])
            expect(lon).toBeLessThanOrEqual(CLIP_BBOX[2])
            expect(lat).toBeGreaterThanOrEqual(CLIP_BBOX[1])
            expect(lat).toBeLessThanOrEqual(CLIP_BBOX[3])
          }
    }
  })
})
