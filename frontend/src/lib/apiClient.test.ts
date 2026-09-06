import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { apiRequest, createAbortSlot, SLOW_AT_MS, VERY_SLOW_AT_MS } from './apiClient'
import { ApiError } from './apiError'
import { apiHealth } from './apiHealth'

/** Build a Response-alike; `body` is sent as-is so non-JSON cases are real. */
function reply(status: number, body: string, contentType = 'application/json'): Response {
  return new Response(body, {
    status,
    headers: contentType ? { 'Content-Type': contentType } : {},
  })
}

/** A fetch that never settles until the returned resolve is called. */
function pending(): { fetchImpl: () => Promise<Response>; resolve: (r: Response) => void } {
  let resolve!: (r: Response) => void
  const promise = new Promise<Response>((r) => {
    resolve = r
  })
  return { fetchImpl: () => promise, resolve }
}

let health: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  health = vi.spyOn(apiHealth, 'record').mockImplementation(() => {})
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
})

async function expectFailure(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise
  } catch (err) {
    expect(err).toBeInstanceOf(ApiError)
    return err as ApiError
  }
  throw new Error('expected the request to reject')
}

describe('apiRequest — happy path', () => {
  test('resolves with the parsed body and reports health', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(reply(200, '{"stops":[]}')))
    await expect(apiRequest('/api/params/StopInfrastructures')).resolves.toEqual({ stops: [] })
    expect(health).toHaveBeenCalledWith('ok')
  })

  test('a JSON body sets Content-Type; a bodyless request does not', async () => {
    // A fresh Response per call — a body can only be read once.
    const fetchMock = vi.fn(async () => reply(200, '{"ok":true}'))
    vi.stubGlobal('fetch', fetchMock)

    await apiRequest('/api/proposals', { method: 'POST', body: { limit: 10 } })
    expect(fetchMock.mock.calls[0][1].headers).toMatchObject({
      'Content-Type': 'application/json',
    })
    expect(fetchMock.mock.calls[0][1].body).toBe('{"limit":10}')

    await apiRequest('/api/auth/guest', { method: 'POST' })
    expect(fetchMock.mock.calls[1][1].headers['Content-Type']).toBeUndefined()
    expect(fetchMock.mock.calls[1][1].body).toBeUndefined()
  })
})

// The bug this whole module exists to kill: the old call sites ran
// response.json() BEFORE checking response.ok, so a body that wasn't JSON
// surfaced a JSON-parser message as the user-facing error text.
describe('apiRequest — unreadable error bodies never leak a parser message', () => {
  test('Caddy 502 with an empty body classifies as server, not a parse error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(reply(502, '', '')))
    const err = await expectFailure(apiRequest('/api/proposals', { method: 'POST' }))
    expect(err.failure).toEqual({ kind: 'server', status: 502, slug: null })
    expect(err.verbatim).toBeNull()
    expect(err.message).not.toMatch(/JSON/i)
    expect(health).toHaveBeenCalledWith('outage')
  })

  test('a 504 HTML gateway page classifies as unavailable', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(reply(504, '<html><body>Gateway Timeout</body></html>', 'text/html')),
    )
    const err = await expectFailure(apiRequest('/api/proposal/calc', { method: 'POST' }))
    expect(err.failure.kind).toBe('unavailable')
    expect(err.verbatim).toBeNull()
    expect(err.message).not.toMatch(/<html>/)
  })

  test('a well-formed 500 still classifies, and drops its message', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        reply(
          500,
          JSON.stringify({
            error: 'calc_error',
            message: 'Routing engine HTTP 400: Cannot find point 0: 60.171742,24.941443',
          }),
        ),
      ),
    )
    const err = await expectFailure(apiRequest('/api/proposal/calc', { method: 'POST' }))
    expect(err.failure).toMatchObject({ kind: 'server', status: 500, slug: 'calc_error' })
    expect(err.verbatim).toBeNull()
  })

  test('a 400 keeps its validation details', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          reply(400, JSON.stringify({ error: 'validation_error', details: ['Need two stops.'] })),
        ),
    )
    const err = await expectFailure(apiRequest('/api/proposal/calc', { method: 'POST' }))
    expect(err.verbatim).toBe('Need two stops.')
    // A bad request is not evidence the server is unwell.
    expect(health).toHaveBeenCalledWith('ignore')
  })
})

// Caddy's forward_auth -> /api/gate/check answers 302 to /gate when the gate
// cookie expires; fetch follows the redirect silently, so the app gets a 200
// carrying HTML. Every old call site died inside response.json() here.
describe('apiRequest — a 2xx we cannot read is malformed, not a crash', () => {
  test('200 with an HTML body', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(reply(200, '<!doctype html><title>Gate</title>', 'text/html')),
    )
    const err = await expectFailure(apiRequest('/api/scenarios'))
    expect(err.failure).toEqual({ kind: 'malformed', status: 200 })
    // A stale session is not an outage — it must not arm the degraded banner.
    expect(health).toHaveBeenCalledWith('ignore')
  })

  test('200 with an empty body', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(reply(200, '', '')))
    const err = await expectFailure(apiRequest('/api/scenarios'))
    expect(err.failure.kind).toBe('malformed')
  })

  test('204 resolves as undefined when the caller opts in with allowEmpty', async () => {
    // DELETE /api/proposal/<id>/comment/<cid> is the one endpoint that answers
    // with no content; without the opt-in it would look like a stale session.
    // Not via reply(): the WHATWG Response constructor rejects a body — even
    // an empty string — on 204, so this has to be the real null-body form.
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })))
    await expect(
      apiRequest('/api/proposal/1/comment/2', { method: 'DELETE', allowEmpty: true }),
    ).resolves.toBeUndefined()
    expect(health).toHaveBeenCalledWith('ok')
  })

  test('allowEmpty does not excuse an unreadable non-empty body', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(reply(200, '<!doctype html>', 'text/html')))
    const err = await expectFailure(apiRequest('/api/scenarios', { allowEmpty: true }))
    expect(err.failure.kind).toBe('malformed')
  })

  test('200 whose body claims JSON but is truncated', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(reply(200, '{"stops":[')))
    const err = await expectFailure(apiRequest('/api/params/StopInfrastructures'))
    expect(err.failure.kind).toBe('malformed')
    expect(err.message).not.toMatch(/Unexpected end of JSON/)
  })
})

describe('apiRequest — thrown fetch failures', () => {
  test('a rejected fetch is a network failure and counts as an outage', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    const err = await expectFailure(apiRequest('/api/scenarios'))
    expect(err.failure.kind).toBe('network')
    expect(health).toHaveBeenCalledWith('outage')
  })

  test('countsTowardOutage: false keeps the auth flow out of the banner', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    await expectFailure(
      apiRequest('/api/auth/verify', { method: 'POST', countsTowardOutage: false }),
    )
    expect(health).not.toHaveBeenCalled()
  })
})

describe('apiRequest — deadlines', () => {
  test('a reference call that never answers times out and aborts the request', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn(
      (_url: string, init: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init.signal?.addEventListener('abort', () => reject(new Error('aborted')))
        }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const promise = apiRequest('/api/scenarios', { budget: 'reference' })
    const settled = expectFailure(promise)
    await vi.advanceTimersByTimeAsync(10_000)

    const err = await settled
    expect(err.failure).toEqual({ kind: 'timeout', budgetMs: 10_000 })
    expect(fetchMock.mock.calls[0][1].signal.aborted).toBe(true)
    expect(health).toHaveBeenCalledWith('outage')
  })

  // Aborting a heavy call cannot free the gunicorn worker, so we never do it.
  test("a 'heavy' call has no deadline", async () => {
    vi.useFakeTimers()
    const { fetchImpl, resolve } = pending()
    vi.stubGlobal('fetch', vi.fn(fetchImpl))

    const promise = apiRequest('/api/proposal/calc', { method: 'POST', budget: 'heavy' })
    await vi.advanceTimersByTimeAsync(300_000)
    resolve(reply(200, '{"route":{}}'))
    await expect(promise).resolves.toEqual({ route: {} })
  })
})

describe('apiRequest — slow-progress escalation', () => {
  test('both phases fire, in order, while the request is still in flight', async () => {
    vi.useFakeTimers()
    const { fetchImpl, resolve } = pending()
    vi.stubGlobal('fetch', vi.fn(fetchImpl))
    const onSlow = vi.fn()

    const promise = apiRequest('/api/proposal/calc', { budget: 'heavy', onSlow })

    await vi.advanceTimersByTimeAsync(SLOW_AT_MS - 1)
    expect(onSlow).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1)
    expect(onSlow).toHaveBeenCalledExactlyOnceWith('slow')

    await vi.advanceTimersByTimeAsync(VERY_SLOW_AT_MS - SLOW_AT_MS)
    expect(onSlow).toHaveBeenCalledTimes(2)
    expect(onSlow).toHaveBeenLastCalledWith('verySlow')

    resolve(reply(200, '{}'))
    await promise
  })

  test('a fast response never escalates', async () => {
    vi.useFakeTimers()
    const { fetchImpl, resolve } = pending()
    vi.stubGlobal('fetch', vi.fn(fetchImpl))
    const onSlow = vi.fn()

    const promise = apiRequest('/api/proposal/calc', { budget: 'heavy', onSlow })
    await vi.advanceTimersByTimeAsync(3_000)
    resolve(reply(200, '{}'))
    await promise

    await vi.advanceTimersByTimeAsync(60_000)
    expect(onSlow).not.toHaveBeenCalled()
  })

  // A leaked timer would set "still working" on a component that has navigated
  // away.
  test('timers are cleared on failure too', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    const onSlow = vi.fn()

    await expectFailure(apiRequest('/api/scenarios', { onSlow }))
    await vi.advanceTimersByTimeAsync(60_000)
    expect(onSlow).not.toHaveBeenCalled()
  })
})

describe('apiRequest — caller-driven cancellation', () => {
  test('a caller abort is canceled, is silent, and never touches health', async () => {
    const controller = new AbortController()
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_url: string, init: RequestInit) =>
          new Promise<Response>((_resolve, reject) => {
            init.signal?.addEventListener('abort', () => reject(new Error('aborted')))
          }),
      ),
    )

    const settled = expectFailure(
      apiRequest('/api/proposal/calc', { budget: 'heavy', signal: controller.signal }),
    )
    controller.abort()

    expect((await settled).failure).toEqual({ kind: 'canceled' })
    expect(health).not.toHaveBeenCalled()
  })

  test('an already-aborted signal cancels immediately', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('aborted')))
    const err = await expectFailure(apiRequest('/api/scenarios', { signal: AbortSignal.abort() }))
    expect(err.failure.kind).toBe('canceled')
  })
})

describe('createAbortSlot', () => {
  test('a new request supersedes the previous one, which cancels silently', async () => {
    const slot = createAbortSlot()
    vi.stubGlobal(
      'fetch',
      vi.fn((_url: string, init: RequestInit) => {
        const url = String(_url)
        return new Promise<Response>((resolve, reject) => {
          init.signal?.addEventListener('abort', () => reject(new Error('aborted')))
          if (url.includes('page=2')) resolve(reply(200, '{"page":2}'))
        })
      }),
    )

    const first = expectFailure(apiRequest('/api/proposals?page=1', { signal: slot.begin() }))
    const second = apiRequest('/api/proposals?page=2', { signal: slot.begin() })

    expect((await first).failure.kind).toBe('canceled')
    await expect(second).resolves.toEqual({ page: 2 })
    // The loser is silent; only the winner reported.
    expect(health).toHaveBeenCalledExactlyOnceWith('ok')
  })

  test('cancel() aborts the in-flight request (unmount)', async () => {
    const slot = createAbortSlot()
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_url: string, init: RequestInit) =>
          new Promise<Response>((_resolve, reject) => {
            init.signal?.addEventListener('abort', () => reject(new Error('aborted')))
          }),
      ),
    )
    const settled = expectFailure(apiRequest('/api/proposal/1', { signal: slot.begin() }))
    slot.cancel()
    expect((await settled).failure.kind).toBe('canceled')
  })
})
