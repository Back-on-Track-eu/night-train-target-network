-- 2026-10-03 — proposal_corridors (adapters/proposal/README.md §5.4b): the
-- gallery's corridor overview precomputed, so POST /api/proposals'
-- map_lines stops walking every segment of every proposal per request
-- (31 s on production's 1,334 proposals; the whole unfiltered gallery
-- timed out on it).
--
-- Additive: a new table, nothing existing touched. Rows arrive with every
-- publish/refresh from the api version that ships this file (backend
-- 0.5.11); proposals published before it have none until the data task
--
--     python db/run_tasks.py        (db/tasks/2026-10-03_backfill_proposal_corridors.py)
--
-- has run — pure SQL over data already stored, no routing engine, about a
-- minute. Until then map_lines falls back to the request-time derivation,
-- so the gallery is correct throughout — only slow.
--
-- Deploy order: migration, api, data tasks (the compose one-shot runs
-- them). Dev counterpart: db/dev/sql/create_proposal_schema.sql.

-- ---------------------------------------------------------------
-- proposal_corridors (§5.4b) — the gallery's corridor overview
-- (POST /api/proposals `map_lines`), precomputed: one row per
-- (proposal, scenario variant, direction-collapsed stop pair), geometry
-- already simplified to the overview tolerance
-- (adapters/proposal/repository.py MAP_LINES_SIMPLIFY_TOLERANCE_DEG).
-- Until 2026-10-03 map_lines derived this at request time by walking
-- proposals.trips -> segments -> shapes (base) or the scenario rows'
-- `segments` JSON (variants) and parsing every representative shape at
-- full resolution — 31 s and 8.8 MB on production's 1,334 proposals.
--
-- Same discipline as the other projections: derived, rebuildable, written
-- in the same transaction as every publish/refresh (_write_state() ->
-- _replace_corridors()) and whenever the scenario rows are replaced;
-- backfilled by db/tasks/2026-10-03_backfill_proposal_corridors.py. A
-- proposal whose rows are missing makes map_lines fall back to the
-- request-time derivation (repository.map_lines()), so the gallery is
-- never wrong while the backfill runs — only slow.
--
-- scenario_variant_id NULL is the base projection (what a request
-- without scenario_variant_id reads); a non-base variant has rows only
-- where its scenario row is status 'ok'. UNIQUE NULLS NOT DISTINCT keeps
-- the base rows unique too (one NULL per stop pair).
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS proposals.proposal_corridors (
    proposal_id         INTEGER NOT NULL REFERENCES proposals.proposals(proposal_id) ON DELETE CASCADE,
    proposal_version    INTEGER NOT NULL,
    scenario_variant_id INTEGER,
    stop_a              TEXT    NOT NULL,
    stop_b              TEXT    NOT NULL,
    geometry_routed     BOOLEAN NOT NULL,
    geom                geometry(LineString, 4326) NOT NULL,
    UNIQUE NULLS NOT DISTINCT (proposal_id, scenario_variant_id, stop_a, stop_b)
);

CREATE INDEX IF NOT EXISTS idx_proposal_corridors_pair ON proposals.proposal_corridors (stop_a, stop_b);

COMMENT ON TABLE  proposals.proposal_corridors                     IS 'Precomputed corridor pieces for the gallery''s map_lines (§5.4b): one row per (proposal, scenario variant, stop pair), geometry simplified for overview zoom at write time. Derived, NOT a source of truth: rewritten with every publish/refresh and whenever the scenario rows are replaced; backfilled by db/tasks/2026-10-03_backfill_proposal_corridors.py. Missing rows make map_lines fall back to deriving corridors at request time.';
COMMENT ON COLUMN proposals.proposal_corridors.scenario_variant_id IS 'NULL = the base projection (proposals.segments/shapes of the stored route); otherwise the §5.4a variant whose scenario row (status ok) the corridor came from.';
COMMENT ON COLUMN proposals.proposal_corridors.stop_a              IS 'Smaller stop id of the pair (direction collapsed, same grain as ontd.route_corridors).';
COMMENT ON COLUMN proposals.proposal_corridors.stop_b              IS 'Larger stop id of the pair.';
COMMENT ON COLUMN proposals.proposal_corridors.geometry_routed     IS 'Whether the UNSIMPLIFIED shape had more than two points — measured before simplification so a routed line that happens to run straight is not mislabelled a two-stop placeholder.';
COMMENT ON COLUMN proposals.proposal_corridors.geom                IS 'The corridor''s representative shape (the first segment over this pair, by shape id), Douglas-Peucker simplified at MAP_LINES_SIMPLIFY_TOLERANCE_DEG (~200 m).';
