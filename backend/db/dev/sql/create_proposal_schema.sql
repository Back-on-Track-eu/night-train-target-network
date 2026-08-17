DROP SCHEMA IF EXISTS proposals CASCADE;
CREATE SCHEMA proposals;

-- ---------------------------------------------------------------
-- services
-- ---------------------------------------------------------------
CREATE TABLE proposals.services (
    service_id  TEXT PRIMARY KEY
);

COMMENT ON TABLE  proposals.services           IS 'GTFS service registry. calendar and calendar_dates are two independent ways of attaching active dates to a service_id — use calendar for regular weekly patterns, calendar_dates for irregular or fully enumerated schedules.';
COMMENT ON COLUMN proposals.services.service_id IS 'Unique service identifier referenced by trips, calendar, and calendar_dates.';

-- ---------------------------------------------------------------
-- calendar
-- ---------------------------------------------------------------
CREATE TABLE proposals.calendar (
    service_id   TEXT PRIMARY KEY REFERENCES proposals.services(service_id) ON DELETE CASCADE,
    monday       BOOLEAN NOT NULL DEFAULT FALSE,
    tuesday      BOOLEAN NOT NULL DEFAULT FALSE,
    wednesday    BOOLEAN NOT NULL DEFAULT FALSE,
    thursday     BOOLEAN NOT NULL DEFAULT FALSE,
    friday       BOOLEAN NOT NULL DEFAULT FALSE,
    saturday     BOOLEAN NOT NULL DEFAULT FALSE,
    sunday       BOOLEAN NOT NULL DEFAULT FALSE,
    start_date   DATE NOT NULL,
    end_date     DATE NOT NULL
);

COMMENT ON TABLE  proposals.calendar            IS 'GTFS calendar.txt — regular weekly service pattern with a start and end date.';
COMMENT ON COLUMN proposals.calendar.service_id  IS 'References proposals.services.';
COMMENT ON COLUMN proposals.calendar.monday      IS 'Service runs on Mondays within the start/end date window.';
COMMENT ON COLUMN proposals.calendar.tuesday     IS 'Service runs on Tuesdays within the start/end date window.';
COMMENT ON COLUMN proposals.calendar.wednesday   IS 'Service runs on Wednesdays within the start/end date window.';
COMMENT ON COLUMN proposals.calendar.thursday    IS 'Service runs on Thursdays within the start/end date window.';
COMMENT ON COLUMN proposals.calendar.friday      IS 'Service runs on Fridays within the start/end date window.';
COMMENT ON COLUMN proposals.calendar.saturday    IS 'Service runs on Saturdays within the start/end date window.';
COMMENT ON COLUMN proposals.calendar.sunday      IS 'Service runs on Sundays within the start/end date window.';
COMMENT ON COLUMN proposals.calendar.start_date  IS 'First date on which this service is active (inclusive).';
COMMENT ON COLUMN proposals.calendar.end_date    IS 'Last date on which this service is active (inclusive).';

-- ---------------------------------------------------------------
-- calendar_dates
-- ---------------------------------------------------------------
CREATE TABLE proposals.calendar_dates (
    service_id      TEXT NOT NULL REFERENCES proposals.services(service_id) ON DELETE CASCADE,
    date            DATE NOT NULL,
    exception_type  SMALLINT NOT NULL CHECK (exception_type IN (1, 2)),
    PRIMARY KEY (service_id, date)
);

COMMENT ON TABLE  proposals.calendar_dates                IS 'GTFS calendar_dates.txt — per-date exceptions to a calendar pattern, or a fully enumerated irregular schedule when used without calendar.';
COMMENT ON COLUMN proposals.calendar_dates.service_id      IS 'References proposals.services.';
COMMENT ON COLUMN proposals.calendar_dates.date            IS 'The specific date to which the exception applies.';
COMMENT ON COLUMN proposals.calendar_dates.exception_type  IS 'GTFS exception type: 1 = service added for this date, 2 = service removed for this date.';

-- ---------------------------------------------------------------
-- shapes
-- ---------------------------------------------------------------
CREATE TABLE proposals.shapes (
    shape_id    TEXT PRIMARY KEY,
    geometry    JSONB NOT NULL,
    length_km   NUMERIC(8, 2),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE  proposals.shapes           IS 'Route geometry — one row per shape, stored as a GeoJSON LineString in JSONB. Consumed directly by Leaflet/MapLibre. shape_id follows the proposal ID convention e.g. P1_V1_R1_D0_T1_SHAPE.';
COMMENT ON COLUMN proposals.shapes.shape_id  IS 'Unique shape identifier. References proposals.trips.shape_id.';
COMMENT ON COLUMN proposals.shapes.geometry  IS 'GeoJSON LineString: {"type":"LineString","coordinates":[[lon,lat],...]}. Unit: WGS-84 decimal degrees.';
COMMENT ON COLUMN proposals.shapes.length_km IS 'Total route length derived from the geometry. Unit: km';

-- ---------------------------------------------------------------
-- routes
-- ---------------------------------------------------------------
CREATE TABLE proposals.routes (
    route_id          TEXT PRIMARY KEY,
    agency_id         TEXT,
    route_short_name  TEXT,
    route_long_name   TEXT NOT NULL,
    route_desc        TEXT,
    route_type        SMALLINT NOT NULL DEFAULT 105,
    route_color       TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE  proposals.routes                IS 'GTFS routes.txt — one row per proposal version route. route_id follows convention P{proposal_id}_V{version}_R{route_index} e.g. P1_V1_R1. route_type 105 = Sleeper Rail Service (GTFS extended HVT code).';
COMMENT ON COLUMN proposals.routes.route_id         IS 'GTFS route identifier. Convention: P{proposal_id}_V{version}_R{route_index} e.g. P1_V1_R1.';
COMMENT ON COLUMN proposals.routes.agency_id        IS 'GTFS agency_id — nullable; populate on GTFS export from input_params.operators.';
COMMENT ON COLUMN proposals.routes.route_short_name IS 'Short public name of the route (e.g. train number "NJ 470").';
COMMENT ON COLUMN proposals.routes.route_long_name  IS 'Full descriptive name of the route (e.g. "Berlin Hbf - Vienna Hbf").';
COMMENT ON COLUMN proposals.routes.route_desc       IS 'Optional free-text description of the route.';
COMMENT ON COLUMN proposals.routes.route_type       IS 'GTFS route type. Default 105 = Sleeper Rail Service (Google HVT extended code).';
COMMENT ON COLUMN proposals.routes.route_color      IS 'Hex color for map rendering (without leading #), e.g. "1C3D2E".';

-- ---------------------------------------------------------------
-- trips
-- ---------------------------------------------------------------
CREATE TABLE proposals.trips (
    trip_id                   TEXT PRIMARY KEY,
    route_id                  TEXT NOT NULL REFERENCES proposals.routes(route_id) ON DELETE CASCADE,
    service_id                TEXT NOT NULL REFERENCES proposals.services(service_id) ON DELETE CASCADE,
    shape_id                  TEXT REFERENCES proposals.shapes(shape_id) ON DELETE SET NULL,
    trip_headsign             TEXT,
    direction_id              SMALLINT CHECK (direction_id IN (0, 1)),
    composition_type_id       TEXT NOT NULL,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE  proposals.trips                        IS 'GTFS trips.txt — one scheduled run of a route per proposal version. trip_id convention: P{proposal_id}_V{version}_R{route_index}_D{direction}_T{trip_index} e.g. P1_V1_R1_D0_T1.';
COMMENT ON COLUMN proposals.trips.trip_id                IS 'GTFS trip identifier. Convention: P{proposal_id}_V{version}_R{route_index}_D{direction}_T{trip_index}.';
COMMENT ON COLUMN proposals.trips.route_id               IS 'References proposals.routes.';
COMMENT ON COLUMN proposals.trips.service_id             IS 'References proposals.services — defines which days this trip runs.';
COMMENT ON COLUMN proposals.trips.shape_id               IS 'References proposals.shapes — optional route geometry for map display.';
COMMENT ON COLUMN proposals.trips.trip_headsign          IS 'Destination text shown to passengers (e.g. "Wien Hbf").';
COMMENT ON COLUMN proposals.trips.direction_id           IS 'GTFS direction: 0 = outbound, 1 = inbound.';
COMMENT ON COLUMN proposals.trips.composition_type_id    IS 'Natural key of the composition type used. Soft reference to input_params.composition_types.composition_type_id.';

-- ---------------------------------------------------------------
-- stop_times
-- ---------------------------------------------------------------
CREATE TABLE proposals.stop_times (
    trip_id         TEXT NOT NULL REFERENCES proposals.trips(trip_id) ON DELETE CASCADE,
    stop_sequence   INTEGER NOT NULL,
    stop_id         TEXT NOT NULL,
    arrival_time    INTERVAL,
    departure_time  INTERVAL,
    stop_headsign   TEXT,
    pickup_type     SMALLINT NOT NULL DEFAULT 0,
    drop_off_type   SMALLINT NOT NULL DEFAULT 0,
    stop_type       TEXT NOT NULL,  -- lossless boarding/alighting/night/both classification — always set by the sole write path (route_gtfs_serialize.insert_route_gtfs(), WP5)
    auto_added      BOOLEAN NOT NULL DEFAULT FALSE,  -- mirrors Stop.auto_added (2026-08-03, proposals redesign phase 1b) — see migrations/2026-08-03_proposal_schema_phase1b_auto_added.sql
    PRIMARY KEY (trip_id, stop_sequence)
);

COMMENT ON TABLE  proposals.stop_times               IS 'GTFS stop_times.txt — ordered stop sequence per trip. Times stored as INTERVAL to support GTFS overnight convention where times exceed 24:00:00.';
COMMENT ON COLUMN proposals.stop_times.trip_id        IS 'References proposals.trips.';
COMMENT ON COLUMN proposals.stop_times.stop_sequence  IS 'Ordered position of this stop within the trip (1-based).';
COMMENT ON COLUMN proposals.stop_times.stop_id        IS 'Soft reference to input_params.stop_infrastructures.stop_id.';
COMMENT ON COLUMN proposals.stop_times.arrival_time   IS 'Scheduled arrival time as INTERVAL from service-day midnight. Values above 24:00:00 indicate next-day arrivals per GTFS convention. Unit: HH:MM:SS';
COMMENT ON COLUMN proposals.stop_times.departure_time IS 'Scheduled departure time. Same INTERVAL convention as arrival_time. Unit: HH:MM:SS';
COMMENT ON COLUMN proposals.stop_times.stop_headsign  IS 'Optional destination sign override for this specific stop.';
COMMENT ON COLUMN proposals.stop_times.pickup_type    IS 'GTFS pickup type: 0 = regular, 1 = no pickup, 2 = phone agency, 3 = coordinate with driver.';
COMMENT ON COLUMN proposals.stop_times.drop_off_type  IS 'GTFS drop-off type: 0 = regular, 1 = no drop-off, 2 = phone agency, 3 = coordinate with driver.';
COMMENT ON COLUMN proposals.stop_times.stop_type      IS 'Lossless stop classification: boarding, alighting, night, or both (mirrors models.route.trip.StopType) — not losslessly encoded by pickup_type/drop_off_type alone ("night" and "both" both map to (0,0)). Always set by the sole write path (route_gtfs_serialize.insert_route_gtfs(), WP5).';
COMMENT ON COLUMN proposals.stop_times.auto_added     IS 'Mirrors models.route.trip.Stop.auto_added — true if auto_stop_addition inserted this stop. Added phase 1b (2026-08-03) to close a round-trip gap phase 1 missed.';

-- ---------------------------------------------------------------
-- proposals  (not GTFS — project-specific version container)
--
-- ---------------------------------------------------------------
-- proposals  (not GTFS — project-specific version container)
--
-- Proposals redesign cutover (2026-08-04, backend/adapters/proposal/README.md
-- §5.3): one row per proposal, always current — no version history.
-- proposal_version is an internal state counter bumped on every
-- overwrite-publish or system refresh (§4); the previous state is
-- hard-deleted in the same transaction (adapters/proposal_repository.py:
-- publish()). proposals.update_log is the append-only timeline that
-- survives what this table prunes.
--
-- The route lives in GTFS + sidecar tables (above), not here — no
-- route_body JSON blob. evaluation_output holds only the computed
-- models + views (§5.1); input.parameters is never stored, rebuilt on
-- read via the scenario_id pin (api/helpers/route_gtfs_serialize.py:
-- input_parameters_from_scenario()) — storing it per proposal would
-- duplicate the params tables into every row. compute_request is the
-- resolved POST /api/proposal/calc request the publish was computed
-- from, verbatim.
--
-- compute_request/evaluation_output are JSON, deliberately NOT JSONB:
-- JSONB does not preserve original key order (PostgreSQL's own
-- documentation) — object keys come back in an implementation-defined
-- order on read. Since GET /api/proposal/<id> and POST /api/proposal/
-- publish's response both need stable, predictable key order, JSON (the
-- older, text-based type, which stores an exact copy of the input text)
-- is used instead.
-- ---------------------------------------------------------------
CREATE TABLE proposals.proposals (
    proposal_id            SERIAL PRIMARY KEY,
    proposal_version       INTEGER NOT NULL DEFAULT 1,
    user_id                INTEGER REFERENCES admin.users(user_id) ON DELETE SET NULL,
    name                   TEXT NOT NULL,
    route_fingerprint      TEXT NOT NULL,
    composition_id         TEXT NOT NULL,
    scenario_id            INTEGER NOT NULL,
    route_builder_version  TEXT NOT NULL,
    calc_version           TEXT NOT NULL,
    compute_request        JSON NOT NULL,
    evaluation_output      JSON NOT NULL,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE  proposals.proposals                        IS 'One row per proposal, always current (§5.3) — no version history. All GTFS rows of the current state are linked by ID convention P{proposal_id}_V{proposal_version}_R1, not by FK.';
COMMENT ON COLUMN proposals.proposals.proposal_id            IS 'Stable identity. Assigned from the sequence for new proposals, unchanged across overwrite-publishes.';
COMMENT ON COLUMN proposals.proposals.proposal_version       IS 'Internal state counter — bumped on every overwrite-publish or system refresh (§4), embedded in every row-ID prefix. Not a version-history concept: exactly one state exists at any time.';
COMMENT ON COLUMN proposals.proposals.user_id                IS 'FK to admin.users — the owner. Decides overwrite-vs-new at the next publish. Nullable (SET NULL on user deletion).';
COMMENT ON COLUMN proposals.proposals.name                   IS 'User-supplied proposal name.';
COMMENT ON COLUMN proposals.proposals.route_fingerprint      IS 'Route identity fingerprint (§3.1) — informational only, no lookup/index depends on it.';
COMMENT ON COLUMN proposals.proposals.composition_id         IS 'The proposal''s current composition — an overwrite-publish may change it like any other input. Soft reference to input_params.composition_types.composition_type_id.';
COMMENT ON COLUMN proposals.proposals.scenario_id            IS 'The base snapshot the stored evaluation ran under — always the current base at publish time (§2.2); system-managed via the version-refresh mechanism (§4.2) when the base moves.';
COMMENT ON COLUMN proposals.proposals.route_builder_version  IS 'ROUTE_BUILDER_VERSION the route was built with — drives the version-refresh mechanism (§4.2).';
COMMENT ON COLUMN proposals.proposals.calc_version           IS 'CALC_VERSION the evaluation ran with — drives the version-refresh mechanism (§4.2). Always populated: every proposal has route AND evaluation, no half-states (§2.4).';
COMMENT ON COLUMN proposals.proposals.compute_request        IS 'Resolved POST /api/proposal/calc request, verbatim (§2.1).';
COMMENT ON COLUMN proposals.proposals.evaluation_output      IS 'The computed evaluation''s models + views only (§5.1) — NOT input.parameters (rebuilt on read) and NOT a route copy (route lives in GTFS + sidecars).';
COMMENT ON COLUMN proposals.proposals.updated_at             IS 'Bumped on every overwrite-publish and system refresh.';

-- ---------------------------------------------------------------
-- likes / comments  (proposal engagement — 2026-07-29)
-- ---------------------------------------------------------------
-- Adds proposal rating (thumbs-up "like") and commenting.
-- Behavioural counterpart: api/proposal_engagement.py,
-- adapters/proposal_engagement_repository.py.
-- ============================================================

-- ---------------------------------------------------------------
-- likes: one thumbs-up per (proposal, user). No down-vote — a
-- missing row simply means "not liked". proposal_id is a soft
-- reference to proposals.proposals, same convention as
-- stop_times.stop_id / trips.composition_type_id — the composite
-- (proposal_id, proposal_version) primary key there means
-- proposal_id alone can't be an FK target, so existence is
-- checked at the API layer instead.
-- ---------------------------------------------------------------
CREATE TABLE proposals.likes (
    like_id           SERIAL PRIMARY KEY,
    proposal_id       INTEGER NOT NULL,
    proposal_version  INTEGER NOT NULL,
    user_id           INTEGER NOT NULL REFERENCES admin.users(user_id) ON DELETE CASCADE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (proposal_id, user_id)
);

CREATE INDEX idx_likes_proposal ON proposals.likes (proposal_id);

COMMENT ON TABLE  proposals.likes                  IS 'Thumbs-up on a proposal, one per user. Toggled via POST/DELETE /api/proposal/<id>/like; read (with comments and the timeline) via GET /api/proposal/<id>/engagements.';
COMMENT ON COLUMN proposals.likes.proposal_id      IS 'Soft reference to proposals.proposals.proposal_id — validated at the API layer (see module docstring), not a DB constraint.';
COMMENT ON COLUMN proposals.likes.proposal_version IS 'proposal_version that was current at the moment of liking — a context stamp only, not re-derived if the proposal is later versioned.';
COMMENT ON COLUMN proposals.likes.user_id          IS 'admin.users identity of the liker. CASCADE: a deleted account takes its likes with it, since an anonymous like would break the one-per-user constraint''s meaning.';

-- ---------------------------------------------------------------
-- comments: flat (non-threaded) discussion per proposal. Soft
-- delete preserves chronological context even after removal.
-- ---------------------------------------------------------------
CREATE TABLE proposals.comments (
    comment_id        SERIAL PRIMARY KEY,
    proposal_id       INTEGER NOT NULL,
    proposal_version  INTEGER NOT NULL,
    user_id           INTEGER REFERENCES admin.users(user_id) ON DELETE SET NULL,
    body              TEXT NOT NULL,
    is_deleted        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_comments_proposal ON proposals.comments (proposal_id, created_at);

COMMENT ON TABLE  proposals.comments                  IS 'Flat (non-threaded) comment thread per proposal. Written via POST/PATCH/DELETE /api/proposal/<id>/comment[/<cid>], read via GET /api/proposal/<id>/engagements.';
COMMENT ON COLUMN proposals.comments.proposal_id      IS 'Soft reference to proposals.proposals.proposal_id — same convention as proposals.likes.proposal_id.';
COMMENT ON COLUMN proposals.comments.proposal_version IS 'proposal_version that was current at the moment of commenting — a context stamp only, not re-derived on later versions.';
COMMENT ON COLUMN proposals.comments.user_id          IS 'admin.users identity of the author. SET NULL on account deletion (same pattern as admin.feedback.user_id) so the comment text survives; the API renders a null user_id as a deleted-user placeholder.';
COMMENT ON COLUMN proposals.comments.body             IS 'Comment text. Cleared server-side (empty string) when is_deleted is set — the API never trusts a client-supplied deleted body.';
COMMENT ON COLUMN proposals.comments.is_deleted       IS 'Soft-delete flag, settable only by the comment''s own author. Storage-level tombstone: the row is kept so comment_id stays stable, but TRUE rows are returned by nothing — neither the thread nor the timeline (WP11).';
COMMENT ON COLUMN proposals.comments.updated_at       IS 'Bumped on edit and on soft-delete. Also the comment''s position in the timeline — an edited comment moves to its edit time (backend/adapters/proposal/README.md §7.5).';

-- ============================================================
-- Proposals redesign — schema phase 1 (2026-08-03, additive)
-- New GTFS sidecar tables, update_log, proposal_summaries, and the
-- compute cache. See backend/adapters/proposal/README.md and
-- migrations/2026-08-03_proposal_schema_phase1.sql (this block is a
-- verbatim copy of that migration's CREATE TABLE statements — the two
-- new columns on proposals.proposals/stop_times above are the ALTER
-- half, already folded into their table definitions in this file).
-- WP1 of the design doc's implementation plan (§10) — strictly
-- additive, nothing here drops or constrains the existing
-- persist-on-calc tables/code, which keep running until WP5's cutover.
-- ============================================================

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
    countries                JSONB NOT NULL DEFAULT '[]'::jsonb,
    passages                 JSONB NOT NULL DEFAULT '[]'::jsonb,
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
COMMENT ON COLUMN proposals.segments.countries                IS 'The same countries as country_distance_shares, but IN PATH ORDER, which a JSON object cannot express. Track access charges need it: a night rate applies to the clock time a run spends in one country, and placing each country on the clock requires knowing which was entered first. Empty for routes stored before ROUTE_BUILDER 0.9.21.';
COMMENT ON COLUMN proposals.segments.passages                 IS 'Separately charged crossings this segment owns (STOREBAELT, OERESUND_DK, OERESUND_SE, CHANNEL_TUNNEL), matched by polygon intersection at routing time. A crossing is attributed to exactly one segment per trip, so one split by an intermediate stop is not charged twice. Empty for routes stored before ROUTE_BUILDER 0.9.21.';

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
    layover_min   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (route_id, stop_id)
);

COMMENT ON TABLE  proposals.parkings               IS 'One row per Parking (models/route/route.py) — an overnight parking location, deduplicated by stop_id within the route. trip_ids lists every trip whose formation parks here.';
COMMENT ON COLUMN proposals.parkings.route_id      IS 'References proposals.routes.';
COMMENT ON COLUMN proposals.parkings.stop_id       IS 'Soft reference to input_params.stop_infrastructures.stop_id.';
COMMENT ON COLUMN proposals.parkings.trip_ids      IS 'All trip_ids (soft references to proposals.trips) whose formation parks at this stop.';
COMMENT ON COLUMN proposals.parkings.layover_min IS 'Scheduled layover in MINUTES (Parking.hours x 60, ROUTE_BUILDER 0.9.23) — the gap between the arrival that ends one trip here and the departure that starts the next. Stored rather than re-derived because the facility charge depends on it, and a stored route must price identically to the response it was published from. Minutes rather than hours because that is what the timetable actually holds: hours is minutes/60, which is rarely exact in decimal, and a NUMERIC column would round the reconstruction away from the published value. 0 for routes published before that version.';

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

COMMENT ON TABLE  proposals.update_log                  IS 'Append-only timeline event log for proposals. Unlike proposals.proposals (one row per proposal, previous states hard-deleted on overwrite), this preserves every state transition for the frontend timeline (§7.5, merged with comments + likes by GET /api/proposal/<id>/engagements). Written by adapters/proposal/repository.py inside the publish/refresh transaction, read by adapters/proposal/engagement_repository.py.';
COMMENT ON COLUMN proposals.update_log.proposal_id      IS 'Soft reference to proposals.proposals.proposal_id — same convention as likes/comments.';
COMMENT ON COLUMN proposals.update_log.proposal_version IS 'State counter AFTER the event.';
COMMENT ON COLUMN proposals.update_log.user_id          IS 'Acting user; NULL for system events (version-bump/base-scenario refresh) — the timeline renders a NULL here as actor: null, which is what distinguishes a system recalculation from a user overwrite.';
COMMENT ON COLUMN proposals.update_log.event            IS 'One of: published, overwritten, recalculated, branched_from, branched_to.';
COMMENT ON COLUMN proposals.update_log.detail           IS 'Event-specific context. branched_*: {"source_proposal_id": …}. recalculated: {"trigger": "calc_version"|"route_builder_version"|"base_scenario_moved", "from": …, "to": …}.';

-- ---------------------------------------------------------------
-- proposal_summaries (§5.4) — derived projection, NOT a source of
-- truth. Rebuildable at any time by a backfill script; written in the
-- same transaction as every publish (adapters/proposal_repository.py:
-- publish() -> _upsert_summary(), WP5).
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
    country_relations        TEXT[] NOT NULL DEFAULT '{}',
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

    co2_g_per_pax_km            NUMERIC(6, 1),

    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_summaries_countries ON proposals.proposal_summaries USING GIN (countries);
CREATE INDEX idx_summaries_relations ON proposals.proposal_summaries USING GIN (country_relations);
CREATE INDEX idx_summaries_stop_ids  ON proposals.proposal_summaries USING GIN (stop_ids);
CREATE INDEX idx_summaries_geom      ON proposals.proposal_summaries USING GIST (geom_simplified);
-- btree indexes on sortable KPI columns added as query patterns settle (§5.4)

COMMENT ON TABLE  proposals.proposal_summaries                        IS 'Derived projection over proposals.proposals — one row per proposal, NOT a source of truth. Written in the same transaction as every publish (and, from WP8 on, the version-refresh batch); rebuildable at any time by a backfill script.';
COMMENT ON COLUMN proposals.proposal_summaries.route_fingerprint      IS 'Route identity fingerprint (§3.1) — informational only, same as proposals.proposals.route_fingerprint.';
COMMENT ON COLUMN proposals.proposal_summaries.subsidy_eur_per_year   IS 'max(0, -net_eur): gap to target margin. Unit: EUR/year';
COMMENT ON COLUMN proposals.proposal_summaries.geom_simplified        IS 'Per-segment shapes concatenated and simplified (Douglas-Peucker, tolerance tuned for gallery-map zoom levels) — small enough to ship all proposals in one map response for a long time.';
COMMENT ON COLUMN proposals.proposal_summaries.country_relations      IS 'Country-to-country relations this proposal actually serves, as sorted "AA__BB" keys — derived from od_pairs (boarding-capable origin before alighting-capable destination), so a merely transited country contributes nothing. Ranking dimension of GET /api/proposals/stats (§7.7); written by models/evaluation/summary.py''s build_summary_row().';
COMMENT ON COLUMN proposals.proposal_summaries.demand_kpis_placeholder IS 'TRUE while demand_*/shift_*/co2_* columns are placeholder-faked (§8) — no demand model exists yet.';
COMMENT ON COLUMN proposals.proposal_summaries.co2_g_per_pax_km      IS 'Night-train GHG intensity (§8, decision 24): the flat models/emissions factor until the energy-based, country-resolved model enriches it per route. Unit: g CO2e / pax-km';
COMMENT ON COLUMN proposals.proposal_summaries.created_at             IS 'Set once at the proposal''s first publish, never touched by an overwrite-publish or refresh — repository.py''s _upsert_summary() excludes it from the ON CONFLICT UPDATE. Gallery filter/sort target (WP6.1).';

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
