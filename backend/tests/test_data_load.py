"""
test_data_load.py
=================
Verifies the database was seeded correctly after startup.

Tests:
  - All expected schemas exist
  - All expected tables exist
  - Each table has the expected minimum row count
  - Key columns are present in each table
  - No NULL values in required fields
"""

import pytest


# ---------------------------------------------------------------------------
# Expected minimum row counts after seeding
# ---------------------------------------------------------------------------

EXPECTED_ROW_COUNTS = {
    "admin.users":                          2,
    "input_params.sources":                 2,
    "input_params.stops":                   8,
    "input_params.stop_defaults":           1,
    "input_params.infrastructure":          7,
    "input_params.infrastructure_defaults": 1,
    "input_params.classes":                 1,   # at least 1
    "input_params.operators":               1,
    "input_params.operator_class_costs":    1,
    "input_params.coachtypes":              3,
    "input_params.coachtype_classes":       3,
    "input_params.compositions":            10,
    "input_params.composition_coaches":     1,   # at least 1
    "proposals.routes":                     1,
    "proposals.trips":                      1,
    "proposals.stop_times":                 3,
    "proposals.shapes":                     1,
    "proposals.proposals":                  1,
}

# ---------------------------------------------------------------------------
# Expected schemas
# ---------------------------------------------------------------------------

EXPECTED_SCHEMAS = {"admin", "input_params", "proposals"}

# ---------------------------------------------------------------------------
# Key NOT NULL columns to spot-check per table
# ---------------------------------------------------------------------------

REQUIRED_COLUMNS = {
    "input_params.stops":          ["stop_id", "stop_name", "stop_country_code", "stop_lat", "stop_lon"],
    "input_params.infrastructure": ["country_code", "infra_tac_eur_train_km", "infra_energy_price_eur_kwh"],
    "input_params.compositions":   ["comp_id", "comp_description", "comp_operator_id", "comp_max_speed_kmh"],
    "input_params.coachtypes":     ["coachtype_id"],
    "input_params.operators":      ["operator_id", "operator_name", "operator_driver_costs_eur_h"],
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_schemas_exist(db_cur):
    """All three project schemas exist in the database."""
    db_cur.execute("""
        SELECT schema_name
        FROM information_schema.schemata
        WHERE schema_name IN ('admin', 'input_params', 'proposals')
    """)
    found = {row["schema_name"] for row in db_cur.fetchall()}
    assert found == EXPECTED_SCHEMAS, \
        f"Missing schemas: {EXPECTED_SCHEMAS - found}"


@pytest.mark.parametrize("table,min_rows", EXPECTED_ROW_COUNTS.items())
def test_table_row_count(db_cur, table, min_rows):
    """Each seeded table has at least the expected number of rows."""
    schema, tbl = table.split(".")
    db_cur.execute(f"SELECT COUNT(*) AS n FROM {schema}.{tbl}")
    count = db_cur.fetchone()["n"]
    assert count >= min_rows, \
        f"{table}: expected >= {min_rows} rows, got {count}"


@pytest.mark.parametrize("table,columns", REQUIRED_COLUMNS.items())
def test_required_columns_not_null(db_cur, table, columns):
    """Required columns have no NULL values."""
    schema, tbl = table.split(".")
    for col in columns:
        db_cur.execute(
            f"SELECT COUNT(*) AS n FROM {schema}.{tbl} WHERE {col} IS NULL"
        )
        nulls = db_cur.fetchone()["n"]
        assert nulls == 0, \
            f"{table}.{col} has {nulls} NULL values"


def test_compositions_have_coaches(db_cur):
    """Every current composition has at least one coach assigned."""
    db_cur.execute("""
        SELECT c.comp_id
        FROM input_params.compositions c
        LEFT JOIN input_params.composition_coaches cc ON cc.comp_row_id = c.comp_row_id
        WHERE c.is_current = TRUE
        GROUP BY c.comp_id
        HAVING COUNT(cc.position) = 0
    """)
    orphans = [row["comp_id"] for row in db_cur.fetchall()]
    assert orphans == [], \
        f"Compositions with no coaches: {orphans}"


def test_coachtype_classes_have_places(db_cur):
    """Every coachtype_class row has a positive place count."""
    db_cur.execute("""
        SELECT COUNT(*) AS n
        FROM input_params.coachtype_classes
        WHERE coachtype_class_places <= 0
    """)
    bad = db_cur.fetchone()["n"]
    assert bad == 0, f"{bad} coachtype_class rows have zero or negative places"


def test_infra_has_current_row_per_country(db_cur):
    """Each country has exactly one is_current infrastructure row."""
    db_cur.execute("""
        SELECT country_code, COUNT(*) AS n
        FROM input_params.infrastructure
        WHERE is_current = TRUE
        GROUP BY country_code
        HAVING COUNT(*) > 1
    """)
    dupes = [row["country_code"] for row in db_cur.fetchall()]
    assert dupes == [], \
        f"Countries with multiple current infra rows: {dupes}"
