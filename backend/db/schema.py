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
"Unit: X". Versioning contract for the five snapshot-versioned
infrastructure tables and the scenario container: db/README.md, section
"Schema overview".
"""

from __future__ import annotations

import re
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
    lines. description becomes COMMENT ON TABLE. unlogged marks a
    disposable cache table — no WAL, lost on crash, never a source of
    truth."""

    schema: str
    name: str
    description: str
    columns: tuple[Column, ...]
    constraints: tuple[str, ...] = ()
    indexes: tuple[str, ...] = ()
    unlogged: bool = False


# Member-organisation languages of the localized stop-catalog columns —
# one entry per language, mirrored by the stop classification pipeline
# (models/infrastructure/stops, step 7 LANGS) and by the API serializer.
# Extending the catalog to another language starts here and in the pipeline.
STOP_NAME_LANGS = ("en", "de", "fr", "nl", "it", "es", "pl")


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
            "Indicative track access charge for the reference night train — "
            "a single headline number for display and comparison. The cost "
            "model does NOT read it: it prices track access from the "
            "calibrated component columns further down.",
            "€/train-km",
        ),
        _src("track_tac_src", "the track access charge"),
        Column(
            "track_parking_eur_day",
            f"NUMERIC(8,2){nn}",
            "Indicative cost of one stabling occupation for the reference "
            "train — a single headline number for display and comparison. The "
            "cost model does NOT read it: it prices stabling from the basis "
            "and rate columns further down, against the actual layover and "
            "train length.",
            "€/occupation (EUR at 2032 prices)",
        ),
        _src("track_parking_src", "the parking cost"),
        Column(
            "track_shunting_eur_event",
            f"NUMERIC(8,2){nn}",
            "All-in cost of one shunting movement: what the infrastructure "
            "manager charges plus what it does not supply. Roughly nine "
            "tenths of the figure is the market cost of a shunting locomotive "
            "and crew where the IM sells only facility access — see the "
            "calibration document.",
            "€/event (EUR at 2032 prices)",
        ),
        _src("track_shunting_src", "the shunting cost"),
        Column(
            "track_energy_price_eur_kwh",
            f"NUMERIC(8,6){nn}",
            "Traction electricity price: the day rate, and the rate around "
            "the clock for the twenty-five countries whose tariff is not "
            "banded. Where a night band exists the cost model prices the "
            "in-band share at track_energy_price_night_eur_kwh instead.",
            "€/kWh (EUR at 2032 prices)",
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


def _track_facility_columns() -> tuple[Column, ...]:
    """The calibrated service-facility terms: how a country prices one
    stabling occupation, and the power the train draws while it stands.

    EUR at the 2032 evaluation year (see
    models/infrastructure/facility/calib/FACILITY_CALIBRATION.md). Shunting
    needs no column here — it stays the single per-event figure it always was
    in track_shunting_eur_event above, now carrying the calibrated all-in
    value rather than a placeholder.

    track_parking_basis is the group's trigger: NULL means the whole group
    resolves from the defaults row (see DBDataLoader._row_to_track), because
    unlike a night band or a catenary charge, every country that stables a
    train charges *something* — or has been positively documented not to, in
    which case the basis reads 'none'. Only the rate column matching the basis
    is populated; the other two are NULL because that country does not price
    in that unit.
    """
    return (
        Column(
            "track_parking_basis",
            "VARCHAR(16) CHECK (track_parking_basis IN "
            "('per_metre_day', 'per_hour', 'per_event', 'none'))",
            "How the country prices one stabling occupation: per metre of "
            "train length per started 24 hours, per started hour "
            "(length-independent, as Germany's Anlagenpreissystem is by "
            "design), a flat charge per occupation with no time term, or "
            "'none' where the network statement documents that no siding "
            "charge is levied.",
        ),
        Column(
            "track_parking_eur_metre_day",
            "NUMERIC(8,4)",
            "Stabling rate where the country prices by length and time. Empty "
            "means it prices in one of the other units.",
            "€/metre per started 24 h (EUR at 2032 prices)",
        ),
        Column(
            "track_parking_eur_hour",
            "NUMERIC(8,4)",
            "Stabling rate where the country prices per started hour, "
            "independent of train length.",
            "€/started hour (EUR at 2032 prices)",
        ),
        Column(
            "track_parking_eur_event",
            "NUMERIC(10,4)",
            "Stabling charge where the country prices one occupation flat, "
            "with no time or length term.",
            "€/occupation (EUR at 2032 prices)",
        ),
        Column(
            "track_parking_free_hours",
            "NUMERIC(6,2)",
            "Free stabling allowance before the charge starts. Material where "
            "it exceeds a layover: Norway's 48 h and Croatia's 24 h zero a "
            "twelve-hour turnaround entirely.",
            "hours",
        ),
        Column(
            "track_parking_hotel_power_eur_hour",
            "NUMERIC(8,4)",
            "Power the train draws while stabled, charged on ACTUAL stabled "
            "hours rather than on the billable hours after a free track "
            "allowance — the electricity flows whether or not the siding is "
            "free. One European proxy rate, from DB InfraGO's unmetered "
            "Elektrant flat charge.",
            "€/stabled hour (EUR at 2032 prices)",
        ),
    )


def _track_energy_columns() -> tuple[Column, ...]:
    """The calibrated traction-energy price terms beyond the day rate,
    shared verbatim by track_infrastructures and
    track_infrastructure_defaults.

    Every monetary value is EUR at the 2032 evaluation year — the
    calibration notebook converts currency and price basis exactly once,
    before the seed step (see
    models/infrastructure/energy_pricing/calib/ENERGY_PRICING_CALIBRATION.md).

    Nullable in BOTH tables, and — unlike the TAC component group — never
    substituted from the defaults row: an empty night price means the
    country charges one rate around the clock, and an empty catenary term
    means it levies no separate supply-equipment charge. Both are tariff
    facts, and only three of twenty-eight countries band their tariff at
    all, so defaulting either would invent tariff structure. The day rate
    (track_energy_price_eur_kwh) stays with the legacy parameters above
    because it does resolve field by field: every country pays *something*
    for electricity.
    """
    return (
        Column(
            "track_energy_price_night_eur_kwh",
            "NUMERIC(8,6)",
            "Traction electricity price inside the country's night tariff "
            "band, charged pro rata on the share of a run that falls in "
            "it. Empty means one rate around the clock (AT, CH and HR are "
            "the only banded tariffs). Never resolved from the defaults "
            "row, which leaves it empty: a banded tariff is a national "
            "particularity, not a gap to fill.",
            "€/kWh (EUR at 2032 prices)",
        ),
        Column(
            "track_energy_night_band_start",
            "TIME",
            "Start of the national electricity night tariff band, local "
            "clock. Bands may run across midnight (22:00–06:00). This is "
            "the ENERGY band and is independent of the track access night "
            "band (track_tac_night_band_start): Germany bands the track "
            "charge 23:00–06:00 and does not band electricity at all, "
            "Switzerland the reverse.",
            "time of day",
        ),
        Column(
            "track_energy_night_band_end",
            "TIME",
            "End of the national electricity night tariff band, local clock.",
            "time of day",
        ),
        Column(
            "track_energy_catenary_eur_train_km",
            "NUMERIC(10,6)",
            "Charge for using the catenary and traction power-supply "
            "installations, where the infrastructure manager levies it per "
            "train-kilometre (FR, HR, HU, IT, LT, LU, LV, PL, RO). Empty "
            "means not levied in this unit — either not levied at all, or "
            "charged on weight in the column below, or already inside the "
            "energy price. Never resolved from the defaults row: roughly "
            "half of Europe's infrastructure managers levy this charge, so "
            "an uncalibrated country is priced without one rather than "
            "given an invented median.",
            "€/train-km (EUR at 2032 prices)",
        ),
        Column(
            "track_energy_catenary_eur_gross_tonne_km",
            "NUMERIC(12,8)",
            "The same supply-equipment charge where the infrastructure "
            "manager levies it on the weight moved instead (FI, GR, SK), "
            "charged on the whole consist — coaches plus locomotives.",
            "€/gross-tonne-km (EUR at 2032 prices)",
        ),
    )


def _track_tac_columns(nullable: bool) -> tuple[Column, ...]:
    """The calibrated track-access-charge component model, shared verbatim
    by track_infrastructures and track_infrastructure_defaults.

    Every monetary value is EUR at the 2032 evaluation year — the
    calibration notebook converts currency and price basis exactly once,
    before the seed step, so nothing downstream ever sees a native
    currency or a document year (see
    models/infrastructure/tac/calib/TAC_CALIBRATION.md).

    The rate terms stay nullable in BOTH tables, unlike the ten legacy
    parameters above: an empty component is the documented tariff fact
    "this country does not levy this term", not a gap to fill. Only when
    a country has no rate term at all does the loader substitute the
    defaults row as a group — see DBDataLoader._row_to_track().
    """
    nn = "" if nullable else " NOT NULL"
    return (
        Column(
            "track_tac_b_day",
            "NUMERIC(10,6)",
            "Base day rate of the minimum access package. Empty means the "
            "country levies no distance-based day rate.",
            "€/train-km (EUR at 2032 prices)",
        ),
        Column(
            "track_tac_b_night",
            "NUMERIC(10,6)",
            "Night rate of the minimum access package, charged on the share "
            "of a run falling inside the country's night band. Empty means "
            "the country has no separate night rate.",
            "€/train-km (EUR at 2032 prices)",
        ),
        Column(
            "track_tac_gamma",
            "NUMERIC(12,8)",
            "Weight-dependent term, charged on the whole consist — coaches "
            "plus locomotives.",
            "€/gross-tonne-km (EUR at 2032 prices)",
        ),
        Column(
            "track_tac_seat_km",
            "NUMERIC(12,8)",
            "Capacity-dependent term, charged per place the train offers "
            "(Spanish corridor surcharge).",
            "€/seat-km (EUR at 2032 prices)",
        ),
        Column(
            "track_tac_per_stop",
            "NUMERIC(10,6)",
            "Per-stop element of the path price: stopping and restarting "
            "consumes path capacity (Swiss Haltezuschlag). NOT a station "
            "usage fee — those are stop_infrastructures.stop_charge_eur. "
            "Charged at each stop's own country rate.",
            "€/stop (EUR at 2032 prices)",
        ),
        Column(
            "track_tac_revenue_share",
            "NUMERIC(6,4)",
            "Share of the traffic revenue earned in this country that the "
            "infrastructure manager takes on top of the distance charges "
            "(Swiss Deckungsbeitrag).",
            "fraction",
        ),
        Column(
            "track_tac_fixed_per_train_km",
            "NUMERIC(10,6)",
            "Flat administrative add-on charged per kilometre alongside the "
            "base rate (Luxembourgish path administration).",
            "€/train-km (EUR at 2032 prices)",
        ),
        Column(
            "track_tac_peak_multiplier",
            "NUMERIC(4,2)",
            "Factor the day rate is multiplied by on the share of a run "
            "falling inside the country's peak bands (Swiss NZV: 2).",
            "factor",
        ),
        Column(
            "track_tac_congestion_surcharge_eur_km",
            "NUMERIC(10,6)",
            "Flat surcharge on congested sections, charged on the share of "
            "a run falling inside the peak bands (Austrian überlastete "
            "Schienenwege). Kept apart from the multiplier above so a "
            "congestion charge can be shown as one.",
            "€/train-km (EUR at 2032 prices)",
        ),
        Column(
            "track_tac_night_mode",
            f"VARCHAR(10){nn} DEFAULT 'none' CHECK (track_tac_night_mode IN "
            "('none', 'time_band'))",
            "How the country prices night traffic: 'none' (one rate around "
            "the clock) or 'time_band' (the night rate applies pro rata to "
            "the time a run spends inside the band below).",
        ),
        Column(
            "track_tac_night_band_start",
            "TIME",
            "Start of the national night tariff band, local clock. Bands "
            "may run across midnight (23:00–06:00).",
            "time of day",
        ),
        Column(
            "track_tac_night_band_end",
            "TIME",
            "End of the national night tariff band, local clock.",
            "time of day",
        ),
        Column(
            "track_tac_night_full_if_accommodation",
            f"BOOLEAN{nn} DEFAULT FALSE",
            "German SPFV Nacht rule: when true, a train carrying night "
            "accommodation (couchette, sleeper or capsule) is priced at the "
            "night rate over its ENTIRE run in this country, not just the "
            "part inside the band.",
        ),
        Column(
            "track_tac_peak_band1_start",
            "TIME",
            "Start of the first daily peak band (morning commuter peak), local clock.",
            "time of day",
        ),
        Column(
            "track_tac_peak_band1_end",
            "TIME",
            "End of the first daily peak band.",
            "time of day",
        ),
        Column(
            "track_tac_peak_band2_start",
            "TIME",
            "Start of the second daily peak band (evening commuter peak), local clock.",
            "time of day",
        ),
        Column(
            "track_tac_peak_band2_end",
            "TIME",
            "End of the second daily peak band.",
            "time of day",
        ),
        Column(
            "track_tac_peak_weekdays_only",
            f"BOOLEAN{nn} DEFAULT FALSE",
            "Whether the peak bands apply Monday to Friday only. The model "
            "knows a departure's clock time but not its weekday, so such a "
            "band is charged at its expected value — five sevenths of the "
            "overlap.",
        ),
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
                "Country border polygon (SRID 4326) covering the country's "
                "land area AND its maritime zones (territorial sea, internal "
                "and archipelagic waters, EEZ) — seeded from the Marine "
                "Regions union of the ESRI country shapefile and the "
                "Exclusive Economic Zones, v4. The maritime coverage is what "
                "attributes belt, strait and tunnel crossings to a country "
                "instead of the UNK sentinel: this is a routing-attribution "
                "geometry, not a cartographic land border. NULL for "
                "countries with no rail network, which no route can transit.",
            ),
        ),
        indexes=(
            "CREATE INDEX idx_countries_geom ON input_params.countries "
            "USING GIST (country_geom);",
        ),
    ),
    Table(
        schema="input_params",
        name="country_relations",
        description="Which pairs of countries are close enough to each "
        "other for one night train to plausibly connect them — the "
        "candidate set the proposal statistics rank top and flop "
        "relations over (GET /api/proposals/stats). One row per "
        "unordered country pair, measured between each country's "
        "reference station (the catalog stop closest to that country's "
        "stop centroid) and routed on real track, so sea crossings that "
        "force a long land detour drop out on their own. Derived, "
        "rebuildable data, NOT hand-maintained: "
        "scripts/build_country_relations.py rebuilds it from the pinned "
        "stop catalog, and countries with no stops in the catalog yet "
        "simply have no rows.",
        columns=(
            Column(
                "country_a",
                "CHAR(2) NOT NULL REFERENCES input_params.countries(country_code)",
                "First country of the pair — always the alphabetically "
                "smaller code, so each pair appears exactly once.",
            ),
            Column(
                "country_b",
                "CHAR(2) NOT NULL REFERENCES input_params.countries(country_code)",
                "Second country of the pair — always the alphabetically larger code.",
            ),
            Column(
                "ref_stop_a",
                "VARCHAR(120) NOT NULL",
                "Reference station used for country_a: the catalog stop "
                "closest to that country's stop centroid.",
            ),
            Column(
                "ref_stop_b",
                "VARCHAR(120) NOT NULL",
                "Reference station used for country_b.",
            ),
            Column(
                "great_circle_km",
                "NUMERIC(8,1) NOT NULL",
                "Straight-line distance between the two reference "
                "stations. Only used to decide whether routing the pair "
                "is worth attempting.",
                "km",
            ),
            Column(
                "rail_km",
                "NUMERIC(8,1)",
                "Distance on real track between the two reference "
                "stations. Empty when no rail path could be found.",
                "km",
            ),
            Column(
                "rail_time_h",
                "NUMERIC(6,2)",
                "Travel time on that rail path, for a future "
                "travel-time-based threshold. Empty when no rail path "
                "could be found.",
                "h",
            ),
            Column(
                "routing_status",
                "VARCHAR(20) NOT NULL",
                "Why this pair does or does not carry a rail distance: "
                "routed, prefiltered (too far apart to be worth "
                "routing), no_connection (no rail path exists), "
                "gauge_mismatch (the two reference stations share no "
                "track gauge, so no through service is possible), or "
                "snap_failed (a reference station could not be placed "
                "on the network).",
            ),
            Column(
                "stop_infra_version",
                "INTEGER NOT NULL",
                "Stop catalog snapshot the reference stations were "
                "picked from. Resolved via "
                "scenario.scenarios.stop_infrastructures_version — never "
                "inferred.",
            ),
            Column(
                "built_at",
                "TIMESTAMPTZ NOT NULL DEFAULT now()",
                "When this row was last rebuilt.",
            ),
        ),
        constraints=(
            "PRIMARY KEY (country_a, country_b, stop_infra_version)",
            "CHECK (country_a < country_b)",
        ),
        indexes=(
            "CREATE INDEX idx_country_relations_rail_km ON "
            "input_params.country_relations (stop_infra_version, rail_km);",
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
            Column(
                "service_class_is_night_accommodation",
                "BOOLEAN NOT NULL DEFAULT FALSE",
                "Whether places of this class make the train count as "
                "carrying night accommodation for tariff purposes. Germany "
                "prices such a train at its night rate over the whole "
                "German run (see track_tac_night_full_if_accommodation). "
                "True for every class a passenger can lie down in; a "
                "dining car alone does not make a night train.",
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
                "Driver pay per PRODUCTIVE hour, i.e. the raw wage rate "
                "before roster inefficiency. Evaluation divides it by the "
                "Dienstplanwirkungsgrad it computes per trip from the four "
                "roster columns below.",
                "€/h",
            ),
            Column(
                "operator_crew_costs_eur_h",
                "NUMERIC(8,2) NOT NULL",
                "Cabin crew pay per PRODUCTIVE hour, per attendant, before "
                "roster inefficiency (same treatment as the driver rate). "
                "The train manager is counted with a factor on the "
                "composition.",
                "€/h",
            ),
            Column(
                "operator_driver_max_duty_h",
                "NUMERIC(4,2) NOT NULL",
                "Longest driving time one driver may work between daily "
                "rest periods. Directive 2005/47/EC sets 8 h on a night "
                "shift (9 h by day); national agreements may be stricter. "
                "A trip whose driving time exceeds it needs a relief "
                "driver, which lowers the roster efficiency.",
                "h",
            ),
            Column(
                "operator_crew_max_duty_h",
                "NUMERIC(4,2) NOT NULL",
                "Longest working time one onboard attendant may work "
                "between daily rest periods, per the applicable collective "
                "agreement. Same relief mechanism as the driver column.",
                "h",
            ),
            Column(
                "operator_driver_roster_eff_ref",
                "NUMERIC(4,3) NOT NULL",
                "Dienstplanwirkungsgrad for a driver duty that needs no "
                "relief: the share of paid hours that is productive once "
                "sign-on/off, reserve cover and leave are absorbed.",
                "fraction",
            ),
            Column(
                "operator_crew_roster_eff_ref",
                "NUMERIC(4,3) NOT NULL",
                "Dienstplanwirkungsgrad for an onboard duty that needs no "
                "relief. Higher than the driver value: onboard links "
                "position less and rest away from base more predictably.",
                "fraction",
            ),
            Column(
                "operator_relief_allowance_h",
                "NUMERIC(4,2) NOT NULL",
                "Unproductive hours added per relief event — positioning "
                "to and from the relief point, the extra sign-on/off, and "
                "away-base rest handling. Applied once per additional duty "
                "beyond the first, for both roles.",
                "h",
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
        "Which locomotives it hauls comes from composition_type_locos; "
        "they are rented, not purchased, and the rate is per operator and "
        "machine (operator_loco_costs). A catalog, not history: "
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
        name="loco_types",
        description="Locomotive types — the physical machine, independent "
        "of who runs it. Weight and speed live here; the rental rate does "
        "not, because it is a commercial term that varies by operator "
        "(operator_loco_costs), exactly as onboard service cost varies by "
        "operator over service_classes. A catalog, not history: "
        "loco_type_id is a permanent natural key — a changed spec means a "
        "new loco_type_id, never editing a row in place.",
        columns=(
            Column("loco_type_row_id", "SERIAL PRIMARY KEY"),
            Column(
                "loco_type_id",
                "VARCHAR(50) NOT NULL UNIQUE",
                "Stable natural key, e.g. VECTRON-MS-230.",
            ),
            Column(
                "loco_type_description",
                "TEXT NOT NULL",
                "Machine and configuration in plain words, including the "
                "national class designation where the calibration pins "
                "one and an explicit note where it does not.",
            ),
            Column(
                "loco_type_traction",
                "VARCHAR(50) NOT NULL",
                "Traction system, e.g. 'electric multi-system'. Not yet "
                "read by any model — recorded so a future electrification "
                "or traction-change model has it.",
            ),
            Column(
                "loco_type_weight_t",
                "NUMERIC(8,3) NOT NULL",
                "Mass of one locomotive. Completes the gross weight the "
                "weight-dependent track access charge and the traction "
                "dynamics both work on — coach weight alone is not what "
                "gets hauled or weighed.",
                "t",
            ),
            Column(
                "loco_type_max_speed_kmh",
                "SMALLINT NOT NULL",
                "Design maximum speed. The composition's own max speed "
                "still governs the timetable; this records what the "
                "machine could do.",
                "km/h",
            ),
            _src("source_id", "all values in this row"),
            _CHANGE_LOG,
        ),
    ),
    Table(
        schema="input_params",
        name="operator_loco_costs",
        description="Locomotive rental rate per operator and machine — the "
        "locomotive counterpart of operator_class_costs. A pairing with no "
        "row is not priced, and the loader refuses to resolve a "
        "composition that needs one rather than substituting a fallback: a "
        "missing pairing is a wiring error, and a silent default would "
        "hide exactly the mistake this table exists to catch.",
        columns=(
            Column(
                "operator_row_id",
                "INTEGER NOT NULL REFERENCES "
                "input_params.operators(operator_row_id) ON DELETE CASCADE",
            ),
            Column(
                "loco_type_row_id",
                "INTEGER NOT NULL REFERENCES input_params.loco_types(loco_type_row_id)",
            ),
            Column(
                "operator_loco_lease_eur_h",
                "NUMERIC(10,3) NOT NULL",
                "All-inclusive rental rate (maintenance and insurance "
                "included), billed per hour the locomotive is in use.",
                "€/h",
            ),
            _src("source_id", "all values in this row"),
        ),
        constraints=("PRIMARY KEY (operator_row_id, loco_type_row_id)",),
    ),
    Table(
        schema="input_params",
        name="composition_type_locos",
        description="Ordered locomotive slots per composition type — the "
        "locomotive counterpart of composition_type_coaches. The number of "
        "locomotives is the number of rows here, never a stored column, so "
        "the two cannot disagree. position expresses machines hauling "
        "TOGETHER (double heading); a traction change part-way along a "
        "route is route-dependent and cannot be expressed on a composition "
        "type at all — that belongs on the trip when it is modelled.",
        columns=(
            Column(
                "composition_type_row_id",
                "INTEGER NOT NULL REFERENCES "
                "input_params.composition_types(composition_type_row_id) "
                "ON DELETE CASCADE",
            ),
            Column(
                "position",
                "SMALLINT NOT NULL",
                "1-based position in the consist.",
            ),
            Column(
                "loco_type_row_id",
                "INTEGER NOT NULL REFERENCES input_params.loco_types(loco_type_row_id)",
            ),
        ),
        constraints=("PRIMARY KEY (composition_type_row_id, position)",),
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
            *_track_tac_columns(nullable=False),
            *_track_energy_columns(),
            *_track_facility_columns(),
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
            *_track_tac_columns(nullable=True),
            *_track_energy_columns(),
            *_track_facility_columns(),
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
        name="passage_charges",
        description="Crossings that are charged per traverse instead of "
        "per kilometre — the Storebælt and Øresund fixed links and the "
        "Channel Tunnel. A crossing is its own entity rather than a "
        "country attribute because the charging party is the crossing's "
        "operator: Øresund is two rows over one polygon, each "
        "infrastructure manager billing its half. Which trip segment "
        "crosses which passage is decided at routing time by polygon "
        "intersection, so a crossing split by an intermediate stop is "
        "still paid for once. Version bumps are full-table snapshots, "
        "resolved via scenario.scenarios.passage_charges_version — see "
        "db/README.md for the versioning contract.",
        columns=(
            Column("passage_row_id", "SERIAL PRIMARY KEY"),
            Column(
                "passage_id",
                "VARCHAR(50) NOT NULL",
                "Stable crossing identifier (STOREBAELT, OERESUND_DK, "
                "OERESUND_SE, CHANNEL_TUNNEL).",
            ),
            Column(
                "passage_name",
                "VARCHAR(120) NOT NULL",
                "Full crossing name.",
            ),
            Column(
                "passage_fixed_eur",
                "NUMERIC(10,2) NOT NULL DEFAULT 0",
                "Charge per train crossing, one way.",
                "€/traverse (EUR at 2032 prices)",
            ),
            Column(
                "passage_per_passenger_eur",
                "NUMERIC(8,2) NOT NULL DEFAULT 0",
                "Charge per carried passenger, one way (Channel Tunnel). "
                "Evaluated against the passengers actually aboard on the "
                "crossing segment, so this term follows demand.",
                "€/passenger (EUR at 2032 prices)",
            ),
            _src("passage_src", "the crossing charges"),
            Column(
                "passage_geom",
                "geometry(Polygon, 4326) NOT NULL",
                "Crossing polygon (SRID 4326). A routed trip leg "
                "intersecting it owns the crossing. Static reference "
                "geometry — a tunnel does not move between scenarios; what "
                "the version pins are the charges.",
            ),
            _CHANGE_LOG,
            Column(
                "passage_version",
                "INTEGER NOT NULL DEFAULT 1",
                "Per-table full-snapshot version number. Resolved via "
                "scenario.scenarios.passage_charges_version — never "
                "inferred.",
            ),
        ),
        constraints=("UNIQUE (passage_id, passage_version)",),
        indexes=(
            "CREATE INDEX idx_passage_charges_geom ON "
            "input_params.passage_charges USING GIST (passage_geom);",
        ),
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
            Column(
                "stop_charge_vat_rate_per",
                "NUMERIC(5,2)",
                "VAT rate applying to the station charge, as a percentage "
                "(19.00 = 19%). NULL where no charge is calibrated.",
                "%",
            ),
            Column(
                "stop_charge_incl_vat_eur",
                "NUMERIC(10,2)",
                "The station charge including VAT. The model prices from the "
                "net stop_charge_eur; this is carried so both figures can be "
                "compared against whichever one the tariff document printed.",
                "EUR",
            ),
            Column(
                "stop_charge_basis",
                "VARCHAR(30)",
                "What the charge is per — 'per_call' unless a country's "
                "tariff genuinely differs.",
            ),
            Column(
                "stop_charge_price_basis_year",
                "SMALLINT",
                "The year the published figure applies to, before any escalation.",
            ),
            Column(
                "stop_charge_class",
                "VARCHAR(60)",
                "The country's own category for the station ('Preisklasse 2'), "
                "which is why two stations in one country differ.",
            ),
            Column(
                "stop_charge_source",
                "VARCHAR(40)",
                "source_id of the tariff document the charge was read from, "
                "in the charge pipeline's own register "
                "(models/infrastructure/stops/charges/01_source_extraction).",
            ),
            Column(
                "stop_provenance",
                "VARCHAR(60) NOT NULL",
                "Why the stop is in the catalog, as a human-readable "
                "category (step 10 PROVENANCE_LABELS: 'existing night train "
                "stop', 'urban area currently without night train service', "
                "...). The detailed per-stop reasons stay in the pipeline's "
                "step 6 notebook.",
            ),
            Column(
                "name_latin",
                "VARCHAR(120) NOT NULL",
                "Latin-script form of the station name (transliterated where "
                "the original is Cyrillic/Greek, otherwise the name itself).",
            ),
            Column(
                "name_ascii",
                "VARCHAR(120) NOT NULL",
                "ASCII fold of name_latin — the diacritic-free search form.",
            ),
            Column(
                "uic_ref",
                "VARCHAR(120)",
                "UIC station code from OSM, where tagged — the tag verbatim, "
                "so a station holding more than one code carries them all, "
                "semicolon-separated (Paris CDG 2 TGV: 8727149;8700147). "
                "Intended join key for station-charge tariff documents, not "
                "normalised yet: split on the semicolon before matching, and "
                "note that a few stops carry a national number rather than "
                "the country-prefixed UIC code.",
            ),
            *(
                Column(
                    f"country_{lang}",
                    "VARCHAR(60) NOT NULL",
                    f"Country name in '{lang}' (ISO 3166 translation "
                    "catalogs via the pipeline).",
                )
                for lang in STOP_NAME_LANGS
            ),
            Column(
                "city",
                "VARCHAR(120)",
                "Municipality the stop belongs to (Berlin Gesundbrunnen -> "
                "Berlin), resolved geographically against OSM place nodes. "
                "Empty for rural halts beyond any city/town radius.",
            ),
            Column(
                "city_osm_id",
                "BIGINT",
                "OSM node id of the resolved place — the stable key behind "
                "the localized city names.",
            ),
            *(
                Column(
                    f"city_{lang}",
                    "VARCHAR(120)",
                    f"City name in '{lang}' from the place node's own "
                    "name:* tags (exonyms as curated in OSM — an Italian "
                    "search for 'Monaco' reaches München's stops here).",
                )
                for lang in STOP_NAME_LANGS
            ),
            Column(
                "gauges_mm",
                "INTEGER[]",
                "Night-train-capable track gauges at the stop (railway=rail, "
                ">= 1435 mm; trams/Stadtbahn/narrow gauge are excluded by "
                "the pipeline). Several values at break-of-gauge stations "
                "(Kaunas 1435+1520). NULL = no usable tracks found nearby.",
                "mm",
            ),
            Column(
                "gauge_evidence",
                "VARCHAR(20) CHECK (gauge_evidence IN ('tagged', "
                "'untagged_tracks', 'narrow_gauge_only', 'no_tracks_nearby', "
                "'override'))",
                "How the gauge set was established from OSM: tagged tracks, "
                "rail present but untagged, only sub-1435 rail nearby "
                "(review flag), no rail within the search radius, or a "
                "hand-verified override (step 8's GAUGE_OVERRIDES — the "
                "station node is right but OSM carries no gauge-tagged way "
                "within the radius).",
            ),
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
        "All five *_version columns are per-table full-snapshot version "
        "numbers, resolved by exact match, and are NOT NULL — a scenario "
        "is always a complete, self-contained pin, never a partial diff. "
        "routing_graph_key pins the routing graph the same way (the one "
        "piece of infrastructure living outside the database). "
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
            Column(
                "passage_charges_version",
                "INTEGER NOT NULL",
                "Pinned input_params.passage_charges version (full-table snapshot).",
            ),
            Column(
                "routing_graph_key",
                "VARCHAR(50) NOT NULL",
                "Routing graph this scenario routes on — the physical rail "
                "network (OSM state) behind every distance and travel time, "
                'e.g. "infra_2026" or "infra_2032". Pinned like the '
                "*_version columns but not itself a snapshot version: the "
                "graph lives outside the database, in an OpenRailRouting "
                "instance. Naming contract with the deployment: key <k> is "
                "served by the instance at env OPENRAILROUTING_URL_<K>, the "
                "key uppercased — every graph alike, none implicit — see "
                "models/route/routing/rail_router.py. The TAC and "
                "passage changes an upgraded network implies are NOT carried "
                "here; they ride this same row's track_infrastructures_version "
                "and passage_charges_version pins.",
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
# route_cache — per-graph stop-pair routing segment cache
# =============================================================================
# Mirrored verbatim by db/dev/sql/migrations/2026-08-31_route_segment_cache.sql
# (servers only ever move through migrations). A cache like the §2.3
# compute cache, not versioned data: keyed per routing graph, purged per
# graph when that graph's GraphHopper import changes, refilled by
# scripts/precompute_route_segments.py and by every live-routed miss.

ROUTE_CACHE_TABLES: tuple[Table, ...] = (
    Table(
        schema="route_cache",
        name="graph_state",
        description="GraphHopper import_date each graph's cached segments "
        "were routed against. RouteSegmentRepository.sync_graph_import() "
        "compares it with the live /info at API startup and purges that "
        "graph's rows on a change — a re-import empties exactly the graph "
        "it touched.",
        columns=(
            Column("routing_graph_key", "VARCHAR(50) PRIMARY KEY"),
            Column("import_date", "TEXT NOT NULL"),
            Column("synced_at", "TIMESTAMPTZ NOT NULL DEFAULT now()"),
        ),
    ),
    Table(
        schema="route_cache",
        name="route_segments",
        description="Raw routed physics for one stop pair on one routing "
        "graph, canonical lo->hi orientation (stop ids sorted; direction is "
        "symmetric, one row serves both). Scenario-independent by design: "
        "buffer quotas, traction dynamics and energy are applied downstream, "
        "so parameter recalibrations invalidate zero rows. Grows from "
        "precompute loads (source=precompute) and from every live-routed "
        "miss (source=runtime). Row contract: "
        "models/route/routing/segment_cache.py.",
        unlogged=True,
        columns=(
            Column(
                "routing_graph_key",
                "VARCHAR(50) NOT NULL",
                "The graph these segments were routed on — each graph has its "
                "own snapped points and HSR resolution, nothing is shared.",
            ),
            Column("stop_lo", "VARCHAR(120) NOT NULL", "Smaller stop_id of the pair."),
            Column("stop_hi", "VARCHAR(120) NOT NULL", "Larger stop_id of the pair."),
            Column(
                "variant_key",
                "VARCHAR(80) NOT NULL",
                "route_variant_key(): gauge profile + hash of the resolved "
                "custom model — everything that shapes the geometry on a "
                "graph. Unknown key -> miss -> live route + store.",
            ),
            Column(
                "distance_m", "INTEGER NOT NULL", "Rounded total, for screening.", "m"
            ),
            Column(
                "country_distance_m",
                "JSONB NOT NULL",
                "Unrounded per-country distance; shares derive from this.",
                "m",
            ),
            Column(
                "country_driving_ms",
                "JSONB NOT NULL",
                "Unrounded per-country raw driving time — what buffer quotas "
                "and driving_time_min are recomputed from per request.",
                "ms",
            ),
            Column(
                "countries", "JSONB NOT NULL", "Country codes in path order, lo->hi."
            ),
            Column(
                "passages",
                "JSONB NOT NULL",
                "Full intersecting passage_id list of this pair — the cross-leg "
                "first-claim dedupe happens at trip assembly.",
            ),
            Column(
                "geometry",
                "JSONB NOT NULL",
                "[[lon, lat], ...] lo->hi. Deliberately the last column — large; "
                "keep it out of ad-hoc SELECTs.",
            ),
            Column(
                "source",
                "VARCHAR(10) NOT NULL DEFAULT 'runtime'",
                "'precompute' (bulk load) or 'runtime' (stored on a miss).",
            ),
            Column("routed_at", "TIMESTAMPTZ NOT NULL DEFAULT now()"),
        ),
        constraints=("PRIMARY KEY (routing_graph_key, stop_lo, stop_hi, variant_key)",),
    ),
)


ALL_TABLES: tuple[Table, ...] = (
    INPUT_PARAMS_TABLES + SCENARIO_TABLES + ROUTE_CACHE_TABLES
)


# =============================================================================
# Column introspection
# =============================================================================

_CHAR_LIMIT = re.compile(r"^\s*(?:VAR)?CHAR\s*\(\s*(\d+)\s*\)", re.IGNORECASE)


def varchar_limits(qualified_table: str) -> dict[str, int]:
    """Declared character limits of one table's CHAR/VARCHAR columns, keyed
    by column name — read back out of the same definitions build_ddl()
    renders, so they can never drift from the database.

    seed.py uses them to name the column and the offending value behind a
    truncation, which psycopg2 reports only as "value too long for type
    character varying(n)". Unknown table or no character columns: empty."""
    for table in ALL_TABLES:
        if f"{table.schema}.{table.name}" == qualified_table:
            return {
                c.name: int(m.group(1))
                for c in table.columns
                if (m := _CHAR_LIMIT.match(c.sql_type))
            }
    return {}


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
        f"CREATE {'UNLOGGED ' if table.unlogged else ''}TABLE {qualified} (",
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
    parts += [
        "DROP SCHEMA IF EXISTS route_cache CASCADE;",
        "CREATE SCHEMA route_cache;",
        "",
    ]
    parts += [_table_ddl(t) + "\n" for t in ROUTE_CACHE_TABLES]
    return "\n".join(parts)
