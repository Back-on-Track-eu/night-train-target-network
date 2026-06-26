"""
test_loader.py
==============
Verifies the DBDataLoader produces correct output.

Two levels:
  Static  — SQL schema contains every column the loader tries to read.
  Runtime — loader output matches raw DB values for known rows.
"""

import re
import os
import pytest


# ---------------------------------------------------------------------------
# Static checks
# ---------------------------------------------------------------------------

def _parse_schema_columns() -> dict[str, set[str]]:
    sql_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "db", "dev", "sql"
    )
    tables: dict[str, set[str]] = {}
    for fname in os.listdir(sql_dir):
        if not fname.endswith(".sql"):
            continue
        src = open(os.path.join(sql_dir, fname), encoding="utf-8-sig").read()
        for match in re.finditer(
            r"CREATE TABLE (?:IF NOT EXISTS )?(\w+\.\w+)\s*\((.*?)\);",
            src, re.DOTALL | re.IGNORECASE
        ):
            table_name = match.group(1).lower()
            block = match.group(2)
            cols = re.findall(r"^\s{4}(\w+)\s+\w", block, re.MULTILINE)
            tables[table_name] = set(cols)
    return tables


SCHEMA_COLUMNS = _parse_schema_columns()


@pytest.mark.parametrize("table,column", [
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
    ("input_params.composition_types", "composition_type_purchase_loco_eur"),
    ("input_params.composition_types", "composition_type_purchase_coach_eur"),
    ("input_params.composition_types", "composition_type_loco_avail_per"),
    ("input_params.composition_types", "composition_type_coach_avail_per"),
    ("input_params.composition_types", "composition_type_loco_amort_years"),
    ("input_params.composition_types", "composition_type_coach_amort_years"),
    ("input_params.composition_types", "composition_type_cleaning_eur_day"),
    ("input_params.composition_types", "composition_type_loco_maint_eur_km"),
    ("input_params.composition_types", "composition_type_coach_maint_eur_km"),
    # operators
    ("input_params.operators", "operator_id"),
    ("input_params.operators", "operator_driver_costs_eur_h"),
    ("input_params.operators", "operator_crew_costs_eur_h"),
    ("input_params.operators", "operator_driver_overhead_h"),
    ("input_params.operators", "operator_crew_overhead_h"),
    ("input_params.operators", "operator_ebit_margin_per"),
    ("input_params.operators", "operator_financing_quota_per"),
    ("input_params.operators", "operator_shunting_eur_per_event"),
    ("input_params.operators", "operator_var_overhead_per"),
    ("input_params.operators", "operator_fix_overhead_quota_per"),
    # coach_types
    ("input_params.coach_types", "coach_type_id"),
    ("input_params.coach_types", "coach_type_weight_gross_t"),
    # coach_type_classes
    ("input_params.coach_type_classes", "coach_type_row_id"),
    ("input_params.coach_type_classes", "coach_type_class_places"),
    # composition_type_coaches
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
])
def test_column_exists_in_schema(table, column):
    """Every column the loader reads exists in the SQL schema."""
    table_lower = table.lower()
    assert table_lower in SCHEMA_COLUMNS, \
        f"Table {table} not found in schema files. Found: {sorted(SCHEMA_COLUMNS.keys())}"
    assert column in SCHEMA_COLUMNS[table_lower], \
        f"Column {table}.{column} not found in schema"


# ---------------------------------------------------------------------------
# Runtime checks
# ---------------------------------------------------------------------------

COMP_ID  = "STD-7.1"
COUNTRY  = "DE"
STOP_ID  = "DE_BERLIN_HBF"


def test_loader_composition_fields_match_db(loader, db_cur):
    """Composition built by loader matches raw DB values for key fields."""
    comp, _ = loader.build_composition(COMP_ID)

    db_cur.execute("""
        SELECT ct.*, op.operator_driver_costs_eur_h, op.operator_crew_costs_eur_h,
               op.operator_ebit_margin_per, op.operator_financing_quota_per
        FROM input_params.composition_types ct
        JOIN input_params.operators op ON op.operator_id = ct.composition_type_operator_id
        WHERE ct.composition_type_id = %s AND ct.is_current = TRUE
    """, (COMP_ID,))
    row = db_cur.fetchone()
    assert row is not None, f"No DB row found for composition '{COMP_ID}'"

    assert comp.comp_id         == row["composition_type_id"]
    assert comp.max_speed_kmh   == pytest.approx(float(row["composition_type_max_speed_kmh"]), rel=1e-4)
    assert comp.hsr_allowed     == row["composition_type_hsr_allowed"]
    assert comp.driver_costs_eur_h == pytest.approx(float(row["operator_driver_costs_eur_h"]), rel=1e-4)
    assert comp.ebit_margin_per == pytest.approx(float(row["operator_ebit_margin_per"]), rel=1e-4)


def test_loader_composition_capacity_aggregation(loader, db_cur):
    """places_by_class from loader matches direct DB aggregation."""
    comp, _ = loader.build_composition(COMP_ID)

    db_cur.execute("""
        SELECT ctc.service_class_id, SUM(ctc.coach_type_class_places) AS places
        FROM input_params.composition_types ct
        JOIN input_params.composition_type_coaches cc ON cc.composition_type_row_id = ct.composition_type_row_id
        JOIN input_params.coach_type_classes ctc      ON ctc.coach_type_row_id = cc.coach_type_row_id
        WHERE ct.composition_type_id = %s AND ct.is_current = TRUE
        GROUP BY ctc.service_class_id
    """, (COMP_ID,))
    rows = {row["service_class_id"]: int(row["places"]) for row in db_cur.fetchall()}

    for svc_class_id, expected_places in rows.items():
        assert comp.places_by_class.get(svc_class_id, 0) == expected_places, \
            f"places_by_class[{svc_class_id}] mismatch: loader={comp.places_by_class.get(svc_class_id)} db={expected_places}"


def test_loader_composition_weight_aggregation(loader, db_cur):
    """total_weight_t from loader matches SUM of coach weights from DB."""
    comp, _ = loader.build_composition(COMP_ID)

    db_cur.execute("""
        SELECT COALESCE(SUM(ct.coach_type_weight_gross_t), 0) AS weight
        FROM input_params.composition_types c
        JOIN input_params.composition_type_coaches cc ON cc.composition_type_row_id = c.composition_type_row_id
        JOIN input_params.coach_types ct              ON ct.coach_type_row_id = cc.coach_type_row_id
        WHERE c.composition_type_id = %s AND c.is_current = TRUE
    """, (COMP_ID,))
    row = db_cur.fetchone()
    assert comp.total_weight_t == pytest.approx(float(row["weight"]), rel=1e-4)


def test_loader_track_infra_fields_match_db(loader, db_cur):
    """TrackInfrastructure from loader matches raw DB values."""
    tracks, pv = loader.build_all_tracks()
    assert COUNTRY in tracks.all(), f"Country {COUNTRY} not in tracks collection"
    t = tracks.get(COUNTRY)

    db_cur.execute("""
        SELECT * FROM input_params.track_infrastructures
        WHERE country_code = %s AND is_current = TRUE
    """, (COUNTRY,))
    row = db_cur.fetchone()
    assert row is not None

    assert t.country_code         == row["country_code"]
    assert t.tac_eur_train_km     == pytest.approx(float(row["track_tac_eur_train_km"]), rel=1e-4)
    assert t.energy_price_eur_kwh == pytest.approx(float(row["track_energy_price_eur_kwh"]), rel=1e-4)
    assert t.hsr_allowed          == row["track_hsr_allowed"]
    assert t.terrain_category     == row["track_terrain_category"]

    # verify is_default=False for a country with explicit data
    entry = pv.get(f"track_infra:{COUNTRY}:tac_eur_train_km")
    assert entry is not None
    assert entry.is_default is False


def test_loader_stop_fields_match_db(loader, db_cur):
    """StopInfrastructure from loader matches raw DB values."""
    stops, pv = loader.build_all_stops()
    assert STOP_ID in stops.all(), f"Stop {STOP_ID} not in stops collection"
    s = stops.get(STOP_ID)

    db_cur.execute("""
        SELECT * FROM input_params.stop_infrastructures
        WHERE stop_id = %s AND is_current = TRUE
    """, (STOP_ID,))
    row = db_cur.fetchone()
    assert row is not None

    assert s.stop_id           == row["stop_id"]
    assert s.stop_name         == row["stop_name"]
    assert s.stop_country_code == row["country_code"]
    assert s.lat               == pytest.approx(float(row["stop_lat"]), rel=1e-4)
    assert s.lon               == pytest.approx(float(row["stop_lon"]), rel=1e-4)


def test_loader_all_compositions_load(loader):
    """All current compositions load without errors."""
    comps, _ = loader.build_all_compositions()
    assert len(comps) >= 1, f"Expected at least 1 composition, got {len(comps)}"


def test_loader_track_infra_default_resolves(loader, db_cur):
    """A country with NULL fields gets values from track_infrastructure_defaults."""
    # Find a country that has at least one NULL field
    db_cur.execute("""
        SELECT country_code FROM input_params.track_infrastructures
        WHERE is_current = TRUE AND track_tac_eur_train_km IS NULL
        LIMIT 1
    """)
    row = db_cur.fetchone()
    if row is None:
        pytest.skip("No country with NULL tac_eur_train_km in test data")

    tracks, pv = loader.build_all_tracks()
    cc = row["country_code"]
    assert tracks.get(cc) is not None

    entry = pv.get(f"track_infra:{cc}:tac_eur_train_km")
    assert entry is not None
    assert entry.is_default is True, \
        f"Expected is_default=True for country '{cc}' tac_eur_train_km"


def test_loader_composition_has_indicative_figures(loader):
    """Composition with a reference row has indicative figures."""
    comps, _ = loader.build_all_compositions()
    with_indicative = [c for c in comps.values() if c.indicative is not None]
    assert len(with_indicative) >= 1, \
        "Expected at least one composition with indicative figures"
    ind = with_indicative[0].indicative
    assert ind.cost_eur_per_seat_km  > 0
    assert ind.cost_eur_per_place_km > 0
    assert 0.0 <= ind.breakeven_load_factor <= 1.0


def test_loader_all_stops_load(loader):
    """All current stops load without errors."""
    stops, _ = loader.build_all_stops()
    assert len(stops.all()) >= 1, \
        f"Expected at least 1 stop, got {len(stops.all())}"