-- ============================================================
-- 2026-08-17_facility_charges.sql
--
-- The calibrated service-facility charges
-- (models/infrastructure/facility/calib/FACILITY_CALIBRATION.md), replacing
-- the flat per-country parking rate and the placeholder shunting figure the
-- cost model used until CALC 0.9.21. Mirrors db/schema.py, which is the
-- source of truth for input_params and scenario; this file is its migration
-- counterpart for server databases, which are never reseeded.
--
-- Two changes:
--
--   1. Six stabling columns on both track tables. Europe prices a stabling
--      occupation four different ways — per metre per started 24 h, per
--      started hour (Germany, length-independent by design), flat per
--      occupation, or not at all — so a mode column carries the basis and
--      only the matching rate column is populated. A free-hours allowance
--      and the hotel-power rate complete the group.
--   2. proposals.parkings.layover_min — the scheduled layover, persisted
--      with a published route, in minutes. The stabling charge is priced from it, so a
--      stored route that did not carry it would reprice cheaper on every
--      reload than the response it was published from. Routes published
--      before ROUTE_BUILDER 0.9.23 default to 0 and therefore price no
--      stabling, which is the same visible understatement a stale payload
--      gets through the serializer. Minutes rather than hours because that
--      is what the timetable holds: hours is minutes/60, rarely exact in
--      decimal, and a fixed-scale NUMERIC column rounds the reconstruction
--      away from the published value (13.983333... -> 13.98), which a
--      deep-equality round-trip test rightly rejects.
--   3. Nothing is added for shunting: it stays the single per-event figure
--      in track_shunting_eur_event, which now carries the calibrated all-in
--      value (IM tariff plus the market cost of what the IM does not
--      supply) instead of one flat placeholder for every country.
--
-- VALUES ARE NOT BACKFILLED: they are calibrated per country and arrive
-- through db/dev/seed.py's facility seed path
-- (models/infrastructure/facility/calib/seed/track_facility.csv). Until they
-- do, track_parking_basis is NULL, which the loader reads as "resolve the
-- whole group from the defaults row" — so a server database prices stabling
-- from the EU default rather than being mispriced, and the existing
-- track_parking_eur_day column keeps its values as a display figure.
--
-- Unlike the energy group, this group IS resolved against the defaults row:
-- every country that stables a train charges something, or has been
-- positively documented not to, in which case its basis reads 'none'.
-- ============================================================

ALTER TABLE input_params.track_infrastructures
    ADD COLUMN track_parking_basis VARCHAR(16) CHECK (track_parking_basis IN ('per_metre_day', 'per_hour', 'per_event', 'none')),
    ADD COLUMN track_parking_eur_metre_day NUMERIC(8,4),
    ADD COLUMN track_parking_eur_hour NUMERIC(8,4),
    ADD COLUMN track_parking_eur_event NUMERIC(10,4),
    ADD COLUMN track_parking_free_hours NUMERIC(6,2),
    ADD COLUMN track_parking_hotel_power_eur_hour NUMERIC(8,4);

ALTER TABLE input_params.track_infrastructure_defaults
    ADD COLUMN track_parking_basis VARCHAR(16) CHECK (track_parking_basis IN ('per_metre_day', 'per_hour', 'per_event', 'none')),
    ADD COLUMN track_parking_eur_metre_day NUMERIC(8,4),
    ADD COLUMN track_parking_eur_hour NUMERIC(8,4),
    ADD COLUMN track_parking_eur_event NUMERIC(10,4),
    ADD COLUMN track_parking_free_hours NUMERIC(6,2),
    ADD COLUMN track_parking_hotel_power_eur_hour NUMERIC(8,4);

-- Column documentation, rendered verbatim from db/schema.py so the two cannot
-- drift. The two legacy columns are included: both change meaning here, from
-- placeholder values to a display figure (parking) and a calibrated all-in
-- charge (shunting).
-- track_infrastructure_defaults
COMMENT ON COLUMN input_params.track_infrastructure_defaults.track_parking_eur_day IS 'Indicative cost of one stabling occupation for the reference train — a single headline number for display and comparison. The cost model does NOT read it: it prices stabling from the basis and rate columns further down, against the actual layover and train length. Unit: €/occupation (EUR at 2032 prices)';
COMMENT ON COLUMN input_params.track_infrastructure_defaults.track_shunting_eur_event IS 'All-in cost of one shunting movement: what the infrastructure manager charges plus what it does not supply. Roughly nine tenths of the figure is the market cost of a shunting locomotive and crew where the IM sells only facility access — see the calibration document. Unit: €/event (EUR at 2032 prices)';
COMMENT ON COLUMN input_params.track_infrastructure_defaults.track_parking_basis IS 'How the country prices one stabling occupation: per metre of train length per started 24 hours, per started hour (length-independent, as Germany''s Anlagenpreissystem is by design), a flat charge per occupation with no time term, or ''none'' where the network statement documents that no siding charge is levied.';
COMMENT ON COLUMN input_params.track_infrastructure_defaults.track_parking_eur_metre_day IS 'Stabling rate where the country prices by length and time. Empty means it prices in one of the other units. Unit: €/metre per started 24 h (EUR at 2032 prices)';
COMMENT ON COLUMN input_params.track_infrastructure_defaults.track_parking_eur_hour IS 'Stabling rate where the country prices per started hour, independent of train length. Unit: €/started hour (EUR at 2032 prices)';
COMMENT ON COLUMN input_params.track_infrastructure_defaults.track_parking_eur_event IS 'Stabling charge where the country prices one occupation flat, with no time or length term. Unit: €/occupation (EUR at 2032 prices)';
COMMENT ON COLUMN input_params.track_infrastructure_defaults.track_parking_free_hours IS 'Free stabling allowance before the charge starts. Material where it exceeds a layover: Norway''s 48 h and Croatia''s 24 h zero a twelve-hour turnaround entirely. Unit: hours';
COMMENT ON COLUMN input_params.track_infrastructure_defaults.track_parking_hotel_power_eur_hour IS 'Power the train draws while stabled, charged on ACTUAL stabled hours rather than on the billable hours after a free track allowance — the electricity flows whether or not the siding is free. One European proxy rate, from DB InfraGO''s unmetered Elektrant flat charge. Unit: €/stabled hour (EUR at 2032 prices)';

-- track_infrastructures
COMMENT ON COLUMN input_params.track_infrastructures.track_parking_eur_day IS 'Indicative cost of one stabling occupation for the reference train — a single headline number for display and comparison. The cost model does NOT read it: it prices stabling from the basis and rate columns further down, against the actual layover and train length. Unit: €/occupation (EUR at 2032 prices)';
COMMENT ON COLUMN input_params.track_infrastructures.track_shunting_eur_event IS 'All-in cost of one shunting movement: what the infrastructure manager charges plus what it does not supply. Roughly nine tenths of the figure is the market cost of a shunting locomotive and crew where the IM sells only facility access — see the calibration document. Unit: €/event (EUR at 2032 prices)';
COMMENT ON COLUMN input_params.track_infrastructures.track_parking_basis IS 'How the country prices one stabling occupation: per metre of train length per started 24 hours, per started hour (length-independent, as Germany''s Anlagenpreissystem is by design), a flat charge per occupation with no time term, or ''none'' where the network statement documents that no siding charge is levied.';
COMMENT ON COLUMN input_params.track_infrastructures.track_parking_eur_metre_day IS 'Stabling rate where the country prices by length and time. Empty means it prices in one of the other units. Unit: €/metre per started 24 h (EUR at 2032 prices)';
COMMENT ON COLUMN input_params.track_infrastructures.track_parking_eur_hour IS 'Stabling rate where the country prices per started hour, independent of train length. Unit: €/started hour (EUR at 2032 prices)';
COMMENT ON COLUMN input_params.track_infrastructures.track_parking_eur_event IS 'Stabling charge where the country prices one occupation flat, with no time or length term. Unit: €/occupation (EUR at 2032 prices)';
COMMENT ON COLUMN input_params.track_infrastructures.track_parking_free_hours IS 'Free stabling allowance before the charge starts. Material where it exceeds a layover: Norway''s 48 h and Croatia''s 24 h zero a twelve-hour turnaround entirely. Unit: hours';
COMMENT ON COLUMN input_params.track_infrastructures.track_parking_hotel_power_eur_hour IS 'Power the train draws while stabled, charged on ACTUAL stabled hours rather than on the billable hours after a free track allowance — the electricity flows whether or not the siding is free. One European proxy rate, from DB InfraGO''s unmetered Elektrant flat charge. Unit: €/stabled hour (EUR at 2032 prices)';


-- Published routes carry the layover the facility charge is priced from.
ALTER TABLE proposals.parkings
    ADD COLUMN layover_min INTEGER NOT NULL DEFAULT 0;

COMMENT ON COLUMN proposals.parkings.layover_min IS 'Scheduled layover in MINUTES (Parking.hours x 60, ROUTE_BUILDER 0.9.23) — the gap between the arrival that ends one trip here and the departure that starts the next. Stored rather than re-derived because the facility charge depends on it, and a stored route must price identically to the response it was published from. Minutes rather than hours because that is what the timetable actually holds: hours is minutes/60, which is rarely exact in decimal, and a NUMERIC column would round the reconstruction away from the published value. 0 for routes published before that version.';
