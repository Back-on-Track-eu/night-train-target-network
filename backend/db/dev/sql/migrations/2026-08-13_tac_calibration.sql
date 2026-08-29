-- ============================================================
-- 2026-08-13_tac_calibration.sql
--
-- The calibrated track access charge component model
-- (models/infrastructure/tac/calib/TAC_CALIBRATION.md), replacing the
-- single flat per-country rate the cost model used until CALC 0.9.18.
-- Mirrors db/schema.py, which is the source of truth for input_params
-- and scenario; this file is its migration counterpart for server
-- databases, which are never reseeded.
--
-- Five additions:
--
--   1. The TAC component columns on both track tables — day/night
--      train-km rates with their bands, gross-tonne-km, seat-km,
--      per-stop, flat per-train-km and revenue-share terms, plus the
--      peak multiplier, congestion surcharge and peak bands.
--   2. input_params.passage_charges — the fifth scenario-versioned
--      table, carrying the crossings billed per traverse (Storebælt,
--      Øresund, Channel Tunnel) and the polygon routing matches them by.
--   3. scenario.scenarios.passage_charges_version — the fifth pin.
--   4. input_params.service_classes.service_class_is_night_accommodation
--      — backfilled below, and load-bearing: without it the German
--      whole-run night rate never fires and DE track access is
--      understated for every sleeper train.
--   5. input_params.composition_types.composition_type_loco_weight_t —
--      completes the gross weight the tonnage terms are charged on.
--
-- VALUES ARE NOT BACKFILLED for the component columns: they are
-- calibrated per country and arrive through db/dev/seed.py's TAC seed
-- path (models/infrastructure/tac/calib/seed/track_tac.csv). Until they
-- do, every component is NULL, which the loader reads as "no rate term
-- at all" and resolves to the EU-median default group — so a server
-- database is priced from the median rather than mispriced, and the flat
-- track_tac_eur_train_km column survives untouched for display.
--
-- The existing flat column keeps its values and its meaning as a
-- display figure; its comment is corrected to say so.
-- ============================================================

ALTER TABLE input_params.track_infrastructures
    ADD COLUMN track_tac_b_day NUMERIC(10,6),
    ADD COLUMN track_tac_b_night NUMERIC(10,6),
    ADD COLUMN track_tac_gamma NUMERIC(12,8),
    ADD COLUMN track_tac_seat_km NUMERIC(12,8),
    ADD COLUMN track_tac_per_stop NUMERIC(10,6),
    ADD COLUMN track_tac_revenue_share NUMERIC(6,4),
    ADD COLUMN track_tac_fixed_per_train_km NUMERIC(10,6),
    ADD COLUMN track_tac_peak_multiplier NUMERIC(4,2),
    ADD COLUMN track_tac_congestion_surcharge_eur_km NUMERIC(10,6),
    ADD COLUMN track_tac_night_mode VARCHAR(10) DEFAULT 'none' CHECK (track_tac_night_mode IN ('none', 'time_band')),
    ADD COLUMN track_tac_night_band_start TIME,
    ADD COLUMN track_tac_night_band_end TIME,
    ADD COLUMN track_tac_night_full_if_accommodation BOOLEAN DEFAULT FALSE,
    ADD COLUMN track_tac_peak_band1_start TIME,
    ADD COLUMN track_tac_peak_band1_end TIME,
    ADD COLUMN track_tac_peak_band2_start TIME,
    ADD COLUMN track_tac_peak_band2_end TIME,
    ADD COLUMN track_tac_peak_weekdays_only BOOLEAN DEFAULT FALSE;

COMMENT ON COLUMN input_params.track_infrastructures.track_tac_b_day IS 'Base day rate of the minimum access package. Empty means the country levies no distance-based day rate. Unit: €/train-km (EUR at 2032 prices)';
COMMENT ON COLUMN input_params.track_infrastructures.track_tac_b_night IS 'Night rate of the minimum access package, charged on the share of a run falling inside the country''s night band. Empty means the country has no separate night rate. Unit: €/train-km (EUR at 2032 prices)';
COMMENT ON COLUMN input_params.track_infrastructures.track_tac_gamma IS 'Weight-dependent term, charged on the whole consist — coaches plus locomotives. Unit: €/gross-tonne-km (EUR at 2032 prices)';
COMMENT ON COLUMN input_params.track_infrastructures.track_tac_seat_km IS 'Capacity-dependent term, charged per place the train offers (Spanish corridor surcharge). Unit: €/seat-km (EUR at 2032 prices)';
COMMENT ON COLUMN input_params.track_infrastructures.track_tac_per_stop IS 'Per-stop element of the path price: stopping and restarting consumes path capacity (Swiss Haltezuschlag). NOT a station usage fee — those are stop_infrastructures.stop_charge_eur. Charged at each stop''s own country rate. Unit: €/stop (EUR at 2032 prices)';
COMMENT ON COLUMN input_params.track_infrastructures.track_tac_revenue_share IS 'Share of the traffic revenue earned in this country that the infrastructure manager takes on top of the distance charges (Swiss Deckungsbeitrag). Unit: fraction';
COMMENT ON COLUMN input_params.track_infrastructures.track_tac_fixed_per_train_km IS 'Flat administrative add-on charged per kilometre alongside the base rate (Luxembourgish path administration). Unit: €/train-km (EUR at 2032 prices)';
COMMENT ON COLUMN input_params.track_infrastructures.track_tac_peak_multiplier IS 'Factor the day rate is multiplied by on the share of a run falling inside the country''s peak bands (Swiss NZV: 2). Unit: factor';
COMMENT ON COLUMN input_params.track_infrastructures.track_tac_congestion_surcharge_eur_km IS 'Flat surcharge on congested sections, charged on the share of a run falling inside the peak bands (Austrian überlastete Schienenwege). Kept apart from the multiplier above so a congestion charge can be shown as one. Unit: €/train-km (EUR at 2032 prices)';
COMMENT ON COLUMN input_params.track_infrastructures.track_tac_night_mode IS 'How the country prices night traffic: ''none'' (one rate around the clock) or ''time_band'' (the night rate applies pro rata to the time a run spends inside the band below).';
COMMENT ON COLUMN input_params.track_infrastructures.track_tac_night_band_start IS 'Start of the national night tariff band, local clock. Bands may run across midnight (23:00–06:00). Unit: time of day';
COMMENT ON COLUMN input_params.track_infrastructures.track_tac_night_band_end IS 'End of the national night tariff band, local clock. Unit: time of day';
COMMENT ON COLUMN input_params.track_infrastructures.track_tac_night_full_if_accommodation IS 'German SPFV Nacht rule: when true, a train carrying night accommodation (couchette, sleeper or capsule) is priced at the night rate over its ENTIRE run in this country, not just the part inside the band.';
COMMENT ON COLUMN input_params.track_infrastructures.track_tac_peak_band1_start IS 'Start of the first daily peak band (morning commuter peak), local clock. Unit: time of day';
COMMENT ON COLUMN input_params.track_infrastructures.track_tac_peak_band1_end IS 'End of the first daily peak band. Unit: time of day';
COMMENT ON COLUMN input_params.track_infrastructures.track_tac_peak_band2_start IS 'Start of the second daily peak band (evening commuter peak), local clock. Unit: time of day';
COMMENT ON COLUMN input_params.track_infrastructures.track_tac_peak_band2_end IS 'End of the second daily peak band. Unit: time of day';
COMMENT ON COLUMN input_params.track_infrastructures.track_tac_peak_weekdays_only IS 'Whether the peak bands apply Monday to Friday only. The model knows a departure''s clock time but not its weekday, so such a band is charged at its expected value — five sevenths of the overlap.';

ALTER TABLE input_params.track_infrastructure_defaults
    ADD COLUMN track_tac_b_day NUMERIC(10,6),
    ADD COLUMN track_tac_b_night NUMERIC(10,6),
    ADD COLUMN track_tac_gamma NUMERIC(12,8),
    ADD COLUMN track_tac_seat_km NUMERIC(12,8),
    ADD COLUMN track_tac_per_stop NUMERIC(10,6),
    ADD COLUMN track_tac_revenue_share NUMERIC(6,4),
    ADD COLUMN track_tac_fixed_per_train_km NUMERIC(10,6),
    ADD COLUMN track_tac_peak_multiplier NUMERIC(4,2),
    ADD COLUMN track_tac_congestion_surcharge_eur_km NUMERIC(10,6),
    ADD COLUMN track_tac_night_mode VARCHAR(10) NOT NULL DEFAULT 'none' CHECK (track_tac_night_mode IN ('none', 'time_band')),
    ADD COLUMN track_tac_night_band_start TIME,
    ADD COLUMN track_tac_night_band_end TIME,
    ADD COLUMN track_tac_night_full_if_accommodation BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN track_tac_peak_band1_start TIME,
    ADD COLUMN track_tac_peak_band1_end TIME,
    ADD COLUMN track_tac_peak_band2_start TIME,
    ADD COLUMN track_tac_peak_band2_end TIME,
    ADD COLUMN track_tac_peak_weekdays_only BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN input_params.track_infrastructure_defaults.track_tac_b_day IS 'Base day rate of the minimum access package. Empty means the country levies no distance-based day rate. Unit: €/train-km (EUR at 2032 prices)';
COMMENT ON COLUMN input_params.track_infrastructure_defaults.track_tac_b_night IS 'Night rate of the minimum access package, charged on the share of a run falling inside the country''s night band. Empty means the country has no separate night rate. Unit: €/train-km (EUR at 2032 prices)';
COMMENT ON COLUMN input_params.track_infrastructure_defaults.track_tac_gamma IS 'Weight-dependent term, charged on the whole consist — coaches plus locomotives. Unit: €/gross-tonne-km (EUR at 2032 prices)';
COMMENT ON COLUMN input_params.track_infrastructure_defaults.track_tac_seat_km IS 'Capacity-dependent term, charged per place the train offers (Spanish corridor surcharge). Unit: €/seat-km (EUR at 2032 prices)';
COMMENT ON COLUMN input_params.track_infrastructure_defaults.track_tac_per_stop IS 'Per-stop element of the path price: stopping and restarting consumes path capacity (Swiss Haltezuschlag). NOT a station usage fee — those are stop_infrastructures.stop_charge_eur. Charged at each stop''s own country rate. Unit: €/stop (EUR at 2032 prices)';
COMMENT ON COLUMN input_params.track_infrastructure_defaults.track_tac_revenue_share IS 'Share of the traffic revenue earned in this country that the infrastructure manager takes on top of the distance charges (Swiss Deckungsbeitrag). Unit: fraction';
COMMENT ON COLUMN input_params.track_infrastructure_defaults.track_tac_fixed_per_train_km IS 'Flat administrative add-on charged per kilometre alongside the base rate (Luxembourgish path administration). Unit: €/train-km (EUR at 2032 prices)';
COMMENT ON COLUMN input_params.track_infrastructure_defaults.track_tac_peak_multiplier IS 'Factor the day rate is multiplied by on the share of a run falling inside the country''s peak bands (Swiss NZV: 2). Unit: factor';
COMMENT ON COLUMN input_params.track_infrastructure_defaults.track_tac_congestion_surcharge_eur_km IS 'Flat surcharge on congested sections, charged on the share of a run falling inside the peak bands (Austrian überlastete Schienenwege). Kept apart from the multiplier above so a congestion charge can be shown as one. Unit: €/train-km (EUR at 2032 prices)';
COMMENT ON COLUMN input_params.track_infrastructure_defaults.track_tac_night_mode IS 'How the country prices night traffic: ''none'' (one rate around the clock) or ''time_band'' (the night rate applies pro rata to the time a run spends inside the band below).';
COMMENT ON COLUMN input_params.track_infrastructure_defaults.track_tac_night_band_start IS 'Start of the national night tariff band, local clock. Bands may run across midnight (23:00–06:00). Unit: time of day';
COMMENT ON COLUMN input_params.track_infrastructure_defaults.track_tac_night_band_end IS 'End of the national night tariff band, local clock. Unit: time of day';
COMMENT ON COLUMN input_params.track_infrastructure_defaults.track_tac_night_full_if_accommodation IS 'German SPFV Nacht rule: when true, a train carrying night accommodation (couchette, sleeper or capsule) is priced at the night rate over its ENTIRE run in this country, not just the part inside the band.';
COMMENT ON COLUMN input_params.track_infrastructure_defaults.track_tac_peak_band1_start IS 'Start of the first daily peak band (morning commuter peak), local clock. Unit: time of day';
COMMENT ON COLUMN input_params.track_infrastructure_defaults.track_tac_peak_band1_end IS 'End of the first daily peak band. Unit: time of day';
COMMENT ON COLUMN input_params.track_infrastructure_defaults.track_tac_peak_band2_start IS 'Start of the second daily peak band (evening commuter peak), local clock. Unit: time of day';
COMMENT ON COLUMN input_params.track_infrastructure_defaults.track_tac_peak_band2_end IS 'End of the second daily peak band. Unit: time of day';
COMMENT ON COLUMN input_params.track_infrastructure_defaults.track_tac_peak_weekdays_only IS 'Whether the peak bands apply Monday to Friday only. The model knows a departure''s clock time but not its weekday, so such a band is charged at its expected value — five sevenths of the overlap.';

-- ---------------------------------------------------------------
-- passage_charges — the fifth scenario-versioned table.
-- ---------------------------------------------------------------
CREATE TABLE input_params.passage_charges (
    passage_row_id SERIAL PRIMARY KEY,
    passage_id VARCHAR(50) NOT NULL,
    passage_name VARCHAR(120) NOT NULL,
    passage_fixed_eur NUMERIC(10,2) NOT NULL DEFAULT 0,
    passage_per_passenger_eur NUMERIC(8,2) NOT NULL DEFAULT 0,
    passage_src INTEGER REFERENCES input_params.sources(source_id),
    passage_geom geometry(Polygon, 4326) NOT NULL,
    change_log TEXT,
    passage_version INTEGER NOT NULL DEFAULT 1,
    UNIQUE (passage_id, passage_version)
);
COMMENT ON TABLE input_params.passage_charges IS 'Crossings that are charged per traverse instead of per kilometre — the Storebælt and Øresund fixed links and the Channel Tunnel. A crossing is its own entity rather than a country attribute because the charging party is the crossing''s operator: Øresund is two rows over one polygon, each infrastructure manager billing its half. Which trip segment crosses which passage is decided at routing time by polygon intersection, so a crossing split by an intermediate stop is still paid for once. Version bumps are full-table snapshots, resolved via scenario.scenarios.passage_charges_version — see db/README.md for the versioning contract.';
COMMENT ON COLUMN input_params.passage_charges.passage_id IS 'Stable crossing identifier (STOREBAELT, OERESUND_DK, OERESUND_SE, CHANNEL_TUNNEL).';
COMMENT ON COLUMN input_params.passage_charges.passage_name IS 'Full crossing name.';
COMMENT ON COLUMN input_params.passage_charges.passage_fixed_eur IS 'Charge per train crossing, one way. Unit: €/traverse (EUR at 2032 prices)';
COMMENT ON COLUMN input_params.passage_charges.passage_per_passenger_eur IS 'Charge per carried passenger, one way (Channel Tunnel). Evaluated against the passengers actually aboard on the crossing segment, so this term follows demand. Unit: €/passenger (EUR at 2032 prices)';
COMMENT ON COLUMN input_params.passage_charges.passage_src IS 'Source for the crossing charges.';
COMMENT ON COLUMN input_params.passage_charges.passage_geom IS 'Crossing polygon (SRID 4326). A routed trip leg intersecting it owns the crossing. Static reference geometry — a tunnel does not move between scenarios; what the version pins are the charges.';
COMMENT ON COLUMN input_params.passage_charges.change_log IS 'Free-text description of what changed in this version and why.';
COMMENT ON COLUMN input_params.passage_charges.passage_version IS 'Per-table full-snapshot version number. Resolved via scenario.scenarios.passage_charges_version — never inferred.';
CREATE INDEX idx_passage_charges_geom ON input_params.passage_charges USING GIST (passage_geom);

-- ---------------------------------------------------------------
-- scenario.scenarios — the fifth version pointer. Backfilled to 1 for
-- existing rows; seed.py pins each seeded scenario explicitly.
-- ---------------------------------------------------------------
ALTER TABLE scenario.scenarios
    ADD COLUMN passage_charges_version INTEGER NOT NULL DEFAULT 1;

COMMENT ON COLUMN scenario.scenarios.passage_charges_version IS 'Pinned input_params.passage_charges version (full-table snapshot).';

-- ---------------------------------------------------------------
-- service_classes — night accommodation. Backfilled by class_main:
-- everything a passenger can lie down in counts; a dining car alone
-- does not make a night train.
-- ---------------------------------------------------------------
ALTER TABLE input_params.service_classes
    ADD COLUMN service_class_is_night_accommodation BOOLEAN NOT NULL DEFAULT FALSE;

UPDATE input_params.service_classes
SET service_class_is_night_accommodation = TRUE
WHERE service_class_main NOT IN ('Seat', 'Catering');

COMMENT ON COLUMN input_params.service_classes.service_class_is_night_accommodation IS 'Whether places of this class make the train count as carrying night accommodation for tariff purposes. Germany prices such a train at its night rate over the whole German run (see track_tac_night_full_if_accommodation). True for every class a passenger can lie down in; a dining car alone does not make a night train.';

-- ---------------------------------------------------------------
-- composition_types — locomotive weight. The default is the same
-- Vectron-class assumption the traction dynamics model already makes,
-- so no existing figure changes.
-- ---------------------------------------------------------------
ALTER TABLE input_params.composition_types
    ADD COLUMN composition_type_loco_weight_t NUMERIC(8,3) NOT NULL DEFAULT 90.0;

COMMENT ON COLUMN input_params.composition_types.composition_type_loco_weight_t IS 'Weight of one locomotive. Together with the number of locomotives it completes the gross weight an infrastructure manager charges weight-dependent track access on — the coach weights alone are not what gets weighed. Default 90 t (Siemens Vectron class), the same assumption the traction dynamics model makes; per-type calibration is a compositions-domain follow-up. Unit: t';

-- ---------------------------------------------------------------
-- The flat rate is now display only — the cost model prices from the
-- components above.
-- ---------------------------------------------------------------
COMMENT ON COLUMN input_params.track_infrastructures.track_tac_eur_train_km IS 'Indicative track access charge for the reference night train — a single headline number for display and comparison. The cost model does NOT read it: it prices track access from the calibrated component columns further down. Unit: €/train-km';
COMMENT ON COLUMN input_params.track_infrastructure_defaults.track_tac_eur_train_km IS 'Indicative track access charge for the reference night train — a single headline number for display and comparison. The cost model does NOT read it: it prices track access from the calibrated component columns further down. Unit: €/train-km';
