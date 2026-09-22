-- 2026-09-19 — the manual demand model (DEMAND 0.1.0, CALC 0.9.34,
-- EMISSIONS 0.2.0; docs/2026-09-18_manual_demand_guide.md, phase B)
--
-- Three schema changes, no data rewrite: every stored proposal is outdated
-- by the version bumps and scripts/refresh_proposals.py (run by deploy
-- after this) recomputes it under the new model, which rewrites od_pairs
-- and the summary row in full. Runs after 2026-09-19_schedule_frequency.sql
-- (filename order) but does not depend on it.
--
--   1. proposals.od_pairs.places_sold INTEGER -> DOUBLE PRECISION. The
--      allocation seats fractional places per departure and the OD spread
--      multiplies by a share and by 313.71 departures a year; rounding per
--      pair would break the identity between places seated and passengers
--      counted (ODPair.places_sold is a float now). Existing integers cast
--      losslessly.
--   2. proposals.proposal_summaries.shift_car_* -> shift_other_*. The
--      passengers who would not have flown are half car shift and half
--      induced (models/demand/sources.py); the column carries both, the
--      name says so. Renamed rather than added: the old figures were
--      revenue-derived placeholders, nothing reads them as history.
--   3. demand_kpis_placeholder defaults FALSE. Rows written before this
--      migration keep TRUE until refreshed, which is exactly what the flag
--      means; a fresh row is the model's own figure.
--
-- Idempotent: the type change and the default are no-ops on a migrated
-- database, and the renames are guarded.

ALTER TABLE proposals.od_pairs
    ALTER COLUMN places_sold TYPE DOUBLE PRECISION;

COMMENT ON COLUMN proposals.od_pairs.places_sold IS 'Annual total tickets sold for this OD pair / class / trip. Fractional since DEMAND 0.1.0: served places per departure x the pair''s share x operating days.';

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'proposals' AND table_name = 'proposal_summaries'
          AND column_name = 'shift_car_trips_per_year'
    ) THEN
        ALTER TABLE proposals.proposal_summaries
            RENAME COLUMN shift_car_trips_per_year TO shift_other_trips_per_year;
        ALTER TABLE proposals.proposal_summaries
            RENAME COLUMN shift_car_trip_km_per_year TO shift_other_trip_km_per_year;
    END IF;
END $$;

ALTER TABLE proposals.proposal_summaries
    ALTER COLUMN demand_kpis_placeholder SET DEFAULT FALSE;

COMMENT ON COLUMN proposals.proposal_summaries.passengers_per_year   IS 'Places actually sold, summed over every OD pair (CALC 0.9.29) — the base catering_contribution_eur multiplies. Equal to demand_trips_per_year since DEMAND 0.1.0; kept as its own column because the supply KPIs and the demand KPIs are read by different consumers.';
COMMENT ON COLUMN proposals.proposal_summaries.demand_trips_per_year IS 'Passengers per year (DEMAND 0.1.0: the places actually sold, no longer a revenue-derived placeholder).';
COMMENT ON COLUMN proposals.proposal_summaries.demand_trip_km_per_year IS 'Passenger-km per year over every OD pair sold (DEMAND 0.1.0).';
COMMENT ON COLUMN proposals.proposal_summaries.shift_air_trips_per_year IS 'Passengers who would otherwise have flown (DEMAND 0.1.0, models/demand/sources.py: 0 below 300 km, 25 % at 300 km, linear to 100 % at 1 200 km, per OD pair).';
COMMENT ON COLUMN proposals.proposal_summaries.shift_air_trip_km_per_year IS 'Passenger-km of shift_air_trips_per_year.';
COMMENT ON COLUMN proposals.proposal_summaries.shift_other_trips_per_year IS 'Passengers who would not have flown: half shifted from the car, half induced (DEMAND 0.1.0, OTHER_CAR_SHARE). Replaces shift_car_trips_per_year.';
COMMENT ON COLUMN proposals.proposal_summaries.shift_other_trip_km_per_year IS 'Passenger-km of shift_other_trips_per_year.';
COMMENT ON COLUMN proposals.proposal_summaries.co2_savings_t_per_year IS 'Air and car shift x (that mode''s factor - the train''s) less induced x the train''s, t CO2e/year (EMISSIONS 0.2.0, DEMAND 0.1.0). Can be negative on a very short route.';
COMMENT ON COLUMN proposals.proposal_summaries.demand_kpis_placeholder IS 'FALSE since DEMAND 0.1.0 — demand_*/shift_*/co2_* are the manual demand model''s figures. Kept for readers that filter on it; TRUE only on rows written before the 2026-09-19 migration and not yet refreshed.';
