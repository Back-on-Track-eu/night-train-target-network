"""
build_country_relations.py
==========================
Rebuild input_params.country_relations — the candidate set of
country-to-country relations a night train could plausibly serve, which
GET /api/proposals/stats ranks its top and flop relations over
(adapters/proposal/README.md §7.7).

Run at seed time, after the stop catalog is in place and with the
routing engine up:

    python scripts/build_country_relations.py
    python scripts/build_country_relations.py --max-km 2000
    python scripts/build_country_relations.py --dry-run   # measure, write nothing

What it does, per current-base stop snapshot:

  1. REFERENCE STATION per country — the catalog stop closest to that
     country's own stop centroid. Not the centroid of the country
     polygon: input_params.countries.country_geom is the Marine Regions
     EEZ union (land PLUS maritime zones — that is what attributes belt
     and strait crossings correctly), so its centroid sits offshore for
     any country with a large sea area. Countries with no stops in the
     catalog get no reference station and therefore no relations; the
     stats response names them under unresolved_countries, and they
     appear on their own as stop coverage grows.
  2. PREFILTER — great-circle distance between the two reference
     stations × RAIL_DETOUR_FACTOR must come in under the threshold.
     This only decides whether routing the pair is worth an HTTP call;
     rejected pairs are still stored, with routing_status 'prefiltered',
     so "why is DE–PT missing" has an answer in the table.
  3. ROUTE the survivors on real track with the shared reference
     composition (adapters/routing_context.py, same rules the existing
     ONTD trains are drawn with) and store the routed distance and time.
     The API then keeps only pairs whose ROUTED distance is under the
     threshold — which is what makes the sea crossings fall out by
     themselves: Italy and Greece are ~1000 km apart in a straight line
     and 1900+ km apart by track around the Adriatic, and the Gulf of
     Bothnia plus the 1524mm gauge break leaves Finland with no rail
     path into the network at all.

Idempotent: rows are upserted per (country_a, country_b,
stop_infra_version), so a rerun costs nothing and a snapshot bump builds
a fresh set beside the old one rather than mutating it (the versioning
contract — pinned snapshots are immutable).

Soft-failing by design, like the other seed-time jobs: no router means
no rows and a loud log line, never a container that refuses to start.
The statistics degrade to an empty relations block.
"""

from __future__ import annotations

import argparse
import logging
import math
import sys
from pathlib import Path

# Executed as a plain script, so the backend root is not on sys.path.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402

from adapters.routing_context import (  # noqa: E402
    DEFAULT_WORKERS,
    build_reference_context,
    route_all,
)
from api import config  # noqa: E402
from dev_env import db_config  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# Straight-line distance underestimates track distance: rail follows
# valleys, existing corridors and border crossings. Only used to skip
# pairs too far apart to be worth an HTTP round trip — the decision that
# matters is made on the routed distance afterwards, so a generous
# factor here costs a few router calls and an ungenerous one would
# silently lose real relations.
RAIL_DETOUR_FACTOR = 1.25

EARTH_RADIUS_KM = 6371.0088


def great_circle_km(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    """Spherical distance between two coordinates, km."""
    phi_a, phi_b = math.radians(lat_a), math.radians(lat_b)
    delta = math.radians(lon_b - lon_a)
    cosine = math.sin(phi_a) * math.sin(phi_b) + math.cos(phi_a) * math.cos(
        phi_b
    ) * math.cos(delta)
    return EARTH_RADIUS_KM * math.acos(min(1.0, max(-1.0, cosine)))


def connect():
    """One resolver for host- and container-run alike (dev_env.py), which
    also points OPENRAILROUTING_URL at localhost when run from the host —
    the router and the database have to agree on which stack this is."""
    return psycopg2.connect(**db_config())


def current_stop_infra_version(cur) -> int | None:
    cur.execute(
        "SELECT stop_infrastructures_version FROM scenario.scenarios "
        "WHERE is_current_base"
    )
    row = cur.fetchone()
    return row["stop_infrastructures_version"] if row else None


def reference_stations(cur, stop_infra_version: int) -> list[dict]:
    """One reference station per country: the catalog stop closest to
    that country's stop centroid.

    Stops with KNOWN gauges are preferred over gauge-NULL ones at any
    distance (ORDER BY gauges_mm IS NULL first): a NULL reference station
    resolves standard-gauge and then fails to snap for exactly the reason
    step 8 found no tracks — Albania's centroid-nearest stop was Tirana's
    BUS terminal, and it silently cost the country all 19 of its
    relations. One defective stop must not poison a country's whole row.

    gauges_mm rides along: without it every reference station looks
    gauge-unknown to the router, which then routes the whole matrix on
    the standard-gauge profile and cannot snap a single broad-gauge
    station (measured 2026-08-29: 102 of 302 pairs failing, every one of
    them Finnish, Baltic, Ukrainian, Irish or Iberian).

    Both steps run in PostGIS on the pinned snapshot — the centroid over
    the country's own stop points, then a nearest-neighbour back onto a
    real station, so the reference is always somewhere a train can
    actually stop rather than a point in a field. Stops carry lat/lon as
    NUMERIC (no geometry column), hence the ST_MakePoint construction;
    at a few hundred stops per snapshot the scan is immaterial.
    """
    cur.execute(
        """
        WITH catalog AS (
            SELECT stop_id, stop_name, country_code, gauges_mm,
                   ST_SetSRID(ST_MakePoint(stop_lon, stop_lat), 4326) AS geom,
                   stop_lat, stop_lon
              FROM input_params.stop_infrastructures
             WHERE stop_infra_version = %s
        ), centroid AS (
            SELECT country_code, ST_Centroid(ST_Collect(geom)) AS geom
              FROM catalog
          GROUP BY country_code
        )
        SELECT DISTINCT ON (c.country_code)
               c.country_code, s.stop_id, s.stop_name, s.stop_lat, s.stop_lon,
               s.gauges_mm
          FROM centroid c
          JOIN catalog s ON s.country_code = c.country_code
      ORDER BY c.country_code, s.gauges_mm IS NULL, s.geom <-> c.geom
        """,
        (stop_infra_version,),
    )
    return [dict(row) for row in cur.fetchall()]


def candidate_pairs(stations: list[dict], max_km: float) -> list[dict]:
    """Every unordered country pair with its great-circle distance and a
    prefilter verdict. country_a < country_b throughout, matching the
    table's own CHECK and the "AA__BB" relation keys both summary
    projections write."""
    ordered = sorted(stations, key=lambda s: s["country_code"])
    pairs = []
    for index, a in enumerate(ordered):
        for b in ordered[index + 1 :]:
            distance = great_circle_km(
                float(a["stop_lat"]),
                float(a["stop_lon"]),
                float(b["stop_lat"]),
                float(b["stop_lon"]),
            )
            pairs.append(
                {
                    "country_a": a["country_code"],
                    "country_b": b["country_code"],
                    "station_a": a,
                    "station_b": b,
                    "great_circle_km": round(distance, 1),
                    "prefiltered": distance * RAIL_DETOUR_FACTOR > max_km,
                }
            )
    return pairs


def write_pairs(cur, pairs: list[dict], stop_infra_version: int) -> None:
    psycopg2.extras.execute_batch(
        cur,
        """
        INSERT INTO input_params.country_relations (
            country_a, country_b, ref_stop_a, ref_stop_b,
            great_circle_km, rail_km, rail_time_h, routing_status,
            stop_infra_version, built_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
        ON CONFLICT (country_a, country_b, stop_infra_version) DO UPDATE SET
            ref_stop_a      = EXCLUDED.ref_stop_a,
            ref_stop_b      = EXCLUDED.ref_stop_b,
            great_circle_km = EXCLUDED.great_circle_km,
            rail_km         = EXCLUDED.rail_km,
            rail_time_h     = EXCLUDED.rail_time_h,
            routing_status  = EXCLUDED.routing_status,
            built_at        = now()
        """,
        [
            (
                pair["country_a"],
                pair["country_b"],
                pair["station_a"]["stop_id"],
                pair["station_b"]["stop_id"],
                pair["great_circle_km"],
                pair.get("rail_km"),
                pair.get("rail_time_h"),
                pair["routing_status"],
                stop_infra_version,
            )
            for pair in pairs
        ],
    )


def build(max_km: float, workers: int, dry_run: bool = False) -> int:
    """Rebuild the table for the current base snapshot. Returns the
    number of pairs that came out routable within the threshold."""
    conn = connect()
    conn.autocommit = False
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        stop_infra_version = current_stop_infra_version(cur)
        if stop_infra_version is None:
            logger.warning("No current base scenario — nothing to build.")
            return 0

        stations = reference_stations(cur, stop_infra_version)
        if len(stations) < 2:
            logger.warning(
                "Stop catalog covers %d country(ies) — no pairs to build.",
                len(stations),
            )
            return 0
        logger.info(
            "Stop snapshot v%d: reference stations for %d countries (%s)",
            stop_infra_version,
            len(stations),
            ", ".join(s["country_code"] for s in stations),
        )

        pairs = candidate_pairs(stations, max_km)
        routable = [p for p in pairs if not p["prefiltered"]]
        logger.info(
            "%d country pairs, %d within %.0f km after the straight-line "
            "prefilter (x%.2f detour) — routing those",
            len(pairs),
            len(routable),
            max_km,
            RAIL_DETOUR_FACTOR,
        )

        context = build_reference_context()
        if context is None:
            logger.warning(
                "Routing unavailable — no relations built. The statistics "
                "endpoint returns an empty relations block until this runs "
                "again with the router up."
            )
            return 0

        results = route_all(
            context,
            (
                (
                    (pair["country_a"], pair["country_b"]),
                    [
                        (
                            pair["station_a"]["stop_id"],
                            float(pair["station_a"]["stop_lat"]),
                            float(pair["station_a"]["stop_lon"]),
                            pair["station_a"]["gauges_mm"],
                        ),
                        (
                            pair["station_b"]["stop_id"],
                            float(pair["station_b"]["stop_lat"]),
                            float(pair["station_b"]["stop_lon"]),
                            pair["station_b"]["gauges_mm"],
                        ),
                    ],
                )
                for pair in routable
            ),
            workers=workers,
        )

        within = 0
        for pair in pairs:
            if pair["prefiltered"]:
                pair["routing_status"] = "prefiltered"
                continue
            result = results.get((pair["country_a"], pair["country_b"]))
            if result is None or not result.routed:
                pair["routing_status"] = result.status if result else "snap_failed"
                continue
            pair["routing_status"] = "routed"
            pair["rail_km"] = round(result.distance_km, 1)
            pair["rail_time_h"] = round(result.time_h, 2)
            if pair["rail_km"] <= max_km:
                within += 1

        _log_summary(pairs, max_km, within)

        if dry_run:
            logger.info("--dry-run: nothing written.")
            conn.rollback()
            return within

        write_pairs(cur, pairs, stop_infra_version)
    conn.commit()
    conn.close()
    logger.info("Wrote %d rows; %d relations inside the threshold.", len(pairs), within)
    return within


def _log_summary(pairs: list[dict], max_km: float, within: int) -> None:
    """One line per outcome class, plus the closest relations — enough to
    tell "the threshold is wrong" from "the router is wrong" without
    opening the table."""
    by_status: dict[str, int] = {}
    for pair in pairs:
        by_status[pair["routing_status"]] = by_status.get(pair["routing_status"], 0) + 1
    logger.info(
        "Outcome: %s",
        ", ".join(f"{status}={count}" for status, count in sorted(by_status.items())),
    )
    over = [
        p for p in pairs if p["routing_status"] == "routed" and p["rail_km"] > max_km
    ]
    logger.info(
        "%d routed relations within %.0f km, %d routed but too far.",
        within,
        max_km,
        len(over),
    )
    closest = sorted(
        (p for p in pairs if p["routing_status"] == "routed"),
        key=lambda p: p["rail_km"],
    )[:10]
    for pair in closest:
        logger.info(
            "  %s-%s  %6.0f km rail  (%5.0f km straight)  %s – %s",
            pair["country_a"],
            pair["country_b"],
            pair["rail_km"],
            pair["great_circle_km"],
            pair["station_a"]["stop_name"],
            pair["station_b"]["stop_name"],
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[2])
    parser.add_argument(
        "--max-km",
        type=float,
        default=config.PROPOSALS_STATS_RELATION_MAX_KM,
        help=(
            "Routed distance ceiling for a relation, km "
            f"(default: {config.PROPOSALS_STATS_RELATION_MAX_KM:.0f}, from "
            "PROPOSALS_STATS_RELATION_MAX_KM — keep the build and the API "
            "on the same number)"
        ),
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Pairs to route concurrently (default: {DEFAULT_WORKERS})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Measure and report, write nothing",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when no relations could be built (CI)",
    )
    args = parser.parse_args()

    try:
        built = build(args.max_km, args.workers, args.dry_run)
    except Exception as e:
        logger.warning("Country relation build failed (%s: %s).", type(e).__name__, e)
        return 1 if args.strict else 0

    if args.strict and not built:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
