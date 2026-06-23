"""
Load ONTD (Open Night Train Database) into the ontd schema.

Fetches the 11 canonical tables from the public GitHub snapshot and inserts
into the ontd.* tables created by create_ontd_schema.sql.

Idempotent: TRUNCATEs all ontd tables before each load (CASCADE handles FKs).
Does NOT touch admin / input_params / proposals schemas.

Usage:
    python db/dev/ontd_loader.py                  # fetch from GitHub (default)
    python db/dev/ontd_loader.py --local /path    # load from local data/latest/

Run from the API container:
    docker exec night-train-api python db/dev/ontd_loader.py
"""

import argparse
import json
import os
import urllib.request
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv()

GITHUB_BASE = (
    "https://raw.githubusercontent.com/Back-on-Track-eu/"
    "night-train-data/main/data/latest"
)

# Load order respects FK constraints
TABLES = [
    "agencies",
    "stops",
    "classes",
    "calendar",
    "routes",
    "trips",
    "trip_stop",
    "calendar_dates",
    "translations",
    "routes_inactive",
    "trips_inactive",
]

# Columns to drop per table (Sheet artifacts)
DROP_COLS = {
    "trips": {
        "Merged Doc ID - ONTD_Chatbase_Export",
        "Merged Doc URL - ONTD_Chatbase_Export",
        "Link to merged Doc - ONTD_Chatbase_Export",
        "Document Merge Status - ONTD_Chatbase_Export",
        "",
    },
    "trip_stop": {"qqa`", ""},
    "agencies": {""},
}

# Schema column names (must match create_ontd_schema.sql exactly)
SCHEMA_COLS = {
    "agencies": [
        "agency_id","agency_name","agency_url","agency_timezone","agency_lang",
        "agency_phone","agency_fare_url","agency_email","agency_name_romanized",
        "agency_name_brand","agency_state","agency_logo_url",
        "agency_conditions_groups","agency_conditions_children",
    ],
    "stops": [
        "stop_id","stop_name","stop_country","stop_timezone","stop_lat","stop_lon",
        "location_type","stop_name_romanized","stop_name_alt","stop_cityname",
        "stop_cityname_romanized","stop_cityname_alt","stop_tariffname",
        "stop_charge","stop_uic_code","stop_code","stop_region",
    ],
    "routes": [
        "route_id","agency_id","agency_1","agency_2","agency_3",
        "route_short_name","route_long_name","route_desc","route_type",
        "version","is_active","origin_trip_0","destination_trip_0",
        "distance","emissions","classes","countries","source",
        "source_interrail","picture","emissions_relation",
    ],
    "trips": [
        "trip_id","route_id","agency_id","trip_origin","origin_departure_time",
        "trip_headsign","destination_arrival_time","trip_short_name",
        "direction_id","version","countries","is_active","irregularities",
        "service_id","classes","connections","catering","plugs",
        "wheelchair_accessible","bikes_allowed","car_transport",
        "duration","distance","emissions_co2e","co2_per_km","via",
    ],
    "trip_stop": [
        "trip_id","stop_sequence","stop_id","arrival_time","departure_time",
        "no_exit","no_entry","border_control",
    ],
    "calendar": [
        "service_id","monday","tuesday","wednesday","thursday","friday",
        "saturday","sunday","start_date","end_date",
    ],
    "calendar_dates": [
        "uid","train_id","service_id","date","date_from","date_until",
        "exception_type",
    ],
    "classes": ["class_id","class_main"],
    "translations": [
        "table_name","field_name","language_code","translation",
        "record_id","field_value",
    ],
    "routes_inactive": [
        "route_id","agency_id","agency_1","agency_2","agency_3",
        "route_short_name","route_long_name","route_desc","route_type",
        "version","is_active","origin_trip_0","destination_trip_0",
        "distance","emissions","classes","countries","source",
        "source_interrail","picture","emissions_relation",
    ],
    "trips_inactive": [
        "trip_id","route_id","agency_id","trip_origin","origin_departure_time",
        "trip_headsign","destination_arrival_time","trip_short_name",
        "direction_id","version","countries","is_active","irregularities",
        "service_id","classes","connections","catering","plugs",
        "wheelchair_accessible","bikes_allowed","car_transport",
        "duration","distance","emissions_co2e","co2_per_km","via",
    ],
}

BOOL_COLS = {
    "routes": {"is_active"},
    "trips": {"is_active"},
    "trips_inactive": {"is_active"},
    "routes_inactive": {"is_active"},
    "trip_stop": {"no_exit","no_entry","border_control"},
    "calendar": {"monday","tuesday","wednesday","thursday","friday","saturday","sunday"},
}

INT_COLS = {
    "trip_stop": {"stop_sequence"},
    "trips": {"direction_id","wheelchair_accessible","bikes_allowed","car_transport"},
    "trips_inactive": {"direction_id","wheelchair_accessible","bikes_allowed","car_transport"},
    "routes": {"route_type"},
    "routes_inactive": {"route_type"},
    "calendar_dates": {"exception_type"},
    "stops": {"location_type"},
}

FLOAT_COLS = {
    "stops": {"stop_lat","stop_lon"},
    "routes": {"distance","emissions"},
    "routes_inactive": {"distance","emissions"},
    "trips": {"distance","emissions_co2e","co2_per_km"},
    "trips_inactive": {"distance","emissions_co2e","co2_per_km"},
}


def _coerce(table, col, val):
    """Cast value to the correct Python type for the DB column."""
    if val == "" or val is None:
        return None
    if col in BOOL_COLS.get(table, set()):
        if isinstance(val, bool):
            return val
        return str(val).strip().upper() in ("TRUE","1","YES","T")
    if col in INT_COLS.get(table, set()):
        try:
            return int(str(val).strip())
        except (ValueError, TypeError):
            return None
    if col in FLOAT_COLS.get(table, set()):
        try:
            return float(str(val).replace(",",".").strip())
        except (ValueError, TypeError):
            return None
    return val if val != "" else None


def fetch_json(table, local_dir=None):
    if local_dir:
        path = Path(local_dir) / f"{table}.json"
        with open(path) as f:
            raw = json.load(f)
    else:
        url = f"{GITHUB_BASE}/{table}.json"
        with urllib.request.urlopen(url) as r:
            raw = json.load(r)
    # Data is dict-keyed (row index → row dict)
    if isinstance(raw, dict):
        return list(raw.values())
    return raw


def get_valid_agency_ids(cur):
    cur.execute("SELECT agency_id FROM ontd.agencies")
    return {r[0] for r in cur.fetchall()}


def load_table(cur, table, rows, cols, valid_agency_ids=None):
    drop = DROP_COLS.get(table, set())
    placeholders = ", ".join(["%s"] * len(cols))
    col_names = ", ".join(cols)
    sql = f"INSERT INTO ontd.{table} ({col_names}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"

    inserted = 0
    skipped = 0
    for row in rows:
        values = []
        for col in cols:
            raw = row.get(col)
            if col in drop:
                continue
            val = _coerce(table, col, raw)
            # Nullify compound agency_ids (e.g. 'PKP/ČD') — not in agencies table
            if col == "agency_id" and valid_agency_ids and val not in valid_agency_ids:
                val = None
            values.append(val)
        cur.execute("SAVEPOINT sp")
        try:
            cur.execute(sql, values)
            cur.execute("RELEASE SAVEPOINT sp")
            inserted += 1
        except Exception:
            cur.execute("ROLLBACK TO SAVEPOINT sp")
            skipped += 1

    return inserted, skipped


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--local", help="Path to local data/latest/ directory")
    args = parser.parse_args()

    conn = psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=os.environ.get("POSTGRES_PORT", 5432),
        dbname=os.environ.get("POSTGRES_DB", "night_train_db"),
        user=os.environ.get("POSTGRES_USER", "nighttrain"),
        password=os.environ.get("POSTGRES_PASSWORD"),
    )
    conn.autocommit = False
    cur = conn.cursor()

    print("Truncating ontd schema...")
    cur.execute("""
        TRUNCATE ontd.translations, ontd.trip_stop, ontd.calendar_dates,
                 ontd.trips, ontd.trips_inactive, ontd.routes, ontd.routes_inactive,
                 ontd.calendar, ontd.stops, ontd.agencies, ontd.classes
        CASCADE
    """)

    source = f"local ({args.local})" if args.local else "GitHub"
    print(f"Loading from {source}...\n")

    total_inserted = 0
    for table in TABLES:
        cols = SCHEMA_COLS[table]
        try:
            rows = fetch_json(table, args.local)
        except Exception as e:
            print(f"  ontd.{table}: SKIPPED (could not fetch — {e})")
            continue
        valid_agency_ids = get_valid_agency_ids(cur) if table in ("routes","trips","routes_inactive","trips_inactive") else None
        inserted, skipped = load_table(cur, table, rows, cols, valid_agency_ids)
        print(f"  ontd.{table}: {inserted} rows inserted, {skipped} skipped")
        total_inserted += inserted

    conn.commit()
    cur.close()
    conn.close()
    print(f"\nDone — {total_inserted} total rows loaded into ontd schema.")


if __name__ == "__main__":
    main()
