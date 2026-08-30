"""
test_03_loader.py
=================
Verifies the DBDataLoader produces correct domain objects.

Two levels:
  Static  — the schema definition contains every column the loader reads
            (catches a rename that the loader wasn't updated for, without
            needing a live DB round-trip per column). Sources: the
            declarative db/schema.py (input_params + scenario) plus the
            CREATE TABLE blocks in db/dev/sql/*.sql (admin, proposals).
  Runtime — loader output matches raw DB values for known seeded rows,
            including the aggregations (capacity, weight) and the density
            values the evaluation model depends on.
"""

import os
import re

import pytest

from models.params import ENERGY_PRICE_FIELD_NAMES, FACILITY_FIELD_NAMES

# =============================================================================
# Static checks — SQL schema vs loader expectations
# =============================================================================


def _parse_schema_columns() -> dict[str, set[str]]:
    """{table: {columns}} across both schema sources: the declarative
    db/schema.py tables (input_params + scenario, read directly from the
    dataclasses — no SQL parsing) and the CREATE TABLE blocks in
    db/dev/sql/*.sql (admin, proposals).

    Deliberately only the application schemas: the ontd schema
    (db/ontd/sql/) is reference data that DBDataLoader never reads, so it
    has no loader columns to check.
    """
    from db.schema import INPUT_PARAMS_TABLES, SCENARIO_TABLES

    tables: dict[str, set[str]] = {
        f"{t.schema}.{t.name}".lower(): {c.name for c in t.columns}
        for t in INPUT_PARAMS_TABLES + SCENARIO_TABLES
    }
    sql_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db", "dev", "sql"
    )
    for fname in os.listdir(sql_dir):
        if not fname.endswith(".sql"):
            continue
        src = open(os.path.join(sql_dir, fname), encoding="utf-8-sig").read()
        for match in re.finditer(
            r"CREATE TABLE (?:IF NOT EXISTS )?(\w+\.\w+)\s*\((.*?)\);",
            src,
            re.DOTALL | re.IGNORECASE,
        ):
            block = match.group(2)
            cols = re.findall(r"^\s{4}(\w+)\s+\w", block, re.MULTILINE)
            tables[match.group(1).lower()] = set(cols)
    return tables


SCHEMA_COLUMNS = _parse_schema_columns()

# Every column the loader reads, per table — keep in sync with the SELECTs
# in adapters/data_loader_from_db.py.
LOADER_READ_COLUMNS = [
    # composition_types
    ("input_params.composition_types", "composition_type_id"),
    ("input_params.composition_types", "composition_type_operator_id"),
    ("input_params.composition_types", "composition_type_hsr_allowed"),
    ("input_params.composition_types", "composition_type_max_speed_kmh"),
    ("input_params.composition_types", "composition_type_min_boarding_time"),
    ("input_params.composition_types", "composition_type_min_alighting_time"),
    ("input_params.composition_types", "composition_type_purchase_coach_eur"),
    ("input_params.composition_types", "composition_type_coach_avail_per"),
    ("input_params.composition_types", "composition_type_coach_amort_years"),
    ("input_params.composition_types", "composition_type_cleaning_eur_day"),
    ("input_params.composition_types", "composition_type_coach_maint_eur_km"),
    # operators
    ("input_params.operators", "operator_id"),
    ("input_params.operators", "operator_driver_costs_eur_h"),
    ("input_params.operators", "operator_crew_costs_eur_h"),
    ("input_params.operators", "operator_ebit_margin_per"),
    ("input_params.operators", "operator_financing_quota_per"),
    ("input_params.operators", "operator_var_overhead_per"),
    ("input_params.operators", "operator_fix_overhead_quota_per"),
    # service_classes
    ("input_params.service_classes", "service_class_id"),
    ("input_params.service_classes", "service_class_main"),
    # coach_types / coach_type_classes / composition_type_coaches
    ("input_params.coach_types", "coach_type_id"),
    ("input_params.coach_types", "coach_type_weight_gross_t"),
    ("input_params.coach_type_classes", "coach_type_row_id"),
    ("input_params.coach_type_classes", "coach_type_class_places"),
    ("input_params.composition_type_coaches", "composition_type_row_id"),
    ("input_params.composition_type_coaches", "position"),
    ("input_params.composition_type_coaches", "coach_type_row_id"),
    # track_infrastructures
    ("input_params.track_infrastructures", "country_code"),
    ("input_params.track_infrastructures", "track_tac_eur_train_km"),
    ("input_params.track_infrastructures", "track_parking_eur_day"),
    ("input_params.track_infrastructures", "track_energy_price_eur_kwh"),
    ("input_params.track_infrastructures", "track_energy_price_night_eur_kwh"),
    ("input_params.track_infrastructures", "track_energy_night_band_start"),
    ("input_params.track_infrastructures", "track_energy_catenary_eur_train_km"),
    (
        "input_params.track_infrastructures",
        "track_energy_catenary_eur_gross_tonne_km",
    ),
    ("input_params.track_infrastructures", "track_parking_basis"),
    ("input_params.track_infrastructures", "track_parking_eur_metre_day"),
    ("input_params.track_infrastructures", "track_parking_eur_hour"),
    ("input_params.track_infrastructures", "track_parking_eur_event"),
    ("input_params.track_infrastructures", "track_parking_free_hours"),
    ("input_params.track_infrastructures", "track_parking_hotel_power_eur_hour"),
    ("input_params.track_infrastructures", "track_terrain_category"),
    ("input_params.track_infrastructures", "track_terrain_score"),
    ("input_params.track_infrastructures", "track_hsr_allowed"),
    ("input_params.track_infrastructures", "track_min_boarding_time"),
    ("input_params.track_infrastructures", "track_min_alighting_time"),
    ("input_params.track_infrastructures", "track_buffer_quota_per"),
    # stop_infrastructures
    ("input_params.stop_infrastructures", "stop_id"),
    ("input_params.stop_infrastructures", "stop_name"),
    ("input_params.stop_infrastructures", "country_code"),
    ("input_params.stop_infrastructures", "stop_lat"),
    ("input_params.stop_infrastructures", "stop_lon"),
    ("input_params.stop_infrastructures", "stop_charge_eur"),
]


@pytest.mark.parametrize("table,column", LOADER_READ_COLUMNS)
def test_column_exists_in_schema(table, column):
    """Every column the loader reads exists in the schema definition."""
    table_lower = table.lower()
    assert table_lower in SCHEMA_COLUMNS, (
        f"Table {table} not found in schema definition. Found: {sorted(SCHEMA_COLUMNS)}"
    )
    assert column in SCHEMA_COLUMNS[table_lower], (
        f"Column {table}.{column} not found in schema"
    )


# =============================================================================
# Runtime checks — loader output vs raw DB values
# =============================================================================

COMP_ID = "NEW-BAL-7"
COUNTRY = "DE"
STOP_ID = "osm:n3856100103"


def test_all_compositions_load(loader):
    """All seeded compositions load without errors."""
    comps = loader.build_all_compositions()
    assert len(comps) == 8, (
        f"Expected the eight calibrated compositions, got {len(comps)}"
    )


def test_all_stops_load(loader):
    """All seeded stops load without errors."""
    stops = loader.build_all_stops()
    assert len(stops.all()) >= 8, f"Expected >= 8 stops, got {len(stops.all())}"


def test_composition_fields_match_db(loader, db_cur):
    """Composition built by the loader matches raw DB values for key routing
    and cost fields (including the operator join)."""
    comp = loader.build_all_compositions().get(COMP_ID)

    db_cur.execute(
        """
        SELECT ct.*, op.operator_driver_costs_eur_h, op.operator_ebit_margin_per
        FROM input_params.composition_types ct
        JOIN input_params.operators op ON op.operator_id = ct.composition_type_operator_id
        WHERE ct.composition_type_id = %s
        """,
        (COMP_ID,),
    )
    row = db_cur.fetchone()
    assert row is not None, f"No DB row found for composition '{COMP_ID}'"

    assert comp.comp_id == row["composition_type_id"]
    assert comp.max_speed_kmh == pytest.approx(
        float(row["composition_type_max_speed_kmh"]), rel=1e-4
    )
    assert comp.hsr_allowed == row["composition_type_hsr_allowed"]
    assert comp.driver_costs_eur_h == pytest.approx(
        float(row["operator_driver_costs_eur_h"]), rel=1e-4
    )
    assert comp.ebit_margin_per == pytest.approx(
        float(row["operator_ebit_margin_per"]), rel=1e-4
    )


def test_composition_capacity_matches_db_aggregation(loader, db_cur):
    """places_by_class (keyed by class_main) matches a direct DB aggregation
    over the composition's coaches."""
    comp = loader.build_all_compositions().get(COMP_ID)

    db_cur.execute(
        """
        SELECT sc.service_class_main AS class_main,
               SUM(ctc.coach_type_class_places) AS places
        FROM input_params.composition_types ct
        JOIN input_params.composition_type_coaches cc
            ON cc.composition_type_row_id = ct.composition_type_row_id
        JOIN input_params.coach_type_classes ctc
            ON ctc.coach_type_row_id = cc.coach_type_row_id
        JOIN input_params.service_classes sc
            ON sc.service_class_id = ctc.service_class_id
        WHERE ct.composition_type_id = %s
        GROUP BY sc.service_class_main
        """,
        (COMP_ID,),
    )
    expected = {row["class_main"]: int(row["places"]) for row in db_cur.fetchall()}

    for class_main, places in expected.items():
        assert comp.places_by_class.get(class_main, 0) == places, (
            f"places_by_class[{class_main}]: "
            f"loader={comp.places_by_class.get(class_main)} db={places}"
        )


def test_composition_weight_matches_db_aggregation(loader, db_cur):
    """total_weight_t matches SUM of coach gross weights from the DB."""
    comp = loader.build_all_compositions().get(COMP_ID)

    db_cur.execute(
        """
        SELECT COALESCE(SUM(ct.coach_type_weight_gross_t), 0) AS weight
        FROM input_params.composition_types c
        JOIN input_params.composition_type_coaches cc
            ON cc.composition_type_row_id = c.composition_type_row_id
        JOIN input_params.coach_types ct ON ct.coach_type_row_id = cc.coach_type_row_id
        WHERE c.composition_type_id = %s
        """,
        (COMP_ID,),
    )
    assert comp.total_weight_t == pytest.approx(
        float(db_cur.fetchone()["weight"]), rel=1e-4
    )


def test_composition_density_matches_db(loader, db_cur):
    """Densities are DERIVED from real section geometry since 2026-07-22
    (service_class_density retired): m/place and t/place per class_main
    must reproduce section sums over places from the DB exactly."""
    comps = loader.build_all_compositions()
    comp = comps.get("NEW-BAL-7")
    dl = comp.density_by_class_main_length
    dw = comp.density_by_class_main_weight
    assert set(dl) == set(comp.places_by_class) == set(dw)
    for cls, places in comp.places_by_class.items():
        assert dl[cls] > 0 and dw[cls] > 0
        m_sum = sum(
            a.section_length_m
            for ct in comp.coaches.values()
            for a in ct.classes.values()
            if a.class_main == cls
        )
        assert dl[cls] == pytest.approx(m_sum / places)


def test_track_infra_fields_match_db(loader, db_cur, base_scenario):
    """TrackInfrastructure for a fully-populated country (DE) matches raw DB
    values at the pinned version, and is flagged non-default."""
    tracks = loader.build_all_tracks()
    assert COUNTRY in tracks.all(), f"Country {COUNTRY} not in tracks collection"
    t = tracks.get(COUNTRY)

    db_cur.execute(
        "SELECT * FROM input_params.track_infrastructures "
        "WHERE country_code = %s AND track_infra_version = %s",
        (COUNTRY, base_scenario["track_infrastructures_version"]),
    )
    row = db_cur.fetchone()
    assert row is not None

    assert t.country_code == row["country_code"]
    assert t.tac_eur_train_km == pytest.approx(
        float(row["track_tac_eur_train_km"]), rel=1e-4
    )
    assert t.energy_price_eur_kwh == pytest.approx(
        float(row["track_energy_price_eur_kwh"]), rel=1e-4
    )
    assert t.hsr_allowed == row["track_hsr_allowed"]
    assert t.terrain_category == row["track_terrain_category"]

    # Germany is calibrated for energy but bands neither its electricity
    # tariff nor levies a catenary charge, so its energy group is a day rate
    # plus four documented NULLs — which is exactly what must survive the
    # load. A None here that arrived as a substituted default would price a
    # night discount Germany does not give.
    assert t.energy_price_night_eur_kwh is None
    assert t.energy_night_band_start_min is None
    assert t.energy_night_band_end_min is None
    assert t.energy_catenary_eur_train_km is None
    assert t.energy_catenary_eur_gross_tonne_km is None

    entry = tracks.param_versions.get(f"track_infra:{COUNTRY}:tac_eur_train_km")
    assert entry is not None
    assert entry.is_default is False

    # The energy group is registered in ParamVersions like any other field,
    # and never flagged defaulted: unlike the ten legacy parameters it has no
    # fallback to resolve against (see models/params.py,
    # ENERGY_PRICE_FIELD_NAMES).
    for field_name in ENERGY_PRICE_FIELD_NAMES:
        entry = tracks.param_versions.get(f"track_infra:{COUNTRY}:{field_name}")
        assert entry is not None, f"{field_name} missing from param_versions"
        assert entry.is_default is False

    # The facility group is registered the same way. Germany is calibrated, so
    # it is not defaulted — and it prices per started hour, which is the one
    # basis a per-metre model would silently get wrong.
    for field_name in FACILITY_FIELD_NAMES:
        entry = tracks.param_versions.get(f"track_infra:{COUNTRY}:{field_name}")
        assert entry is not None, f"{field_name} missing from param_versions"
        assert entry.is_default is False
    assert t.parking_basis == "per_hour"
    assert t.parking_eur_metre_day is None


def test_facility_group_is_resolved_for_every_country(loader):
    """Every country ends up with a stabling basis, and exactly one rate column
    populated for it. A country with no calibration takes the European default
    group; a country documented as levying nothing carries the basis 'none'
    with no rate at all — which is what distinguishes the two."""
    tracks = loader.build_all_tracks()
    rate_column = {
        "per_metre_day": "parking_eur_metre_day",
        "per_hour": "parking_eur_hour",
        "per_event": "parking_eur_event",
    }
    for t in tracks.all().values():
        assert t.parking_basis in (*rate_column, "none"), (
            f"{t.country_code}: unresolved stabling basis {t.parking_basis!r}"
        )
        populated = [c for c in rate_column.values() if getattr(t, c) is not None]
        if t.parking_basis == "none":
            assert not populated, (
                f"{t.country_code}: basis 'none' but carries {populated}"
            )
            continue
        assert populated == [rate_column[t.parking_basis]], (
            f"{t.country_code}: basis {t.parking_basis} with rate columns {populated}"
        )


def test_shunting_is_an_all_in_figure_not_an_im_tariff(loader):
    """The calibrated shunting charge is the IM tariff plus the market cost of
    what the IM does not supply, so every country lands in the band one hour of
    a shunting locomotive and crew costs anywhere in Europe. A figure at the
    published-tariff level (single-digit euro) would mean the top-up was lost."""
    tracks = loader.build_all_tracks()
    for t in tracks.all().values():
        assert 80.0 <= t.shunting_eur_event <= 400.0, (
            f"{t.country_code}: shunting {t.shunting_eur_event} outside the "
            "all-in band — has the market top-up been dropped?"
        )


def test_banded_country_keeps_its_night_price_and_band(loader):
    """Austria, Switzerland and Croatia are the three banded electricity
    tariffs. Whichever of them the scenario routes through must arrive with a
    night price BELOW its day price and a band on both ends — a half-loaded
    band would silently price a whole country at one rate."""
    tracks = loader.build_all_tracks()
    banded = [
        t for t in tracks.all().values() if t.energy_price_night_eur_kwh is not None
    ]
    assert banded, "no banded electricity tariff loaded — expected AT, CH and HR"
    for t in banded:
        assert t.energy_price_night_eur_kwh < t.energy_price_eur_kwh, (
            f"{t.country_code}: night rate not below the day rate"
        )
        assert t.energy_night_band_start_min is not None
        assert t.energy_night_band_end_min is not None
        assert 0 <= t.energy_night_band_start_min < 24 * 60
        assert 0 <= t.energy_night_band_end_min < 24 * 60


def test_catenary_charge_is_levied_in_one_unit_only(loader):
    """An infrastructure manager picks a unit: per train-km or per
    gross-tonne-km. Both populated for one country would double-charge the
    same asset."""
    tracks = loader.build_all_tracks()
    levied = [
        t
        for t in tracks.all().values()
        if t.energy_catenary_eur_train_km is not None
        or t.energy_catenary_eur_gross_tonne_km is not None
    ]
    assert levied, "no supply-equipment charge loaded — expected thirteen countries"
    for t in levied:
        assert (
            t.energy_catenary_eur_train_km is None
            or t.energy_catenary_eur_gross_tonne_km is None
        ), f"{t.country_code} levies a catenary charge in both units"


def test_stop_fields_match_db(loader, db_cur, base_scenario):
    """StopInfrastructure for a seeded stop matches raw DB values."""
    stops = loader.build_all_stops()
    assert STOP_ID in stops.all(), f"Stop {STOP_ID} not in stops collection"
    s = stops.get(STOP_ID)

    db_cur.execute(
        "SELECT * FROM input_params.stop_infrastructures "
        "WHERE stop_id = %s AND stop_infra_version = %s",
        (STOP_ID, base_scenario["stop_infrastructures_version"]),
    )
    row = db_cur.fetchone()
    assert row is not None

    assert s.stop_id == row["stop_id"]
    assert s.stop_name == row["stop_name"]
    assert s.stop_country_code == row["country_code"]
    assert s.lat == pytest.approx(float(row["stop_lat"]), rel=1e-4)
    assert s.lon == pytest.approx(float(row["stop_lon"]), rel=1e-4)


def test_country_geometries_cover_stop_countries(loader, db_cur):
    """get_country_geometries() returns a polygon for every country a seeded
    stop sits in — the runtime counterpart of the DB-level geometry check."""
    geoms = dict(loader.get_country_geometries())
    db_cur.execute(
        "SELECT DISTINCT country_code FROM input_params.stop_infrastructures"
    )
    stop_countries = {row["country_code"] for row in db_cur.fetchall()}
    missing = stop_countries - set(geoms)
    assert missing == set(), f"No geometry loaded for stop countries: {missing}"


def test_composition_indicative_figures_present(loader):
    """Compositions with a reference row carry seeded indicative figures.

    Since CALC_VERSION 0.9.7 the KPIs are calibration values read from
    composition_types columns (calib/CALIBRATION.md) — real,
    per-composition figures, no longer flat placeholders.
    """
    comps = loader.build_all_compositions()
    with_indicative = [c for c in comps.all().values() if c.indicative is not None]
    assert len(with_indicative) >= 1, "No composition with indicative figures"
    by_id = {c.comp_id: c for c in with_indicative}
    # both material strategies present and differentiated
    assert "NEW-BAL-7" in by_id and "REF-BUD-6" in by_id
    for c in with_indicative:
        assert c.indicative.cost_eur_per_train_km > 0
        assert c.indicative.cost_ct_per_place_km > 0
    assert (
        by_id["NEW-BAL-7"].indicative.cost_eur_per_train_km
        != by_id["REF-BUD-6"].indicative.cost_eur_per_train_km
    ), "seeded KPIs should differ per composition — placeholder era is over"
    assert by_id["NEW-BAL-7"].material_strategy == "new"
    assert by_id["NEW-BAL-7"].total_length_m == pytest.approx(185.7)
    assert len(by_id["NEW-BAL-7"].coaches) == 7
    assert by_id["REF-BUD-6"].material_strategy == "refurbished"
