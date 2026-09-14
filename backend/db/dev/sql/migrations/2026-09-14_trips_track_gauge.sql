-- ============================================================
-- 2026-09-14_trips_track_gauge.sql
-- ROUTE_BUILDER 0.9.39: persist Trip.gauge_mm.
--
-- Same shape of gap as 2026-09-14_trips_departure_shift.sql, one version
-- older. 0.9.27 resolved each trip's routing gauge (routing/gauge.py) and
-- serialized it as general_parameters.track_gauge_mm, but proposals.trips
-- had no column for it, so route_dict_from_gtfs() rebuilt every published
-- trip with Trip.gauge_mm's default of 1435 — a published Finnish or
-- Iberian route reported standard gauge on reload, though its stop times
-- and geometry were the broad-gauge ones.
--
-- DEFAULT 1435 backfills every existing row: correct for the whole
-- network west of the break-of-gauge lines, and for the few broad-gauge
-- routes published since 0.9.27 it is exactly what the API has returned
-- for them since publication — the true family is recoverable from the
-- stops if anyone needs it, by re-publishing. Schema only; no truncate,
-- no recompute.
-- ============================================================

ALTER TABLE proposals.trips
    ADD COLUMN track_gauge_mm SMALLINT NOT NULL DEFAULT 1435;

COMMENT ON COLUMN proposals.trips.track_gauge_mm IS
    'Gauge family the trip was routed on (ROUTE_BUILDER 0.9.27): 1435, 1520 (incl. 1524), 1668 or 1000. Stored, not derived: the routing profile that carried the trip is not recoverable from its stops alone once published.';
