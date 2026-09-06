"""
migrate_scenarios_2026.py — install the Infra 2026 scenario set on a server.
============================================================================

Servers are never reseeded (db/README.md), so the scenario restructure that
`db/dev/seed.py` performs by rebuilding from scratch has to be applied to
staging and production as a data migration. It is not a SQL migration
because the rows it writes ARE the seed's own data structures — hand-copying
28 countries × 5 tables into a .sql file would fork the calibration.

Two phases, deliberately separated by a proposal refresh:

  --install       write the new snapshots and scenario rows, move the base
  (refresh)       scripts/refresh_proposals.py repoints every proposal onto
                  the new base — the old scenario rows are still present
                  and still resolvable while this runs
  --delete-old    remove the old scenario rows and their snapshot versions

The order matters and is not negotiable. proposals.proposals.scenario_id has
NO foreign key, so deleting a scenario row does not fail — it strands every
proposal that pins it, because reads rebuild input.parameters through that
pin and _resolve_scenario_versions() raises on a missing row. --delete-old
refuses to run while any proposal, summary or cache row still references an
old scenario.

Version numbers on a server will NOT match a freshly seeded dev database:
the new snapshots are appended after whatever versions already exist. That
is cosmetic — scenario_id is the handle every consumer uses, and versions
are resolved through it, never assumed.

Usage (from backend/, with the stack's POSTGRES_* environment):
    uv run python scripts/migrate_scenarios_2026.py --install --dry-run
    uv run python scripts/migrate_scenarios_2026.py --install
    uv run python scripts/refresh_proposals.py
    uv run python scripts/migrate_scenarios_2026.py --delete-old --dry-run
    uv run python scripts/migrate_scenarios_2026.py --delete-old
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.dev.seed import (  # noqa: E402
    BASE_SCENARIO,
    HSR_SCENARIO,
    OPT_TT_SCENARIO,
    PASSAGE_CHARGES,
    STOP_INFRA_DEFAULTS,
    STOP_INFRASTRUCTURES,
    TRACK_INFRA_DEFAULTS,
    TRACK_INFRASTRUCTURES,
    insert_rows,
)
from dev_env import db_config  # noqa: E402

# The scenarios this script installs, in seed order. The superseded
# revision (version 4 in the seed) is deliberately NOT installed: it exists
# in dev to keep the scenario-override tests honest, and a server already
# has its own history in the rows this migration retires.
NEW_SCENARIOS = (BASE_SCENARIO, HSR_SCENARIO, OPT_TT_SCENARIO)

# Every versioned table, with its version column and the seed rows it takes.
# One entry per table keeps the offset arithmetic in one place — a table
# missed here would silently install a scenario pinning a version that does
# not exist.
VERSIONED_TABLES = (
    (
        "input_params.track_infrastructures",
        "track_infra_version",
        TRACK_INFRASTRUCTURES,
    ),
    (
        "input_params.track_infrastructure_defaults",
        "track_infra_default_version",
        TRACK_INFRA_DEFAULTS,
    ),
    ("input_params.stop_infrastructures", "stop_infra_version", STOP_INFRASTRUCTURES),
    (
        "input_params.stop_infrastructure_defaults",
        "stop_infra_default_version",
        STOP_INFRA_DEFAULTS,
    ),
    ("input_params.passage_charges", "passage_version", PASSAGE_CHARGES),
)

# The seed version numbers the three installed scenarios use. Rows carrying
# any other version (4, the superseded revision) are not migrated.
SEED_VERSIONS = (1, 2, 3)

# Tables whose scenario_id must no longer point at a retired scenario
# before --delete-old will proceed.
SCENARIO_REFERENCES = (
    "proposals.proposals",
    "proposals.proposal_summaries",
    "proposals.compute_cache_pointer",
    "proposals.compute_cache_result",
)


def _version_offset(cur) -> int:
    """Highest version currently in use across the versioned tables.

    New snapshots are appended above it so nothing already pinned is
    disturbed — the immutability contract applies to server rows exactly as
    it does in dev.
    """
    highest = 0
    for table, column, _ in VERSIONED_TABLES:
        cur.execute(f"SELECT COALESCE(MAX({column}), 0) AS v FROM {table}")
        highest = max(highest, cur.fetchone()["v"])
    return highest


def _shift(rows: list[dict], column: str, offset: int) -> list[dict]:
    """Seed rows renumbered onto the server's free version range."""
    return [
        {**row, column: row[column] + offset}
        for row in rows
        if row[column] in SEED_VERSIONS
    ]


def install(cur, dry_run: bool) -> None:
    offset = _version_offset(cur)
    print(f"Highest existing version: {offset} — new snapshots start at {offset + 1}.")

    for table, column, rows in VERSIONED_TABLES:
        shifted = _shift(rows, column, offset)
        versions = sorted({row[column] for row in shifted})
        print(f"  {table}: {len(shifted)} rows at versions {versions}")
        if not dry_run:
            if table == "input_params.passage_charges":
                _insert_passages(cur, shifted)
            else:
                insert_rows(cur, table, shifted)

    scenarios = [
        {
            **scenario,
            **{
                column: scenario[column] + offset
                for column in scenario
                if column.endswith("_version")
            },
            # The base moves at the end of this phase, not before: an
            # interrupted run must leave the OLD base current rather than a
            # scenario whose snapshots may be half-written.
            "is_current_base": False,
        }
        for scenario in NEW_SCENARIOS
    ]
    print(f"  scenario.scenarios: {len(scenarios)} rows")
    if dry_run:
        print("\nDry run — nothing written.")
        return

    insert_rows(cur, "scenario.scenarios", scenarios)
    cur.execute("UPDATE scenario.scenarios SET is_current_base = FALSE")
    cur.execute(
        "UPDATE scenario.scenarios SET is_current_base = TRUE "
        "WHERE scenario_key = %s AND is_current_scenario = TRUE",
        (BASE_SCENARIO["scenario_key"],),
    )
    cur.execute(
        "UPDATE scenario.scenarios SET is_current_scenario = FALSE "
        "WHERE scenario_key NOT IN %s",
        (tuple(s["scenario_key"] for s in NEW_SCENARIOS),),
    )
    # The compute cache keys on scenario_id and is disposable by design
    # (UNLOGGED) — clearing it costs a recompute and avoids reasoning about
    # which entries survived a base move.
    cur.execute("TRUNCATE proposals.compute_cache_pointer")
    cur.execute("TRUNCATE proposals.compute_cache_result")
    print("\nInstalled. Next: uv run python scripts/refresh_proposals.py")


def _insert_passages(cur, rows: list[dict]) -> None:
    """passage_charges needs ST_GeomFromGeoJSON() around its geometry
    placeholder, so it cannot go through insert_rows() — same reason
    seed.seed_passage_charges() exists."""
    for row in rows:
        cur.execute(
            """INSERT INTO input_params.passage_charges
               (passage_id, passage_name, passage_fixed_eur,
                passage_per_passenger_eur, passage_geom, passage_version)
               VALUES (%s, %s, %s, %s, ST_GeomFromGeoJSON(%s), %s)""",
            (
                row["passage_id"],
                row["passage_name"],
                row["passage_fixed_eur"],
                row["passage_per_passenger_eur"],
                row["passage_geom"],
                row["passage_version"],
            ),
        )


def _retired_scenario_ids(cur) -> list[int]:
    cur.execute(
        "SELECT scenario_id FROM scenario.scenarios WHERE scenario_key NOT IN %s "
        "ORDER BY scenario_id",
        (tuple(s["scenario_key"] for s in NEW_SCENARIOS),),
    )
    return [row["scenario_id"] for row in cur.fetchall()]


def delete_old(cur, dry_run: bool) -> int:
    retired = _retired_scenario_ids(cur)
    if not retired:
        print("Nothing to delete — no scenarios outside the Infra 2026 set.")
        return 0
    print(f"Retired scenario_ids: {retired}")

    blocking = []
    for table in SCENARIO_REFERENCES:
        cur.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE scenario_id = ANY(%s)",
            (retired,),
        )
        count = cur.fetchone()["n"]
        if count:
            blocking.append((table, count))

    if blocking:
        print("\nREFUSING to delete — rows still reference these scenarios:")
        for table, count in blocking:
            print(f"  {table}: {count}")
        print(
            "\nRun scripts/refresh_proposals.py first; it recomputes every "
            "proposal against the new base and repoints scenario_id."
        )
        return 1

    for table, column, _ in VERSIONED_TABLES:
        cur.execute(
            f"SELECT DISTINCT {column} AS v FROM {table} "
            f"WHERE {column} NOT IN ("
            "  SELECT track_infrastructures_version FROM scenario.scenarios"
            "  UNION SELECT track_infrastructure_defaults_version FROM scenario.scenarios"
            "  UNION SELECT stop_infrastructures_version FROM scenario.scenarios"
            "  UNION SELECT stop_infrastructure_defaults_version FROM scenario.scenarios"
            "  UNION SELECT passage_charges_version FROM scenario.scenarios"
            ") ORDER BY v"
        )
        orphans = [row["v"] for row in cur.fetchall()]
        print(f"  {table}: drop versions {orphans}")

    if dry_run:
        print("\nDry run — nothing deleted.")
        return 0

    cur.execute(
        "DELETE FROM scenario.scenarios WHERE scenario_id = ANY(%s)", (retired,)
    )
    for table, column, _ in VERSIONED_TABLES:
        cur.execute(
            f"DELETE FROM {table} WHERE {column} NOT IN ("
            "  SELECT track_infrastructures_version FROM scenario.scenarios"
            "  UNION SELECT track_infrastructure_defaults_version FROM scenario.scenarios"
            "  UNION SELECT stop_infrastructures_version FROM scenario.scenarios"
            "  UNION SELECT stop_infrastructure_defaults_version FROM scenario.scenarios"
            "  UNION SELECT passage_charges_version FROM scenario.scenarios"
            ")"
        )
    print("\nOld scenarios and their snapshots deleted.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--install", action="store_true")
    group.add_argument("--delete-old", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = psycopg2.connect(**db_config())
    conn.autocommit = False
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            status = (
                install(cur, args.dry_run) or 0
                if args.install
                else delete_old(cur, args.dry_run)
            )
        if args.dry_run or status:
            conn.rollback()
        else:
            conn.commit()
        return status
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
