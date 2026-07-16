"""
proposal_repository.py
======================
Write-path database adapter for saved proposals — the persistence
counterpart to data_loader_from_db.py (which stays strictly read-only for
parameter data).

A save is one transaction that inserts a proposals.proposals row plus the
full GTFS decomposition of the route (services/calendar/shapes/routes/
trips/stop_times). save() takes the WHOLE response of each upstream API
call — route_body is exactly what POST /api/route/plan returned
(route_builder_version + request + route), and evaluation_body, if
given, is exactly what POST /api/evaluation/calc returned (calc_version +
route_id + models + input + views). Both are stored verbatim (after
draft-ID rewriting) as route_body/evaluation_body JSONB — no field
picked apart or trimmed. See db/dev/sql/create_proposal_schema.sql for
the versioning contract this module implements:

  save() action outcomes
    "created"    proposal_id in the posted route is a draft placeholder or
                 unknown → new proposal_id from the sequence, version 1
    "versioned"  proposal_id exists and the saver owns the current version
                 → same proposal_id, version + 1, is_current flipped
    "branched"   proposal_id exists but belongs to someone else
                 → new proposal_id from the sequence, version 1

All draft IDs inside the route JSON (route_id, trip_ids, geometry_ids,
od_pair/shunting/parking trip references) share the prefix
"P{proposal_id}_V{version}_", so re-minting them is a single recursive
prefix rewrite over the JSON.

This module works on route JSON dicts (route_to_dict() output), not domain
objects — the save endpoint receives JSON and stores JSON, so a domain
round-trip would add cost without adding meaning.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Optional

import psycopg2
import psycopg2.extras
from psycopg2.extras import Json

logger = logging.getLogger(__name__)

_ROUTE_ID_PATTERN = re.compile(r"^P(\d+)_V(\d+)_R1$")

# Nominal GTFS calendar window for persisted services — the project's
# target timetable year, 2032 (per the December-to-December European
# rail timetable-change convention: 2nd Sunday of December through the
# day before the following year's 2nd Sunday). GTFS requires concrete
# dates; the model itself only knows seasonal frequencies, so every saved
# service is pinned to this window until real timetable-year handling
# exists. If "2032" means the timetable period covering most of calendar
# year 2032 (starting Dec 2031) rather than the one starting Dec 2032,
# swap these two lines for "2031-12-14" / "2032-12-11".
_SERVICE_START = "2032-12-12"
_SERVICE_END = "2033-12-10"

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


def parse_route_id(route_id: str) -> tuple[int, int]:
    """Extract (proposal_id, proposal_version) from a route_id following the
    P{proposal_id}_V{version}_R1 convention. Raises ValueError otherwise."""
    match = _ROUTE_ID_PATTERN.match(route_id or "")
    if not match:
        raise ValueError(
            f"route_id '{route_id}' does not follow the "
            "P{proposal_id}_V{version}_R1 convention."
        )
    return int(match.group(1)), int(match.group(2))


def _rewrite_id_prefix(obj: Any, old_prefix: str, new_prefix: str) -> Any:
    """Recursively replace the proposal/version ID prefix in every string
    value AND dict key of a JSON structure. Covers route_id, trip_ids,
    geometry_ids, and all trip references (od_pairs, shuntings, parkings)
    as values — and, in the evaluation response's per-trip-pair/per-stop
    views (api/helpers/evaluation_serialize.py), trip_id/pair-key strings
    used as dict keys rather than values (e.g. data[pair_key][country_key]).
    Keys are always strings in a JSON-compatible dict, so the same
    startswith/replace logic applies to both."""
    if isinstance(obj, str):
        return (
            new_prefix + obj[len(old_prefix) :] if obj.startswith(old_prefix) else obj
        )
    if isinstance(obj, list):
        return [_rewrite_id_prefix(item, old_prefix, new_prefix) for item in obj]
    if isinstance(obj, dict):
        return {
            _rewrite_id_prefix(key, old_prefix, new_prefix): _rewrite_id_prefix(
                value, old_prefix, new_prefix
            )
            for key, value in obj.items()
        }
    return obj


def _min_to_interval(minutes: int) -> str:
    """Minutes-from-service-day-midnight → 'HH:MM:SS' INTERVAL literal.
    Values ≥ 1440 min naturally produce the GTFS overnight convention of
    times above 24:00:00."""
    return f"{minutes // 60:02d}:{minutes % 60:02d}:00"


def _trip_stops(trip: dict) -> list[dict]:
    """Ordered stop dicts of a trip: first segment's from_stop, then every
    segment's to_stop."""
    segments = trip["segments"]
    return [segments[0]["from_stop"]] + [seg["to_stop"] for seg in segments]


def _all_trips(route: dict) -> list[tuple[dict, str]]:
    """Every (trip_dict, composition_id) of a route, outbound and return of
    every trip pair, in order."""
    trips = []
    for pair in route["trip_pairs"]:
        trips.append((pair["outbound"], pair["composition_id"]))
        trips.append((pair["return_trip"], pair["composition_id"]))
    return trips


class ProposalRepository:
    """Persists proposals — thin connection wrapper mirroring DBDataLoader's
    construction (same env vars, one connection per process/worker)."""

    def __init__(self) -> None:
        self._conn = self._connect()

    def _connect(self):
        required = {
            "POSTGRES_HOST": os.environ.get("POSTGRES_HOST"),
            "POSTGRES_PORT": os.environ.get("POSTGRES_PORT"),
            "POSTGRES_DB": os.environ.get("POSTGRES_DB"),
            "POSTGRES_USER": os.environ.get("POSTGRES_USER"),
            "POSTGRES_PASSWORD": os.environ.get("POSTGRES_PASSWORD"),
        }
        missing = [key for key, value in required.items() if not value]
        if missing:
            raise RuntimeError(
                f"Missing required environment variable(s) for DB connection: "
                f"{', '.join(missing)}."
            )
        return psycopg2.connect(
            host=required["POSTGRES_HOST"],
            port=required["POSTGRES_PORT"],
            dbname=required["POSTGRES_DB"],
            user=required["POSTGRES_USER"],
            password=required["POSTGRES_PASSWORD"],
        )

    def _cursor(self):
        return self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def close(self) -> None:
        if self._conn and not self._conn.closed:
            self._conn.close()

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    def get_user(self, user_id: int) -> Optional[dict]:
        """admin.users row for user_id, or None."""
        with self._cursor() as cur:
            cur.execute(
                # display_name aliased to user_name — see feedback_repository
                # .get_user(): the API field name stays user_name for now.
                "SELECT user_id, display_name AS user_name, email "
                "FROM admin.users WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
        self._conn.rollback()  # release the read-only transaction
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def save(
        self,
        route_body: dict,
        user_id: int,
        change_log: Optional[str],
        evaluation_body: Optional[dict] = None,
    ) -> dict:
        """Persist one proposal version — see module docstring for the
        created/versioned/branched contract.

        route_body: the whole POST /api/route/plan response
        (route_builder_version + request + route) — stored verbatim as
        route_body after draft-ID rewriting.

        evaluation_body: the whole POST /api/evaluation/calc response,
        optional. Stored verbatim as evaluation_body after the same
        rewrite — a point-in-time snapshot, not re-derived. Its
        input.route is a duplicate copy of route_body.route by
        design (see module docstring); callers are expected to have
        already validated the two agree (proposal_serialize.
        validate_route_evaluation_sync) before calling this.

        Returns {action, proposal_id, proposal_version, is_current, user_id,
        change_log, created_at, route_id, route_body, evaluation_body}.
        """
        posted_route = route_body["route"]
        posted_pid, posted_version = parse_route_id(posted_route["route_id"])

        try:
            with self._cursor() as cur:
                # FOR UPDATE serialises concurrent saves of the same proposal
                # so two of them can't both allocate the same next version.
                cur.execute(
                    "SELECT proposal_id, proposal_version, user_id "
                    "FROM proposals.proposals "
                    "WHERE proposal_id = %s AND is_current FOR UPDATE",
                    (posted_pid,),
                )
                current = cur.fetchone()

                if current is None:
                    action = "created"
                    new_pid = self._next_proposal_id(cur)
                    new_version = 1
                elif current["user_id"] == user_id:
                    action = "versioned"
                    new_pid = posted_pid
                    new_version = current["proposal_version"] + 1
                    cur.execute(
                        "UPDATE proposals.proposals SET is_current = FALSE "
                        "WHERE proposal_id = %s AND is_current",
                        (new_pid,),
                    )
                else:
                    action = "branched"
                    new_pid = self._next_proposal_id(cur)
                    new_version = 1

                old_prefix = f"P{posted_pid}_V{posted_version}_"
                new_prefix = f"P{new_pid}_V{new_version}_"

                route_body = _rewrite_id_prefix(route_body, old_prefix, new_prefix)
                # The embedded request may still carry the draft
                # proposal_id/proposal_version as integers — the string
                # rewrite above doesn't touch ints, so correct them here.
                request_section = route_body.get("request")
                if isinstance(request_section, dict):
                    route_body["request"] = {
                        **request_section,
                        **{
                            key: value
                            for key, value in (
                                ("proposal_id", new_pid),
                                ("proposal_version", new_version),
                            )
                            if key in request_section
                        },
                    }
                route = route_body["route"]  # post-rewrite, for GTFS below

                evaluation_body = (
                    _rewrite_id_prefix(evaluation_body, old_prefix, new_prefix)
                    if evaluation_body is not None
                    else None
                )

                cur.execute(
                    "INSERT INTO proposals.proposals "
                    "(proposal_id, proposal_version, is_current, user_id, "
                    " route_body, evaluation_body, change_log) "
                    "VALUES (%s, %s, TRUE, %s, %s, %s, %s) "
                    "RETURNING created_at",
                    (
                        new_pid,
                        new_version,
                        user_id,
                        Json(route_body),
                        Json(evaluation_body) if evaluation_body is not None else None,
                        change_log,
                    ),
                )
                created_at = cur.fetchone()["created_at"]

                self._insert_gtfs(cur, route)

            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

        logger.info(
            "proposal save: action=%s proposal_id=%s version=%s user_id=%s",
            action,
            new_pid,
            new_version,
            user_id,
        )
        return {
            "action": action,
            "proposal_id": new_pid,
            "proposal_version": new_version,
            "is_current": True,
            "user_id": user_id,
            "change_log": change_log,
            "created_at": created_at,
            "route_id": route["route_id"],
            "route_body": route_body,
            "evaluation_body": evaluation_body,
        }

    @staticmethod
    def _next_proposal_id(cur) -> int:
        cur.execute(
            "SELECT nextval(pg_get_serial_sequence('proposals.proposals', 'proposal_id'))"
        )
        return cur.fetchone()["nextval"]

    # ------------------------------------------------------------------
    # Save — GTFS decomposition
    # ------------------------------------------------------------------

    def _insert_gtfs(self, cur, route: dict) -> None:
        """Decompose an (already ID-rewritten) route JSON into the GTFS
        tables. Historical versions keep their rows — every version writes
        under its own P{id}_V{version} IDs, nothing is deleted."""
        route_id = route["route_id"]
        service_id = f"{route_id}_SVC"

        self._insert_service(cur, service_id, route["schedule"])
        cur.execute(
            "INSERT INTO proposals.routes (route_id, route_long_name) VALUES (%s, %s)",
            (route_id, self._route_long_name(route)),
        )

        for trip, composition_id in _all_trips(route):
            stops = _trip_stops(trip)
            shape_id = self._insert_shape(cur, trip, route["geometries"])
            cur.execute(
                "INSERT INTO proposals.trips "
                "(trip_id, route_id, service_id, shape_id, trip_headsign, "
                " direction_id, composition_type_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    trip["trip_id"],
                    route_id,
                    service_id,
                    shape_id,
                    stops[-1]["stop_name"],
                    trip["direction"],
                    composition_id,
                ),
            )
            self._insert_stop_times(cur, trip["trip_id"], stops)

    def _insert_service(self, cur, service_id: str, schedule: dict) -> None:
        """One shared GTFS service per proposal version. Only fully daily
        schedules are persistable for now — the only reachable case, since
        route planning supports schedule_mode='alwaysDaily' exclusively. A
        non-daily frequency would need a weekday pattern the model doesn't
        define yet, so it fails loudly instead of storing wrong data."""
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
            (service_id, _SERVICE_START, _SERVICE_END),
        )

    def _insert_shape(self, cur, trip: dict, geometries: list[dict]) -> str:
        """Concatenate a trip's per-segment geometries into one GTFS shape.
        Shared junction points (segment end == next segment start) are
        deduplicated. shape_id convention: {trip_id}_SHAPE."""
        coords_by_id = {g["id"]: g["coords"] for g in geometries}
        coordinates: list = []
        distance_m = 0
        for seg in trip["segments"]:
            seg_coords = coords_by_id[seg["geometry_id"]]
            start = 1 if coordinates and coordinates[-1] == seg_coords[0] else 0
            coordinates.extend(seg_coords[start:])
            distance_m += seg["distance_m"]

        shape_id = f"{trip['trip_id']}_SHAPE"
        cur.execute(
            "INSERT INTO proposals.shapes (shape_id, geometry, length_km) "
            "VALUES (%s, %s, %s)",
            (
                shape_id,
                Json({"type": "LineString", "coordinates": coordinates}),
                round(distance_m / 1000.0, 2),
            ),
        )
        return shape_id

    def _insert_stop_times(self, cur, trip_id: str, stops: list[dict]) -> None:
        """Trip origin has no arrival and trip destination no departure in
        the model — GTFS convention fills each from the other side."""
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
                " pickup_type, drop_off_type) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    trip_id,
                    sequence,
                    stop["stop_id"],
                    arrival,
                    departure,
                    pickup,
                    drop_off,
                ),
            )

    @staticmethod
    def _route_long_name(route: dict) -> str:
        """'Origin – Destination' from each trip pair's outbound endpoints,
        multiple pairs joined by ' / ' (Y-shaped routes)."""
        names = []
        for pair in route["trip_pairs"]:
            stops = _trip_stops(pair["outbound"])
            names.append(f"{stops[0]['stop_name']} – {stops[-1]['stop_name']}")
        return " / ".join(names)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_current(self, proposal_id: int) -> Optional[dict]:
        """Current version of a proposal with the full route_body (and
        evaluation_body, if one was saved), or None if the proposal_id is
        unknown."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT p.proposal_id, p.proposal_version, p.is_current, "
                "       p.user_id, u.display_name AS user_name, p.change_log, p.created_at, "
                "       p.route_body, p.evaluation_body "
                "FROM proposals.proposals p "
                "LEFT JOIN admin.users u USING (user_id) "
                "WHERE p.proposal_id = %s AND p.is_current",
                (proposal_id,),
            )
            row = cur.fetchone()
        self._conn.rollback()
        return dict(row) if row else None

    def list_current(self, user_ids: Optional[list[int]] = None) -> list[dict]:
        """All current proposal versions, newest first, each with a trimmed
        route JSON (geometries and track_infrastructure stripped in SQL —
        the bulky parts a list summary never needs) and, if an evaluation
        was saved, its route-level per_year totals (revenue/cost/net —
        the one nested object list summaries need, not the full breakdown
        tree). user_ids filters SQL-side; content filters (countries/
        stops) are applied by the caller on the summaries."""
        sql = (
            "SELECT p.proposal_id, p.proposal_version, p.is_current, "
            "       p.user_id, u.display_name AS user_name, p.change_log, p.created_at, "
            # route_body is JSON (not JSONB — preserves key order, see
            # create_proposal_schema.sql), so the delete-key operator (-)
            # used below needs an explicit ::jsonb cast; that operator only
            # exists for jsonb. Read-only, has no effect on what's stored.
            "       (p.route_body::jsonb -> 'route') - 'geometries' - 'track_infrastructure' "
            "           AS route_trimmed, "
            "       p.evaluation_body #> '{views,route,data,per_year}' AS eval_totals "
            "FROM proposals.proposals p "
            "LEFT JOIN admin.users u USING (user_id) "
            "WHERE p.is_current"
        )
        params: tuple = ()
        if user_ids:
            sql += " AND p.user_id = ANY(%s)"
            params = (user_ids,)
        sql += " ORDER BY p.created_at DESC"

        with self._cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        self._conn.rollback()
        return [dict(row) for row in rows]