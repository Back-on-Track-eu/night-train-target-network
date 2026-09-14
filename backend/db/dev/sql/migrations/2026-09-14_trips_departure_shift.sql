-- ============================================================
-- 2026-09-14_trips_departure_shift.sql
-- ROUTE_BUILDER 0.9.38: persist Trip.departure_shift_min.
--
-- 0.9.37 added departure_shift_min to the trip (how far an expert
-- departure override moved the first departure off its automatic value,
-- mirrored the other way onto the return) and serialized it as
-- general_parameters.departure_shift_min, but proposals.trips had no
-- column for it, so route_dict_from_gtfs() rebuilt every published trip
-- with the field's default of 0. A published expert timetable therefore
-- came back with its stop times intact but its shift forgotten — the
-- client could no longer show "automatic 21:00" next to the pinned 20:00,
-- and a re-mirror from the stored route would have moved the return.
--
-- DEFAULT 0 is the correct backfill: every route published before this
-- column existed was either automatic (shift 0 by definition) or an
-- expert timetable whose shift 0.9.37 did not store — for those the true
-- value is unrecoverable and 0 matches what the API has been returning
-- since publication. Schema only; no truncate, no recompute.
-- ============================================================

ALTER TABLE proposals.trips
    ADD COLUMN departure_shift_min SMALLINT NOT NULL DEFAULT 0;

COMMENT ON COLUMN proposals.trips.departure_shift_min IS
    'How far an expert departure override moved the first departure from its automatic value, in minutes (ROUTE_BUILDER 0.9.37); 0 for every automatic timetable. Stored, not derived: the automatic departure is gone once an override replaced it.';
