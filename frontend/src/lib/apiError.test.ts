import { describe, expect, test } from 'vitest'
import {
  ApiError,
  classify,
  classifyThrown,
  isRetryable,
  messageKey,
  outcome,
  treatment,
  type ApiFailure,
} from './apiError'
import en from '@/i18n/locales/en.json'

/** Resolve a dotted i18n key against en.json, or undefined. */
function lookup(key: string): unknown {
  return key.split('.').reduce<unknown>((node, part) => {
    if (node && typeof node === 'object') return (node as Record<string, unknown>)[part]
    return undefined
  }, en)
}

/** Real backend bodies, copied from the shapes in backend/api/*.py. */
const VALIDATION_400 = {
  error: 'validation_error',
  details: ["'stops' must contain at least 2 entries."],
}
const BAD_REQUEST_400 = { error: 'bad_request', message: 'Request body must be JSON.' }
const DOMAIN_422 = { error: 'domain_error', message: 'user_id 7 does not exist.' }
// The response that started all this: proposal_calc.py's except Exception ->
// str(e) on a RailRoutingError, reported as a 500.
const CALC_ERROR_500 = {
  error: 'calc_error',
  message: 'Routing engine HTTP 400: Cannot find point 0: 60.171742,24.941443',
}
const RATE_LIMITED_429 = {
  error: 'rate_limited',
  message: 'Too many requests. Please wait a moment and try again.',
}
const DATA_NOT_LOADED_503 = {
  error: 'data_not_loaded',
  message: 'Data not loaded. Call POST /api/data/load first.',
}

describe('classify', () => {
  test('400 with details is a validation failure carrying the details', () => {
    const f = classify(400, VALIDATION_400)
    expect(f).toEqual({
      kind: 'validation',
      status: 400,
      slug: 'validation_error',
      details: ["'stops' must contain at least 2 entries."],
    })
  })

  test('400 without details is bad_input carrying the message', () => {
    const f = classify(400, BAD_REQUEST_400)
    expect(f).toMatchObject({ kind: 'bad_input', message: 'Request body must be JSON.' })
  })

  test('422 domain_error is bad_input', () => {
    expect(classify(422, DOMAIN_422)).toMatchObject({ kind: 'bad_input', slug: 'domain_error' })
  })

  test.each([
    [401, 'auth'],
    [403, 'auth'],
    [404, 'not_found'],
    [429, 'rate_limited'],
    [500, 'server'],
    [502, 'server'],
    [503, 'unavailable'],
    [504, 'unavailable'],
    [405, 'server'],
  ])('%i classifies as %s', (status, kind) => {
    expect(classify(status, null).kind).toBe(kind)
  })

  test('Caddy 502 with an empty body still classifies, with no slug', () => {
    expect(classify(502, null)).toEqual({ kind: 'server', status: 502, slug: null })
  })

  test('the backend error slug is read (it was ignored entirely before)', () => {
    expect(classify(503, DATA_NOT_LOADED_503).slug).toBe('data_not_loaded')
  })

  test('Retry-After is parsed when present (the backend does not send it yet)', () => {
    expect(classify(429, RATE_LIMITED_429).kind).toBe('rate_limited')
    const withHeader = classify(429, RATE_LIMITED_429, new Headers({ 'Retry-After': '30' }))
    expect(withHeader).toMatchObject({ retryAfterMs: 30_000 })
    const without = classify(429, RATE_LIMITED_429, new Headers())
    expect(without).toMatchObject({ retryAfterMs: null })
  })
})

describe('ApiError.verbatim — backend text never escapes for server-side faults', () => {
  test('validation details are kept (they are written for users)', () => {
    const err = new ApiError(classify(400, VALIDATION_400), 'POST /api/proposal/calc')
    expect(err.verbatim).toBe("'stops' must contain at least 2 entries.")
  })

  test('bad_input and domain_error messages are kept', () => {
    expect(new ApiError(classify(400, BAD_REQUEST_400), 'x').verbatim).toBe(
      'Request body must be JSON.',
    )
    expect(new ApiError(classify(422, DOMAIN_422), 'x').verbatim).toBe('user_id 7 does not exist.')
  })

  test('the routing-engine 500 message is dropped at the boundary', () => {
    const err = new ApiError(classify(500, CALC_ERROR_500), 'POST /api/proposal/calc')
    expect(err.verbatim).toBeNull()
    expect(err.message).not.toContain('Cannot find point')
    expect(err.message).not.toContain('60.171742')
  })

  // The invariant, as an executable assertion: no 5xx body is renderable, no
  // matter how tempting its `message` looks.
  test.each([500, 501, 502, 503, 504, 599])(
    '%i with a juicy message yields verbatim === null',
    (status) => {
      const body = {
        error: 'internal_error',
        message: "HTTPConnectionPool(host='openrailrouting', port=8989): Read timed out.",
        details: ['duplicate key value violates unique constraint "feedback_pkey"'],
      }
      expect(new ApiError(classify(status, body), 'x').verbatim).toBeNull()
    },
  )

  test('empty or whitespace-only backend text does not become an empty message', () => {
    expect(
      new ApiError(classify(400, { error: 'bad_request', message: '   ' }), 'x').verbatim,
    ).toBeNull()
    expect(
      new ApiError(classify(400, { error: 'validation_error', details: [] }), 'x').verbatim,
    ).toBeNull()
  })
})

describe('classifyThrown', () => {
  test('our own deadline wins over everything', () => {
    expect(
      classifyThrown(new Error('aborted'), { timedOut: true, canceled: false, budgetMs: 10_000 }),
    ).toEqual({ kind: 'timeout', budgetMs: 10_000 })
  })

  test('a caller abort is canceled, not a failure', () => {
    expect(classifyThrown(new Error('aborted'), { timedOut: false, canceled: true })).toEqual({
      kind: 'canceled',
    })
  })

  test('navigator.onLine === false gives offline; otherwise network', () => {
    const original = globalThis.navigator
    Object.defineProperty(globalThis, 'navigator', {
      value: { onLine: false },
      configurable: true,
    })
    expect(classifyThrown(new TypeError('failed'), { timedOut: false, canceled: false })).toEqual({
      kind: 'offline',
    })
    Object.defineProperty(globalThis, 'navigator', { value: { onLine: true }, configurable: true })
    expect(classifyThrown(new TypeError('failed'), { timedOut: false, canceled: false })).toEqual({
      kind: 'network',
    })
    Object.defineProperty(globalThis, 'navigator', { value: original, configurable: true })
  })
})

describe('messageKey', () => {
  test('a recognised slug beats the kind fallback', () => {
    expect(messageKey(classify(401, { error: 'invalid_code' }))).toBe('errors.slug.invalid_code')
    expect(messageKey(classify(503, DATA_NOT_LOADED_503))).toBe('errors.slug.data_not_loaded')
  })

  test('an unrecognised or future slug falls back to the kind, never a missing key', () => {
    expect(messageKey(classify(500, { error: 'stop_unroutable' }))).toBe('errors.server')
    expect(messageKey(classify(422, { error: 'no_rail_connection', message: 'x' }))).toBe(
      'errors.badInput',
    )
  })

  // Catches "shipped a key that doesn't exist in en.json", which is otherwise
  // only visible as a raw key rendered in the UI.
  test('every kind and every recognised slug resolves to real copy in en.json', () => {
    const samples: ApiFailure[] = [
      { kind: 'offline' },
      { kind: 'network' },
      { kind: 'timeout', budgetMs: 1 },
      { kind: 'canceled' },
      { kind: 'validation', status: 400, slug: null, details: ['x'] },
      { kind: 'bad_input', status: 400, slug: null, message: 'x' },
      { kind: 'auth', status: 401, slug: null },
      { kind: 'not_found', status: 404, slug: null },
      { kind: 'rate_limited', slug: null, retryAfterMs: null },
      { kind: 'unavailable', status: 503, slug: null },
      { kind: 'server', status: 500, slug: null },
      { kind: 'malformed', status: 200 },
    ]
    for (const f of samples) {
      expect(typeof lookup(messageKey(f)), `${f.kind} -> ${messageKey(f)}`).toBe('string')
    }
    for (const slug of [
      'invalid_code',
      'rate_limited',
      'data_not_loaded',
      'email_failed',
      'scenario_not_base',
    ]) {
      expect(typeof lookup(`errors.slug.${slug}`), slug).toBe('string')
    }
  })
})

describe('treatment / outcome / isRetryable', () => {
  test('actionable failures go inline, systemic ones toast, cancels say nothing', () => {
    expect(treatment({ kind: 'validation', status: 400, slug: null, details: ['x'] })).toBe(
      'inline',
    )
    expect(treatment({ kind: 'bad_input', status: 422, slug: null, message: 'x' })).toBe('inline')
    expect(treatment({ kind: 'not_found', status: 404, slug: null })).toBe('inline')
    expect(treatment({ kind: 'server', status: 500, slug: null })).toBe('toast')
    expect(treatment({ kind: 'offline' })).toBe('toast')
    expect(treatment({ kind: 'canceled' })).toBe('silent')
  })

  test('only genuine server trouble arms the degraded banner', () => {
    for (const f of [
      { kind: 'offline' },
      { kind: 'network' },
      { kind: 'timeout', budgetMs: 1 },
      { kind: 'server', status: 500, slug: null },
      { kind: 'unavailable', status: 503, slug: null },
    ] as ApiFailure[]) {
      expect(outcome(f), f.kind).toBe('outage')
    }
    // We caused the rate limit; a bad input is not an outage; a stale gate
    // cookie is a session problem; a cancel is ours.
    for (const f of [
      { kind: 'rate_limited', slug: null, retryAfterMs: null },
      { kind: 'validation', status: 400, slug: null, details: ['x'] },
      { kind: 'auth', status: 401, slug: null },
      { kind: 'not_found', status: 404, slug: null },
      { kind: 'malformed', status: 200 },
      { kind: 'canceled' },
    ] as ApiFailure[]) {
      expect(outcome(f), f.kind).toBe('ignore')
    }
  })

  test('Retry is offered for transient failures, not for bad input', () => {
    expect(isRetryable({ kind: 'server', status: 500, slug: null })).toBe(true)
    expect(isRetryable({ kind: 'rate_limited', slug: null, retryAfterMs: null })).toBe(true)
    expect(isRetryable({ kind: 'validation', status: 400, slug: null, details: ['x'] })).toBe(false)
  })
})
