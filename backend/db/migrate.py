"""
migrate.py — apply pending SQL migrations to a server database.
================================================================

The contract this script exists for (agreed 2026-07-23):

  * ``dev/sql/create_*.sql`` + ``dev/seed.py`` always represent the LATEST
    schema and are for LOCAL databases only (seed drops and recreates).
  * Server databases (staging, production) are NEVER reseeded. They move
    forward exclusively through ``dev/sql/migrations/*.sql``, applied in
    filename order (the ``YYYY-MM-DD_name.sql`` prefix sorts chronologically).
  * Deploys run this script before the API starts, so a deployed backend can
    never meet a database missing its schema changes (the failure mode of the
    frozen 23-jun production database).

Which migrations a database already has is recorded in
``admin.schema_migrations`` (one row per applied filename). The table is
created by this script on first contact — deliberately not a migration
itself, since it is the thing that makes migrations trackable.

Each migration is applied in a single transaction TOGETHER WITH its tracking
row, so a crash can never leave a migration applied-but-unrecorded or
recorded-but-unapplied. Because of that outer transaction, migration files
must not manage their own: standalone ``BEGIN;``/``COMMIT;``/``ROLLBACK;``
lines are stripped before execution (the 2026-07-14 file predates this
convention and carries its own pair) — new migration files should simply
omit them.

Existing databases predate the tracking table. Bring one up to date with
``--baseline``: every migration file currently in the folder is recorded as
applied WITHOUT being executed. Use it exactly once per database whose schema
already contains the changes (a fresh seed from create_*.sql, or a server DB
that received the files by hand), then never again.

Usage:
    python db/migrate.py              # apply pending migrations
    python db/migrate.py --dry-run    # list pending, change nothing
    python db/migrate.py --check      # exit 2 if pending (deploy assertion)
    python db/migrate.py --baseline   # record all as applied, execute nothing

Connection comes from the same environment variables seed.py uses:
POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD.
"""

import argparse
import os
import re
import sys
from pathlib import Path

import psycopg2

MIGRATIONS_DIR = Path(__file__).parent / "dev" / "sql" / "migrations"

TRACKING_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS admin.schema_migrations (
    filename    TEXT PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

# Standalone transaction-control lines (see module docstring). Matched only
# at line start so e.g. a COMMENT mentioning "COMMIT;" mid-line survives.
_TX_CONTROL = re.compile(
    r"^\s*(BEGIN|COMMIT|ROLLBACK)\s*;\s*$", re.IGNORECASE | re.MULTILINE
)


def _connect():
    missing = [
        name
        for name in (
            "POSTGRES_HOST",
            "POSTGRES_PORT",
            "POSTGRES_DB",
            "POSTGRES_USER",
            "POSTGRES_PASSWORD",
        )
        if not os.environ.get(name)
    ]
    if missing:
        sys.exit(f"migrate.py: missing environment variable(s): {', '.join(missing)}")
    return psycopg2.connect(
        host=os.environ["POSTGRES_HOST"],
        port=os.environ["POSTGRES_PORT"],
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
    )


def _ensure_tracking_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(TRACKING_TABLE_SQL)
    conn.commit()


def _applied(conn) -> set:
    with conn.cursor() as cur:
        cur.execute("SELECT filename FROM admin.schema_migrations")
        return {row[0] for row in cur.fetchall()}


def _pending(conn) -> list:
    files = sorted(p.name for p in MIGRATIONS_DIR.glob("*.sql"))
    applied = _applied(conn)
    unknown = applied - set(files)
    if unknown:
        # Recorded but no longer in the folder — history must never be
        # rewritten or removed, so treat this as corruption and stop.
        sys.exit(
            "migrate.py: schema_migrations records filenames missing from "
            f"{MIGRATIONS_DIR}: {', '.join(sorted(unknown))} — refusing to continue."
        )
    return [f for f in files if f not in applied]


def _apply(conn, filename: str) -> None:
    raw = (MIGRATIONS_DIR / filename).read_text()
    sql, n_stripped = _TX_CONTROL.subn("", raw)
    if n_stripped:
        print(
            f"  (stripped {n_stripped} transaction-control line(s) — runner owns the transaction)"
        )
    with conn.cursor() as cur:
        cur.execute(sql)
        cur.execute(
            "INSERT INTO admin.schema_migrations (filename) VALUES (%s)",
            (filename,),
        )
    conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run", action="store_true", help="list pending migrations, change nothing"
    )
    mode.add_argument(
        "--check", action="store_true", help="exit 2 if migrations are pending"
    )
    mode.add_argument(
        "--baseline",
        action="store_true",
        help="record all migration files as applied WITHOUT executing them",
    )
    args = parser.parse_args()

    conn = _connect()
    try:
        _ensure_tracking_table(conn)
        pending = _pending(conn)

        if args.dry_run or args.check:
            if not pending:
                print("migrate.py: database is up to date.")
                return
            print(f"migrate.py: {len(pending)} pending migration(s):")
            for f in pending:
                print(f"  {f}")
            if args.check:
                sys.exit(2)
            return

        if args.baseline:
            if not pending:
                print(
                    "migrate.py: nothing to baseline — all migrations already recorded."
                )
                return
            with conn.cursor() as cur:
                for f in pending:
                    cur.execute(
                        "INSERT INTO admin.schema_migrations (filename) VALUES (%s)",
                        (f,),
                    )
            conn.commit()
            print(
                f"migrate.py: baselined {len(pending)} migration(s) (recorded, NOT executed):"
            )
            for f in pending:
                print(f"  {f}")
            return

        if not pending:
            print("migrate.py: database is up to date.")
            return
        for f in pending:
            print(f"migrate.py: applying {f} ...")
            try:
                _apply(conn, f)
            except psycopg2.Error as e:
                conn.rollback()
                sys.exit(
                    f"migrate.py: FAILED on {f} — rolled back, stopping. "
                    f"Nothing after this file was attempted.\n{e}"
                )
            print("  applied.")
        print(f"migrate.py: done — {len(pending)} migration(s) applied.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
