-- 2026-09-12b — additional-services revenue on the gallery summary
-- (CALC 0.9.30, the three-part tariff)
--
-- The tariff is now base fare (a fixed term plus a per-km term) + additional
-- services + the catering contribution, each per accommodation class. This
-- column reports the middle one: the ticket revenue for carrying a bicycle,
-- oversized luggage or a reservation. It is ordinary ticket revenue — not
-- signed, and inside the variable-overhead and EBIT-margin bases, unlike the
-- catering figure beside it, which is already net of its own costs.
--
-- Additive and idempotent. It is already inside net_eur_per_year, which this
-- migration does not change; rows written before it keep 0, because they were
-- priced without a services term and no backfill is possible without
-- recomputing them.
--
-- Deploy order, as always for a summary column: migration, then api. The
-- publish projection writes every summary key as a column.
--
-- Dev counterpart: db/dev/sql/create_proposal_schema.sql.

ALTER TABLE proposals.proposal_summaries
    ADD COLUMN IF NOT EXISTS services_revenue_eur NUMERIC(14, 2) NOT NULL DEFAULT 0;

COMMENT ON COLUMN proposals.proposal_summaries.services_revenue_eur IS 'Revenue from additional services sold with the ticket — bicycles, oversized luggage, reservations (CALC 0.9.30). Ordinary ticket revenue: not signed, and inside the variable-overhead and EBIT-margin bases. Unit: EUR/year';
