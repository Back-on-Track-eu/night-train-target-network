-- 2026-09-07_proposal_summaries_supply_kpis.sql
-- ---------------------------------------------------------------------
-- proposals.proposal_summaries: five new KPI columns (CALC 0.9.25).
--
-- build_summary_row() (models/evaluation/summary.py) now also emits the
-- SIGNED annual net and the annual supply denominators, so a comparison
-- table (POST /api/proposal/calc/matrix, summary detail) can show
-- surplus, EUR/place-km and utilisation without the full views block.
-- The repository writes every summary key as a column
-- (adapters/proposal/repository.py _upsert_summary()), hence the columns.
--
-- Defaults of 0 keep the ALTER metadata-only (no rewrite) and let
-- pre-0.9.25 rows read back consistently until the version bump's
-- refresh (scripts/refresh_proposals.py) overwrites them with real
-- values — which it does for every stored proposal, because the CALC
-- bump marks them all outdated.
--
-- Mirrors db/dev/sql/create_proposal_schema.sql, where fresh local seeds
-- get the columns from; the comment texts below are those columns'.
-- ---------------------------------------------------------------------

ALTER TABLE proposals.proposal_summaries
    ADD COLUMN IF NOT EXISTS net_eur_per_year            NUMERIC(14, 2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS operating_days_per_year     SMALLINT       NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS train_km_per_year           NUMERIC(12, 0) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS available_place_km_per_year NUMERIC(16, 0) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS sold_place_km_per_year      NUMERIC(16, 0) NOT NULL DEFAULT 0;

COMMENT ON COLUMN proposals.proposal_summaries.net_eur_per_year       IS 'Signed annual net after the target margin (CALC 0.9.25): negative is the shortfall subsidy_eur_per_year reports, positive is a surplus. Unit: EUR/year';
COMMENT ON COLUMN proposals.proposal_summaries.operating_days_per_year IS 'Operating days from the seasonal schedule (CALC 0.9.25) — the annualisation factor behind every per-year figure.';
COMMENT ON COLUMN proposals.proposal_summaries.train_km_per_year      IS 'Annual train-km, both directions, all pairs (CALC 0.9.25) — the per_train_km divisor. Unit: km/year';
COMMENT ON COLUMN proposals.proposal_summaries.available_place_km_per_year IS 'Annual capacity place-km (CALC 0.9.25) — the per_available_place_km divisor. Unit: place-km/year';
COMMENT ON COLUMN proposals.proposal_summaries.sold_place_km_per_year IS 'Annual sold place-km from the OD loads (CALC 0.9.25) — sold / available is the utilisation. Unit: place-km/year';
