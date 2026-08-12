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
-- Seeding: db/ontd/loader.py applies this file at the start
-- of every run (destructive only to refreshed tables — see the DDL
-- lifecycle note below), then loads the canonical tables and rebuilds
-- route_summaries; db/ontd/composition_loader.py fills the
-- curated tables once. Never touched by seed.py. The Sheet remains
-- source of truth for the canonical tables until a decision is made to
-- migrate editorial tooling off Google (deferred to later in 2026).
--
-- Two table classes (backend/adapters/proposal/README.md §5.5, WP10):
--   REFRESHED — the 11 canonical mirrors below + route_summaries:
--     TRUNCATEd and reloaded on every half-yearly ONTD refresh.
--   CURATED   — coachtypes / coachtype_classes / compositions /
--     composition_coaches / route_compositions (end of file): imported
--     once, then maintained by hand in the DB. Never truncated by the
--     refresh; only soft references cross the lifecycle boundary.
--
-- Schema alignment with Target Network:
--   ontd.stops.stop_id / stop_uic_code ↔ input_params.stops.stop_id
--   Alignment task agreed Giovanni ↔ David Wedekind, 2026-06-22.
-- =============================================================================

-- DDL lifecycle: this file is applied by db/ontd/loader.py at the start of
-- every run (there is no seed.py involvement — ontd is a separate
-- concern). It is destructive ONLY to refreshed tables: those are
-- dropped and recreated, curated tables are CREATE TABLE IF NOT EXISTS
-- and never dropped. Safe to re-run at any time.

CREATE SCHEMA IF NOT EXISTS ontd;

-- Refreshed tables: dropped in reverse dependency order, recreated
-- below. Curated tables are untouched — they hold only soft references
-- into this set, so no CASCADE can reach them.
DROP TABLE IF EXISTS
    ontd.route_corridors,
    ontd.route_legs,
    ontd.route_summaries,
    ontd.translations,
    ontd.trip_stop,
    ontd.calendar_dates,
    ontd.trips,
    ontd.trips_inactive,
    ontd.routes,
    ontd.routes_inactive,
    ontd.calendar,
    ontd.stops,
    ontd.agencies,
    ontd.classes
    CASCADE;

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
    exception_type  SMALLINT,  -- 1=service added, 2=service removed (GTFS)
    PRIMARY KEY (uid)
);

COMMENT ON TABLE ontd.calendar_dates IS 'Keyed on the sheet''s own uid surrogate, NOT (service_id, date): PK columns are implicitly NOT NULL, and the sheet legitimately carries period exceptions (date_from/date_until with date empty) plus rows keyed only by train_id — a composite PK rejected 40 of 59 rows on the first real load (2026-08-04).';

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
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY
);

COMMENT ON TABLE ontd.translations IS 'Surrogate PK: record_id — the join key back to ontd.stops — is #REF! in the source sheet for most rows, so a PK including it rejected 75 of 91 rows on the first real load (2026-08-04). Rows are kept so the breakage stays visible in the data rather than silently dropped; joining on record_id needs the sheet fixed at source first.';

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

-- =============================================================================
-- WP10 — curated composition tables + route_summaries projection
-- (backend/adapters/proposal/README.md §5.5). This file is the ONLY home of the ontd DDL —
-- the WP10 migration carries just the proposals-schema ALTER and points
-- here for the ontd bootstrap.
-- =============================================================================

-- ---------------------------------------------------------------
-- coachtypes (curated)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ontd.coachtypes (
    coachtype_id        TEXT PRIMARY KEY,
    agency_id           TEXT,
    passenger_total     INTEGER,
    lying_total         INTEGER,
    catering            TEXT,
    places_catering     INTEGER,
    bikes               INTEGER,
    climatization       BOOLEAN,
    plugs               BOOLEAN,
    weight_gross_t      NUMERIC(8,3),
    purchase_price_eur  NUMERIC(12,2),
    write_off_years     INTEGER,
    remarks             TEXT
);

COMMENT ON TABLE  ontd.coachtypes IS 'Curated: real-world coach types of existing night trains, imported once from the target-network workbook, then maintained in the DB. Descriptive catalog only — the evaluated composition blueprints live in input_params.coach_types, a separate calibrated model. Excluded from the ONTD refresh TRUNCATE.';
COMMENT ON COLUMN ontd.coachtypes.agency_id IS 'Soft reference to ontd.agencies.agency_id (refreshed table — no FK across the lifecycle boundary). Nullable for shared/unattributed types.';
COMMENT ON COLUMN ontd.coachtypes.passenger_total IS 'Total places in one coach of this type. Unit: pax';
COMMENT ON COLUMN ontd.coachtypes.lying_total IS 'Lying places (berths) of passenger_total. Unit: pax';

-- ---------------------------------------------------------------
-- coach_classes (curated) — the composition catalog's own taxonomy
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ontd.coach_classes (
    class_id    TEXT PRIMARY KEY,
    class_main  TEXT NOT NULL
);

COMMENT ON TABLE ontd.coach_classes IS 'Curated: accommodation classes as used by the composition catalog (26 ids from the target-network workbook). Deliberately SEPARATE from the refreshed ontd.classes: the two taxonomies are differently grained and overlap in only 7 ids (measured), so they are not one list at two resolutions. class_main (Seat/Couchette/Sleeper/Capsule) is the coarse grouping both share.';
COMMENT ON COLUMN ontd.coach_classes.class_main IS 'Coarse grouping: Seat, Couchette, Sleeper, or Capsule.';

-- ---------------------------------------------------------------
-- coachtype_classes (curated) — places per accommodation class
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ontd.coachtype_classes (
    coachtype_id  TEXT    NOT NULL REFERENCES ontd.coachtypes(coachtype_id) ON DELETE CASCADE,
    class_id      TEXT    NOT NULL,
    places        INTEGER NOT NULL,
    lying         INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (coachtype_id, class_id)
);

COMMENT ON TABLE  ontd.coachtype_classes IS 'Curated: places per accommodation class within a coach type (mirrors the input_params.coach_type_classes pattern).';
COMMENT ON COLUMN ontd.coachtype_classes.class_id IS 'Soft reference to ontd.coach_classes.class_id — soft rather than FK because the workbook already references class ids it does not define (e.g. "Sleeper (2-berth)", which exists only in ontd.classes); the importer warns on these instead of dropping the row.';

-- ---------------------------------------------------------------
-- compositions (curated)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ontd.compositions (
    composition_id   TEXT PRIMARY KEY,
    passenger_total  INTEGER,
    lying_total      INTEGER,
    weight_gross_t   NUMERIC(8,3)
);

COMMENT ON TABLE ontd.compositions IS 'Curated: observed train compositions of existing night trains. Totals are stored as imported (workbook aggregates), not derived — slot-level data in composition_coaches may be incomplete for some formations.';

-- ---------------------------------------------------------------
-- composition_coaches (curated) — ordered coach slots
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ontd.composition_coaches (
    composition_id  TEXT     NOT NULL REFERENCES ontd.compositions(composition_id) ON DELETE CASCADE,
    position        SMALLINT NOT NULL CHECK (position >= 1),
    coachtype_id    TEXT     NOT NULL REFERENCES ontd.coachtypes(coachtype_id),
    places          INTEGER,
    lying           INTEGER,
    PRIMARY KEY (composition_id, position)
);

COMMENT ON TABLE  ontd.composition_coaches IS 'Curated: ordered coach slots per composition (unpivoted from the workbook''s 15-slot wide format; mirrors input_params.composition_type_coaches).';
COMMENT ON COLUMN ontd.composition_coaches.places IS 'Slot-level places as recorded in the workbook — kept because they can deviate from the coach type''s nominal capacity (e.g. partially blocked coaches). Nullable where the sheet left it blank.';

-- ---------------------------------------------------------------
-- route_compositions (curated) — route → composition assignment
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ontd.route_compositions (
    route_id        TEXT NOT NULL PRIMARY KEY,
    composition_id  TEXT NOT NULL REFERENCES ontd.compositions(composition_id),
    occupancy_rate  NUMERIC(4,3)
);

COMMENT ON TABLE  ontd.route_compositions IS 'Curated: which composition runs on which existing route. Survives the half-yearly ONTD refresh; the loader reports rows whose route_id no longer exists after each reload.';
COMMENT ON COLUMN ontd.route_compositions.route_id IS 'Soft reference to ontd.routes.route_id (refreshed table). Route ids are stable natural keys in the source sheet, so assignments survive reloads.';
COMMENT ON COLUMN ontd.route_compositions.occupancy_rate IS 'Assumed average occupancy (informational — no evaluation runs on existing routes). Unit: fraction. NULL after the one-time import: the column was dropped from the source workbook before the import ran, so this is hand-maintained only.';

-- ---------------------------------------------------------------
-- route_legs (refreshed) — per-leg router output vs real schedule.
-- The dataset for calibrating country buffer quotas: NOT a gallery
-- projection, and deliberately separate from route_summaries, which
-- stays pure ONTD (decision 23 — routing feeds geometry only there).
--
-- Grain is one row per stop pair because buffer is calibrated PER
-- COUNTRY: a route crosses several, so a route-level total cannot be
-- attributed to any of them, while a leg carries country_time_shares
-- and is short enough to sit mostly in one country.
--
-- The two times are directly comparable by construction: scheduled is
-- departure(from) → arrival(to), i.e. running time with NO dwell, and
-- the router components are likewise in-motion only. Dwell never enters
-- either side.
-- ---------------------------------------------------------------
CREATE TABLE ontd.route_legs (
    route_id               TEXT     NOT NULL,
    trip_id                TEXT     NOT NULL,
    direction_id           SMALLINT,
    leg_sequence           SMALLINT NOT NULL CHECK (leg_sequence >= 1),
    from_stop_id           TEXT     NOT NULL,
    to_stop_id             TEXT     NOT NULL,

    scheduled_running_min  INTEGER,

    routed_driving_min     INTEGER,
    routed_dynamics_min    INTEGER,
    routed_buffer_min      INTEGER,
    routed_distance_m      INTEGER,

    country_time_shares    JSONB,
    country_distance_shares JSONB,

    PRIMARY KEY (trip_id, leg_sequence)
);

CREATE INDEX idx_ontd_route_legs_route ON ontd.route_legs (route_id);

COMMENT ON TABLE ontd.route_legs IS 'Per-leg comparison of router output against the real ONTD timetable — the input for calibrating country buffer quotas in a later work package. Rebuilt with route_summaries by db/ontd/projection.py. Written for EVERY active route: scheduled_running_min is always populated where the timetable allows, while the routed_* columns are NULL when routing failed, so the calibration sample and its gaps are both visible (filter on routed_driving_min IS NOT NULL).';
COMMENT ON COLUMN ontd.route_legs.scheduled_running_min IS 'Real running time from the timetable: departure(from_stop) → arrival(to_stop), midnight rollover resolved by walking the stop sequence. Excludes dwell, so it is directly comparable to routed_driving+dynamics+buffer. NULL where the sheet lacks either time.';
COMMENT ON COLUMN ontd.route_legs.routed_driving_min IS 'Router raw passage time at constant cruise speed (RoutedLeg.driving_time_min). Unit: min';
COMMENT ON COLUMN ontd.route_legs.routed_dynamics_min IS 'Traction dynamics surcharge — acceleration/braking time loss per stop (RoutedLeg.dynamics_time_min, fullRouting only). Unit: min';
COMMENT ON COLUMN ontd.route_legs.routed_buffer_min IS 'Country buffer quota applied to driving and dynamics (RoutedLeg.buffer_time_min) — THE quantity being calibrated: scheduled_running_min minus driving minus dynamics is the buffer the real timetable implies. Unit: min';
COMMENT ON COLUMN ontd.route_legs.country_time_shares IS 'Fractions summing to 1.0, keyed by country code — how this leg''s time splits across countries, so leg-level residuals can be attributed per country.';

-- ---------------------------------------------------------------
-- route_summaries (refreshed) — gallery/map projection, one row per
-- active route. Rebuilt by the loader after every ONTD reload.
-- ---------------------------------------------------------------
CREATE TABLE ontd.route_summaries (
    route_id           TEXT PRIMARY KEY,
    name               TEXT NOT NULL,
    stop_ids           TEXT[] NOT NULL,
    n_stops            SMALLINT NOT NULL,
    countries          TEXT[] NOT NULL,
    country_relations  TEXT[] NOT NULL DEFAULT '{}',
    total_distance_km  NUMERIC(8,1),
    total_time_h       NUMERIC(6,2),
    avg_speed_kmh      NUMERIC(5,1),
    composition_id     TEXT REFERENCES ontd.compositions(composition_id),
    co2_g_per_pax_km   NUMERIC(6,1),
    geom_simplified    geometry(MultiLineString, 4326),
    geometry_routed    BOOLEAN NOT NULL DEFAULT FALSE,
    routing_status     TEXT,
    routing_error      TEXT,

    -- Deep link back to the Open Night Train Database's public page for
    -- this route. GENERATED rather than written by the loader: the URL is
    -- a pure function of route_id, so storing a copy could only ever
    -- drift. Changing the pattern costs nothing — this table is dropped
    -- and rebuilt on every refresh, so the DDL is effectively the config.
    ontd_url           TEXT GENERATED ALWAYS AS (
                           'https://back-on-track.eu/nighttrains/?route_id='
                           || route_id
                       ) STORED,
    refreshed_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON COLUMN ontd.route_summaries.country_relations IS 'Country-to-country relations this existing train actually serves, as sorted "AA__BB" keys — the same shape and meaning as proposals.proposal_summaries.country_relations, so GET /api/proposals/stats ranks both sources on one dimension. Derived in projection.py from the timetable: a stop pair counts only where the origin can be boarded (models/route/timetable.py classify_stop_type + trip_stop.no_entry) and the destination alighted (+ no_exit).';

COMMENT ON COLUMN ontd.route_summaries.stop_ids IS 'TARGET NETWORK stop ids (translated via ontd.stop_mappings at projection time, WP10 step 6a) so gallery filters and map aggregations share one namespace with proposals — raw ONTD ids stay on trip_stop/route_legs. Stops the mapping cannot cover (no coordinates, or country outside input_params.countries) keep their raw ONTD id.';

-- ---------------------------------------------------------------
-- route_corridors (refreshed) — per-stop-pair route pieces for the
-- gallery map's corridor layer (§7.1 map_lines), one row per distinct
-- (route, corridor). Written by db/ontd/projection.py from the same
-- per-leg router geometry route_legs is built from (straight-line
-- fallback legs included), stop pair translated to Target Network ids
-- and direction-collapsed (stop_a < stop_b) — exactly the grain the
-- proposal side aggregates proposals.segments into, so an existing
-- Nightjet and three proposals over the same line thicken one shared
-- corridor instead of drawing beside each other.
-- ---------------------------------------------------------------
CREATE TABLE ontd.route_corridors (
    route_id  TEXT  NOT NULL,
    stop_a    TEXT  NOT NULL,
    stop_b    TEXT  NOT NULL,
    geometry  JSONB NOT NULL,
    PRIMARY KEY (route_id, stop_a, stop_b)
);

COMMENT ON TABLE  ontd.route_corridors IS 'Gallery-map corridor pieces for existing routes (WP10 step 6a, decision B option 3): per consecutive stop pair of each active route, geometry from the individual router leg (or the straight-line fallback), stop ids in the Target Network namespace via ontd.stop_mappings. Grain matches the proposal side''s map_lines aggregation.';
COMMENT ON COLUMN ontd.route_corridors.stop_a   IS 'Target Network stop id, LEAST of the pair — direction-collapsed like the proposal corridors (outbound and return share a corridor).';
COMMENT ON COLUMN ontd.route_corridors.geometry IS 'GeoJSON LineString, same convention as proposals.shapes.geometry: {"type":"LineString","coordinates":[[lon,lat],...]}.';

CREATE INDEX idx_ontd_corridors_pair ON ontd.route_corridors (stop_a, stop_b);

CREATE INDEX idx_ontd_summaries_countries ON ontd.route_summaries USING GIN (countries);
CREATE INDEX idx_ontd_summaries_stop_ids  ON ontd.route_summaries USING GIN (stop_ids);
CREATE INDEX idx_ontd_summaries_geom      ON ontd.route_summaries USING GIST (geom_simplified);

COMMENT ON TABLE  ontd.route_summaries IS 'Derived projection over the ONTD tables for the gallery/map union (§5.5) — one row per ACTIVE route, rebuilt after every refresh. Descriptive + emission KPIs only: no financial, demand, or engagement columns, implementing the no-rating-of-existing-routes policy (decision 23) at schema level.';
COMMENT ON COLUMN ontd.route_summaries.total_time_h IS 'Average duration over the two directional trips (decision on WP10 kickoff). Unit: h';
COMMENT ON COLUMN ontd.route_summaries.composition_id IS 'From ontd.route_compositions where curated — NULL otherwise (~151 of 204 active routes assigned at import time).';
COMMENT ON COLUMN ontd.route_summaries.co2_g_per_pax_km IS 'Night-train GHG intensity from ontd.trips.co2_per_km (trip average per route; NULL where the source sheet has no value). Unit: g CO2e / pax-km';
COMMENT ON COLUMN ontd.route_summaries.geom_simplified IS 'Routed via OpenRailRouting at projection-build time using the SAME fullRouting path as the live tool — custom model, speed cap, HSR avoidance — so an existing route and a proposal are drawn by identical rules on one map (decision 25, revised 2026-08-05). Concatenated + simplified at the proposal projection''s tolerance.';
COMMENT ON COLUMN ontd.route_summaries.geometry_routed IS 'FALSE = straight-line fallback between consecutive stops (routing failed for this route).';
COMMENT ON COLUMN ontd.route_summaries.ontd_url IS 'Public ONTD page for this route (https://back-on-track.eu/nighttrains/?route_id=<id>) — lets the gallery link an existing route back to its source record. Generated from route_id, never written.';
COMMENT ON COLUMN ontd.route_summaries.routing_status IS 'routed | snap_failed | no_connection | no_router | too_few_stops. Every active route is imported regardless; this records why geometry is a fallback, so the gap is queryable instead of implicit in geometry_routed.';
COMMENT ON COLUMN ontd.route_summaries.routing_error IS 'Verbatim router message for a failed route (e.g. which point could not be snapped) — kept for diagnosis; most failures are the night_train profile''s 1435mm gauge filter excluding broad-gauge networks (UA 1520mm, FI 1524mm), which is correct behaviour for proposals.';


-- ---------------------------------------------------------------
-- stop_mappings (CURATED) — interim ONTD ↔ Target Network stop-id
-- bridge (WP10 step 6a). Rebuilt automatically by
-- db/ontd/stop_mapping.py on every projection run EXCEPT rows marked
-- match_method='manual' or verified — those are hand-corrections and
-- survive both the rebuild and the refresh TRUNCATE (this table is in
-- the curated lifecycle, like route_compositions). Soft references
-- only, both directions. This table is the seed of the harmonization
-- deliverable (alignment task Giovanni ↔ David, 2026-06-22) and is
-- replaced wholesale by the OSM-id stop list when that lands.
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ontd.stop_mappings (
    ontd_stop_id  TEXT PRIMARY KEY,
    tn_stop_id    TEXT NOT NULL,
    match_method  TEXT NOT NULL CHECK (match_method IN ('coordinate', 'minted', 'manual')),
    distance_m    NUMERIC(8,1),
    verified      BOOLEAN NOT NULL DEFAULT FALSE
);

COMMENT ON TABLE  ontd.stop_mappings IS 'ONTD stop_id → input_params stop_id (soft references). coordinate = matched to an existing curated stop within 500 m; minted = a new Target Network stop was created from the ONTD data (NULL charge, resolves via defaults); manual = hand-entered, never overwritten. verified=TRUE also protects a row from the automatic rebuild.';
COMMENT ON COLUMN ontd.stop_mappings.distance_m IS 'Match distance for coordinate rows — NULL for minted/manual. Unit: m';
