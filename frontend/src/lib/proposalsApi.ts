// Thin client for POST /api/proposals — the filtered/sorted/paginated list of
// saved proposals shown in the Gallery. No generic API client exists to extend,
// so this mirrors the store's fetch pattern (stores/store.ts) and feedbackApi.ts.
// The list endpoint is public (no auth needed).

import type {
  ProposalsRequest,
  ProposalsResponse,
  ProposalsSummariesSection,
  ProposalDetailResponse,
  GalleryRouteShape,
  PublishRequest,
  PublishResponse,
  LikeResponse,
} from '@/types/api'

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:5050'

/** Carries a human-readable, already-surfaceable message for the UI. */
export class ProposalsError extends Error {}

/** Pull the most specific human-readable message out of an error body. */
function extractErrorMessage(body: unknown, status: number): string {
  if (body && typeof body === 'object') {
    const record = body as Record<string, unknown>
    const details = record.details
    if (Array.isArray(details) && details.length > 0) {
      return details.filter((d) => typeof d === 'string').join(' ')
    }
    if (typeof record.message === 'string' && record.message) {
      return record.message
    }
  }
  return `Request failed (HTTP ${status}).`
}

/**
 * Fetch one page of proposals. The list response is sectioned; the gallery
 * only requests summaries, so this unwraps and resolves with the `summaries`
 * section ({ total, proposals }). Rejects with a ProposalsError carrying a
 * readable message on any network or non-2xx failure.
 */
export async function fetchProposals(body: ProposalsRequest): Promise<ProposalsSummariesSection> {
  let response: Response
  try {
    response = await fetch(`${BASE_URL}/api/proposals`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  } catch (err) {
    throw new ProposalsError(err instanceof Error ? err.message : 'Network error')
  }

  let parsed: unknown = null
  try {
    parsed = await response.json()
  } catch {
    // Non-JSON body (unexpected) — fall through to the status-based message.
  }

  if (!response.ok) {
    throw new ProposalsError(extractErrorMessage(parsed, response.status))
  }
  return (parsed as ProposalsResponse).summaries ?? { total: 0, proposals: [] }
}

/**
 * Load one proposal's current version (route + evaluation + metadata) —
 * identical wire shape to POST /api/proposal/publish's response. Used by the
 * gallery map (route geometry only, the default TRoute) and by
 * ProposalViewport (the full route, via an explicit TRoute) to open a stored
 * proposal in display mode. Rejects with a ProposalsError on any network or
 * non-2xx failure.
 */
export async function fetchProposalRoute<TRoute = GalleryRouteShape>(
  id: number,
): Promise<ProposalDetailResponse<TRoute>> {
  let response: Response
  try {
    response = await fetch(`${BASE_URL}/api/proposal/${id}`)
  } catch (err) {
    throw new ProposalsError(err instanceof Error ? err.message : 'Network error')
  }

  let parsed: unknown = null
  try {
    parsed = await response.json()
  } catch {
    // Non-JSON body (unexpected) — fall through to the status-based message.
  }

  if (!response.ok) {
    throw new ProposalsError(extractErrorMessage(parsed, response.status))
  }
  return parsed as ProposalDetailResponse<TRoute>
}

/**
 * Publish (persist) a proposal — the only write path. Requires an auth header
 * (a guest token is enough); the caller passes `store.authHeaders()`. The server
 * recomputes from `body.compute_request`. Rejects with a ProposalsError carrying
 * a readable message on any network or non-2xx failure.
 */
export async function publishProposal(
  body: PublishRequest,
  authHeaders: Record<string, string>,
): Promise<PublishResponse> {
  let response: Response
  try {
    response = await fetch(`${BASE_URL}/api/proposal/publish`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders },
      body: JSON.stringify(body),
    })
  } catch (err) {
    throw new ProposalsError(err instanceof Error ? err.message : 'Network error')
  }

  let parsed: unknown = null
  try {
    parsed = await response.json()
  } catch {
    // Non-JSON body (unexpected) — fall through to the status-based message.
  }

  if (!response.ok) {
    throw new ProposalsError(extractErrorMessage(parsed, response.status))
  }
  return parsed as PublishResponse
}

/**
 * Like/unlike a proposal. Both require an auth header (a guest token is
 * accepted by the backend, but the like button only offers this to logged-in
 * accounts — see ProposalCard.vue). Both resolve with the resulting
 * {count, liked_by_me} directly, no client-side toggle math needed. Rejects
 * with a ProposalsError on any network or non-2xx failure.
 */
async function sendLike(
  method: 'POST' | 'DELETE',
  proposalId: number,
  authHeaders: Record<string, string>,
): Promise<LikeResponse> {
  let response: Response
  try {
    response = await fetch(`${BASE_URL}/api/proposal/${proposalId}/like`, {
      method,
      headers: { ...authHeaders },
    })
  } catch (err) {
    throw new ProposalsError(err instanceof Error ? err.message : 'Network error')
  }

  let parsed: unknown = null
  try {
    parsed = await response.json()
  } catch {
    // Non-JSON body (unexpected) — fall through to the status-based message.
  }

  if (!response.ok) {
    throw new ProposalsError(extractErrorMessage(parsed, response.status))
  }
  return parsed as LikeResponse
}

export function likeProposal(
  proposalId: number,
  authHeaders: Record<string, string>,
): Promise<LikeResponse> {
  return sendLike('POST', proposalId, authHeaders)
}

export function unlikeProposal(
  proposalId: number,
  authHeaders: Record<string, string>,
): Promise<LikeResponse> {
  return sendLike('DELETE', proposalId, authHeaders)
}
