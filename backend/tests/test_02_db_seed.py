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
  - Proposals redesign, schema phase 1 (2026-08-03, additive-only — see
    docs/PROPOSALS_DESIGN.md §10 WP1): new sidecar/update_log/
    proposal_summaries/compute-cache tables exist, the new columns on
    proposals.proposals/stop_times exist and are still nullable, the
    PostGIS geometry column and UNLOGGED cache tables are set up correctly
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
    "input_params.sources": 3,  # 2 legacy + calibration umbrella
    "input_params.countries": 28,  # 7 original routing countries + 21 further EU27
    "input_params.service_classes": 25,  # one per coach section (class_id naming rule)
    "input_params.operators": 2,  # STD-REF / STD-NEW
    "input_params.operator_class_costs": 50,  # 2 operators × 25 section classes (fan-out by class_main)
    "input_params.coach_types": 24,  # real coach types (workbook 2026-07-22)
    "input_params.coach_type_classes": 25,
    "input_params.composition_types": 8,  # the eight calibrated standard compositions
    "input_params.composition_type_coaches": 76,
    "input_params.track_infrastructure_defaults": 3,  # 1 per scenario
    "input_params.track_infrastructures": 84,  # 3 full-table snapshots × 28 countries
    "input_params.stop_infrastructure_defaults": 3,  # 1 per scenario
    # 3 full-table snapshots × 58 seeded stops. A minimum, not an exact
    # count: db/ontd/stop_mapping.py (WP10 step 6a) mints additional
    # stops into the pinned snapshot once the ONTD pipeline has run.
    "input_params.stop_infrastructures": 174,
    "scenario.scenarios": 3,  # 2026-baseline + base + 2032-baseline-hsr-allowed
    "proposals.proposals": 1,  # one real saved example proposal — see seed_example_proposal()
    "proposals.routes": 1,
    "proposals.trips": 2,  # both directions of the one seeded proposal
    "proposals.stop_times": 6,  # 3 stops x 2 directions
}

# Tables added by the proposals redesign, schema phase 1 (2026-08-03,
# additive-only — see docs/PROPOSALS_DESIGN.md §10 WP1 and
# migrations/2026-08-03_proposal_schema_phase1.sql). Existence-only checks:
# nothing seeds them yet, since the compute/publish endpoints that would
# write to them don't exist until later WPs.
EXPECTED_PHASE1_TABLES = {
    "proposals.segments",
    "proposals.od_pairs",
    "proposals.parkings",
    "proposals.shuntings",
    "proposals.timetable_warnings",
    "proposals.seasonal_schedules",
    "proposals.update_log",
    "proposals.proposal_summaries",
    "proposals.compute_cache_pointer",
    "proposals.compute_cache_result",
}

# Columns WP5's finalizing migration (2026-08-04_proposal_schema_phase2_
# cutover.sql) enforces NOT NULL on, now that the sole write path
# (ProposalRepository.publish() / gtfs_store.insert_route_gtfs())
# always sets them — no half-states, no unpopulated rows possible anymore.
EXPECTED_PHASE2_NOT_NULL_COLUMNS = {
    "proposals.proposals": ["route_fingerprint", "compute_request"],
    "proposals.stop_times": ["stop_type"],
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
# Proposals redesign — schema phase 1 (2026-08-03, additive-only)
# =============================================================================


@pytest.mark.parametrize("table", sorted(EXPECTED_PHASE1_TABLES))
def test_phase1_table_exists(db_cur, table):
    """Every table the phase-1 migration adds is present. Existence only —
    the tables are empty until later WPs wire up writers (WP5 for
    update_log/proposal_summaries, WP13 for the compute cache)."""
    schema, tbl = table.split(".")
    db_cur.execute(
        "SELECT COUNT(*) AS n FROM information_schema.tables "
        "WHERE table_schema = %s AND table_name = %s",
        (schema, tbl),
    )
    assert db_cur.fetchone()["n"] == 1, f"{table}: table not found"


@pytest.mark.parametrize(
    "table,columns",
    EXPECTED_PHASE2_NOT_NULL_COLUMNS.items(),
)
def test_phase2_not_null_columns_enforced(db_cur, table, columns):
    """WP5's finalizing migration enforces NOT NULL on these columns —
    every proposal is now always fully populated (no half-states, §2.4),
    so a nullable column here would mean the migration didn't apply."""
    schema, tbl = table.split(".")
    for col in columns:
        db_cur.execute(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s AND column_name = %s",
            (schema, tbl, col),
        )
        row = db_cur.fetchone()
        assert row is not None, f"{table}.{col}: column not found"
        assert row["is_nullable"] == "NO", f"{table}.{col}: expected NOT NULL"


def test_proposal_summaries_geom_is_postgis_geometry(db_cur):
    """proposal_summaries.geom_simplified is a PostGIS geometry column, not
    a plain type — information_schema doesn't expose the (MultiLineString,
    4326) type modifier, so this only asserts the underlying udt_name;
    the full type constraint is exercised once WP5/WP6 start writing and
    querying real geometries."""
    db_cur.execute(
        "SELECT udt_name FROM information_schema.columns "
        "WHERE table_schema = 'proposals' AND table_name = 'proposal_summaries' "
        "AND column_name = 'geom_simplified'"
    )
    row = db_cur.fetchone()
    assert row is not None, "proposal_summaries.geom_simplified: column not found"
    assert row["udt_name"] == "geometry"


def test_compute_cache_tables_are_unlogged(db_cur):
    """Both compute cache tables are UNLOGGED (docs/PROPOSALS_DESIGN.md
    §2.3) — a disposable performance layer, no WAL overhead, safe to lose
    on crash."""
    db_cur.execute(
        "SELECT relname, relpersistence FROM pg_class "
        "WHERE relname IN ('compute_cache_pointer', 'compute_cache_result')"
    )
    persistence = {row["relname"]: row["relpersistence"] for row in db_cur.fetchall()}
    assert persistence == {
        "compute_cache_pointer": "u",
        "compute_cache_result": "u",
    }


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
