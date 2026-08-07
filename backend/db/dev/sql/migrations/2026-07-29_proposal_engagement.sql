-- ============================================================
-- 2026-07-29_proposal_engagement.sql
-- Adds proposal rating (thumbs-up "like") and commenting.
-- Behavioural counterpart: api/proposal_engagement.py,
-- adapters/proposal_engagement_repository.py.
-- ============================================================

-- ---------------------------------------------------------------
-- likes: one thumbs-up per (proposal, user). No down-vote — a
-- missing row simply means "not liked". proposal_id is a soft
-- reference to proposals.proposals, same convention as
-- stop_times.stop_id / trips.composition_type_id — the composite
-- (proposal_id, proposal_version) primary key there means
-- proposal_id alone can't be an FK target, so existence is
-- checked at the API layer instead.
-- ---------------------------------------------------------------
CREATE TABLE proposals.likes (
    like_id           SERIAL PRIMARY KEY,
    proposal_id       INTEGER NOT NULL,
    proposal_version  INTEGER NOT NULL,
    user_id           INTEGER NOT NULL REFERENCES admin.users(user_id) ON DELETE CASCADE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (proposal_id, user_id)
);

CREATE INDEX idx_likes_proposal ON proposals.likes (proposal_id);

COMMENT ON TABLE  proposals.likes                  IS 'Thumbs-up on a proposal, one per user. Toggled via POST/DELETE /api/proposal/<id>/likes.';
COMMENT ON COLUMN proposals.likes.proposal_id      IS 'Soft reference to proposals.proposals.proposal_id — validated at the API layer (see module docstring), not a DB constraint.';
COMMENT ON COLUMN proposals.likes.proposal_version IS 'proposal_version that was current at the moment of liking — a context stamp only, not re-derived if the proposal is later versioned.';
COMMENT ON COLUMN proposals.likes.user_id          IS 'admin.users identity of the liker. CASCADE: a deleted account takes its likes with it, since an anonymous like would break the one-per-user constraint''s meaning.';

-- ---------------------------------------------------------------
-- comments: flat (non-threaded) discussion per proposal. Soft
-- delete preserves chronological context even after removal.
-- ---------------------------------------------------------------
CREATE TABLE proposals.comments (
    comment_id        SERIAL PRIMARY KEY,
    proposal_id       INTEGER NOT NULL,
    proposal_version  INTEGER NOT NULL,
    user_id           INTEGER REFERENCES admin.users(user_id) ON DELETE SET NULL,
    body              TEXT NOT NULL,
    is_deleted        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_comments_proposal ON proposals.comments (proposal_id, created_at);

COMMENT ON TABLE  proposals.comments                  IS 'Flat (non-threaded) comment thread per proposal. Soft-deleted rows keep their place in the list with the body cleared, rather than being removed outright.';
COMMENT ON COLUMN proposals.comments.proposal_id      IS 'Soft reference to proposals.proposals.proposal_id — same convention as proposals.likes.proposal_id.';
COMMENT ON COLUMN proposals.comments.proposal_version IS 'proposal_version that was current at the moment of commenting — a context stamp only, not re-derived on later versions.';
COMMENT ON COLUMN proposals.comments.user_id          IS 'admin.users identity of the author. SET NULL on account deletion (same pattern as admin.feedback.user_id) so the comment text survives; the API renders a null user_id as a deleted-user placeholder.';
COMMENT ON COLUMN proposals.comments.body             IS 'Comment text. Cleared server-side (empty string) when is_deleted is set — the API never trusts a client-supplied deleted body.';
COMMENT ON COLUMN proposals.comments.is_deleted       IS 'Soft-delete flag, settable only by the comment''s own author. TRUE rows are still returned by GET (with body cleared) so the thread stays chronologically intact.';
COMMENT ON COLUMN proposals.comments.updated_at       IS 'Bumped on edit and on soft-delete.';
