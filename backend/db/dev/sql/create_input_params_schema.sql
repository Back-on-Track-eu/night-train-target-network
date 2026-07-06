DROP SCHEMA IF EXISTS input_params CASCADE;
CREATE SCHEMA input_params;

-- PostGIS is database-wide (not schema-scoped) — created here since
-- input_params.countries.country_geom is its first consumer.
CREATE EXTENSION IF NOT EXISTS postgis;

-- ---------------------------------------------------------------
-- countries
-- ---------------------------------------------------------------
CREATE TABLE input_params.countries (
    country_code CHAR(2)      PRIMARY KEY,
    country_name VARCHAR(100) NOT NULL,
    country_geom geometry(MultiPolygon, 4326)
);

COMMENT ON TABLE  input_params.countries              IS 'Country reference table. country_code is ISO 3166-1 alpha-2.';
COMMENT ON COLUMN input_params.countries.country_code IS 'ISO 3166-1 alpha-2 country code. Primary key.';
COMMENT ON COLUMN input_params.countries.country_name IS 'Full English country name.';
COMMENT ON COLUMN input_params.countries.country_geom IS 'Country border polygon (SRID 4326), seeded from Natural Earth admin-0 countries geojson. Nullable — countries without a matched source feature keep this NULL.';

CREATE INDEX idx_countries_geom ON input_params.countries USING GIST (country_geom);

-- ---------------------------------------------------------------
-- sources
-- ---------------------------------------------------------------
CREATE TABLE input_params.sources (
    source_id          SERIAL PRIMARY KEY,
    source_description TEXT NOT NULL,
    source_url         TEXT,
    source_date        DATE
);

COMMENT ON TABLE  input_params.sources                    IS 'Reusable registry of data sources referenced by parameter tables. One row per source document or dataset.';
COMMENT ON COLUMN input_params.sources.source_description IS 'Human-readable description of the source (e.g. "DB Netz Trassenpreissystem 2025", "Eurostat Energy Statistics Q1 2025").';
COMMENT ON COLUMN input_params.sources.source_url         IS 'Optional URL pointing to the source document or dataset.';
COMMENT ON COLUMN input_params.sources.source_date        IS 'Date the source data was published or retrieved.';

-- ---------------------------------------------------------------
-- service_classes
-- ---------------------------------------------------------------
CREATE TABLE input_params.service_classes (
    service_class_id      VARCHAR(100) PRIMARY KEY,
    service_class_main    VARCHAR(50)  NOT NULL,
    service_class_density NUMERIC(8,6) NOT NULL
);

COMMENT ON TABLE  input_params.service_classes                    IS 'Stable accommodation class taxonomy. service_class_main groups: Seat, Couchette, Sleeper, Capsule, Catering.';
COMMENT ON COLUMN input_params.service_classes.service_class_id   IS 'Unique class identifier (e.g. "couchette (6-berth)", "Sleeper (2-berth) with shower & WC").';
COMMENT ON COLUMN input_params.service_classes.service_class_main IS 'Top-level accommodation category: Seat, Couchette, Sleeper, Capsule, or Catering.';
COMMENT ON COLUMN input_params.service_classes.service_class_density IS 'Space units consumed per place of this class. Used for cost allocation. E.g. 6-berth couchette = 1/6 ≈ 0.166667. Unit: space units/place';

-- ---------------------------------------------------------------
-- operators
-- ---------------------------------------------------------------
CREATE TABLE input_params.operators (
    operator_row_id                 SERIAL        PRIMARY KEY,
    operator_id                     VARCHAR(50)   NOT NULL,
    operator_name                   VARCHAR(200)  NOT NULL,
    operator_driver_costs_eur_h     NUMERIC(8,2)  NOT NULL,
    operator_crew_costs_eur_h       NUMERIC(8,2)  NOT NULL,
    operator_driver_overhead_h      INTERVAL      NOT NULL,
    operator_crew_overhead_h        INTERVAL      NOT NULL,
    operator_ebit_margin_per        NUMERIC(5,4)  NOT NULL,
    operator_financing_quota_per    NUMERIC(5,4)  NOT NULL,
    operator_var_overhead_per       NUMERIC(5,4)  NOT NULL,
    operator_fix_overhead_quota_per NUMERIC(5,4)  NOT NULL,
    operator_loco_lease_eur_h       NUMERIC(10,3) NOT NULL,
    source_id                       INTEGER       REFERENCES input_params.sources(source_id),
    change_log                      TEXT,
    operator_version                INTEGER       NOT NULL DEFAULT 1,
    UNIQUE (operator_id, operator_version)
);

COMMENT ON TABLE  input_params.operators IS 'Train operating company — bears operational costs. Row-versioned: operator_id is a natural key referenced (as a soft reference, not an enforced FK) from coach_types and composition_types, resolved per-scenario at load time via scenario.scenarios.operators_version. Version bumps are full-table snapshots — see scenario.scenarios for the versioning contract.';
COMMENT ON COLUMN input_params.operators.operator_driver_costs_eur_h     IS 'Driver staff cost per billable hour. Billable hours = driving time + operator_driver_overhead_h. Unit: €/h';
COMMENT ON COLUMN input_params.operators.operator_crew_costs_eur_h       IS 'Cabin crew cost per billable hour. Unit: €/h';
COMMENT ON COLUMN input_params.operators.operator_driver_overhead_h      IS 'Fixed overhead hours added per trip for driver cost calculation. Unit: h/trip';
COMMENT ON COLUMN input_params.operators.operator_crew_overhead_h        IS 'Fixed overhead hours added per trip for crew cost calculation. Unit: h/trip';
COMMENT ON COLUMN input_params.operators.operator_ebit_margin_per        IS 'Required EBIT margin as a share of revenue. Unit: %';
COMMENT ON COLUMN input_params.operators.operator_financing_quota_per    IS 'Annual financing cost as a share of total capital employed. Unit: %/year';
COMMENT ON COLUMN input_params.operators.operator_var_overhead_per       IS 'Variable overhead as a share of total ticket revenue. Unit: %';
COMMENT ON COLUMN input_params.operators.operator_fix_overhead_quota_per IS 'Fixed overhead as a share of all other railway operation costs. Unit: %';
COMMENT ON COLUMN input_params.operators.operator_loco_lease_eur_h       IS 'Full-service locomotive lease rate, utilization-based — bundles capital, maintenance, and insurance. Billed per loco operating hour (driving + buffer + dwell). Unit: €/h';
COMMENT ON COLUMN input_params.operators.source_id                       IS 'Source for all values in this row.';
COMMENT ON COLUMN input_params.operators.change_log                      IS 'Free-text description of changes made in this version.';
COMMENT ON COLUMN input_params.operators.operator_version                IS 'Per-table full-snapshot version number. Resolved via scenario.scenarios.operators_version — never inferred.';

-- ---------------------------------------------------------------
-- operator_class_costs
-- ---------------------------------------------------------------
CREATE TABLE input_params.operator_class_costs (
    operator_row_id                        INTEGER      NOT NULL REFERENCES input_params.operators(operator_row_id) ON DELETE CASCADE,
    service_class_id                       VARCHAR(100) NOT NULL REFERENCES input_params.service_classes(service_class_id),
    operator_class_svc_stockings_eur_place NUMERIC(8,4) NOT NULL,
    source_id                              INTEGER      REFERENCES input_params.sources(source_id),
    PRIMARY KEY (operator_row_id, service_class_id)
);

COMMENT ON TABLE  input_params.operator_class_costs IS 'Variable cost of onboard services and stockings per operator and accommodation class.';
COMMENT ON COLUMN input_params.operator_class_costs.operator_class_svc_stockings_eur_place IS 'Service and stockings cost per available place per trip. Unit: €/place';
COMMENT ON COLUMN input_params.operator_class_costs.source_id IS 'Source for all values in this row.';

-- ---------------------------------------------------------------
-- coach_types
-- ---------------------------------------------------------------
CREATE TABLE input_params.coach_types (
    coach_type_row_id      SERIAL       PRIMARY KEY,
    coach_type_id          VARCHAR(50)  NOT NULL,
    coach_type_operator_id VARCHAR(50),
    coach_type_weight_gross_t NUMERIC(8,3),
    coach_type_bikes          INTEGER   NOT NULL DEFAULT 0,
    coach_type_climatization  BOOLEAN   NOT NULL DEFAULT FALSE,
    coach_type_plugs          BOOLEAN   NOT NULL DEFAULT FALSE,
    coach_type_crew_factor    NUMERIC(4,2) NOT NULL DEFAULT 0,
    coach_type_remarks        TEXT,
    source_id                 INTEGER   REFERENCES input_params.sources(source_id),
    change_log                TEXT,
    coach_type_version        INTEGER   NOT NULL DEFAULT 1,
    UNIQUE (coach_type_id, coach_type_version)
);

COMMENT ON TABLE  input_params.coach_types IS 'Individual railcar/coach types. Capacity is derived from coach_type_classes, not stored here. Version bumps are full-table snapshots, resolved via scenario.scenarios.coach_types_version — see scenario.scenarios for the versioning contract.';
COMMENT ON COLUMN input_params.coach_types.coach_type_id             IS 'Unique coach type identifier (e.g. WLABmz, Bcmz, type1).';
COMMENT ON COLUMN input_params.coach_types.coach_type_operator_id    IS 'Operating company this coach type belongs to. Soft reference to input_params.operators.operator_id (not an enforced FK, since operators is itself row-versioned) — resolved per-scenario at load time. Nullable for generic/shared types.';
COMMENT ON COLUMN input_params.coach_types.coach_type_weight_gross_t IS 'Gross weight of a single coach of this type. Unit: t';
COMMENT ON COLUMN input_params.coach_types.coach_type_bikes          IS 'Number of bicycle spaces in this coach type.';
COMMENT ON COLUMN input_params.coach_types.coach_type_climatization  IS 'Whether this coach type has air conditioning.';
COMMENT ON COLUMN input_params.coach_types.coach_type_plugs          IS 'Whether this coach type has passenger power sockets.';
COMMENT ON COLUMN input_params.coach_types.coach_type_crew_factor    IS 'Fractional cabin crew per trip (e.g. 0.5 = one crew covers two coaches).';
COMMENT ON COLUMN input_params.coach_types.source_id                 IS 'Source for all values in this row.';
COMMENT ON COLUMN input_params.coach_types.change_log                IS 'Free-text description of changes made in this version.';
COMMENT ON COLUMN input_params.coach_types.coach_type_version        IS 'Per-table full-snapshot version number. Resolved via scenario.scenarios.coach_types_version — never inferred.';

-- ---------------------------------------------------------------
-- coach_type_classes
-- ---------------------------------------------------------------
CREATE TABLE input_params.coach_type_classes (
    coach_type_row_id        INTEGER      NOT NULL REFERENCES input_params.coach_types(coach_type_row_id) ON DELETE CASCADE,
    service_class_id         VARCHAR(100) NOT NULL REFERENCES input_params.service_classes(service_class_id),
    coach_type_class_places  INTEGER      NOT NULL CHECK (coach_type_class_places > 0),
    source_id                INTEGER      REFERENCES input_params.sources(source_id),
    PRIMARY KEY (coach_type_row_id, service_class_id)
);

COMMENT ON TABLE  input_params.coach_type_classes IS 'Places per accommodation class within a coach type.';
COMMENT ON COLUMN input_params.coach_type_classes.coach_type_class_places IS 'Number of places of this class in the coach type. Unit: pax';
COMMENT ON COLUMN input_params.coach_type_classes.source_id               IS 'Source for all values in this row.';

-- ---------------------------------------------------------------
-- composition_types
-- ---------------------------------------------------------------
CREATE TABLE input_params.composition_types (
    composition_type_row_id              SERIAL        PRIMARY KEY,
    composition_type_id                  VARCHAR(50)   NOT NULL,
    composition_type_description         VARCHAR(200)  NOT NULL,
    composition_type_operator_id         VARCHAR(50)   NOT NULL,
    composition_type_hsr_allowed         BOOLEAN       NOT NULL,
    composition_type_max_speed_kmh       NUMERIC(6,2)  NOT NULL,
    composition_type_energy_factor_weight  NUMERIC(10,6) NOT NULL,
    composition_type_energy_factor_speed   NUMERIC(10,6) NOT NULL,
    composition_type_energy_factor_terrain NUMERIC(10,6) NOT NULL,
    composition_type_min_boarding_time   INTERVAL      NOT NULL,
    composition_type_min_alighting_time  INTERVAL      NOT NULL,
    composition_type_purchase_coach_eur  NUMERIC(12,2) NOT NULL,
    composition_type_coach_avail_per     NUMERIC(5,4)  NOT NULL,
    composition_type_coach_amort_years   INTEGER       NOT NULL,
    composition_type_cleaning_eur_day    NUMERIC(10,3) NOT NULL,
    composition_type_coach_maint_eur_km  NUMERIC(10,8) NOT NULL,
    composition_type_driver_factor       NUMERIC(4,2)  NOT NULL DEFAULT 1,
    source_id                            INTEGER       REFERENCES input_params.sources(source_id),
    change_log                           TEXT,
    composition_type_version             INTEGER       NOT NULL DEFAULT 1,
    UNIQUE (composition_type_id, composition_type_version)
);

COMMENT ON TABLE  input_params.composition_types IS 'Train composition blueprints: operational and cost parameters. Capacity derived from composition_type_coaches → coach_type_classes. Locomotives are not purchased — see operators.operator_loco_lease_eur_h for full-service lease cost. Version bumps are full-table snapshots, resolved via scenario.scenarios.composition_types_version — see scenario.scenarios for the versioning contract.';
COMMENT ON COLUMN input_params.composition_types.composition_type_id          IS 'Unique composition identifier (e.g. STD-3.1).';
COMMENT ON COLUMN input_params.composition_types.composition_type_operator_id IS 'Operating company. Soft reference to input_params.operators.operator_id (not an enforced FK, since operators is itself row-versioned) — resolved per-scenario at load time.';
COMMENT ON COLUMN input_params.composition_types.composition_type_hsr_allowed IS 'Whether this composition may use high-speed rail infrastructure.';
COMMENT ON COLUMN input_params.composition_types.composition_type_max_speed_kmh IS 'Maximum operational speed. Unit: km/h';
COMMENT ON COLUMN input_params.composition_types.composition_type_energy_factor_weight  IS 'Energy regression coefficient for tonne-kilometre term. Unit: kWh/(t·km)';
COMMENT ON COLUMN input_params.composition_types.composition_type_energy_factor_speed   IS 'Energy regression coefficient for speed-squared term. Unit: kWh/((km/h)²·km)';
COMMENT ON COLUMN input_params.composition_types.composition_type_energy_factor_terrain IS 'Energy regression coefficient for terrain profile.';
COMMENT ON COLUMN input_params.composition_types.composition_type_min_boarding_time  IS 'Vehicle-dependent minimum dwell time at boarding stops. Unit: h';
COMMENT ON COLUMN input_params.composition_types.composition_type_min_alighting_time IS 'Vehicle-dependent minimum dwell time at alighting stops. Unit: h';
COMMENT ON COLUMN input_params.composition_types.composition_type_purchase_coach_eur IS 'Total purchase cost for all coaches. Unit: €';
COMMENT ON COLUMN input_params.composition_types.composition_type_coach_avail_per    IS 'Share of calendar days coach fleet is available. Unit: %';
COMMENT ON COLUMN input_params.composition_types.composition_type_coach_amort_years  IS 'Coach amortisation period. Unit: years';
COMMENT ON COLUMN input_params.composition_types.composition_type_cleaning_eur_day   IS 'Daily cleaning and service preparation cost. Unit: €/day';
COMMENT ON COLUMN input_params.composition_types.composition_type_coach_maint_eur_km IS 'Variable coach maintenance cost per km. Unit: €/km';
COMMENT ON COLUMN input_params.composition_types.composition_type_driver_factor      IS 'Number of drivers required per trip (e.g. 1 or 2).';
COMMENT ON COLUMN input_params.composition_types.source_id                           IS 'Source for all values in this row.';
COMMENT ON COLUMN input_params.composition_types.change_log                          IS 'Free-text description of changes made in this version.';
COMMENT ON COLUMN input_params.composition_types.composition_type_version            IS 'Per-table full-snapshot version number. Resolved via scenario.scenarios.composition_types_version — never inferred.';

-- ---------------------------------------------------------------
-- composition_type_coaches
-- ---------------------------------------------------------------
CREATE TABLE input_params.composition_type_coaches (
    composition_type_row_id INTEGER  NOT NULL REFERENCES input_params.composition_types(composition_type_row_id) ON DELETE CASCADE,
    position                SMALLINT NOT NULL CHECK (position >= 1),
    coach_type_row_id       INTEGER  NOT NULL REFERENCES input_params.coach_types(coach_type_row_id),
    PRIMARY KEY (composition_type_row_id, position)
);

COMMENT ON TABLE  input_params.composition_type_coaches          IS 'Ordered coach slots per composition type. coach_type_row_id is version-pinned.';
COMMENT ON COLUMN input_params.composition_type_coaches.position IS 'Position of the coach in the composition (1 = first coach behind the locomotive).';

-- ---------------------------------------------------------------
-- composition_references
-- Reference trip profile per composition — used to compute
-- indicative KPIs at load time via compute_indicative_figures()
-- in calc.py. One current row per composition_type_id.
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS input_params.composition_references (
    composition_reference_id  SERIAL          PRIMARY KEY,
    composition_type_row_id   INTEGER         NOT NULL REFERENCES input_params.composition_types(composition_type_row_id) ON DELETE CASCADE,
    composition_type_id       TEXT            NOT NULL,
    ref_distance_km           INTEGER         NOT NULL,
    ref_avg_speed_kmh         NUMERIC(6,2)    NOT NULL,
    ref_terrain_score         NUMERIC(6,3)    NOT NULL,
    ref_operating_days        INTEGER         NOT NULL DEFAULT 360,
    ref_utilization_seat      NUMERIC(4,3)    NOT NULL DEFAULT 0.70,
    ref_utilization_couchette NUMERIC(4,3)    NOT NULL DEFAULT 0.65,
    ref_utilization_sleeper   NUMERIC(4,3)    NOT NULL DEFAULT 0.80,
    ref_utilization_capsule   NUMERIC(4,3)    NOT NULL DEFAULT 0.70,
    ref_utilization_catering  NUMERIC(4,3)    NOT NULL DEFAULT 0.00,
    ref_avg_fare_seat         NUMERIC(8,2)    NOT NULL DEFAULT 49.00,
    ref_avg_fare_couchette    NUMERIC(8,2)    NOT NULL DEFAULT 79.00,
    ref_avg_fare_sleeper      NUMERIC(8,2)    NOT NULL DEFAULT 129.00,
    ref_avg_fare_capsule      NUMERIC(8,2)    NOT NULL DEFAULT 99.00,
    ref_avg_fare_catering     NUMERIC(8,2)    NOT NULL DEFAULT 0.00,
    version                   INTEGER         NOT NULL DEFAULT 1,
    change_log                TEXT,
    source_id                 INTEGER         REFERENCES input_params.sources(source_id)
);

COMMENT ON TABLE input_params.composition_references IS
    'Reference trip profile per composition for indicative KPI computation. Version bumps are full-table snapshots, resolved via scenario.scenarios.composition_references_version — see scenario.scenarios for the versioning contract.';
COMMENT ON COLUMN input_params.composition_references.version IS 'Per-table full-snapshot version number. Resolved via scenario.scenarios.composition_references_version — never inferred.';
COMMENT ON COLUMN input_params.composition_references.change_log IS 'Free-text description of changes made in this version.';

-- ---------------------------------------------------------------
-- track_infrastructure_defaults
-- ---------------------------------------------------------------
CREATE TABLE input_params.track_infrastructure_defaults (
    track_infra_default_id       SERIAL      PRIMARY KEY,
    track_infra_default_key      VARCHAR(50) NOT NULL,
    track_tac_eur_train_km       NUMERIC(8,2) NOT NULL,
    track_tac_src                INTEGER      REFERENCES input_params.sources(source_id),
    track_parking_eur_day        NUMERIC(8,2) NOT NULL,
    track_parking_src            INTEGER      REFERENCES input_params.sources(source_id),
    track_shunting_eur_event     NUMERIC(8,2) NOT NULL,
    track_shunting_src           INTEGER      REFERENCES input_params.sources(source_id),
    track_energy_price_eur_kwh   NUMERIC(6,3) NOT NULL,
    track_energy_price_src       INTEGER      REFERENCES input_params.sources(source_id),
    track_terrain_category       VARCHAR(20)  NOT NULL CHECK (track_terrain_category IN ('Flat','Hilly','Mountainous')),
    track_terrain_score          NUMERIC(5,2) NOT NULL,
    track_terrain_src            INTEGER      REFERENCES input_params.sources(source_id),
    track_hsr_allowed            BOOLEAN      NOT NULL,
    track_hsr_src                INTEGER      REFERENCES input_params.sources(source_id),
    track_min_boarding_time      INTERVAL     NOT NULL,
    track_min_boarding_src       INTEGER      REFERENCES input_params.sources(source_id),
    track_min_alighting_time     INTERVAL     NOT NULL,
    track_min_alighting_src      INTEGER      REFERENCES input_params.sources(source_id),
    track_buffer_quota_per       NUMERIC(5,3) NOT NULL,
    track_buffer_src             INTEGER      REFERENCES input_params.sources(source_id),
    change_log                   TEXT,
    track_infra_default_version  INTEGER      NOT NULL DEFAULT 1,
    UNIQUE (track_infra_default_key, track_infra_default_version)
);

COMMENT ON TABLE  input_params.track_infrastructure_defaults IS 'EU-average fallback track infrastructure parameters applied when a country field is NULL. Version bumps are full-table snapshots, resolved via scenario.scenarios.track_infrastructure_defaults_version — see scenario.scenarios for the versioning contract.';
COMMENT ON COLUMN input_params.track_infrastructure_defaults.change_log              IS 'Free-text description of changes made in this version.';
COMMENT ON COLUMN input_params.track_infrastructure_defaults.track_infra_default_version IS 'Per-table full-snapshot version number. Resolved via scenario.scenarios.track_infrastructure_defaults_version — never inferred.';

-- ---------------------------------------------------------------
-- track_infrastructures
-- ---------------------------------------------------------------
CREATE TABLE input_params.track_infrastructures (
    track_infra_row_id     SERIAL      PRIMARY KEY,
    country_code           CHAR(2)     NOT NULL REFERENCES input_params.countries(country_code),
    track_tac_eur_train_km       NUMERIC(8,2),
    track_tac_src                INTEGER      REFERENCES input_params.sources(source_id),
    track_parking_eur_day        NUMERIC(8,2),
    track_parking_src            INTEGER      REFERENCES input_params.sources(source_id),
    track_shunting_eur_event     NUMERIC(8,2),
    track_shunting_src           INTEGER      REFERENCES input_params.sources(source_id),
    track_energy_price_eur_kwh   NUMERIC(6,3),
    track_energy_price_src       INTEGER      REFERENCES input_params.sources(source_id),
    track_terrain_category       VARCHAR(20)  CHECK (track_terrain_category IN ('Flat','Hilly','Mountainous')),
    track_terrain_score          NUMERIC(5,2),
    track_terrain_src            INTEGER      REFERENCES input_params.sources(source_id),
    track_hsr_allowed            BOOLEAN,
    track_hsr_src                INTEGER      REFERENCES input_params.sources(source_id),
    track_min_boarding_time      INTERVAL,
    track_min_boarding_src       INTEGER      REFERENCES input_params.sources(source_id),
    track_min_alighting_time     INTERVAL,
    track_min_alighting_src      INTEGER      REFERENCES input_params.sources(source_id),
    track_buffer_quota_per       NUMERIC(5,3),
    track_buffer_src             INTEGER      REFERENCES input_params.sources(source_id),
    change_log                   TEXT,
    track_infra_version          INTEGER      NOT NULL DEFAULT 1,
    UNIQUE (country_code, track_infra_version)
);

COMMENT ON TABLE  input_params.track_infrastructures IS 'Country-level track infrastructure parameters. NULL fields are resolved against track_infrastructure_defaults by the loader. Version bumps are full-table snapshots — every country''s row is duplicated forward on any single-country edit — resolved via scenario.scenarios.track_infrastructures_version. See scenario.scenarios for the versioning contract.';
COMMENT ON COLUMN input_params.track_infrastructures.country_code             IS 'ISO 3166-1 alpha-2 country code. FK to countries table.';
COMMENT ON COLUMN input_params.track_infrastructures.track_tac_eur_train_km   IS 'Track access charge per train-km. Unit: €/train-km';
COMMENT ON COLUMN input_params.track_infrastructures.track_parking_eur_day    IS 'Overnight stabling cost per day. Unit: €/day';
COMMENT ON COLUMN input_params.track_infrastructures.track_shunting_eur_event IS 'Shunting cost per event at this country''s yards. Unit: €/event';
COMMENT ON COLUMN input_params.track_infrastructures.track_energy_price_eur_kwh IS 'Traction electricity price. Unit: €/kWh';
COMMENT ON COLUMN input_params.track_infrastructures.track_terrain_category   IS 'Qualitative terrain classification: Flat / Hilly / Mountainous.';
COMMENT ON COLUMN input_params.track_infrastructures.track_terrain_score      IS 'Numerical terrain difficulty score (1–100). Unit: 1–100';
COMMENT ON COLUMN input_params.track_infrastructures.track_hsr_allowed        IS 'Whether HSR infrastructure may be used for night train routing.';
COMMENT ON COLUMN input_params.track_infrastructures.track_min_boarding_time  IS 'Infrastructure-dependent minimum dwell time at boarding stops. Unit: h';
COMMENT ON COLUMN input_params.track_infrastructures.track_min_alighting_time IS 'Infrastructure-dependent minimum dwell time at alighting stops. Unit: h';
COMMENT ON COLUMN input_params.track_infrastructures.track_buffer_quota_per   IS 'Schedule buffer as fraction of driving time. Unit: %';
COMMENT ON COLUMN input_params.track_infrastructures.change_log               IS 'Free-text description of changes made in this version.';
COMMENT ON COLUMN input_params.track_infrastructures.track_infra_version      IS 'Per-table full-snapshot version number. Resolved via scenario.scenarios.track_infrastructures_version — never inferred.';

-- ---------------------------------------------------------------
-- stop_infrastructure_defaults
-- ---------------------------------------------------------------
CREATE TABLE input_params.stop_infrastructure_defaults (
    stop_infra_default_id      SERIAL      PRIMARY KEY,
    country_code               CHAR(2)     REFERENCES input_params.countries(country_code),
    stop_charge_eur            NUMERIC(10,2) NOT NULL,
    stop_charge_src            INTEGER      REFERENCES input_params.sources(source_id),
    change_log                 TEXT,
    stop_infra_default_version INTEGER      NOT NULL DEFAULT 1,
    UNIQUE (country_code, stop_infra_default_version)
);

COMMENT ON TABLE  input_params.stop_infrastructure_defaults IS 'Fallback stop access charge per country (country_code NULL = global default). Version bumps are full-table snapshots, resolved via scenario.scenarios.stop_infrastructure_defaults_version — see scenario.scenarios for the versioning contract.';
COMMENT ON COLUMN input_params.stop_infrastructure_defaults.country_code   IS 'Country this default applies to. NULL = global fallback.';
COMMENT ON COLUMN input_params.stop_infrastructure_defaults.stop_charge_eur IS 'Fallback station access charge per stop. Unit: €/stop';
COMMENT ON COLUMN input_params.stop_infrastructure_defaults.stop_charge_src IS 'Source for stop_charge_eur.';
COMMENT ON COLUMN input_params.stop_infrastructure_defaults.change_log     IS 'Free-text description of changes made in this version.';
COMMENT ON COLUMN input_params.stop_infrastructure_defaults.stop_infra_default_version IS 'Per-table full-snapshot version number. Resolved via scenario.scenarios.stop_infrastructure_defaults_version — never inferred.';

-- ---------------------------------------------------------------
-- stop_infrastructures
-- ---------------------------------------------------------------
CREATE TABLE input_params.stop_infrastructures (
    stop_infra_row_id  SERIAL       PRIMARY KEY,
    stop_id            VARCHAR(120) NOT NULL,
    stop_name          VARCHAR(120) NOT NULL,
    country_code       CHAR(2)      NOT NULL REFERENCES input_params.countries(country_code),
    stop_timezone      VARCHAR(50)  NOT NULL,
    stop_lat           NUMERIC(9,6) NOT NULL,
    stop_lon           NUMERIC(9,6) NOT NULL,
    stop_loc_src       INTEGER      REFERENCES input_params.sources(source_id),
    stop_charge_eur    NUMERIC(10,2),
    stop_charge_src    INTEGER      REFERENCES input_params.sources(source_id),
    change_log         TEXT,
    stop_infra_version INTEGER      NOT NULL DEFAULT 1,
    UNIQUE (stop_id, stop_infra_version)
);

COMMENT ON TABLE  input_params.stop_infrastructures IS 'Night train stopping points. stop_charge_eur NULL is resolved against stop_infrastructure_defaults by the loader. Version bumps are full-table snapshots — every stop''s row is duplicated forward on any single-stop edit — resolved via scenario.scenarios.stop_infrastructures_version. See scenario.scenarios for the versioning contract.';
COMMENT ON COLUMN input_params.stop_infrastructures.stop_id         IS 'Unique stop identifier.';
COMMENT ON COLUMN input_params.stop_infrastructures.stop_name       IS 'Official station name.';
COMMENT ON COLUMN input_params.stop_infrastructures.country_code    IS 'ISO 3166-1 alpha-2 country code. FK to countries.';
COMMENT ON COLUMN input_params.stop_infrastructures.stop_timezone   IS 'IANA timezone identifier (e.g. Europe/Berlin).';
COMMENT ON COLUMN input_params.stop_infrastructures.stop_lat        IS 'Latitude in WGS-84 decimal degrees. Unit: °';
COMMENT ON COLUMN input_params.stop_infrastructures.stop_lon        IS 'Longitude in WGS-84 decimal degrees. Unit: °';
COMMENT ON COLUMN input_params.stop_infrastructures.stop_loc_src    IS 'Source for lat/lon coordinates.';
COMMENT ON COLUMN input_params.stop_infrastructures.stop_charge_eur IS 'Station access charge per stop. NULL = use country or global default. Unit: €/stop';
COMMENT ON COLUMN input_params.stop_infrastructures.stop_charge_src IS 'Source for stop_charge_eur.';
COMMENT ON COLUMN input_params.stop_infrastructures.change_log      IS 'Free-text description of changes made in this version.';
COMMENT ON COLUMN input_params.stop_infrastructures.stop_infra_version IS 'Per-table full-snapshot version number. Resolved via scenario.scenarios.stop_infrastructures_version — never inferred.';