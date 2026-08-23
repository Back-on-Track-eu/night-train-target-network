// Proposal read/write endpoints. All error handling, timeouts and cancellation
// live in apiClient — these are thin wrappers that name the endpoint, pick a
// budget class, and type the response.

import { apiRequest } from './apiClient'
import { ApiError } from './apiError'
import type {
  ProposalsRequest,
  ProposalsResponse,
  ProposalDetailResponse,
  PublishRequest,
  PublishResponse,
  LikeResponse,
} from '@/types/api'

/** Every failure is an ApiError; re-exported so callers need one import. */
export { ApiError }

/**
 * The gallery's one read: list page AND map in a single request. The response
 * is sectioned and the caller picks which sections to compute via `body.include`
 * (see ProposalsSection), so this returns the whole envelope rather than
 * unwrapping one section.
 */
export function fetchProposals(
  body: ProposalsRequest,
  signal?: AbortSignal,
): Promise<ProposalsResponse> {
  return apiRequest<ProposalsResponse>('/api/proposals', {
    method: 'POST',
    body,
    ...(signal ? { signal } : {}),
  })
}

/**
 * One proposal's current version (route + evaluation + metadata) — same wire
 * shape as publish's response. Used by ProposalViewport to open a stored
 * proposal; it needs the full route.
 *
 * Note this is not cheap on the server: it reconstructs the route and the whole
 * evaluation, and re-runs the version refresh, which can reach the routing
 * engine (api/helpers/proposal_load.py) — hence the interactive budget rather
 * than the reference one. Do not call it in a loop: anything that needs
 * geometry for many proposals at once wants POST /api/proposals' map sections.
 */
export function fetchProposalRoute<TRoute>(
  id: number,
  signal?: AbortSignal,
): Promise<ProposalDetailResponse<TRoute>> {
  return apiRequest<ProposalDetailResponse<TRoute>>(`/api/proposal/${id}`, {
    ...(signal ? { signal } : {}),
  })
}

/**
 * Publish (persist) a proposal — the only user write path. Requires an auth
 * header (a guest token is enough). The server recomputes from
 * `body.compute_request`, so this is as expensive as a calc: 'heavy', no
 * deadline (see apiClient's header for why aborting would not help).
 */
export function publishProposal(
  body: PublishRequest,
  authHeaders: Record<string, string>,
  opts?: { signal?: AbortSignal; onSlow?: (phase: 'slow' | 'verySlow') => void },
): Promise<PublishResponse> {
  return apiRequest<PublishResponse>('/api/proposal/publish', {
    method: 'POST',
    body,
    headers: authHeaders,
    budget: 'heavy',
    ...(opts?.signal ? { signal: opts.signal } : {}),
    ...(opts?.onSlow ? { onSlow: opts.onSlow } : {}),
  })
}

/**
 * Like/unlike. Both resolve with the resulting {count, liked_by_me}, so no
 * client-side toggle math is needed.
 */
function sendLike(
  method: 'POST' | 'DELETE',
  proposalId: number,
  authHeaders: Record<string, string>,
): Promise<LikeResponse> {
  return apiRequest<LikeResponse>(`/api/proposal/${proposalId}/like`, {
    method,
    headers: authHeaders,
  })
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
