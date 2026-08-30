// Pure logic for the proposal comment thread — everything CommentSection.vue
// would otherwise do inline. Extracted so it is unit-testable without mounting
// the component (see the frontend test note in AGENTS.md).
//
// The thread arrives from GET /api/proposal/<id>/engagements oldest-first and
// every write returns the resulting row, so the functions below are patches
// against that server-owned order — never a re-sort, never a recount.

import type { Comment } from '@/types/api'

/**
 * Mirrors backend api/config.py::COMMENT_BODY_MAX_LEN. Restated here on
 * purpose, so a 4000-character paste is refused before a round trip rather
 * than by a 400 — but the SERVER IS AUTHORITATIVE: it is env-overridable
 * there, so treat a length rejection from the API as the real answer and this
 * as a courtesy.
 */
export const COMMENT_BODY_MAX_LEN = 4000

export type BodyProblem = 'empty' | 'tooLong'

/**
 * Why this body cannot be sent, or null when it can. Mirrors
 * validate_comment_body(): blank-after-trim is empty, and the cap is measured
 * on the RAW text (the server checks length before stripping, so trimming
 * first here would let a 4000-char body plus trailing newlines through to a
 * 400).
 */
export function validateBody(text: string): BodyProblem | null {
  if (!text.trim()) return 'empty'
  if (text.length > COMMENT_BODY_MAX_LEN) return 'tooLong'
  return null
}

/** Characters still available — negative once over the cap, so a counter can
 *  show how far over the user is rather than clamping at zero. */
export function charsRemaining(text: string): number {
  return COMMENT_BODY_MAX_LEN - text.length
}

/**
 * Whether a comment has been edited since it was posted. Same rule the backend
 * timeline uses (`updated_at > created_at`), compared as ISO-8601 strings:
 * both come from the same column type in the same response, so they are
 * always the same shape and lexicographic order matches chronological order.
 */
export function wasEdited(comment: Comment): boolean {
  return comment.updated_at > comment.created_at
}

/**
 * Whether the current user may edit/delete this comment. The server enforces
 * this (403 otherwise); this only decides whether to OFFER the controls.
 *
 * A null user_id is a deleted account, never "mine" — without that guard a
 * logged-out viewer (userId null) would be offered controls on every orphaned
 * comment in the thread.
 */
export function isOwnComment(comment: Comment, userId: number | null): boolean {
  return userId !== null && comment.user_id === userId
}

// --- Thread patches ---------------------------------------------------------
// All three return a NEW array: the caller assigns it to a ref, and Vue sees a
// change without needing deep reactivity on the rows.

/** Append a freshly posted comment. Oldest-first, so a new one belongs last. */
export function applyPosted(comments: Comment[], posted: Comment): Comment[] {
  return [...comments, posted]
}

/**
 * Replace a comment with its edited version. Position is preserved even though
 * the backend TIMELINE moves an edited comment to its edit time — the thread
 * and the timeline deliberately order differently, and re-sorting a thread
 * under the reader mid-edit would be its own bug.
 */
export function applyEdited(comments: Comment[], edited: Comment): Comment[] {
  return comments.map((c) => (c.comment_id === edited.comment_id ? edited : c))
}

/** Drop a deleted comment. The server soft-deletes, but the row never comes
 *  back from any endpoint, so the thread has no tombstone to hold. */
export function applyDeleted(comments: Comment[], commentId: number): Comment[] {
  return comments.filter((c) => c.comment_id !== commentId)
}

// --- Timestamps -------------------------------------------------------------

/**
 * How old a comment is, as a unit + value rather than a formatted string:
 * the copy belongs in i18n (pluralized), not in here. `now` is injected so the
 * result is deterministic under test.
 *
 * A timestamp in the future (clock skew between server and browser) reads as
 * 'now' rather than a negative age — the alternative is "in 3 minutes" on a
 * comment the user just posted.
 */
export type CommentAge =
  | { unit: 'now' }
  | { unit: 'minutes'; value: number }
  | { unit: 'hours'; value: number }
  | { unit: 'days'; value: number }
  | { unit: 'date' }

const MINUTE_MS = 60_000
const HOUR_MS = 60 * MINUTE_MS
const DAY_MS = 24 * HOUR_MS
/** Past a week, "6 days ago" stops helping and a real date starts. */
const ABSOLUTE_AFTER_MS = 7 * DAY_MS

export function commentAge(iso: string, now: Date): CommentAge {
  const then = new Date(iso).getTime()
  // An unparseable timestamp must not render "NaN minutes ago"; showing the
  // raw date is the honest fallback.
  if (Number.isNaN(then)) return { unit: 'date' }

  const elapsed = now.getTime() - then
  if (elapsed < MINUTE_MS) return { unit: 'now' }
  if (elapsed < HOUR_MS) return { unit: 'minutes', value: Math.floor(elapsed / MINUTE_MS) }
  if (elapsed < DAY_MS) return { unit: 'hours', value: Math.floor(elapsed / HOUR_MS) }
  if (elapsed < ABSOLUTE_AFTER_MS) return { unit: 'days', value: Math.floor(elapsed / DAY_MS) }
  return { unit: 'date' }
}
