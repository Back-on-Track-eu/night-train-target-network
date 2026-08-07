-- ============================================================
-- 2026-08-03_proposal_schema_phase1b_auto_added.sql
-- Proposals redesign, schema phase 1b (additive only) — WP3 of
-- docs/PROPOSALS_DESIGN.md's implementation plan (§10).
--
-- Closes a round-trip gap phase 1 (2026-08-03_proposal_schema_phase1.sql)
-- missed: Stop.auto_added (models/route/trip.py — whether
-- auto_stop_addition inserted this stop) has no column anywhere in the
-- GTFS/sidecar schema. Without it, api/helpers/route_gtfs_serialize.py's
-- route_dict_from_gtfs() cannot reconstruct auto_added=true for any stop
-- that auto_stop_addition actually inserted — silently downgrading it to
-- false and breaking §5.1's "reconstruction deep-equals the original
-- compute result" guarantee for any route where "add" mode did anything.
-- Not derivable after the fact (it's a record of what the one-time
-- candidate search decided, not something recomputable from stored
-- physics), so it has to be stored, same as stop_type.
-- ============================================================

ALTER TABLE proposals.stop_times
    ADD COLUMN auto_added BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN proposals.stop_times.auto_added IS 'Mirrors models.route.trip.Stop.auto_added — true if auto_stop_addition inserted this stop (vs. the caller''s own stop list). Default FALSE matches Stop''s own dataclass default. Closes a round-trip gap in the 2026-08-03 phase 1 migration — see WP3 in docs/PROPOSALS_DESIGN.md §10.';
