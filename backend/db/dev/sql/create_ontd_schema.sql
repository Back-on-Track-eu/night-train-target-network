-- =============================================================================
-- ONTD (Open Night Train Database) schema
-- =============================================================================
-- Source of truth: Google Sheet owned by Juri Maier (jme@wegewerk.com).
-- This schema is a faithful mirror of the Sheet, cleaned of artifacts:
--   · Chatbase/merged-doc columns removed from trips
--   · Corrupted GSheet header column ("qqa`") removed from trip_stop
--   · stop_sequence stored as INTEGER (TEXT in sheet caused 4.6× network_km bug)
--   · Empty trailing columns dropped from agencies
--
-- Seeding: run backend/db/dev/seed.py (or the ontd-specific loader once built).
-- The Sheet remains source of truth until a decision is made to migrate
-- editorial tooling off Google (deferred to later in 2026).
--
-- Schema alignment with Target Network:
--   ontd.stops.stop_id / stop_uic_code ↔ input_params.stops.stop_id
--   Alignment task agreed Giovanni ↔ David Wedekind, 2026-06-22.
-- =============================================================================

DROP SCHEMA IF EXISTS ontd CASCADE;
CREATE SCHEMA ontd;

-- ---------------------------------------------------------------------------
-- agencies
-- ---------------------------------------------------------------------------
CREATE TABLE ontd.agencies (
    agency_id               TEXT PRIMARY KEY,
    agency_name             TEXT,
    agency_url              TEXT,
    agency_timezone         TEXT,
    agency_lang             TEXT,
    agency_phone            TEXT,
    agency_fare_url         TEXT,
    agency_email            TEXT,
    agency_name_romanized   TEXT,
    agency_name_brand       TEXT,
    agency_state            TEXT,          -- active / inactive / ...
    agency_logo_url         TEXT,
    agency_conditions_groups   TEXT,
    agency_conditions_children TEXT
);

-- ---------------------------------------------------------------------------
-- stops
-- ---------------------------------------------------------------------------
CREATE TABLE ontd.stops (
    stop_id                 TEXT PRIMARY KEY,
    stop_name               TEXT NOT NULL,
    stop_country            CHAR(2),
    stop_timezone           TEXT,
    stop_lat                NUMERIC(9,6),
    stop_lon                NUMERIC(9,6),
    location_type           SMALLINT DEFAULT 0,
    stop_name_romanized     TEXT,
    stop_name_alt           TEXT,
    stop_cityname           TEXT,
    stop_cityname_romanized TEXT,
    stop_cityname_alt       TEXT,
    stop_tariffname         TEXT,
    stop_charge             TEXT,
    stop_uic_code           TEXT,          -- future PK candidate; resolves duplicate stop_id
    stop_code               TEXT,
    stop_region             TEXT
);

COMMENT ON COLUMN ontd.stops.stop_uic_code IS 'UIC station code — future primary key once duplicate stop_id rows (Roman BG/RO, Dimitrovgrad BG/RS, Kolari FI/RS) are resolved with Juri.';

-- ---------------------------------------------------------------------------
-- routes
-- ---------------------------------------------------------------------------
CREATE TABLE ontd.routes (
    route_id            TEXT PRIMARY KEY,
    agency_id           TEXT REFERENCES ontd.agencies(agency_id),
    agency_1            TEXT,
    agency_2            TEXT,
    agency_3            TEXT,
    route_short_name    TEXT,
    route_long_name     TEXT,
    route_desc          TEXT,
    route_type          SMALLINT,
    version             TEXT,
    is_active           BOOLEAN,
    origin_trip_0       TEXT,
    destination_trip_0  TEXT,
    distance            NUMERIC,
    emissions           NUMERIC,
    classes             TEXT,
    countries           TEXT,
    source              TEXT,
    source_interrail    TEXT,
    picture             TEXT,
    emissions_relation  TEXT
);

-- ---------------------------------------------------------------------------
-- trips
-- ---------------------------------------------------------------------------
CREATE TABLE ontd.trips (
    trip_id                 TEXT PRIMARY KEY,
    route_id                TEXT REFERENCES ontd.routes(route_id),
    agency_id               TEXT REFERENCES ontd.agencies(agency_id),
    trip_origin             TEXT,
    origin_departure_time   TEXT,          -- HH:MM; overnight trains may exceed 24:00
    trip_headsign           TEXT,
    destination_arrival_time TEXT,
    trip_short_name         TEXT,
    direction_id            SMALLINT,
    version                 TEXT,
    countries               TEXT,
    is_active               BOOLEAN,
    irregularities          TEXT,
    service_id              TEXT,
    classes                 TEXT,
    connections             TEXT,
    catering                TEXT,
    plugs                   TEXT,
    wheelchair_accessible   SMALLINT,
    bikes_allowed           SMALLINT,
    car_transport           SMALLINT,
    duration                TEXT,
    distance                NUMERIC,
    emissions_co2e          NUMERIC,
    co2_per_km              NUMERIC,
    via                     TEXT
    -- Chatbase/merged-doc columns intentionally excluded (Sheet artifact)
);

-- ---------------------------------------------------------------------------
-- trip_stop  (the stop-sequence per trip)
-- ---------------------------------------------------------------------------
CREATE TABLE ontd.trip_stop (
    trip_id          TEXT NOT NULL REFERENCES ontd.trips(trip_id) ON DELETE CASCADE,
    stop_sequence    INTEGER NOT NULL,     -- MUST be INTEGER; TEXT sort inflated network_km 4.6×
    stop_id          TEXT NOT NULL REFERENCES ontd.stops(stop_id),
    arrival_time     TEXT,                 -- HH:MM, nullable for first stop
    departure_time   TEXT,                 -- HH:MM, nullable for last stop
    no_exit          BOOLEAN DEFAULT FALSE,
    no_entry         BOOLEAN DEFAULT FALSE,
    border_control   BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (trip_id, stop_sequence)
    -- Corrupted GSheet header column ("qqa`") intentionally excluded
);

-- ---------------------------------------------------------------------------
-- calendar
-- ---------------------------------------------------------------------------
CREATE TABLE ontd.calendar (
    service_id  TEXT PRIMARY KEY,
    monday      BOOLEAN NOT NULL DEFAULT FALSE,
    tuesday     BOOLEAN NOT NULL DEFAULT FALSE,
    wednesday   BOOLEAN NOT NULL DEFAULT FALSE,
    thursday    BOOLEAN NOT NULL DEFAULT FALSE,
    friday      BOOLEAN NOT NULL DEFAULT FALSE,
    saturday    BOOLEAN NOT NULL DEFAULT FALSE,
    sunday      BOOLEAN NOT NULL DEFAULT FALSE,
    start_date  DATE,
    end_date    DATE
);

-- ---------------------------------------------------------------------------
-- calendar_dates  (exception days: added or removed service)
-- ---------------------------------------------------------------------------
CREATE TABLE ontd.calendar_dates (
    uid             TEXT,
    train_id        TEXT,
    service_id      TEXT REFERENCES ontd.calendar(service_id) ON DELETE CASCADE,
    date            DATE,
    date_from       DATE,
    date_until      DATE,
    exception_type  SMALLINT NOT NULL,  -- 1=service added, 2=service removed (GTFS)
    PRIMARY KEY (service_id, date)
);

-- ---------------------------------------------------------------------------
-- classes
-- ---------------------------------------------------------------------------
CREATE TABLE ontd.classes (
    class_id    TEXT PRIMARY KEY,
    class_main  TEXT
);

-- ---------------------------------------------------------------------------
-- translations
-- ---------------------------------------------------------------------------
CREATE TABLE ontd.translations (
    table_name      TEXT NOT NULL,
    field_name      TEXT NOT NULL,
    language_code   TEXT NOT NULL,
    translation     TEXT,
    record_id       TEXT,
    field_value     TEXT,
    PRIMARY KEY (table_name, field_name, language_code, record_id)
);

-- ---------------------------------------------------------------------------
-- Inactive tables (retirements — added 2026-05-07 to git-track history)
-- ---------------------------------------------------------------------------
CREATE TABLE ontd.routes_inactive (LIKE ontd.routes INCLUDING ALL);
CREATE TABLE ontd.trips_inactive  (LIKE ontd.trips  INCLUDING ALL);

-- ---------------------------------------------------------------------------
-- Useful indexes
-- ---------------------------------------------------------------------------
CREATE INDEX ON ontd.trip_stop (stop_id);
CREATE INDEX ON ontd.trips     (route_id);
CREATE INDEX ON ontd.trips     (service_id);
CREATE INDEX ON ontd.stops     (stop_country);
CREATE INDEX ON ontd.stops     (stop_uic_code);
