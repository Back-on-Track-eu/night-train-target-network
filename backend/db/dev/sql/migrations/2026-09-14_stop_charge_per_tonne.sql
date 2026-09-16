-- 2026-09-14 — mass-based station charge (CALC 0.9.32)
--
-- Czechia prices a passenger stop per tonne of train mass, not per call
-- (Správa železnic Network Statement 2026, Annex C II.5: 0.04-0.08 CZK per
-- scheduled stop per tonne of mpk — train mass without traction that carries
-- no passengers). A per-call figure cannot express that, so the stop table
-- gains the rate and the cost model multiplies it by the composition's
-- coach mass (CompositionType.total_weight_t) at evaluation time:
--
--     charge per call = resolved(stop_charge_eur) + stop_charge_per_tonne_eur × mass
--
-- NULL means no mass-based part, which is every stop outside Czechia. There
-- is no default row for it. Czech stops carry stop_charge_eur = 0.00
-- explicitly (no fixed component, sourced) beside the rate.
--
-- Additive and idempotent; every snapshot version gets the column, NULL.
-- The values arrive with the next stop_seed_catalog.csv (step 10 writes
-- the column, seed.py reads it — the 37-column contract). Dev counterpart:
-- db/schema.py.

ALTER TABLE input_params.stop_infrastructures
    ADD COLUMN IF NOT EXISTS stop_charge_per_tonne_eur NUMERIC(10, 6);

COMMENT ON COLUMN input_params.stop_infrastructures.stop_charge_per_tonne_eur IS 'Mass-based part of the station fee, per tonne of train mass excluding non-carrying traction (CompositionType.total_weight_t). Added to stop_charge_eur per call; empty = none. Czechia prices stops this way (Správa železnic, Annex C II.5). Unit: €/stop/t';
