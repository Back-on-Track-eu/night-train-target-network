// The app's only fetch. Everything that talks to the backend goes through
// apiRequest, which guarantees four things no call site had before:
//
//   1. The body is read as text and parsed BEFORE response.ok is consulted, so
//      a non-JSON error body (Caddy's upstream-failure 502 is EMPTY) can never
//      surface a JSON-parser message to a user, and a non-JSON *success* body
//      (the expired-gate-cookie 200 + HTML) is caught as 'malformed' instead of
//      throwing somewhere random.
//   2. Every failure is an ApiError carrying a classified ApiFailure.
//   3. Cheap calls have a deadline; expensive ones report progress instead.
//   4. Outcomes feed apiHealth, so repeated failures raise one banner.
//
// Budgets are named classes, not raw numbers, so a caller cannot accidentally
// give the calc a reference-data deadline.
//
// 'heavy' has NO deadline on purpose. gunicorn runs --workers 4 --timeout 120
// (backend/docker/entrypoint.sh) and OPENRAILROUTING_TIMEOUT is per routing
// LEG, not per request, so a long multi-leg calc can legitimately outlast any
// client deadline we'd pick — and aborting the fetch does not free the worker.
// Aborting could therefore only convert "slow but succeeding" into "failed,
// worker still busy". Heavy calls escalate their copy and stay cancellable by
// the user instead.

import { API_BASE_URL } from './apiBase'
import { ApiError, classify, classifyThrown, outcome, type ApiFailure } from './apiError'
import { apiHealth } from './apiHealth'

export const BUDGET_MS = {
  /** Small reference payloads (stops, compositions, scenarios). A hung one is
   *  broken, not busy. */
  reference: 10_000,
  /** Anything the user is waiting on that isn't a full recompute. */
  interactive: 15_000,
  /** Server-side recompute (calc, publish). No deadline — see header. */
  heavy: null,
} as const

export type Budget = keyof typeof BUDGET_MS

/** First escalation: "still working, the server is busy". */
export const SLOW_AT_MS = 8_000
/** Second escalation: "we're experiencing high demand". */
export const VERY_SLOW_AT_MS = 30_000

export type SlowPhase = 'slow' | 'verySlow'

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'DELETE' | 'PATCH'
  /** Serialized as JSON; sets Content-Type automatically. */
  body?: unknown
  headers?: Record<string, string>
  /** Default 'interactive'. */
  budget?: Budget
  /** Fires at most once per phase while the request is still in flight. */
  onSlow?: (phase: SlowPhase) => void
  /** Caller-owned abort: user cancel, supersession, unmount. Produces
   *  { kind: 'canceled' }, which is never surfaced and never counts as an
   *  outage. */
  signal?: AbortSignal
  /** Set false for calls whose failure says nothing about server health — the
   *  auth/OTP flow, where a user's own mistakes must not arm the banner. */
  countsTowardOutage?: boolean
  /** Set true for the one endpoint family that answers 204 No Content
   *  (DELETE /api/proposal/<id>/comment/<cid>). An empty 2xx then resolves as
   *  undefined instead of being classified 'malformed' — see the empty-body
   *  check below for why that is the default. */
  allowEmpty?: boolean
}

/**
 * Dev-only override so the escalation and deadline paths are actually testable
 * by hand. Without it nobody will ever sit through the 30s copy change.
 *   localStorage.setItem('api.slowAt', '2000')
 *   localStorage.setItem('api.verySlowAt', '5000')
 *   localStorage.setItem('api.budget', '3000')
 * Dead-stripped from production builds.
 */
function devOverride(key: string): number | null {
  if (!import.meta.env.DEV || typeof localStorage === 'undefined') return null
  const raw = Number(localStorage.getItem(key))
  return Number.isFinite(raw) && raw > 0 ? raw : null
}

/** True when the text is worth handing to JSON.parse. */
function looksLikeJson(contentType: string | null, text: string): boolean {
  if (contentType && contentType.includes('json')) return true
  const head = text.trimStart()
  return head.startsWith('{') || head.startsWith('[')
}

export async function apiRequest<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const method = opts.method ?? 'GET'
  const budgetName = opts.budget ?? 'interactive'
  const budgetMs = devOverride('api.budget') ?? BUDGET_MS[budgetName]
  const slowAt = devOverride('api.slowAt') ?? SLOW_AT_MS
  const verySlowAt = devOverride('api.verySlowAt') ?? VERY_SLOW_AT_MS
  const countsTowardOutage = opts.countsTowardOutage ?? true
  const dev = `${method} ${path}`

  const controller = new AbortController()
  let timedOut = false
  let canceled = false
  const timers: ReturnType<typeof setTimeout>[] = []

  const onCallerAbort = () => {
    canceled = true
    controller.abort()
  }
  if (opts.signal) {
    if (opts.signal.aborted) onCallerAbort()
    else opts.signal.addEventListener('abort', onCallerAbort, { once: true })
  }

  if (budgetMs !== null) {
    timers.push(
      setTimeout(() => {
        timedOut = true
        controller.abort()
      }, budgetMs),
    )
  }
  if (opts.onSlow) {
    const notify = opts.onSlow
    timers.push(setTimeout(() => notify('slow'), slowAt))
    timers.push(setTimeout(() => notify('verySlow'), verySlowAt))
  }

  // Recorded exactly once, in the finally below, so no path can forget it.
  let signal: 'ok' | ReturnType<typeof outcome> | null = null

  try {
    let response: Response
    try {
      response = await fetch(`${API_BASE_URL}${path}`, {
        method,
        headers: {
          ...(opts.body === undefined ? {} : { 'Content-Type': 'application/json' }),
          ...opts.headers,
        },
        ...(opts.body === undefined ? {} : { body: JSON.stringify(opts.body) }),
        signal: controller.signal,
      })
    } catch (err) {
      const failure = classifyThrown(err, { timedOut, canceled, budgetMs })
      signal = failure.kind === 'canceled' ? null : outcome(failure)
      throw new ApiError(failure, dev)
    }

    // Text first, then parse, then check ok. This ordering is the whole point:
    // it is what the old call sites got backwards.
    const text = await response.text()
    let parsed: unknown = null
    let parseFailed = false
    if (text.length > 0) {
      if (looksLikeJson(response.headers.get('content-type'), text)) {
        try {
          parsed = JSON.parse(text)
        } catch {
          parseFailed = true
        }
      } else {
        parseFailed = true
      }
    }

    if (!response.ok) {
      const failure = classify(response.status, parsed, response.headers)
      signal = outcome(failure)
      throw new ApiError(failure, `${dev} -> ${response.status}`)
    }

    // A 2xx we can't read. Almost always the gate cookie expiring: Caddy's
    // forward_auth target 302s to /gate, fetch follows it, and we get HTML.
    // An empty 2xx counts too: an endpoint that answers with a body and
    // returned none did not answer at all — something in front of the API did.
    // Endpoints that genuinely return 204 opt out via allowEmpty, so the check
    // keeps its teeth everywhere else rather than being weakened globally.
    if (opts.allowEmpty && text.length === 0) {
      signal = 'ok'
      return undefined as T
    }
    if (parseFailed || text.length === 0) {
      const failure: ApiFailure = { kind: 'malformed', status: response.status }
      signal = outcome(failure)
      throw new ApiError(failure, `${dev} -> ${response.status} non-JSON body`)
    }

    signal = 'ok'
    return parsed as T
  } finally {
    for (const timer of timers) clearTimeout(timer)
    opts.signal?.removeEventListener('abort', onCallerAbort)
    if (signal !== null && countsTowardOutage) apiHealth.record(signal)
  }
}

/**
 * One in-flight request at a time for a given concern, newest wins.
 * begin() aborts whatever the previous begin() started, so the loser rejects
 * with { kind: 'canceled' } — silent, and not an outage. Used for supersession
 * (a filter change during a slow load) and for cancel-on-unmount.
 */
export function createAbortSlot(): { begin(): AbortSignal; cancel(): void } {
  let current: AbortController | null = null
  return {
    begin() {
      current?.abort()
      current = new AbortController()
      return current.signal
    },
    cancel() {
      current?.abort()
      current = null
    },
  }
}
