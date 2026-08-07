-- ============================================================
-- 2026-08-06_wp11_engagement_timeline.sql
-- WP11 — engagement API restructure + merged timeline.
--
-- No structural change. The endpoints moved (GET/POST/DELETE
-- /api/proposal/<id>/likes + GET/POST/PATCH/DELETE
-- /api/proposal/<id>/comments[/<cid>] became one aggregate read,
-- GET /api/proposal/<id>/engagements, plus singular writes on
-- /like and /comment[/<cid>]) and the soft-delete semantics
-- changed (a deleted comment is now returned by nothing), so the
-- DDL comments that documented the old contract would otherwise
-- lie to anyone introspecting the production schema.
--
-- No index is added for the timeline: it is a UNION ALL over three
-- tables with an outer ORDER BY, which sorts regardless, and the
-- per-proposal row counts are small. The existing per-proposal
-- indexes already serve the lookups.
--
-- Behavioural counterpart: api/proposal_engagement.py,
-- adapters/proposal/engagement_repository.py.
-- ============================================================

COMMENT ON TABLE  proposals.likes                  IS 'Thumbs-up on a proposal, one per user. Toggled via POST/DELETE /api/proposal/<id>/like; read (with comments and the timeline) via GET /api/proposal/<id>/engagements.';

COMMENT ON TABLE  proposals.comments                  IS 'Flat (non-threaded) comment thread per proposal. Written via POST/PATCH/DELETE /api/proposal/<id>/comment[/<cid>], read via GET /api/proposal/<id>/engagements.';
COMMENT ON COLUMN proposals.comments.is_deleted       IS 'Soft-delete flag, settable only by the comment''s own author. Storage-level tombstone: the row is kept so comment_id stays stable, but TRUE rows are returned by nothing — neither the thread nor the timeline (WP11).';
COMMENT ON COLUMN proposals.comments.updated_at       IS 'Bumped on edit and on soft-delete. Also the comment''s position in the timeline — an edited comment moves to its edit time (docs/PROPOSALS_DESIGN.md §7.5).';

COMMENT ON TABLE  proposals.update_log                  IS 'Append-only timeline event log for proposals. Unlike proposals.proposals (one row per proposal, previous states hard-deleted on overwrite), this preserves every state transition for the frontend timeline (§7.5, merged with comments + likes by GET /api/proposal/<id>/engagements). Written by adapters/proposal/repository.py inside the publish/refresh transaction, read by adapters/proposal/engagement_repository.py.';
COMMENT ON COLUMN proposals.update_log.user_id          IS 'Acting user; NULL for system events (version-bump/base-scenario refresh) — the timeline renders a NULL here as actor: null, which is what distinguishes a system recalculation from a user overwrite.';
