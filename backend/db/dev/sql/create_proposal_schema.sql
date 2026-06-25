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

-- ---------------------------------------------------------------
-- proposals  (not GTFS — project-specific versioned evaluation table)
-- ---------------------------------------------------------------
CREATE TABLE proposals.proposals (
    proposal_id                SERIAL PRIMARY KEY,
    proposal_version           INTEGER NOT NULL DEFAULT 1,
    route_id                   TEXT NOT NULL REFERENCES proposals.routes(route_id) ON DELETE CASCADE,
    is_current                 BOOLEAN NOT NULL DEFAULT TRUE,
    user_id                    INTEGER REFERENCES admin.users(user_id) ON DELETE SET NULL,
    composition_type_row_id    INTEGER NOT NULL REFERENCES input_params.composition_types(composition_type_row_id),
    -- route physics (from RouteStats)
    total_distance_km          NUMERIC(8, 2) NOT NULL,
    total_driving_time_h       NUMERIC(6, 2) NOT NULL,
    total_time_h               NUMERIC(6, 2) NOT NULL,
    total_energy_kwh           NUMERIC(10, 2),
    -- climate impact (future)
    air_shift_flights          NUMERIC(10, 2),
    air_shift_seats            NUMERIC(12, 2),
    air_shift_seat_km          NUMERIC(14, 2),
    co2_reduction_t_co2e       NUMERIC(10, 2),
    subsidy_per_seat_km_eur    NUMERIC(8, 4),
    subsidy_per_t_co2e_eur     NUMERIC(10, 2),
    -- cost/revenue (from EvaluationResult)
    total_revenue_eur          NUMERIC(10, 2),
    total_cost_eur             NUMERIC(10, 2),
    margin_eur                 NUMERIC(10, 2),
    margin_per                 NUMERIC(6, 4),
    -- JSONB breakdowns
    capacity_breakdown         JSONB,
    revenue_breakdown          JSONB,
    cost_breakdown             JSONB,
    -- parameter provenance (ParamVersions serialised)
    parameter_snapshot         JSONB,
    -- metadata
    editor                     VARCHAR(100),
    change_log                 TEXT,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (proposal_id, proposal_version)
);

CREATE UNIQUE INDEX idx_proposals_one_current_per_id
    ON proposals.proposals (proposal_id)
    WHERE is_current;

COMMENT ON TABLE  proposals.proposals                       IS 'One versioned row per saved evaluation of a night train proposal. proposal_id is stable across versions — proposal_version increments on every change. route_id encodes the version: P{proposal_id}_V{proposal_version}_R1.';
COMMENT ON COLUMN proposals.proposals.proposal_id           IS 'Stable surrogate key across all versions of a proposal.';
COMMENT ON COLUMN proposals.proposals.proposal_version      IS 'Monotonically increasing version counter. Increments on every change (reroute or schedule adjustment).';
COMMENT ON COLUMN proposals.proposals.route_id              IS 'FK to proposals.routes. Encodes version: P{proposal_id}_V{proposal_version}_R1.';
COMMENT ON COLUMN proposals.proposals.is_current            IS 'True for the latest version of this proposal. Enforced by partial unique index.';
COMMENT ON COLUMN proposals.proposals.user_id               IS 'FK to admin.users — user who saved this version. Nullable (SET NULL on user deletion).';
COMMENT ON COLUMN proposals.proposals.composition_type_row_id IS 'Version-pinned FK to input_params.composition_types — the composition active at evaluation time.';
COMMENT ON COLUMN proposals.proposals.total_distance_km     IS 'Total route distance across all trips. Unit: km';
COMMENT ON COLUMN proposals.proposals.total_driving_time_h  IS 'Total driving time across all trips. Unit: h';
COMMENT ON COLUMN proposals.proposals.total_time_h          IS 'Total time including buffer across all trips. Unit: h';
COMMENT ON COLUMN proposals.proposals.total_energy_kwh      IS 'Total energy consumed across all trips. Unit: kWh';
COMMENT ON COLUMN proposals.proposals.parameter_snapshot    IS 'JSONB: ParamVersions serialised at evaluation time. One entry per parameter field keyed by table_short:entity_id:field_name. Each entry carries value, version, source, and description.';
COMMENT ON COLUMN proposals.proposals.editor                IS 'User who created or last edited this version.';
COMMENT ON COLUMN proposals.proposals.change_log            IS 'Free-text description of what changed in this version.';