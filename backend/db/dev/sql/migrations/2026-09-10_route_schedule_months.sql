-- 2026-09-10 — the per-month schedule on proposals.routes
-- ROUTE_BUILDER 0.9.35 replaced the summer/winter x daily/three_per_week
-- schedule with days-per-week for each month plus a minimum turnaround.
-- proposals.seasonal_schedules only holds the two-season projection, so a
-- per-month plan was widened on reload. This gives it a home.
--
-- Additive and idempotent. seasonal_schedules stays: gtfs_store still writes
-- the projection for readers that expect it, and reads schedule_months first.
-- Rows written before this migration have NULLs and are read from the
-- projection exactly as before, so no backfill is needed.
--
-- Dev counterpart: db/dev/seed.py _catch_up_columns and
-- create_proposal_schema.sql.

ALTER TABLE proposals.routes
    ADD COLUMN IF NOT EXISTS schedule_months    JSONB,
    ADD COLUMN IF NOT EXISTS min_turnaround_min INTEGER;

COMMENT ON COLUMN proposals.routes.schedule_months    IS 'Days per week for each month, {"1": 7, ..., "12": 0} (models/route/route.py Schedule). NULL on rows written before ROUTE_BUILDER 0.9.35 — read seasonal_schedules instead.';
COMMENT ON COLUMN proposals.routes.min_turnaround_min IS 'Minimum terminal turnaround the fleet was sized with, minutes. NULL before 0.9.35 (default 180).';

-- CALC 0.9.28: the summary row gains two supply KPIs. The publish
-- projection (adapters/proposal/repository.py) writes every summary key as
-- a column, so these must exist before the api image that produces them.
ALTER TABLE proposals.proposal_summaries
    ADD COLUMN IF NOT EXISTS departures_per_year INTEGER  NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS trainsets_physical  SMALLINT NOT NULL DEFAULT 0;

COMMENT ON COLUMN proposals.proposal_summaries.departures_per_year IS 'Departures per year, every trip of every pair on every operating day (CALC 0.9.28).';
COMMENT ON COLUMN proposals.proposal_summaries.trainsets_physical  IS 'Physical rakes the busiest pair needs in its busiest month — the cycle-time rule, ROUTE_BUILDER 0.9.35 (CALC 0.9.28).';
