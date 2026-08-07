"""
Build ontd.route_summaries — the gallery/map projection over the ONTD
tables (adapters/proposal/README.md §5.5, decisions 23/25).

One row per ACTIVE route, carrying only descriptive and emission KPIs:
composition (where curated), duration, distance, average speed, stop
count, countries, GHG intensity, and a routed shape. Never financial,
demand, or engagement values — existing trains are gallery context, not
rated proposals.

Run automatically at the end of loader.py; also runnable standalone
after editing the curated composition tables by hand, since a changed
route→composition assignment shows up here.

Geometry is routed through OpenRailRouting via the same RailRouter.route()
path the live tool uses — full two-pass routing with the custom model,
speed cap and HSR avoidance, so an existing route and a proposal are
drawn by identical rules on the gallery map. The per-leg physics
route() also returns feeds route_legs (buffer calibration) and, since
WP10 step 6a, each leg's own geometry feeds route_corridors — the
per-stop-pair pieces the gallery map's corridor layer aggregates
alongside proposal segments. Physics never feeds an evaluation —
existing routes are not rated (decision 23).
Routing 200+ routes takes a few minutes and needs the router container
up; --no-geometry skips it for a quick metadata-only rebuild. Any route
whose stops the router can't snap falls back to straight lines between
consecutive stops and is flagged geometry_routed = FALSE, so a partial
router outage degrades the map instead of failing the load.

Directional averaging: a route's two trips differ slightly in timing, so
total_time_h and total_distance_km are averaged over whichever
directions carry a value (decided WP10 kickoff).

Usage:
    python db/ontd/projection.py                # rebuild, with routing
    python db/ontd/projection.py --no-geometry  # skip routing
"""

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Optional

from connection import connect, resolve_service_url
from psycopg2.extras import RealDictCursor
from stop_mapping import build_stop_mappings

# db/ontd/projection.py -> backend/ is two levels up. Needed because
# this script imports models/ and api/ (the router and its dependencies)
# while being executed directly, which puts only db/dev/ on sys.path —
# same pattern as seed.py.
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

# Same Douglas-Peucker tolerance as the proposal projection — both feed
# the same gallery map, so they must simplify to the same visual
# fidelity. Imported (single owner) rather than redefined, so the two
# can never drift apart; needs the sys.path insert above.
from adapters.proposal.projection import GEOM_SIMPLIFY_TOLERANCE_DEG  # noqa: E402

# Reference composition for routing existing routes. The ONTD catalog has
# no speed/HSR data of its own, and route() needs max_speed_kmh and
# hsr_allowed — so one input_params composition stands in for every
# existing train.
#
# Resolved at runtime rather than hardcoded: composition ids are a
# calibration output and do rot (STD-7.1, the id used across the docs and
# comparison scripts, had already been dropped from the catalog by the
# time this ran). MATERIAL_STRATEGY picks the family instead —
# 'refurbished' matches what existing night trains actually run, so the
# routed times are comparable to their real schedules. --composition-id
# overrides with a specific id.
ROUTING_MATERIAL_STRATEGY = "refurbished"

# Routes are routed concurrently: each is an independent pair of HTTP
# round-trips (fullRouting snaps, then routes), so the run is bound by
# router latency rather than by anything local. RailRouter's session is
# built for this — its connection pool holds 64 — but the router
# container is shared, so the default stays modest. Override with
# ONTD_ROUTING_WORKERS.
ROUTING_WORKERS = int(os.environ.get("ONTD_ROUTING_WORKERS", "8"))
ROUTING_COMPOSITION_ID = None


# HH:MM duration strings (the schema's convention — hours are NOT wrapped
# at 24, so a 25:03 overnight run parses correctly).
def _duration_to_hours(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        hours, _, minutes = str(value).strip().partition(":")
        return int(hours) + int(minutes) / 60
    except (ValueError, TypeError):
        return None


def _split_countries(value: Optional[str]) -> list[str]:
    """ontd.routes.countries is a comma-separated TEXT list ('BE, DE, AT');
    route_summaries.countries is TEXT[] for GIN-indexed filtering."""
    if not value:
        return []
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _mean(values: list[float]) -> Optional[float]:
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


def fetch_active_routes(cur) -> list[dict[str, Any]]:
    """Route metadata plus its trips' timings, one row per route.

    countries comes off the route rather than being derived from the
    stops: the sheet's own list includes transited countries that no stop
    sits in, which is what the gallery's country filter should match on.
    """
    cur.execute(
        """
        SELECT r.route_id,
               COALESCE(r.route_long_name, r.route_short_name) AS name,
               r.countries,
               r.distance        AS route_distance_km,
               rc.composition_id,
               array_agg(t.duration    ORDER BY t.trip_id) AS durations,
               array_agg(t.distance    ORDER BY t.trip_id) AS distances,
               array_agg(t.co2_per_km  ORDER BY t.trip_id) AS co2_values
          FROM ontd.routes r
          LEFT JOIN ontd.trips t
                 ON t.route_id = r.route_id AND t.is_active
          LEFT JOIN ontd.route_compositions rc
                 ON rc.route_id = r.route_id
         WHERE r.is_active
      GROUP BY r.route_id, name, r.countries, r.distance, rc.composition_id
      ORDER BY r.route_id
        """
    )
    return [dict(row) for row in cur.fetchall()]


def fetch_route_stops(cur) -> dict[str, list[dict[str, Any]]]:
    """Ordered stops per route, taken from the route's first direction.

    DISTINCT ON picks one trip per route deterministically; the two
    directions mirror each other, so either gives the same stop set and
    the same shape on a map.
    """
    cur.execute(
        """
        WITH first_trip AS (
            SELECT DISTINCT ON (route_id) route_id, trip_id, direction_id
              FROM ontd.trips
             WHERE is_active
          ORDER BY route_id, trip_id
        )
        SELECT ft.route_id, ft.trip_id, ft.direction_id,
               ts.stop_id, ts.stop_sequence,
               ts.arrival_time, ts.departure_time,
               s.stop_lat, s.stop_lon
          FROM first_trip ft
          JOIN ontd.trip_stop ts ON ts.trip_id = ft.trip_id
          LEFT JOIN ontd.stops s ON s.stop_id = ts.stop_id
      ORDER BY ft.route_id, ts.stop_sequence
        """
    )
    by_route: dict[str, list[dict[str, Any]]] = {}
    for row in cur.fetchall():
        by_route.setdefault(row["route_id"], []).append(dict(row))
    return by_route


def _clock_to_minutes(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    try:
        hours, _, minutes = str(value).strip().partition(":")
        return int(hours) * 60 + int(minutes)
    except (ValueError, TypeError):
        return None


def _scheduled_running_minutes(stops: list[dict[str, Any]]) -> list[Optional[int]]:
    """Real running time per leg: departure(from) → arrival(to).

    Excludes dwell by construction, which is what makes it comparable to
    the router's in-motion components — a night train's dwell would
    otherwise show up as if the router were systematically fast.

    Night trains cross midnight, so the sequence is walked with a day
    offset that advances whenever a clock reading goes backwards; times
    are HH:MM wall clock with no date attached.
    """
    minutes: list[Optional[int]] = []
    day_offset = 0
    previous: Optional[int] = None

    def absolute(raw: Optional[str]) -> Optional[int]:
        """Resolve one clock reading against the running day offset,
        advancing it on rollover. Mutates day_offset/previous, so it must
        be called in strict timetable order."""
        nonlocal day_offset, previous
        base = _clock_to_minutes(raw)
        if base is None:
            return None
        if previous is not None and base + day_offset * 1440 < previous:
            day_offset += 1
        value = base + day_offset * 1440
        previous = value
        return value

    for index in range(len(stops) - 1):
        # Strict order matters: a stop's arrival precedes its departure.
        departure = absolute(stops[index].get("departure_time")) or absolute(
            stops[index].get("arrival_time")
        )
        arrival = absolute(stops[index + 1].get("arrival_time"))
        if arrival is None:
            # Keep the offset walking even when a leg can't be measured.
            absolute(stops[index + 1].get("departure_time"))
        minutes.append(
            arrival - departure
            if departure is not None and arrival is not None and arrival >= departure
            else None
        )
    return minutes


def _straight_line_geometry(stops: list[dict[str, Any]]) -> list[list[float]]:
    return [
        [float(s["stop_lon"]), float(s["stop_lat"])]
        for s in stops
        if s["stop_lat"] is not None and s["stop_lon"] is not None
    ]


def _route_legs(context, stops: list[dict[str, Any]]):
    """Route the stop sequence and return (legs, routed).

    legs are RoutedLegs — geometry for the map projection, and the
    driving/dynamics/buffer split plus country shares for the buffer
    calibration dataset. Returns ([], False) when the router can't
    produce a path, so the caller can fall back to straight lines and
    flag it rather than presenting interpolated track as real.
    """
    from models.params import StopInfrastructure
    from models.route.routing.rail_router import StopInput
    from models.route.trip import StopType

    located = [
        s for s in stops if s["stop_lat"] is not None and s["stop_lon"] is not None
    ]
    if len(located) < 2:
        return [], "too_few_stops", "fewer than two stops carry coordinates"

    router, tracks, composition = context
    router_stops = [
        StopInput(
            stop=StopInfrastructure(
                stop_id=s["stop_id"],
                stop_name=s["stop_id"],
                stop_country_code="",
                lat=float(s["stop_lat"]),
                lon=float(s["stop_lon"]),
                # Never read while routing — charges belong to evaluation,
                # which never runs on existing routes (decision 23).
                stop_charge_eur=0.0,
            ),
            stop_type=StopType.BOTH,
        )
        for s in located
    ]
    try:
        return (
            router.route(router_stops, composition, tracks, "fullRouting"),
            "routed",
            None,
        )
    except Exception as e:
        message = str(e)
        # The router distinguishes "could not snap a stop to any usable
        # track" from "snapped fine but no path exists" — worth keeping
        # apart, since the first is usually the profile's 1435mm gauge
        # filter and the second a genuinely disconnected network.
        status = "no_connection" if "Connection between" in message else "snap_failed"
        print(
            f"    routing failed ({type(e).__name__}: {message}) — straight-line fallback"
        )
        return [], status, message


def _simplified_geojson(coords: list[list[float]]) -> Optional[str]:
    """MultiLineString GeoJSON, matching the column type and the proposal
    projection's own simplification."""
    if len(coords) < 2:
        return None
    from shapely.geometry import LineString, MultiLineString, mapping

    simplified = MultiLineString([LineString(coords)]).simplify(
        GEOM_SIMPLIFY_TOLERANCE_DEG, preserve_topology=False
    )
    if simplified.geom_type == "LineString":
        simplified = MultiLineString([simplified])
    return json.dumps(mapping(simplified))


def _select_composition(collection, requested: Optional[str]):
    """Resolve the reference composition: an explicit id if given, else
    the first ROUTING_MATERIAL_STRATEGY one by id.

    Deterministic (sorted) so successive rebuilds stay comparable — a
    calibration set silently routed with a different composition than the
    previous run would be worse than useless.
    """
    catalog = collection.all()
    if requested:
        composition = collection.get(requested)
        if composition is None:
            available = ", ".join(sorted(catalog)[:12])
            print(
                f"  WARNING: composition '{requested}' not found — pass a valid "
                f"--composition-id. Available (first 12): {available}"
            )
        return composition

    matching = sorted(
        (
            c
            for c in catalog.values()
            if c.material_strategy == ROUTING_MATERIAL_STRATEGY
        ),
        key=lambda c: c.comp_id,
    )
    if matching:
        return matching[0]

    fallback = sorted(catalog.values(), key=lambda c: c.comp_id)
    if not fallback:
        print("  WARNING: composition catalog is empty.")
        return None
    print(
        f"  WARNING: no '{ROUTING_MATERIAL_STRATEGY}' composition in the catalog — "
        f"falling back to '{fallback[0].comp_id}'."
    )
    return fallback[0]


def _build_routing_context(composition_id: Optional[str]):
    """Assemble everything route() needs: router, tracks, composition.

    Existing routes are drawn on the same gallery map as proposals, so
    they must be routed by the same rules — full two-pass routing with
    the custom model, the composition's speed cap and HSR avoidance
    (adapters/proposal/README.md decision 25, revised). Anything less would draw
    the same physical night train on different tracks depending on which
    table it came from.

    The ONTD catalog carries no speed or HSR data (ontd.compositions is
    descriptive — places and weight only), so one reference composition
    stands in for every existing route; route() reads exactly two fields
    off it, max_speed_kmh and hsr_allowed.

    Returns None if anything is unavailable (router down, params not
    seeded, unknown composition) — the caller falls back to straight
    lines rather than aborting a load whose other work is good.
    """
    try:
        from adapters.data_loader_from_db import DBDataLoader
        from models.route.routing.rail_router import CountryIndex, RailRouter

        # RailRouter reads OPENRAILROUTING_URL at construction, so the
        # compose-service host has to be translated before that.
        resolve_service_url()

        loader = DBDataLoader()
        composition = _select_composition(
            loader.build_all_compositions(), composition_id
        )
        if composition is None:
            return None

        router = RailRouter(CountryIndex(loader.get_country_geometries()))
        router.check_server()
        print(
            f"  routing with composition '{composition.comp_id}' "
            f"({composition.material_strategy}, "
            f"max {composition.max_speed_kmh:.0f} km/h, "
            f"hsr_allowed={composition.hsr_allowed})"
        )
        return router, loader.build_all_tracks(), composition
    except Exception as e:
        print(
            f"  WARNING: routing unavailable ({type(e).__name__}: {e}) — "
            f"all geometry falls back to straight lines."
        )
        return None


def _write_legs(cur, route_id: str, stops: list[dict[str, Any]], legs) -> None:
    """Persist the router-vs-timetable comparison for one route.

    Written for every route. Where routing failed the routed_* columns
    are NULL rather than zero: a zero would read as "no buffer needed"
    and bias the calibration, whereas NULL states plainly that there is
    no observation. The timetable side is recorded either way, so the
    sample and its gaps are both queryable.
    """
    scheduled = _scheduled_running_minutes(stops)
    trip_id = stops[0].get("trip_id")
    direction_id = stops[0].get("direction_id")
    if not trip_id:
        return

    # No legs = routing failed; still record the timetable side, with the
    # routed_* columns left NULL.
    for position in range(len(stops) - 1):
        # Router legs pair consecutive stops, so leg i spans stops i→i+1.
        # A shorter leg list (routing failed, or the router merged points)
        # leaves the routed_* columns NULL for the remaining pairs rather
        # than aligning them by guesswork.
        leg = legs[position] if position < len(legs) else None
        cur.execute(
            """
            INSERT INTO ontd.route_legs (
                route_id, trip_id, direction_id, leg_sequence,
                from_stop_id, to_stop_id, scheduled_running_min,
                routed_driving_min, routed_dynamics_min, routed_buffer_min,
                routed_distance_m, country_time_shares, country_distance_shares
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (trip_id, leg_sequence) DO NOTHING
            """,
            (
                route_id,
                trip_id,
                direction_id,
                position + 1,
                stops[position]["stop_id"],
                stops[position + 1]["stop_id"],
                scheduled[position] if position < len(scheduled) else None,
                leg.driving_time_min if leg else None,
                leg.dynamics_time_min if leg else None,
                leg.buffer_time_min if leg else None,
                leg.distance_m if leg else None,
                json.dumps(leg.country_time_shares) if leg else None,
                json.dumps(leg.country_distance_shares) if leg else None,
            ),
        )


def _write_corridors(
    cur,
    route_id: str,
    stops: list[dict[str, Any]],
    legs,
    mapping: dict[str, str],
) -> None:
    """Per consecutive stop pair: one corridor row with that leg's own
    geometry (router leg where routing succeeded, straight line between
    the two stops otherwise), stop ids translated to the Target Network
    namespace and direction-collapsed (stop_a < stop_b) — the same grain
    repository.py aggregates proposals.segments into for map_lines. Pairs
    where either stop lacks coordinates are skipped (no geometry to
    draw); ON CONFLICT covers a route traversing one corridor twice."""
    for position in range(len(stops) - 1):
        from_stop, to_stop = stops[position], stops[position + 1]
        if None in (
            from_stop["stop_lat"],
            from_stop["stop_lon"],
            to_stop["stop_lat"],
            to_stop["stop_lon"],
        ):
            continue
        leg = legs[position] if position < len(legs) else None
        coords = (
            [list(point) for point in leg.geometry]
            if leg is not None and len(leg.geometry) >= 2
            else [
                [float(from_stop["stop_lon"]), float(from_stop["stop_lat"])],
                [float(to_stop["stop_lon"]), float(to_stop["stop_lat"])],
            ]
        )
        tn_from = mapping.get(from_stop["stop_id"], from_stop["stop_id"])
        tn_to = mapping.get(to_stop["stop_id"], to_stop["stop_id"])
        cur.execute(
            """
            INSERT INTO ontd.route_corridors (route_id, stop_a, stop_b, geometry)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (route_id, stop_a, stop_b) DO NOTHING
            """,
            (
                route_id,
                min(tn_from, tn_to),
                max(tn_from, tn_to),
                json.dumps({"type": "LineString", "coordinates": coords}),
            ),
        )


def _route_all(context, routes, stops_by_route, workers: int) -> dict:
    """Route every route concurrently; return {route_id: (legs, status, error)}.

    Routing is done up front and in parallel, then written sequentially by
    the caller — the database work stays single-threaded on one
    connection, which keeps the transaction semantics exactly as they
    were while removing the part that actually costs time.

    Nothing shared here is mutated: the router's session is pooled, and
    the composition, tracks and country index are read-only lookups.
    """
    results: dict = {}
    routable = [r["route_id"] for r in routes if stops_by_route.get(r["route_id"])]
    if not routable:
        return results

    print(f"  routing {len(routable)} routes, {workers} at a time")
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_route_legs, context, stops_by_route[rid]): rid
            for rid in routable
        }
        for future in as_completed(futures):
            route_id = futures[future]
            done += 1
            try:
                results[route_id] = future.result()
            except Exception as e:
                # A crash in one route must not lose the other 204.
                results[route_id] = ([], "snap_failed", f"{type(e).__name__}: {e}")
            status = results[route_id][1]
            if status != "routed":
                print(f"  [{done}/{len(routable)}] {route_id}: {status}")
            elif done % 25 == 0 or done == len(routable):
                print(f"  [{done}/{len(routable)}] routed")
    return results


def build_summaries(
    cur,
    with_geometry: bool = True,
    composition_id: Optional[str] = ROUTING_COMPOSITION_ID,
    workers: int = ROUTING_WORKERS,
) -> tuple[int, int]:
    routes = fetch_active_routes(cur)
    stops_by_route = fetch_route_stops(cur)

    context = _build_routing_context(composition_id) if with_geometry else None
    routed = (
        _route_all(context, routes, stops_by_route, workers)
        if context is not None
        else {}
    )

    # ONTD → Target Network stop translation (WP10 step 6a): built
    # before anything is written, so route_summaries.stop_ids and
    # route_corridors come out in the proposal side's namespace. Matching
    # only — the catalog is complete at seed time (stop_mapping.py's
    # module docstring); unmatched stops are reported and keep raw ids.
    mapping = build_stop_mappings(cur)

    cur.execute("TRUNCATE ontd.route_corridors")
    cur.execute("TRUNCATE ontd.route_legs")
    cur.execute("TRUNCATE ontd.route_summaries")

    written = routed_count = 0
    for index, route in enumerate(routes, start=1):
        route_id = route["route_id"]
        stops = stops_by_route.get(route_id, [])

        total_time_h = _mean([_duration_to_hours(d) for d in route["durations"] or []])
        total_distance_km = _mean(
            [float(d) for d in (route["distances"] or []) if d is not None]
        ) or (float(route["route_distance_km"]) if route["route_distance_km"] else None)
        co2 = _mean([float(c) for c in (route["co2_values"] or []) if c is not None])
        avg_speed = (
            total_distance_km / total_time_h
            if total_distance_km and total_time_h
            else None
        )

        legs: list = []
        status = "no_router" if context is None else "too_few_stops"
        error = None
        geojson = None
        if stops:
            if context is not None:
                legs, status, error = routed.get(
                    route_id, ([], "snap_failed", "no routing result")
                )
            geometry_routed = status == "routed"
            coords = (
                [point for leg in legs for point in leg.geometry]
                if geometry_routed
                else _straight_line_geometry(stops)
            )
            geojson = _simplified_geojson(coords)
            # Written for every route: the timetable side is valuable on
            # its own, and a visible NULL on the routed columns is a
            # better record of the gap than a missing row.
            _write_legs(cur, route_id, stops, legs)
            _write_corridors(cur, route_id, stops, legs, mapping)
        geometry_routed = status == "routed"
        routed_count += 1 if geometry_routed else 0

        cur.execute(
            """
            INSERT INTO ontd.route_summaries (
                route_id, name, stop_ids, n_stops, countries,
                total_distance_km, total_time_h, avg_speed_kmh,
                composition_id, co2_g_per_pax_km,
                geom_simplified, geometry_routed, routing_status, routing_error
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                CASE WHEN %s IS NULL THEN NULL
                     ELSE ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326) END,
                %s, %s, %s
            )
            """,
            (
                route_id,
                route["name"] or route_id,
                [mapping.get(s["stop_id"], s["stop_id"]) for s in stops],
                len(stops),
                _split_countries(route["countries"]),
                round(total_distance_km, 1) if total_distance_km else None,
                round(total_time_h, 2) if total_time_h else None,
                round(avg_speed, 1) if avg_speed else None,
                route["composition_id"],
                round(co2, 1) if co2 else None,
                geojson,
                geojson,
                geometry_routed,
                status,
                error,
            ),
        )
        written += 1

    return written, routed_count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--composition-id",
        default=ROUTING_COMPOSITION_ID,
        help=(
            "Reference composition id for routing "
            f"(default: first '{ROUTING_MATERIAL_STRATEGY}' composition in the catalog)"
        ),
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=ROUTING_WORKERS,
        help=f"Routes to route concurrently (default: {ROUTING_WORKERS})",
    )
    parser.add_argument(
        "--no-geometry",
        action="store_true",
        help="Skip routing (metadata-only rebuild; geometry falls back to straight lines)",
    )
    args = parser.parse_args()

    conn = connect()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    written, routed = build_summaries(
        cur,
        with_geometry=not args.no_geometry,
        composition_id=args.composition_id,
        workers=args.workers,
    )

    conn.commit()
    cur.close()
    conn.close()
    print(
        f"\nDone — ontd.route_summaries rebuilt: {written} active routes, "
        f"{routed} with routed geometry, {written - routed} on straight-line fallback."
    )


if __name__ == "__main__":
    main()
