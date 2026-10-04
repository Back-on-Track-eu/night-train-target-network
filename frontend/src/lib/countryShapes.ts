// Lazy access to the gallery's country outlines. The asset is ~175 kB
// (46 kB over the wire) and only a country or country-pair filter needs it,
// so it stays out of the main bundle and loads once, on first use.

import type { CountryShapesCollection } from '@/lib/galleryMap'

let pending: Promise<CountryShapesCollection> | null = null

export function loadCountryShapes(): Promise<CountryShapesCollection> {
  pending ??= import('@/assets/country_shapes.json').then(
    (module) => module.default as CountryShapesCollection,
  )
  return pending
}
