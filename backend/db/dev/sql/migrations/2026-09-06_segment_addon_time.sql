-- 2026-09-06_segment_addon_time.sql
-- ---------------------------------------------------------------------
-- proposals.segments: new addon_time_min column (ROUTE_BUILDER 0.9.32,
-- expert timetable mode).
--
-- A leg can now carry manual minutes the caller added by hand
-- (compute_request.expert_timetable.segment_addons). They are stored
-- apart from slack_time_min because the author differs: slack is the
-- model stretching a fixed-night interval to cover the night window,
-- addon is a person deciding this leg needs more time than the physics
-- say. Folding them into one column would make a stored timetable
-- unable to answer "who added these minutes", which is exactly what a
-- reader of an expert timetable wants to know.
--
-- Adding a NOT NULL column WITH a constant default is metadata-only on
-- PostgreSQL >= 11 (no table rewrite), so this is a safe online change
-- however many proposals are stored. Every route published before 0.9.32
-- reads back as 0, which is what api/helpers/route_serialize.py's
-- _segment_from_dict() fallback already assumes for pre-0.9.32 payloads.
--
-- Mirrors db/dev/sql/create_proposal_schema.sql, where fresh local seeds
-- get the column from; the comment text below is that column's.
-- ---------------------------------------------------------------------

ALTER TABLE proposals.segments
    ADD COLUMN IF NOT EXISTS addon_time_min INTEGER NOT NULL DEFAULT 0;

COMMENT ON COLUMN proposals.segments.addon_time_min IS 'Manual padding the caller put on this leg in expert timetable mode (compute_request.expert_timetable.segment_addons) — kept apart from slack_time_min because the author differs: slack is the model stretching an interval, this is a person. Never negative; 0 for every automatic timetable and every route stored before ROUTE_BUILDER 0.9.32. Unit: min';
