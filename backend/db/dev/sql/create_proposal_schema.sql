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
-- proposals  (not GTFS — project-specific version container)
--
-- Refit 2026-07-08: the former wide evaluation table (denormalised
-- metrics, JSONB breakdowns, parameter snapshot) is reduced to a thin
-- version container around two JSON columns. route_body is the
-- exact POST /api/route/plan response the proposal was saved from
-- ({route_builder_version, request, route}); evaluation_body, if the
-- saver included one, is the exact POST /api/evaluation/calc response
-- ({calc_version, route_id, models, input, views}). Neither is trimmed
-- before storing, so evaluation_body.input.route ends up holding a
-- second, full copy of the same route already in route_body.route —
-- a deliberate simplicity tradeoff (2026-07-09), not an oversight. The
-- API layer (api/helpers/proposal_serialize.py:
-- validate_route_evaluation_sync) rejects a save with 400
-- validation_error if the two copies don't describe the exact same
-- route, so this table can never end up holding two disagreeing
-- versions of one proposal's route. The route is additionally
-- decomposed into the GTFS tables above; three representations written
-- on every save (JSON x2, GTFS) is a deliberate "for now" — the JSON
-- guarantees an exact, cheap round-trip back to the frontend (GET
-- /api/proposal/<id> returns both columns truly verbatim, byte for
-- byte, key order included — see next paragraph), the GTFS side keeps
-- export/interop viable, and neither blocks a later consolidation.
--
-- route_body/evaluation_body are JSON, deliberately NOT JSONB (2026-07-
-- 09 fix). JSONB is a decomposed binary format: per PostgreSQL's own
-- documentation, storing a value as JSONB does not preserve the
-- original key order or insignificant whitespace — object keys come
-- back in an implementation-defined order on read, not the order the
-- application wrote them in. Since these two columns exist specifically
-- to let GET /api/proposal/<id> hand back the exact bytes originally
-- POSTed to /api/route/plan and /api/evaluation/calc, that reordering
-- defeats the column's whole purpose. JSON (the older, text-based type)
-- stores an exact copy of the input text and so preserves key order
-- exactly. The tradeoff: JSONB-only operators (-, #-, @>, <@, ?, ?|,
-- ?&, ||) and GIN indexing aren't available directly on a JSON column;
-- ->, ->>, #>, #>> still work on both types. Where this schema's own
-- queries need a JSONB-only operator (see adapters/proposal_repository.
-- py's list_current(), which uses - to strip bulky keys before
-- returning a list summary), they cast explicitly with ::jsonb at query
-- time — a normal, cheap, read-only cast that has no effect on what's
-- stored.
--
-- Versioning contract (same append-only discipline as
-- scenario.scenarios): rows are never updated in place. Saving changes
-- to your own proposal inserts a new row with the same proposal_id and
-- proposal_version + 1, flipping is_current. Saving changes to someone
-- else's proposal inserts a brand-new proposal_id at version 1.
-- ---------------------------------------------------------------
CREATE TABLE proposals.proposals (
    proposal_id       SERIAL,
    proposal_version  INTEGER NOT NULL DEFAULT 1,
    is_current        BOOLEAN NOT NULL DEFAULT TRUE,
    user_id           INTEGER REFERENCES admin.users(user_id) ON DELETE SET NULL,
    route_body        JSON NOT NULL,
    evaluation_body   JSON,
    change_log        TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (proposal_id, proposal_version)
);

CREATE UNIQUE INDEX idx_proposals_one_current_per_id
    ON proposals.proposals (proposal_id)
    WHERE is_current;

COMMENT ON TABLE  proposals.proposals                   IS 'One row per saved version of a night train proposal. proposal_id is stable across versions; proposal_version increments on every save by the owner (append-only — rows are never updated). All GTFS rows of a version are linked by ID convention P{proposal_id}_V{proposal_version}_R1, not by FK.';
COMMENT ON COLUMN proposals.proposals.proposal_id       IS 'Stable surrogate key across all versions of a proposal. Assigned from the sequence for new/branched proposals, reused for new versions.';
COMMENT ON COLUMN proposals.proposals.proposal_version  IS 'Monotonically increasing version counter within a proposal_id.';
COMMENT ON COLUMN proposals.proposals.is_current        IS 'True for the latest version of this proposal_id. Enforced by partial unique index.';
COMMENT ON COLUMN proposals.proposals.user_id           IS 'FK to admin.users — user who saved this version. Owner of the current version decides overwrite-vs-branch on the next save. Nullable (SET NULL on user deletion).';
COMMENT ON COLUMN proposals.proposals.route_body        IS 'JSON (not JSONB — see column type note above): the exact, whole POST /api/route/plan response this version was saved from ({route_builder_version, request, route}, all three sections — the API rejects a save whose route_body is missing any of them), with all draft IDs already rewritten to the real proposal_id/proposal_version. Same name in the API request/response bodies (POST /api/proposal request field, GET /api/proposal/<id> response field) — GET returns this column verbatim, key order included.';
COMMENT ON COLUMN proposals.proposals.evaluation_body   IS 'JSON (not JSONB — see column type note above): the exact, whole POST /api/evaluation/calc response for this version, if the saver included one (optional — a proposal can be saved without demand/evaluation). Untrimmed, so input.route is a full second copy of route_body.route — see the table comment above. Same draft-ID rewrite applied as route_body, and will still drift from a fresh /api/evaluation/calc call if parameters change later (a snapshot, not re-derived — mirrors how scenario pinning already works elsewhere). List summaries read total_revenue_eur/total_cost_eur/net_eur out of views.route.data.per_year here. Same name in the API request/response bodies, same as route_body — GET returns this column verbatim (null if absent), key order included.';
COMMENT ON COLUMN proposals.proposals.change_log        IS 'Free-text description of what changed in this version.';