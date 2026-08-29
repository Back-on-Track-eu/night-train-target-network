"""
gtfs_store.py
=============
GTFS + sidecar persistence — the DB write/read counterpart of
api/helpers/route_serialize.py's route_to_dict()/route_from_dict(), against
proposals.{routes,trips,stop_times,shapes,services,calendar} + the WP1
sidecar tables (proposals.segments, od_pairs, parkings, shuntings,
timetable_warnings, seasonal_schedules) instead of a JSON blob
(adapters/proposal/README.md §5.1/§5.2). Lives under adapters/ — it
executes SQL, and the project's layering keeps all DB access in adapters/;
the pure dict↔domain serializers it delegates to stay in api/helpers/
(Flask-free by design, importable from here — see AGENTS.md's layering
note).

Two halves, mirroring route_serialize.py's own split:

  insert_route_gtfs(cur, route)                        — write side
  route_dict_from_gtfs(proposal_id, version, loader,
                        scenario_id, cur)                — read side
  input_parameters_from_scenario(scenario_id, loader)   — the
                                                            evaluation.
                                                            input.parameters
                                                            rebuild helper

route_dict_from_gtfs() reconstructs Stop/Segment/Trip/TripPair/Route
domain objects from the DB (composition reloaded via loader, same
discipline route_from_dict() already uses for JSON) and then hands off to
the existing, already-tested route_to_dict() to serialize — so this
module never reimplements general_parameters, the composition/track
physics-subset shape, or geometry_id assignment; it only has to get the
domain objects right and everything downstream is proven code.

WP5 update: this is the SOLE GTFS write/read path — the old
persist-on-calc _insert_gtfs() was removed in WP5's cutover along with
route_body/evaluation_body. repository.py's publish() calls
insert_route_gtfs() directly (within its own transaction/cursor) and does
no GTFS assembly itself.

Segment geometry is stored per-segment on `shapes` (shape_id convention
"{trip_id}_L{i}_SHAPE", mirroring route_to_dict()'s own geometry_id
convention) rather than concatenated per-trip — per §5.2, the per-trip
concatenated shape is a GTFS-export-time concern, not a storage one.
trips.shape_id is left NULL here.
"""

from __future__ import annotations

import re

from psycopg2.extras import Json

from api.helpers.route_serialize import route_to_dict
from api.helpers.evaluation_serialize import input_to_dict
from models.route.route import (
    Route,
    TripPair,
    Schedule,
    SeasonalSchedule,
    Season,
    Frequency,
    Parking,
    Shunting,
)
from models.route.trip import Stop, StopType, Segment, Trip, TimetableWarning
from models.route.model import GTFS_SERVICE_END, GTFS_SERVICE_START
from models.params import ODPair
from models.utils import min_to_interval as _min_to_interval

_TRIP_SUFFIX_PATTERN = re.compile(r"_D(\d+)_T(\d+)$")


_WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

# stop_type → (pickup_type, drop_off_type). GTFS: 0 = regular, 1 = none.
# "night" maps like "both": the classification is a demand statement, not an
# operational prohibition — boarding and alighting both stay possible at a
# night stop (it also dwells like "both", see timetable.dwell_min()).
_STOP_TYPE_TO_PICKUP_DROPOFF = {
    "boarding": (0, 1),
    "alighting": (1, 0),
    "night": (0, 0),
    "both": (0, 0),
}


def _trip_stops(trip: dict) -> list[dict]:
    """Ordered stop dicts of a trip: first segment's from_stop, then every
    segment's to_stop."""
    segments = trip["segments"]
    return [segments[0]["from_stop"]] + [seg["to_stop"] for seg in segments]


def _route_long_name(route: dict) -> str:
    """'Origin – Destination' from each trip pair's outbound endpoints,
    multiple pairs joined by ' / ' (Y-shaped routes)."""
    names = []
    for pair in route["trip_pairs"]:
        stops = _trip_stops(pair["outbound"])
        names.append(f"{stops[0]['stop_name']} – {stops[-1]['stop_name']}")
    return " / ".join(names)


# =============================================================================
# WRITE SIDE
# =============================================================================


def insert_route_gtfs(cur, route: dict) -> None:
    """Full GTFS + sidecar decomposition of a route dict (route_to_dict()
    shape). route["route_id"] must already carry its real
    P{proposal_id}_V{version}_R1 prefix — this function assumes ID
    rewriting already happened — it does no rewriting itself.

    Nothing here is discarded — every WP1
    sidecar table gets populated, plus stop_times.stop_type/auto_added.
    """
    route_id = route["route_id"]
    service_id = f"{route_id}_SVC"
    coords_by_id = {g["id"]: g["coords"] for g in route.get("geometries", [])}

    _insert_service(cur, service_id, route["schedule"])
    cur.execute(
        "INSERT INTO proposals.routes (route_id, route_long_name) VALUES (%s, %s)",
        (route_id, _route_long_name(route)),
    )
    for ss in route["schedule"]["seasonal_schedules"]:
        cur.execute(
            "INSERT INTO proposals.seasonal_schedules (route_id, season, frequency) "
            "VALUES (%s, %s, %s)",
            (route_id, ss["season"], ss["frequency"]),
        )

    for pair in route["trip_pairs"]:
        composition_id = pair["composition_id"]
        for trip in (pair["outbound"], pair["return_trip"]):
            _insert_trip(cur, route_id, service_id, trip, composition_id, coords_by_id)
        for od in pair["od_pairs"]:
            cur.execute(
                "INSERT INTO proposals.od_pairs "
                "(trip_id, origin_stop_id, destination_stop_id, class_main, "
                " places_sold, avg_price) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    od["trip_id"],
                    od["origin_stop_id"],
                    od["destination_stop_id"],
                    od["class_main"],
                    od["places_sold"],
                    od["avg_price"],
                ),
            )

    for p in route["parkings"]:
        cur.execute(
            "INSERT INTO proposals.parkings "
            "(route_id, stop_id, stop_name, country_code, trip_ids, layover_min) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (
                route_id,
                p["stop_id"],
                p["stop_name"],
                p["country_code"],
                p["trip_ids"],
                # The facility charge is priced from the layover, so a stored
                # route has to carry it or it would reprice cheaper than the
                # response it was published from. Stored in minutes: hours is
                # minutes/60 and rarely exact in decimal, so a fixed-scale
                # column would round the reconstruction away from the value
                # that was published (13.983333... -> 13.98).
                round(p.get("hours", 0.0) * 60),
            ),
        )
    for s in route["shuntings"]:
        cur.execute(
            "INSERT INTO proposals.shuntings "
            "(route_id, stop_id, stop_name, country_code, trip_id) "
            "VALUES (%s, %s, %s, %s, %s)",
            (route_id, s["stop_id"], s["stop_name"], s["country_code"], s["trip_id"]),
        )


def _insert_service(cur, service_id: str, schedule: dict) -> None:
    """One shared GTFS service per route. Identical constraint to the old
    write path's _insert_service(): only fully daily schedules are
    persistable for now (the only reachable case — route planning
    supports schedule_mode='alwaysDaily' exclusively)."""
    frequencies = {ss["frequency"] for ss in schedule["seasonal_schedules"]}
    if frequencies != {"daily"}:
        raise ValueError(
            f"Only fully daily schedules can be saved as proposals for now "
            f"(got frequencies {sorted(frequencies)})."
        )
    cur.execute(
        "INSERT INTO proposals.services (service_id) VALUES (%s)", (service_id,)
    )
    columns = ", ".join(_WEEKDAYS)
    flags = ", ".join(["TRUE"] * len(_WEEKDAYS))
    cur.execute(
        f"INSERT INTO proposals.calendar (service_id, {columns}, start_date, end_date) "
        f"VALUES (%s, {flags}, %s, %s)",
        (service_id, GTFS_SERVICE_START, GTFS_SERVICE_END),
    )


def _insert_trip(
    cur,
    route_id: str,
    service_id: str,
    trip: dict,
    composition_id: str,
    coords_by_id: dict,
) -> None:
    trip_id = trip["trip_id"]
    stops = _trip_stops(trip)
    cur.execute(
        "INSERT INTO proposals.trips "
        "(trip_id, route_id, service_id, shape_id, trip_headsign, "
        " direction_id, composition_type_id) "
        "VALUES (%s, %s, %s, NULL, %s, %s, %s)",
        (
            trip_id,
            route_id,
            service_id,
            stops[-1]["stop_name"],
            trip["direction"],
            composition_id,
        ),
    )
    _insert_stop_times(cur, trip_id, stops)
    _insert_segments(cur, trip_id, trip["segments"], coords_by_id)
    for w in trip.get("general_parameters", {}).get("timetable_warnings", []):
        cur.execute(
            "INSERT INTO proposals.timetable_warnings "
            "(trip_id, code, interval_start_stop_id, interval_end_stop_id, "
            " timetable_speed_kmh, routing_speed_kmh, ratio) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                trip_id,
                w["code"],
                w["interval"][0],
                w["interval"][1],
                w["timetable_speed_kmh"],
                w["routing_speed_kmh"],
                w["ratio"],
            ),
        )


def _insert_stop_times(cur, trip_id: str, stops: list[dict]) -> None:
    """Trip origin has no arrival and trip destination no departure in the
    model — GTFS convention fills each from the other side, same as the
    old write path. stop_type/auto_added are the two lossless additions
    over the old path (§5.2, and the phase 1b migration for auto_added)."""
    for sequence, stop in enumerate(stops, start=1):
        arrival_min = stop["arrival_time_min"]
        departure_min = stop["departure_time_min"]
        arrival = _min_to_interval(
            arrival_min if arrival_min is not None else departure_min
        )
        departure = _min_to_interval(
            departure_min if departure_min is not None else arrival_min
        )
        pickup, drop_off = _STOP_TYPE_TO_PICKUP_DROPOFF[stop["stop_type"]]
        cur.execute(
            "INSERT INTO proposals.stop_times "
            "(trip_id, stop_sequence, stop_id, arrival_time, departure_time, "
            " pickup_type, drop_off_type, stop_type, auto_added) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                trip_id,
                sequence,
                stop["stop_id"],
                arrival,
                departure,
                pickup,
                drop_off,
                stop["stop_type"],
                stop.get("auto_added", False),
            ),
        )


def _insert_segments(
    cur, trip_id: str, segments: list[dict], coords_by_id: dict
) -> None:
    """One shapes row + one segments row per segment (0-based sequence,
    matching route_to_dict()'s geometry_id index) — the per-segment shape
    storage §5.2 calls for, replacing the old write path's one
    concatenated per-trip shape."""
    for i, seg in enumerate(segments):
        shape_id = f"{trip_id}_L{i}_SHAPE"
        coords = coords_by_id[seg["geometry_id"]]
        cur.execute(
            "INSERT INTO proposals.shapes (shape_id, geometry, length_km) "
            "VALUES (%s, %s, %s)",
            (
                shape_id,
                Json({"type": "LineString", "coordinates": coords}),
                round(seg["distance_m"] / 1000.0, 2),
            ),
        )
        cur.execute(
            "INSERT INTO proposals.segments "
            "(trip_id, segment_sequence, from_stop_id, to_stop_id, shape_id, "
            " distance_m, driving_time_min, dynamics_time_min, buffer_time_min, "
            " slack_time_min, energy_kwh, country_distance_shares, "
            " country_time_shares, countries, passages) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                trip_id,
                i,
                seg["from_stop"]["stop_id"],
                seg["to_stop"]["stop_id"],
                shape_id,
                seg["distance_m"],
                seg["driving_time_min"],
                seg["dynamics_time_min"],
                seg["buffer_time_min"],
                seg["slack_time_min"],
                seg["energy_kwh"],
                Json(seg["country_distance_shares"]),
                Json(seg["country_time_shares"]),
                # Ordered countries and owned crossings — see
                # models/route/trip.py. Payloads planned before
                # ROUTE_BUILDER 0.9.21 carry neither; an empty list is
                # what route_serialize.py's fallback expects to see.
                Json(seg.get("countries") or []),
                Json(seg.get("passages") or []),
            ),
        )


# =============================================================================
# READ SIDE
# =============================================================================


def _interval_to_min(value) -> int:
    """psycopg2 returns INTERVAL columns as datetime.timedelta — convert
    back to plain minutes-from-service-day-midnight, the inverse of
    _min_to_interval()."""
    return int(round(value.total_seconds() / 60))


def _parse_trip_suffix(trip_id: str) -> tuple[int, int]:
    """trip_id convention: {route_id}_D{direction}_T{pair_index} — extract
    (direction, pair_index) without assuming anything about route_id's own
    shape (it's already stripped by the caller via the WHERE clause, this
    only needs the trailing _D.._T.. suffix)."""
    match = _TRIP_SUFFIX_PATTERN.search(trip_id)
    if not match:
        raise ValueError(
            f"route_dict_from_gtfs: trip_id '{trip_id}' does not match the "
            "_D{direction}_T{pair_index} suffix convention."
        )
    return int(match.group(1)), int(match.group(2))


def route_dict_from_gtfs(
    proposal_id: int, proposal_version: int, loader, scenario_id: int, cur
) -> dict:
    """Reconstruct the route_to_dict() shape from GTFS + sidecar rows.

    scenario_id: explicit parameter rather than looked up internally —
    kept that way even now that proposals.proposals.scenario_id exists
    (§5.3, WP5), since the caller (api/proposals.py's GET /api/proposal/
    <id>) already has the container row in hand and passing its
    scenario_id through avoids a second, redundant lookup here.
    """
    route_id = f"P{proposal_id}_V{proposal_version}_R1"

    cur.execute(
        "SELECT trip_id, direction_id, composition_type_id FROM proposals.trips "
        "WHERE route_id = %s ORDER BY trip_id",
        (route_id,),
    )
    trip_rows = cur.fetchall()
    if not trip_rows:
        raise ValueError(
            f"route_dict_from_gtfs: no trips found for route_id '{route_id}' "
            f"(proposal_id={proposal_id}, proposal_version={proposal_version})."
        )

    cur.execute(
        "SELECT season, frequency FROM proposals.seasonal_schedules WHERE route_id = %s",
        (route_id,),
    )
    schedule = Schedule(
        seasonal_schedules=[
            SeasonalSchedule(
                season=Season(r["season"]), frequency=Frequency(r["frequency"])
            )
            for r in cur.fetchall()
        ]
    )

    # Built once, not per trip pair — same rationale as route_from_dict()
    # and plan_route(): a fixed number of queries regardless of how many
    # trip pairs a Y-shaped route has.
    stop_infra = loader.build_all_stops(scenario_id)
    compositions = loader.build_all_compositions(scenario_id)

    pairs: dict[int, dict[int, dict]] = {}
    composition_id_by_pair: dict[int, str] = {}
    for row in trip_rows:
        direction, pair_index = _parse_trip_suffix(row["trip_id"])
        pairs.setdefault(pair_index, {})[direction] = row
        composition_id_by_pair[pair_index] = row["composition_type_id"]

    trip_pairs = []
    for pair_index in sorted(pairs):
        group = pairs[pair_index]
        if set(group) != {0, 1}:
            raise ValueError(
                f"route_dict_from_gtfs: trip pair {pair_index} of '{route_id}' "
                f"doesn't have exactly directions {{0, 1}} (found {sorted(group)})."
            )
        composition_id = composition_id_by_pair[pair_index]
        composition = compositions.get(composition_id)
        if composition is None:
            raise ValueError(
                f"route_dict_from_gtfs: composition '{composition_id}' not found."
            )
        outbound = _build_trip(
            cur, group[0]["trip_id"], direction=0, stop_infra=stop_infra
        )
        return_trip = _build_trip(
            cur, group[1]["trip_id"], direction=1, stop_infra=stop_infra
        )
        od_pairs = _build_od_pairs(cur, group[0]["trip_id"], group[1]["trip_id"])
        trip_pairs.append(
            TripPair(
                outbound=outbound,
                return_trip=return_trip,
                composition=composition,
                od_pairs=od_pairs,
            )
        )

    parkings = _build_parkings(cur, route_id)
    shuntings = _build_shuntings(cur, route_id)

    route = Route._create(
        route_id=route_id,
        schedule=schedule,
        trip_pairs=trip_pairs,
        parkings=parkings,
        shuntings=shuntings,
    )

    tracks = loader.build_all_tracks(scenario_id)
    return route_to_dict(route, scenario_id, tracks)


def _build_trip(cur, trip_id: str, direction: int, stop_infra) -> Trip:
    cur.execute(
        "SELECT stop_sequence, stop_id, arrival_time, departure_time, "
        " stop_type, auto_added "
        "FROM proposals.stop_times WHERE trip_id = %s ORDER BY stop_sequence",
        (trip_id,),
    )
    stop_rows = cur.fetchall()
    n = len(stop_rows)
    stops: list[Stop] = []
    for i, row in enumerate(stop_rows):
        infra = stop_infra.get(row["stop_id"])
        if infra is None:
            raise ValueError(
                f"route_dict_from_gtfs: stop '{row['stop_id']}' not found in the "
                "stop catalog for this scenario."
            )
        stops.append(
            Stop(
                stop_id=infra.stop_id,
                stop_name=infra.stop_name,
                country_code=infra.stop_country_code,
                lat=infra.lat,
                lon=infra.lon,
                stop_type=StopType(row["stop_type"]),
                # First stop's arrival and last stop's departure are never
                # actually read anywhere downstream (Trip.departure_time_min/
                # arrival_time_min read the opposite ends) — None here
                # matches the domain contract regardless of what GTFS's
                # fill-from-the-other-side convention wrote to that column.
                arrival_time_min=None
                if i == 0
                else _interval_to_min(row["arrival_time"]),
                departure_time_min=(
                    None if i == n - 1 else _interval_to_min(row["departure_time"])
                ),
                auto_added=row["auto_added"],
            )
        )

    cur.execute(
        "SELECT segment_sequence, shape_id, distance_m, driving_time_min, "
        " dynamics_time_min, buffer_time_min, slack_time_min, energy_kwh, "
        " country_distance_shares, country_time_shares, countries, passages "
        "FROM proposals.segments WHERE trip_id = %s ORDER BY segment_sequence",
        (trip_id,),
    )
    segments: list[Segment] = []
    for i, srow in enumerate(cur.fetchall()):
        cur.execute(
            "SELECT geometry FROM proposals.shapes WHERE shape_id = %s",
            (srow["shape_id"],),
        )
        geometry = cur.fetchone()["geometry"]
        segments.append(
            Segment(
                from_stop=stops[i],
                to_stop=stops[i + 1],
                geometry=geometry["coordinates"],
                distance_m=int(srow["distance_m"]),
                driving_time_min=int(srow["driving_time_min"]),
                dynamics_time_min=int(srow["dynamics_time_min"]),
                buffer_time_min=int(srow["buffer_time_min"]),
                slack_time_min=int(srow["slack_time_min"]),
                energy_kwh=float(srow["energy_kwh"]),
                country_distance_shares=srow["country_distance_shares"],
                country_time_shares=srow["country_time_shares"],
                countries=list(srow["countries"] or []),
                passages=list(srow["passages"] or []),
            )
        )

    cur.execute(
        "SELECT code, interval_start_stop_id, interval_end_stop_id, "
        " timetable_speed_kmh, routing_speed_kmh, ratio "
        "FROM proposals.timetable_warnings WHERE trip_id = %s",
        (trip_id,),
    )
    warnings = [
        TimetableWarning(
            code=w["code"],
            interval=(w["interval_start_stop_id"], w["interval_end_stop_id"]),
            timetable_speed_kmh=float(w["timetable_speed_kmh"]),
            routing_speed_kmh=float(w["routing_speed_kmh"]),
            ratio=float(w["ratio"]),
        )
        for w in cur.fetchall()
    ]

    return Trip(
        trip_id=trip_id,
        direction=direction,
        segments=segments,
        timetable_warnings=warnings,
    )


def _build_od_pairs(cur, outbound_trip_id: str, return_trip_id: str) -> list[ODPair]:
    cur.execute(
        "SELECT origin_stop_id, destination_stop_id, class_main, trip_id, "
        " places_sold, avg_price "
        "FROM proposals.od_pairs WHERE trip_id IN (%s, %s)",
        (outbound_trip_id, return_trip_id),
    )
    return [
        ODPair(
            origin_stop_id=r["origin_stop_id"],
            destination_stop_id=r["destination_stop_id"],
            class_main=r["class_main"],
            trip_id=r["trip_id"],
            places_sold=int(r["places_sold"]),
            avg_price=float(r["avg_price"]),
        )
        for r in cur.fetchall()
    ]


def _build_parkings(cur, route_id: str) -> list[Parking]:
    cur.execute(
        "SELECT stop_id, stop_name, country_code, trip_ids, layover_min "
        "FROM proposals.parkings WHERE route_id = %s",
        (route_id,),
    )
    return [
        Parking(
            stop_id=r["stop_id"],
            stop_name=r["stop_name"],
            country_code=r["country_code"],
            trip_ids=list(r["trip_ids"]),
            # The same arithmetic route_factory._layover_hours() does, so the
            # reconstruction reproduces the published float exactly.
            hours=(r["layover_min"] or 0) / 60.0,
        )
        for r in cur.fetchall()
    ]


def _build_shuntings(cur, route_id: str) -> list[Shunting]:
    cur.execute(
        "SELECT stop_id, stop_name, country_code, trip_id "
        "FROM proposals.shuntings WHERE route_id = %s",
        (route_id,),
    )
    return [
        Shunting(
            stop_id=r["stop_id"],
            stop_name=r["stop_name"],
            country_code=r["country_code"],
            trip_id=r["trip_id"],
        )
        for r in cur.fetchall()
    ]


# =============================================================================
# input.parameters rebuild helper
# =============================================================================


def input_parameters_from_scenario(scenario_id: int, loader) -> dict:
    """Rebuild the evaluation.input.parameters block
    section from a scenario pin alone (§5.1 — parameters are never stored
    per proposal, only the scenario_id that resolves them). Reuses
    evaluation_serialize.input_to_dict() itself (include_route=False, same
    as api/proposal_calc.py) rather than reimplementing its
    tracks/stop_infra/compositions assembly a second time — returns
    exactly {"parameters": {...}}."""
    tracks = loader.build_all_tracks(scenario_id)
    stop_infra = loader.build_all_stops(scenario_id)
    compositions = loader.build_all_compositions(scenario_id, include_indicative=False)
    return input_to_dict(
        route_dict=None,
        tracks=tracks,
        stop_infra=stop_infra,
        compositions=compositions,
        include_route=False,
    )
