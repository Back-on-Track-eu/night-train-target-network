-- ============================================================
-- 2026-08-17_energy_pricing.sql
--
-- The calibrated traction energy price model
-- (models/infrastructure/energy_pricing/calib/ENERGY_PRICING_CALIBRATION.md),
-- replacing the single flat electricity price per country the cost model
-- used until CALC 0.9.20. Mirrors db/schema.py, which is the source of
-- truth for input_params and scenario; this file is its migration
-- counterpart for server databases, which are never reseeded.
--
-- Three changes:
--
--   1. A night price and its band on both track tables. Only AT, CH and
--      HR band their electricity tariff; everywhere else the column stays
--      NULL, which the cost model reads as "one rate around the clock".
--      The band is deliberately separate from the TAC night band: Germany
--      bands track access 23:00-06:00 and does not band electricity at
--      all, Switzerland the reverse.
--   2. Two catenary columns — the charge for using the traction
--      power-supply installations, which the TAC calibration excludes per
--      country as energy and nothing has priced since. Two columns rather
--      than one because the infrastructure managers publish in different
--      units (nine per train-km, three per gross-tonne-km), and dividing
--      a per-train-km charge by an assumed consumption would bake the
--      energy model's placeholder factor into an infrastructure charge.
--   3. track_energy_price_eur_kwh widened from NUMERIC(6,3) to (8,6).
--      Calibrated prices carry six decimals; three would quantise the
--      difference between two countries into noise at the fourth.
--
-- VALUES ARE NOT BACKFILLED for the new columns: they are calibrated per
-- country and arrive through db/dev/seed.py's energy seed path
-- (models/infrastructure/energy_pricing/calib/seed/track_energy.csv).
-- Until they do, every new column is NULL — which the loader reads as
-- "not levied", never as missing data, so a server database prices
-- electricity exactly as it does today rather than being mispriced.
--
-- Unlike the TAC group, these columns are NEVER resolved against the
-- defaults row: an empty night price or catenary term is a tariff fact.
-- Only the day rate defaults, as it always has.
-- ============================================================

ALTER TABLE input_params.track_infrastructures
    ALTER COLUMN track_energy_price_eur_kwh TYPE NUMERIC(8,6),
    ADD COLUMN track_energy_price_night_eur_kwh NUMERIC(8,6),
    ADD COLUMN track_energy_night_band_start TIME,
    ADD COLUMN track_energy_night_band_end TIME,
    ADD COLUMN track_energy_catenary_eur_train_km NUMERIC(10,6),
    ADD COLUMN track_energy_catenary_eur_gross_tonne_km NUMERIC(12,8);

ALTER TABLE input_params.track_infrastructure_defaults
    ALTER COLUMN track_energy_price_eur_kwh TYPE NUMERIC(8,6),
    ADD COLUMN track_energy_price_night_eur_kwh NUMERIC(8,6),
    ADD COLUMN track_energy_night_band_start TIME,
    ADD COLUMN track_energy_night_band_end TIME,
    ADD COLUMN track_energy_catenary_eur_train_km NUMERIC(10,6),
    ADD COLUMN track_energy_catenary_eur_gross_tonne_km NUMERIC(12,8);

-- Column documentation, rendered verbatim from db/schema.py so the two
-- cannot drift — the comments are what the /api/params descriptions block
-- serves. The fallback row carries the same texts as the country table:
-- the "never resolved from the defaults row" clause is a property of the
-- column, so it reads correctly on both.
-- track_infrastructure_defaults
COMMENT ON COLUMN input_params.track_infrastructure_defaults.track_energy_price_eur_kwh IS 'Traction electricity price: the day rate, and the rate around the clock for the twenty-five countries whose tariff is not banded. Where a night band exists the cost model prices the in-band share at track_energy_price_night_eur_kwh instead. Unit: €/kWh (EUR at 2032 prices)';
COMMENT ON COLUMN input_params.track_infrastructure_defaults.track_energy_price_night_eur_kwh IS 'Traction electricity price inside the country''s night tariff band, charged pro rata on the share of a run that falls in it. Empty means one rate around the clock (AT, CH and HR are the only banded tariffs). Never resolved from the defaults row, which leaves it empty: a banded tariff is a national particularity, not a gap to fill. Unit: €/kWh (EUR at 2032 prices)';
COMMENT ON COLUMN input_params.track_infrastructure_defaults.track_energy_night_band_start IS 'Start of the national electricity night tariff band, local clock. Bands may run across midnight (22:00–06:00). This is the ENERGY band and is independent of the track access night band (track_tac_night_band_start): Germany bands the track charge 23:00–06:00 and does not band electricity at all, Switzerland the reverse. Unit: time of day';
COMMENT ON COLUMN input_params.track_infrastructure_defaults.track_energy_night_band_end IS 'End of the national electricity night tariff band, local clock. Unit: time of day';
COMMENT ON COLUMN input_params.track_infrastructure_defaults.track_energy_catenary_eur_train_km IS 'Charge for using the catenary and traction power-supply installations, where the infrastructure manager levies it per train-kilometre (FR, HR, HU, IT, LT, LU, LV, PL, RO). Empty means not levied in this unit — either not levied at all, or charged on weight in the column below, or already inside the energy price. Never resolved from the defaults row: roughly half of Europe''s infrastructure managers levy this charge, so an uncalibrated country is priced without one rather than given an invented median. Unit: €/train-km (EUR at 2032 prices)';
COMMENT ON COLUMN input_params.track_infrastructure_defaults.track_energy_catenary_eur_gross_tonne_km IS 'The same supply-equipment charge where the infrastructure manager levies it on the weight moved instead (FI, GR, SK), charged on the whole consist — coaches plus locomotives. Unit: €/gross-tonne-km (EUR at 2032 prices)';

-- track_infrastructures
COMMENT ON COLUMN input_params.track_infrastructures.track_energy_price_eur_kwh IS 'Traction electricity price: the day rate, and the rate around the clock for the twenty-five countries whose tariff is not banded. Where a night band exists the cost model prices the in-band share at track_energy_price_night_eur_kwh instead. Unit: €/kWh (EUR at 2032 prices)';
COMMENT ON COLUMN input_params.track_infrastructures.track_energy_price_night_eur_kwh IS 'Traction electricity price inside the country''s night tariff band, charged pro rata on the share of a run that falls in it. Empty means one rate around the clock (AT, CH and HR are the only banded tariffs). Never resolved from the defaults row, which leaves it empty: a banded tariff is a national particularity, not a gap to fill. Unit: €/kWh (EUR at 2032 prices)';
COMMENT ON COLUMN input_params.track_infrastructures.track_energy_night_band_start IS 'Start of the national electricity night tariff band, local clock. Bands may run across midnight (22:00–06:00). This is the ENERGY band and is independent of the track access night band (track_tac_night_band_start): Germany bands the track charge 23:00–06:00 and does not band electricity at all, Switzerland the reverse. Unit: time of day';
COMMENT ON COLUMN input_params.track_infrastructures.track_energy_night_band_end IS 'End of the national electricity night tariff band, local clock. Unit: time of day';
COMMENT ON COLUMN input_params.track_infrastructures.track_energy_catenary_eur_train_km IS 'Charge for using the catenary and traction power-supply installations, where the infrastructure manager levies it per train-kilometre (FR, HR, HU, IT, LT, LU, LV, PL, RO). Empty means not levied in this unit — either not levied at all, or charged on weight in the column below, or already inside the energy price. Never resolved from the defaults row: roughly half of Europe''s infrastructure managers levy this charge, so an uncalibrated country is priced without one rather than given an invented median. Unit: €/train-km (EUR at 2032 prices)';
COMMENT ON COLUMN input_params.track_infrastructures.track_energy_catenary_eur_gross_tonne_km IS 'The same supply-equipment charge where the infrastructure manager levies it on the weight moved instead (FI, GR, SK), charged on the whole consist — coaches plus locomotives. Unit: €/gross-tonne-km (EUR at 2032 prices)';
