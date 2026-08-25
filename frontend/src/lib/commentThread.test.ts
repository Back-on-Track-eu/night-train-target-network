import { describe, it, expect } from 'vitest'
import {
  COMMENT_BODY_MAX_LEN,
  validateBody,
  charsRemaining,
  wasEdited,
  isOwnComment,
  applyPosted,
  applyEdited,
  applyDeleted,
  commentAge,
} from './commentThread'
import type { Comment } from '@/types/api'

// The columns are TIMESTAMPTZ, so the backend's isoformat() always carries an
// offset — the fixtures keep it, since a naive string would be parsed as LOCAL
// time by Date and quietly shift every age by the runner's UTC offset.
function comment(over: Partial<Comment> = {}): Comment {
  return {
    comment_id: 1,
    proposal_id: 7,
    proposal_version: 2,
    user_id: 42,
    user_name: 'Ada',
    body: 'Sleeper to Lisbon, please.',
    created_at: '2026-08-23T10:00:00+00:00',
    updated_at: '2026-08-23T10:00:00+00:00',
    ...over,
  }
}

describe('validateBody', () => {
  it('accepts ordinary text', () => {
    expect(validateBody('Looks great')).toBeNull()
  })

  it('rejects blank and whitespace-only bodies', () => {
    expect(validateBody('')).toBe('empty')
    expect(validateBody('   \n\t ')).toBe('empty')
  })

  it('rejects a body over the cap', () => {
    expect(validateBody('x'.repeat(COMMENT_BODY_MAX_LEN))).toBeNull()
    expect(validateBody('x'.repeat(COMMENT_BODY_MAX_LEN + 1))).toBe('tooLong')
  })

  it('measures the cap on raw text, as the server does', () => {
    // Trailing whitespace still counts: the backend checks length before
    // stripping, so trimming here would let a 400 through.
    expect(validateBody('x'.repeat(COMMENT_BODY_MAX_LEN) + '  ')).toBe('tooLong')
  })
})

describe('charsRemaining', () => {
  it('counts down and goes negative past the cap', () => {
    expect(charsRemaining('')).toBe(COMMENT_BODY_MAX_LEN)
    expect(charsRemaining('abc')).toBe(COMMENT_BODY_MAX_LEN - 3)
    expect(charsRemaining('x'.repeat(COMMENT_BODY_MAX_LEN + 5))).toBe(-5)
  })
})

describe('wasEdited', () => {
  it('is false for an untouched comment', () => {
    expect(wasEdited(comment())).toBe(false)
  })

  it('is true once updated_at moves past created_at', () => {
    expect(wasEdited(comment({ updated_at: '2026-08-23T10:04:00+00:00' }))).toBe(true)
  })
})

describe('isOwnComment', () => {
  it('matches the author', () => {
    expect(isOwnComment(comment({ user_id: 42 }), 42)).toBe(true)
    expect(isOwnComment(comment({ user_id: 43 }), 42)).toBe(false)
  })

  it('never claims a deleted account for a logged-out viewer', () => {
    expect(isOwnComment(comment({ user_id: null, user_name: '[deleted]' }), null)).toBe(false)
  })

  it('is false for any comment when nobody is logged in', () => {
    expect(isOwnComment(comment(), null)).toBe(false)
  })
})

describe('thread patches', () => {
  const a = comment({ comment_id: 1 })
  const b = comment({ comment_id: 2 })

  it('appends a posted comment last (thread is oldest-first)', () => {
    expect(applyPosted([a], b).map((c) => c.comment_id)).toEqual([1, 2])
  })

  it('replaces an edited comment in place', () => {
    const edited = comment({ comment_id: 1, body: 'changed my mind' })
    const result = applyEdited([a, b], edited)
    expect(result.map((c) => c.comment_id)).toEqual([1, 2])
    expect(result[0].body).toBe('changed my mind')
  })

  it('removes a deleted comment', () => {
    expect(applyDeleted([a, b], 1).map((c) => c.comment_id)).toEqual([2])
  })

  it('returns new arrays rather than mutating', () => {
    const original = [a, b]
    applyPosted(original, comment({ comment_id: 3 }))
    applyDeleted(original, 1)
    expect(original.map((c) => c.comment_id)).toEqual([1, 2])
  })

  it('leaves the thread alone for an unknown comment_id', () => {
    expect(applyDeleted([a, b], 99)).toHaveLength(2)
    expect(applyEdited([a, b], comment({ comment_id: 99 }))).toHaveLength(2)
  })
})

describe('commentAge', () => {
  const now = new Date('2026-08-23T12:00:00+00:00')

  it('reads under a minute as "now"', () => {
    expect(commentAge('2026-08-23T11:59:30+00:00', now)).toEqual({ unit: 'now' })
  })

  it('counts minutes, then hours, then days', () => {
    expect(commentAge('2026-08-23T11:30:00+00:00', now)).toEqual({ unit: 'minutes', value: 30 })
    expect(commentAge('2026-08-23T09:00:00+00:00', now)).toEqual({ unit: 'hours', value: 3 })
    expect(commentAge('2026-08-20T12:00:00+00:00', now)).toEqual({ unit: 'days', value: 3 })
  })

  it('switches to an absolute date past a week', () => {
    expect(commentAge('2026-08-16T11:00:00+00:00', now)).toEqual({ unit: 'date' })
  })

  it('treats a future timestamp as "now" rather than a negative age', () => {
    // Server/browser clock skew — a just-posted comment must not read
    // "in 2 minutes".
    expect(commentAge('2026-08-23T12:02:00+00:00', now)).toEqual({ unit: 'now' })
  })

  it('falls back to a date for an unparseable timestamp', () => {
    expect(commentAge('not a date', now)).toEqual({ unit: 'date' })
  })
})
