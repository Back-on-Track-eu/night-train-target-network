"""
Seeds the Back-on-Track night train database.

Only schema DDL (CREATE SCHEMA / CREATE TABLE) lives in sql/*.sql, loaded
via sql_loader. Every row of seed data is a plain Python list/dict below,
inserted through one generic psycopg2 helper (insert_rows) — no separate
.sql file per table, no hand-written INSERT statement per table.

Idempotent — each schema file starts with DROP SCHEMA ... CASCADE, so this
can be re-run freely while iterating.

Run order matters: admin must exist before proposals (proposals.proposals.
user_id is a cross-schema FK to admin.users), and compositions must exist
before the demo proposal (composition_row_id is a cross-schema FK into
input_params.compositions).
"""

import json
import os
from datetime import timezone, datetime, timedelta
from decimal import Decimal

import psycopg2
from dotenv import load_dotenv

load_dotenv()

from sql_loader import load_sql

DB_HOST     = os.environ.get("POSTGRES_HOST", "localhost")
DB_PORT     = os.environ.get("POSTGRES_PORT", "5432")
DB_NAME     = os.environ.get("POSTGRES_DB",   "night_train_db")
DB_USER     = os.environ.get("POSTGRES_USER",  "bot_admin")
DB_PASSWORD = os.environ.get("POSTGRES_PASSWORD")

MODEL_VERSION = "v1.0.0"


class _PgEncoder(json.JSONEncoder):
    """Handles types returned by psycopg2 that the stdlib encoder can't serialize."""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, timedelta):
            total = int(obj.total_seconds())
            h, rem = divmod(total, 3600)
            m, s   = divmod(rem, 60)
            return f"{h:02d}:{m:02d}:{s:02d}"
        return super().default(obj)


def _dumps(obj) -> str:
    return json.dumps(obj, cls=_PgEncoder)


def insert_rows(cur, table: str, rows: list[dict]) -> None:
    """Generic seeder: builds INSERT INTO table (...) VALUES (...) from
    each row dict's keys (assumed uniform across rows). dict/list values
    (JSONB columns) are auto-serialized."""
    if not rows:
        return
    columns = list(rows[0].keys())
    sql = (
        f"INSERT INTO {table} ({', '.join(columns)}) "
        f"VALUES ({', '.join(['%s'] * len(columns))})"
    )
    for row in rows:
        values = [
            _dumps(row[c]) if isinstance(row[c], (dict, list)) else row[c]
            for c in columns
        ]
        cur.execute(sql, values)


# ============================================================
# admin
# ============================================================

USERS = [
    {"email": "david@backontrack.eu"},
    {"email": "bjarne@backontrack.eu"},
]

# ============================================================
# input_params — sources
# ============================================================
# source_id values are assigned by SERIAL; we look them up after insert
# via fetch_source_ids() rather than hardcoding them.

SOURCES = [
    {
        "source_description": "B-o-T_targetnetwork_DB_v2.xlsx — illustrative placeholder values",
        "source_url":  None,
        "source_date": "2025-06-01",
    },
    {
        "source_description": "Illustrative / internal estimate",
        "source_url":  None,
        "source_date": None,
    },
]

# Symbolic names used below — resolved to real IDs after insert
SRC_EXCEL       = "B-o-T_targetnetwork_DB_v2.xlsx — illustrative placeholder values"
SRC_ILLUSTRATIVE = "Illustrative / internal estimate"


def fetch_source_ids(cur) -> dict[str, int]:
    """Returns {source_description: source_id} for all seeded sources."""
    cur.execute("SELECT source_id, source_description FROM input_params.sources")
    return {desc: sid for sid, desc in cur.fetchall()}


# ============================================================
# input_params — infrastructure
# ============================================================

STOP_DEFAULTS = [
    {"stop_default_key": "_default", "stop_charge_eur": 11.28},
]

INFRASTRUCTURE_DEFAULTS = [
    {
        "infra_default_key": "_default",
        "infra_tac_eur_train_km": 4.50, "infra_parking_eur_day": 65.00,
        "infra_energy_price_eur_kwh": 0.150, "infra_terrain_category": "Flat",
        "infra_terrain_score": 1.0, "infra_hsr_allowed": True,
        "infra_min_boarding_time_h": "00:02:00", "infra_min_alighting_time_h": "00:02:00",
        "infra_buffer_quota_per": 0.10,
    },
]

INFRASTRUCTURE = [
    {"country_code": "DE", "country_name": "Germany",     "infra_tac_eur_train_km": 5.40, "infra_parking_eur_day": 70.00, "infra_energy_price_eur_kwh": 0.142, "infra_terrain_category": "Flat",        "infra_terrain_score": 1.0, "infra_hsr_allowed": True, "infra_min_boarding_time_h": "00:02:00", "infra_min_alighting_time_h": "00:02:00", "infra_buffer_quota_per": 0.10},
    {"country_code": "AT", "country_name": "Austria",     "infra_tac_eur_train_km": 4.20, "infra_parking_eur_day": 60.00, "infra_energy_price_eur_kwh": 0.138, "infra_terrain_category": "Hilly",       "infra_terrain_score": 1.4, "infra_hsr_allowed": True, "infra_min_boarding_time_h": "00:02:00", "infra_min_alighting_time_h": "00:02:00", "infra_buffer_quota_per": 0.12},
    {"country_code": "CH", "country_name": "Switzerland", "infra_tac_eur_train_km": 6.80, "infra_parking_eur_day": 85.00, "infra_energy_price_eur_kwh": 0.165, "infra_terrain_category": "Mountainous", "infra_terrain_score": 1.8, "infra_hsr_allowed": True, "infra_min_boarding_time_h": "00:03:00", "infra_min_alighting_time_h": "00:03:00", "infra_buffer_quota_per": 0.15},
    {"country_code": "FR", "country_name": "France",      "infra_tac_eur_train_km": 4.60, "infra_parking_eur_day": 55.00, "infra_energy_price_eur_kwh": 0.130, "infra_terrain_category": "Flat",        "infra_terrain_score": 1.0, "infra_hsr_allowed": True, "infra_min_boarding_time_h": "00:02:00", "infra_min_alighting_time_h": "00:02:00", "infra_buffer_quota_per": 0.10},
    {"country_code": "BE", "country_name": "Belgium",     "infra_tac_eur_train_km": 5.10, "infra_parking_eur_day": 50.00, "infra_energy_price_eur_kwh": 0.145, "infra_terrain_category": "Flat",        "infra_terrain_score": 1.0, "infra_hsr_allowed": True, "infra_min_boarding_time_h": "00:02:00", "infra_min_alighting_time_h": "00:02:00", "infra_buffer_quota_per": 0.10},
    {"country_code": "DK", "country_name": "Denmark",     "infra_tac_eur_train_km": 4.80, "infra_parking_eur_day": 55.00, "infra_energy_price_eur_kwh": 0.128, "infra_terrain_category": "Flat",        "infra_terrain_score": 1.0, "infra_hsr_allowed": True, "infra_min_boarding_time_h": "00:02:00", "infra_min_alighting_time_h": "00:02:00", "infra_buffer_quota_per": 0.10},
    {"country_code": "SE", "country_name": "Sweden",      "infra_tac_eur_train_km": 4.30, "infra_parking_eur_day": 60.00, "infra_energy_price_eur_kwh": 0.090, "infra_terrain_category": "Hilly",       "infra_terrain_score": 1.2, "infra_hsr_allowed": True, "infra_min_boarding_time_h": "00:02:00", "infra_min_alighting_time_h": "00:02:00", "infra_buffer_quota_per": 0.10},
]

STOPS = [
    {"stop_id": "DE_BERLIN_HBF",  "stop_name": "Berlin Hbf",          "stop_country_code": "DE", "stop_timezone": "Europe/Berlin",     "stop_lat": 52.525, "stop_lon": 13.369, "stop_charge_eur": 9.80},
    {"stop_id": "DE_DRESDEN_HBF", "stop_name": "Dresden Hbf",         "stop_country_code": "DE", "stop_timezone": "Europe/Berlin",     "stop_lat": 51.040, "stop_lon": 13.732, "stop_charge_eur": 6.50},
    {"stop_id": "AT_WIEN_HBF",    "stop_name": "Wien Hbf",            "stop_country_code": "AT", "stop_timezone": "Europe/Vienna",     "stop_lat": 48.185, "stop_lon": 16.376, "stop_charge_eur": 11.00},
    {"stop_id": "CH_ZUERICH_HB",  "stop_name": "Zuerich HB",          "stop_country_code": "CH", "stop_timezone": "Europe/Zurich",     "stop_lat": 47.378, "stop_lon": 8.540,  "stop_charge_eur": 14.50},
    {"stop_id": "FR_PARIS_EST",   "stop_name": "Paris Gare de l'Est", "stop_country_code": "FR", "stop_timezone": "Europe/Paris",      "stop_lat": 48.877, "stop_lon": 2.359,  "stop_charge_eur": 13.20},
    {"stop_id": "BE_BRUSSELS_M",  "stop_name": "Bruxelles-Midi",      "stop_country_code": "BE", "stop_timezone": "Europe/Brussels",   "stop_lat": 50.836, "stop_lon": 4.336,  "stop_charge_eur": 10.40},
    {"stop_id": "DK_COPENHAGEN",  "stop_name": "Koebenhavn H",        "stop_country_code": "DK", "stop_timezone": "Europe/Copenhagen", "stop_lat": 55.673, "stop_lon": 12.565, "stop_charge_eur": 9.00},
    {"stop_id": "SE_STOCKHOLM_C", "stop_name": "Stockholm C",         "stop_country_code": "SE", "stop_timezone": "Europe/Stockholm",  "stop_lat": 59.330, "stop_lon": 18.058, "stop_charge_eur": 8.50},
]

CLASSES = [
    {"class_id": "seat (reclining)",                          "class_main": "Seat"},
    {"class_id": "seat (compartment)",                        "class_main": "Seat"},
    {"class_id": "seat (large room)",                         "class_main": "Seat"},
    {"class_id": "seat (spare)",                              "class_main": "Seat"},
    {"class_id": "seat (playzone)",                           "class_main": "Seat"},
    {"class_id": "seat PRM",                                  "class_main": "Seat"},
    {"class_id": "couchette (4-berth)",                       "class_main": "Couchette"},
    {"class_id": "couchette (5-berth)",                       "class_main": "Couchette"},
    {"class_id": "couchette (6-berth)",                       "class_main": "Couchette"},
    {"class_id": "couchette (large room)",                    "class_main": "Couchette"},
    {"class_id": "couchette PRM (2-berth)",                   "class_main": "Couchette"},
    {"class_id": "Capsule (1-bed) with seat",                 "class_main": "Capsule"},
    {"class_id": "Capsule (2-bed) with seats",                "class_main": "Capsule"},
    {"class_id": "Capsule (double) with seats",               "class_main": "Capsule"},
    {"class_id": "Capsule (3-bed) with seats",                "class_main": "Capsule"},
    {"class_id": "Mini-Cabin (bed)",                          "class_main": "Capsule"},
    {"class_id": "Sleeper (2-berth) with shower & WC",        "class_main": "Sleeper"},
    {"class_id": "Sleeper (2-berth) with shower option & WC", "class_main": "Sleeper"},
    {"class_id": "Sleeper (double) with shower & WC",         "class_main": "Sleeper"},
    {"class_id": "Sleeper (3-berth) with shower & WC",        "class_main": "Sleeper"},
    {"class_id": "Sleeper (2-berth) with basin",              "class_main": "Sleeper"},
    {"class_id": "Sleeper (3-berth) with basin",              "class_main": "Sleeper"},
    {"class_id": "Sleeper (4-berth) with basin",              "class_main": "Sleeper"},
    {"class_id": "Sleeper PRM (2-berth)",                     "class_main": "Sleeper"},
    {"class_id": "Sleeper PRM (double)",                      "class_main": "Sleeper"},
    {"class_id": "Sleeper PRM (single)",                      "class_main": "Sleeper"},
    {"class_id": "Catering",                                  "class_main": "Catering"},
]

OPERATORS = [
    {
        "operator_id":                     "STD",
        "operator_name":                   "Standard (illustrative)",
        "operator_driver_costs_eur_h":     52.00,
        "operator_crew_costs_eur_h":       38.00,
        "operator_driver_overhead_h":      "01:00:00",
        "operator_crew_overhead_h":        "01:00:00",
        "operator_ebit_margin_per":        0.03,
        "operator_financing_quota_per":    0.04,
        "operator_shunting_eur_per_event": 575.932,
        "operator_var_overhead_per":       0.10,
        "operator_fix_overhead_quota_per": 0.15,
    },
]

OPERATOR_CLASS_COSTS_RAW = [
    ("STD", "seat (reclining)",                          0.01),
    ("STD", "seat (compartment)",                        0.01),
    ("STD", "seat (large room)",                         0.01),
    ("STD", "seat (spare)",                              0.01),
    ("STD", "seat (playzone)",                           0.01),
    ("STD", "seat PRM",                                  0.01),
    ("STD", "couchette (4-berth)",                       0.05),
    ("STD", "couchette (5-berth)",                       0.05),
    ("STD", "couchette (6-berth)",                       0.05),
    ("STD", "couchette (large room)",                    0.05),
    ("STD", "couchette PRM (2-berth)",                   0.05),
    ("STD", "Sleeper (2-berth) with shower & WC",        0.10),
    ("STD", "Sleeper (2-berth) with shower option & WC", 0.10),
    ("STD", "Sleeper (double) with shower & WC",         0.10),
    ("STD", "Sleeper (3-berth) with shower & WC",        0.10),
    ("STD", "Sleeper (2-berth) with basin",              0.10),
    ("STD", "Sleeper (3-berth) with basin",              0.10),
    ("STD", "Sleeper (4-berth) with basin",              0.10),
    ("STD", "Sleeper PRM (2-berth)",                     0.10),
    ("STD", "Sleeper PRM (double)",                      0.10),
    ("STD", "Sleeper PRM (single)",                      0.10),
]

COACHTYPES = [
    {"coachtype_id": "type1", "coachtype_operator_id": "STD", "coachtype_weight_gross_t": 52.00, "coachtype_bikes": 0, "coachtype_climatization": True,  "coachtype_plugs": True,  "coachtype_crew_factor": 0.5, "coachtype_remarks": "STD seat coach — 80 reclining seats"},
    {"coachtype_id": "type2", "coachtype_operator_id": "STD", "coachtype_weight_gross_t": 50.70, "coachtype_bikes": 0, "coachtype_climatization": True,  "coachtype_plugs": False, "coachtype_crew_factor": 0.5, "coachtype_remarks": "STD couchette coach — 48 couchette (6-berth) places"},
    {"coachtype_id": "type3", "coachtype_operator_id": "STD", "coachtype_weight_gross_t": 55.50, "coachtype_bikes": 0, "coachtype_climatization": True,  "coachtype_plugs": True,  "coachtype_crew_factor": 1.0, "coachtype_remarks": "STD sleeper coach — 24 sleeper berths (2-berth with shower & WC)"},
]

COACHTYPE_CLASSES_RAW = [
    ("type1", "seat (reclining)",                  80),
    ("type2", "couchette (6-berth)",               48),
    ("type3", "Sleeper (2-berth) with shower & WC", 24),
]

STD_COMPANY_DEFAULTS = dict(
    hsr_allowed=True, max_speed_kmh=230,
    energy_factor_weight=0.000168, energy_factor_speed=0.015123, energy_factor_terrain=0.034545,
    veh_min_boarding_time="00:02:00", veh_min_alighting_time="00:02:00",
    purchase_loco_eur=24500000.00, purchase_coach_eur=20000000.00,
    loco_avail_per=0.85, coach_avail_per=0.80, loco_amort_years=25, coach_amort_years=30,
    cleaning_services_eur_day=1753.584,
    loco_maint_eur_km=2.86533333, coach_maint_eur_km=2.86533333,
    driver_factor=1.0,
)

COMPOSITIONS_VARYING = [
    ("STD-3.1",  "Standard 3 coach composition"),
    ("STD-4.1",  "Standard 4 coach composition v1"),
    ("STD-4.2",  "Standard 4 coach composition v2"),
    ("STD-5.1",  "Standard 5 coach composition v1"),
    ("STD-5.2",  "Standard 5 coach composition v2"),
    ("STD-6.1",  "Standard 6 coach composition v1"),
    ("STD-6.2",  "Standard 6 coach composition v2"),
    ("STD-7.1",  "Standard 7 coach composition"),
    ("STD-9.1",  "Standard 9 coach composition"),
    ("STD-13.1", "Standard 13 coach composition"),
]


def build_compositions() -> list[dict]:
    d = STD_COMPANY_DEFAULTS
    return [
        {
            "comp_id": comp_id, "comp_description": description,
            "comp_operator_id":              "STD",
            "comp_hsr_allowed":              d["hsr_allowed"],
            "comp_max_speed_kmh":            d["max_speed_kmh"],
            "comp_energy_factor_weight":     d["energy_factor_weight"],
            "comp_energy_factor_speed":      d["energy_factor_speed"],
            "comp_energy_factor_terrain":    d["energy_factor_terrain"],
            "comp_veh_min_boarding_time":    d["veh_min_boarding_time"],
            "comp_veh_min_alighting_time":   d["veh_min_alighting_time"],
            "comp_purchase_loco_eur":        d["purchase_loco_eur"],
            "comp_purchase_coach_eur":       d["purchase_coach_eur"],
            "comp_loco_avail_per":           d["loco_avail_per"],
            "comp_coach_avail_per":          d["coach_avail_per"],
            "comp_loco_amort_years":         d["loco_amort_years"],
            "comp_coach_amort_years":        d["coach_amort_years"],
            "comp_cleaning_services_eur_day": d["cleaning_services_eur_day"],
            "comp_loco_maint_eur_km":        d["loco_maint_eur_km"],
            "comp_coach_maint_eur_km":       d["coach_maint_eur_km"],
            "comp_driver_factor":            d["driver_factor"],
        }
        for comp_id, description in COMPOSITIONS_VARYING
    ]


COMPOSITION_COACHES_RAW = [
    ("STD-3.1",  1, "type2"), ("STD-3.1",  2, "type2"), ("STD-3.1",  3, "type2"),
    ("STD-4.1",  1, "type1"), ("STD-4.1",  2, "type2"), ("STD-4.1",  3, "type2"), ("STD-4.1",  4, "type2"),
    ("STD-4.2",  1, "type2"), ("STD-4.2",  2, "type2"), ("STD-4.2",  3, "type2"), ("STD-4.2",  4, "type2"),
    ("STD-5.1",  1, "type1"), ("STD-5.1",  2, "type2"), ("STD-5.1",  3, "type2"), ("STD-5.1",  4, "type2"), ("STD-5.1",  5, "type3"),
    ("STD-5.2",  1, "type2"), ("STD-5.2",  2, "type2"), ("STD-5.2",  3, "type2"), ("STD-5.2",  4, "type2"), ("STD-5.2",  5, "type3"),
    ("STD-6.1",  1, "type1"), ("STD-6.1",  2, "type2"), ("STD-6.1",  3, "type2"), ("STD-6.1",  4, "type2"), ("STD-6.1",  5, "type2"), ("STD-6.1",  6, "type3"),
    ("STD-6.2",  1, "type2"), ("STD-6.2",  2, "type2"), ("STD-6.2",  3, "type2"), ("STD-6.2",  4, "type2"), ("STD-6.2",  5, "type2"), ("STD-6.2",  6, "type3"),
    ("STD-7.1",  1, "type1"), ("STD-7.1",  2, "type1"), ("STD-7.1",  3, "type2"), ("STD-7.1",  4, "type2"), ("STD-7.1",  5, "type2"), ("STD-7.1",  6, "type3"), ("STD-7.1",  7, "type3"),
    ("STD-9.1",  1, "type1"), ("STD-9.1",  2, "type1"), ("STD-9.1",  3, "type2"), ("STD-9.1",  4, "type2"), ("STD-9.1",  5, "type2"), ("STD-9.1",  6, "type2"), ("STD-9.1",  7, "type2"), ("STD-9.1",  8, "type3"), ("STD-9.1",  9, "type3"),
    ("STD-13.1",  1, "type1"), ("STD-13.1",  2, "type1"), ("STD-13.1",  3, "type2"), ("STD-13.1",  4, "type2"), ("STD-13.1",  5, "type2"), ("STD-13.1",  6, "type2"), ("STD-13.1",  7, "type2"), ("STD-13.1",  8, "type2"), ("STD-13.1",  9, "type2"), ("STD-13.1", 10, "type3"), ("STD-13.1", 11, "type3"), ("STD-13.1", 12, "type3"), ("STD-13.1", 13, "type3"),
]

# ============================================================
# proposals
# ============================================================

SERVICES     = [{"service_id": "NJ-BER-VIE-DAILY"}]
CALENDAR     = [{"service_id": "NJ-BER-VIE-DAILY", "monday": True, "tuesday": True, "wednesday": True, "thursday": True, "friday": True, "saturday": True, "sunday": True, "start_date": "2026-12-13", "end_date": "2027-12-11"}]
CALENDAR_DATES = [{"service_id": "NJ-BER-VIE-DAILY", "date": "2026-12-24", "exception_type": 2}]
SHAPES       = [{"shape_id": "NJ-BER-VIE-SHAPE", "geometry": {"type": "LineString", "coordinates": [[13.369, 52.525], [13.732, 51.040], [16.376, 48.185]]}, "length_km": 683.4}]
ROUTES       = [{"route_id": "NJ-BER-VIE", "agency_id": None, "route_short_name": "NJ 470", "route_long_name": "Berlin Hbf - Vienna Hbf", "route_type": 105}]
TRIPS        = [{"trip_id": "NJ-BER-VIE-OUTBOUND", "route_id": "NJ-BER-VIE", "service_id": "NJ-BER-VIE-DAILY", "shape_id": "NJ-BER-VIE-SHAPE", "trip_headsign": "Wien Hbf", "direction_id": 0, "composition_id": "STD-3.1"}]
STOP_TIMES   = [
    {"trip_id": "NJ-BER-VIE-OUTBOUND", "stop_sequence": 1, "stop_id": "DE_BERLIN_HBF",  "arrival_time": "21:04:00", "departure_time": "21:04:00"},
    {"trip_id": "NJ-BER-VIE-OUTBOUND", "stop_sequence": 2, "stop_id": "DE_DRESDEN_HBF", "arrival_time": "22:47:00", "departure_time": "22:52:00"},
    {"trip_id": "NJ-BER-VIE-OUTBOUND", "stop_sequence": 3, "stop_id": "AT_WIEN_HBF",    "arrival_time": "30:30:00", "departure_time": "30:30:00"},
]

# ============================================================
# FK-resolving seed helpers
# ============================================================

def seed_sources(cur, source_ids: dict) -> None:
    """Inject source_id into all versioned parameter rows after sources are seeded."""
    excel_id       = source_ids[SRC_EXCEL]
    illustrative_id = source_ids[SRC_ILLUSTRATIVE]

    cur.execute("UPDATE input_params.stop_defaults   SET source_id = %s", (illustrative_id,))
    cur.execute("UPDATE input_params.infrastructure_defaults SET source_id = %s", (illustrative_id,))
    cur.execute("UPDATE input_params.infrastructure  SET source_id = %s", (illustrative_id,))
    cur.execute("UPDATE input_params.stops           SET source_id = %s", (illustrative_id,))
    cur.execute("UPDATE input_params.operators       SET source_id = %s", (illustrative_id,))
    cur.execute("UPDATE input_params.coachtypes      SET source_id = %s", (illustrative_id,))
    cur.execute("UPDATE input_params.coachtype_classes SET source_id = %s", (excel_id,))
    cur.execute("UPDATE input_params.compositions    SET source_id = %s", (excel_id,))
    cur.execute("UPDATE input_params.operator_class_costs SET source_id = %s", (illustrative_id,))


def seed_operator_class_costs(cur):
    for operator_id, class_id, eur_place in OPERATOR_CLASS_COSTS_RAW:
        cur.execute(
            """INSERT INTO input_params.operator_class_costs
               (operator_id, class_id, operator_class_svc_stockings_eur_place)
               VALUES (%s, %s, %s)""",
            (operator_id, class_id, eur_place),
        )


def seed_coachtype_classes(cur):
    for coachtype_id, class_id, places in COACHTYPE_CLASSES_RAW:
        cur.execute(
            "SELECT coachtype_row_id FROM input_params.coachtypes WHERE coachtype_id = %s AND is_current",
            (coachtype_id,),
        )
        coachtype_row_id = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO input_params.coachtype_classes
               (coachtype_row_id, class_id, coachtype_class_places) VALUES (%s, %s, %s)""",
            (coachtype_row_id, class_id, places),
        )


def seed_composition_coaches(cur):
    for comp_id, position, coachtype_id in COMPOSITION_COACHES_RAW:
        cur.execute(
            "SELECT comp_row_id FROM input_params.compositions WHERE comp_id = %s AND is_current",
            (comp_id,),
        )
        comp_row_id = cur.fetchone()[0]
        cur.execute(
            "SELECT coachtype_row_id FROM input_params.coachtypes WHERE coachtype_id = %s AND is_current",
            (coachtype_id,),
        )
        coachtype_row_id = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO input_params.composition_coaches
               (comp_row_id, position, coachtype_row_id) VALUES (%s, %s, %s)""",
            (comp_row_id, position, coachtype_row_id),
        )


# ============================================================
# Parameter snapshot assembly
# ============================================================

def fetch_col_comments(cur, schema: str, table: str) -> dict[str, str]:
    """Returns {column_name: comment} for all commented columns in a table."""
    cur.execute("""
        SELECT a.attname, col_description(c.oid, a.attnum)
        FROM   pg_class c
        JOIN   pg_namespace n ON n.oid = c.relnamespace
        JOIN   pg_attribute a ON a.attrelid = c.oid
        WHERE  n.nspname = %s AND c.relname = %s
          AND  a.attnum > 0 AND NOT a.attisdropped
          AND  col_description(c.oid, a.attnum) IS NOT NULL
        ORDER BY a.attnum
    """, (schema, table))
    return {name: comment for name, comment in cur.fetchall()}


def resolve_source(cur, row_source_id, column_sources: dict | None, col_name: str) -> dict | None:
    """Returns {source_id, source_description, source_date} for a specific column,
    using the column-level override if present, otherwise the row-level default."""
    sid = (column_sources or {}).get(col_name) or row_source_id
    if sid is None:
        return None
    cur.execute(
        "SELECT source_id, source_description, source_date FROM input_params.sources WHERE source_id = %s",
        (sid,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return {"source_id": row[0], "source_description": row[1], "source_date": str(row[2]) if row[2] else None}


def build_param_block(cur, schema: str, table: str, row: dict,
                      exclude_cols: set | None = None) -> dict:
    """Builds the params sub-object for a snapshot block: each column maps to
    {value, comment, source_id, source_description, source_date}."""
    comments       = fetch_col_comments(cur, schema, table)
    row_source_id  = row.get("source_id")
    column_sources = row.get("column_sources") or {}
    skip = (exclude_cols or set()) | {
        "source_id", "column_sources", "created_at", "is_current",
    }
    params = {}
    for col, value in row.items():
        if col in skip or value is None:
            continue
        source = resolve_source(cur, row_source_id, column_sources, col)
        entry  = {"value": value, "comment": comments.get(col)}
        if source:
            entry.update(source)
        params[col] = entry
    return params


def build_parameter_snapshot(cur, composition_id: str,
                              route_stop_ids: list[str],
                              route_country_codes: list[str]) -> dict:
    """Assembles the full parameter snapshot for a proposal evaluation.

    Only includes parameters actually used for this route:
    - the chosen composition and its operator
    - infrastructure rows for countries the route passes through
    - stop rows for stops on this route
    - coachtypes used by this composition
    - operator_class_costs for classes present in those coachtypes
    """
    snapshot: dict = {
        "model_version": MODEL_VERSION,
        "generated_at":  datetime.now(timezone.utc).isoformat(),
    }

    # --- composition ---
    cur.execute("""
        SELECT * FROM input_params.compositions
        WHERE comp_id = %s AND is_current
    """, (composition_id,))
    cols = [d[0] for d in cur.description]
    comp_row = dict(zip(cols, cur.fetchone()))

    snapshot["composition"] = {
        "comp_id":      comp_row["comp_id"],
        "comp_row_id":  comp_row["comp_row_id"],
        "comp_version": comp_row["comp_version"],
        **_source_header(cur, comp_row),
        "params": build_param_block(cur, "input_params", "compositions", comp_row,
                                    exclude_cols={"comp_row_id", "comp_id", "comp_version", "comp_operator_id", "comp_description"}),
    }

    # --- operator ---
    cur.execute("""
        SELECT * FROM input_params.operators WHERE operator_id = %s
    """, (comp_row["comp_operator_id"],))
    cols = [d[0] for d in cur.description]
    op_row = dict(zip(cols, cur.fetchone()))

    snapshot["operator"] = {
        "operator_id": op_row["operator_id"],
        **_source_header(cur, op_row),
        "params": build_param_block(cur, "input_params", "operators", op_row,
                                    exclude_cols={"operator_id", "operator_name"}),
    }

    # --- operator_class_costs (only classes present in the composition's coachtypes) ---
    cur.execute("""
        SELECT DISTINCT ctc.class_id
        FROM   input_params.composition_coaches cc
        JOIN   input_params.coachtypes ct   ON ct.coachtype_row_id = cc.coachtype_row_id
        JOIN   input_params.coachtype_classes ctc ON ctc.coachtype_row_id = ct.coachtype_row_id
        JOIN   input_params.compositions c  ON c.comp_row_id = cc.comp_row_id
        WHERE  c.comp_id = %s AND c.is_current
    """, (composition_id,))
    class_ids = [r[0] for r in cur.fetchall()]

    occ_blocks = []
    for class_id in class_ids:
        cur.execute("""
            SELECT * FROM input_params.operator_class_costs
            WHERE operator_id = %s AND class_id = %s
        """, (op_row["operator_id"], class_id))
        cols = [d[0] for d in cur.description]
        occ_row = cur.fetchone()
        if occ_row:
            occ_row = dict(zip(cols, occ_row))
            occ_blocks.append({
                "class_id": class_id,
                **_source_header(cur, occ_row),
                "params": build_param_block(cur, "input_params", "operator_class_costs", occ_row,
                                            exclude_cols={"operator_id", "class_id"}),
            })
    snapshot["operator_class_costs"] = occ_blocks

    # --- infrastructure (only countries this route passes through) ---
    infra_blocks = []
    for country_code in route_country_codes:
        cur.execute("""
            SELECT * FROM input_params.infrastructure
            WHERE country_code = %s AND is_current
        """, (country_code,))
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
        if row:
            row = dict(zip(cols, row))
            infra_blocks.append({
                "country_code":  row["country_code"],
                "infra_row_id":  row["infra_row_id"],
                "infra_version": row["infra_version"],
                **_source_header(cur, row),
                "params": build_param_block(cur, "input_params", "infrastructure", row,
                                            exclude_cols={"infra_row_id", "country_code", "country_name", "infra_version"}),
            })
    snapshot["infrastructure"] = infra_blocks

    # --- stops (only stops on this route) ---
    stop_blocks = []
    for stop_id in route_stop_ids:
        cur.execute("""
            SELECT * FROM input_params.stops
            WHERE stop_id = %s AND is_current
        """, (stop_id,))
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
        if row:
            row = dict(zip(cols, row))
            stop_blocks.append({
                "stop_id":      row["stop_id"],
                "stop_row_id":  row["stop_row_id"],
                "stop_version": row["stop_version"],
                **_source_header(cur, row),
                "params": build_param_block(cur, "input_params", "stops", row,
                                            exclude_cols={"stop_row_id", "stop_id", "stop_version", "stop_name", "stop_country_code", "stop_timezone"}),
            })
    snapshot["stops"] = stop_blocks

    # --- coachtypes (distinct types used by this composition) ---
    cur.execute("""
        SELECT DISTINCT ct.*
        FROM   input_params.composition_coaches cc
        JOIN   input_params.coachtypes ct  ON ct.coachtype_row_id = cc.coachtype_row_id
        JOIN   input_params.compositions c ON c.comp_row_id = cc.comp_row_id
        WHERE  c.comp_id = %s AND c.is_current
        ORDER  BY ct.coachtype_id
    """, (composition_id,))
    cols = [d[0] for d in cur.description]
    ct_rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    coachtype_blocks = []
    for ct_row in ct_rows:
        # class breakdown for this coachtype
        cur.execute("""
            SELECT ctc.*, cl.class_main
            FROM   input_params.coachtype_classes ctc
            JOIN   input_params.classes cl ON cl.class_id = ctc.class_id
            WHERE  ctc.coachtype_row_id = %s
        """, (ct_row["coachtype_row_id"],))
        ctc_cols = [d[0] for d in cur.description]
        class_breakdown = [dict(zip(ctc_cols, r)) for r in cur.fetchall()]

        coachtype_blocks.append({
            "coachtype_id":      ct_row["coachtype_id"],
            "coachtype_row_id":  ct_row["coachtype_row_id"],
            "coachtype_version": ct_row["coachtype_version"],
            **_source_header(cur, ct_row),
            "params": build_param_block(cur, "input_params", "coachtypes", ct_row,
                                        exclude_cols={"coachtype_row_id", "coachtype_id", "coachtype_version", "coachtype_operator_id", "coachtype_remarks"}),
            "class_breakdown": [
                {
                    "class_id":   r["class_id"],
                    "class_main": r["class_main"],
                    "places":     r["coachtype_class_places"],
                    **_source_header(cur, r),
                }
                for r in class_breakdown
            ],
        })
    snapshot["coachtypes"] = coachtype_blocks

    return snapshot


def _source_header(cur, row: dict) -> dict:
    """Extracts source_id, source_description, source_date from a parameter row."""
    sid = row.get("source_id")
    if not sid:
        return {}
    cur.execute(
        "SELECT source_description, source_date FROM input_params.sources WHERE source_id = %s",
        (sid,),
    )
    r = cur.fetchone()
    if not r:
        return {}
    return {
        "source_id":          sid,
        "source_description": r[0],
        "source_date":        str(r[1]) if r[1] else None,
    }


# ============================================================
# Proposal save
# ============================================================

def save_proposal(cur, route_id, user_id, composition_id, model_result: dict,
                  route_stop_ids: list[str], route_country_codes: list[str]):
    cur.execute(
        "SELECT comp_row_id FROM input_params.compositions WHERE comp_id = %s AND is_current",
        (composition_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"No current composition found for comp_id={composition_id!r}")
    composition_row_id = row[0]

    cur.execute(
        "SELECT COALESCE(MAX(version), 0) + 1 FROM proposals.proposals WHERE route_id = %s",
        (route_id,),
    )
    next_version = cur.fetchone()[0]

    cur.execute(
        "UPDATE proposals.proposals SET is_current = FALSE WHERE route_id = %s AND is_current",
        (route_id,),
    )

    snapshot = build_parameter_snapshot(cur, composition_id, route_stop_ids, route_country_codes)

    cur.execute(
        """
        INSERT INTO proposals.proposals (
            route_id, version, user_id, composition_row_id,
            total_distance_km, total_driving_time_h,
            air_shift_flights, air_shift_seats, air_shift_seat_km,
            co2_reduction_t_co2e, subsidy_per_seat_km_eur, subsidy_per_t_co2e_eur,
            total_revenue_eur, total_cost_eur, margin_eur, margin_per,
            capacity_breakdown, revenue_breakdown, cost_breakdown,
            parameter_snapshot
        ) VALUES (
            %s, %s, %s, %s,
            %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s,
            %s
        )
        RETURNING proposal_id
        """,
        (
            route_id, next_version, user_id, composition_row_id,
            model_result["total_distance_km"], model_result["total_driving_time_h"],
            model_result.get("air_shift_flights"), model_result.get("air_shift_seats"),
            model_result.get("air_shift_seat_km"), model_result.get("co2_reduction_t_co2e"),
            model_result.get("subsidy_per_seat_km_eur"), model_result.get("subsidy_per_t_co2e_eur"),
            model_result["total_revenue_eur"], model_result["total_cost_eur"],
            model_result["margin_eur"], model_result["margin_per"],
            _dumps(model_result["capacity_breakdown"]),
            _dumps(model_result["revenue_breakdown"]),
            _dumps(model_result["cost_breakdown"]),
            _dumps(snapshot),
        ),
    )
    return cur.fetchone()[0]


# ============================================================
# Main
# ============================================================

def main():
    conn = psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD,
    )
    print(f"Connected to '{DB_NAME}' at {DB_HOST}:{DB_PORT}")
    cur = conn.cursor()

    print("Creating schema 'admin'...")
    cur.execute(load_sql("create_admin_schema.sql"))
    print("Creating schema 'input_params'...")
    cur.execute(load_sql("create_input_params_schema.sql"))
    print("Creating schema 'proposals'...")
    cur.execute(load_sql("create_proposal_schema.sql"))

    print("Seeding admin.users...")
    insert_rows(cur, "admin.users", USERS)
    cur.execute("SELECT user_id FROM admin.users ORDER BY user_id LIMIT 1")
    demo_user_id = cur.fetchone()[0]

    print("Seeding input_params.sources...")
    insert_rows(cur, "input_params.sources", SOURCES)
    source_ids = fetch_source_ids(cur)

    print("Seeding input_params (infrastructure)...")
    insert_rows(cur, "input_params.stop_defaults", STOP_DEFAULTS)
    insert_rows(cur, "input_params.infrastructure_defaults", INFRASTRUCTURE_DEFAULTS)
    insert_rows(cur, "input_params.infrastructure", INFRASTRUCTURE)
    insert_rows(cur, "input_params.stops", STOPS)

    print("Seeding input_params (lookups: classes, operators, operator_class_costs)...")
    insert_rows(cur, "input_params.classes", CLASSES)
    insert_rows(cur, "input_params.operators", OPERATORS)
    seed_operator_class_costs(cur)

    print("Seeding input_params (coach types and classes)...")
    insert_rows(cur, "input_params.coachtypes", COACHTYPES)
    seed_coachtype_classes(cur)

    print("Seeding input_params (compositions and coach assignments)...")
    insert_rows(cur, "input_params.compositions", build_compositions())
    seed_composition_coaches(cur)

    print("Injecting source_ids into parameter rows...")
    seed_sources(cur, source_ids)

    print("Seeding proposals (services, calendar, shapes, routes, trips, stop_times)...")
    insert_rows(cur, "proposals.services", SERVICES)
    insert_rows(cur, "proposals.calendar", CALENDAR)
    insert_rows(cur, "proposals.calendar_dates", CALENDAR_DATES)
    insert_rows(cur, "proposals.shapes", SHAPES)
    insert_rows(cur, "proposals.routes", ROUTES)
    insert_rows(cur, "proposals.trips", TRIPS)
    insert_rows(cur, "proposals.stop_times", STOP_TIMES)

    print("Saving one demo proposal for NJ-BER-VIE...")
    demo_result = {
        "total_distance_km": 683.4, "total_driving_time_h": 8.9,
        "air_shift_flights": 0.8, "air_shift_seats": 144, "air_shift_seat_km": 98410.0,
        "co2_reduction_t_co2e": 62.5, "subsidy_per_seat_km_eur": 0.0612, "subsidy_per_t_co2e_eur": 980.0,
        "total_revenue_eur": 9871.0, "total_cost_eur": 6818.7,
        "margin_eur": 3052.3, "margin_per": 0.3093,
        "capacity_breakdown": {"seats": 0, "couchettes": 144, "sleepers": 0},
        "revenue_breakdown":  {"revenue_couchette": 9871.0},
        "cost_breakdown":     {"loco_amortisation": 420.0, "coach_amortisation": 980.0},
    }
    proposal_id = save_proposal(
        cur, "NJ-BER-VIE", demo_user_id, "STD-3.1", demo_result,
        route_stop_ids=["DE_BERLIN_HBF", "DE_DRESDEN_HBF", "AT_WIEN_HBF"],
        route_country_codes=["DE", "AT"],
    )

    conn.commit()

    print("\nDone. Row counts:")
    for schema, table in [
        ("admin", "users"), ("admin", "feedback"),
        ("input_params", "sources"),
        ("input_params", "stops"), ("input_params", "stop_defaults"),
        ("input_params", "infrastructure"), ("input_params", "infrastructure_defaults"),
        ("input_params", "classes"), ("input_params", "operators"),
        ("input_params", "operator_class_costs"),
        ("input_params", "coachtypes"), ("input_params", "coachtype_classes"),
        ("input_params", "compositions"), ("input_params", "composition_coaches"),
        ("proposals", "routes"), ("proposals", "trips"), ("proposals", "stop_times"),
        ("proposals", "shapes"), ("proposals", "proposals"),
    ]:
        cur.execute(f"SELECT COUNT(*) FROM {schema}.{table}")
        print(f"  {schema}.{table}: {cur.fetchone()[0]} rows")
    print(f"\nDemo proposal_id = {proposal_id} (user_id = {demo_user_id})")

    # spot-check: print the snapshot keys to confirm structure
    cur.execute("SELECT parameter_snapshot FROM proposals.proposals WHERE proposal_id = %s", (proposal_id,))
    snap = cur.fetchone()[0]
    print("\nSnapshot top-level keys:", list(snap.keys()))
    print("Snapshot infrastructure countries:", [i["country_code"] for i in snap["infrastructure"]])
    print("Snapshot coachtypes:", [c["coachtype_id"] for c in snap["coachtypes"]])
    print("Snapshot stops:", [s["stop_id"] for s in snap["stops"]])
    print("First composition param sample:",
          {k: v for k, v in list(snap["composition"]["params"].items())[:2]})

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()