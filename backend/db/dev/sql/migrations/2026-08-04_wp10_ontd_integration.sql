-- ============================================================
-- WP10 — ONTD integration (PROPOSALS_DESIGN.md §5.5, decisions 23–26).
--
-- The ontd schema has never existed in any environment (seed.py does not
-- create it, and the loader was never run) — there is no ontd data to
-- migrate. The full ontd DDL therefore lives ONLY in
-- create_ontd_schema.sql, which is safely re-runnable (destructive only
-- to refreshed tables; curated tables are CREATE TABLE IF NOT EXISTS)
-- and is applied by db/ontd/loader.py at the start of every run.
--
-- Migration procedure:
--   1. psql -f db/dev/sql/create_ontd_schema.sql   (or just run the loader)
--   2. this file — the one true ALTER, on the proposals schema
--
-- The ALTER below is folded into create_proposal_schema.sql's
-- proposal_summaries definition (usual two-copy convention).
-- ============================================================

ALTER TABLE proposals.proposal_summaries
    ADD COLUMN co2_g_per_pax_km NUMERIC(6,1);

COMMENT ON COLUMN proposals.proposal_summaries.co2_g_per_pax_km IS 'Night-train GHG intensity (§8, decision 24): the flat models/emissions factor until the energy-based, country-resolved model enriches it per route. Unit: g CO2e / pax-km';
