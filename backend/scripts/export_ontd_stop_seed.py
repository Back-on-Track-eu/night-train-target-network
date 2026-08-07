"""
export_ontd_stop_seed.py
========================
Derive db/dev/data/ontd_seed_stops.csv — the ONTD-required stops that
db/dev/seed.py seeds into input_params.stop_infrastructures alongside the
curated catalog (all snapshot versions).

This replaces the retired runtime mint in db/ontd/stop_mapping.py
(2026-08-07): instead of the bootstrap inserting missing stops into
pinned snapshot versions — which broke the compute cache's scenario-pin
invariant and never survived a reseed — the full stop set is derived
ONCE and seeded like everything else. The CSV is a derived artifact,
Drive-hosted rather than committed (no large data in the repo);
seed.py downloads it into db/dev/data/ when the local copy is absent
(file id: ONTD_SEED_STOPS_FILE_ID, defaulted in seed.py, overridable via
env — same pattern as ONTD_WORKBOOK_ID). It cannot be regenerated at
seed time: deriving it needs a loaded ontd schema, which only exists
after the bootstrap this data feeds.

Run against a database whose ontd schema is loaded (any environment
after a bootstrap — the ontd schema survives reseeds):

    cd backend
    uv run python scripts/export_ontd_stop_seed.py            # writes the CSV
    uv run python scripts/export_ontd_stop_seed.py --dry-run  # report only

Then upload the CSV to Drive as a NEW VERSION of the existing file
(Drive: right-click file → File information → Manage versions — keeps
the file id stable so no config changes), and reseed (restart the API
container; the local copy just written is used directly). Re-run after
every ONTD snapshot refresh that adds stations — build_stop_mappings()
reports unmatched stops in the bootstrap log when the CSV has gone
stale.

Derivation, mirroring the retired mint exactly:

  - candidate set: every distinct stop on an active ONTD route (the same
    population build_stop_mappings() resolves)
  - match targets: the CURATED rows of the current base scenario's
    pinned snapshot — rows whose change_log does not carry the ONTD
    provenance marker — plus each row this run derives (so two ONTD ids
    for one physical station collapse to one seed row, same as before)
  - a candidate within MATCH_RADIUS_M of a target needs no row; anything
    farther becomes a seed row with mint_tn_stop_id()'s curated-style id,
    suffix-deduplicated on collision
  - stops without coordinates, or in countries outside
    input_params.countries (the NOT NULL FK), cannot be seeded — reported
    and skipped, same stops build_stop_mappings() reports as unmapped

Candidates are processed in stop_id order, so regeneration is
deterministic. One consequence: suffix-deduplicated ids (rare) can come
out differently than a pre-2026-08-07 runtime mint produced them — a
manual ontd.stop_mappings row pointing at such an id may need a one-time
correction after the first regeneration.
"""

import argparse
import csv
import sys
from pathlib import Path

import psycopg2.extras

# db/ontd is a script directory (its modules import each other bare) —
# same sys.path bridge tests/test_38_ontd_stop_mapping.py uses.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND_ROOT / "db" / "ontd"))

from connection import connect  # noqa: E402
from stop_mapping import (  # noqa: E402
    MATCH_RADIUS_M,
    _active_ontd_stops,
    _known_countries,
    _nearest,
    mint_tn_stop_id,
)

CSV_PATH = _BACKEND_ROOT / "db" / "dev" / "data" / "ontd_seed_stops.csv"
CSV_COLUMNS = (
    "stop_id",
    "stop_name",
    "country_code",
    "stop_timezone",
    "stop_lat",
    "stop_lon",
)

# Matches db/dev/seed.py's _ONTD_SEED_CHANGE_LOG prefix — rows carrying it
# are this CSV's own output and must not be match targets when the CSV is
# regenerated (each run re-derives the full set from the curated rows).
ONTD_PROVENANCE_PREFIX = "seeded from ONTD snapshot"


def _curated_catalog(cur) -> list[dict]:
    """The pinned base snapshot minus ONTD-derived rows — the stable,
    human-curated match targets. Excluding by the provenance marker (not
    by counting) keeps regeneration idempotent whether or not a previous
    CSV has already been seeded; the retired runtime mint's marker is
    excluded too, for databases that still carry pre-2026-08-07 rows."""
    cur.execute(
        "SELECT stop_infrastructures_version FROM scenario.scenarios "
        "WHERE is_current_base"
    )
    pinned_version = cur.fetchone()["stop_infrastructures_version"]
    cur.execute(
        """
        SELECT stop_id, stop_name, stop_lat, stop_lon
          FROM input_params.stop_infrastructures
         WHERE stop_infra_version = %s
           AND (change_log IS NULL
                OR (change_log NOT LIKE %s AND change_log NOT LIKE %s))
        """,
        (pinned_version, f"{ONTD_PROVENANCE_PREFIX}%", "minted from ONTD%"),
    )
    return [dict(row) for row in cur.fetchall()]


def derive_rows(cur) -> tuple[list[dict], list[str]]:
    """(seed rows, human-readable skip reports) for the current ontd
    schema content — pure derivation, writes nothing."""
    catalog = _curated_catalog(cur)
    known_countries = _known_countries(cur)
    catalog_ids = {stop["stop_id"] for stop in catalog}

    rows: list[dict] = []
    skipped: list[str] = []

    for stop in sorted(_active_ontd_stops(cur), key=lambda s: s["stop_id"]):
        if stop["stop_lat"] is None or stop["stop_lon"] is None:
            skipped.append(f"{stop['stop_id']} {stop['stop_name']!r}: no coordinates")
            continue
        lat, lon = float(stop["stop_lat"]), float(stop["stop_lon"])

        nearest, distance = _nearest(lat, lon, catalog)
        if nearest is not None and distance <= MATCH_RADIUS_M:
            continue  # an existing (or just-derived) stop covers this station

        country = (stop["stop_country"] or "").strip().upper()
        if country not in known_countries:
            skipped.append(
                f"{stop['stop_id']} {stop['stop_name']!r}: country "
                f"{country or '?'} not in input_params.countries"
            )
            continue

        tn_id = mint_tn_stop_id(country, stop["stop_name"])
        # Same-name-different-station collision: suffix rather than merge
        # — a wrong merge corrupts corridors, a suffix is merely ugly.
        base_id, suffix = tn_id, 2
        while tn_id in catalog_ids:
            tn_id = f"{base_id}_{suffix}"
            suffix += 1

        rows.append(
            {
                "stop_id": tn_id,
                "stop_name": stop["stop_name"],
                "country_code": country,
                "stop_timezone": stop["stop_timezone"] or "Europe/Brussels",
                "stop_lat": lat,
                "stop_lon": lon,
            }
        )
        catalog_ids.add(tn_id)
        # Derived rows are match targets for later candidates, so two
        # ONTD ids for one physical station collapse to one seed row.
        catalog.append(
            {
                "stop_id": tn_id,
                "stop_name": stop["stop_name"],
                "stop_lat": lat,
                "stop_lon": lon,
            }
        )

    rows.sort(key=lambda r: r["stop_id"])
    return rows, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[2])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be written, write nothing",
    )
    args = parser.parse_args()

    conn = connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT count(*) AS n FROM ontd.route_summaries")
            if cur.fetchone()["n"] == 0:
                print(
                    "[export] ontd schema is empty — run the bootstrap first "
                    "(python db/ontd/bootstrap.py --force), then re-run this."
                )
                return 1
            rows, skipped = derive_rows(cur)
    finally:
        conn.close()

    print(f"[export] {len(rows)} ONTD-derived stop rows, {len(skipped)} skipped")
    for line in skipped:
        print(f"  skipped: {line}")

    if args.dry_run:
        print("[export] dry run — nothing written.")
        return 0

    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[export] wrote {CSV_PATH.relative_to(_BACKEND_ROOT.parent)}")
    print(
        "[export] upload it to Drive as a new version of the existing file "
        "(keeps the file id), then reseed (restart the API container)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
