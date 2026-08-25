// Failure classification for every backend call — the single place that decides
// what a non-2xx / dead-network / malformed response MEANS, so no component has
// to. Pure: no fetch, no vue, no i18n. Callers get a discriminated union plus
// three lookups (which copy, which surface, does it count as an outage).
//
// The load-bearing rule is `ApiError.verbatim`: backend text is kept ONLY for
// the two kinds whose messages are written for users ('validation',
// 'bad_input'). Everything else drops it at this boundary, so a 500 carrying
// `Routing engine HTTP 400: Cannot find point 0: 60.17,24.94` or a psycopg2
// constraint name cannot be rendered downstream even by accident — there is
// nothing left to render.
//
// The backend's own error contract is `{error: <slug>, message: <str>}`, or
// `{error: 'validation_error', details: [<str>, ...]}` with no message. See
// backend/api/README.md; the slug was previously ignored by this app entirely.

/** What went wrong, in the terms the UI actually needs to branch on. */
export type ApiFailure =
  /** Browser reports no connectivity. */
  | { kind: 'offline' }
  /** fetch() rejected: DNS, refused, CORS, TLS. Indistinguishable by design. */
  | { kind: 'network' }
  /** Our own budget elapsed and we aborted. */
  | { kind: 'timeout'; budgetMs: number }
  /** The caller aborted (user cancel, supersession, unmount). Never surfaced. */
  | { kind: 'canceled' }
  /** 400 validation_error — per-field reasons, written for users. */
  | { kind: 'validation'; status: number; slug: string | null; details: string[] }
  /** 400 bad_request / 422 domain_error — one reason, written for users. */
  | { kind: 'bad_input'; status: number; slug: string | null; message: string | null }
  | { kind: 'auth'; status: 401 | 403; slug: string | null }
  | { kind: 'not_found'; status: 404; slug: string | null }
  | { kind: 'rate_limited'; slug: string | null; retryAfterMs: number | null }
  /** 503, 504 — the service is up but can't serve right now. */
  | { kind: 'unavailable'; status: number; slug: string | null }
  /** 500, 502, any other 5xx — our bug or a dead upstream. */
  | { kind: 'server'; status: number; slug: string | null }
  /** 2xx whose body isn't JSON. In this deployment that is overwhelmingly the
   *  expired gate cookie: Caddy's forward_auth -> /api/gate/check answers 302
   *  to /gate, fetch follows it silently, and we get 200 + HTML. */
  | { kind: 'malformed'; status: number }

export type FailureKind = ApiFailure['kind']

/**
 * Thrown by apiRequest for every failure. `message` is a DEVELOPER string
 * (method, path, status) — never render it. Render `verbatim` when it is
 * non-null, otherwise `t(messageKey(failure))`.
 */
export class ApiError extends Error {
  readonly failure: ApiFailure
  readonly verbatim: string | null

  constructor(failure: ApiFailure, devDetail: string) {
    super(`api ${failure.kind}: ${devDetail}`)
    this.name = 'ApiError'
    this.failure = failure
    this.verbatim = safeVerbatim(failure)
  }
}

/**
 * The user-safe slice of the backend's text, or null. Only 'validation' and
 * 'bad_input' bodies are written for users; every other kind returns null even
 * when the response carried a `message`.
 */
function safeVerbatim(f: ApiFailure): string | null {
  if (f.kind === 'validation') {
    const joined = f.details.join(' ').trim()
    return joined.length > 0 ? joined : null
  }
  if (f.kind === 'bad_input') {
    const trimmed = f.message?.trim()
    return trimmed ? trimmed : null
  }
  return null
}

/** Narrow an unknown catch binding to its classified failure, or null if the
 *  rejection didn't come from apiRequest. */
export function asApiFailure(err: unknown): ApiFailure | null {
  return err instanceof ApiError ? err.failure : null
}

/** Backend `error` slugs we have reviewed copy for, keyed as errors.slug.<slug>.
 *  Gating the lookup on this set means an unrecognised or future slug falls back
 *  to its kind's copy instead of rendering a missing i18n key. Adding a slug the
 *  backend starts sending is one entry here plus one key in en.json. */
const SLUG_KEYS: ReadonlySet<string> = new Set([
  'invalid_code',
  'rate_limited',
  'data_not_loaded',
  'email_failed',
  'scenario_not_base',
])

const KIND_KEYS: Record<FailureKind, string> = {
  offline: 'errors.offline',
  network: 'errors.network',
  timeout: 'errors.timeout',
  // Never rendered (treatment is 'silent'); mapped so the table stays total.
  canceled: 'errors.network',
  validation: 'errors.badInput',
  bad_input: 'errors.badInput',
  auth: 'errors.unauthorized',
  not_found: 'errors.notFound',
  rate_limited: 'errors.slug.rate_limited',
  unavailable: 'errors.unavailable',
  server: 'errors.server',
  malformed: 'errors.malformed',
}

function readSlug(body: unknown): string | null {
  if (body && typeof body === 'object') {
    const slug = (body as Record<string, unknown>).error
    if (typeof slug === 'string' && slug) return slug
  }
  return null
}

function readMessage(body: unknown): string | null {
  if (body && typeof body === 'object') {
    const message = (body as Record<string, unknown>).message
    if (typeof message === 'string' && message) return message
  }
  return null
}

function readDetails(body: unknown): string[] {
  if (body && typeof body === 'object') {
    const details = (body as Record<string, unknown>).details
    if (Array.isArray(details)) return details.filter((d): d is string => typeof d === 'string')
  }
  return []
}

/**
 * Parse `Retry-After` (delta-seconds or HTTP-date) into milliseconds.
 * The backend does not send this header yet (api/limiter.py omits
 * headers_enabled), so this returns null today — written now so a backend
 * adding it needs no frontend change.
 */
function readRetryAfter(headers: Headers | undefined, now: number): number | null {
  const raw = headers?.get('Retry-After')
  if (!raw) return null
  const seconds = Number(raw)
  if (Number.isFinite(seconds)) return Math.max(0, seconds * 1000)
  const date = Date.parse(raw)
  return Number.isNaN(date) ? null : Math.max(0, date - now)
}

/** Classify a response we did receive. `body` is the parsed JSON, or null when
 *  the body was absent or unparseable (Caddy's upstream-failure 502 is empty). */
export function classify(status: number, body: unknown, headers?: Headers): ApiFailure {
  const slug = readSlug(body)

  if (status === 429) {
    return { kind: 'rate_limited', slug, retryAfterMs: readRetryAfter(headers, Date.now()) }
  }
  if (status === 401 || status === 403) {
    return { kind: 'auth', status, slug }
  }
  if (status === 404) {
    return { kind: 'not_found', status, slug }
  }
  if (status === 400 || status === 422) {
    const details = readDetails(body)
    if (details.length > 0) return { kind: 'validation', status, slug, details }
    return { kind: 'bad_input', status, slug, message: readMessage(body) }
  }
  if (status === 503 || status === 504) {
    return { kind: 'unavailable', status, slug }
  }
  if (status >= 500) {
    return { kind: 'server', status, slug }
  }
  // Any other non-2xx (405, 409, 413, 415, ...) — nothing actionable, and the
  // backend returns werkzeug HTML rather than JSON for several of these.
  return { kind: 'server', status, slug }
}

/** Classify a thrown fetch failure. `timedOut`/`canceled` disambiguate the
 *  AbortError, which is otherwise identical for both causes. */
export function classifyThrown(
  err: unknown,
  ctx: { timedOut: boolean; canceled: boolean; budgetMs?: number | null },
): ApiFailure {
  if (ctx.timedOut) return { kind: 'timeout', budgetMs: ctx.budgetMs ?? 0 }
  if (ctx.canceled) return { kind: 'canceled' }
  // navigator.onLine === true proves nothing, but false is reliable.
  if (typeof navigator !== 'undefined' && navigator.onLine === false) {
    return { kind: 'offline' }
  }
  void err
  return { kind: 'network' }
}

/** The i18n key whose copy describes this failure to a user. */
export function messageKey(f: ApiFailure): string {
  const slug = 'slug' in f ? f.slug : null
  if (slug && SLUG_KEYS.has(slug)) return `errors.slug.${slug}`
  return KIND_KEYS[f.kind]
}

/**
 * Where this failure belongs.
 * 'inline' — the user can act on it, so it goes next to the control.
 * 'toast'  — transient or systemic; not tied to one field.
 * 'silent' — we caused it (cancel/supersede/unmount); say nothing.
 */
export function treatment(f: ApiFailure): 'inline' | 'toast' | 'silent' {
  switch (f.kind) {
    case 'canceled':
      return 'silent'
    case 'validation':
    case 'bad_input':
    case 'not_found':
    case 'timeout':
      return 'inline'
    default:
      return 'toast'
  }
}

/**
 * Whether this failure is evidence the backend is in trouble, for the
 * consecutive-failure counter behind the degraded banner. `rate_limited` is
 * excluded on purpose — we caused that, the server is fine. `malformed` is a
 * session problem (expired gate cookie), not an outage.
 */
export function outcome(f: ApiFailure): 'outage' | 'ignore' {
  switch (f.kind) {
    case 'offline':
    case 'network':
    case 'timeout':
    case 'server':
    case 'unavailable':
      return 'outage'
    default:
      return 'ignore'
  }
}

/** Whether re-sending the same request could plausibly succeed. Drives whether
 *  a Retry control is offered — never an automatic retry. */
export function isRetryable(f: ApiFailure): boolean {
  return outcome(f) === 'outage' || f.kind === 'rate_limited'
}
