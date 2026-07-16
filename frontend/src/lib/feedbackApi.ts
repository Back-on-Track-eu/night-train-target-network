// Thin client for POST /api/feedback — the anonymous (email reply-to) path
// used by the cost-factor feedback form in the evaluation panel's detail
// popover. Same hardcoded backend origin as the store (stores/store.ts); no
// generic API client exists to extend, so this mirrors that fetch pattern.

const BASE_URL = 'http://localhost:5000'

/** Request body for a cost-factor feedback submission (anonymous path). */
export interface FeedbackPayload {
  /** Reply-to address for the anonymous submitter (backend requires it). */
  email: string
  /** Auto-generated subject line, max 200 chars (backend-enforced). */
  subject: string
  /** Free-text category taxonomy value (protocol constant). */
  category: string
  /** Dotted Breakdown path of the cost factor (protocol value). */
  sub_category: string
  /** The user's feedback text. */
  message: string
}

/** Success body of POST /api/feedback (201). */
export interface FeedbackSuccess {
  feedback_id: number
  created_at: string
  email_sent: boolean
}

/** Carries a human-readable, already-surfaceable message for the UI. */
export class FeedbackError extends Error {}

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
 * Submit feedback. Resolves with the 201 body on success; rejects with a
 * FeedbackError carrying a readable message (backend `details`/`message`
 * where present) on any network or non-2xx failure.
 */
export async function submitFeedback(payload: FeedbackPayload): Promise<FeedbackSuccess> {
  let response: Response
  try {
    response = await fetch(`${BASE_URL}/api/feedback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
  } catch (err) {
    throw new FeedbackError(err instanceof Error ? err.message : 'Network error')
  }

  let body: unknown = null
  try {
    body = await response.json()
  } catch {
    // Non-JSON body (unexpected) — fall through to the status-based message.
  }

  if (!response.ok) {
    throw new FeedbackError(extractErrorMessage(body, response.status))
  }
  return body as FeedbackSuccess
}
