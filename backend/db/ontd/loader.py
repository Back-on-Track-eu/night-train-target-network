"""
Load ONTD (Open Night Train Database) into the ontd schema.

Fetches the whole ONTD workbook via its public export link (Sheets
export?format=xlsx — no API key/credentials, see adapters/proposal/README.md §5.5,
decision 26) and inserts the 11 canonical tables into the REFRESHED half
of the ontd schema. The CURATED tables (composition catalog — see
composition_loader.py) are never touched here.

Bootstraps its own DDL on every run: create_ontd_schema.sql is applied
first (DROP+CREATE for refreshed tables, CREATE TABLE IF NOT EXISTS for
curated ones — see that file's header), so this script works identically
on a schema that has never existed and on a routine half-yearly refresh.

Column extraction is header-name based (case-insensitive): each canonical
table's DB column list (SCHEMA_COLS) is looked up by name in the sheet's
own header row. This is what makes the known sheet artifacts a non-issue
without special-casing — trips' trailing Chatbase/AutoCrat columns and
trip_stop's leading train_stop_id column are simply never in SCHEMA_COLS,
so they're silently skipped; routes_inactive/trips_inactive reuse their
active twin's SCHEMA_COLS (their DB tables are LIKE ... INCLUDING ALL) so
sheet-only columns on those tabs (line_name, valid_from_date, ...) are
skipped the same way, and DB columns absent on those tabs (picture,
source_interrail, ...) come back None.

Idempotent: refreshed tables are dropped/recreated (via the DDL
bootstrap) before each load. Never touches admin / input_params /
scenario / proposals, and never touches the curated ontd tables.

Usage:
    python db/ontd/loader.py                  # fetch the live sheet (default)
    python db/ontd/loader.py --xlsx /path.xlsx # load from a local export

Run from the API container:
    docker exec night-train-api python db/ontd/loader.py
"""

import argparse
from pathlib import Path
from typing import Any, Optional

from connection import connect

from projection import build_summaries
from psycopg2.extras import RealDictCursor
from xlsx_utils import (
    is_blank,
    workbook_url,
    load_workbook,
    sheet_row_dicts,
    to_bool,
    to_clock,
    to_date,
    to_duration,
    to_float,
    to_int,
    to_text,
)

SCHEMA_SQL = Path(__file__).parent / "sql" / "create_ontd_schema.sql"


# Load order respects FK constraints (agencies before routes/trips before
# trip_stop; calendar before calendar_dates).
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

# routes_inactive/trips_inactive share their active twin's DB columns
# (LIKE ontd.routes/trips INCLUDING ALL) — reusing the same SCHEMA_COLS
# entry rather than hand-duplicating it is what keeps the loader from
# drifting out of sync with the DDL, and what makes the sheet's diverging
# inactive-tab columns (line_name, valid_from_date, destination_trip_1, …)
# fall out for free during header-name extraction.
TABLE_ALIASES = {"routes_inactive": "routes", "trips_inactive": "trips"}

# Canonical DB column names per table (must match create_ontd_schema.sql
# exactly — this is the single source for both SELECT-by-header-name and
# the INSERT column list).
SCHEMA_COLS: dict[str, list[str]] = {
    "agencies": [
        "agency_id",
        "agency_name",
        "agency_url",
        "agency_timezone",
        "agency_lang",
        "agency_phone",
        "agency_fare_url",
        "agency_email",
        "agency_name_romanized",
        "agency_name_brand",
        "agency_state",
        "agency_logo_url",
        "agency_conditions_groups",
        "agency_conditions_children",
    ],
    "stops": [
        "stop_id",
        "stop_name",
        "stop_country",
        "stop_timezone",
        "stop_lat",
        "stop_lon",
        "location_type",
        "stop_name_romanized",
        "stop_name_alt",
        "stop_cityname",
        "stop_cityname_romanized",
        "stop_cityname_alt",
        "stop_tariffname",
        "stop_charge",
        "stop_uic_code",
        "stop_code",
        "stop_region",
    ],
    "routes": [
        "route_id",
        "agency_id",
        "agency_1",
        "agency_2",
        "agency_3",
        "route_short_name",
        "route_long_name",
        "route_desc",
        "route_type",
        "version",
        "is_active",
        "origin_trip_0",
        "destination_trip_0",
        "distance",
        "emissions",
        "classes",
        "countries",
        "source",
        "source_interrail",
        "picture",
        "emissions_relation",
    ],
    "trips": [
        "route_id",
        "agency_id",
        "trip_id",
        "trip_origin",
        "origin_departure_time",
        "trip_headsign",
        "destination_arrival_time",
        "trip_short_name",
        "direction_id",
        "version",
        "countries",
        "is_active",
        "irregularities",
        "service_id",
        "classes",
        "connections",
        "catering",
        "plugs",
        "wheelchair_accessible",
        "bikes_allowed",
        "car_transport",
        "duration",
        "distance",
        "emissions_co2e",
        "co2_per_km",
        "via",
    ],
    "trip_stop": [
        "trip_id",
        "stop_sequence",
        "stop_id",
        "arrival_time",
        "departure_time",
        "no_exit",
        "no_entry",
        "border_control",
    ],
    "calendar": [
        "service_id",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
        "start_date",
        "end_date",
    ],
    "calendar_dates": [
        "uid",
        "train_id",
        "service_id",
        "date",
        "date_from",
        "date_until",
        "exception_type",
    ],
    "classes": ["class_id", "class_main"],
    "translations": [
        "table_name",
        "field_name",
        "language_code",
        "translation",
        "record_id",
        "field_value",
    ],
}

BOOL_COLS: dict[str, set[str]] = {
    "routes": {"is_active"},
    "trips": {"is_active"},
    "trip_stop": {"no_exit", "no_entry", "border_control"},
    "calendar": {
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    },
}

INT_COLS: dict[str, set[str]] = {
    "trip_stop": {"stop_sequence"},  # MUST be INTEGER — TEXT here previously
    # inflated network_km 4.6x (sort order bug, see db/README.md history)
    "trips": {
        "direction_id",
        "wheelchair_accessible",
        "bikes_allowed",
        "car_transport",
    },
    "routes": {"route_type"},
    "calendar_dates": {"exception_type"},
    "stops": {"location_type"},
}

FLOAT_COLS: dict[str, set[str]] = {
    "stops": {"stop_lat", "stop_lon"},
    "routes": {"distance", "emissions"},
    "trips": {"distance", "emissions_co2e", "co2_per_km"},
}

# Clock-time cells (openpyxl returns datetime.time for these on a
# correctly-typed sheet) — serialized to the schema's HH:MM TEXT
# convention.
TIME_COLS: dict[str, set[str]] = {
    "trips": {"origin_departure_time", "destination_arrival_time"},
    "trip_stop": {"arrival_time", "departure_time"},
}

# Duration cells (openpyxl returns datetime.timedelta) — serialized with
# hours NOT wrapped at 24 (a multi-day trip duration like 25:03 is valid;
# datetime.time/strftime can't represent that, hence the manual format).
DURATION_COLS: dict[str, set[str]] = {"trips": {"duration"}}

# Date-only cells (openpyxl returns datetime.datetime at midnight) —
# reduced to datetime.date for the schema's DATE columns.
DATE_COLS: dict[str, set[str]] = {
    "calendar": {"start_date", "end_date"},
    "calendar_dates": {"date", "date_from", "date_until"},
}


def _coerce(canonical_table: str, col: str, val: Any) -> Any:
    """Cast one cell to the type its DB column expects. canonical_table
    resolves routes_inactive/trips_inactive to their active twin (see
    TABLE_ALIASES) before looking up the column-kind sets."""
    if col in BOOL_COLS.get(canonical_table, ()):
        return to_bool(val)
    if col in INT_COLS.get(canonical_table, ()):
        return to_int(val)
    if col in FLOAT_COLS.get(canonical_table, ()):
        return to_float(val)
    if col in TIME_COLS.get(canonical_table, ()):
        return to_clock(val)
    if col in DURATION_COLS.get(canonical_table, ()):
        return to_duration(val)
    if col in DATE_COLS.get(canonical_table, ()):
        return to_date(val)
    return to_text(val)


# =============================================================================
# Load
# =============================================================================


_DAY_COLS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


def _is_calendar_separator(row: dict[str, Any]) -> bool:
    """The calendar tab carries section headers ('-- 2025 --', 'Unknown')
    with no day flags at all. They aren't services; dropping them here
    keeps the load's warnings meaningful instead of routine."""
    return all(is_blank(row.get(col)) for col in _DAY_COLS)


def get_valid_agency_ids(cur) -> set[str]:
    cur.execute("SELECT agency_id FROM ontd.agencies")
    return {r[0] for r in cur.fetchall()}


def load_table(
    cur,
    table: str,
    row_dicts: list[dict[str, Any]],
    valid_agency_ids: Optional[set[str]] = None,
) -> tuple[int, int]:
    canonical = TABLE_ALIASES.get(table, table)
    cols = SCHEMA_COLS[canonical]
    placeholders = ", ".join(["%s"] * len(cols))
    col_names = ", ".join(cols)
    sql = f"INSERT INTO ontd.{table} ({col_names}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"

    inserted = skipped = 0
    for row in row_dicts:
        values = []
        for col in cols:
            val = _coerce(canonical, col, row.get(col))
            # Nullify compound agency_ids (e.g. 'PKP/ČD') — not in agencies table
            if col == "agency_id" and valid_agency_ids and val not in valid_agency_ids:
                val = None
            values.append(val)
        cur.execute("SAVEPOINT sp")
        try:
            cur.execute(sql, values)
            cur.execute("RELEASE SAVEPOINT sp")
            inserted += 1
        except Exception as e:
            cur.execute("ROLLBACK TO SAVEPOINT sp")
            skipped += 1
            pk_hint = (
                row.get("trip_id")
                or row.get("route_id")
                or row.get("stop_id")
                or row.get("service_id")
                or row.get("agency_id")
                or "?"
            )
            print(f"  WARNING: ontd.{table} row skipped (pk≈{pk_hint!r}): {e}")

    return inserted, skipped


def report_orphaned_route_compositions(cur) -> None:
    """Curated table (route_compositions) vs. the just-refreshed routes
    table — route_ids are a stable natural key across refreshes (decision
    26), but a route can still be retired from the sheet entirely."""
    cur.execute(
        "SELECT rc.route_id FROM ontd.route_compositions rc "
        "LEFT JOIN ontd.routes r ON r.route_id = rc.route_id "
        "WHERE r.route_id IS NULL ORDER BY rc.route_id"
    )
    orphans = [row[0] for row in cur.fetchall()]
    if orphans:
        print(
            f"\nWARNING: {len(orphans)} ontd.route_compositions row(s) reference "
            f"route_ids no longer in ontd.routes (curated assignment left as-is): "
            f"{orphans}"
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--xlsx", help="Path to a local ONTD .xlsx export (skips the network fetch)"
    )
    parser.add_argument(
        "--no-geometry",
        action="store_true",
        help="Skip routing when rebuilding route_summaries (straight-line geometry)",
    )
    args = parser.parse_args()

    conn = connect()
    cur = conn.cursor()

    print(
        "Bootstrapping ontd schema (refreshed tables dropped/recreated, "
        "curated tables left untouched if present)..."
    )
    cur.execute(SCHEMA_SQL.read_text(encoding="utf-8"))

    url = (
        None
        if args.xlsx
        else workbook_url(
            "ONTD_WORKBOOK_ID",
            "ONTD_WORKBOOK_KIND",
            "the ONTD timetable workbook (agencies, stops, routes, trips, …)",
        )
    )
    wb = load_workbook(url=url, path=args.xlsx)
    try:
        sheets = {table: sheet_row_dicts(wb[table]) for table in TABLES}
    finally:
        wb.close()
    for table, rows in sheets.items():
        print(f"  read ontd tab '{table}': {len(rows)} data rows")

    separators = [r for r in sheets["calendar"] if _is_calendar_separator(r)]
    if separators:
        sheets["calendar"] = [
            r for r in sheets["calendar"] if not _is_calendar_separator(r)
        ]
        print(f"  (skipped {len(separators)} calendar separator row(s))")

    print("\nInserting...\n")
    total_inserted = 0
    for table in TABLES:
        valid_agency_ids = (
            get_valid_agency_ids(cur)
            if table in ("routes", "trips", "routes_inactive", "trips_inactive")
            else None
        )
        inserted, skipped = load_table(cur, table, sheets[table], valid_agency_ids)
        print(f"  ontd.{table}: {inserted} rows inserted, {skipped} skipped")
        total_inserted += inserted

    report_orphaned_route_compositions(cur)

    print("\nRebuilding ontd.route_summaries projection...\n")
    written, routed = build_summaries(
        conn.cursor(cursor_factory=RealDictCursor), with_geometry=not args.no_geometry
    )
    print(
        f"  {written} active routes, {routed} with routed geometry, "
        f"{written - routed} on straight-line fallback"
    )

    conn.commit()
    cur.close()
    conn.close()
    print(f"\nDone — {total_inserted} total rows loaded into ontd schema.")


if __name__ == "__main__":
    main()
