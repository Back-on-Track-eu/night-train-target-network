import { describe, it, expect } from 'vitest'
import {
  buildShareUrls,
  routeFacts,
  mailtoHref,
  whatsappHref,
  type ShareRouteInput,
} from './shareLinks'

function route(over: Partial<ShareRouteInput> = {}): ShareRouteInput {
  return {
    trip_pairs: [
      {
        outbound: {
          general_parameters: { trip_km: 1283.7 },
          segments: [{}, {}, {}],
        },
      },
    ],
    track_infrastructure: [{ country_code: 'DE' }, { country_code: 'FR' }],
    ...over,
  }
}

describe('buildShareUrls', () => {
  it('hands the clipboard the clean URL and the chat channels the stub', () => {
    const urls = buildShareUrls(12, 'https://targetnetwork.back-on-track.eu', '')
    expect(urls.appUrl).toBe('https://targetnetwork.back-on-track.eu/proposal/12')
    expect(urls.shareUrl).toBe('https://targetnetwork.back-on-track.eu/api/proposal/12/share')
  })

  it('sends the share URL to the api origin when it differs (local dev)', () => {
    // Otherwise the stub would be requested from Vite, which does not serve /api.
    const urls = buildShareUrls(3, 'http://localhost:5173', 'http://localhost:5050')
    expect(urls.appUrl).toBe('http://localhost:5173/proposal/3')
    expect(urls.shareUrl).toBe('http://localhost:5050/api/proposal/3/share')
  })

  it('does not double the slash when an origin carries one', () => {
    const urls = buildShareUrls(1, 'https://example.test/', 'https://example.test/')
    expect(urls.appUrl).toBe('https://example.test/proposal/1')
    expect(urls.shareUrl).toBe('https://example.test/api/proposal/1/share')
  })
})

describe('routeFacts', () => {
  it('reads distance, stop count and country count off the calc payload', () => {
    expect(routeFacts(route())).toEqual({ km: 1284, stops: 4, countries: 2 })
  })

  it('counts each country once however many times it appears', () => {
    const facts = routeFacts(
      route({
        track_infrastructure: [
          { country_code: 'DE' },
          { country_code: 'CH' },
          { country_code: 'DE' },
        ],
      }),
    )
    expect(facts?.countries).toBe(2)
  })

  it('is null with no route, so the caller can quote nothing', () => {
    expect(routeFacts(null)).toBeNull()
    expect(routeFacts(route({ trip_pairs: [] }))).toBeNull()
  })
})

describe('mailtoHref', () => {
  it('encodes the separators that would otherwise end the parameter', () => {
    const href = mailtoHref('Berlin & Paris', 'One\nTwo?three&four=five')
    expect(href).toBe('mailto:?subject=Berlin%20%26%20Paris&body=One%0ATwo%3Fthree%26four%3Dfive')
  })

  it('keeps a URL in the body intact once decoded', () => {
    const url = 'https://example.test/api/proposal/12/share'
    const href = mailtoHref('s', `See ${url}`)
    const body = new URL(href).searchParams.get('body')
    expect(body).toBe(`See ${url}`)
  })
})

describe('whatsappHref', () => {
  it('encodes newlines and the hash, which would otherwise cut the text short', () => {
    // A bare # starts the fragment, so everything after it never reaches WhatsApp.
    const href = whatsappHref('Night train\n#nighttrains https://example.test/s')
    expect(href).toBe(
      'https://wa.me/?text=Night%20train%0A%23nighttrains%20https%3A%2F%2Fexample.test%2Fs',
    )
    expect(new URL(href).searchParams.get('text')).toContain('#nighttrains')
  })
})
