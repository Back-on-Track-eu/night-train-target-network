"""
test_02_db_seed.py
==================
Verifies the database was created and seeded correctly at stack startup —
the data foundation every loader/API test builds on.

Covers:
  - All four project schemas exist
  - Every seeded table has at least its expected row count
  - Key columns contain no NULLs
  - Referential/structural integrity spot checks (compositions have coaches,
    coach classes have places, exactly one row per country at the pinned
    track infra version, defaults rows exist)
  - All three seeded scenarios (2026 Base Line / 2032 Base Line / 2032 Base
    Line + HSR allowed) are present and consistent
"""

import pytest

# =============================================================================
# Expectations after seeding — see db/dev/seed.py
# =============================================================================

EXPECTED_SCHEMAS = {"admin", "input_params", "scenario", "proposals"}

# Minimum row counts. Deliberately >= (not ==) so adding seed data doesn't
# break the suite, while dropping seed data still fails loudly.
EXPECTED_ROW_COUNTS = {
    "admin.users": 3,  # David, Bjarne, test_script (suite identity)
    "input_params.sources": 2,
    "input_params.countries": 28,  # 7 original routing countries + 21 further EU27
    "input_params.service_classes": 1,
    "input_params.operators": 1,
    "input_params.operator_class_costs": 1,
    "input_params.coach_types": 3,
    "input_params.coach_type_classes": 3,
    "input_params.composition_types": 10,  # STD-3.1 … STD-13.1
    "input_params.composition_type_coaches": 1,
    "input_params.composition_references": 1,
    "input_params.track_infrastructure_defaults": 3,  # 1 per scenario
    "input_params.track_infrastructures": 84,  # 3 full-table snapshots × 28 countries
    "input_params.stop_infrastructure_defaults": 3,  # 1 per scenario
    "input_params.stop_infrastructures": 174,  # 3 full-table snapshots × 58 stops
    "scenario.scenarios": 3,  # 2026-baseline + base + 2032-baseline-hsr-allowed
    "proposals.proposals": 1,  # one real saved example proposal — see seed_example_proposal()
    "proposals.routes": 1,
    "proposals.trips": 2,  # both directions of the one seeded proposal
    "proposals.stop_times": 6,  # 3 stops x 2 directions
}

# Columns that must never be NULL. Every other track_infrastructures column
# is legitimately nullable — resolved from track_infrastructure_defaults by
# the loader (SE nulls tac/parking intentionally; the 21 EU27 countries added
# beyond the original 7 null everything but country_code — see seed.py).
REQUIRED_COLUMNS = {
    "input_params.stop_infrastructures": [
        "stop_id",
        "stop_name",
        "country_code",
        "stop_lat",
        "stop_lon",
    ],
    "input_params.track_infrastructures": ["country_code"],
    "input_params.composition_types": [
        "composition_type_id",
        "composition_type_max_speed_kmh",
    ],
    "input_params.coach_types": ["coach_type_id"],
    "input_params.operators": ["operator_id", "operator_driver_costs_eur_h"],
}


# =============================================================================
# Schemas and row counts
# =============================================================================


def test_schemas_exist(db_cur):
    """All four project schemas exist in the database."""
    db_cur.execute("""
        SELECT schema_name FROM information_schema.schemata
        WHERE schema_name IN ('admin', 'input_params', 'scenario', 'proposals')
        """)
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
    """Required columns contain no NULL values in any row."""
    schema, tbl = table.split(".")
    for col in columns:
        db_cur.execute(f"SELECT COUNT(*) AS n FROM {schema}.{tbl} WHERE {col} IS NULL")
        nulls = db_cur.fetchone()["n"]
        assert nulls == 0, f"{table}.{col} has {nulls} NULL values"


# =============================================================================
# Structural integrity
# =============================================================================


def test_composition_types_have_coaches(db_cur):
    """Every composition type has at least one coach assigned — a composition
    with zero coaches would have zero capacity and zero weight."""
    db_cur.execute("""
        SELECT ct.composition_type_id
        FROM input_params.composition_types ct
        LEFT JOIN input_params.composition_type_coaches cc
            ON cc.composition_type_row_id = ct.composition_type_row_id
        GROUP BY ct.composition_type_id
        HAVING COUNT(cc.position) = 0
        """)
    orphans = [row["composition_type_id"] for row in db_cur.fetchall()]
    assert orphans == [], f"Composition types with no coaches: {orphans}"


def test_coach_type_classes_have_places(db_cur):
    """Every coach_type_class row has a positive place count."""
    db_cur.execute(
        "SELECT COUNT(*) AS n FROM input_params.coach_type_classes "
        "WHERE coach_type_class_places <= 0"
    )
    bad = db_cur.fetchone()["n"]
    assert bad == 0, f"{bad} coach_type_class rows have zero or negative places"


def test_service_classes_have_no_invalid_density(db_cur):
    """Density (space consumption per place) is never NULL and never
    negative. Exactly 0.0 is allowed and expected for non-passenger classes
    like Catering, which occupy space but sell no places; a NULL or negative
    value, by contrast, would corrupt capacity weighting."""
    db_cur.execute(
        "SELECT service_class_id FROM input_params.service_classes "
        "WHERE service_class_density IS NULL OR service_class_density < 0"
    )
    bad = [row["service_class_id"] for row in db_cur.fetchall()]
    assert bad == [], f"service_class rows with NULL/negative density: {bad}"


def test_track_infra_one_row_per_country_at_pinned_version(db_cur, base_scenario):
    """Exactly one track infra row per country at the base scenario's pinned
    version — a duplicate would make exact-match resolution ambiguous."""
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


def test_track_infrastructure_default_row_exists(db_cur, base_scenario):
    """The base scenario's pinned track infrastructure default row exists —
    every NULL country field resolves against it."""
    db_cur.execute(
        "SELECT COUNT(*) AS n FROM input_params.track_infrastructure_defaults "
        "WHERE track_infra_default_version = %s",
        (base_scenario["track_infrastructure_defaults_version"],),
    )
    assert db_cur.fetchone()["n"] >= 1


def test_stop_infrastructure_global_default_exists(db_cur, base_scenario):
    """A global stop default (country_code IS NULL) exists at the pinned
    version — stops with NULL stop_charge_eur resolve against it."""
    db_cur.execute(
        "SELECT COUNT(*) AS n FROM input_params.stop_infrastructure_defaults "
        "WHERE stop_infra_default_version = %s AND country_code IS NULL",
        (base_scenario["stop_infrastructure_defaults_version"],),
    )
    assert db_cur.fetchone()["n"] >= 1, "No global stop infrastructure default found"


def test_country_geometries_seeded(db_cur):
    """The PostGIS border geometry is populated for every routing-relevant
    country a seeded stop sits in — CountryIndex is built from these at API
    startup, so a missing polygon breaks country attribution silently."""
    db_cur.execute("""
        SELECT DISTINCT s.country_code
        FROM input_params.stop_infrastructures s
        JOIN input_params.countries c ON c.country_code = s.country_code
        WHERE c.country_geom IS NULL
        """)
    missing = [row["country_code"] for row in db_cur.fetchall()]
    assert missing == [], f"Stop countries without a border geometry: {missing}"


# =============================================================================
# Scenario seed consistency
# =============================================================================


def test_exactly_one_current_base_scenario(db_cur):
    """Exactly one scenario carries is_current_base = TRUE — the partial
    unique index enforces at most one; the seed must supply exactly one."""
    db_cur.execute(
        "SELECT COUNT(*) AS n FROM scenario.scenarios WHERE is_current_base = TRUE"
    )
    assert db_cur.fetchone()["n"] == 1


def test_historical_scenario_pins_version_1(historical_scenario, base_scenario):
    """The 2026 Base Line scenario pins all four infrastructure tables to
    version 1 — its own full snapshot, not a partial diff against base."""
    for col in (
        "track_infrastructures_version",
        "track_infrastructure_defaults_version",
        "stop_infrastructures_version",
        "stop_infrastructure_defaults_version",
    ):
        assert historical_scenario[col] == 1
        assert historical_scenario[col] != base_scenario[col]


def test_hsr_scenario_pins_version_3(hsr_scenario, base_scenario):
    """The 2032 Base Line + HSR allowed scenario pins all four
    infrastructure tables to version 3 — independent from base's
    version 2, per-table, even though only track_hsr_allowed actually
    differs in the underlying data."""
    for col in (
        "track_infrastructures_version",
        "track_infrastructure_defaults_version",
        "stop_infrastructures_version",
        "stop_infrastructure_defaults_version",
    ):
        assert hsr_scenario[col] == 3
        assert hsr_scenario[col] != base_scenario[col]


def test_stop_infrastructure_values_unchanged_by_hsr_scenario(
    db_cur, hsr_scenario, base_scenario
):
    """Stop charges don't depend on the HSR policy — the hsr_scenario's
    stop_infrastructures snapshot (version 3) carries the same values as
    base's (version 2), even though the version numbers differ."""
    db_cur.execute(
        "SELECT stop_id, stop_charge_eur FROM input_params.stop_infrastructures "
        "WHERE stop_infra_version = %s ORDER BY stop_id",
        (base_scenario["stop_infrastructures_version"],),
    )
    base_rows = db_cur.fetchall()
    db_cur.execute(
        "SELECT stop_id, stop_charge_eur FROM input_params.stop_infrastructures "
        "WHERE stop_infra_version = %s ORDER BY stop_id",
        (hsr_scenario["stop_infrastructures_version"],),
    )
    hsr_rows = db_cur.fetchall()
    base_values = [dict(r) for r in base_rows]
    hsr_values = [dict(r) for r in hsr_rows]
    assert base_values == hsr_values