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
  Comment,
  EngagementResponse,
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

/**
 * Likes + comment thread + timeline for one proposal, in one request. The
 * endpoint is open (optional_auth), but PASS THE AUTH HEADERS ANYWAY when the
 * caller has them: `likes.liked_by_me` is always false without them, which is
 * exactly the wrong-icon bug the gallery card has to live with.
 */
export function fetchEngagements(
  proposalId: number,
  authHeaders: Record<string, string>,
  signal?: AbortSignal,
): Promise<EngagementResponse> {
  return apiRequest<EngagementResponse>(`/api/proposal/${proposalId}/engagements`, {
    headers: authHeaders,
    ...(signal ? { signal } : {}),
  })
}

/** Post a comment. Resolves with the created row (201), ready to append. */
export function postComment(
  proposalId: number,
  body: string,
  authHeaders: Record<string, string>,
): Promise<Comment> {
  return apiRequest<Comment>(`/api/proposal/${proposalId}/comment`, {
    method: 'POST',
    body: { body },
    headers: authHeaders,
  })
}

/** Edit own comment. Author-only server-side: 403 for anyone else. */
export function editComment(
  proposalId: number,
  commentId: number,
  body: string,
  authHeaders: Record<string, string>,
): Promise<Comment> {
  return apiRequest<Comment>(`/api/proposal/${proposalId}/comment/${commentId}`, {
    method: 'PATCH',
    body: { body },
    headers: authHeaders,
  })
}

/**
 * Delete own comment. The only endpoint in the API that answers 204, hence
 * allowEmpty — see apiClient's empty-body check. The delete is soft server-side
 * but the row leaves the thread for good, so callers just drop it.
 */
export function deleteComment(
  proposalId: number,
  commentId: number,
  authHeaders: Record<string, string>,
): Promise<void> {
  return apiRequest<void>(`/api/proposal/${proposalId}/comment/${commentId}`, {
    method: 'DELETE',
    headers: authHeaders,
    allowEmpty: true,
  })
}
