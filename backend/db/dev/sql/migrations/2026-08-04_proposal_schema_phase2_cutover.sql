-- ============================================================
-- 2026-08-04_proposal_schema_phase2_cutover.sql
-- Proposals redesign, schema phase 2 (finalizing) — WP5 of
-- docs/PROPOSALS_DESIGN.md's implementation plan (§10). The single
-- migration that atomically finalizes the schema alongside the code that
-- requires it (adapters/proposal_repository.py's publish(), WP5).
--
-- Data strategy (decided, §10 WP5 "Data strategy"): drop and recreate,
-- no row migration. Every proposal-storage table is truncated —
-- currently stored proposals are pre-launch test artifacts, nothing to
-- reseed (proposals are user-generated content; the params/ONTD/scenario
-- schemas are untouched). Engagement tables (likes, comments,
-- update_log) keep their structure (soft references survive) but their
-- stale pre-cutover rows are truncated in the same migration for a clean
-- start. The compute-cache tables (§2.3, empty until WP13) are included
-- for completeness, not because they hold anything yet.
--
-- Drops (§5.3 "Dropped vs. the current implementation"): route_body,
-- evaluation_body, is_current (+ its partial unique index), change_log.
-- Adds: name (added here per the WP5 design-gap decision — proposal
-- identity/metadata, not projection-only, see docs/PROPOSALS_DESIGN.md's
-- WP5 entry), composition_id, scenario_id, route_builder_version,
-- calc_version, evaluation_output, updated_at. Changes: primary key from
-- (proposal_id, proposal_version) to proposal_id alone — one row per
-- proposal, no version history (§4: previous state hard-deleted on
-- overwrite, update_log is the append-only timeline instead).
-- ============================================================

-- ---------------------------------------------------------------
-- Truncate every proposal-storage table. CASCADE follows the FK graph
-- structurally (regardless of each FK's own ON DELETE action), so listing
-- every table once here is sufficient — no ordering dependency.
-- ---------------------------------------------------------------
TRUNCATE TABLE
    proposals.proposals,
    proposals.proposal_summaries,
    proposals.routes,
    proposals.trips,
    proposals.stop_times,
    proposals.shapes,
    proposals.services,
    proposals.calendar,
    proposals.calendar_dates,
    proposals.segments,
    proposals.od_pairs,
    proposals.parkings,
    proposals.shuntings,
    proposals.timetable_warnings,
    proposals.seasonal_schedules,
    proposals.update_log,
    proposals.likes,
    proposals.comments,
    proposals.compute_cache_pointer,
    proposals.compute_cache_result
CASCADE;

-- ---------------------------------------------------------------
-- proposals.proposals — drop the old persist-on-calc columns + their
-- partial unique index (must drop the index before the column it
-- indexes), change the primary key, add the §5.3 columns. The table is
-- empty after the TRUNCATE above, so ADD COLUMN ... NOT NULL needs no
-- DEFAULT to satisfy existing rows.
-- ---------------------------------------------------------------
DROP INDEX IF EXISTS proposals.idx_proposals_one_current_per_id;

ALTER TABLE proposals.proposals
    DROP COLUMN route_body,
    DROP COLUMN evaluation_body,
    DROP COLUMN is_current,
    DROP COLUMN change_log;

ALTER TABLE proposals.proposals
    DROP CONSTRAINT proposals_pkey,
    ADD PRIMARY KEY (proposal_id);

ALTER TABLE proposals.proposals
    ADD COLUMN name                   TEXT NOT NULL,
    ADD COLUMN composition_id         TEXT NOT NULL,
    ADD COLUMN scenario_id            INTEGER NOT NULL,
    ADD COLUMN route_builder_version  TEXT NOT NULL,
    ADD COLUMN calc_version           TEXT NOT NULL,
    ADD COLUMN evaluation_output      JSON NOT NULL,
    ADD COLUMN updated_at             TIMESTAMPTZ NOT NULL DEFAULT now();

ALTER TABLE proposals.proposals
    ALTER COLUMN route_fingerprint SET NOT NULL,
    ALTER COLUMN compute_request SET NOT NULL;

COMMENT ON TABLE  proposals.proposals                  IS 'One row per proposal, always current (§5.3, WP5 slimmed schema) — no version history: proposal_version is an internal state counter bumped on every overwrite-publish/refresh, the previous state is hard-deleted in the same transaction (§4). Route lives in GTFS + sidecar tables, not here; evaluation_output holds only models+views (§5.1) — input.parameters is rebuilt on read via the scenario_id pin.';
COMMENT ON COLUMN proposals.proposals.name             IS 'User-supplied proposal name. Deliberately on the container (not only proposal_summaries) — identity/metadata a load must be able to return even if the summary projection were ever rebuilt from scratch.';
COMMENT ON COLUMN proposals.proposals.composition_id   IS 'The proposal''s current composition — an overwrite-publish may change it like any other input. Soft reference to input_params.composition_types.composition_type_id.';
COMMENT ON COLUMN proposals.proposals.scenario_id      IS 'The base snapshot the stored evaluation ran under — always the current base at publish time (§2.2); system-managed via the version-refresh mechanism (§4.2, WP8) when the base moves. Currentness derived by joining scenario.scenarios, not stored as a flag.';
COMMENT ON COLUMN proposals.proposals.route_builder_version IS 'ROUTE_BUILDER_VERSION the route was built with — drives the version-refresh mechanism (§4.2).';
COMMENT ON COLUMN proposals.proposals.calc_version     IS 'CALC_VERSION the evaluation ran with — drives the version-refresh mechanism (§4.2). Always populated: every proposal has route AND evaluation, no half-states (§2.4).';
COMMENT ON COLUMN proposals.proposals.compute_request  IS 'Resolved POST /api/proposal/calc request, verbatim (§2.1). NOT NULL — every publish carries one, freshly computed or reused from the compute cache (§2.2 integrity rule).';
COMMENT ON COLUMN proposals.proposals.evaluation_output IS 'The computed evaluation''s models + views only (§5.1) — NOT input.parameters (rebuilt on read via the scenario_id pin) and NOT a route copy (route lives in GTFS + sidecars). JSON, not JSONB — same key-order rationale as historically applied to this schema''s JSON columns.';
COMMENT ON COLUMN proposals.proposals.route_fingerprint IS 'Route identity fingerprint (§3.1) — informational only, no lookup/index depends on it. NOT NULL as of this migration (WP5) — every publish computes and stores one.';
COMMENT ON COLUMN proposals.proposals.updated_at       IS 'Bumped on every overwrite-publish and system refresh — what proposal_summaries.updated_at and gallery "newest first" sort key off.';

-- ---------------------------------------------------------------
-- stop_times.stop_type — always populated by the sole write path
-- (route_gtfs_serialize.insert_route_gtfs()) as of WP5; enforce NOT NULL
-- now that the table is empty (post-TRUNCATE) rather than leaving it as
-- the phase-1 placeholder nullable.
-- ---------------------------------------------------------------
ALTER TABLE proposals.stop_times
    ALTER COLUMN stop_type SET NOT NULL;

COMMENT ON COLUMN proposals.stop_times.stop_type IS 'Lossless stop classification: boarding, alighting, night, or both (mirrors models.route.trip.StopType) — not losslessly encoded by pickup_type/drop_off_type alone ("night" and "both" both map to (0,0)). NOT NULL as of WP5 — the sole write path (route_gtfs_serialize.insert_route_gtfs()) always sets it.';
