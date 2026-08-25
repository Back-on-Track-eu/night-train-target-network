// POST /api/feedback — the anonymous (email reply-to) path used by the
// cost-factor feedback form in the evaluation panel's detail popover.
// Error handling, timeouts and classification live in apiClient.

import { apiRequest } from './apiClient'
import { ApiError } from './apiError'

/** Every failure is an ApiError; re-exported so callers need one import. */
export { ApiError }

/** Request body for a cost-factor feedback submission. */
export interface FeedbackPayload {
  /** Reply-to address for an anonymous submitter. Omitted when submitting as
   * a logged-in user — the backend derives the account's email from the
   * bearer token instead (see `authHeaders` on `submitFeedback`). */
  email?: string
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

/**
 * Submit feedback. Resolves with the 201 body; rejects with an ApiError whose
 * `verbatim` carries the backend's validation text when there is any, and is
 * null for a 500 (feedback.py's except-Exception returns str(e), which for a
 * failed INSERT is a psycopg2 message naming tables and constraints).
 */
export function submitFeedback(
  payload: FeedbackPayload,
  authHeaders: Record<string, string> = {},
): Promise<FeedbackSuccess> {
  return apiRequest<FeedbackSuccess>('/api/feedback', {
    method: 'POST',
    body: payload,
    headers: authHeaders,
  })
}
