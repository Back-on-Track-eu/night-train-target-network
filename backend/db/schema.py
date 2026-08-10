"""
schema.py
=========
Declarative definition of the input_params and scenario schemas — the
single reviewable file for every parameter table: each column with its
type, a plain-language description, and its unit.

seed.py renders this into DDL via build_ddl() (CREATE SCHEMA / CREATE
TABLE / COMMENT ON / CREATE INDEX) instead of loading a .sql file, so
what the team reviews here is exactly what the database gets. The other
schemas (admin, proposals, ontd) are application plumbing, not parameter
definitions, and stay as .sql files under dev/sql/ and ontd/sql/.

Descriptions are written for tool users and become the COMMENT ON
TABLE/COLUMN texts (visible e.g. in Mathesar); units are appended as
"Unit: X". Versioning contract for the four snapshot-versioned
infrastructure tables and the scenario container: db/README.md, section
"Schema overview".
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Column:
    """One table column.

    name        — column name
    sql_type    — verbatim PostgreSQL type incl. column constraints
                  (NOT NULL, DEFAULT, REFERENCES, CHECK)
    description — plain-language meaning, becomes COMMENT ON COLUMN;
                  empty = no comment
    unit        — display unit, appended to the comment as "Unit: X"
    """

    name: str
    sql_type: str
    description: str = ""
    unit: str = ""


@dataclass(frozen=True)
class Table:
    """One table: columns plus verbatim table-level constraint and index
    lines. description becomes COMMENT ON TABLE."""

    schema: str
    name: str
    description: str
    columns: tuple[Column, ...]
    constraints: tuple[str, ...] = ()
    indexes: tuple[str, ...] = ()


def _src(name: str, of: str) -> Column:
    """Source-reference column — every parameter table links its values
    to the sources registry so each number stays traceable."""
    return Column(
        name,
        "INTEGER REFERENCES input_params.sources(source_id)",
        f"Source for {of}.",
    )


def _track_param_columns(nullable: bool) -> tuple[Column, ...]:
    """The ten track parameters shared verbatim by track_infrastructures
    (nullable — empty resolves against the defaults table) and
    track_infrastructure_defaults (NOT NULL — they ARE the fallback)."""
    nn = "" if nullable else " NOT NULL"
    return (
        Column(
            "track_tac_eur_train_km",
            f"NUMERIC(8,2){nn}",
            "Track access charge — the 'rail toll' paid to the country's "
            "infrastructure company per kilometre driven.",
            "€/train-km",
        ),
        _src("track_tac_src", "the track access charge"),
        Column(
            "track_parking_eur_day",
            f"NUMERIC(8,2){nn}",
            "Cost of parking the train overnight between two nights of service.",
            "€/day",
        ),
        _src("track_parking_src", "the parking cost"),
        Column(
            "track_shunting_eur_event",
            f"NUMERIC(8,2){nn}",
            "Cost of one shunting movement (coupling, uncoupling, moving "
            "the train in the yard).",
            "€/event",
        ),
        _src("track_shunting_src", "the shunting cost"),
        Column(
            "track_energy_price_eur_kwh",
            f"NUMERIC(6,3){nn}",
            "Traction electricity price.",
            "€/kWh",
        ),
        _src("track_energy_price_src", "the electricity price"),
        Column(
            "track_terrain_category",
            f"VARCHAR(20){nn} CHECK (track_terrain_category IN "
            "('Flat','Hilly','Mountainous'))",
            "Rough terrain classification: Flat, Hilly, or Mountainous.",
        ),
        Column(
            "track_terrain_score",
            f"NUMERIC(5,2){nn}",
            "Terrain difficulty score — hills and mountains increase energy use.",
            "1–100",
        ),
        _src("track_terrain_src", "terrain category and score"),
        Column(
            "track_hsr_allowed",
            f"BOOLEAN{nn}",
            "Whether night trains may use the country's high-speed lines.",
        ),
        _src("track_hsr_src", "the high-speed permission"),
        Column(
            "track_min_boarding_time",
            f"INTERVAL{nn}",
            "Minimum waiting time the country's stations need at stops "
            "where passengers board.",
            "interval (hh:mm:ss)",
        ),
        _src("track_min_boarding_src", "the minimum boarding time"),
        Column(
            "track_min_alighting_time",
            f"INTERVAL{nn}",
            "Minimum waiting time the country's stations need at stops "
            "where passengers get off.",
            "interval (hh:mm:ss)",
        ),
        _src("track_min_alighting_src", "the minimum alighting time"),
        Column(
            "track_buffer_quota_per",
            f"NUMERIC(5,3){nn}",
            "Schedule buffer added on top of driving time, reflecting how "
            "congested and delay-prone the network is.",
            "fraction of driving time",
        ),
        _src("track_buffer_src", "the buffer quota"),
    )


_CHANGE_LOG = Column(
    "change_log",
    "TEXT",
    "Free-text description of what changed in this version and why.",
)


# =============================================================================
# input_params — the domain parameter tables
# =============================================================================

INPUT_PARAMS_TABLES: tuple[Table, ...] = (
    Table(
        schema="input_params",
        name="countries",
        description="Country reference table with border polygons.",
        columns=(
            Column(
                "country_code",
                "CHAR(2) PRIMARY KEY",
                "Two-letter country code (ISO 3166-1 alpha-2). Primary key.",
            ),
            Column(
                "country_name",
                "VARCHAR(100) NOT NULL",
                "Full English country name.",
            ),
            Column(
                "country_geom",
                "geometry(MultiPolygon, 4326)",
                "Country border polygon (SRID 4326), seeded from Natural "
                "Earth admin-0 countries geojson. Empty for countries "
                "without a matched source feature.",
            ),
        ),
        indexes=(
            "CREATE INDEX idx_countries_geom ON input_params.countries "
            "USING GIST (country_geom);",
        ),
    ),
    Table(
        schema="input_params",
        name="sources",
        description="Registry of data sources. Every parameter row can "
        "point to the source its values came from, so every number in the "
        "tool stays traceable. One row per source document or dataset.",
        columns=(
            Column("source_id", "SERIAL PRIMARY KEY"),
            Column(
                "source_description",
                "TEXT NOT NULL",
                'Human-readable description of the source (e.g. "DB Netz '
                'Trassenpreissystem 2025").',
            ),
            Column(
                "source_url",
                "TEXT",
                "Optional link to the source document or dataset.",
            ),
            Column(
                "source_date",
                "DATE",
                "Date the source data was published or retrieved.",
            ),
        ),
    ),
    Table(
        schema="input_params",
        name="service_classes",
        description="Accommodation class taxonomy. service_class_main "
        "groups the detailed classes into: Seat, Couchette, Sleeper, "
        "Capsule, Catering.",
        columns=(
            Column(
                "service_class_id",
                "VARCHAR(200) PRIMARY KEY",
                'Detailed class name (e.g. "couchette (6-berth)", '
                '"Sleeper (2-berth) with shower & WC").',
            ),
            Column(
                "service_class_main",
                "VARCHAR(50) NOT NULL",
                "Top-level accommodation category: Seat, Couchette, "
                "Sleeper, Capsule, or Catering.",
            ),
        ),
    ),
    Table(
        schema="input_params",
        name="operators",
        description="Train operating company and its cost rates. A "
        "catalog, not history: operator_id is a permanent natural key — "
        "changed rates mean adding a new operator_id, never editing a row "
        "in place (soft-referenced from coach_types and "
        "composition_types).",
        columns=(
            Column("operator_row_id", "SERIAL PRIMARY KEY"),
            Column(
                "operator_id",
                "VARCHAR(50) NOT NULL",
                "Operator identifier (e.g. STD-REF, STD-NEW).",
            ),
            Column(
                "operator_name",
                "VARCHAR(200) NOT NULL",
                "Full operator name.",
            ),
            Column(
                "operator_driver_costs_eur_h",
                "NUMERIC(8,2) NOT NULL",
                "Driver pay per hour on duty (roster inefficiency already "
                "included — billable hours equal trip time).",
                "€/h",
            ),
            Column(
                "operator_crew_costs_eur_h",
                "NUMERIC(8,2) NOT NULL",
                "Cabin crew pay per hour on duty, per attendant. The train "
                "manager is counted with a factor on the composition.",
                "€/h",
            ),
            Column(
                "operator_ebit_margin_per",
                "NUMERIC(5,4) NOT NULL",
                "Operating profit the operator requires, as a share of ticket revenue.",
                "fraction of revenue",
            ),
            Column(
                "operator_financing_quota_per",
                "NUMERIC(5,4) NOT NULL",
                "Annual financing cost as a share of the capital tied up in coaches.",
                "fraction/year",
            ),
            Column(
                "operator_var_overhead_per",
                "NUMERIC(5,4) NOT NULL",
                "Variable overhead — ticket sales, distribution, customer "
                "service — as a share of ticket revenue.",
                "fraction of revenue",
            ),
            Column(
                "operator_fix_overhead_quota_per",
                "NUMERIC(5,4) NOT NULL",
                "Fixed overhead — administration, management, planning — "
                "as a share of all other operating costs.",
                "fraction of other costs",
            ),
            Column(
                "operator_loco_lease_eur_h",
                "NUMERIC(10,3) NOT NULL",
                "All-inclusive locomotive rental rate (maintenance and "
                "insurance included), billed per hour the locomotive is in "
                "use. Two speed configurations exist as separate operator "
                "rows: up to 200 km/h (STD-REF) and 230 km/h (STD-NEW).",
                "€/h",
            ),
            _src("source_id", "all values in this row"),
        ),
        constraints=("UNIQUE (operator_id)",),
    ),
    Table(
        schema="input_params",
        name="operator_class_costs",
        description="Onboard service cost per operator and accommodation class.",
        columns=(
            Column(
                "operator_row_id",
                "INTEGER NOT NULL REFERENCES "
                "input_params.operators(operator_row_id) ON DELETE CASCADE",
            ),
            Column(
                "service_class_id",
                "VARCHAR(200) NOT NULL REFERENCES "
                "input_params.service_classes(service_class_id)",
            ),
            Column(
                "operator_class_svc_stockings_eur_place",
                "NUMERIC(8,4) NOT NULL",
                "Onboard service cost — bedding, breakfast, amenities — "
                "per sold place and trip, for this class.",
                "€/place",
            ),
            _src("source_id", "all values in this row"),
        ),
        constraints=("PRIMARY KEY (operator_row_id, service_class_id)",),
    ),
    Table(
        schema="input_params",
        name="coach_types",
        description="Individual railcar/coach types. Capacity is derived "
        "from coach_type_classes, not stored here. A catalog, not "
        "history: coach_type_id is a permanent natural key — a changed "
        "spec means a new coach_type_id, never editing a row in place.",
        columns=(
            Column("coach_type_row_id", "SERIAL PRIMARY KEY"),
            Column(
                "coach_type_id",
                "VARCHAR(50) NOT NULL",
                "Coach type name (e.g. WLABmz, Bcmz, type1).",
            ),
            Column(
                "coach_type_operator_id",
                "VARCHAR(50)",
                "Operator this coach type belongs to (soft reference to "
                "operators.operator_id). Empty for generic/shared types.",
            ),
            Column(
                "coach_type_weight_gross_t",
                "NUMERIC(8,3)",
                "Gross weight of one coach of this type.",
                "t",
            ),
            Column(
                "coach_type_length_m",
                "NUMERIC(6,2) NOT NULL",
                "Coach length over buffers — basis of the per-metre "
                "purchase price and of the composition's total length.",
                "m",
            ),
            Column(
                "coach_type_has_wifi",
                "BOOLEAN NOT NULL DEFAULT FALSE",
                "Coach offers WiFi. A composition offers an amenity if any "
                "of its coaches does.",
            ),
            Column(
                "coach_type_length_wo_service_m",
                "NUMERIC(6,2) NOT NULL",
                "Coach length excluding dining/shared service areas — the "
                "passenger-space basis of the class cost split.",
                "m",
            ),
            Column(
                "coach_type_weight_wo_service_t",
                "NUMERIC(8,3) NOT NULL",
                "Coach weight excluding service areas.",
                "t",
            ),
            Column(
                "coach_type_bikes",
                "INTEGER NOT NULL DEFAULT 0",
                "Number of bicycle spaces in this coach type.",
            ),
            Column(
                "coach_type_climatization",
                "BOOLEAN NOT NULL DEFAULT FALSE",
                "Whether this coach type has air conditioning.",
            ),
            Column(
                "coach_type_plugs",
                "BOOLEAN NOT NULL DEFAULT FALSE",
                "Whether this coach type has passenger power sockets.",
            ),
            Column(
                "coach_type_crew_factor",
                "NUMERIC(4,2) NOT NULL DEFAULT 0",
                "Cabin crew this coach needs, as a fraction of an "
                "attendant (0.5 = one attendant covers two coaches).",
            ),
            Column("coach_type_remarks", "TEXT", "Free-text remarks."),
            _src("source_id", "all values in this row"),
        ),
        constraints=("UNIQUE (coach_type_id)",),
    ),
    Table(
        schema="input_params",
        name="coach_type_classes",
        description="Places per accommodation class within a coach type, "
        "with the class section's share of the coach.",
        columns=(
            Column(
                "coach_type_row_id",
                "INTEGER NOT NULL REFERENCES "
                "input_params.coach_types(coach_type_row_id) ON DELETE CASCADE",
            ),
            Column(
                "service_class_id",
                "VARCHAR(200) NOT NULL REFERENCES "
                "input_params.service_classes(service_class_id)",
            ),
            Column(
                "coach_type_class_places",
                "INTEGER NOT NULL CHECK (coach_type_class_places > 0)",
                "Number of places of this class in the coach type.",
                "places",
            ),
            Column(
                "section_length_m",
                "NUMERIC(6,2)",
                "Length of this class's section within the coach — basis "
                "of the class cost split and derived per-class densities.",
                "m",
            ),
            Column(
                "section_weight_t",
                "NUMERIC(8,3)",
                "Weight of this class's section within the coach.",
                "t",
            ),
            Column(
                "section_crew_factor",
                "NUMERIC(5,2) NOT NULL DEFAULT 0",
                "Cabin crew this class section needs, as a fraction of an attendant.",
            ),
            _src("source_id", "all values in this row"),
        ),
        constraints=("PRIMARY KEY (coach_type_row_id, service_class_id)",),
    ),
    Table(
        schema="input_params",
        name="composition_types",
        description="Train composition blueprint: which coaches, at which "
        "speed, with which cost parameters. Capacity comes from the coach "
        "list (composition_type_coaches → coach_type_classes). "
        "Locomotives are rented, not purchased — see "
        "operators.operator_loco_lease_eur_h. A catalog, not history: "
        "composition_type_id is a permanent natural key — new settings "
        "mean a new composition_type_id, never editing a row in place.",
        columns=(
            Column("composition_type_row_id", "SERIAL PRIMARY KEY"),
            Column(
                "composition_type_id",
                "VARCHAR(50) NOT NULL",
                "Composition name (e.g. STD-3.1).",
            ),
            Column(
                "composition_type_description",
                "VARCHAR(200) NOT NULL",
                "Short human-readable description of the composition.",
            ),
            Column(
                "composition_type_operator_id",
                "VARCHAR(50) NOT NULL",
                "Operator running this composition (soft reference to "
                "operators.operator_id).",
            ),
            Column(
                "composition_type_hsr_allowed",
                "BOOLEAN NOT NULL",
                "Whether this train may use high-speed lines at all "
                "(combined with each country's own permission).",
            ),
            Column(
                "composition_type_max_speed_kmh",
                "NUMERIC(6,2) NOT NULL",
                "Maximum operational speed.",
                "km/h",
            ),
            Column(
                "composition_type_energy_factor_weight",
                "NUMERIC(10,6) NOT NULL",
                "Energy model: base factor per tonne-kilometre.",
                "kWh/(t·km)",
            ),
            Column(
                "composition_type_energy_factor_speed",
                "NUMERIC(10,6) NOT NULL",
                "Energy model: air resistance factor, applied to speed squared.",
                "kWh/(t·km·(km/h)²)",
            ),
            Column(
                "composition_type_energy_factor_terrain",
                "NUMERIC(10,6) NOT NULL",
                "Energy model: terrain factor, applied to the terrain score.",
                "kWh/(t·km) per terrain point",
            ),
            Column(
                "composition_type_min_boarding_time",
                "INTERVAL NOT NULL",
                "Minimum waiting time this train needs at stops where "
                "passengers board.",
                "interval (hh:mm:ss)",
            ),
            Column(
                "composition_type_min_alighting_time",
                "INTERVAL NOT NULL",
                "Minimum waiting time this train needs at stops where "
                "passengers get off.",
                "interval (hh:mm:ss)",
            ),
            Column(
                "composition_type_purchase_coach_eur",
                "NUMERIC(12,2) NOT NULL",
                "Average purchase price per coach, from the per-metre "
                "price model (new 145 / refurbished 53 k€ per metre of "
                "coach, double-deck ×1.12) applied to this composition's "
                "coach lengths. Derivation: calib/CALIBRATION.md.",
                "€/coach",
            ),
            Column(
                "composition_type_coach_avail_per",
                "NUMERIC(5,4) NOT NULL",
                "Share of calendar days a coach is available for service "
                "(the rest it is in the workshop).",
                "fraction",
            ),
            Column(
                "composition_type_coach_amort_years",
                "INTEGER NOT NULL",
                "Useful life over which a coach is written off.",
                "years",
            ),
            Column(
                "composition_type_cleaning_eur_day",
                "NUMERIC(10,3) NOT NULL",
                "Cleaning and preparation for the next night, per coach "
                "and operating day, at 2032 prices.",
                "€/coach/day",
            ),
            Column(
                "composition_type_coach_maint_eur_km",
                "NUMERIC(10,8) NOT NULL",
                "Coach maintenance for the whole train per kilometre "
                "(per-coach rate × number of coaches; new 1.00 / "
                "refurbished 1.30 €/coach-km, 2032 prices).",
                "€/train-km",
            ),
            Column(
                "composition_type_driver_factor",
                "NUMERIC(4,2) NOT NULL DEFAULT 1",
                "Number of drivers required per trip (e.g. 1 or 2).",
                "persons",
            ),
            Column(
                "composition_type_n_locos",
                "SMALLINT NOT NULL DEFAULT 1",
                "Number of locomotives. Scales the locomotive rental cost "
                "and (once calibrated) the energy weight basis.",
                "count",
            ),
            Column(
                "composition_type_zugchef_crew_factor",
                "NUMERIC(5,2) NOT NULL DEFAULT 1.19",
                "Train manager, counted in attendant-equivalents (1.19; "
                "2.38 for trains with 10 or more coaches). Total crew = "
                "sum of coach crew factors + this factor.",
                "attendant-equivalents",
            ),
            Column(
                "composition_type_length_cost_prop",
                "NUMERIC(4,3) NOT NULL DEFAULT 0.700",
                "Weighting X of the class cost split: X by length, (1−X) "
                "by weight, on passenger space; service areas are split "
                "per place. See calib/CALIBRATION.md.",
                "fraction",
            ),
            Column(
                "composition_type_food_and_beverages",
                "VARCHAR(120)",
                "Catering concept (e.g. 'dining car'). Coach amenities "
                "aggregate separately.",
            ),
            Column(
                "composition_type_material_strategy",
                "VARCHAR(15) NOT NULL CHECK "
                "(composition_type_material_strategy IN "
                "('new', 'refurbished'))",
                "Rolling stock family: 'new' (230 km/h-capable, 30-year "
                "write-off, 0.909 availability) or 'refurbished' (200 "
                "km/h cap, 12 years, 0.80). Selects the matching operator "
                "row (STD-NEW / STD-REF) and parameter family — see "
                "calib/CALIBRATION.md.",
            ),
            Column(
                "composition_type_indicative_cost_eur_train_km",
                "NUMERIC(8,2)",
                "Indicative operator cost per train-kilometre on the "
                "1,000 km reference route (14.5 h trip, 350 operating "
                "days, 2 trainsets) at 2032 prices, excluding "
                "infrastructure charges, energy, variable overhead and "
                "profit — a comparison figure between compositions, not a "
                "route evaluation. Derivation: calib/CALIBRATION.md.",
                "€/train-km",
            ),
            Column(
                "composition_type_indicative_cost_ct_place_km",
                "NUMERIC(6,2)",
                "The same cost basis divided by the number of places.",
                "ct/place-km",
            ),
            _src("source_id", "all values in this row"),
        ),
        constraints=("UNIQUE (composition_type_id)",),
    ),
    Table(
        schema="input_params",
        name="composition_type_coaches",
        description="Ordered coach slots per composition type.",
        columns=(
            Column(
                "composition_type_row_id",
                "INTEGER NOT NULL REFERENCES "
                "input_params.composition_types(composition_type_row_id) "
                "ON DELETE CASCADE",
            ),
            Column(
                "position",
                "SMALLINT NOT NULL CHECK (position >= 1)",
                "Position of the coach in the train (1 = first coach "
                "behind the locomotive).",
            ),
            Column(
                "coach_type_row_id",
                "INTEGER NOT NULL REFERENCES "
                "input_params.coach_types(coach_type_row_id)",
            ),
        ),
        constraints=("PRIMARY KEY (composition_type_row_id, position)",),
    ),
    Table(
        schema="input_params",
        name="track_infrastructure_defaults",
        description="EU-average fallback track parameters, applied "
        "wherever a country's own field is empty. Version bumps are "
        "full-table snapshots, resolved via "
        "scenario.scenarios.track_infrastructure_defaults_version — see "
        "db/README.md for the versioning contract.",
        columns=(
            Column("track_infra_default_id", "SERIAL PRIMARY KEY"),
            Column(
                "track_infra_default_key",
                "VARCHAR(50) NOT NULL",
                "Identifier of the default set (e.g. 'EU').",
            ),
            *_track_param_columns(nullable=False),
            _CHANGE_LOG,
            Column(
                "track_infra_default_version",
                "INTEGER NOT NULL DEFAULT 1",
                "Per-table full-snapshot version number. Resolved via "
                "scenario.scenarios.track_infrastructure_defaults_version "
                "— never inferred.",
            ),
        ),
        constraints=("UNIQUE (track_infra_default_key, track_infra_default_version)",),
    ),
    Table(
        schema="input_params",
        name="track_infrastructures",
        description="Country-level track parameters. Empty fields are "
        "resolved against track_infrastructure_defaults by the loader. "
        "Version bumps are full-table snapshots — every country's row is "
        "duplicated forward on any single-country edit — resolved via "
        "scenario.scenarios.track_infrastructures_version. See "
        "db/README.md for the versioning contract.",
        columns=(
            Column("track_infra_row_id", "SERIAL PRIMARY KEY"),
            Column(
                "country_code",
                "CHAR(2) NOT NULL REFERENCES input_params.countries(country_code)",
                "Two-letter country code (ISO 3166-1 alpha-2).",
            ),
            *_track_param_columns(nullable=True),
            _CHANGE_LOG,
            Column(
                "track_infra_version",
                "INTEGER NOT NULL DEFAULT 1",
                "Per-table full-snapshot version number. Resolved via "
                "scenario.scenarios.track_infrastructures_version — never "
                "inferred.",
            ),
        ),
        constraints=("UNIQUE (country_code, track_infra_version)",),
    ),
    Table(
        schema="input_params",
        name="stop_infrastructure_defaults",
        description="Fallback station charge per country (empty country = "
        "global default). Version bumps are full-table snapshots, "
        "resolved via "
        "scenario.scenarios.stop_infrastructure_defaults_version — see "
        "db/README.md for the versioning contract.",
        columns=(
            Column("stop_infra_default_id", "SERIAL PRIMARY KEY"),
            Column(
                "country_code",
                "CHAR(2) REFERENCES input_params.countries(country_code)",
                "Country this default applies to. Empty = global fallback.",
            ),
            Column(
                "stop_charge_eur",
                "NUMERIC(10,2) NOT NULL",
                "Fallback station fee per scheduled stop.",
                "€/stop",
            ),
            _src("stop_charge_src", "the station fee"),
            _CHANGE_LOG,
            Column(
                "stop_infra_default_version",
                "INTEGER NOT NULL DEFAULT 1",
                "Per-table full-snapshot version number. Resolved via "
                "scenario.scenarios.stop_infrastructure_defaults_version "
                "— never inferred.",
            ),
        ),
        constraints=("UNIQUE (country_code, stop_infra_default_version)",),
    ),
    Table(
        schema="input_params",
        name="stop_infrastructures",
        description="Catalog of possible night train stops. An empty "
        "stop_charge_eur is resolved against stop_infrastructure_defaults "
        "by the loader. Version bumps are full-table snapshots — every "
        "stop's row is duplicated forward on any single-stop edit — "
        "resolved via scenario.scenarios.stop_infrastructures_version. "
        "See db/README.md for the versioning contract.",
        columns=(
            Column("stop_infra_row_id", "SERIAL PRIMARY KEY"),
            Column(
                "stop_id",
                "VARCHAR(120) NOT NULL",
                "Unique stop identifier.",
            ),
            Column(
                "stop_name",
                "VARCHAR(120) NOT NULL",
                "Official station name.",
            ),
            Column(
                "country_code",
                "CHAR(2) NOT NULL REFERENCES input_params.countries(country_code)",
                "Two-letter country code (ISO 3166-1 alpha-2).",
            ),
            Column(
                "stop_timezone",
                "VARCHAR(50) NOT NULL",
                "IANA timezone identifier (e.g. Europe/Berlin).",
            ),
            Column(
                "stop_lat",
                "NUMERIC(9,6) NOT NULL",
                "Latitude in WGS-84 decimal degrees.",
                "°",
            ),
            Column(
                "stop_lon",
                "NUMERIC(9,6) NOT NULL",
                "Longitude in WGS-84 decimal degrees.",
                "°",
            ),
            _src("stop_loc_src", "the coordinates"),
            Column(
                "stop_charge_eur",
                "NUMERIC(10,2)",
                "Station fee per scheduled stop. Empty = the country or "
                "global default applies.",
                "€/stop",
            ),
            _src("stop_charge_src", "the station fee"),
            _CHANGE_LOG,
            Column(
                "stop_infra_version",
                "INTEGER NOT NULL DEFAULT 1",
                "Per-table full-snapshot version number. Resolved via "
                "scenario.scenarios.stop_infrastructures_version — never "
                "inferred.",
            ),
        ),
        constraints=("UNIQUE (stop_id, stop_infra_version)",),
    ),
)


# =============================================================================
# scenario — the container pinning parameter versions
# =============================================================================

SCENARIO_TABLES: tuple[Table, ...] = (
    Table(
        schema="scenario",
        name="scenarios",
        description="Container pinning one version of each versioned "
        "infrastructure table. Exactly one row has is_current_base = TRUE "
        "(the live default); exactly one row per scenario_key has "
        "is_current_scenario = TRUE (the head of that what-if lineage). "
        "All four *_version columns are per-table full-snapshot version "
        "numbers, resolved by exact match, and are NOT NULL — a scenario "
        "is always a complete, self-contained pin, never a partial diff. "
        "Compositions, coach types, and operators are catalogs, not "
        "scenario-versioned. Full versioning contract: db/README.md.",
        columns=(
            Column("scenario_id", "SERIAL PRIMARY KEY"),
            Column(
                "scenario_key",
                "VARCHAR(100) NOT NULL",
                "Stable identifier for one lineage of scenario edits, "
                'e.g. "base", "whatif-de-track-infra". Shared across '
                "every row belonging to that lineage; scenario_id changes "
                "on every edit, scenario_key does not.",
            ),
            Column(
                "scenario_name",
                "TEXT NOT NULL",
                'Short human-readable label, e.g. "2032 Base Line", '
                '"What-if: DE power tax -10%".',
            ),
            Column(
                "description",
                "TEXT",
                "Free-text explanation of what this scenario represents "
                "and why it exists.",
            ),
            Column(
                "change_log",
                "TEXT",
                "Free-text summary of what changed relative to the "
                "scenario this was derived from — the batch-level "
                "narrative; per-value rationale lives in each parameter "
                "table's own change_log.",
            ),
            Column(
                "editor",
                "VARCHAR(100)",
                "User who created this scenario.",
            ),
            Column("created_at", "TIMESTAMPTZ NOT NULL DEFAULT now()"),
            Column(
                "is_current_base",
                "BOOLEAN NOT NULL DEFAULT FALSE",
                "TRUE for the single live default scenario, used whenever "
                "an API call is not given an explicit scenario_id.",
            ),
            Column(
                "is_current_scenario",
                "BOOLEAN NOT NULL DEFAULT TRUE",
                "TRUE for the newest row within this scenario_key. "
                "Exactly one per key.",
            ),
            Column(
                "track_infrastructures_version",
                "INTEGER NOT NULL",
                "Pinned input_params.track_infrastructures version "
                "(full-table snapshot).",
            ),
            Column(
                "track_infrastructure_defaults_version",
                "INTEGER NOT NULL",
                "Pinned input_params.track_infrastructure_defaults "
                "version (full-table snapshot).",
            ),
            Column(
                "stop_infrastructures_version",
                "INTEGER NOT NULL",
                "Pinned input_params.stop_infrastructures version "
                "(full-table snapshot).",
            ),
            Column(
                "stop_infrastructure_defaults_version",
                "INTEGER NOT NULL",
                "Pinned input_params.stop_infrastructure_defaults version "
                "(full-table snapshot).",
            ),
        ),
        indexes=(
            "CREATE UNIQUE INDEX idx_scenarios_one_current_base\n"
            "    ON scenario.scenarios (is_current_base) WHERE is_current_base;",
            "CREATE UNIQUE INDEX idx_scenarios_one_current_per_key\n"
            "    ON scenario.scenarios (scenario_key) WHERE is_current_scenario;",
        ),
    ),
)


# =============================================================================
# DDL rendering
# =============================================================================


def _sql_str(text: str) -> str:
    """Escape a description for use inside a single-quoted SQL string."""
    return text.replace("'", "''")


def _comment(target: str, qualified: str, text: str) -> str:
    return f"COMMENT ON {target} {qualified} IS '{_sql_str(text)}';"


def _table_ddl(table: Table) -> str:
    qualified = f"{table.schema}.{table.name}"
    body_lines = [f"    {c.name} {c.sql_type}" for c in table.columns]
    body_lines += [f"    {c}" for c in table.constraints]
    lines = [
        f"CREATE TABLE {qualified} (",
        ",\n".join(body_lines),
        ");",
        _comment("TABLE", qualified, table.description),
    ]
    for c in table.columns:
        if not c.description:
            continue
        text = c.description + (f" Unit: {c.unit}" if c.unit else "")
        lines.append(_comment("COLUMN", f"{qualified}.{c.name}", text))
    lines.extend(table.indexes)
    return "\n".join(lines)


def build_ddl() -> str:
    """Render the input_params and scenario schemas as one DDL script —
    the exact replacement for the former create_input_params_schema.sql
    and create_scenario_schema.sql files, executed by seed.py.
    Idempotent: each schema starts with DROP SCHEMA ... CASCADE."""
    parts = [
        "DROP SCHEMA IF EXISTS input_params CASCADE;",
        "CREATE SCHEMA input_params;",
        "",
        "-- PostGIS is database-wide (not schema-scoped) — created here since",
        "-- input_params.countries.country_geom is its first consumer.",
        "CREATE EXTENSION IF NOT EXISTS postgis;",
        "",
    ]
    parts += [_table_ddl(t) + "\n" for t in INPUT_PARAMS_TABLES]
    parts += [
        "DROP SCHEMA IF EXISTS scenario CASCADE;",
        "CREATE SCHEMA scenario;",
        "",
    ]
    parts += [_table_ddl(t) + "\n" for t in SCENARIO_TABLES]
    return "\n".join(parts)
