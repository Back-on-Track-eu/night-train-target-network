import { describe, expect, it } from 'vitest'
import { entryBundleOf } from './freshBuild'

describe('entryBundleOf', () => {
  it('finds the hashed entry bundle an index.html names', () => {
    const html =
      '<link rel="stylesheet" href="/assets/index-R3cUu3X8.css">' +
      '<script type="module" crossorigin src="/assets/index-DD0WsVP0.js"></script>'
    expect(entryBundleOf(html)).toBe('/assets/index-DD0WsVP0.js')
  })

  it('is null for the dev server entry and for anything else', () => {
    expect(entryBundleOf('<script type="module" src="/src/main.ts"></script>')).toBeNull()
    expect(entryBundleOf('/assets/maplibre-gl-csp-worker-BF1M-q9C.js')).toBeNull()
    expect(entryBundleOf('')).toBeNull()
  })
})
