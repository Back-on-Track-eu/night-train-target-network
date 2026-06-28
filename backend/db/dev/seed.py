"""
seed.py
=======
Entry point for seeding the Back-on-Track night train database.

Shared utilities (insert_rows, JSON encoder) live here and are imported
by the sub-seeders. Schema DDL lives in sql/*.sql via sql_loader.

Sub-seeders:
  seed_admin.py        → admin schema
  seed_input_params.py → input_params schema
  seed_proposals.py    → proposals schema

Idempotent — each schema file starts with DROP SCHEMA ... CASCADE.

Run from backend/db/dev/:
  python seed.py
"""

import json
import os
from datetime import timedelta
from decimal import Decimal

import psycopg2
from dotenv import load_dotenv

load_dotenv()

from sql_loader import load_sql
import seed_admin as _seed_admin_mod
import seed_input_params as _seed_input_params_mod
import seed_proposals as _seed_proposals_mod

DB_HOST     = os.environ["POSTGRES_HOST"]
DB_PORT     = os.environ["POSTGRES_PORT"]
DB_NAME     = os.environ["POSTGRES_DB"]
DB_USER     = os.environ["POSTGRES_USER"]
DB_PASSWORD = os.environ["POSTGRES_PASSWORD"]


# ============================================================
# Shared utilities (imported by sub-seeders)
# ============================================================

class _PgEncoder(json.JSONEncoder):
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
    """Generic seeder: builds INSERT INTO table (...) VALUES (%s, ...) from
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
# Row count reporter
# ============================================================

_COUNT_TABLES = [
    ("admin",        "users"),
    ("admin",        "auth_tokens"),
    ("input_params", "sources"),
    ("input_params", "countries"),
    ("input_params", "service_classes"),
    ("input_params", "operators"),
    ("input_params", "operator_class_costs"),
    ("input_params", "coach_types"),
    ("input_params", "coach_type_classes"),
    ("input_params", "track_infrastructure_defaults"),
    ("input_params", "track_infrastructures"),       # 8 rows: 7 current + 1 old DE
    ("input_params", "stop_infrastructure_defaults"),
    ("input_params", "stop_infrastructures"),
    ("input_params", "composition_types"),
    ("input_params", "composition_type_coaches"),
    ("input_params", "composition_references"),
    ("proposals",    "services"),
    ("proposals",    "calendar"),
    ("proposals",    "calendar_dates"),
    ("proposals",    "shapes"),
    ("proposals",    "routes"),
    ("proposals",    "trips"),
    ("proposals",    "stop_times"),
]


def _print_row_counts(cur) -> None:
    print("\nDone. Row counts:")
    for schema, table in _COUNT_TABLES:
        cur.execute(f"SELECT COUNT(*) FROM {schema}.{table}")
        print(f"  {schema}.{table}: {cur.fetchone()[0]} rows")


# ============================================================
# Main
# ============================================================

def main() -> None:
    conn = psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASSWORD,
    )
    print(f"Connected to '{DB_NAME}' at {DB_HOST}:{DB_PORT}")
    cur = conn.cursor()

    print("Creating schemas...")
    cur.execute(load_sql("create_admin_schema.sql"))
    cur.execute(load_sql("create_input_params_schema.sql"))
    cur.execute(load_sql("create_proposal_schema.sql"))

    _seed_admin_mod.seed_admin(cur, insert_rows)
    _seed_input_params_mod.seed_input_params(cur, insert_rows)
    _seed_proposals_mod.seed_proposals(cur, insert_rows)

    conn.commit()
    _print_row_counts(cur)

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()