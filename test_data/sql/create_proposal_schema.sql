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

COMMENT ON TABLE  proposals.shapes          IS 'Route geometry — one row per shape, stored as a GeoJSON LineString in JSONB rather than the GTFS per-point shapes.txt format. Consumed directly by Leaflet/MapLibre. On GTFS export, explode coordinates into one row per point.';
COMMENT ON COLUMN proposals.shapes.shape_id  IS 'Unique shape identifier. Referenced by proposals.trips.';
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

COMMENT ON TABLE  proposals.routes                IS 'GTFS routes.txt — one row per named night train line. route_type 105 = Sleeper Rail Service (GTFS extended HVT code).';
COMMENT ON COLUMN proposals.routes.route_id         IS 'Unique route identifier (e.g. NJ-BER-VIE).';
COMMENT ON COLUMN proposals.routes.agency_id        IS 'GTFS agency_id — nullable for now; populate on GTFS export from input_params.operators (operator_id maps to agency_id in agency.txt).';
COMMENT ON COLUMN proposals.routes.route_short_name IS 'Short public name of the route (e.g. train number "NJ 470").';
COMMENT ON COLUMN proposals.routes.route_long_name  IS 'Full descriptive name of the route (e.g. "Berlin Hbf - Vienna Hbf").';
COMMENT ON COLUMN proposals.routes.route_desc       IS 'Optional free-text description of the route.';
COMMENT ON COLUMN proposals.routes.route_type       IS 'GTFS route type. Default 105 = Sleeper Rail Service (Google HVT extended code).';
COMMENT ON COLUMN proposals.routes.route_color      IS 'Hex color for map rendering (without leading #), e.g. "1C3D2E".';

-- ---------------------------------------------------------------
-- trips
-- ---------------------------------------------------------------
CREATE TABLE proposals.trips (
    trip_id         TEXT PRIMARY KEY,
    route_id        TEXT NOT NULL REFERENCES proposals.routes(route_id) ON DELETE CASCADE,
    service_id      TEXT NOT NULL REFERENCES proposals.services(service_id) ON DELETE CASCADE,
    shape_id        TEXT REFERENCES proposals.shapes(shape_id) ON DELETE SET NULL,
    trip_headsign   TEXT,
    direction_id    SMALLINT CHECK (direction_id IN (0, 1)),
    composition_id  TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE  proposals.trips                IS 'GTFS trips.txt — one scheduled run of a route. composition_id is a project extension (not GTFS) linking to the rolling stock used.';
COMMENT ON COLUMN proposals.trips.trip_id        IS 'Unique trip identifier.';
COMMENT ON COLUMN proposals.trips.route_id       IS 'References proposals.routes.';
COMMENT ON COLUMN proposals.trips.service_id     IS 'References proposals.services — defines which days this trip runs.';
COMMENT ON COLUMN proposals.trips.shape_id       IS 'References proposals.shapes — optional route geometry for map display.';
COMMENT ON COLUMN proposals.trips.trip_headsign  IS 'Destination text shown to passengers (e.g. "Wien Hbf").';
COMMENT ON COLUMN proposals.trips.direction_id   IS 'GTFS direction: 0 = outbound, 1 = inbound.';
COMMENT ON COLUMN proposals.trips.composition_id IS 'Project extension: natural key of the rolling stock composition used (references input_params.compositions.comp_id). Not a hard FK — the versioned FK is on proposals.proposals.composition_row_id.';

-- ---------------------------------------------------------------
-- stop_times
-- ---------------------------------------------------------------
CREATE TABLE proposals.stop_times (
    trip_id         TEXT NOT NULL REFERENCES proposals.trips(trip_id) ON DELETE CASCADE,
    stop_sequence   INTEGER NOT NULL,
    stop_id         TEXT NOT NULL,
    arrival_time    INTERVAL NOT NULL,
    departure_time  INTERVAL NOT NULL,
    stop_headsign   TEXT,
    pickup_type     SMALLINT NOT NULL DEFAULT 0,
    drop_off_type   SMALLINT NOT NULL DEFAULT 0,
    PRIMARY KEY (trip_id, stop_sequence)
);

COMMENT ON TABLE  proposals.stop_times               IS 'GTFS stop_times.txt — ordered stop sequence per trip. Times stored as INTERVAL (not TIME) to support GTFS overnight convention where times exceed 24:00:00.';
COMMENT ON COLUMN proposals.stop_times.trip_id        IS 'References proposals.trips.';
COMMENT ON COLUMN proposals.stop_times.stop_sequence  IS 'Ordered position of this stop within the trip (1-based).';
COMMENT ON COLUMN proposals.stop_times.stop_id        IS 'Soft reference to input_params.stops.stop_id — no hard FK since stops live in Google Sheets at this stage.';
COMMENT ON COLUMN proposals.stop_times.arrival_time   IS 'Scheduled arrival time as INTERVAL from service-day midnight. Values above 24:00:00 indicate next-day arrivals per GTFS convention. Unit: HH:MM:SS';
COMMENT ON COLUMN proposals.stop_times.departure_time IS 'Scheduled departure time. Same INTERVAL convention as arrival_time. Unit: HH:MM:SS';
COMMENT ON COLUMN proposals.stop_times.stop_headsign  IS 'Optional destination sign override for this specific stop.';
COMMENT ON COLUMN proposals.stop_times.pickup_type    IS 'GTFS pickup type: 0 = regular, 1 = no pickup, 2 = phone agency, 3 = coordinate with driver.';
COMMENT ON COLUMN proposals.stop_times.drop_off_type  IS 'GTFS drop-off type: 0 = regular, 1 = no drop-off, 2 = phone agency, 3 = coordinate with driver.';

-- ---------------------------------------------------------------
-- proposals (not GTFS)
-- ---------------------------------------------------------------
CREATE TABLE proposals.proposals (
    proposal_id              SERIAL PRIMARY KEY,
    route_id                 TEXT NOT NULL REFERENCES proposals.routes(route_id) ON DELETE CASCADE,
    version                  INTEGER NOT NULL,
    is_current               BOOLEAN NOT NULL DEFAULT TRUE,
    user_id                  INTEGER REFERENCES admin.users(user_id) ON DELETE SET NULL,
    composition_row_id       INTEGER NOT NULL REFERENCES input_params.compositions(comp_row_id),
    total_distance_km        NUMERIC(8, 2) NOT NULL,
    total_driving_time_h     NUMERIC(6, 2) NOT NULL,
    air_shift_flights        NUMERIC(10, 2),
    air_shift_seats          NUMERIC(12, 2),
    air_shift_seat_km        NUMERIC(14, 2),
    co2_reduction_t_co2e     NUMERIC(10, 2),
    subsidy_per_seat_km_eur  NUMERIC(8, 4),
    subsidy_per_t_co2e_eur   NUMERIC(10, 2),
    total_revenue_eur        NUMERIC(10, 2) NOT NULL,
    total_cost_eur           NUMERIC(10, 2) NOT NULL,
    margin_eur               NUMERIC(10, 2) NOT NULL,
    margin_per               NUMERIC(6, 4) NOT NULL,
    capacity_breakdown       JSONB NOT NULL,
    revenue_breakdown        JSONB NOT NULL,
    cost_breakdown           JSONB NOT NULL,
    parameter_snapshot       JSONB,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (route_id, version)
);

CREATE UNIQUE INDEX idx_proposals_one_current_per_route
    ON proposals.proposals (route_id)
    WHERE is_current;

COMMENT ON TABLE  proposals.proposals                    IS 'Project-specific table: one versioned row per saved cost/revenue/climate evaluation of a route. Not part of GTFS. Uses a partial unique index to enforce exactly one is_current row per route_id.';
COMMENT ON COLUMN proposals.proposals.proposal_id         IS 'Surrogate primary key.';
COMMENT ON COLUMN proposals.proposals.route_id            IS 'References proposals.routes — the route this evaluation belongs to.';
COMMENT ON COLUMN proposals.proposals.version             IS 'Monotonically increasing version number per route_id. Managed by save_proposal() in seed_database.py.';
COMMENT ON COLUMN proposals.proposals.is_current          IS 'True for the latest version of this route. Enforced by partial unique index idx_proposals_one_current_per_route.';
COMMENT ON COLUMN proposals.proposals.user_id             IS 'Cross-schema FK to admin.users — the user who saved this evaluation. Nullable (SET NULL on user deletion).';
COMMENT ON COLUMN proposals.proposals.composition_row_id  IS 'Cross-schema FK to input_params.compositions(comp_row_id) — version-pinned snapshot of the composition active at evaluation time.';
COMMENT ON COLUMN proposals.proposals.total_distance_km   IS 'Total route distance calculated by OpenRailRouting. Unit: km';
COMMENT ON COLUMN proposals.proposals.total_driving_time_h IS 'Total scheduled driving time (sum of all legs, excluding dwell times). Unit: h';
COMMENT ON COLUMN proposals.proposals.air_shift_flights   IS 'Estimated number of flight departures that could be replaced by this night train service. Nullable — not yet computed by model.py.';
COMMENT ON COLUMN proposals.proposals.air_shift_seats     IS 'Estimated number of airline seats replaced per departure day. Nullable — not yet computed by model.py.';
COMMENT ON COLUMN proposals.proposals.air_shift_seat_km   IS 'Distance-weighted airline seats replaced (seats × km). Nullable — not yet computed by model.py. Unit: seat-km';
COMMENT ON COLUMN proposals.proposals.co2_reduction_t_co2e IS 'Estimated CO₂ reduction vs. replaced air travel. Nullable — not yet computed by model.py. Unit: t CO₂e';
COMMENT ON COLUMN proposals.proposals.subsidy_per_seat_km_eur IS 'Public subsidy required per shifted seat-kilometre, if the route needs support. Nullable — not yet computed. Unit: €/seat-km';
COMMENT ON COLUMN proposals.proposals.subsidy_per_t_co2e_eur  IS 'Public subsidy cost per tonne of CO₂ avoided. Nullable — not yet computed. Unit: €/t CO₂e';
COMMENT ON COLUMN proposals.proposals.total_revenue_eur   IS 'Total ticket revenue for one trip at modelled utilisation. Unit: €';
COMMENT ON COLUMN proposals.proposals.total_cost_eur      IS 'Total operating cost for one trip. Unit: €';
COMMENT ON COLUMN proposals.proposals.margin_eur          IS 'Operating margin per trip (revenue − cost). Unit: €';
COMMENT ON COLUMN proposals.proposals.margin_per          IS 'Operating margin as a share of revenue. Unit: ratio (e.g. 0.31 = 31%)';
COMMENT ON COLUMN proposals.proposals.capacity_breakdown  IS 'JSONB: seat/couchette/sleeper capacity for this trip, e.g. {"seats":80,"couchettes":144,"sleepers":0}.';
COMMENT ON COLUMN proposals.proposals.revenue_breakdown   IS 'JSONB: revenue split by class, matching RevenueBreakdown.to_dict() from model.py.';
COMMENT ON COLUMN proposals.proposals.cost_breakdown      IS 'JSONB: cost split by category, matching CostBreakdown.to_dict() from model.py.';
COMMENT ON COLUMN proposals.proposals.parameter_snapshot  IS 'JSONB: complete reproducibility record for this evaluation. Contains model_version, generated_at, and one entry per input parameter block (composition, operator, infrastructure per country, coachtypes, stops, operator_class_costs). Each entry records the row_id, version, source_id, source_description, source_date, and a params sub-object where every used column maps to {value, comment, source_id} — source_id resolved from column_sources override if present, otherwise the row-level source_id. Nullable on legacy rows seeded before snapshot assembly was implemented.';