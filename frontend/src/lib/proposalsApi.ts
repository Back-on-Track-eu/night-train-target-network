// Thin client for POST /api/proposals — the filtered/sorted/paginated list of
// saved proposals shown in the Gallery. No generic API client exists to extend,
// so this mirrors the store's fetch pattern (stores/store.ts) and feedbackApi.ts.
// The list endpoint is public (no auth needed).

import type {
  ProposalsRequest,
  ProposalsResponse,
  ProposalsSummariesSection,
  ProposalDetailResponse,
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
 * Load one proposal's current version (route geometry + evaluation). Used by
 * the gallery map to draw the routes behind the search results. Rejects with a
 * ProposalsError on any network or non-2xx failure.
 */
export async function fetchProposalRoute(id: number): Promise<ProposalDetailResponse> {
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
  return parsed as ProposalDetailResponse
}
