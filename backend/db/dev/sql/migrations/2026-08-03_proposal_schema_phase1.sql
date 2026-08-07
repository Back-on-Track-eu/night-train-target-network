-- ============================================================
-- 2026-08-03_proposal_schema_phase1.sql
-- Proposals redesign, schema phase 1 (additive only) — WP1 of
-- docs/PROPOSALS_DESIGN.md's implementation plan (§10). Nothing
-- dropped, no constraint the existing persist-on-calc code (route_body/
-- evaluation_body/is_current/change_log, adapters/proposal_repository.py)
-- violates — the old code keeps running untouched until WP5's cutover
-- drops it in one atomic PR (see design doc §5.3 "Dropped vs. the
-- current implementation" and the WP5 data-strategy note).
--
-- Adds:
--   - two new nullable columns on proposals.proposals/stop_times, ahead
--     of WP5 making them NOT NULL on the final slimmed schema (§5.3)
--   - the GTFS sidecar tables (§5.2): segments, od_pairs, parkings,
--     shuntings, timetable_warnings, seasonal_schedules
--   - proposals.update_log (§4.1)
--   - proposals.proposal_summaries (§5.4)
--   - the two compute-cache tables (§2.3)
-- ============================================================

-- ---------------------------------------------------------------
-- proposals.proposals — two new nullable columns ahead of WP5's
-- cutover (§5.3). Nullable for now: nothing populates them until the
-- merged compute/publish endpoints (WP2-5) exist.
-- ---------------------------------------------------------------
ALTER TABLE proposals.proposals
    ADD COLUMN route_fingerprint TEXT,
    ADD COLUMN compute_request   JSON;

COMMENT ON COLUMN proposals.proposals.route_fingerprint IS 'Route identity fingerprint (§3.1) — informational only, no lookup/index depends on it. Nullable in phase 1 (nothing populates it until WP4); NOT NULL on the final schema (WP5).';
COMMENT ON COLUMN proposals.proposals.compute_request   IS 'Resolved POST /api/proposal/calc request, verbatim (§2.1). Nullable in phase 1 (nothing populates it until WP2/5); NOT NULL on the final schema (WP5). JSON, not JSONB — same key-order rationale as route_body/evaluation_body above.';

-- ---------------------------------------------------------------
-- stop_times.stop_type — lossless boarding/alighting/night/both
-- classification (§5.2), not losslessly encoded by GTFS pickup_type/
-- drop_off_type alone ("night" and "both" both map to (0,0)).
-- pickup_type/drop_off_type stay as derived columns for GTFS export
-- compatibility.
-- ---------------------------------------------------------------
ALTER TABLE proposals.stop_times
    ADD COLUMN stop_type TEXT;

COMMENT ON COLUMN proposals.stop_times.stop_type IS 'Lossless stop classification: boarding, alighting, night, or both (mirrors models.route.trip.StopType). Nullable in phase 1 — not yet populated by any write path; source of truth for GTFS pickup_type/drop_off_type going forward once WP3 lands.';

-- ---------------------------------------------------------------
-- segments — one row per Segment (models/route/trip.py), the atomic
-- routing unit. Mirrors Segment's fields 1:1 (see route_serialize.py's
-- _segment_to_dict) so WP3's reconstruction serializer has no
-- lossy/derived mapping to invent. segment_sequence is 0-based, matching
-- the geometry_id index the current serializer already assigns
-- per-trip (f"{trip_id}_L{i}").
-- ---------------------------------------------------------------
CREATE TABLE proposals.segments (
    trip_id                  TEXT NOT NULL REFERENCES proposals.trips(trip_id) ON DELETE CASCADE,
    segment_sequence         INTEGER NOT NULL,
    from_stop_id             TEXT NOT NULL,
    to_stop_id                TEXT NOT NULL,
    shape_id                 TEXT REFERENCES proposals.shapes(shape_id) ON DELETE SET NULL,
    distance_m               INTEGER NOT NULL,
    driving_time_min         INTEGER NOT NULL,
    dynamics_time_min        INTEGER NOT NULL,
    buffer_time_min          INTEGER NOT NULL,
    slack_time_min           INTEGER NOT NULL DEFAULT 0,
    energy_kwh                NUMERIC NOT NULL,
    country_distance_shares  JSONB NOT NULL,
    country_time_shares      JSONB NOT NULL,
    PRIMARY KEY (trip_id, segment_sequence)
);

COMMENT ON TABLE  proposals.segments                          IS 'One row per Segment (models/route/trip.py) — the atomic per-stop-pair physics unit of a trip. Together with shapes, the irreducible per-segment route data the design doc calls out (§5.1) as not reconstructible from anything else.';
COMMENT ON COLUMN proposals.segments.trip_id                  IS 'References proposals.trips.';
COMMENT ON COLUMN proposals.segments.segment_sequence         IS 'Ordered position of this segment within the trip (0-based), matching the geometry_id index the API serializer already assigns per trip.';
COMMENT ON COLUMN proposals.segments.from_stop_id             IS 'Soft reference to input_params.stop_infrastructures.stop_id — same convention as stop_times.stop_id.';
COMMENT ON COLUMN proposals.segments.to_stop_id                IS 'Soft reference to input_params.stop_infrastructures.stop_id.';
COMMENT ON COLUMN proposals.segments.shape_id                 IS 'References proposals.shapes — this segment''s own geometry. Per-segment storage (not per-trip); the per-trip concatenated shape is produced on GTFS export instead of stored (§5.2).';
COMMENT ON COLUMN proposals.segments.distance_m               IS 'Segment distance. Unit: m';
COMMENT ON COLUMN proposals.segments.driving_time_min         IS 'Raw router time (constant-cruise-speed passage). Unit: min';
COMMENT ON COLUMN proposals.segments.dynamics_time_min        IS 'Per-stop acceleration/braking loss. Unit: min';
COMMENT ON COLUMN proposals.segments.buffer_time_min          IS 'Schedule buffer: country quota on driving + on dynamics. Unit: min';
COMMENT ON COLUMN proposals.segments.slack_time_min           IS 'Deliberate schedule padding beyond routing physics — 0 everywhere except legs inside a stretched fixed-night interval. Unit: min';
COMMENT ON COLUMN proposals.segments.energy_kwh                IS 'Energy consumption for this segment. Unit: kWh';
COMMENT ON COLUMN proposals.segments.country_distance_shares  IS 'Per-country share of this segment''s distance, e.g. {"DE": 0.7, "AT": 0.3}. Shares sum to 1.0.';
COMMENT ON COLUMN proposals.segments.country_time_shares      IS 'Per-country share of this segment''s time. Can differ from country_distance_shares (e.g. a mountainous section is slower relative to its length). Shares sum to 1.0.';

-- ---------------------------------------------------------------
-- od_pairs — one row per ODPair (models/params.py): trip-pair-scoped
-- demand input, one per class per origin-destination pair per trip.
-- ---------------------------------------------------------------
CREATE TABLE proposals.od_pairs (
    od_pair_id           SERIAL PRIMARY KEY,
    trip_id              TEXT NOT NULL REFERENCES proposals.trips(trip_id) ON DELETE CASCADE,
    origin_stop_id       TEXT NOT NULL,
    destination_stop_id  TEXT NOT NULL,
    class_main            TEXT NOT NULL,
    places_sold           INTEGER NOT NULL,
    avg_price             NUMERIC(10, 2) NOT NULL
);

CREATE INDEX idx_od_pairs_trip ON proposals.od_pairs (trip_id);

COMMENT ON TABLE  proposals.od_pairs                      IS 'One row per ODPair (models/params.py) — demand for one origin-destination pair, one accommodation class, on one specific trip. A Berlin-Copenhagen demand split across two trips of a Y-shaped route is two rows, each with its own trip_id and places_sold.';
COMMENT ON COLUMN proposals.od_pairs.trip_id               IS 'References proposals.trips.';
COMMENT ON COLUMN proposals.od_pairs.origin_stop_id        IS 'Soft reference to input_params.stop_infrastructures.stop_id.';
COMMENT ON COLUMN proposals.od_pairs.destination_stop_id   IS 'Soft reference to input_params.stop_infrastructures.stop_id.';
COMMENT ON COLUMN proposals.od_pairs.class_main             IS 'Top-level accommodation category: Seat, Couchette, Sleeper, Capsule, or Catering.';
COMMENT ON COLUMN proposals.od_pairs.places_sold             IS 'Annual total tickets sold for this OD pair / class / trip.';
COMMENT ON COLUMN proposals.od_pairs.avg_price               IS 'Average ticket price across all tickets sold for this OD pair, class, and trip. Unit: EUR';

-- ---------------------------------------------------------------
-- parkings — one row per Parking (models/route/route.py): route-level,
-- deduplicated by stop_id (a stop parks the same formation for however
-- many trips share it, typically both outbound and return).
-- ---------------------------------------------------------------
CREATE TABLE proposals.parkings (
    route_id      TEXT NOT NULL REFERENCES proposals.routes(route_id) ON DELETE CASCADE,
    stop_id       TEXT NOT NULL,
    stop_name     TEXT NOT NULL,
    country_code  TEXT NOT NULL,
    trip_ids      TEXT[] NOT NULL,
    PRIMARY KEY (route_id, stop_id)
);

COMMENT ON TABLE  proposals.parkings               IS 'One row per Parking (models/route/route.py) — an overnight parking location, deduplicated by stop_id within the route. trip_ids lists every trip whose formation parks here.';
COMMENT ON COLUMN proposals.parkings.route_id      IS 'References proposals.routes.';
COMMENT ON COLUMN proposals.parkings.stop_id       IS 'Soft reference to input_params.stop_infrastructures.stop_id.';
COMMENT ON COLUMN proposals.parkings.trip_ids      IS 'All trip_ids (soft references to proposals.trips) whose formation parks at this stop.';

-- ---------------------------------------------------------------
-- shuntings — one row per Shunting (models/route/route.py): route-level,
-- one row per trip end/start (a round trip produces up to 4, no
-- deduplication — unlike parkings).
-- ---------------------------------------------------------------
CREATE TABLE proposals.shuntings (
    shunting_id   SERIAL PRIMARY KEY,
    route_id      TEXT NOT NULL REFERENCES proposals.routes(route_id) ON DELETE CASCADE,
    stop_id       TEXT NOT NULL,
    stop_name     TEXT NOT NULL,
    country_code  TEXT NOT NULL,
    trip_id       TEXT NOT NULL REFERENCES proposals.trips(trip_id) ON DELETE CASCADE
);

CREATE INDEX idx_shuntings_route ON proposals.shuntings (route_id);

COMMENT ON TABLE  proposals.shuntings          IS 'One row per Shunting (models/route/route.py) — one shunting event at a trip terminal. Not deduplicated by stop_id, unlike parkings: a round trip produces up to 4 rows (2 per trip end).';
COMMENT ON COLUMN proposals.shuntings.route_id  IS 'References proposals.routes.';
COMMENT ON COLUMN proposals.shuntings.stop_id   IS 'Soft reference to input_params.stop_infrastructures.stop_id.';
COMMENT ON COLUMN proposals.shuntings.trip_id   IS 'References proposals.trips — the trip this shunting event belongs to.';

-- ---------------------------------------------------------------
-- timetable_warnings — one row per TimetableWarning (models/route/
-- trip.py): a derived quality annotation, informational only, never
-- blocks the route.
-- ---------------------------------------------------------------
CREATE TABLE proposals.timetable_warnings (
    warning_id              SERIAL PRIMARY KEY,
    trip_id                 TEXT NOT NULL REFERENCES proposals.trips(trip_id) ON DELETE CASCADE,
    code                    TEXT NOT NULL,
    interval_start_stop_id  TEXT NOT NULL,
    interval_end_stop_id    TEXT NOT NULL,
    timetable_speed_kmh     NUMERIC NOT NULL,
    routing_speed_kmh       NUMERIC NOT NULL,
    ratio                   NUMERIC NOT NULL
);

CREATE INDEX idx_timetable_warnings_trip ON proposals.timetable_warnings (trip_id);

COMMENT ON TABLE  proposals.timetable_warnings                     IS 'One row per TimetableWarning (models/route/trip.py) — a derived timetable quality annotation (e.g. fixed_night_stretch_slow), informational only.';
COMMENT ON COLUMN proposals.timetable_warnings.trip_id              IS 'References proposals.trips.';
COMMENT ON COLUMN proposals.timetable_warnings.code                 IS 'Warning code, e.g. "fixed_night_stretch_slow".';
COMMENT ON COLUMN proposals.timetable_warnings.interval_start_stop_id IS 'Soft reference to input_params.stop_infrastructures.stop_id — start of the affected interval (TimetableWarning.interval[0]).';
COMMENT ON COLUMN proposals.timetable_warnings.interval_end_stop_id   IS 'Soft reference to input_params.stop_infrastructures.stop_id — end of the affected interval (TimetableWarning.interval[1]).';
COMMENT ON COLUMN proposals.timetable_warnings.ratio                 IS 'timetable_speed_kmh / routing_speed_kmh over the interval — below FIXED_NIGHT_MIN_SPEED_RATIO triggers "fixed_night_stretch_slow".';

-- ---------------------------------------------------------------
-- seasonal_schedules — one row per SeasonalSchedule (models/route/
-- route.py): route-level operating frequency per season. calendar/
-- calendar_dates alone only cover the daily case.
-- ---------------------------------------------------------------
CREATE TABLE proposals.seasonal_schedules (
    route_id   TEXT NOT NULL REFERENCES proposals.routes(route_id) ON DELETE CASCADE,
    season     TEXT NOT NULL,
    frequency  TEXT NOT NULL,
    PRIMARY KEY (route_id, season)
);

COMMENT ON TABLE  proposals.seasonal_schedules            IS 'One row per SeasonalSchedule (models/route/route.py) — operating frequency for one season (summer/winter) on a route. calendar/calendar_dates alone only cover the always-daily case.';
COMMENT ON COLUMN proposals.seasonal_schedules.route_id   IS 'References proposals.routes.';
COMMENT ON COLUMN proposals.seasonal_schedules.season     IS 'summer or winter (mirrors models.route.route.Season).';
COMMENT ON COLUMN proposals.seasonal_schedules.frequency  IS 'daily or three_per_week (mirrors models.route.route.Frequency).';

-- ---------------------------------------------------------------
-- update_log (§4.1) — append-only timeline event log. States are
-- pruned on overwrite and likes/comments only stamp a state number, so
-- this is what preserves "comment on state 3, route overwritten
-- afterwards, then recalculated with a new calc version" for the
-- frontend timeline (§7.5).
-- ---------------------------------------------------------------
CREATE TABLE proposals.update_log (
    log_id            SERIAL PRIMARY KEY,
    proposal_id       INTEGER NOT NULL,
    proposal_version  INTEGER NOT NULL,
    user_id           INTEGER REFERENCES admin.users(user_id) ON DELETE SET NULL,
    event             TEXT NOT NULL,
    detail            JSONB,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_update_log_proposal ON proposals.update_log (proposal_id, created_at);

COMMENT ON TABLE  proposals.update_log                  IS 'Append-only timeline event log for proposals. Unlike proposals.proposals (one row per proposal, previous states hard-deleted on overwrite), this preserves every state transition for the frontend timeline (§7.5, chronological merge with comments + likes).';
COMMENT ON COLUMN proposals.update_log.proposal_id      IS 'Soft reference to proposals.proposals.proposal_id — same convention as likes/comments.';
COMMENT ON COLUMN proposals.update_log.proposal_version IS 'State counter AFTER the event.';
COMMENT ON COLUMN proposals.update_log.user_id          IS 'Acting user; NULL for system events (version-bump/base-scenario refresh).';
COMMENT ON COLUMN proposals.update_log.event            IS 'One of: published, overwritten, recalculated, branched_from, branched_to.';
COMMENT ON COLUMN proposals.update_log.detail           IS 'Event-specific context. branched_*: {"source_proposal_id": …}. recalculated: {"trigger": "calc_version"|"route_builder_version"|"base_scenario_moved", "from": …, "to": …}.';

-- ---------------------------------------------------------------
-- proposal_summaries (§5.4) — derived projection, NOT a source of
-- truth. Rebuildable at any time by a backfill script; written in the
-- same transaction as every publish/refresh once WP5 lands. Empty
-- until then — this migration only lands the shape.
-- ---------------------------------------------------------------
CREATE TABLE proposals.proposal_summaries (
    proposal_id             INTEGER PRIMARY KEY,
    proposal_version        INTEGER NOT NULL,
    user_id                 INTEGER,
    route_fingerprint       TEXT NOT NULL,
    composition_id          TEXT NOT NULL,
    scenario_id             INTEGER NOT NULL,
    name                    TEXT NOT NULL,
    route_builder_version   TEXT NOT NULL,
    calc_version             TEXT NOT NULL,

    total_distance_km       NUMERIC(8, 1) NOT NULL,
    total_time_h             NUMERIC(6, 2) NOT NULL,
    avg_speed_kmh            NUMERIC(5, 1) NOT NULL,
    n_stops                  SMALLINT NOT NULL,
    countries                TEXT[] NOT NULL,
    stop_ids                 TEXT[] NOT NULL,
    geom_simplified          geometry(MultiLineString, 4326),

    cost_eur_per_train_km       NUMERIC(10, 2) NOT NULL,
    revenue_eur_per_train_km    NUMERIC(10, 2) NOT NULL,
    margin_eur_per_train_km     NUMERIC(10, 2) NOT NULL,
    subsidy_eur_per_year        NUMERIC(14, 2) NOT NULL,

    demand_trips_per_year       NUMERIC(12, 0),
    demand_trip_km_per_year     NUMERIC(16, 0),
    shift_air_trips_per_year    NUMERIC(12, 0),
    shift_air_trip_km_per_year  NUMERIC(16, 0),
    shift_car_trips_per_year    NUMERIC(12, 0),
    shift_car_trip_km_per_year  NUMERIC(16, 0),
    co2_savings_t_per_year      NUMERIC(12, 1),
    subsidy_eur_per_t_co2       NUMERIC(10, 2),
    demand_kpis_placeholder     BOOLEAN NOT NULL DEFAULT TRUE,

    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_summaries_countries ON proposals.proposal_summaries USING GIN (countries);
CREATE INDEX idx_summaries_stop_ids  ON proposals.proposal_summaries USING GIN (stop_ids);
CREATE INDEX idx_summaries_geom      ON proposals.proposal_summaries USING GIST (geom_simplified);
-- btree indexes on sortable KPI columns added as query patterns settle (§5.4)

COMMENT ON TABLE  proposals.proposal_summaries                        IS 'Derived projection over proposals.proposals — one row per proposal, NOT a source of truth. Written in the same transaction as every publish/refresh (from WP5 on); rebuildable at any time by a backfill script. Empty until WP5 wires the publish handler.';
COMMENT ON COLUMN proposals.proposal_summaries.route_fingerprint      IS 'Route identity fingerprint (§3.1) — informational only, same as proposals.proposals.route_fingerprint.';
COMMENT ON COLUMN proposals.proposal_summaries.subsidy_eur_per_year   IS 'max(0, -net_eur): gap to target margin. Unit: EUR/year';
COMMENT ON COLUMN proposals.proposal_summaries.geom_simplified        IS 'Per-segment shapes concatenated and simplified (Douglas-Peucker, tolerance tuned for gallery-map zoom levels) — small enough to ship all proposals in one map response for a long time.';
COMMENT ON COLUMN proposals.proposal_summaries.demand_kpis_placeholder IS 'TRUE while demand_*/shift_*/co2_* columns are placeholder-faked (§8) — no demand model exists yet.';

-- ---------------------------------------------------------------
-- compute_cache_pointer / compute_cache_result (§2.3) — server-side
-- TTL-bounded compute cache. UNLOGGED: disposable, no WAL overhead,
-- safe to lose on crash (a miss just costs one recompute). No FKs —
-- both key off value tuples, never off a proposals.proposals row.
--
-- Two tables because the fingerprint that keys a result is only known
-- AFTER routing: the pointer table answers "have I seen this exact
-- request before" (keyed by a hash of the request), the result table
-- answers "do I already have this result, regardless of which request
-- asked for it" (keyed by the route's own identity). One table would
-- force picking a single key that can't do both jobs — see the
-- implementation note in §2.3 for the full read/write/cleanup
-- algorithm (request hashing, write order, 1% opportunistic TTL
-- sweep, version-bump flush). Empty until WP13 wires the logic in;
-- this migration only lands the shape.
-- ---------------------------------------------------------------
CREATE UNLOGGED TABLE proposals.compute_cache_pointer (
    request_hash       TEXT PRIMARY KEY,
    route_fingerprint  TEXT NOT NULL,
    scenario_id        INTEGER NOT NULL,
    composition_id     TEXT NOT NULL,
    resolved_request   JSON NOT NULL,
    suggested_stops    JSON,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNLOGGED TABLE proposals.compute_cache_result (
    route_fingerprint  TEXT NOT NULL,
    scenario_id        INTEGER NOT NULL,
    composition_id     TEXT NOT NULL,
    payload            JSON NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (route_fingerprint, scenario_id, composition_id)
);

CREATE INDEX idx_cache_pointer_created ON proposals.compute_cache_pointer (created_at);
CREATE INDEX idx_cache_result_created  ON proposals.compute_cache_result (created_at);

COMMENT ON TABLE  proposals.compute_cache_pointer            IS 'Compute cache, pointer side (§2.3): request_hash -> which result it resolves to, plus the request-specific response parts (resolved request echo, suggested_stops). UNLOGGED — a disposable performance layer, never a source of truth, safe to flush at any time.';
COMMENT ON COLUMN proposals.compute_cache_pointer.request_hash      IS 'Hash of the canonicalized resolved compute request (sorted keys, stable number formatting).';
COMMENT ON COLUMN proposals.compute_cache_pointer.resolved_request  IS 'The request echo for this specific request — request-specific, so it lives on the pointer side, never on the shared result row.';
COMMENT ON COLUMN proposals.compute_cache_pointer.suggested_stops   IS 'auto_stop_addition="suggest" output for this specific request. NULL outside suggest mode.';
COMMENT ON TABLE  proposals.compute_cache_result             IS 'Compute cache, result side (§2.3): (route_fingerprint, scenario_id, composition_id) -> the shared route + evaluation payload, stored once per distinct result no matter how many requests converge on it. UNLOGGED — same disposability as compute_cache_pointer.';
COMMENT ON COLUMN proposals.compute_cache_result.payload             IS 'Route + evaluation core (route + evaluation_output shape), shared across every request that resolves to this exact result.';
