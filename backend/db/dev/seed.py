"""
Seeds the Back-on-Track night train database.

Only schema DDL lives in sql/*.sql, loaded via sql_loader.
All seed data is plain Python dicts inserted via insert_rows().
Idempotent — each schema starts with DROP SCHEMA ... CASCADE.

Run order:
  1. admin
  2. input_params: sources → countries → service_classes → operators →
     operator_class_costs → coach_types → coach_type_classes →
     track_infrastructure_defaults → track_infrastructures →
     stop_infrastructure_defaults → stop_infrastructures →
     composition_types → composition_type_coaches → composition_references
  3. scenario: scenarios (base scenario pinning the version numbers seeded
     for the four infrastructure tables, plus one illustrative what-if
     scenario)
  4. proposals

Versioning note
---------------
Only the four infrastructure input_params tables (track_infrastructures,
track_infrastructure_defaults, stop_infrastructures,
stop_infrastructure_defaults) are versioned — "current" is entirely a
scenario.scenarios concept for these (see create_scenario_schema.sql). A
version bump is a FULL-TABLE SNAPSHOT: editing one row duplicates every
other row of that table forward into the new version number.

Each of the three seeded scenarios (see the "scenario" section near the
bottom of this file) pins its own version number, in lockstep, across all
four tables — i.e. version 1 belongs entirely to the "2026 Base Line"
scenario, version 2 to "2032 Base Line", version 3 to "2032 Base Line +
Night Trains on HSR allowed":

  - version 1 — 2026 Base Line (deprecated): the original, lower-cost
    baseline. Only track_infrastructures/track_infrastructure_defaults
    carry deliberately different figures (DE's pre-correction rates,
    a slightly lower EU-average default); stop_infrastructures and
    stop_infrastructure_defaults are duplicated unchanged, since nothing
    about stop charges differs for this scenario.
  - version 2 — 2032 Base Line (current default, is_current_base=TRUE):
    the current parameter set, with track_hsr_allowed=False everywhere
    (night trains may not use HSR infrastructure).
  - version 3 — 2032 Base Line + Night Trains on HSR allowed (the other
    current scenario lineage head): identical to version 2 in every
    field except track_hsr_allowed=True everywhere.

Because each scenario owns a full, independent snapshot of all four
tables, comparing data across scenarios must go through resolved values,
not version-number equality — see test_04_versioning.py /
test_31_evaluation_content.py for the pattern.

operators, coach_types, composition_types, and composition_references are
NOT versioned — they're a catalog you add to, not history you edit. Each
row's natural id (operator_id, coach_type_id, composition_type_id) is
permanent; changing a value means seeding a new id, never editing a row
in place. See create_input_params_schema.sql for the rationale.
"""

import os
from datetime import timedelta
from decimal import Decimal
import json

import psycopg2
from dotenv import load_dotenv

load_dotenv()

from sql_loader import load_sql

DB_HOST = os.environ["POSTGRES_HOST"]
DB_PORT = os.environ["POSTGRES_PORT"]
DB_NAME = os.environ["POSTGRES_DB"]
DB_USER = os.environ["POSTGRES_USER"]
DB_PASSWORD = os.environ["POSTGRES_PASSWORD"]


class _PgEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, timedelta):
            total = int(obj.total_seconds())
            h, rem = divmod(total, 3600)
            m, s = divmod(rem, 60)
            return f"{h:02d}:{m:02d}:{s:02d}"
        return super().default(obj)


def _dumps(obj) -> str:
    return json.dumps(obj, cls=_PgEncoder)


def insert_rows(cur, table: str, rows: list[dict]) -> None:
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
    {"user_name": "David", "email": "david@backontrack.eu"},
    {"user_name": "Bjarne", "email": "bjarne@backontrack.eu"},
]

# ============================================================
# sources
# ============================================================

SOURCES = [
    {
        "source_description": "B-o-T_targetnetwork_DB_v2.xlsx — illustrative placeholder values",
        "source_url": None,
        "source_date": "2025-06-01",
    },
    {
        "source_description": "Illustrative / internal estimate",
        "source_url": None,
        "source_date": None,
    },
]

SRC_EXCEL = "B-o-T_targetnetwork_DB_v2.xlsx — illustrative placeholder values"
SRC_ILLUSTRATIVE = "Illustrative / internal estimate"


def fetch_source_ids(cur) -> dict[str, int]:
    cur.execute("SELECT source_id, source_description FROM input_params.sources")
    return {desc: sid for sid, desc in cur.fetchall()}


# ============================================================
# countries
# ============================================================

COUNTRIES = [
    {"country_code": "DE", "country_name": "Germany"},
    {"country_code": "AT", "country_name": "Austria"},
    {
        "country_code": "CH",
        "country_name": "Switzerland",
    },  # not an EU member — kept for existing CH routes
    {"country_code": "FR", "country_name": "France"},
    {"country_code": "BE", "country_name": "Belgium"},
    {"country_code": "DK", "country_name": "Denmark"},
    {"country_code": "SE", "country_name": "Sweden"},
    # Remaining EU27 members — added so _check_country_coverage() in
    # route_factory.py doesn't reject a route for merely transiting one of
    # these, even though none has real track_infrastructures figures yet
    # (see _TRACK_INFRA_CANONICAL_ROWS below: every field but country_code is None,
    # so TrackInfraCollection resolves every one of them from the EU-average
    # default — is_default stays False since a real row exists, but expect
    # a "using EU default" warning logged per field per country).
    {"country_code": "BG", "country_name": "Bulgaria"},
    {"country_code": "HR", "country_name": "Croatia"},
    {"country_code": "CY", "country_name": "Cyprus"},
    {"country_code": "CZ", "country_name": "Czechia"},
    {"country_code": "EE", "country_name": "Estonia"},
    {"country_code": "FI", "country_name": "Finland"},
    {"country_code": "GR", "country_name": "Greece"},
    {"country_code": "HU", "country_name": "Hungary"},
    {"country_code": "IE", "country_name": "Ireland"},
    {"country_code": "IT", "country_name": "Italy"},
    {"country_code": "LV", "country_name": "Latvia"},
    {"country_code": "LT", "country_name": "Lithuania"},
    {"country_code": "LU", "country_name": "Luxembourg"},
    {"country_code": "MT", "country_name": "Malta"},
    {"country_code": "NL", "country_name": "Netherlands"},
    {"country_code": "PL", "country_name": "Poland"},
    {"country_code": "PT", "country_name": "Portugal"},
    {"country_code": "RO", "country_name": "Romania"},
    {"country_code": "SK", "country_name": "Slovakia"},
    {"country_code": "SI", "country_name": "Slovenia"},
    {"country_code": "ES", "country_name": "Spain"},
]

# Natural Earth's ADM0_A3 (ISO 3166-1 alpha-3) for exactly the countries
# seeded above. Kept local and minimal — this is a one-off seed-time
# matching key, not a general country-code utility. It isn't importable
# from elsewhere in the codebase anyway: seed.py also runs standalone in
# the db/dev seeder image, which has no models/ package (see
# backend/db/dev/Dockerfile).
_COUNTRY_CODE_TO_ADM0_A3 = {
    "DE": "DEU",
    "AT": "AUT",
    "CH": "CHE",
    "FR": "FRA",
    "BE": "BEL",
    "DK": "DNK",
    "SE": "SWE",
    "BG": "BGR",
    "HR": "HRV",
    "CY": "CYP",
    "CZ": "CZE",
    "EE": "EST",
    "FI": "FIN",
    "GR": "GRC",
    "HU": "HUN",
    "IE": "IRL",
    "IT": "ITA",
    "LV": "LVA",
    "LT": "LTU",
    "LU": "LUX",
    "MT": "MLT",
    "NL": "NLD",
    "PL": "POL",
    "PT": "PRT",
    "RO": "ROU",
    "SK": "SVK",
    "SI": "SVN",
    "ES": "ESP",
}


def _load_natural_earth_features() -> dict[str, dict] | None:
    """
    Read the Natural Earth admin-0 countries geojson — the same file
    rail_router.py used to read directly before country borders moved into
    PostGIS — and index its features by ADM0_A3.

    Returns None (with a warning) if the file isn't present, e.g. when
    running seed.py outside the Docker images that download it at build
    time. country_geom is a nullable column, so this degrades gracefully
    to an ungeocoded seed rather than failing the whole run.
    """
    path = os.environ.get("COUNTRIES_GEOJSON_PATH")
    if not path or not os.path.exists(path):
        print(
            f"  WARNING: countries geojson not found at "
            f"COUNTRIES_GEOJSON_PATH={path!r} — skipping country_geom, "
            f"all countries will be seeded with NULL geometry."
        )
        return None
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {f["properties"].get("ADM0_A3"): f["geometry"] for f in data["features"]}


def seed_country_geometries(cur) -> None:
    """
    Populate input_params.countries.country_geom for every seeded country
    that has a matching Natural Earth feature. Runs as UPDATEs after
    COUNTRIES has been inserted, since ST_GeomFromGeoJSON() isn't something
    insert_rows()'s plain-value INSERT can express.
    """
    features = _load_natural_earth_features()
    if features is None:
        return
    matched, missing = 0, []
    for cc, adm0_a3 in _COUNTRY_CODE_TO_ADM0_A3.items():
        geometry = features.get(adm0_a3)
        if geometry is None:
            missing.append(cc)
            continue
        cur.execute(
            """
            UPDATE input_params.countries
            SET country_geom = ST_SetSRID(ST_Multi(ST_GeomFromGeoJSON(%s)), 4326)
            WHERE country_code = %s
            """,
            (_dumps(geometry), cc),
        )
        matched += 1
    print(f"  Matched {matched}/{len(_COUNTRY_CODE_TO_ADM0_A3)} country geometries.")
    if missing:
        print(f"  WARNING: no Natural Earth feature found for: {', '.join(missing)}")


# ============================================================
# service_classes  (density = space consumption per place, Sleeper > Couchette > Seat)
# seat=1/64, couchette=1/20, sleeper=1/12
# ============================================================

SERVICE_CLASSES = [
    # Seat
    {
        "service_class_id": "seat (reclining)",
        "service_class_main": "Seat",
        "service_class_density": round(1 / 64, 6),
    },
    {
        "service_class_id": "seat (compartment)",
        "service_class_main": "Seat",
        "service_class_density": round(1 / 64, 6),
    },
    {
        "service_class_id": "seat (large room)",
        "service_class_main": "Seat",
        "service_class_density": round(1 / 64, 6),
    },
    {
        "service_class_id": "seat (spare)",
        "service_class_main": "Seat",
        "service_class_density": round(1 / 64, 6),
    },
    {
        "service_class_id": "seat (playzone)",
        "service_class_main": "Seat",
        "service_class_density": round(1 / 64, 6),
    },
    {
        "service_class_id": "seat PRM",
        "service_class_main": "Seat",
        "service_class_density": round(1 / 64, 6),
    },
    # Couchette
    {
        "service_class_id": "couchette (4-berth)",
        "service_class_main": "Couchette",
        "service_class_density": round(1 / 20, 6),
    },
    {
        "service_class_id": "couchette (5-berth)",
        "service_class_main": "Couchette",
        "service_class_density": round(1 / 20, 6),
    },
    {
        "service_class_id": "couchette (6-berth)",
        "service_class_main": "Couchette",
        "service_class_density": round(1 / 20, 6),
    },
    {
        "service_class_id": "couchette (large room)",
        "service_class_main": "Couchette",
        "service_class_density": round(1 / 20, 6),
    },
    {
        "service_class_id": "couchette PRM (2-berth)",
        "service_class_main": "Couchette",
        "service_class_density": round(1 / 20, 6),
    },
    # Capsule
    {
        "service_class_id": "Capsule (1-bed) with seat",
        "service_class_main": "Capsule",
        "service_class_density": 1.0,
    },
    {
        "service_class_id": "Capsule (2-bed) with seats",
        "service_class_main": "Capsule",
        "service_class_density": round(1 / 2, 6),
    },
    {
        "service_class_id": "Capsule (double) with seats",
        "service_class_main": "Capsule",
        "service_class_density": round(1 / 2, 6),
    },
    {
        "service_class_id": "Capsule (3-bed) with seats",
        "service_class_main": "Capsule",
        "service_class_density": round(1 / 3, 6),
    },
    {
        "service_class_id": "Mini-Cabin (bed)",
        "service_class_main": "Capsule",
        "service_class_density": 1.0,
    },
    # Sleeper
    {
        "service_class_id": "Sleeper (2-berth) with shower & WC",
        "service_class_main": "Sleeper",
        "service_class_density": round(1 / 12, 6),
    },
    {
        "service_class_id": "Sleeper (2-berth) with shower option & WC",
        "service_class_main": "Sleeper",
        "service_class_density": round(1 / 12, 6),
    },
    {
        "service_class_id": "Sleeper (double) with shower & WC",
        "service_class_main": "Sleeper",
        "service_class_density": round(1 / 12, 6),
    },
    {
        "service_class_id": "Sleeper (3-berth) with shower & WC",
        "service_class_main": "Sleeper",
        "service_class_density": round(1 / 12, 6),
    },
    {
        "service_class_id": "Sleeper (2-berth) with basin",
        "service_class_main": "Sleeper",
        "service_class_density": round(1 / 12, 6),
    },
    {
        "service_class_id": "Sleeper (3-berth) with basin",
        "service_class_main": "Sleeper",
        "service_class_density": round(1 / 12, 6),
    },
    {
        "service_class_id": "Sleeper (4-berth) with basin",
        "service_class_main": "Sleeper",
        "service_class_density": round(1 / 12, 6),
    },
    {
        "service_class_id": "Sleeper PRM (2-berth)",
        "service_class_main": "Sleeper",
        "service_class_density": round(1 / 12, 6),
    },
    {
        "service_class_id": "Sleeper PRM (double)",
        "service_class_main": "Sleeper",
        "service_class_density": round(1 / 12, 6),
    },
    {
        "service_class_id": "Sleeper PRM (single)",
        "service_class_main": "Sleeper",
        "service_class_density": round(1 / 12, 6),
    },
    # Catering
    {
        "service_class_id": "Catering",
        "service_class_main": "Catering",
        "service_class_density": 0.0,
    },
]

# ============================================================
# operators
# ============================================================

OPERATORS = [
    {
        "operator_id": "STD",
        "operator_name": "Standard (illustrative)",
        "operator_driver_costs_eur_h": 52.00,
        "operator_crew_costs_eur_h": 38.00,
        "operator_driver_overhead_h": "01:00:00",
        "operator_crew_overhead_h": "01:00:00",
        "operator_ebit_margin_per": 0.03,
        "operator_financing_quota_per": 0.04,
        "operator_var_overhead_per": 0.10,
        "operator_fix_overhead_quota_per": 0.15,
        # Full-service locomotive lease — utilization-based, bundles
        # capital, maintenance, and insurance. Illustrative rate based on
        # European full-service lease providers (ELP, Railpool, Alpha
        # Trains), billed per loco operating hour.
        "operator_loco_lease_eur_h": 145.00,
    },
]

OPERATOR_CLASS_COSTS_RAW = [
    ("STD", "seat (reclining)", 0.01),
    ("STD", "seat (compartment)", 0.01),
    ("STD", "seat (large room)", 0.01),
    ("STD", "seat (spare)", 0.01),
    ("STD", "seat (playzone)", 0.01),
    ("STD", "seat PRM", 0.01),
    ("STD", "couchette (4-berth)", 0.05),
    ("STD", "couchette (5-berth)", 0.05),
    ("STD", "couchette (6-berth)", 0.05),
    ("STD", "couchette (large room)", 0.05),
    ("STD", "couchette PRM (2-berth)", 0.05),
    ("STD", "Sleeper (2-berth) with shower & WC", 0.10),
    ("STD", "Sleeper (2-berth) with shower option & WC", 0.10),
    ("STD", "Sleeper (double) with shower & WC", 0.10),
    ("STD", "Sleeper (3-berth) with shower & WC", 0.10),
    ("STD", "Sleeper (2-berth) with basin", 0.10),
    ("STD", "Sleeper (3-berth) with basin", 0.10),
    ("STD", "Sleeper (4-berth) with basin", 0.10),
    ("STD", "Sleeper PRM (2-berth)", 0.10),
    ("STD", "Sleeper PRM (double)", 0.10),
    ("STD", "Sleeper PRM (single)", 0.10),
]

# ============================================================
# coach_types
# ============================================================

COACH_TYPES = [
    {
        "coach_type_id": "type1",
        "coach_type_operator_id": "STD",
        "coach_type_weight_gross_t": 52.00,
        "coach_type_bikes": 0,
        "coach_type_climatization": True,
        "coach_type_plugs": True,
        "coach_type_crew_factor": 0.5,
        "coach_type_remarks": "STD seat coach — 80 reclining seats",
    },
    {
        "coach_type_id": "type2",
        "coach_type_operator_id": "STD",
        "coach_type_weight_gross_t": 50.70,
        "coach_type_bikes": 0,
        "coach_type_climatization": True,
        "coach_type_plugs": False,
        "coach_type_crew_factor": 0.5,
        "coach_type_remarks": "STD couchette coach — 48 couchette (6-berth) places",
    },
    {
        "coach_type_id": "type3",
        "coach_type_operator_id": "STD",
        "coach_type_weight_gross_t": 55.50,
        "coach_type_bikes": 0,
        "coach_type_climatization": True,
        "coach_type_plugs": True,
        "coach_type_crew_factor": 1.0,
        "coach_type_remarks": "STD sleeper coach — 24 sleeper berths (2-berth with shower & WC)",
    },
]

COACH_TYPE_CLASSES_RAW = [
    ("type1", "seat (reclining)", 80),
    ("type2", "couchette (6-berth)", 48),
    ("type3", "Sleeper (2-berth) with shower & WC", 24),
]

# ============================================================
# track infrastructure
# ============================================================
#
# Three full-table snapshots, one per scenario (see the "scenario" section
# near the bottom of this file):
#   version 1 — 2026 Base Line (deprecated): the original, lower-cost
#     figures, kept only as a frozen historical reference.
#   version 2 — 2032 Base Line (current default): track_hsr_allowed=False
#     everywhere — night trains may not use HSR infrastructure.
#   version 3 — 2032 Base Line + Night Trains on HSR allowed: identical to
#     version 2 except track_hsr_allowed=True everywhere.
# A scenario pins one version NUMBER for the whole table, never a
# per-country flag — see create_scenario_schema.sql.

# 2032 default row. track_hsr_allowed is set per-version below (see
# _build_track_infra_defaults) rather than baked in here.
_TRACK_INFRA_DEFAULT_2032 = {
    "track_infra_default_key": "_default",
    "track_tac_eur_train_km": 4.50,
    "track_parking_eur_day": 65.00,
    "track_shunting_eur_event": 575.00,
    "track_energy_price_eur_kwh": 0.150,
    "track_terrain_category": "Flat",
    "track_terrain_score": 1.0,
    "track_min_boarding_time": "00:02:00",
    "track_min_alighting_time": "00:02:00",
    # Qualified assumption: schedule buffer quotas across European networks
    # realistically sit at 30-50% of pure driving time (construction sites,
    # mixed-traffic congestion, temporary speed restrictions, node dwell
    # creep); 0.40 is the band's midpoint, used for every country without
    # an explicit row. The per-country rows below differentiate within the
    # band — see the comment on each.
    # TODO: differentiate buffer_quota_per by TIME OF DAY — congestion is
    # daypart-dependent (after ~05:00 the morning rush builds, while the
    # night hours most night-train legs actually run in are far emptier),
    # so a flat per-country quota over-pads genuine night legs and
    # under-pads early-morning arrival legs. Needs a schema change
    # (per-country time bands) plus route-model work to apply the quota
    # per leg by clock time — see OPEN_TODOS["buffer_quota_time_of_day"]
    # in models/route/version.py before starting.
    "track_buffer_quota_per": 0.40,
}

# 2026 deprecated row — a handful of values manipulated downward (same
# spirit as DE's track_infrastructures pre-correction rates below), just
# enough to make the two default rows distinguishable in the frozen
# historical scenario. Everything not overridden here matches 2032.
_TRACK_INFRA_DEFAULT_2026_OVERRIDES = {
    "track_tac_eur_train_km": 4.20,
    "track_parking_eur_day": 60.00,
    "track_buffer_quota_per": 0.35,
}


def _build_track_infra_defaults() -> list[dict]:
    v2032 = _TRACK_INFRA_DEFAULT_2032
    return [
        {
            **v2032,
            **_TRACK_INFRA_DEFAULT_2026_OVERRIDES,
            "track_hsr_allowed": True,
            "track_infra_default_version": 1,
        },
        {**v2032, "track_hsr_allowed": False, "track_infra_default_version": 2},
        {**v2032, "track_hsr_allowed": True, "track_infra_default_version": 3},
    ]


TRACK_INFRA_DEFAULTS = _build_track_infra_defaults()

# Canonical per-country dataset (all 28 countries) — hsr_allowed here is
# irrelevant, it's overridden per-version below (True for the 2026 and
# 2032+HSR snapshots, False for the 2032 no-HSR snapshot).
_TRACK_INFRA_CANONICAL_ROWS = [
    {
        "country_code": "DE",
        "track_infra_version": 2,
        "track_tac_eur_train_km": 5.40,
        "track_parking_eur_day": 70.00,
        "track_shunting_eur_event": 575.00,
        "track_energy_price_eur_kwh": 0.142,
        "track_terrain_category": "Flat",
        "track_terrain_score": 1.0,
        "track_hsr_allowed": True,
        "track_min_boarding_time": "00:02:00",
        "track_min_alighting_time": "00:02:00",
        # worst long-distance punctuality of the major networks, Generalsanierung
        # construction backlog, dense mixed traffic
        "track_buffer_quota_per": 0.50,
    },
    {
        "country_code": "AT",
        "track_infra_version": 2,
        "track_tac_eur_train_km": 4.20,
        "track_parking_eur_day": 60.00,
        "track_shunting_eur_event": 575.00,
        "track_energy_price_eur_kwh": 0.138,
        "track_terrain_category": "Hilly",
        "track_terrain_score": 1.4,
        "track_hsr_allowed": True,
        "track_min_boarding_time": "00:02:00",
        "track_min_alighting_time": "00:02:00",
        # high ÖBB punctuality, well-maintained network; Alpine corridors and the Wien
        # node keep it above the floor
        "track_buffer_quota_per": 0.35,
    },
    {
        "country_code": "CH",
        "track_infra_version": 2,
        "track_tac_eur_train_km": 6.80,
        "track_parking_eur_day": 85.00,
        "track_shunting_eur_event": 575.00,
        "track_energy_price_eur_kwh": 0.165,
        "track_terrain_category": "Mountainous",
        "track_terrain_score": 1.8,
        "track_hsr_allowed": True,
        "track_min_boarding_time": "00:03:00",
        "track_min_alighting_time": "00:03:00",
        # best punctuality in Europe — dense but rigorously timetabled; band floor
        "track_buffer_quota_per": 0.30,
    },
    {
        "country_code": "FR",
        "track_infra_version": 2,
        "track_tac_eur_train_km": 4.60,
        "track_parking_eur_day": 55.00,
        "track_shunting_eur_event": 575.00,
        "track_energy_price_eur_kwh": 0.130,
        "track_terrain_category": "Flat",
        "track_terrain_score": 1.0,
        "track_hsr_allowed": True,
        "track_min_boarding_time": "00:02:00",
        "track_min_alighting_time": "00:02:00",
        # moderate punctuality; maintenance backlog on the conventional (non-LGV)
        # network night trains use
        "track_buffer_quota_per": 0.40,
    },
    {
        "country_code": "BE",
        "track_infra_version": 2,
        "track_tac_eur_train_km": 5.10,
        "track_parking_eur_day": 50.00,
        "track_shunting_eur_event": 575.00,
        "track_energy_price_eur_kwh": 0.145,
        "track_terrain_category": "Flat",
        "track_terrain_score": 1.0,
        "track_hsr_allowed": True,
        "track_min_boarding_time": "00:02:00",
        "track_min_alighting_time": "00:02:00",
        # dense, congested network around the Brussels node, frequent engineering
        # works
        "track_buffer_quota_per": 0.45,
    },
    {
        "country_code": "DK",
        "track_infra_version": 2,
        "track_tac_eur_train_km": 4.80,
        "track_parking_eur_day": 55.00,
        "track_shunting_eur_event": 575.00,
        "track_energy_price_eur_kwh": 0.128,
        "track_terrain_category": "Flat",
        "track_terrain_score": 1.0,
        "track_hsr_allowed": True,
        "track_min_boarding_time": "00:02:00",
        "track_min_alighting_time": "00:02:00",
        # ERTMS/signalling programme disruptions, Storebælt corridor bottleneck
        "track_buffer_quota_per": 0.40,
    },
    # SE has NULL tac and parking → will resolve from defaults (tests is_default=True)
    {
        "country_code": "SE",
        "track_infra_version": 2,
        "track_tac_eur_train_km": None,
        "track_parking_eur_day": None,
        "track_shunting_eur_event": None,
        "track_energy_price_eur_kwh": 0.090,
        "track_terrain_category": "Hilly",
        "track_terrain_score": 1.2,
        "track_hsr_allowed": True,
        "track_min_boarding_time": "00:02:00",
        "track_min_alighting_time": "00:02:00",
        # long single-track stretches, freight mixing, winter operations
        "track_buffer_quota_per": 0.40,
    },
    # Remaining EU27 members — every field None, resolved entirely from the
    # EU-average default (track_infrastructure_defaults). Real figures TBD;
    # this just gives each a real row so _check_country_coverage() in
    # route_factory.py doesn't reject a route for merely transiting one of
    # these (is_default stays False — a row exists — but every field will
    # log a "using EU default" warning the first time it's resolved).
    {
        "country_code": "BG",
        "track_infra_version": 2,
        "track_tac_eur_train_km": None,
        "track_parking_eur_day": None,
        "track_shunting_eur_event": None,
        "track_energy_price_eur_kwh": None,
        "track_terrain_category": None,
        "track_terrain_score": None,
        "track_hsr_allowed": None,
        "track_min_boarding_time": None,
        "track_min_alighting_time": None,
        "track_buffer_quota_per": None,
    },
    {
        "country_code": "HR",
        "track_infra_version": 2,
        "track_tac_eur_train_km": None,
        "track_parking_eur_day": None,
        "track_shunting_eur_event": None,
        "track_energy_price_eur_kwh": None,
        "track_terrain_category": None,
        "track_terrain_score": None,
        "track_hsr_allowed": None,
        "track_min_boarding_time": None,
        "track_min_alighting_time": None,
        "track_buffer_quota_per": None,
    },
    {
        "country_code": "CY",
        "track_infra_version": 2,
        "track_tac_eur_train_km": None,
        "track_parking_eur_day": None,
        "track_shunting_eur_event": None,
        "track_energy_price_eur_kwh": None,
        "track_terrain_category": None,
        "track_terrain_score": None,
        "track_hsr_allowed": None,
        "track_min_boarding_time": None,
        "track_min_alighting_time": None,
        "track_buffer_quota_per": None,
    },
    {
        "country_code": "CZ",
        "track_infra_version": 2,
        "track_tac_eur_train_km": None,
        "track_parking_eur_day": None,
        "track_shunting_eur_event": None,
        "track_energy_price_eur_kwh": None,
        "track_terrain_category": None,
        "track_terrain_score": None,
        "track_hsr_allowed": None,
        "track_min_boarding_time": None,
        "track_min_alighting_time": None,
        "track_buffer_quota_per": None,
    },
    {
        "country_code": "EE",
        "track_infra_version": 2,
        "track_tac_eur_train_km": None,
        "track_parking_eur_day": None,
        "track_shunting_eur_event": None,
        "track_energy_price_eur_kwh": None,
        "track_terrain_category": None,
        "track_terrain_score": None,
        "track_hsr_allowed": None,
        "track_min_boarding_time": None,
        "track_min_alighting_time": None,
        "track_buffer_quota_per": None,
    },
    {
        "country_code": "FI",
        "track_infra_version": 2,
        "track_tac_eur_train_km": None,
        "track_parking_eur_day": None,
        "track_shunting_eur_event": None,
        "track_energy_price_eur_kwh": None,
        "track_terrain_category": None,
        "track_terrain_score": None,
        "track_hsr_allowed": None,
        "track_min_boarding_time": None,
        "track_min_alighting_time": None,
        "track_buffer_quota_per": None,
    },
    {
        "country_code": "GR",
        "track_infra_version": 2,
        "track_tac_eur_train_km": None,
        "track_parking_eur_day": None,
        "track_shunting_eur_event": None,
        "track_energy_price_eur_kwh": None,
        "track_terrain_category": None,
        "track_terrain_score": None,
        "track_hsr_allowed": None,
        "track_min_boarding_time": None,
        "track_min_alighting_time": None,
        "track_buffer_quota_per": None,
    },
    {
        "country_code": "HU",
        "track_infra_version": 2,
        "track_tac_eur_train_km": None,
        "track_parking_eur_day": None,
        "track_shunting_eur_event": None,
        "track_energy_price_eur_kwh": None,
        "track_terrain_category": None,
        "track_terrain_score": None,
        "track_hsr_allowed": None,
        "track_min_boarding_time": None,
        "track_min_alighting_time": None,
        "track_buffer_quota_per": None,
    },
    {
        "country_code": "IE",
        "track_infra_version": 2,
        "track_tac_eur_train_km": None,
        "track_parking_eur_day": None,
        "track_shunting_eur_event": None,
        "track_energy_price_eur_kwh": None,
        "track_terrain_category": None,
        "track_terrain_score": None,
        "track_hsr_allowed": None,
        "track_min_boarding_time": None,
        "track_min_alighting_time": None,
        "track_buffer_quota_per": None,
    },
    {
        "country_code": "IT",
        "track_infra_version": 2,
        "track_tac_eur_train_km": None,
        "track_parking_eur_day": None,
        "track_shunting_eur_event": None,
        "track_energy_price_eur_kwh": None,
        "track_terrain_category": None,
        "track_terrain_score": None,
        "track_hsr_allowed": None,
        "track_min_boarding_time": None,
        "track_min_alighting_time": None,
        "track_buffer_quota_per": None,
    },
    {
        "country_code": "LV",
        "track_infra_version": 2,
        "track_tac_eur_train_km": None,
        "track_parking_eur_day": None,
        "track_shunting_eur_event": None,
        "track_energy_price_eur_kwh": None,
        "track_terrain_category": None,
        "track_terrain_score": None,
        "track_hsr_allowed": None,
        "track_min_boarding_time": None,
        "track_min_alighting_time": None,
        "track_buffer_quota_per": None,
    },
    {
        "country_code": "LT",
        "track_infra_version": 2,
        "track_tac_eur_train_km": None,
        "track_parking_eur_day": None,
        "track_shunting_eur_event": None,
        "track_energy_price_eur_kwh": None,
        "track_terrain_category": None,
        "track_terrain_score": None,
        "track_hsr_allowed": None,
        "track_min_boarding_time": None,
        "track_min_alighting_time": None,
        "track_buffer_quota_per": None,
    },
    {
        "country_code": "LU",
        "track_infra_version": 2,
        "track_tac_eur_train_km": None,
        "track_parking_eur_day": None,
        "track_shunting_eur_event": None,
        "track_energy_price_eur_kwh": None,
        "track_terrain_category": None,
        "track_terrain_score": None,
        "track_hsr_allowed": None,
        "track_min_boarding_time": None,
        "track_min_alighting_time": None,
        "track_buffer_quota_per": None,
    },
    {
        "country_code": "MT",
        "track_infra_version": 2,
        "track_tac_eur_train_km": None,
        "track_parking_eur_day": None,
        "track_shunting_eur_event": None,
        "track_energy_price_eur_kwh": None,
        "track_terrain_category": None,
        "track_terrain_score": None,
        "track_hsr_allowed": None,
        "track_min_boarding_time": None,
        "track_min_alighting_time": None,
        "track_buffer_quota_per": None,
    },
    {
        "country_code": "NL",
        "track_infra_version": 2,
        "track_tac_eur_train_km": None,
        "track_parking_eur_day": None,
        "track_shunting_eur_event": None,
        "track_energy_price_eur_kwh": None,
        "track_terrain_category": None,
        "track_terrain_score": None,
        "track_hsr_allowed": None,
        "track_min_boarding_time": None,
        "track_min_alighting_time": None,
        "track_buffer_quota_per": None,
    },
    {
        "country_code": "PL",
        "track_infra_version": 2,
        "track_tac_eur_train_km": None,
        "track_parking_eur_day": None,
        "track_shunting_eur_event": None,
        "track_energy_price_eur_kwh": None,
        "track_terrain_category": None,
        "track_terrain_score": None,
        "track_hsr_allowed": None,
        "track_min_boarding_time": None,
        "track_min_alighting_time": None,
        "track_buffer_quota_per": None,
    },
    {
        "country_code": "PT",
        "track_infra_version": 2,
        "track_tac_eur_train_km": None,
        "track_parking_eur_day": None,
        "track_shunting_eur_event": None,
        "track_energy_price_eur_kwh": None,
        "track_terrain_category": None,
        "track_terrain_score": None,
        "track_hsr_allowed": None,
        "track_min_boarding_time": None,
        "track_min_alighting_time": None,
        "track_buffer_quota_per": None,
    },
    {
        "country_code": "RO",
        "track_infra_version": 2,
        "track_tac_eur_train_km": None,
        "track_parking_eur_day": None,
        "track_shunting_eur_event": None,
        "track_energy_price_eur_kwh": None,
        "track_terrain_category": None,
        "track_terrain_score": None,
        "track_hsr_allowed": None,
        "track_min_boarding_time": None,
        "track_min_alighting_time": None,
        "track_buffer_quota_per": None,
    },
    {
        "country_code": "SK",
        "track_infra_version": 2,
        "track_tac_eur_train_km": None,
        "track_parking_eur_day": None,
        "track_shunting_eur_event": None,
        "track_energy_price_eur_kwh": None,
        "track_terrain_category": None,
        "track_terrain_score": None,
        "track_hsr_allowed": None,
        "track_min_boarding_time": None,
        "track_min_alighting_time": None,
        "track_buffer_quota_per": None,
    },
    {
        "country_code": "SI",
        "track_infra_version": 2,
        "track_tac_eur_train_km": None,
        "track_parking_eur_day": None,
        "track_shunting_eur_event": None,
        "track_energy_price_eur_kwh": None,
        "track_terrain_category": None,
        "track_terrain_score": None,
        "track_hsr_allowed": None,
        "track_min_boarding_time": None,
        "track_min_alighting_time": None,
        "track_buffer_quota_per": None,
    },
    {
        "country_code": "ES",
        "track_infra_version": 2,
        "track_tac_eur_train_km": None,
        "track_parking_eur_day": None,
        "track_shunting_eur_event": None,
        "track_energy_price_eur_kwh": None,
        "track_terrain_category": None,
        "track_terrain_score": None,
        "track_hsr_allowed": None,
        "track_min_boarding_time": None,
        "track_min_alighting_time": None,
        "track_buffer_quota_per": None,
    },
]

# Version 1 (2026 Base Line, deprecated) = the same full snapshot, except
# DE still carries its original, lower (pre-correction) rates — exactly
# the full-table-snapshot invariant in practice. track_hsr_allowed is
# forced True on every non-null row, matching the pre-2032-policy figures.
_TRACK_INFRA_V1_OVERRIDES = {
    "DE": {
        "track_tac_eur_train_km": 3.10,
        "track_parking_eur_day": 50.00,
        "track_buffer_quota_per": 0.45,
    },
}


def _with_hsr_allowed(row: dict, hsr_allowed: bool) -> dict:
    """Override track_hsr_allowed on a row, unless it's None (the 21
    EU27-placeholder countries deliberately resolve every field from the
    default row — see _TRACK_INFRA_CANONICAL_ROWS above)."""
    if row["track_hsr_allowed"] is None:
        return row
    return {**row, "track_hsr_allowed": hsr_allowed}


def _build_track_infrastructures_v1() -> list[dict]:
    rows = []
    for row in _TRACK_INFRA_CANONICAL_ROWS:
        v1_row = {**_with_hsr_allowed(row, True), "track_infra_version": 1}
        v1_row.update(_TRACK_INFRA_V1_OVERRIDES.get(row["country_code"], {}))
        rows.append(v1_row)
    return rows


def _build_track_infrastructures_v2() -> list[dict]:
    """2032 Base Line — night trains may not use HSR infrastructure."""
    return [
        {**_with_hsr_allowed(row, False), "track_infra_version": 2}
        for row in _TRACK_INFRA_CANONICAL_ROWS
    ]


def _build_track_infrastructures_v3() -> list[dict]:
    """2032 Base Line + Night Trains on HSR allowed — identical to v2
    except every non-null track_hsr_allowed flips to True."""
    return [
        {**_with_hsr_allowed(row, True), "track_infra_version": 3}
        for row in _TRACK_INFRA_CANONICAL_ROWS
    ]


TRACK_INFRASTRUCTURES = (
    _build_track_infrastructures_v1()
    + _build_track_infrastructures_v2()
    + _build_track_infrastructures_v3()
)

# ============================================================
# stop infrastructure
# ============================================================
#
# Three full-table snapshots, one per scenario — same lockstep numbering
# as track infrastructure above (1 = 2026 Base Line, 2 = 2032 Base Line,
# 3 = 2032 Base Line + HSR allowed). Stop charges don't depend on the HSR
# policy, so all three versions carry byte-identical values; only the
# version number differs, satisfying "each scenario holds its own
# infrastructure rows" without inventing an artificial value difference.

_STOP_INFRA_DEFAULT_CANONICAL = [
    # global default (country_code NULL)
    {"country_code": None, "stop_charge_eur": 11.28},
]

_STOP_INFRASTRUCTURES_CANONICAL = [
    # Stops with explicit stop_charge_eur
    {
        "stop_id": "DE_BERLIN_HBF",
        "stop_name": "Berlin Hbf",
        "country_code": "DE",
        "stop_timezone": "Europe/Berlin",
        "stop_lat": 52.525,
        "stop_lon": 13.369,
        "stop_charge_eur": 9.80,
    },
    {
        "stop_id": "DE_DRESDEN_HBF",
        "stop_name": "Dresden Hbf",
        "country_code": "DE",
        "stop_timezone": "Europe/Berlin",
        "stop_lat": 51.040,
        "stop_lon": 13.732,
        "stop_charge_eur": 6.50,
    },
    {
        "stop_id": "AT_WIEN_HBF",
        "stop_name": "Wien Hbf",
        "country_code": "AT",
        "stop_timezone": "Europe/Vienna",
        "stop_lat": 48.185,
        "stop_lon": 16.376,
        "stop_charge_eur": 11.00,
    },
    {
        "stop_id": "CH_ZUERICH_HB",
        "stop_name": "Zuerich HB",
        "country_code": "CH",
        "stop_timezone": "Europe/Zurich",
        "stop_lat": 47.378,
        "stop_lon": 8.540,
        "stop_charge_eur": 14.50,
    },
    {
        "stop_id": "FR_PARIS_EST",
        "stop_name": "Paris Gare de l'Est",
        "country_code": "FR",
        "stop_timezone": "Europe/Paris",
        "stop_lat": 48.877,
        "stop_lon": 2.359,
        "stop_charge_eur": 13.20,
    },
    {
        "stop_id": "BE_BRUSSELS_M",
        "stop_name": "Bruxelles-Midi",
        "country_code": "BE",
        "stop_timezone": "Europe/Brussels",
        "stop_lat": 50.836,
        "stop_lon": 4.336,
        "stop_charge_eur": 10.40,
    },
    {
        "stop_id": "DK_COPENHAGEN",
        "stop_name": "Koebenhavn H",
        "country_code": "DK",
        "stop_timezone": "Europe/Copenhagen",
        "stop_lat": 55.673,
        "stop_lon": 12.565,
        "stop_charge_eur": 9.00,
    },
    # SE_STOCKHOLM has NULL stop_charge_eur → will resolve from global default (tests is_default=True)
    {
        "stop_id": "SE_STOCKHOLM_C",
        "stop_name": "Stockholm C",
        "country_code": "SE",
        "stop_timezone": "Europe/Stockholm",
        "stop_lat": 59.330,
        "stop_lon": 18.058,
        "stop_charge_eur": None,
    },
    # --- 50 additional main-station stops (2026-07-12) — main stations in
    # major cities across SE/DK/DE/BE/NL/CZ/AT/CH/FR/IT, added for broader
    # frontend testing coverage. Curated from the B-o-T target-network c_stops
    # catalogue (~29k rows): coordinates cross-checked against a per-country
    # bounding box (~15-30% of that sheet's rows have corrupted lat/lon —
    # e.g. Danish stops with Spanish coordinates — so every row here was
    # verified in-bounds before use, not copied blindly). stop_charge_eur is
    # left None (→ resolves from DefaultStopInfra, same as SE_STOCKHOLM_C)
    # unless the sheet's value was genuinely distinctive — most of its charge
    # values (e.g. 44.462933, 37.797177, 7.59) turned out to be a handful of
    # generic estimates reused verbatim across hundreds of unrelated stops in
    # totally different countries, not real per-stop tariffs, so those were
    # treated as unavailable rather than copied.
    # Sweden
    {
        "stop_id": "SE_GOTEBORG_C",
        "stop_name": "Göteborg C",
        "country_code": "SE",
        "stop_timezone": "Europe/Stockholm",
        "stop_lat": 57.709,
        "stop_lon": 11.973,
        "stop_charge_eur": None,
    },
    {
        "stop_id": "SE_MALMO_C",
        "stop_name": "Malmö C",
        "country_code": "SE",
        "stop_timezone": "Europe/Stockholm",
        "stop_lat": 55.609,
        "stop_lon": 13.001,
        "stop_charge_eur": None,
    },
    {
        "stop_id": "SE_UPPSALA_C",
        "stop_name": "Uppsala C",
        "country_code": "SE",
        "stop_timezone": "Europe/Stockholm",
        "stop_lat": 59.858,
        "stop_lon": 17.647,
        "stop_charge_eur": None,
    },
    {
        "stop_id": "SE_LINKOPING_C",
        "stop_name": "Linköping C",
        "country_code": "SE",
        "stop_timezone": "Europe/Stockholm",
        "stop_lat": 58.416,
        "stop_lon": 15.626,
        "stop_charge_eur": None,
    },
    {
        "stop_id": "SE_OREBRO_C",
        "stop_name": "Örebro C",
        "country_code": "SE",
        "stop_timezone": "Europe/Stockholm",
        "stop_lat": 59.279,
        "stop_lon": 15.212,
        "stop_charge_eur": None,
    },
    # Denmark
    {
        "stop_id": "DK_AARHUS_H",
        "stop_name": "Aarhus H",
        "country_code": "DK",
        "stop_timezone": "Europe/Copenhagen",
        "stop_lat": 56.15,
        "stop_lon": 10.205,
        "stop_charge_eur": None,
    },
    {
        "stop_id": "DK_ODENSE",
        "stop_name": "Odense",
        "country_code": "DK",
        "stop_timezone": "Europe/Copenhagen",
        "stop_lat": 55.402,
        "stop_lon": 10.386,
        "stop_charge_eur": 93.38,
    },
    {
        "stop_id": "DK_AALBORG",
        "stop_name": "Aalborg",
        "country_code": "DK",
        "stop_timezone": "Europe/Copenhagen",
        "stop_lat": 57.049,
        "stop_lon": 9.922,
        "stop_charge_eur": None,
    },
    {
        "stop_id": "DK_ESBJERG",
        "stop_name": "Esbjerg",
        "country_code": "DK",
        "stop_timezone": "Europe/Copenhagen",
        "stop_lat": 55.468,
        "stop_lon": 8.458,
        "stop_charge_eur": None,
    },
    {
        "stop_id": "DK_KOLDING",
        "stop_name": "Kolding",
        "country_code": "DK",
        "stop_timezone": "Europe/Copenhagen",
        "stop_lat": 55.491,
        "stop_lon": 9.482,
        "stop_charge_eur": None,
    },
    # Germany
    {
        "stop_id": "DE_MUENCHEN_HBF",
        "stop_name": "München Hbf",
        "country_code": "DE",
        "stop_timezone": "Europe/Berlin",
        "stop_lat": 48.142,
        "stop_lon": 11.558,
        "stop_charge_eur": None,
    },
    {
        "stop_id": "DE_HAMBURG_HBF",
        "stop_name": "Hamburg Hbf",
        "country_code": "DE",
        "stop_timezone": "Europe/Berlin",
        "stop_lat": 53.553,
        "stop_lon": 10.007,
        "stop_charge_eur": 32.47,
    },
    {
        "stop_id": "DE_KOELN_HBF",
        "stop_name": "Köln Hbf",
        "country_code": "DE",
        "stop_timezone": "Europe/Berlin",
        "stop_lat": 50.943,
        "stop_lon": 6.959,
        "stop_charge_eur": 47.34,
    },
    {
        "stop_id": "DE_FRANKFURT_HBF",
        "stop_name": "Frankfurt am Main Hbf",
        "country_code": "DE",
        "stop_timezone": "Europe/Berlin",
        "stop_lat": 50.107,
        "stop_lon": 8.663,
        "stop_charge_eur": None,
    },
    {
        "stop_id": "DE_STUTTGART_HBF",
        "stop_name": "Stuttgart Hbf",
        "country_code": "DE",
        "stop_timezone": "Europe/Berlin",
        "stop_lat": 48.784,
        "stop_lon": 9.182,
        "stop_charge_eur": None,
    },
    # Belgium
    {
        "stop_id": "BE_ANTWERPEN_CENTRAAL",
        "stop_name": "Antwerpen Centraal",
        "country_code": "BE",
        "stop_timezone": "Europe/Brussels",
        "stop_lat": 51.217,
        "stop_lon": 4.421,
        "stop_charge_eur": None,
    },
    {
        "stop_id": "BE_GENT_SINT_PIETERS",
        "stop_name": "Gent-Sint-Pieters",
        "country_code": "BE",
        "stop_timezone": "Europe/Brussels",
        "stop_lat": 51.036,
        "stop_lon": 3.711,
        "stop_charge_eur": None,
    },
    {
        "stop_id": "BE_LIEGE_GUILLEMINS",
        "stop_name": "Liège-Guillemins",
        "country_code": "BE",
        "stop_timezone": "Europe/Brussels",
        "stop_lat": 50.624,
        "stop_lon": 5.566,
        "stop_charge_eur": 126.67,
    },
    {
        "stop_id": "BE_LEUVEN",
        "stop_name": "Leuven",
        "country_code": "BE",
        "stop_timezone": "Europe/Brussels",
        "stop_lat": 50.884,
        "stop_lon": 4.714,
        "stop_charge_eur": None,
    },
    {
        "stop_id": "BE_CHARLEROI_CENTRAL",
        "stop_name": "Charleroi Central",
        "country_code": "BE",
        "stop_timezone": "Europe/Brussels",
        "stop_lat": 50.405,
        "stop_lon": 4.439,
        "stop_charge_eur": None,
    },
    # Netherlands
    {
        "stop_id": "NL_AMSTERDAM_CENTRAAL",
        "stop_name": "Amsterdam Centraal",
        "country_code": "NL",
        "stop_timezone": "Europe/Amsterdam",
        "stop_lat": 52.379,
        "stop_lon": 4.9,
        "stop_charge_eur": None,
    },
    {
        "stop_id": "NL_ROTTERDAM_CENTRAAL",
        "stop_name": "Rotterdam Centraal",
        "country_code": "NL",
        "stop_timezone": "Europe/Amsterdam",
        "stop_lat": 51.924,
        "stop_lon": 4.47,
        "stop_charge_eur": None,
    },
    {
        "stop_id": "NL_UTRECHT_CENTRAAL",
        "stop_name": "Utrecht Centraal",
        "country_code": "NL",
        "stop_timezone": "Europe/Amsterdam",
        "stop_lat": 52.089,
        "stop_lon": 5.11,
        "stop_charge_eur": None,
    },
    {
        "stop_id": "NL_DEN_HAAG",
        "stop_name": "Den Haag",
        "country_code": "NL",
        "stop_timezone": "Europe/Amsterdam",
        "stop_lat": 52.08,
        "stop_lon": 4.325,
        "stop_charge_eur": None,
    },
    {
        "stop_id": "NL_EINDHOVEN_CENTRAAL",
        "stop_name": "Eindhoven Centraal",
        "country_code": "NL",
        "stop_timezone": "Europe/Amsterdam",
        "stop_lat": 51.443,
        "stop_lon": 5.48,
        "stop_charge_eur": None,
    },
    # Czechia
    {
        "stop_id": "CZ_PRAHA_HLN",
        "stop_name": "Praha hl.n.",
        "country_code": "CZ",
        "stop_timezone": "Europe/Prague",
        "stop_lat": 50.083,
        "stop_lon": 14.436,
        "stop_charge_eur": None,
    },
    {
        "stop_id": "CZ_BRNO_HLN",
        "stop_name": "Brno hl.n.",
        "country_code": "CZ",
        "stop_timezone": "Europe/Prague",
        "stop_lat": 49.191,
        "stop_lon": 16.613,
        "stop_charge_eur": None,
    },
    {
        "stop_id": "CZ_OSTRAVA_HLN",
        "stop_name": "Ostrava hl.n.",
        "country_code": "CZ",
        "stop_timezone": "Europe/Prague",
        "stop_lat": 49.852,
        "stop_lon": 18.267,
        "stop_charge_eur": None,
    },
    {
        "stop_id": "CZ_PLZEN_HLAVNI_NADRAZI",
        "stop_name": "Plzeň hlavní nádraží",
        "country_code": "CZ",
        "stop_timezone": "Europe/Prague",
        "stop_lat": 49.743,
        "stop_lon": 13.388,
        "stop_charge_eur": None,
    },
    {
        "stop_id": "CZ_OLOMOUC_HLN",
        "stop_name": "Olomouc hl.n.",
        "country_code": "CZ",
        "stop_timezone": "Europe/Prague",
        "stop_lat": 49.593,
        "stop_lon": 17.278,
        "stop_charge_eur": None,
    },
    # Austria
    {
        "stop_id": "AT_GRAZ_HBF",
        "stop_name": "Graz Hbf",
        "country_code": "AT",
        "stop_timezone": "Europe/Vienna",
        "stop_lat": 47.072,
        "stop_lon": 15.416,
        "stop_charge_eur": 50.5,
    },
    {
        "stop_id": "AT_LINZ_HBF",
        "stop_name": "Linz Hbf",
        "country_code": "AT",
        "stop_timezone": "Europe/Vienna",
        "stop_lat": 48.29,
        "stop_lon": 14.292,
        "stop_charge_eur": None,
    },
    {
        "stop_id": "AT_SALZBURG_HBF",
        "stop_name": "Salzburg Hbf",
        "country_code": "AT",
        "stop_timezone": "Europe/Vienna",
        "stop_lat": 47.813,
        "stop_lon": 13.046,
        "stop_charge_eur": None,
    },
    {
        "stop_id": "AT_INNSBRUCK_HBF",
        "stop_name": "Innsbruck Hbf",
        "country_code": "AT",
        "stop_timezone": "Europe/Vienna",
        "stop_lat": 47.263,
        "stop_lon": 11.401,
        "stop_charge_eur": None,
    },
    {
        "stop_id": "AT_KLAGENFURT_HBF",
        "stop_name": "Klagenfurt Hbf",
        "country_code": "AT",
        "stop_timezone": "Europe/Vienna",
        "stop_lat": 46.616,
        "stop_lon": 14.314,
        "stop_charge_eur": None,
    },
    # Switzerland
    {
        "stop_id": "CH_GENEVE",
        "stop_name": "Genève",
        "country_code": "CH",
        "stop_timezone": "Europe/Zurich",
        "stop_lat": 46.211,
        "stop_lon": 6.143,
        "stop_charge_eur": None,
    },
    {
        "stop_id": "CH_BASEL_SBB",
        "stop_name": "Basel SBB",
        "country_code": "CH",
        "stop_timezone": "Europe/Zurich",
        "stop_lat": 47.548,
        "stop_lon": 7.59,
        "stop_charge_eur": 73.86,
    },
    {
        "stop_id": "CH_BERN",
        "stop_name": "Bern",
        "country_code": "CH",
        "stop_timezone": "Europe/Zurich",
        "stop_lat": 46.948,
        "stop_lon": 7.436,
        "stop_charge_eur": None,
    },
    {
        "stop_id": "CH_LAUSANNE",
        "stop_name": "Lausanne",
        "country_code": "CH",
        "stop_timezone": "Europe/Zurich",
        "stop_lat": 46.517,
        "stop_lon": 6.629,
        "stop_charge_eur": None,
    },
    {
        "stop_id": "CH_LUZERN",
        "stop_name": "Luzern",
        "country_code": "CH",
        "stop_timezone": "Europe/Zurich",
        "stop_lat": 47.049,
        "stop_lon": 8.31,
        "stop_charge_eur": None,
    },
    # France
    {
        "stop_id": "FR_LYON_PART_DIEU",
        "stop_name": "Lyon-Part-Dieu",
        "country_code": "FR",
        "stop_timezone": "Europe/Paris",
        "stop_lat": 45.761,
        "stop_lon": 4.86,
        "stop_charge_eur": None,
    },
    {
        "stop_id": "FR_MARSEILLE_SAINT_CHARLES",
        "stop_name": "Marseille Saint-Charles",
        "country_code": "FR",
        "stop_timezone": "Europe/Paris",
        "stop_lat": 43.303,
        "stop_lon": 5.381,
        "stop_charge_eur": None,
    },
    {
        "stop_id": "FR_LILLE_EUROPE",
        "stop_name": "Lille Europe",
        "country_code": "FR",
        "stop_timezone": "Europe/Paris",
        "stop_lat": 50.684,
        "stop_lon": 3.088,
        "stop_charge_eur": None,
    },
    {
        "stop_id": "FR_STRASBOURG",
        "stop_name": "Strasbourg",
        "country_code": "FR",
        "stop_timezone": "Europe/Paris",
        "stop_lat": 48.574,
        "stop_lon": 7.754,
        "stop_charge_eur": None,
    },
    {
        "stop_id": "FR_BORDEAUX_SAINT_JEAN",
        "stop_name": "Bordeaux Saint-Jean",
        "country_code": "FR",
        "stop_timezone": "Europe/Paris",
        "stop_lat": 44.826,
        "stop_lon": -0.556,
        "stop_charge_eur": None,
    },
    # Italy
    {
        "stop_id": "IT_ROMA_TERMINI",
        "stop_name": "Roma Termini",
        "country_code": "IT",
        "stop_timezone": "Europe/Rome",
        "stop_lat": 41.9,
        "stop_lon": 12.503,
        "stop_charge_eur": None,
    },
    {
        "stop_id": "IT_MILANO_CENTRALE",
        "stop_name": "Milano Centrale",
        "country_code": "IT",
        "stop_timezone": "Europe/Rome",
        "stop_lat": 45.487,
        "stop_lon": 9.205,
        "stop_charge_eur": None,
    },
    {
        "stop_id": "IT_NAPOLI_CENTRALE",
        "stop_name": "Napoli Centrale",
        "country_code": "IT",
        "stop_timezone": "Europe/Rome",
        "stop_lat": 40.853,
        "stop_lon": 14.273,
        "stop_charge_eur": None,
    },
    {
        "stop_id": "IT_TORINO_PORTA_SUSA",
        "stop_name": "Torino Porta Susa",
        "country_code": "IT",
        "stop_timezone": "Europe/Rome",
        "stop_lat": 45.072,
        "stop_lon": 7.666,
        "stop_charge_eur": None,
    },
    {
        "stop_id": "IT_FIRENZE_SMN",
        "stop_name": "Firenze S. M. N.",
        "country_code": "IT",
        "stop_timezone": "Europe/Rome",
        "stop_lat": 43.777,
        "stop_lon": 11.248,
        "stop_charge_eur": None,
    },
]


def _build_stop_infra_defaults() -> list[dict]:
    return [
        {**row, "stop_infra_default_version": version}
        for version in (1, 2, 3)
        for row in _STOP_INFRA_DEFAULT_CANONICAL
    ]


def _build_stop_infrastructures() -> list[dict]:
    return [
        {**row, "stop_infra_version": version}
        for version in (1, 2, 3)
        for row in _STOP_INFRASTRUCTURES_CANONICAL
    ]


STOP_INFRA_DEFAULTS = _build_stop_infra_defaults()
STOP_INFRASTRUCTURES = _build_stop_infrastructures()

# ============================================================
# composition_types
# ============================================================

STD_COMP_DEFAULTS = dict(
    composition_type_operator_id="STD",
    composition_type_hsr_allowed=True,
    composition_type_max_speed_kmh=230,
    composition_type_energy_factor_weight=0.000168,
    composition_type_energy_factor_speed=0.015123,
    composition_type_energy_factor_terrain=0.034545,
    composition_type_min_boarding_time="00:02:00",
    composition_type_min_alighting_time="00:02:00",
    composition_type_purchase_coach_eur=20000000.00,
    composition_type_coach_avail_per=0.80,
    composition_type_coach_amort_years=30,
    composition_type_cleaning_eur_day=1753.584,
    composition_type_coach_maint_eur_km=2.86533333,
    composition_type_driver_factor=1.0,
)

COMPOSITION_TYPES_VARYING = [
    ("STD-3.1", "Standard 3 coach composition"),
    ("STD-4.1", "Standard 4 coach composition v1"),
    ("STD-4.2", "Standard 4 coach composition v2"),
    ("STD-5.1", "Standard 5 coach composition v1"),
    ("STD-5.2", "Standard 5 coach composition v2"),
    ("STD-6.1", "Standard 6 coach composition v1"),
    ("STD-6.2", "Standard 6 coach composition v2"),
    ("STD-7.1", "Standard 7 coach composition"),
    ("STD-9.1", "Standard 9 coach composition"),
    ("STD-13.1", "Standard 13 coach composition"),
]


def build_composition_types() -> list[dict]:
    return [
        {
            "composition_type_id": comp_id,
            "composition_type_description": description,
            **STD_COMP_DEFAULTS,
        }
        for comp_id, description in COMPOSITION_TYPES_VARYING
    ]


COMPOSITION_TYPE_COACHES_RAW = [
    ("STD-3.1", 1, "type2"),
    ("STD-3.1", 2, "type2"),
    ("STD-3.1", 3, "type2"),
    ("STD-4.1", 1, "type1"),
    ("STD-4.1", 2, "type2"),
    ("STD-4.1", 3, "type2"),
    ("STD-4.1", 4, "type2"),
    ("STD-4.2", 1, "type2"),
    ("STD-4.2", 2, "type2"),
    ("STD-4.2", 3, "type2"),
    ("STD-4.2", 4, "type2"),
    ("STD-5.1", 1, "type1"),
    ("STD-5.1", 2, "type2"),
    ("STD-5.1", 3, "type2"),
    ("STD-5.1", 4, "type2"),
    ("STD-5.1", 5, "type3"),
    ("STD-5.2", 1, "type2"),
    ("STD-5.2", 2, "type2"),
    ("STD-5.2", 3, "type2"),
    ("STD-5.2", 4, "type2"),
    ("STD-5.2", 5, "type3"),
    ("STD-6.1", 1, "type1"),
    ("STD-6.1", 2, "type2"),
    ("STD-6.1", 3, "type2"),
    ("STD-6.1", 4, "type2"),
    ("STD-6.1", 5, "type2"),
    ("STD-6.1", 6, "type3"),
    ("STD-6.2", 1, "type2"),
    ("STD-6.2", 2, "type2"),
    ("STD-6.2", 3, "type2"),
    ("STD-6.2", 4, "type2"),
    ("STD-6.2", 5, "type2"),
    ("STD-6.2", 6, "type3"),
    ("STD-7.1", 1, "type1"),
    ("STD-7.1", 2, "type1"),
    ("STD-7.1", 3, "type2"),
    ("STD-7.1", 4, "type2"),
    ("STD-7.1", 5, "type2"),
    ("STD-7.1", 6, "type3"),
    ("STD-7.1", 7, "type3"),
    ("STD-9.1", 1, "type1"),
    ("STD-9.1", 2, "type1"),
    ("STD-9.1", 3, "type2"),
    ("STD-9.1", 4, "type2"),
    ("STD-9.1", 5, "type2"),
    ("STD-9.1", 6, "type2"),
    ("STD-9.1", 7, "type2"),
    ("STD-9.1", 8, "type3"),
    ("STD-9.1", 9, "type3"),
    ("STD-13.1", 1, "type1"),
    ("STD-13.1", 2, "type1"),
    ("STD-13.1", 3, "type2"),
    ("STD-13.1", 4, "type2"),
    ("STD-13.1", 5, "type2"),
    ("STD-13.1", 6, "type2"),
    ("STD-13.1", 7, "type2"),
    ("STD-13.1", 8, "type2"),
    ("STD-13.1", 9, "type2"),
    ("STD-13.1", 10, "type3"),
    ("STD-13.1", 11, "type3"),
    ("STD-13.1", 12, "type3"),
    ("STD-13.1", 13, "type3"),
]

# ============================================================
# proposals
# ============================================================
#
# No hand-written GTFS rows here. Every backend/db/README.md-documented
# invariant says GTFS rows are always linked to a proposals.proposals row
# by the P{proposal_id}_V{version}_R1 ID convention — a hand-seeded GTFS
# demo route with its own ad-hoc IDs (as this block used to be) violated
# that silently. seed_example_proposal(), called at the end of main(),
# builds one real proposal (Berlin Hbf -> Dresden Hbf -> Wien Hbf) and
# saves it through adapters.proposal_repository.ProposalRepository — the
# exact same code path a live POST /api/proposal uses — so the seeded
# example and a real save are structurally identical by construction,
# not by two independently maintained representations.

# ============================================================
# FK-resolving seed helpers
# ============================================================


def seed_sources(cur, source_ids: dict) -> None:
    ill = source_ids[SRC_ILLUSTRATIVE]
    exc = source_ids[SRC_EXCEL]
    cur.execute(
        "UPDATE input_params.track_infrastructure_defaults SET track_tac_src=%s, track_parking_src=%s, track_energy_price_src=%s, track_terrain_src=%s, track_hsr_src=%s, track_min_boarding_src=%s, track_min_alighting_src=%s, track_buffer_src=%s",
        (ill,) * 8,
    )
    cur.execute(
        "UPDATE input_params.track_infrastructures         SET track_tac_src=%s, track_parking_src=%s, track_energy_price_src=%s, track_terrain_src=%s, track_hsr_src=%s, track_min_boarding_src=%s, track_min_alighting_src=%s, track_buffer_src=%s",
        (ill,) * 8,
    )
    cur.execute(
        "UPDATE input_params.stop_infrastructure_defaults  SET stop_charge_src=%s",
        (ill,),
    )
    cur.execute(
        "UPDATE input_params.stop_infrastructures          SET stop_loc_src=%s, stop_charge_src=%s",
        (ill, ill),
    )
    cur.execute(
        "UPDATE input_params.operators                     SET source_id=%s", (ill,)
    )
    cur.execute(
        "UPDATE input_params.operator_class_costs          SET source_id=%s", (ill,)
    )
    cur.execute(
        "UPDATE input_params.coach_types                   SET source_id=%s", (ill,)
    )
    cur.execute(
        "UPDATE input_params.coach_type_classes            SET source_id=%s", (ill,)
    )
    cur.execute(
        "UPDATE input_params.composition_types             SET source_id=%s", (exc,)
    )


def seed_operator_class_costs(cur):
    for operator_id, service_class_id, eur_place in OPERATOR_CLASS_COSTS_RAW:
        cur.execute(
            "SELECT operator_row_id FROM input_params.operators WHERE operator_id=%s",
            (operator_id,),
        )
        operator_row_id = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO input_params.operator_class_costs
               (operator_row_id, service_class_id, operator_class_svc_stockings_eur_place)
               VALUES (%s, %s, %s)""",
            (operator_row_id, service_class_id, eur_place),
        )


def seed_coach_type_classes(cur):
    for coach_type_id, service_class_id, places in COACH_TYPE_CLASSES_RAW:
        cur.execute(
            "SELECT coach_type_row_id FROM input_params.coach_types WHERE coach_type_id=%s",
            (coach_type_id,),
        )
        coach_type_row_id = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO input_params.coach_type_classes
               (coach_type_row_id, service_class_id, coach_type_class_places)
               VALUES (%s, %s, %s)""",
            (coach_type_row_id, service_class_id, places),
        )


def seed_composition_type_coaches(cur):
    for comp_id, position, coach_type_id in COMPOSITION_TYPE_COACHES_RAW:
        cur.execute(
            "SELECT composition_type_row_id FROM input_params.composition_types WHERE composition_type_id=%s",
            (comp_id,),
        )
        composition_type_row_id = cur.fetchone()[0]
        cur.execute(
            "SELECT coach_type_row_id FROM input_params.coach_types WHERE coach_type_id=%s",
            (coach_type_id,),
        )
        coach_type_row_id = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO input_params.composition_type_coaches
               (composition_type_row_id, position, coach_type_row_id)
               VALUES (%s, %s, %s)""",
            (composition_type_row_id, position, coach_type_row_id),
        )


def seed_composition_references(cur):
    """
    Seed a reference trip profile for every composition in
    COMPOSITION_TYPES_VARYING, so none come back with indicative=null.

    Same illustrative reference profile reused for all compositions for
    now — compute_indicative_figures() is itself still a flat placeholder
    (see models/compositions/calc_indicative_figures.py), so per-
    composition differentiation here wouldn't be reflected in the
    indicative KPIs yet anyway. Revisit alongside the real compositions
    cost model.
    """
    reference_profile = dict(
        ref_distance_km=800,
        ref_avg_speed_kmh=90.0,
        ref_terrain_score=1.3,
        ref_operating_days=360,
        ref_utilization_seat=0.70,
        ref_utilization_couchette=0.65,
        ref_utilization_sleeper=0.80,
        ref_utilization_capsule=0.00,
        ref_utilization_catering=0.00,
        ref_avg_fare_seat=49.00,
        ref_avg_fare_couchette=79.00,
        ref_avg_fare_sleeper=129.00,
        ref_avg_fare_capsule=0.00,
        ref_avg_fare_catering=0.00,
    )
    for comp_id, _description in COMPOSITION_TYPES_VARYING:
        cur.execute(
            """
            SELECT composition_type_row_id FROM input_params.composition_types
            WHERE composition_type_id = %s
        """,
            (comp_id,),
        )
        row = cur.fetchone()
        if row is None:
            print(f"  WARNING: {comp_id} not found — skipping reference seed")
            continue
        insert_rows(
            cur,
            "input_params.composition_references",
            [
                dict(
                    composition_type_row_id=row[0],
                    composition_type_id=comp_id,
                    **reference_profile,
                ),
            ],
        )


# ============================================================
# scenario
# ============================================================
# Each scenario pins its own version number, in lockstep, across all four
# infrastructure tables — every scenario row is a complete, self-contained
# pin, no NULLs, and no table is shared/inherited between scenarios (see
# the versioning note at the top of this file). Compositions/coach
# types/operators/composition references aren't part of a scenario at
# all — see create_scenario_schema.sql.
#
# Three scenarios, one scenario_key each (three independent lineages, not
# forks of one another):
#   1. "2026-baseline"                — 2026 Base Line (deprecated: not
#      the base, not a current lineage head — a frozen historical
#      reference kept only for version-snapshot regression tests).
#   2. "base"                         — 2032 Base Line (the live default;
#      is_current_base=TRUE).
#   3. "2032-baseline-hsr-allowed"    — 2032 Base Line + Night Trains on
#      HSR allowed (a second current lineage head; is_current_scenario=TRUE,
#      is_current_base=FALSE).

HISTORICAL_SCENARIO_2026 = {
    "scenario_key": "2026-baseline",
    "scenario_name": "2026 Base Line",
    "description": "Deprecated historical baseline — pre-2032-correction "
    "parameter set. Not in active use: not the live base, and not the "
    "head of a current what-if lineage. Kept as a frozen reference so "
    "older evaluations stay reproducible.",
    "change_log": "Initial seed.",
    "editor": "david",
    "is_current_base": False,
    "is_current_scenario": False,
    "track_infrastructures_version": 1,
    "track_infrastructure_defaults_version": 1,
    "stop_infrastructures_version": 1,
    "stop_infrastructure_defaults_version": 1,
}

BASE_SCENARIO = {
    "scenario_key": "base",
    "scenario_name": "2032 Base Line",
    "description": "Live default parameter set — track_hsr_allowed=False "
    "everywhere (night trains may not use HSR infrastructure).",
    "change_log": "Initial seed.",
    "editor": "david",
    "is_current_base": True,
    "is_current_scenario": True,
    "track_infrastructures_version": 2,
    "track_infrastructure_defaults_version": 2,
    "stop_infrastructures_version": 2,
    "stop_infrastructure_defaults_version": 2,
}

HSR_SCENARIO = {
    "scenario_key": "2032-baseline-hsr-allowed",
    "scenario_name": "2032 Base Line + Night Trains on HSR allowed",
    "description": "A second current lineage, independent of 'base': "
    "identical to the 2032 Base Line in every field except "
    "track_hsr_allowed=True everywhere. Own full snapshot of all four "
    "tables (version 3), not a partial diff against 'base'.",
    "change_log": "Initial seed.",
    "editor": "david",
    "is_current_base": False,
    "is_current_scenario": True,
    "track_infrastructures_version": 3,
    "track_infrastructure_defaults_version": 3,
    "stop_infrastructures_version": 3,
    "stop_infrastructure_defaults_version": 3,
}


# ============================================================
# Example proposal — seeded via the real save code path
# ============================================================

# Physics-only field subsets mirroring api/helpers/route_serialize.py's
# _composition_to_dict() / _track_to_dict() — kept intentionally separate
# (rather than importing those underscore-prefixed helpers across a
# module boundary) but sourced from the SAME live domain objects
# (Composition / TrackInfrastructure), never hand-typed numbers. If the
# route_serialize.py field lists change, mirror the change here too.
_EXPOSED_TRACK_FIELDS = (
    "hsr_allowed",
    "min_boarding_time_min",
    "min_alighting_time_min",
    "terrain_score",
    "terrain_category",
    "buffer_quota_per",
)


def _composition_physics_dict(comp) -> dict:
    return {
        "comp_id": comp.comp_id,
        "comp_description": comp.comp_description,
        "operator_id": comp.operator_id,
        "max_speed_kmh": comp.max_speed_kmh,
        "hsr_allowed": comp.hsr_allowed,
        "min_boarding_time_min": comp.min_boarding_time_min,
        "min_alighting_time_min": comp.min_alighting_time_min,
        "energy_factor_weight": comp.energy_factor_weight,
        "energy_factor_speed": comp.energy_factor_speed,
        "energy_factor_terrain": comp.energy_factor_terrain,
        "total_weight_t": comp.total_weight_t,
        "total_crew": comp.total_crew,
        "places_by_class": comp.places_by_class,
        "density_by_class": comp.density_by_class,
    }


def _track_physics_dict(track) -> dict:
    return {
        "country_code": track.country_code,
        "defaulted_fields": [
            f for f in _EXPOSED_TRACK_FIELDS if track.field_is_default.get(f)
        ],
        "hsr_allowed": track.hsr_allowed,
        "min_boarding_time_min": track.min_boarding_time_min,
        "min_alighting_time_min": track.min_alighting_time_min,
        "terrain_score": track.terrain_score,
        "terrain_category": track.terrain_category,
        "buffer_quota_per": track.buffer_quota_per,
    }


def _example_trip(
    trip_id: str,
    direction: int,
    stops: list[tuple[str, str, str, float, float]],
    times_min: list[tuple[int | None, int | None]],
    stop_types: list[str],
    segment_physics: list[tuple[int, int, int, float, dict, dict]],
    segment_geometries: list[list[list[float]]],
    geometries_out: list[dict],
) -> dict:
    """One direction of the example trip pair. stops/times_min/stop_types
    are parallel lists over stop positions (n stops); segment_physics/
    segment_geometries are parallel lists over segments (n - 1). Segment
    distance/time/energy figures are illustrative hand-picked values —
    this script has no OpenRailRouting connection to derive them from,
    same as the demo route this replaces."""
    segments = []
    for i in range(len(stops) - 1):
        from_id, from_name, from_cc, from_lat, from_lon = stops[i]
        to_id, to_name, to_cc, to_lat, to_lon = stops[i + 1]
        distance_m, driving_min, buffer_min, energy_kwh, dist_shares, time_shares = (
            segment_physics[i]
        )
        geometry_id = f"{trip_id}_L{i}"
        geometries_out.append({"id": geometry_id, "coords": segment_geometries[i]})
        segments.append(
            {
                "from_stop": {
                    "stop_id": from_id,
                    "stop_name": from_name,
                    "country_code": from_cc,
                    "lat": from_lat,
                    "lon": from_lon,
                    "stop_type": stop_types[i],
                    "arrival_time_min": times_min[i][0],
                    "departure_time_min": times_min[i][1],
                },
                "to_stop": {
                    "stop_id": to_id,
                    "stop_name": to_name,
                    "country_code": to_cc,
                    "lat": to_lat,
                    "lon": to_lon,
                    "stop_type": stop_types[i + 1],
                    "arrival_time_min": times_min[i + 1][0],
                    "departure_time_min": times_min[i + 1][1],
                },
                "geometry_id": geometry_id,
                "distance_m": distance_m,
                "driving_time_min": driving_min,
                "dynamics_time_min": 0,
                "buffer_time_min": buffer_min,
                "slack_time_min": 0,
                "energy_kwh": energy_kwh,
                "country_distance_shares": dist_shares,
                "country_time_shares": time_shares,
            }
        )
    return {"trip_id": trip_id, "direction": direction, "segments": segments}


def _build_example_route(scenario_id: int, composition, tracks) -> dict:
    """Berlin Hbf -> Dresden Hbf -> Wien Hbf, STD-7.1, no demand (od_pairs
    empty — financial fields on this proposal are null until someone
    evaluates and re-saves it, same as any proposal saved without an
    evaluation). Draft route_id follows the real >=1e9 placeholder
    convention /api/route/plan uses, so ProposalRepository.save() exercises
    the exact same ID-rewrite path a live save does. On a fresh DB this
    naturally becomes proposal_id=1 (first-ever insert) — see
    _SEED_PROPOSAL_ID's comment for why that's collision-free."""
    draft_prefix = "P1234567890_V1_R1"
    composition_dict = _composition_physics_dict(composition)

    berlin = ("DE_BERLIN_HBF", "Berlin Hbf", "DE", 52.525, 13.369)
    dresden = ("DE_DRESDEN_HBF", "Dresden Hbf", "DE", 51.040, 13.732)
    wien = ("AT_WIEN_HBF", "Wien Hbf", "AT", 48.185, 16.376)

    # Berlin -> Dresden: fully within DE. Dresden -> Wien: illustrative
    # DE/AT split (doesn't model the real Berlin-Dresden-Wien routing
    # through Czechia — same simplification the demo route this replaces
    # made).
    outbound_physics = [
        (165300, 95, 8, 850.0, {"DE": 1.0}, {"DE": 1.0}),
        (518100, 430, 28, 2650.0, {"DE": 0.3, "AT": 0.7}, {"DE": 0.3, "AT": 0.7}),
    ]
    return_physics = [
        (518100, 430, 28, 2650.0, {"AT": 0.7, "DE": 0.3}, {"AT": 0.7, "DE": 0.3}),
        (165300, 95, 8, 850.0, {"DE": 1.0}, {"DE": 1.0}),
    ]
    outbound_geometries = [
        [[13.369, 52.525], [13.732, 51.040]],
        [[13.732, 51.040], [16.376, 48.185]],
    ]
    return_geometries = [
        [[16.376, 48.185], [13.732, 51.040]],
        [[13.732, 51.040], [13.369, 52.525]],
    ]

    geometries: list[dict] = []
    outbound = _example_trip(
        trip_id=f"{draft_prefix}_D0_T1",
        direction=0,
        stops=[berlin, dresden, wien],
        times_min=[(None, 1264), (1367, 1372), (1830, None)],
        stop_types=["boarding", "both", "alighting"],
        segment_physics=outbound_physics,
        segment_geometries=outbound_geometries,
        geometries_out=geometries,
    )
    return_trip = _example_trip(
        trip_id=f"{draft_prefix}_D1_T1",
        direction=1,
        stops=[wien, dresden, berlin],
        times_min=[(None, 1200), (1658, 1663), (1766, None)],
        stop_types=["boarding", "both", "alighting"],
        segment_physics=return_physics,
        segment_geometries=return_geometries,
        geometries_out=geometries,
    )

    return {
        "route_id": draft_prefix,
        "scenario_id": scenario_id,
        "schedule": {
            "seasonal_schedules": [
                {"season": "summer", "frequency": "daily"},
                {"season": "winter", "frequency": "daily"},
            ]
        },
        "trip_pairs": [
            {
                "composition_id": composition.comp_id,
                "composition": composition_dict,
                "od_pairs": [],
                "outbound": outbound,
                "return_trip": return_trip,
            }
        ],
        "parkings": [
            {
                "stop_id": "AT_WIEN_HBF",
                "stop_name": "Wien Hbf",
                "country_code": "AT",
                "trip_ids": [f"{draft_prefix}_D0_T1"],
            },
            {
                "stop_id": "DE_BERLIN_HBF",
                "stop_name": "Berlin Hbf",
                "country_code": "DE",
                "trip_ids": [f"{draft_prefix}_D1_T1"],
            },
        ],
        "shuntings": [
            {
                "stop_id": "DE_BERLIN_HBF",
                "stop_name": "Berlin Hbf",
                "country_code": "DE",
                "trip_id": f"{draft_prefix}_D0_T1",
            },
            {
                "stop_id": "AT_WIEN_HBF",
                "stop_name": "Wien Hbf",
                "country_code": "AT",
                "trip_id": f"{draft_prefix}_D0_T1",
            },
            {
                "stop_id": "AT_WIEN_HBF",
                "stop_name": "Wien Hbf",
                "country_code": "AT",
                "trip_id": f"{draft_prefix}_D1_T1",
            },
            {
                "stop_id": "DE_BERLIN_HBF",
                "stop_name": "Berlin Hbf",
                "country_code": "DE",
                "trip_id": f"{draft_prefix}_D1_T1",
            },
        ],
        "track_infrastructure": [
            _track_physics_dict(tracks.get(cc)) for cc in ("AT", "DE")
        ],
        "geometries": geometries,
    }


# The seeded example lands on proposal_id=1 naturally — the first-ever
# INSERT into proposals.proposals on a fresh DB, no reservation needed.
# This is collision-free because tests/conftest.py's session route
# fixtures use draft proposal_id placeholders 100+ (see the range
# convention documented there), not 1-4 as they once did. Documentation
# only below (not read anywhere in this file) — kept in sync with the
# same-named constant in tests/test_50_proposals_api.py, which does use
# it, to make the shared convention explicit in both places.
_SEED_PROPOSAL_ID = 1


def seed_example_proposal(cur, conn) -> None:
    """
    Seeds one real, saved proposal (Berlin Hbf -> Dresden Hbf -> Wien Hbf)
    through the exact same code path a live POST /api/proposal uses —
    ProposalRepository.save() — so the demo GTFS rows and the
    proposals.proposals row that owns them are structurally identical to
    a real save, not a hand-maintained parallel representation. Must run
    after conn.commit() so the users/scenario/composition/track rows it
    reads are visible to the separate connections ProposalRepository and
    DBDataLoader open.

    Best-effort: an illustrative example isn't load-bearing the way
    input_params/admin data is. A failure here is logged and swallowed
    rather than aborting the rest of seeding.
    """
    try:
        import sys
        from pathlib import Path

        # db/dev/seed.py -> backend/ is two levels up. Only the standalone
        # Mathesar dev stack (db/dev/docker-compose.yml) lacks this
        # entirely — its own Dockerfile copies just seed.py/sql_loader.py/
        # sql/, not the rest of the backend tree — so the import below is
        # expected to fail there and is caught below.
        backend_root = Path(__file__).resolve().parents[2]
        if str(backend_root) not in sys.path:
            sys.path.insert(0, str(backend_root))

        from adapters.proposal_repository import ProposalRepository
        from adapters.data_loader_from_db import DBDataLoader
    except ImportError:
        print(
            "Seeding example proposal... skipped (adapters/ not present in "
            "this image — expected on the standalone db/dev docker-compose "
            "stack, which only ships seed.py itself, not the rest of the "
            "backend tree)."
        )
        return

    print("Seeding example proposal...")
    try:
        cur.execute(
            "SELECT scenario_id FROM scenario.scenarios WHERE is_current_base = TRUE"
        )
        scenario_id = cur.fetchone()[0]
        cur.execute(
            "SELECT user_id FROM admin.users WHERE email = %s",
            ("david@backontrack.eu",),
        )
        user_id = cur.fetchone()[0]

        loader = DBDataLoader()
        try:
            composition = loader.build_all_compositions(scenario_id).get("STD-7.1")
            tracks = loader.build_all_tracks(scenario_id)
        finally:
            loader.close()

        route = _build_example_route(scenario_id, composition, tracks)
        route_body = {
            "route_builder_version": "seed",
            # The conceptual request that would have produced this route —
            # save() now requires the whole POST /api/route/plan response,
            # not just its route section, so this can't be omitted/None.
            "request": {
                "stops": ["DE_BERLIN_HBF", "DE_DRESDEN_HBF", "AT_WIEN_HBF"],
                "composition_id": "STD-7.1",
                "routing_mode": "fullRouting",
                "timetable_mode": "simpleAutomatic",
                "schedule_mode": "alwaysDaily",
                "auto_stop_addition": "off",
            },
            "route": route,
        }

        repo = ProposalRepository()
        try:
            repo.save(
                route_body=route_body,
                user_id=user_id,
                change_log="Seed data — illustrative example proposal.",
                evaluation_body=None,
            )
        finally:
            repo.close()
    except Exception as e:
        print(f"  WARNING: example proposal seed failed, skipping: {e}")
        conn.rollback()


def main():
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )
    print(f"Connected to '{DB_NAME}' at {DB_HOST}:{DB_PORT}")
    cur = conn.cursor()

    print("Creating schemas...")
    cur.execute(load_sql("create_admin_schema.sql"))
    cur.execute(load_sql("create_input_params_schema.sql"))
    cur.execute(load_sql("create_scenario_schema.sql"))
    cur.execute(load_sql("create_proposal_schema.sql"))

    print("Seeding admin.users...")
    insert_rows(cur, "admin.users", USERS)

    print("Seeding input_params.sources...")
    insert_rows(cur, "input_params.sources", SOURCES)
    source_ids = fetch_source_ids(cur)

    print("Seeding input_params.countries...")
    insert_rows(cur, "input_params.countries", COUNTRIES)
    seed_country_geometries(cur)

    print("Seeding input_params.service_classes...")
    insert_rows(cur, "input_params.service_classes", SERVICE_CLASSES)

    print("Seeding input_params.operators...")
    insert_rows(cur, "input_params.operators", OPERATORS)
    seed_operator_class_costs(cur)

    print("Seeding input_params.coach_types...")
    insert_rows(cur, "input_params.coach_types", COACH_TYPES)
    seed_coach_type_classes(cur)

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
    seed_composition_type_coaches(cur)
    seed_composition_references(cur)

    print("Injecting source IDs...")
    seed_sources(cur, source_ids)

    print("Seeding scenario.scenarios...")
    insert_rows(
        cur,
        "scenario.scenarios",
        [HISTORICAL_SCENARIO_2026, BASE_SCENARIO, HSR_SCENARIO],
    )

    conn.commit()

    # Must run after commit — it opens its own connections (via
    # ProposalRepository/DBDataLoader) and needs the users/scenario rows
    # above to already be visible to them.
    seed_example_proposal(cur, conn)

    print("\nDone. Row counts:")
    for schema, table in [
        ("admin", "users"),
        ("input_params", "sources"),
        ("input_params", "countries"),
        ("input_params", "service_classes"),
        ("input_params", "operators"),
        ("input_params", "operator_class_costs"),
        ("input_params", "coach_types"),
        ("input_params", "coach_type_classes"),
        ("input_params", "track_infrastructure_defaults"),
        (
            "input_params",
            "track_infrastructures",
        ),  # 84 rows: 3 full snapshots x 28 countries
        ("input_params", "stop_infrastructure_defaults"),
        ("input_params", "stop_infrastructures"),
        ("input_params", "composition_types"),
        ("input_params", "composition_type_coaches"),
        ("input_params", "composition_references"),
        ("scenario", "scenarios"),
        ("proposals", "proposals"),
        ("proposals", "routes"),
        ("proposals", "trips"),
        ("proposals", "stop_times"),
        ("proposals", "shapes"),
        ("proposals", "services"),
    ]:
        cur.execute(f"SELECT COUNT(*) FROM {schema}.{table}")
        print(f"  {schema}.{table}: {cur.fetchone()[0]} rows")

    cur.execute(
        "SELECT COUNT(*) FROM input_params.countries WHERE country_geom IS NOT NULL"
    )
    print(f"  input_params.countries: {cur.fetchone()[0]} rows have country_geom")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()