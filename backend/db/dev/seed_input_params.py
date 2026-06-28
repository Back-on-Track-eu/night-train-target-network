"""
seed_input_params.py
====================
Seed data and seeder for the input_params schema.

Tables covered (in insert order):
  input_params.sources
  input_params.countries
  input_params.service_classes
  input_params.operators
  input_params.operator_class_costs
  input_params.coach_types
  input_params.coach_type_classes
  input_params.track_infrastructure_defaults
  input_params.track_infrastructures
  input_params.stop_infrastructure_defaults
  input_params.stop_infrastructures
  input_params.composition_types
  input_params.composition_type_coaches
  input_params.composition_references
"""

# ============================================================
# Sources
# ============================================================

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

SRC_EXCEL        = "B-o-T_targetnetwork_DB_v2.xlsx — illustrative placeholder values"
SRC_ILLUSTRATIVE = "Illustrative / internal estimate"


def fetch_source_ids(cur) -> dict[str, int]:
    cur.execute("SELECT source_id, source_description FROM input_params.sources")
    return {desc: sid for sid, desc in cur.fetchall()}


# ============================================================
# Countries
# ============================================================

COUNTRIES = [
    {"country_code": "DE", "country_name": "Germany"},
    {"country_code": "AT", "country_name": "Austria"},
    {"country_code": "CH", "country_name": "Switzerland"},
    {"country_code": "FR", "country_name": "France"},
    {"country_code": "BE", "country_name": "Belgium"},
    {"country_code": "DK", "country_name": "Denmark"},
    {"country_code": "SE", "country_name": "Sweden"},
]


# ============================================================
# Service classes  (density = space consumption per place)
# seat=1/64, couchette=1/20, sleeper=1/12
# ============================================================

SERVICE_CLASSES = [
    # Seat
    {"service_class_id": "seat (reclining)",                          "service_class_main": "Seat",      "service_class_density": round(1/64, 6)},
    {"service_class_id": "seat (compartment)",                        "service_class_main": "Seat",      "service_class_density": round(1/64, 6)},
    {"service_class_id": "seat (large room)",                         "service_class_main": "Seat",      "service_class_density": round(1/64, 6)},
    {"service_class_id": "seat (spare)",                              "service_class_main": "Seat",      "service_class_density": round(1/64, 6)},
    {"service_class_id": "seat (playzone)",                           "service_class_main": "Seat",      "service_class_density": round(1/64, 6)},
    {"service_class_id": "seat PRM",                                  "service_class_main": "Seat",      "service_class_density": round(1/64, 6)},
    # Couchette
    {"service_class_id": "couchette (4-berth)",                       "service_class_main": "Couchette", "service_class_density": round(1/20, 6)},
    {"service_class_id": "couchette (5-berth)",                       "service_class_main": "Couchette", "service_class_density": round(1/20, 6)},
    {"service_class_id": "couchette (6-berth)",                       "service_class_main": "Couchette", "service_class_density": round(1/20, 6)},
    {"service_class_id": "couchette (large room)",                    "service_class_main": "Couchette", "service_class_density": round(1/20, 6)},
    {"service_class_id": "couchette PRM (2-berth)",                   "service_class_main": "Couchette", "service_class_density": round(1/20, 6)},
    # Capsule
    {"service_class_id": "Capsule (1-bed) with seat",                 "service_class_main": "Capsule",   "service_class_density": 1.0},
    {"service_class_id": "Capsule (2-bed) with seats",                "service_class_main": "Capsule",   "service_class_density": round(1/2, 6)},
    {"service_class_id": "Capsule (double) with seats",               "service_class_main": "Capsule",   "service_class_density": round(1/2, 6)},
    {"service_class_id": "Capsule (3-bed) with seats",                "service_class_main": "Capsule",   "service_class_density": round(1/3, 6)},
    {"service_class_id": "Mini-Cabin (bed)",                          "service_class_main": "Capsule",   "service_class_density": 1.0},
    # Sleeper
    {"service_class_id": "Sleeper (2-berth) with shower & WC",        "service_class_main": "Sleeper",   "service_class_density": round(1/12, 6)},
    {"service_class_id": "Sleeper (2-berth) with shower option & WC", "service_class_main": "Sleeper",   "service_class_density": round(1/12, 6)},
    {"service_class_id": "Sleeper (double) with shower & WC",         "service_class_main": "Sleeper",   "service_class_density": round(1/12, 6)},
    {"service_class_id": "Sleeper (3-berth) with shower & WC",        "service_class_main": "Sleeper",   "service_class_density": round(1/12, 6)},
    {"service_class_id": "Sleeper (2-berth) with basin",              "service_class_main": "Sleeper",   "service_class_density": round(1/12, 6)},
    {"service_class_id": "Sleeper (3-berth) with basin",              "service_class_main": "Sleeper",   "service_class_density": round(1/12, 6)},
    {"service_class_id": "Sleeper (4-berth) with basin",              "service_class_main": "Sleeper",   "service_class_density": round(1/12, 6)},
    {"service_class_id": "Sleeper PRM (2-berth)",                     "service_class_main": "Sleeper",   "service_class_density": round(1/12, 6)},
    {"service_class_id": "Sleeper PRM (double)",                      "service_class_main": "Sleeper",   "service_class_density": round(1/12, 6)},
    {"service_class_id": "Sleeper PRM (single)",                      "service_class_main": "Sleeper",   "service_class_density": round(1/12, 6)},
    # Catering
    {"service_class_id": "Catering",                                  "service_class_main": "Catering",  "service_class_density": 0.0},
]


# ============================================================
# Operators
# ============================================================

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


# ============================================================
# Coach types
# ============================================================

COACH_TYPES = [
    {"coach_type_id": "type1", "coach_type_operator_id": "STD", "coach_type_weight_gross_t": 52.00, "coach_type_bikes": 0, "coach_type_climatization": True,  "coach_type_plugs": True,  "coach_type_crew_factor": 0.5, "coach_type_remarks": "STD seat coach — 80 reclining seats"},
    {"coach_type_id": "type2", "coach_type_operator_id": "STD", "coach_type_weight_gross_t": 50.70, "coach_type_bikes": 0, "coach_type_climatization": True,  "coach_type_plugs": False, "coach_type_crew_factor": 0.5, "coach_type_remarks": "STD couchette coach — 48 couchette (6-berth) places"},
    {"coach_type_id": "type3", "coach_type_operator_id": "STD", "coach_type_weight_gross_t": 55.50, "coach_type_bikes": 0, "coach_type_climatization": True,  "coach_type_plugs": True,  "coach_type_crew_factor": 1.0, "coach_type_remarks": "STD sleeper coach — 24 sleeper berths (2-berth with shower & WC)"},
]

COACH_TYPE_CLASSES_RAW = [
    ("type1", "seat (reclining)",                   80),
    ("type2", "couchette (6-berth)",                48),
    ("type3", "Sleeper (2-berth) with shower & WC", 24),
]


# ============================================================
# Track infrastructure
# ============================================================

TRACK_INFRA_DEFAULTS = [
    {
        "track_infra_default_key":    "_default",
        "track_tac_eur_train_km":     4.50,
        "track_parking_eur_day":      65.00,
        "track_energy_price_eur_kwh": 0.150,
        "track_terrain_category":     "Flat",
        "track_terrain_score":        1.0,
        "track_hsr_allowed":          True,
        "track_min_boarding_time":    "00:02:00",
        "track_min_alighting_time":   "00:02:00",
        "track_buffer_quota_per":     0.10,
    },
]

TRACK_INFRASTRUCTURES = [
    # DE version 2 (current)
    {"country_code": "DE", "track_infra_version": 2, "is_current": True,  "track_tac_eur_train_km": 5.40, "track_parking_eur_day": 70.00, "track_energy_price_eur_kwh": 0.142, "track_terrain_category": "Flat",        "track_terrain_score": 1.0, "track_hsr_allowed": True, "track_min_boarding_time": "00:02:00", "track_min_alighting_time": "00:02:00", "track_buffer_quota_per": 0.10},
    # DE version 1 (superseded — loader must ignore is_current=False)
    {"country_code": "DE", "track_infra_version": 1, "is_current": False, "track_tac_eur_train_km": 3.10, "track_parking_eur_day": 50.00, "track_energy_price_eur_kwh": 0.120, "track_terrain_category": "Flat",        "track_terrain_score": 1.0, "track_hsr_allowed": True, "track_min_boarding_time": "00:02:00", "track_min_alighting_time": "00:02:00", "track_buffer_quota_per": 0.08},
    {"country_code": "AT", "track_infra_version": 2, "is_current": True,  "track_tac_eur_train_km": 4.20, "track_parking_eur_day": 60.00, "track_energy_price_eur_kwh": 0.138, "track_terrain_category": "Hilly",       "track_terrain_score": 1.4, "track_hsr_allowed": True, "track_min_boarding_time": "00:02:00", "track_min_alighting_time": "00:02:00", "track_buffer_quota_per": 0.12},
    {"country_code": "CH", "track_infra_version": 2, "is_current": True,  "track_tac_eur_train_km": 6.80, "track_parking_eur_day": 85.00, "track_energy_price_eur_kwh": 0.165, "track_terrain_category": "Mountainous", "track_terrain_score": 1.8, "track_hsr_allowed": True, "track_min_boarding_time": "00:03:00", "track_min_alighting_time": "00:03:00", "track_buffer_quota_per": 0.15},
    {"country_code": "FR", "track_infra_version": 2, "is_current": True,  "track_tac_eur_train_km": 4.60, "track_parking_eur_day": 55.00, "track_energy_price_eur_kwh": 0.130, "track_terrain_category": "Flat",        "track_terrain_score": 1.0, "track_hsr_allowed": True, "track_min_boarding_time": "00:02:00", "track_min_alighting_time": "00:02:00", "track_buffer_quota_per": 0.10},
    {"country_code": "BE", "track_infra_version": 2, "is_current": True,  "track_tac_eur_train_km": 5.10, "track_parking_eur_day": 50.00, "track_energy_price_eur_kwh": 0.145, "track_terrain_category": "Flat",        "track_terrain_score": 1.0, "track_hsr_allowed": True, "track_min_boarding_time": "00:02:00", "track_min_alighting_time": "00:02:00", "track_buffer_quota_per": 0.10},
    {"country_code": "DK", "track_infra_version": 2, "is_current": True,  "track_tac_eur_train_km": 4.80, "track_parking_eur_day": 55.00, "track_energy_price_eur_kwh": 0.128, "track_terrain_category": "Flat",        "track_terrain_score": 1.0, "track_hsr_allowed": True, "track_min_boarding_time": "00:02:00", "track_min_alighting_time": "00:02:00", "track_buffer_quota_per": 0.10},
    # SE: NULL tac and parking → resolved from defaults (tests is_default=True path in loader)
    {"country_code": "SE", "track_infra_version": 2, "is_current": True,  "track_tac_eur_train_km": None, "track_parking_eur_day": None,  "track_energy_price_eur_kwh": 0.090, "track_terrain_category": "Hilly",       "track_terrain_score": 1.2, "track_hsr_allowed": True, "track_min_boarding_time": "00:02:00", "track_min_alighting_time": "00:02:00", "track_buffer_quota_per": 0.10},
]


# ============================================================
# Stop infrastructure
# ============================================================

STOP_INFRA_DEFAULTS = [
    {"country_code": None, "stop_charge_eur": 11.28},  # global default (country_code NULL)
]

STOP_INFRASTRUCTURES = [
    {"stop_id": "DE_BERLIN_HBF",  "stop_name": "Berlin Hbf",          "country_code": "DE", "stop_timezone": "Europe/Berlin",     "stop_lat": 52.525, "stop_lon": 13.369, "stop_charge_eur":  9.80},
    {"stop_id": "DE_DRESDEN_HBF", "stop_name": "Dresden Hbf",         "country_code": "DE", "stop_timezone": "Europe/Berlin",     "stop_lat": 51.040, "stop_lon": 13.732, "stop_charge_eur":  6.50},
    {"stop_id": "AT_WIEN_HBF",    "stop_name": "Wien Hbf",            "country_code": "AT", "stop_timezone": "Europe/Vienna",     "stop_lat": 48.185, "stop_lon": 16.376, "stop_charge_eur": 11.00},
    {"stop_id": "CH_ZUERICH_HB",  "stop_name": "Zuerich HB",          "country_code": "CH", "stop_timezone": "Europe/Zurich",     "stop_lat": 47.378, "stop_lon":  8.540, "stop_charge_eur": 14.50},
    {"stop_id": "FR_PARIS_EST",   "stop_name": "Paris Gare de l'Est", "country_code": "FR", "stop_timezone": "Europe/Paris",      "stop_lat": 48.877, "stop_lon":  2.359, "stop_charge_eur": 13.20},
    {"stop_id": "BE_BRUSSELS_M",  "stop_name": "Bruxelles-Midi",      "country_code": "BE", "stop_timezone": "Europe/Brussels",   "stop_lat": 50.836, "stop_lon":  4.336, "stop_charge_eur": 10.40},
    {"stop_id": "DK_COPENHAGEN",  "stop_name": "Koebenhavn H",        "country_code": "DK", "stop_timezone": "Europe/Copenhagen", "stop_lat": 55.673, "stop_lon": 12.565, "stop_charge_eur":  9.00},
    # SE_STOCKHOLM: NULL stop_charge_eur → resolved from global default (tests is_default=True path in loader)
    {"stop_id": "SE_STOCKHOLM_C", "stop_name": "Stockholm C",         "country_code": "SE", "stop_timezone": "Europe/Stockholm",  "stop_lat": 59.330, "stop_lon": 18.058, "stop_charge_eur": None},
]


# ============================================================
# Composition types
# ============================================================

_STD_COMP_DEFAULTS = dict(
    composition_type_operator_id           = "STD",
    composition_type_hsr_allowed           = True,
    composition_type_max_speed_kmh         = 230,
    composition_type_energy_factor_weight  = 0.000168,
    composition_type_energy_factor_speed   = 0.015123,
    composition_type_energy_factor_terrain = 0.034545,
    composition_type_min_boarding_time     = "00:02:00",
    composition_type_min_alighting_time    = "00:02:00",
    composition_type_purchase_loco_eur     = 24500000.00,
    composition_type_purchase_coach_eur    = 20000000.00,
    composition_type_loco_avail_per        = 0.85,
    composition_type_coach_avail_per       = 0.80,
    composition_type_loco_amort_years      = 25,
    composition_type_coach_amort_years     = 30,
    composition_type_cleaning_eur_day      = 1753.584,
    composition_type_loco_maint_eur_km     = 2.86533333,
    composition_type_coach_maint_eur_km    = 2.86533333,
    composition_type_driver_factor         = 1.0,
)

_COMPOSITION_TYPES_VARYING = [
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


def build_composition_types() -> list[dict]:
    return [
        {"composition_type_id": comp_id, "composition_type_description": description, **_STD_COMP_DEFAULTS}
        for comp_id, description in _COMPOSITION_TYPES_VARYING
    ]


COMPOSITION_TYPE_COACHES_RAW = [
    ("STD-3.1",  1, "type2"), ("STD-3.1",  2, "type2"), ("STD-3.1",  3, "type2"),
    ("STD-4.1",  1, "type1"), ("STD-4.1",  2, "type2"), ("STD-4.1",  3, "type2"), ("STD-4.1",  4, "type2"),
    ("STD-4.2",  1, "type2"), ("STD-4.2",  2, "type2"), ("STD-4.2",  3, "type2"), ("STD-4.2",  4, "type2"),
    ("STD-5.1",  1, "type1"), ("STD-5.1",  2, "type2"), ("STD-5.1",  3, "type2"), ("STD-5.1",  4, "type2"), ("STD-5.1",  5, "type3"),
    ("STD-5.2",  1, "type2"), ("STD-5.2",  2, "type2"), ("STD-5.2",  3, "type2"), ("STD-5.2",  4, "type2"), ("STD-5.2",  5, "type3"),
    ("STD-6.1",  1, "type1"), ("STD-6.1",  2, "type2"), ("STD-6.1",  3, "type2"), ("STD-6.1",  4, "type2"), ("STD-6.1",  5, "type2"), ("STD-6.1",  6, "type3"),
    ("STD-6.2",  1, "type2"), ("STD-6.2",  2, "type2"), ("STD-6.2",  3, "type2"), ("STD-6.2",  4, "type2"), ("STD-6.2",  5, "type2"), ("STD-6.2",  6, "type3"),
    ("STD-7.1",  1, "type1"), ("STD-7.1",  2, "type1"), ("STD-7.1",  3, "type2"), ("STD-7.1",  4, "type2"), ("STD-7.1",  5, "type2"), ("STD-7.1",  6, "type3"), ("STD-7.1",  7, "type3"),
    ("STD-9.1",  1, "type1"), ("STD-9.1",  2, "type1"), ("STD-9.1",  3, "type2"), ("STD-9.1",  4, "type2"), ("STD-9.1",  5, "type2"), ("STD-9.1",  6, "type2"), ("STD-9.1",  7, "type2"), ("STD-9.1",  8, "type3"), ("STD-9.1",  9, "type3"),
    ("STD-13.1", 1, "type1"), ("STD-13.1", 2, "type1"), ("STD-13.1", 3, "type2"), ("STD-13.1", 4, "type2"), ("STD-13.1", 5, "type2"), ("STD-13.1", 6, "type2"), ("STD-13.1", 7, "type2"), ("STD-13.1", 8, "type2"), ("STD-13.1", 9, "type2"), ("STD-13.1", 10, "type3"), ("STD-13.1", 11, "type3"), ("STD-13.1", 12, "type3"), ("STD-13.1", 13, "type3"),
]


# ============================================================
# FK-resolving helpers
# ============================================================

def _seed_operator_class_costs(cur) -> None:
    for operator_id, service_class_id, eur_place in OPERATOR_CLASS_COSTS_RAW:
        cur.execute(
            """INSERT INTO input_params.operator_class_costs
               (operator_id, service_class_id, operator_class_svc_stockings_eur_place)
               VALUES (%s, %s, %s)""",
            (operator_id, service_class_id, eur_place),
        )


def _seed_coach_type_classes(cur) -> None:
    for coach_type_id, service_class_id, places in COACH_TYPE_CLASSES_RAW:
        cur.execute(
            "SELECT coach_type_row_id FROM input_params.coach_types WHERE coach_type_id=%s AND is_current",
            (coach_type_id,),
        )
        coach_type_row_id = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO input_params.coach_type_classes
               (coach_type_row_id, service_class_id, coach_type_class_places)
               VALUES (%s, %s, %s)""",
            (coach_type_row_id, service_class_id, places),
        )


def _seed_composition_type_coaches(cur) -> None:
    for comp_id, position, coach_type_id in COMPOSITION_TYPE_COACHES_RAW:
        cur.execute(
            "SELECT composition_type_row_id FROM input_params.composition_types WHERE composition_type_id=%s AND is_current",
            (comp_id,),
        )
        composition_type_row_id = cur.fetchone()[0]
        cur.execute(
            "SELECT coach_type_row_id FROM input_params.coach_types WHERE coach_type_id=%s AND is_current",
            (coach_type_id,),
        )
        coach_type_row_id = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO input_params.composition_type_coaches
               (composition_type_row_id, position, coach_type_row_id)
               VALUES (%s, %s, %s)""",
            (composition_type_row_id, position, coach_type_row_id),
        )


def _seed_composition_references(cur, insert_rows) -> None:
    """Seed reference trip profiles for STD-7.1 and STD-9.1."""
    for comp_id in ("STD-7.1", "STD-9.1"):
        cur.execute(
            "SELECT composition_type_row_id FROM input_params.composition_types WHERE composition_type_id=%s AND is_current",
            (comp_id,),
        )
        row = cur.fetchone()
        if row is None:
            print(f"  WARNING: {comp_id} not found — skipping reference seed")
            continue
        insert_rows(cur, "input_params.composition_references", [
            dict(
                composition_type_row_id   = row[0],
                composition_type_id       = comp_id,
                ref_distance_km           = 800,
                ref_avg_speed_kmh         = 90.0,
                ref_terrain_score         = 1.3,
                ref_operating_days        = 360,
                ref_utilization_seat      = 0.70,
                ref_utilization_couchette = 0.65,
                ref_utilization_sleeper   = 0.80,
                ref_utilization_capsule   = 0.00,
                ref_utilization_catering  = 0.00,
                ref_avg_fare_seat         = 49.00,
                ref_avg_fare_couchette    = 79.00,
                ref_avg_fare_sleeper      = 129.00,
                ref_avg_fare_capsule      = 0.00,
                ref_avg_fare_catering     = 0.00,
            ),
        ])


def _seed_sources(cur, source_ids: dict) -> None:
    """Inject source IDs into all input_params rows after they are inserted."""
    ill = source_ids[SRC_ILLUSTRATIVE]
    exc = source_ids[SRC_EXCEL]
    cur.execute("UPDATE input_params.track_infrastructure_defaults SET track_tac_src=%s, track_parking_src=%s, track_energy_price_src=%s, track_terrain_src=%s, track_hsr_src=%s, track_min_boarding_src=%s, track_min_alighting_src=%s, track_buffer_src=%s", (ill,)*8)
    cur.execute("UPDATE input_params.track_infrastructures         SET track_tac_src=%s, track_parking_src=%s, track_energy_price_src=%s, track_terrain_src=%s, track_hsr_src=%s, track_min_boarding_src=%s, track_min_alighting_src=%s, track_buffer_src=%s", (ill,)*8)
    cur.execute("UPDATE input_params.stop_infrastructure_defaults  SET stop_charge_src=%s", (ill,))
    cur.execute("UPDATE input_params.stop_infrastructures          SET stop_loc_src=%s, stop_charge_src=%s", (ill, ill))
    cur.execute("UPDATE input_params.operators                     SET source_id=%s", (ill,))
    cur.execute("UPDATE input_params.operator_class_costs          SET source_id=%s", (ill,))
    cur.execute("UPDATE input_params.coach_types                   SET source_id=%s", (ill,))
    cur.execute("UPDATE input_params.coach_type_classes            SET source_id=%s", (ill,))
    cur.execute("UPDATE input_params.composition_types             SET source_id=%s", (exc,))


# ============================================================
# Seeder
# ============================================================

def seed_input_params(cur, insert_rows) -> None:
    """Seed all input_params tables in dependency order."""
    print("Seeding input_params.sources...")
    insert_rows(cur, "input_params.sources", SOURCES)
    source_ids = fetch_source_ids(cur)

    print("Seeding input_params.countries...")
    insert_rows(cur, "input_params.countries", COUNTRIES)

    print("Seeding input_params.service_classes...")
    insert_rows(cur, "input_params.service_classes", SERVICE_CLASSES)

    print("Seeding input_params.operators...")
    insert_rows(cur, "input_params.operators", OPERATORS)
    _seed_operator_class_costs(cur)

    print("Seeding input_params.coach_types...")
    insert_rows(cur, "input_params.coach_types", COACH_TYPES)
    _seed_coach_type_classes(cur)

    print("Seeding input_params.track_infrastructure_defaults...")
    insert_rows(cur, "input_params.track_infrastructure_defaults", TRACK_INFRA_DEFAULTS)

    print("Seeding input_params.track_infrastructures...")
    insert_rows(cur, "input_params.track_infrastructures", TRACK_INFRASTRUCTURES)

    print("Seeding input_params.stop_infrastructure_defaults...")
    insert_rows(cur, "input_params.stop_infrastructure_defaults", STOP_INFRA_DEFAULTS)

    print("Seeding input_params.stop_infrastructures...")
    insert_rows(cur, "input_params.stop_infrastructures", STOP_INFRASTRUCTURES)

    print("Seeding input_params.composition_types...")
    insert_rows(cur, "input_params.composition_types", build_composition_types())
    _seed_composition_type_coaches(cur)
    _seed_composition_references(cur, insert_rows)

    print("Injecting source IDs...")
    _seed_sources(cur, source_ids)