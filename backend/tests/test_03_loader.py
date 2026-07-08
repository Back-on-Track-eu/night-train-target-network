"""
test_03_loader.py
=================
Verifies the DBDataLoader produces correct domain objects.

Two levels:
  Static  — the SQL schema files contain every column the loader reads
            (catches a rename in SQL that the loader wasn't updated for,
            without needing a live DB round-trip per column).
  Runtime — loader output matches raw DB values for known seeded rows,
            including the aggregations (capacity, weight) and the density
            values the evaluation model depends on.
"""

import os
import re

import pytest

# =============================================================================
# Static checks — SQL schema vs loader expectations
# =============================================================================


def _parse_schema_columns() -> dict[str, set[str]]:
    """Parse CREATE TABLE blocks in db/dev/sql/*.sql into {table: {columns}}."""
    sql_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db", "dev", "sql"
    )
    tables: dict[str, set[str]] = {}
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
    ("input_params.composition_types", "composition_type_energy_factor_weight"),
    ("input_params.composition_types", "composition_type_energy_factor_speed"),
    ("input_params.composition_types", "composition_type_energy_factor_terrain"),
    ("input_params.composition_types", "composition_type_purchase_coach_eur"),
    ("input_params.composition_types", "composition_type_coach_avail_per"),
    ("input_params.composition_types", "composition_type_coach_amort_years"),
    ("input_params.composition_types", "composition_type_cleaning_eur_day"),
    ("input_params.composition_types", "composition_type_coach_maint_eur_km"),
    # operators
    ("input_params.operators", "operator_id"),
    ("input_params.operators", "operator_driver_costs_eur_h"),
    ("input_params.operators", "operator_crew_costs_eur_h"),
    ("input_params.operators", "operator_driver_overhead_h"),
    ("input_params.operators", "operator_crew_overhead_h"),
    ("input_params.operators", "operator_ebit_margin_per"),
    ("input_params.operators", "operator_financing_quota_per"),
    ("input_params.operators", "operator_var_overhead_per"),
    ("input_params.operators", "operator_fix_overhead_quota_per"),
    # service_classes
    ("input_params.service_classes", "service_class_id"),
    ("input_params.service_classes", "service_class_main"),
    ("input_params.service_classes", "service_class_density"),
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
    # composition_references
    ("input_params.composition_references", "composition_type_id"),
    ("input_params.composition_references", "ref_distance_km"),
    ("input_params.composition_references", "ref_avg_speed_kmh"),
    ("input_params.composition_references", "ref_terrain_score"),
]


@pytest.mark.parametrize("table,column", LOADER_READ_COLUMNS)
def test_column_exists_in_schema(table, column):
    """Every column the loader reads exists in the SQL schema files."""
    table_lower = table.lower()
    assert (
        table_lower in SCHEMA_COLUMNS
    ), f"Table {table} not found in schema files. Found: {sorted(SCHEMA_COLUMNS)}"
    assert (
        column in SCHEMA_COLUMNS[table_lower]
    ), f"Column {table}.{column} not found in schema"


# =============================================================================
# Runtime checks — loader output vs raw DB values
# =============================================================================

COMP_ID = "STD-7.1"
COUNTRY = "DE"
STOP_ID = "DE_BERLIN_HBF"


def test_all_compositions_load(loader):
    """All seeded compositions load without errors."""
    comps = loader.build_all_compositions()
    assert len(comps) >= 10, f"Expected >= 10 compositions, got {len(comps)}"


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
    """density_by_class comes from service_class_density — a regression guard
    for the old bug where densities were left at 0.0."""
    comp = loader.build_all_compositions().get(COMP_ID)

    db_cur.execute(
        "SELECT DISTINCT service_class_main, service_class_density "
        "FROM input_params.service_classes"
    )
    densities = {
        r["service_class_main"]: float(r["service_class_density"])
        for r in db_cur.fetchall()
    }

    for class_main, places in comp.places_by_class.items():
        if places <= 0:
            continue
        assert comp.density_by_class.get(class_main, 0.0) == pytest.approx(
            densities[class_main], rel=1e-4
        ), f"density_by_class[{class_main}] does not match service_class_density"


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

    entry = tracks.param_versions.get(f"track_infra:{COUNTRY}:tac_eur_train_km")
    assert entry is not None
    assert entry.is_default is False


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
    """Compositions with a reference row carry indicative figures.

    compute_indicative_figures() is currently a placeholder (see
    models/compositions/calc_indicative_figures.py) — flat, hand-picked but
    non-zero values — so presence and positivity are all that can be asserted.
    Tighten this once the real compositions cost model lands."""
    comps = loader.build_all_compositions()
    with_indicative = [c for c in comps.all().values() if c.indicative is not None]
    assert len(with_indicative) >= 1, "No composition with indicative figures"
    ind = with_indicative[0].indicative
    assert ind.cost_eur_per_train_km > 0
    assert len(ind.cost_eur_per_place_km_by_class) > 0
    assert all(v > 0 for v in ind.cost_eur_per_place_km_by_class.values())
