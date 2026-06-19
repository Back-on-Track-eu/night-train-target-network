DROP SCHEMA IF EXISTS input_params CASCADE;
CREATE SCHEMA input_params;

-- ---------------------------------------------------------------
-- sources: reusable source registry referenced by all versioned
-- parameter tables. Many-to-many between sources and parameters
-- is handled via source_id (row default) + column_sources JSONB
-- (per-column overrides) on each versioned table.
-- ---------------------------------------------------------------
CREATE TABLE input_params.sources (
    source_id          SERIAL PRIMARY KEY,
    source_description TEXT NOT NULL,
    source_url         TEXT,
    source_date        DATE
);

COMMENT ON TABLE  input_params.sources                  IS 'Reusable registry of data sources referenced by all versioned parameter tables. One row per source document or dataset.';
COMMENT ON COLUMN input_params.sources.source_description IS 'Human-readable description of the source (e.g. "DB Netz Trassenpreissystem 2025", "Eurostat Energy Statistics Q1 2025").';
COMMENT ON COLUMN input_params.sources.source_url         IS 'Optional URL pointing to the source document or dataset.';
COMMENT ON COLUMN input_params.sources.source_date        IS 'Date the source data was published or retrieved.';

-- ---------------------------------------------------------------
-- stops
-- ---------------------------------------------------------------
CREATE TABLE input_params.stops (
    stop_row_id           SERIAL PRIMARY KEY,
    stop_id               VARCHAR(120) NOT NULL,
    stop_name             VARCHAR(120) NOT NULL,
    stop_country_code     CHAR(2)      NOT NULL,
    stop_timezone         VARCHAR(50)  NOT NULL,
    stop_lat              NUMERIC(9,6) NOT NULL,
    stop_lon              NUMERIC(9,6) NOT NULL,
    stop_charge_eur       NUMERIC(10,2),
    source_id             INTEGER      REFERENCES input_params.sources(source_id),
    column_sources        JSONB,
    stop_version          INTEGER      NOT NULL DEFAULT 1,
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
    is_current            BOOLEAN      NOT NULL DEFAULT TRUE,
    UNIQUE (stop_id, stop_version)
);
CREATE UNIQUE INDEX idx_stops_one_current_per_stop
    ON input_params.stops (stop_id) WHERE is_current;

COMMENT ON TABLE  input_params.stops                IS 'Night train stopping points. One row per station version.';
COMMENT ON COLUMN input_params.stops.stop_id        IS 'Unique stop identifier. Primary key for stop lookups from the routing engine and cost model.';
COMMENT ON COLUMN input_params.stops.stop_name      IS 'Official station name in local script.';
COMMENT ON COLUMN input_params.stops.stop_country_code IS 'ISO 3166-1 alpha-2 country code of the stop.';
COMMENT ON COLUMN input_params.stops.stop_timezone  IS 'IANA timezone identifier for the stop (e.g. Europe/Berlin).';
COMMENT ON COLUMN input_params.stops.stop_lat       IS 'Latitude of the stop in WGS-84 decimal degrees. Unit: °';
COMMENT ON COLUMN input_params.stops.stop_lon       IS 'Longitude of the stop in WGS-84 decimal degrees. Unit: °';
COMMENT ON COLUMN input_params.stops.stop_charge_eur IS 'Station access charge per train stop. Applied to intermediate stops in the cost model. Unit: €/stop';
COMMENT ON COLUMN input_params.stops.source_id      IS 'Default source for all columns in this row. Per-column overrides stored in column_sources.';
COMMENT ON COLUMN input_params.stops.column_sources IS 'JSONB map of column_name → source_id for any column whose source differs from the row-level source_id. E.g. {"stop_charge_eur": 3}.';

-- ---------------------------------------------------------------
-- stop_defaults
-- ---------------------------------------------------------------
CREATE TABLE input_params.stop_defaults (
    stop_default_id       SERIAL PRIMARY KEY,
    stop_default_key      VARCHAR(50)  NOT NULL,
    stop_charge_eur       NUMERIC(10,2) NOT NULL,
    source_id             INTEGER      REFERENCES input_params.sources(source_id),
    column_sources        JSONB,
    stop_default_version  INTEGER      NOT NULL DEFAULT 1,
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
    is_current            BOOLEAN      NOT NULL DEFAULT TRUE,
    UNIQUE (stop_default_key, stop_default_version)
);
CREATE UNIQUE INDEX idx_stop_defaults_one_current_per_key
    ON input_params.stop_defaults (stop_default_key) WHERE is_current;

COMMENT ON TABLE  input_params.stop_defaults             IS 'Fallback stop access charge applied when a stop has no explicit charge_eur.';
COMMENT ON COLUMN input_params.stop_defaults.stop_charge_eur IS 'EU average station access charge per stop. Unit: €/stop';
COMMENT ON COLUMN input_params.stop_defaults.source_id   IS 'Default source for all columns in this row.';
COMMENT ON COLUMN input_params.stop_defaults.column_sources IS 'Per-column source overrides. See input_params.stops.column_sources.';

-- ---------------------------------------------------------------
-- infrastructure
-- ---------------------------------------------------------------
CREATE TABLE input_params.infrastructure (
    infra_row_id               SERIAL PRIMARY KEY,
    country_code               CHAR(2)      NOT NULL,
    country_name               VARCHAR(100) NOT NULL,
    infra_tac_eur_train_km     NUMERIC(8,2) NOT NULL,
    infra_parking_eur_day      NUMERIC(8,2) NOT NULL,
    infra_energy_price_eur_kwh NUMERIC(6,3) NOT NULL,
    infra_terrain_category     VARCHAR(20)  NOT NULL CHECK (infra_terrain_category IN ('Flat','Hilly','Mountainous')),
    infra_terrain_score        NUMERIC(5,2) NOT NULL,
    infra_hsr_allowed          BOOLEAN      NOT NULL,
    infra_min_boarding_time_h  INTERVAL     NOT NULL,
    infra_min_alighting_time_h INTERVAL     NOT NULL,
    infra_buffer_quota_per     NUMERIC(5,3) NOT NULL,
    source_id                  INTEGER      REFERENCES input_params.sources(source_id),
    column_sources             JSONB,
    infra_version              INTEGER      NOT NULL DEFAULT 1,
    created_at                 TIMESTAMPTZ  NOT NULL DEFAULT now(),
    is_current                 BOOLEAN      NOT NULL DEFAULT TRUE,
    UNIQUE (country_code, infra_version)
);
CREATE UNIQUE INDEX idx_infrastructure_one_current_per_country
    ON input_params.infrastructure (country_code) WHERE is_current;

COMMENT ON TABLE  input_params.infrastructure IS 'Country-level infrastructure parameters used in routing and cost model.';
COMMENT ON COLUMN input_params.infrastructure.country_code           IS 'ISO 3166-1 alpha-2 country code. Primary key — one row per country per version.';
COMMENT ON COLUMN input_params.infrastructure.country_name           IS 'Full country name.';
COMMENT ON COLUMN input_params.infrastructure.infra_tac_eur_train_km IS 'Track access charge payable to the infrastructure manager per train-kilometre operated in this country. Unit: €/train-km';
COMMENT ON COLUMN input_params.infrastructure.infra_parking_eur_day  IS 'Fixed daily infrastructure access fee for train stabling or parking at origin/destination station. Unit: €/day';
COMMENT ON COLUMN input_params.infrastructure.infra_energy_price_eur_kwh IS 'Traction electricity price in this country. Unit: €/kWh';
COMMENT ON COLUMN input_params.infrastructure.infra_terrain_category IS 'Qualitative terrain classification used in energy modelling: Flat / Hilly / Mountainous.';
COMMENT ON COLUMN input_params.infrastructure.infra_terrain_score    IS 'Numerical terrain difficulty score (1–100). Used with comp_energy_factor_terrain in energy regression. Unit: 1–100';
COMMENT ON COLUMN input_params.infrastructure.infra_hsr_allowed      IS 'Whether high-speed rail infrastructure may be used in this country for night train routing.';
COMMENT ON COLUMN input_params.infrastructure.infra_min_boarding_time_h  IS 'Infrastructure-dependent minimum dwell time at boarding stops. Scheduler uses max(this, comp_veh_min_boarding_time). Unit: h';
COMMENT ON COLUMN input_params.infrastructure.infra_min_alighting_time_h IS 'Infrastructure-dependent minimum dwell time at alighting stops. Unit: h';
COMMENT ON COLUMN input_params.infrastructure.infra_buffer_quota_per IS 'Schedule buffer added on top of calculated driving time per country. Accounts for disruption and timetable margins. Unit: %';
COMMENT ON COLUMN input_params.infrastructure.source_id              IS 'Default source for all columns in this row. Per-column overrides in column_sources.';
COMMENT ON COLUMN input_params.infrastructure.column_sources         IS 'JSONB map of column_name → source_id for columns with a different source than the row default. E.g. {"infra_energy_price_eur_kwh": 4, "infra_terrain_score": 5}.';

-- ---------------------------------------------------------------
-- infrastructure_defaults
-- ---------------------------------------------------------------
CREATE TABLE input_params.infrastructure_defaults (
    infra_default_id              SERIAL PRIMARY KEY,
    infra_default_key             VARCHAR(50)  NOT NULL,
    infra_tac_eur_train_km        NUMERIC(8,2) NOT NULL,
    infra_parking_eur_day         NUMERIC(8,2) NOT NULL,
    infra_energy_price_eur_kwh    NUMERIC(6,3) NOT NULL,
    infra_terrain_category        VARCHAR(20)  NOT NULL CHECK (infra_terrain_category IN ('Flat','Hilly','Mountainous')),
    infra_terrain_score           NUMERIC(5,2) NOT NULL,
    infra_hsr_allowed             BOOLEAN      NOT NULL,
    infra_min_boarding_time_h     INTERVAL     NOT NULL,
    infra_min_alighting_time_h    INTERVAL     NOT NULL,
    infra_buffer_quota_per        NUMERIC(5,3) NOT NULL,
    source_id                     INTEGER      REFERENCES input_params.sources(source_id),
    column_sources                JSONB,
    infra_default_version         INTEGER      NOT NULL DEFAULT 1,
    created_at                    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    is_current                    BOOLEAN      NOT NULL DEFAULT TRUE,
    UNIQUE (infra_default_key, infra_default_version)
);
CREATE UNIQUE INDEX idx_infrastructure_defaults_one_current_per_key
    ON input_params.infrastructure_defaults (infra_default_key) WHERE is_current;

COMMENT ON TABLE  input_params.infrastructure_defaults IS 'EU-average fallback infrastructure parameters applied when a country row is missing.';
COMMENT ON COLUMN input_params.infrastructure_defaults.source_id      IS 'Default source for all columns in this row.';
COMMENT ON COLUMN input_params.infrastructure_defaults.column_sources IS 'Per-column source overrides. See input_params.infrastructure.column_sources.';

-- ---------------------------------------------------------------
-- classes
-- ---------------------------------------------------------------
CREATE TABLE input_params.classes (
    class_id   VARCHAR(100) PRIMARY KEY,
    class_main VARCHAR(50)  NOT NULL
);

COMMENT ON TABLE  input_params.classes          IS 'Stable accommodation class taxonomy. class_main groups: Seat, Couchette, Sleeper, Capsule, Catering.';
COMMENT ON COLUMN input_params.classes.class_id   IS 'Unique class identifier (e.g. "couchette (6-berth)", "Sleeper (2-berth) with shower & WC").';
COMMENT ON COLUMN input_params.classes.class_main IS 'Top-level accommodation category: Seat, Couchette, Sleeper, Capsule, or Catering.';

-- ---------------------------------------------------------------
-- operators
-- ---------------------------------------------------------------
CREATE TABLE input_params.operators (
    operator_id                     VARCHAR(50)   PRIMARY KEY,
    operator_name                   VARCHAR(200)  NOT NULL,
    operator_driver_costs_eur_h     NUMERIC(8,2)  NOT NULL,
    operator_crew_costs_eur_h       NUMERIC(8,2)  NOT NULL,
    operator_driver_overhead_h      INTERVAL      NOT NULL,
    operator_crew_overhead_h        INTERVAL      NOT NULL,
    operator_ebit_margin_per        NUMERIC(5,4)  NOT NULL,
    operator_financing_quota_per    NUMERIC(5,4)  NOT NULL,
    operator_shunting_eur_per_event NUMERIC(10,3) NOT NULL,
    operator_var_overhead_per       NUMERIC(5,4)  NOT NULL,
    operator_fix_overhead_quota_per NUMERIC(5,4)  NOT NULL,
    source_id                       INTEGER       REFERENCES input_params.sources(source_id),
    column_sources                  JSONB
);

COMMENT ON TABLE  input_params.operators IS 'Train operating company — bears operational costs. Distinct from a GTFS agency (the passenger-facing booking brand). On GTFS export, operator_id maps to agency_id in agency.txt.';
COMMENT ON COLUMN input_params.operators.operator_driver_costs_eur_h     IS 'Driver staff cost per billable hour. Billable hours = driving time + operator_driver_overhead_h. Unit: €/h';
COMMENT ON COLUMN input_params.operators.operator_crew_costs_eur_h       IS 'Cabin crew cost per billable hour. Billable hours = driving time + operator_crew_overhead_h. Unit: €/h';
COMMENT ON COLUMN input_params.operators.operator_driver_overhead_h      IS 'Fixed overhead hours added per trip to driving time for driver cost calculation (handover, briefing, positioning). Unit: h/trip';
COMMENT ON COLUMN input_params.operators.operator_crew_overhead_h        IS 'Fixed overhead hours added per trip to driving time for cabin crew cost calculation. Unit: h/trip';
COMMENT ON COLUMN input_params.operators.operator_ebit_margin_per        IS 'Required EBIT margin as a share of revenue. Treated as a cost target deducted from revenue in the model. Unit: %';
COMMENT ON COLUMN input_params.operators.operator_financing_quota_per    IS 'Annual financing cost as a share of total capital employed (loco + coach purchase value combined). Unit: %/year';
COMMENT ON COLUMN input_params.operators.operator_shunting_eur_per_event IS 'Cost per shunting event (positioning the train at origin/destination). Unit: €/event';
COMMENT ON COLUMN input_params.operators.operator_var_overhead_per       IS 'Variable overhead as a share of total ticket revenue. Covers customer incentives, compensations, customer service, payment processing. Unit: %';
COMMENT ON COLUMN input_params.operators.operator_fix_overhead_quota_per IS 'Fixed overhead as a share of all other railway operation costs (excl. amortisation and financing). Covers overhead payroll, tools & software, crew bases, HQ, marketing, R&D. Unit: %';
COMMENT ON COLUMN input_params.operators.source_id                       IS 'Default source for all columns in this row. Per-column overrides in column_sources.';
COMMENT ON COLUMN input_params.operators.column_sources                  IS 'JSONB map of column_name → source_id for columns with a different source than the row default.';

-- ---------------------------------------------------------------
-- operator_class_costs
-- ---------------------------------------------------------------
CREATE TABLE input_params.operator_class_costs (
    operator_id                              VARCHAR(50)  NOT NULL REFERENCES input_params.operators(operator_id),
    class_id                                 VARCHAR(100) NOT NULL REFERENCES input_params.classes(class_id),
    operator_class_svc_stockings_eur_place   NUMERIC(8,4) NOT NULL,
    source_id                                INTEGER      REFERENCES input_params.sources(source_id),
    column_sources                           JSONB,
    PRIMARY KEY (operator_id, class_id)
);

COMMENT ON TABLE  input_params.operator_class_costs IS 'Variable cost of onboard services and stockings (linen, amenities, catering), per operator and accommodation class.';
COMMENT ON COLUMN input_params.operator_class_costs.operator_class_svc_stockings_eur_place IS 'Service and stockings cost per available place per trip, for this operator and class combination. Unit: €/place';
COMMENT ON COLUMN input_params.operator_class_costs.source_id      IS 'Default source for all columns in this row.';
COMMENT ON COLUMN input_params.operator_class_costs.column_sources IS 'Per-column source overrides.';

-- ---------------------------------------------------------------
-- coachtypes
-- ---------------------------------------------------------------
CREATE TABLE input_params.coachtypes (
    coachtype_row_id         SERIAL PRIMARY KEY,
    coachtype_id             VARCHAR(50)  NOT NULL,
    coachtype_operator_id    VARCHAR(50)  REFERENCES input_params.operators(operator_id),
    coachtype_weight_gross_t NUMERIC(8,3),
    coachtype_bikes          INTEGER      NOT NULL DEFAULT 0,
    coachtype_climatization  BOOLEAN      NOT NULL DEFAULT FALSE,
    coachtype_plugs          BOOLEAN      NOT NULL DEFAULT FALSE,
    coachtype_crew_factor    NUMERIC(4,2) NOT NULL DEFAULT 0,
    coachtype_remarks        TEXT,
    source_id                INTEGER      REFERENCES input_params.sources(source_id),
    column_sources           JSONB,
    coachtype_version        INTEGER      NOT NULL DEFAULT 1,
    created_at               TIMESTAMPTZ  NOT NULL DEFAULT now(),
    is_current               BOOLEAN      NOT NULL DEFAULT TRUE,
    UNIQUE (coachtype_id, coachtype_version)
);
CREATE UNIQUE INDEX idx_coachtypes_one_current_per_coachtype
    ON input_params.coachtypes (coachtype_id) WHERE is_current;

COMMENT ON TABLE  input_params.coachtypes IS 'Individual railcar/coach types. Capacity is derived from coachtype_classes, not stored here.';
COMMENT ON COLUMN input_params.coachtypes.coachtype_id             IS 'Unique coach type identifier (e.g. WLABmz, Bcmz, type1).';
COMMENT ON COLUMN input_params.coachtypes.coachtype_operator_id    IS 'Operating company this coach type belongs to. Nullable for generic/shared types.';
COMMENT ON COLUMN input_params.coachtypes.coachtype_weight_gross_t IS 'Gross weight of a single coach of this type. Unit: t';
COMMENT ON COLUMN input_params.coachtypes.coachtype_bikes          IS 'Number of bicycle spaces in this coach type.';
COMMENT ON COLUMN input_params.coachtypes.coachtype_climatization  IS 'Whether this coach type has air conditioning.';
COMMENT ON COLUMN input_params.coachtypes.coachtype_plugs          IS 'Whether this coach type has passenger power sockets.';
COMMENT ON COLUMN input_params.coachtypes.coachtype_crew_factor    IS 'Fractional cabin crew assigned to this coach type per trip (e.g. 0.5 means one crew member covers two coaches of this type).';
COMMENT ON COLUMN input_params.coachtypes.coachtype_remarks        IS 'Free-text remarks about this coach type.';
COMMENT ON COLUMN input_params.coachtypes.source_id                IS 'Default source for all columns in this row. Per-column overrides in column_sources.';
COMMENT ON COLUMN input_params.coachtypes.column_sources           IS 'JSONB map of column_name → source_id for columns with a different source than the row default.';

-- ---------------------------------------------------------------
-- coachtype_classes
-- ---------------------------------------------------------------
CREATE TABLE input_params.coachtype_classes (
    coachtype_row_id       INTEGER      NOT NULL REFERENCES input_params.coachtypes(coachtype_row_id) ON DELETE CASCADE,
    class_id               VARCHAR(100) NOT NULL REFERENCES input_params.classes(class_id),
    coachtype_class_places INTEGER      NOT NULL CHECK (coachtype_class_places > 0),
    source_id              INTEGER      REFERENCES input_params.sources(source_id),
    column_sources         JSONB,
    PRIMARY KEY (coachtype_row_id, class_id)
);

COMMENT ON TABLE  input_params.coachtype_classes IS 'Places per accommodation class within a coach type. Replaces the wide class_id_1..4 / places_1..4 slot columns.';
COMMENT ON COLUMN input_params.coachtype_classes.coachtype_class_places IS 'Number of places of this class in the coach type. Unit: pax';
COMMENT ON COLUMN input_params.coachtype_classes.source_id              IS 'Default source for this row.';
COMMENT ON COLUMN input_params.coachtype_classes.column_sources         IS 'Per-column source overrides.';

-- ---------------------------------------------------------------
-- compositions
-- ---------------------------------------------------------------
CREATE TABLE input_params.compositions (
    comp_row_id                      SERIAL PRIMARY KEY,
    comp_id                          VARCHAR(50)   NOT NULL,
    comp_description                 VARCHAR(200)  NOT NULL,
    comp_operator_id                 VARCHAR(50)   NOT NULL REFERENCES input_params.operators(operator_id),
    comp_hsr_allowed                 BOOLEAN       NOT NULL,
    comp_max_speed_kmh               NUMERIC(6,2)  NOT NULL,
    comp_energy_factor_weight        NUMERIC(10,6) NOT NULL,
    comp_energy_factor_speed         NUMERIC(10,6) NOT NULL,
    comp_energy_factor_terrain       NUMERIC(10,6) NOT NULL,
    comp_veh_min_boarding_time       INTERVAL      NOT NULL,
    comp_veh_min_alighting_time      INTERVAL      NOT NULL,
    comp_purchase_loco_eur           NUMERIC(12,2) NOT NULL,
    comp_purchase_coach_eur          NUMERIC(12,2) NOT NULL,
    comp_loco_avail_per              NUMERIC(5,4)  NOT NULL,
    comp_coach_avail_per             NUMERIC(5,4)  NOT NULL,
    comp_loco_amort_years            INTEGER       NOT NULL,
    comp_coach_amort_years           INTEGER       NOT NULL,
    comp_cleaning_services_eur_day   NUMERIC(10,3) NOT NULL,
    comp_loco_maint_eur_km           NUMERIC(10,8) NOT NULL,
    comp_coach_maint_eur_km          NUMERIC(10,8) NOT NULL,
    comp_driver_factor               NUMERIC(4,2)  NOT NULL DEFAULT 1,
    source_id                        INTEGER       REFERENCES input_params.sources(source_id),
    column_sources                   JSONB,
    comp_version                     INTEGER       NOT NULL DEFAULT 1,
    created_at                       TIMESTAMPTZ   NOT NULL DEFAULT now(),
    is_current                       BOOLEAN       NOT NULL DEFAULT TRUE,
    UNIQUE (comp_id, comp_version)
);
CREATE UNIQUE INDEX idx_compositions_one_current_per_comp
    ON input_params.compositions (comp_id) WHERE is_current;

COMMENT ON TABLE  input_params.compositions IS 'Train compositions: operational and cost parameters at formation level. Capacity is derived from composition_coaches → coachtype_classes.';
COMMENT ON COLUMN input_params.compositions.comp_id               IS 'Unique composition identifier (e.g. STD-3.1).';
COMMENT ON COLUMN input_params.compositions.comp_description      IS 'Human-readable description of the composition.';
COMMENT ON COLUMN input_params.compositions.comp_operator_id      IS 'Operating company. Links to operators for operator-specific cost parameters (driver/crew costs, ebit margin, etc.).';
COMMENT ON COLUMN input_params.compositions.comp_hsr_allowed      IS 'Whether the composition is permitted to use high-speed rail infrastructure.';
COMMENT ON COLUMN input_params.compositions.comp_max_speed_kmh    IS 'Maximum operational speed of the composition. Unit: km/h';
COMMENT ON COLUMN input_params.compositions.comp_energy_factor_weight  IS 'Energy regression coefficient for the tonne-kilometre term: energy_kwh += factor × weight_t × leg_km. Unit: kWh/(t·km)';
COMMENT ON COLUMN input_params.compositions.comp_energy_factor_speed   IS 'Energy regression coefficient for the speed-squared term: energy_kwh += factor × avg_speed² × leg_km. Unit: kWh/((km/h)²·km)';
COMMENT ON COLUMN input_params.compositions.comp_energy_factor_terrain IS 'Energy regression coefficient for terrain profile. Multiplied by the terrain score from infrastructure table.';
COMMENT ON COLUMN input_params.compositions.comp_veh_min_boarding_time  IS 'Vehicle-dependent minimum dwell time at boarding stops. Scheduler uses max(this, infra_min_boarding_time_h). Unit: h';
COMMENT ON COLUMN input_params.compositions.comp_veh_min_alighting_time IS 'Vehicle-dependent minimum dwell time at alighting stops. Unit: h';
COMMENT ON COLUMN input_params.compositions.comp_purchase_loco_eur  IS 'Total purchase or leasing cost for all locomotives in the composition. Unit: €';
COMMENT ON COLUMN input_params.compositions.comp_purchase_coach_eur IS 'Total purchase or leasing cost for all coaches in the composition. Unit: €';
COMMENT ON COLUMN input_params.compositions.comp_loco_avail_per     IS 'Share of calendar days the locomotive fleet is available for revenue service. Unit: %';
COMMENT ON COLUMN input_params.compositions.comp_coach_avail_per    IS 'Share of calendar days the coach fleet is available for revenue service. Unit: %';
COMMENT ON COLUMN input_params.compositions.comp_loco_amort_years   IS 'Amortisation period over which locomotive purchase cost is spread. Unit: years';
COMMENT ON COLUMN input_params.compositions.comp_coach_amort_years  IS 'Amortisation period over which coach purchase cost is spread. Unit: years';
COMMENT ON COLUMN input_params.compositions.comp_cleaning_services_eur_day IS 'Daily cost of train cleaning and onboard service preparation. Unit: €/day';
COMMENT ON COLUMN input_params.compositions.comp_loco_maint_eur_km  IS 'Variable locomotive maintenance cost per kilometre operated. Unit: €/km';
COMMENT ON COLUMN input_params.compositions.comp_coach_maint_eur_km IS 'Variable coach maintenance cost per kilometre operated. Unit: €/km';
COMMENT ON COLUMN input_params.compositions.comp_driver_factor       IS 'Number of drivers required per trip for this composition (e.g. 1 or 2).';
COMMENT ON COLUMN input_params.compositions.source_id                IS 'Default source for all columns in this row. Per-column overrides in column_sources.';
COMMENT ON COLUMN input_params.compositions.column_sources           IS 'JSONB map of column_name → source_id for columns with a different source than the row default.';

-- ---------------------------------------------------------------
-- composition_coaches
-- ---------------------------------------------------------------
CREATE TABLE input_params.composition_coaches (
    comp_row_id      INTEGER  NOT NULL REFERENCES input_params.compositions(comp_row_id) ON DELETE CASCADE,
    position         SMALLINT NOT NULL CHECK (position >= 1),
    coachtype_row_id INTEGER  NOT NULL REFERENCES input_params.coachtypes(coachtype_row_id),
    PRIMARY KEY (comp_row_id, position)
);

COMMENT ON TABLE  input_params.composition_coaches IS 'Ordered coach slots per composition. Replaces the wide coach_01_type..coach_14_type columns. coachtype_row_id is version-pinned so a composition snapshot is stable even if a coach type is later revised.';
COMMENT ON COLUMN input_params.composition_coaches.position IS 'Ordered position of the coach within the composition (1 = first coach behind the locomotive).';