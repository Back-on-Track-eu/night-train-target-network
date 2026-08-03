-- ============================================================
-- 2026-08-04_proposal_summaries_created_at.sql
-- WP6.1 revision (docs/PROPOSALS_DESIGN.md §7.1) — gallery filtering by
-- created_at/updated_at needs a created_at column on the summary
-- projection itself; §7.1's own design principle ("all list/filter/
-- sort/aggregate work runs in SQL against proposal_summaries") is what
-- rules out just joining proposals.proposals.created_at at query time.
--
-- Backfilled from proposals.proposals.created_at (the one place this
-- value already exists) rather than defaulting every existing row to
-- now() — a soft-reference UPDATE...FROM join, same convention every
-- other proposal_summaries write already uses (no FK, §5.4).
-- ============================================================

ALTER TABLE proposals.proposal_summaries
    ADD COLUMN created_at TIMESTAMPTZ NOT NULL DEFAULT now();

UPDATE proposals.proposal_summaries s
SET created_at = p.created_at
FROM proposals.proposals p
WHERE p.proposal_id = s.proposal_id;

COMMENT ON COLUMN proposals.proposal_summaries.created_at IS 'Set once at the proposal''s first publish, never touched by an overwrite-publish or refresh — repository.py''s _upsert_summary() excludes it from the ON CONFLICT UPDATE. Gallery filter/sort target (WP6.1).';
