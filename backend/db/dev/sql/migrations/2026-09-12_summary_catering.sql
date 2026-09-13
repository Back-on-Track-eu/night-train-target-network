-- 2026-09-12 — the catering contribution and the passenger base on the
-- gallery summary (CALC 0.9.29)
--
-- The on-board catering enters the model as one signed net figure per
-- passenger carried (models/demand/model.py STOPGAP_CATERING_EUR_PER_PAX,
-- overridable per proposal as the request field catering_eur_per_pax). It
-- is revenue: it sits inside total_revenue_eur and therefore inside
-- net_eur_per_year, which this migration does NOT change. The two columns
-- below only report it separately, plus the base it multiplies.
--
-- The publish projection (adapters/proposal/repository.py) writes every
-- summary key as a column, so both must exist before the api image that
-- produces them — deploy order: migration, then api.
--
-- Additive and idempotent. Rows written before this migration keep the
-- defaults; they were priced without a catering assumption, so 0 is the
-- honest value and no backfill is possible without recomputing them.
--
-- Dev counterpart: db/dev/sql/create_proposal_schema.sql, which drops and
-- recreates the schema on every seed.

ALTER TABLE proposals.proposal_summaries
    ADD COLUMN IF NOT EXISTS catering_contribution_eur NUMERIC(14, 2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS passengers_per_year       NUMERIC(12, 0) NOT NULL DEFAULT 0;

COMMENT ON COLUMN proposals.proposal_summaries.catering_contribution_eur IS 'Signed net contribution of the on-board catering, already inside net_eur_per_year (CALC 0.9.29): positive means the service pays for itself, negative that the tickets carry it. Unit: EUR/year';
COMMENT ON COLUMN proposals.proposal_summaries.passengers_per_year       IS 'Places actually sold, summed over every OD pair (CALC 0.9.29) — the base catering_contribution_eur multiplies. Not demand_trips_per_year, which is a placeholder derived from revenue.';
