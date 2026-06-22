"""
test_loader.py
==============
Verifies the DBDataLoader produces correct output.

Two levels of checks:

  Static  — the SQL schema contains every column the loader tries to read.
            Catches mismatches early without running any loader code.

  Runtime — loader output matches raw DB values for a known composition,
            infra row, and stop. Catches mapping/conversion bugs.
"""

import re
import os
import pytest
from decimal import Decimal
from datetime import timedelta


# ---------------------------------------------------------------------------
# Static checks — columns the loader reads must exist in the schema
# ---------------------------------------------------------------------------

def _parse_schema_columns() -> dict[str, set[str]]:
    """
    Parse the SQL schema files and return a dict of
    {schema.table: {column_name, ...}} for quick lookup.
    """
    sql_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "db", "dev", "sql"
    )
    tables: dict[str, set[str]] = {}
    for fname in os.listdir(sql_dir):
        if not fname.endswith(".sql"):
            continue
        src = open(os.path.join(sql_dir, fname), encoding="utf-8-sig").read()
        # Find CREATE TABLE blocks
        for match in re.finditer(
            r"CREATE TABLE (\w+\.\w+)\s*\((.*?)\);", src, re.DOTALL
        ):
            table_name = match.group(1)
            block = match.group(2)
            cols = re.findall(r"^\s{4}(\w+)\s+\w", block, re.MULTILINE)
            tables[table_name] = set(cols)
    return tables


SCHEMA_COLUMNS = _parse_schema_columns()


@pytest.mark.parametrize("table,column", [
    # compositions
    ("input_params.compositions", "comp_row_id"),
    ("input_params.compositions", "comp_id"),
    ("input_params.compositions", "comp_operator_id"),
    ("input_params.compositions", "comp_hsr_allowed"),
    ("input_params.compositions", "comp_max_speed_kmh"),
    ("input_params.compositions", "comp_veh_min_boarding_time"),
    ("input_params.compositions", "comp_veh_min_alighting_time"),
    ("input_params.compositions", "comp_energy_factor_weight"),
    ("input_params.compositions", "comp_energy_factor_speed"),
    ("input_params.compositions", "comp_energy_factor_terrain"),
    ("input_params.compositions", "comp_purchase_loco_eur"),
    ("input_params.compositions", "comp_purchase_coach_eur"),
    ("input_params.compositions", "comp_loco_avail_per"),
    ("input_params.compositions", "comp_coach_avail_per"),
    ("input_params.compositions", "comp_loco_amort_years"),
    ("input_params.compositions", "comp_coach_amort_years"),
    ("input_params.compositions", "comp_cleaning_services_eur_day"),
    ("input_params.compositions", "comp_loco_maint_eur_km"),
    ("input_params.compositions", "comp_coach_maint_eur_km"),
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
    # coachtypes
    ("input_params.coachtypes", "coachtype_row_id"),
    ("input_params.coachtypes", "coachtype_weight_gross_t"),
    # coachtype_classes
    ("input_params.coachtype_classes", "coachtype_row_id"),
    ("input_params.coachtype_classes", "coachtype_class_places"),
    # composition_coaches
    ("input_params.composition_coaches", "comp_row_id"),
    ("input_params.composition_coaches", "position"),
    ("input_params.composition_coaches", "coachtype_row_id"),
    # infrastructure
    ("input_params.infrastructure", "country_code"),
    ("input_params.infrastructure", "infra_tac_eur_train_km"),
    ("input_params.infrastructure", "infra_parking_eur_day"),
    ("input_params.infrastructure", "infra_energy_price_eur_kwh"),
    ("input_params.infrastructure", "infra_terrain_category"),
    ("input_params.infrastructure", "infra_terrain_score"),
    ("input_params.infrastructure", "infra_hsr_allowed"),
    ("input_params.infrastructure", "infra_min_boarding_time_h"),
    ("input_params.infrastructure", "infra_min_alighting_time_h"),
    ("input_params.infrastructure", "infra_buffer_quota_per"),
    # stops
    ("input_params.stops", "stop_id"),
    ("input_params.stops", "stop_name"),
    ("input_params.stops", "stop_country_code"),
    ("input_params.stops", "stop_lat"),
    ("input_params.stops", "stop_lon"),
    ("input_params.stops", "stop_charge_eur"),
])
def test_column_exists_in_schema(table, column):
    """Every column the loader reads exists in the SQL schema."""
    assert table in SCHEMA_COLUMNS, f"Table {table} not found in schema files"
    assert column in SCHEMA_COLUMNS[table], \
        f"Column {table}.{column} not found in schema"


# ---------------------------------------------------------------------------
# Runtime checks — loader output matches raw DB values
# ---------------------------------------------------------------------------

COMP_ID = "STD-5.1"   # known composition in test seed
COUNTRY = "DE"         # known infrastructure country
STOP_ID = "DE_BERLIN_HBF"  # known stop


def test_loader_composition_fields_match_db(loader, db_cur):
    """
    CompositionParams built by loader matches raw DB values for key fields.
    """
    comp = loader.build_composition(COMP_ID)

    # Raw row from DB
    db_cur.execute("""
        SELECT c.*, op.operator_driver_costs_eur_h, op.operator_crew_costs_eur_h,
               op.operator_ebit_margin_per, op.operator_financing_quota_per
        FROM input_params.compositions c
        JOIN input_params.operators op ON op.operator_id = c.comp_operator_id
        WHERE c.comp_id = %s AND c.is_current = TRUE
    """, (COMP_ID,))
    row = db_cur.fetchone()

    assert comp.comp_id            == row["comp_id"]
    assert comp.max_speed_kmh      == pytest.approx(float(row["comp_max_speed_kmh"]), rel=1e-4)
    assert comp.hsr_allowed        == row["comp_hsr_allowed"]
    assert comp.driver_costs_eur_h == pytest.approx(float(row["operator_driver_costs_eur_h"]), rel=1e-4)
    assert comp.ebit_margin_per    == pytest.approx(float(row["operator_ebit_margin_per"]), rel=1e-4)

    # Boarding time: DB stores as INTERVAL, loader converts to decimal hours
    boarding_h = row["comp_veh_min_boarding_time"].total_seconds() / 3600
    assert comp.min_boarding_time_h == pytest.approx(boarding_h, rel=1e-4)


def test_loader_composition_capacity_aggregation(loader, db_cur):
    """
    Capacity totals built by loader match direct DB aggregation.
    """
    comp = loader.build_composition(COMP_ID)

    db_cur.execute("""
        SELECT
            COALESCE(SUM(CASE WHEN cl.class_main = 'Seat'      THEN cc.coachtype_class_places ELSE 0 END), 0) AS seats,
            COALESCE(SUM(CASE WHEN cl.class_main = 'Couchette' THEN cc.coachtype_class_places ELSE 0 END), 0) AS couchettes,
            COALESCE(SUM(CASE WHEN cl.class_main = 'Sleeper'   THEN cc.coachtype_class_places ELSE 0 END), 0) AS sleepers
        FROM input_params.compositions c
        JOIN input_params.composition_coaches co ON co.comp_row_id = c.comp_row_id
        JOIN input_params.coachtype_classes   cc ON cc.coachtype_row_id = co.coachtype_row_id
        JOIN input_params.classes             cl ON cl.class_id = cc.class_id
        WHERE c.comp_id = %s AND c.is_current = TRUE
          AND cl.class_main IN ('Seat', 'Couchette', 'Sleeper')
    """, (COMP_ID,))
    row = db_cur.fetchone()

    assert comp.seats_total      == int(row["seats"])
    assert comp.couchettes_total == int(row["couchettes"])
    assert comp.sleepers_total   == int(row["sleepers"])


def test_loader_composition_weight_aggregation(loader, db_cur):
    """
    Gross weight built by loader matches SUM of coach weights from DB.
    """
    comp = loader.build_composition(COMP_ID)

    db_cur.execute("""
        SELECT COALESCE(SUM(ct.coachtype_weight_gross_t), 0) AS weight
        FROM input_params.compositions c
        JOIN input_params.composition_coaches co ON co.comp_row_id = c.comp_row_id
        JOIN input_params.coachtypes ct ON ct.coachtype_row_id = co.coachtype_row_id
        WHERE c.comp_id = %s AND c.is_current = TRUE
    """, (COMP_ID,))
    row = db_cur.fetchone()

    assert comp.weight_gross_t == pytest.approx(float(row["weight"]), rel=1e-4)


def test_loader_infra_fields_match_db(loader, db_cur):
    """
    InfraParams built by loader matches raw DB values for key fields.
    """
    infra = loader.build_all_infra()
    assert COUNTRY in infra.all(), f"Country {COUNTRY} not in infra collection"
    ip = infra.get(COUNTRY)

    db_cur.execute("""
        SELECT * FROM input_params.infrastructure
        WHERE country_code = %s AND is_current = TRUE
    """, (COUNTRY,))
    row = db_cur.fetchone()

    assert ip.country_code         == row["country_code"]
    assert ip.tac_eur_train_km     == pytest.approx(float(row["infra_tac_eur_train_km"]), rel=1e-4)
    assert ip.energy_price_eur_kwh == pytest.approx(float(row["infra_energy_price_eur_kwh"]), rel=1e-4)
    assert ip.hsr_allowed          == row["infra_hsr_allowed"]
    assert ip.terrain_category     == row["infra_terrain_category"]

    boarding_h = row["infra_min_boarding_time_h"].total_seconds() / 3600
    assert ip.min_boarding_time_h  == pytest.approx(boarding_h, rel=1e-4)


def test_loader_stop_fields_match_db(loader, db_cur):
    """
    StopParams built by loader matches raw DB values.
    """
    stops = loader.build_all_stop_params([STOP_ID])
    assert STOP_ID in stops.all(), f"Stop {STOP_ID} not in stop collection"
    sp = stops.get(STOP_ID)

    db_cur.execute("""
        SELECT * FROM input_params.stops
        WHERE stop_id = %s AND is_current = TRUE
    """, (STOP_ID,))
    row = db_cur.fetchone()

    assert sp.stop_id           == row["stop_id"]
    assert sp.stop_name         == row["stop_name"]
    assert sp.stop_country_code == row["stop_country_code"]
    assert sp.lat               == pytest.approx(float(row["stop_lat"]), rel=1e-4)
    assert sp.lon               == pytest.approx(float(row["stop_lon"]), rel=1e-4)
    assert sp.stop_charge_eur   == pytest.approx(float(row["stop_charge_eur"] or 0), rel=1e-4)


def test_loader_all_compositions_load(loader):
    """All current compositions load without errors."""
    compositions = loader.build_all_compositions()
    assert len(compositions) == 10, \
        f"Expected 10 compositions, got {len(compositions)}"


def test_loader_infra_default_exists(loader):
    """InfraCollection includes a _default fallback row."""
    infra = loader.build_all_infra()
    assert "_default" in infra.all(), "No _default infra row found"


def test_loader_all_stops_load(loader):
    """All current stops load without errors."""
    stops = loader.build_all_stops()
    assert len(stops) == 8, \
        f"Expected 8 stops, got {len(stops)}"
