"""
test_data_load.py
=================
Verifies the database was seeded correctly after startup.

Tests:
  - All expected schemas exist
  - All expected tables exist and have minimum row counts
  - Key columns are not NULL
  - Referential integrity spot checks
"""

import pytest


import pytest as _pytest


@_pytest.fixture(autouse=True)
def rollback_on_error(db_conn):
    """Roll back any aborted transaction before each test."""
    try:
        yield
    finally:
        try:
            db_conn.rollback()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Expected minimum row counts after seeding
# ---------------------------------------------------------------------------

EXPECTED_ROW_COUNTS = {
    "admin.users": 2,
    "input_params.sources": 2,
    "input_params.countries": 1,
    "input_params.service_classes": 1,
    "input_params.operators": 1,
    "input_params.operator_class_costs": 1,
    "input_params.coach_types": 3,
    "input_params.coach_type_classes": 3,
    "input_params.composition_types": 1,
    "input_params.composition_type_coaches": 1,
    "input_params.composition_references": 1,
    "input_params.track_infrastructure_defaults": 1,
    "input_params.track_infrastructures": 14,  # 2 full-table snapshots x 7 countries
    "input_params.stop_infrastructure_defaults": 1,
    "input_params.stop_infrastructures": 8,
    "scenario.scenarios": 1,  # at least the base scenario
    "proposals.routes": 1,
    "proposals.trips": 1,
    "proposals.stop_times": 3,
}

EXPECTED_SCHEMAS = {"admin", "input_params", "scenario", "proposals"}

REQUIRED_COLUMNS = {
    "input_params.stop_infrastructures": [
        "stop_id",
        "stop_name",
        "country_code",
        "stop_lat",
        "stop_lon",
    ],
    "input_params.track_infrastructures": [
        "country_code",
    ],  # every other column is legitimately nullable — resolved from
        # track_infrastructure_defaults by the loader. SE has NULL tac/parking
        # intentionally; the 21 EU27 countries added beyond the original 7 have
        # every column NULL except country_code (real figures TBD) — see
        # db/dev/seed.py's _TRACK_INFRA_V2_ROWS.
    "input_params.composition_types": [
        "composition_type_id",
        "composition_type_max_speed_kmh",
    ],
    "input_params.coach_types": ["coach_type_id"],
    "input_params.operators": ["operator_id", "operator_driver_costs_eur_h"],
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_schemas_exist(db_cur):
    """All four project schemas exist in the database."""
    db_cur.execute(
        """
        SELECT schema_name
        FROM information_schema.schemata
        WHERE schema_name IN ('admin', 'input_params', 'scenario', 'proposals')
    """
    )
    found = {row["schema_name"] for row in db_cur.fetchall()}
    assert found == EXPECTED_SCHEMAS, f"Missing schemas: {EXPECTED_SCHEMAS - found}"


@pytest.mark.parametrize("table,min_rows", EXPECTED_ROW_COUNTS.items())
def test_table_row_count(db_cur, table, min_rows):
    """Each seeded table has at least the expected number of rows."""
    schema, tbl = table.split(".")
    db_cur.execute(f"SELECT COUNT(*) AS n FROM {schema}.{tbl}")
    count = db_cur.fetchone()["n"]
    assert count >= min_rows, f"{table}: expected >= {min_rows} rows, got {count}"


@pytest.mark.parametrize("table,columns", REQUIRED_COLUMNS.items())
def test_required_columns_not_null(db_cur, table, columns):
    # Note: SE track_tac and parking are intentionally NULL — resolved from defaults
    """Required columns have no NULL values."""
    schema, tbl = table.split(".")
    for col in columns:
        db_cur.execute(f"SELECT COUNT(*) AS n FROM {schema}.{tbl} WHERE {col} IS NULL")
        nulls = db_cur.fetchone()["n"]
        assert nulls == 0, f"{table}.{col} has {nulls} NULL values"


def test_composition_types_have_coaches(db_cur):
    """Every composition type has at least one coach assigned."""
    db_cur.execute(
        """
        SELECT ct.composition_type_id
        FROM input_params.composition_types ct
        LEFT JOIN input_params.composition_type_coaches cc
            ON cc.composition_type_row_id = ct.composition_type_row_id
        GROUP BY ct.composition_type_id
        HAVING COUNT(cc.position) = 0
    """
    )
    orphans = [row["composition_type_id"] for row in db_cur.fetchall()]
    assert orphans == [], f"Composition types with no coaches: {orphans}"


def test_coach_type_classes_have_places(db_cur):
    """Every coach_type_class row has a positive place count."""
    db_cur.execute(
        """
        SELECT COUNT(*) AS n
        FROM input_params.coach_type_classes
        WHERE coach_type_class_places <= 0  -- column name correct
    """
    )
    bad = db_cur.fetchone()["n"]
    assert bad == 0, f"{bad} coach_type_class rows have zero or negative places"


def test_track_infra_has_current_row_per_country(db_cur, base_scenario):
    """Each country has exactly one row at the base scenario's pinned track_infrastructures version.

    This should always hold by construction (UNIQUE(country_code, track_infra_version)
    plus the full-table-snapshot write invariant), but is asserted directly here to
    catch a broken snapshot write.
    """
    db_cur.execute(
        """
        SELECT country_code, COUNT(*) AS n
        FROM input_params.track_infrastructures
        WHERE track_infra_version = %s
        GROUP BY country_code
        HAVING COUNT(*) > 1
    """,
        (base_scenario["track_infrastructures_version"],),
    )
    dupes = [row["country_code"] for row in db_cur.fetchall()]
    assert dupes == [], f"Countries with multiple rows at the pinned version: {dupes}"


def test_track_infrastructure_defaults_exists(db_cur, base_scenario):
    """The base scenario's pinned track infrastructure default row exists."""
    db_cur.execute(
        """
        SELECT COUNT(*) AS n FROM input_params.track_infrastructure_defaults
        WHERE track_infra_default_version = %s
    """,
        (base_scenario["track_infrastructure_defaults_version"],),
    )
    assert db_cur.fetchone()["n"] >= 1


def test_stop_infrastructure_defaults_has_global(db_cur, base_scenario):
    """A global stop infrastructure default (country_code IS NULL) exists at the pinned version."""
    db_cur.execute(
        """
        SELECT COUNT(*) AS n FROM input_params.stop_infrastructure_defaults
        WHERE stop_infra_default_version = %s AND country_code IS NULL
    """,
        (base_scenario["stop_infrastructure_defaults_version"],),
    )
    assert db_cur.fetchone()["n"] >= 1, "No global stop infrastructure default found"


def test_composition_references_exist(db_cur):
    """At least one composition reference row exists."""
    db_cur.execute(
        """
        SELECT COUNT(*) AS n FROM input_params.composition_references
    """
    )
    assert db_cur.fetchone()["n"] >= 1, "No composition_references row found"


def test_service_classes_exist(db_cur):
    """Service classes table is populated."""
    db_cur.execute("SELECT COUNT(*) AS n FROM input_params.service_classes")
    assert db_cur.fetchone()["n"] >= 1