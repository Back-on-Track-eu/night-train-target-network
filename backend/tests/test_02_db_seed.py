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
  - All six seeded scenarios are present and consistent: three operating
    conditions (baseline / + NT on HSR / + optimised timetables) on each
    of the two networks, each pinning the routing graph its key names,
    plus the superseded infra-2026 revision
  - Proposals redesign, schema phase 1 (2026-08-03, additive-only — see
    adapters/proposal/README.md §5.2): new sidecar/update_log/
    proposal_summaries/compute-cache tables exist, the new columns on
    proposals.proposals/stop_times exist and are still nullable, the
    PostGIS geometry column and UNLOGGED cache tables are set up correctly
"""

import pytest

# The whole catalog now comes from the Drive-hosted stop seed CSV (the
# curated in-file list was retired when the stop classification pipeline
# took over), so its size isn't knowable here — the file lives inside the
# container in CI. Presence is asserted via the change_log provenance
# marker instead, and the floor below is deliberately loose.
STOP_SEED_CHANGE_LOG_PREFIX = "seeded from the stop classification pipeline"

# =============================================================================
# Expectations after seeding — see db/dev/seed.py
# =============================================================================

EXPECTED_SCHEMAS = {"admin", "input_params", "scenario", "proposals"}

# Minimum row counts. Deliberately >= (not ==) so adding seed data doesn't
# break the suite, while dropping seed data still fails loudly.
EXPECTED_ROW_COUNTS = {
    "admin.users": 3,  # David, Bjarne, test_script (suite identity)
    "input_params.sources": 3,  # 2 legacy + calibration umbrella
    # 7 calibrated routing countries + 21 further EU27 + 6 non-EU
    # (NO, GB, BA, RS, ME, AL)
    "input_params.countries": 34,
    "input_params.service_classes": 25,  # one per coach section (class_id naming rule)
    "input_params.operators": 2,  # STD-REF / STD-NEW
    "input_params.operator_class_costs": 50,  # 2 operators × 25 section classes (fan-out by class_main)
    "input_params.coach_types": 24,  # real coach types (workbook 2026-07-22)
    "input_params.coach_type_classes": 25,
    "input_params.composition_types": 8,  # the eight calibrated standard compositions
    "input_params.composition_type_coaches": 76,
    "input_params.track_infrastructure_defaults": 3,  # 1 per scenario
    "input_params.track_infrastructures": 102,  # 3 full-table snapshots × 34 countries
    "input_params.stop_infrastructure_defaults": 3,  # 1 per scenario
    # Floor only — the real total is 3 full-table snapshots × the catalog
    # from db/dev/data/stop_seed_catalog.csv, minus the stops whose country
    # COUNTRIES doesn't model (~870 stops seeded, so ~2600 rows). Kept well
    # below that so regenerating the catalog doesn't break the suite; the
    # snapshot-set invariant is asserted by test_stop_catalog_snapshots.
    "input_params.stop_infrastructures": 1500,
    "scenario.scenarios": 4,  # three current + one superseded revision
    "proposals.proposals": 1,  # one real saved example proposal — see seed_example_proposal()
    "proposals.routes": 1,
    "proposals.trips": 2,  # both directions of the one seeded proposal
    "proposals.stop_times": 6,  # 3 stops x 2 directions
}

# Tables added by the proposals redesign, schema phase 1 (2026-08-03,
# additive-only — see adapters/proposal/README.md §5 and
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
# the loader (SE nulls tac/parking intentionally; the 27 countries in
# _TRACK_INFRA_PLACEHOLDER_COUNTRIES null everything but country_code — see
# seed.py).
REQUIRED_COLUMNS = {
    "input_params.stop_infrastructures": [
        "stop_id",
        "stop_name",
        "country_code",
        "stop_lat",
        "stop_lon",
        "stop_provenance",
        "name_latin",
        "name_ascii",
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


def test_stop_catalog_snapshots(db_cur):
    """The stop catalog is complete at seed time and version-immutable:
    every stop_infra_version carries the identical stop set (the
    full-table-snapshot invariant the retired runtime mint used to
    violate — see db/ontd/stop_mapping.py's module docstring), and every
    stop carries the pipeline's provenance marker. A catalog that is empty
    or unmarked means the seed's Drive download of stop_seed_catalog.csv
    failed (its warning banner is in the container log), which would
    otherwise surface as baffling failures in test_20's auto-stop
    expectations."""
    db_cur.execute(
        "SELECT stop_infra_version, array_agg(stop_id ORDER BY stop_id) AS ids, "
        "       count(*) FILTER (WHERE change_log LIKE %s) AS n_seeded "
        "FROM input_params.stop_infrastructures GROUP BY stop_infra_version",
        (f"{STOP_SEED_CHANGE_LOG_PREFIX}%",),
    )
    rows = db_cur.fetchall()
    snapshots = {row["stop_infra_version"]: row["ids"] for row in rows}

    # Expected versions come from the scenario pins, not a literal: every
    # scenario owns a complete snapshot, so the set of pinned versions IS
    # the set that must exist. Hardcoding it meant adding a scenario broke
    # this test for the wrong reason.
    db_cur.execute(
        "SELECT DISTINCT stop_infrastructures_version AS v FROM scenario.scenarios"
    )
    pinned = {row["v"] for row in db_cur.fetchall()}
    assert set(snapshots) == pinned, (
        "stop snapshot versions do not match the versions scenarios pin — "
        "a scenario resolves to a snapshot that was never seeded, or a "
        "snapshot exists that nothing pins"
    )
    for row in rows:
        version, ids = row["stop_infra_version"], row["ids"]
        assert len(ids) == len(set(ids)), f"duplicate stop_ids in version {version}"
        assert row["n_seeded"] > 0, (
            f"version {version}: no stops carry the pipeline provenance "
            "marker — the seed's Drive download of stop_seed_catalog.csv "
            "failed (see the container log's warning banner) or the CSV "
            "is empty"
        )
        assert len(ids) == row["n_seeded"], (
            f"version {version}: {len(ids)} stops but only {row['n_seeded']} "
            "carry the seed provenance marker — an unmarked writer touched "
            "the catalog"
        )
    reference_version = min(snapshots)
    reference_ids = snapshots[reference_version]
    for version, ids in sorted(snapshots.items()):
        assert ids == reference_ids, (
            f"stop snapshot v{version} differs from v{reference_version} — "
            "the seed is the only writer and builds every version from one "
            "list, so this points at a runtime write into "
            "input_params.stop_infrastructures"
        )


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


# Known stop_provenance vocabulary — step 10's PROVENANCE_LABELS plus its
# fallback. A new category is a deliberate pipeline change and lands here too.
PROVENANCE_VOCABULARY = {
    "existing night train stop",
    "urban area currently without night train service",
    "tourism region currently without night train service",
    "ferry port currently without night train service",
    "border / interchange station",
    "network coherence addition",
    "manual addition",
}


def test_stop_enrichment_seeded(db_cur):
    """The catalog's enrichment actually lands in the DB: provenance from
    the known vocabulary, localized country names on every stop, a city on
    nearly all (rural halts excepted), and night-train-capable gauges on
    most (stops whose OSM object sits off the platforms excepted)."""
    db_cur.execute("""
        SELECT stop_provenance, country_de, country_it, city, city_it,
               gauges_mm
        FROM input_params.stop_infrastructures
        WHERE stop_infra_version = 1
        """)
    rows = db_cur.fetchall()
    assert rows

    bad_provenance = {r["stop_provenance"] for r in rows} - PROVENANCE_VOCABULARY
    assert bad_provenance == set(), f"unknown provenance: {bad_provenance}"

    assert all(r["country_de"] and r["country_it"] for r in rows), (
        "localized country names must be present on every stop"
    )

    with_city = sum(1 for r in rows if r["city"])
    assert with_city / len(rows) >= 0.95, (
        f"only {with_city}/{len(rows)} stops resolve a city — step 7's "
        "place fetch is incomplete (a failed Overpass country?)"
    )
    assert all(r["city_it"] for r in rows if r["city"]), (
        "a resolved city must carry its localized names"
    )

    with_gauges = [r for r in rows if r["gauges_mm"] is not None]
    assert len(with_gauges) / len(rows) >= 0.9, (
        f"only {len(with_gauges)}/{len(rows)} stops carry gauges — "
        "step 8 incomplete (a failed batch is resumable)"
    )
    narrow = [g for r in with_gauges for g in r["gauges_mm"] if g < 1435]
    assert narrow == [], (
        f"sub-1435 gauges seeded: {narrow} — the pipeline's night-train "
        "capability filter (step 8 MIN_GAUGE_MM) is not being applied"
    )


def test_stop_charge_carries_its_price_year(db_cur):
    """A charge without its price year cannot be inflated to the 2032
    target year like every other calibration in the project.

    Split out of test_stop_charge_carries_its_provenance so the rest of
    that test keeps guarding source, basis and the VAT arithmetic. Was a
    strict xfail while the catalogue carried 13 illustrative placeholder
    charges; the 2026-09-01 calibration run replaced them with the 105
    real German rows from the Stationspreisliste 2026, each with its
    price year, so the marker went as its own reason instructed."""
    db_cur.execute("""
        SELECT stop_id, stop_charge_price_basis_year
        FROM input_params.stop_infrastructures
        WHERE stop_charge_eur IS NOT NULL AND stop_infra_version = 1
        """)
    rows = db_cur.fetchall()
    if not rows:
        pytest.skip("no stop carries its own station charge yet")
    for row in rows:
        assert row["stop_charge_price_basis_year"], (
            f"{row['stop_id']}: a charge with no price year"
        )


def test_stop_charge_carries_its_provenance(db_cur):
    """A seeded charge brings the document it came from with it. Without
    that, a published figure cannot be traced back to a tariff, and the
    charge columns are indistinguishable from an invented number."""
    db_cur.execute("""
        SELECT stop_charge_eur, stop_charge_vat_rate_per,
               stop_charge_incl_vat_eur, stop_charge_basis,
               stop_charge_price_basis_year, stop_charge_source
        FROM input_params.stop_infrastructures
        WHERE stop_charge_eur IS NOT NULL AND stop_infra_version = 1
        """)
    rows = db_cur.fetchall()
    if not rows:
        pytest.skip(
            "no stop carries its own station charge yet — run the charge "
            "calibration (models/infrastructure/stops/charges) and re-export"
        )

    for row in rows:
        assert row["stop_charge_source"], "a charge with no source document"
        assert row["stop_charge_basis"], "a charge that is not per anything"
        # Net, rate and gross must still agree once through the database.
        if row["stop_charge_vat_rate_per"] is not None:
            net = float(row["stop_charge_eur"])
            rate = float(row["stop_charge_vat_rate_per"])
            gross = float(row["stop_charge_incl_vat_eur"])
            assert abs(net * (1 + rate / 100) - gross) < 0.01, row


def test_stop_gauge_break_of_gauge(db_cur):
    """Multi-gauge stops read like the break-of-gauge who's-who they are:
    Kaunas carries standard + Russian gauge."""
    db_cur.execute("""
        SELECT gauges_mm FROM input_params.stop_infrastructures
        WHERE stop_name = 'Kaunas' AND stop_infra_version = 1
        """)
    row = db_cur.fetchone()
    assert row is not None, "Kaunas missing from the catalog"
    assert row["gauges_mm"] == [1435, 1520]


def test_stop_uic_refs_survive_the_seed(db_cur):
    """uic_ref is OSM's tag verbatim, and that tag is multi-valued where a
    station holds more than one code (Paris CDG 2 TGV carries both the SNCF
    and the Transilien code). The column has to take the whole list: at
    VARCHAR(12) the 15-character value aborted the seed outright
    (2026-09-05). Each code is checked on its own, since a width that
    clipped the list would leave a short or empty one behind."""
    db_cur.execute("""
        SELECT stop_id, uic_ref FROM input_params.stop_infrastructures
        WHERE stop_infra_version = 1 AND uic_ref IS NOT NULL
        """)
    rows = db_cur.fetchall()
    assert rows, "no stop carries a uic_ref — step 7's OSM tag read came back empty"

    for row in rows:
        codes = [c.strip() for c in row["uic_ref"].split(";")]
        assert all(codes), f"{row['stop_id']}: empty code in {row['uic_ref']!r}"
        # A single code is 7 characters (a few stops carry a shorter national
        # number); anything longer means a list was stored where a code
        # belongs, not that one code grew.
        assert all(len(c) <= 12 for c in codes), (
            f"{row['stop_id']}: {row['uic_ref']!r} is not a list of codes"
        )


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
    """Both compute cache tables are UNLOGGED (adapters/proposal/README.md
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


def test_country_geometries_cover_maritime_zones(db_cur):
    """The border polygons must include maritime zones, not just land.

    This is the whole point of the Marine Regions EEZ land union: with
    land-only borders every belt and strait crossing fell outside all
    polygons and was attributed to the UNK sentinel, taking the real track
    on both approaches with it. Asserted on the Fehmarn Belt and the
    Øresund — the two crossings the seeded routes actually use — rather
    than on the source file, so a regression to a land-only dataset fails
    here regardless of where the geometry came from."""
    for country_code, lon, lat, where in (
        ("DK", 11.29, 54.58, "Fehmarn Belt"),
        ("SE", 12.85, 55.57, "Øresund"),
    ):
        db_cur.execute(
            """
            SELECT country_code
            FROM input_params.countries
            WHERE ST_Contains(country_geom, ST_SetSRID(ST_Point(%s, %s), 4326))
            """,
            (lon, lat),
        )
        matched = [row["country_code"] for row in db_cur.fetchall()]
        assert matched == [country_code], (
            f"{where} resolves to {matched or 'no country'}, expected "
            f"['{country_code}'] — country_geom looks land-only again."
        )


# =============================================================================
# Scenario seed consistency
# =============================================================================


# The five per-table pins every scenario carries — mirrors
# scenario.scenarios in db/schema.py.
_SCENARIO_VERSION_COLUMNS = (
    "track_infrastructures_version",
    "track_infrastructure_defaults_version",
    "stop_infrastructures_version",
    "stop_infrastructure_defaults_version",
    "passage_charges_version",
)


def test_exactly_one_current_base_scenario(db_cur):
    """Exactly one scenario carries is_current_base = TRUE — the partial
    unique index enforces at most one; the seed must supply exactly one."""
    db_cur.execute(
        "SELECT COUNT(*) AS n FROM scenario.scenarios WHERE is_current_base = TRUE"
    )
    assert db_cur.fetchone()["n"] == 1


def test_base_scenario_pins_version_1(base_scenario):
    """Infra 2026 is the live base and pins every table to version 1 —
    its own full snapshot, not a partial diff."""
    assert base_scenario["scenario_key"] == "infra-2026"
    for col in _SCENARIO_VERSION_COLUMNS:
        assert base_scenario[col] == 1


def test_hsr_scenario_pins_version_2(hsr_scenario, base_scenario):
    """The NT-on-HSR scenario pins all five infrastructure tables to
    version 2 — independent from base's version 1, per-table, even though
    only track_hsr_allowed actually differs in the underlying data."""
    for col in _SCENARIO_VERSION_COLUMNS:
        assert hsr_scenario[col] == 2
        assert hsr_scenario[col] != base_scenario[col]


def test_opt_tt_scenario_pins_version_3(opt_tt_scenario, base_scenario):
    """The optimised-timetable scenario pins all five tables to version 3,
    its own complete snapshot."""
    for col in _SCENARIO_VERSION_COLUMNS:
        assert opt_tt_scenario[col] == 3
        assert opt_tt_scenario[col] != base_scenario[col]


def test_superseded_revision_pins_version_4(historical_scenario, base_scenario):
    """The superseded infra-2026 revision owns a complete version-4
    snapshot and shares the base's scenario_key — one lineage, two
    revisions, only one of them current."""
    assert historical_scenario["scenario_key"] == base_scenario["scenario_key"]
    assert historical_scenario["is_current_scenario"] is False
    for col in _SCENARIO_VERSION_COLUMNS:
        assert historical_scenario[col] == 4


def test_scenario_key_and_routing_graph_agree(db_cur):
    """A scenario's key names the network its routing graph serves.

    The two are separate columns and nothing in the schema ties them
    together, so a copy-paste slip could pin infra-2032 to the 2026 graph
    and produce entirely plausible — and entirely wrong — numbers. This
    is the check that would catch it."""
    db_cur.execute("SELECT scenario_key, routing_graph_key FROM scenario.scenarios")
    for row in db_cur.fetchall():
        network = row["scenario_key"].split("-")[1]
        assert row["routing_graph_key"] == f"infra_{network}", (
            f"Scenario '{row['scenario_key']}' pins '{row['routing_graph_key']}'."
        )


def test_infra_2032_scenarios_pin_versions_5_to_7(scenarios_2032):
    """The 2032 trio pins versions 5, 6 and 7 across all five tables —
    one complete snapshot each, in the same operating-condition order as
    the 2026 trio's 1, 2, 3 (db/dev/seed.py's version grid)."""
    for scenario_key, expected in (
        ("infra-2032", 5),
        ("infra-2032-hsr", 6),
        ("infra-2032-hsr-opt-tt", 7),
    ):
        scenario = scenarios_2032[scenario_key]
        for col in _SCENARIO_VERSION_COLUMNS:
            assert scenario[col] == expected, (
                f"{scenario_key}.{col} = {scenario[col]}, expected {expected}"
            )


def test_infra_2032_scenarios_are_current_but_not_base(scenarios_2032):
    """All three are selectable lineage heads, and none of them displaces
    Infra 2026 as the live default."""
    for scenario in scenarios_2032.values():
        assert scenario["is_current_scenario"] is True
        assert scenario["is_current_base"] is False


def test_infra_2032_snapshots_copy_their_2026_counterparts(db_cur):
    """Versions 5-7 are exact copies of 1-3 in the versioned tables.

    What separates a 2032 scenario from its 2026 counterpart is the
    routing graph, not a value here — so any difference in this table
    means someone edited a snapshot in place, which the versioning
    contract forbids outright (db/README.md). Track infrastructure is
    the table to check: it is the only one whose values vary by operating
    condition at all, so a copy defect shows up here first."""
    db_cur.execute(
        """
        SELECT count(*) AS n FROM (
            SELECT country_code, track_hsr_allowed, track_buffer_quota_per,
                   track_tac_eur_train_km, track_infra_version - 4 AS src_version
            FROM input_params.track_infrastructures
            WHERE track_infra_version IN (5, 6, 7)
            EXCEPT
            SELECT country_code, track_hsr_allowed, track_buffer_quota_per,
                   track_tac_eur_train_km, track_infra_version
            FROM input_params.track_infrastructures
            WHERE track_infra_version IN (1, 2, 3)
        ) AS diff
        """
    )
    assert db_cur.fetchone()["n"] == 0, (
        "Infra 2032 track snapshots differ from their 2026 sources."
    )


def test_opt_tt_reduces_buffer_quota(db_cur, opt_tt_scenario, base_scenario):
    """The optimised-timetable snapshot carries a strictly lower schedule
    supplement than the base wherever the base sits above the benchmark,
    and never a higher one — the only numeric difference between the three
    seeded scenarios (models/scenarios/README.md)."""
    db_cur.execute(
        """
        SELECT b.country_code,
               b.track_buffer_quota_per AS base_quota,
               o.track_buffer_quota_per AS opt_quota
        FROM input_params.track_infrastructures b
        JOIN input_params.track_infrastructures o
          ON o.country_code = b.country_code
         AND o.track_infra_version = %s
        WHERE b.track_infra_version = %s
          AND b.track_buffer_quota_per IS NOT NULL
        """,
        (
            opt_tt_scenario["track_infrastructures_version"],
            base_scenario["track_infrastructures_version"],
        ),
    )
    rows = db_cur.fetchall()
    assert rows, "No country carries a buffer quota — seed data missing."
    assert any(r["opt_quota"] < r["base_quota"] for r in rows), (
        "No country's schedule supplement was reduced — the optimised "
        "timetable scenario is indistinguishable from the base."
    )
    for row in rows:
        assert row["opt_quota"] <= row["base_quota"], row["country_code"]


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
