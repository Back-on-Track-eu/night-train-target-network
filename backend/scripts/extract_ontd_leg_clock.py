"""
extract_ontd_leg_clock.py
==========================
One-off extraction for the schedule supplement re-calibration: every
ontd.route_legs row joined to the wall-clock departure and arrival of its
two stops, plus a night-position class per leg.

Why this exists: route_context/calib/01_source_extraction.ipynb reads
scheduled_running_min but not WHEN the leg runs. The Wien-Paris check
(scripts/test_travel_time_paris_vienna.py) showed that the residual on a
leg depends far more on its position in the night than on its country —
legs running in the core night hours carry the operator's arrival-hour
stretching, legs on the evening and morning edges run at commercial
speed. Calibrating "minimum driving time" needs the edge legs only; the
stretching belongs to the timetable layer (slack), not to the supplement.

Writes scripts/data/ontd_legs_clock.csv. Read-only against the database.

Usage:
    uv run python scripts/extract_ontd_leg_clock.py
    uv run python scripts/extract_ontd_leg_clock.py --night-start 23:00 --night-end 05:00

Columns added over ontd.route_legs:
    dep_clock, arr_clock      HH:MM wall clock as in the ONTD sheet
    dep_abs_min, arr_abs_min  minutes from the trip origin's calendar day,
                              walked with the same day rollover the
                              projection uses (db/ontd/projection.py)
    origin_dep_abs_min, dest_arr_abs_min
                              the whole trip's ends on the same scale
    night_class               edge_evening | edge_morning | core | spanning
                              (see _night_class)
    residual_min, residual_pct  scheduled - (driving + dynamics), as in 01
    excluded_reason           the same classification 01 applies, so the
                              same 412 legs survive
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.ontd.connection import connect, resolve_env  # noqa: E402

OUTPUT = os.path.join(os.path.dirname(__file__), "data", "ontd_legs_clock.csv")

# Restated from 01_source_extraction.ipynb so the two agree on the sample.
MAX_RESIDUAL_PCT = 300.0
MIN_LEG_MIN = 10.0

SQL = """
WITH seq AS (
    SELECT trip_id, stop_id, arrival_time, departure_time,
           ROW_NUMBER() OVER (PARTITION BY trip_id ORDER BY stop_sequence) AS rn
      FROM ontd.trip_stop
),
ends AS (
    SELECT trip_id,
           MIN(rn) AS first_rn,
           MAX(rn) AS last_rn
      FROM seq
  GROUP BY trip_id
)
SELECT rl.route_id, rl.trip_id, rl.direction_id, rl.leg_sequence,
       rl.from_stop_id, rl.to_stop_id,
       rl.scheduled_running_min, rl.routed_driving_min, rl.routed_dynamics_min,
       rl.routed_buffer_min, rl.routed_distance_m, rl.country_time_shares,
       f.departure_time AS from_departure,
       f.arrival_time   AS from_arrival,
       t.arrival_time   AS to_arrival,
       t.departure_time AS to_departure,
       o.departure_time AS origin_dep_clock,
       d.arrival_time   AS dest_arr_clock
  FROM ontd.route_legs rl
  JOIN ends e ON e.trip_id = rl.trip_id
  LEFT JOIN seq f ON f.trip_id = rl.trip_id AND f.rn = rl.leg_sequence
  LEFT JOIN seq t ON t.trip_id = rl.trip_id AND t.rn = rl.leg_sequence + 1
  LEFT JOIN seq o ON o.trip_id = rl.trip_id AND o.rn = e.first_rn
  LEFT JOIN seq d ON d.trip_id = rl.trip_id AND d.rn = e.last_rn
 ORDER BY rl.route_id, rl.trip_id, rl.leg_sequence
"""


def _clock(value) -> int | None:
    if not value:
        return None
    try:
        h, _, m = str(value).strip().partition(":")
        return int(h) * 60 + int(m)
    except (TypeError, ValueError):
        return None


def _hhmm(value: str) -> int:
    h, _, m = value.partition(":")
    return int(h) * 60 + int(m)


def _classify(sched, drive, dyn, shares) -> tuple[str, float | None]:
    """01_source_extraction's _classify, restated."""
    dyn = dyn or 0
    if drive is None:
        return "routing_failed", None
    if sched is None:
        return "no_timetable", None
    model = drive + dyn
    if model <= 0:
        return "zero_routed_time", None
    if model < MIN_LEG_MIN:
        return "leg_too_short", None
    pct = (sched - model) / model * 100.0
    if not shares:
        return "no_country_shares", pct
    if sched < model:
        return "router_slower_than_reality", pct
    if pct > MAX_RESIDUAL_PCT:
        return "residual_implausible", pct
    return "", pct


def _night_class(
    dep: int | None, arr: int | None, night_start: int, night_end: int
) -> str:
    """Where the leg sits relative to the core night [night_start, night_end].

    Times are absolute minutes from the origin's day; the night window is
    projected onto the same day scale (night_end < night_start means it
    crosses midnight). A leg is
      edge_evening  — arrives before the core night begins
      edge_morning  — departs after the core night ends
      core          — lies entirely inside the core night
      spanning      — overlaps a night boundary
    Edge legs run with passengers awake and a daytime path to compete
    for; that is where the residual is closest to a minimum driving time.
    """
    if dep is None or arr is None:
        return ""
    # Core night on day 0 starts at night_start and ends at night_end (+1 day).
    ns = night_start
    ne = night_end + 1440 if night_end <= night_start else night_end
    # A leg can also sit relative to the SECOND night for very long trips.
    for k in (0, 1):
        s, e = ns + 1440 * k, ne + 1440 * k
        if arr <= s:
            return "edge_evening" if k == 0 else "edge_morning"
        if dep >= e:
            continue  # after this night — test the next one
        if dep >= s and arr <= e:
            return "core"
        return "spanning"
    return "edge_morning"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--night-start", default="23:00")
    parser.add_argument("--night-end", default="05:00")
    args = parser.parse_args()
    night_start, night_end = _hhmm(args.night_start), _hhmm(args.night_end)

    print(f"connecting to {resolve_env()['POSTGRES_HOST']} ...", end=" ")
    with connect() as conn, conn.cursor() as cur:
        cur.execute(SQL)
        columns = [c.name for c in cur.description]
        fetched = cur.fetchall()
    rows = (
        [dict(r) for r in fetched]
        if fetched and isinstance(fetched[0], dict)
        else [dict(zip(columns, r)) for r in fetched]
    )
    print(f"ok, {len(rows)} legs")

    # Walk each trip in order with a day offset, exactly as
    # db/ontd/projection.py does, so that the absolute minutes agree.
    out = []
    by_trip: dict[str, list[dict]] = {}
    for r in rows:
        by_trip.setdefault(r["trip_id"], []).append(r)

    for trip_id, legs in by_trip.items():
        legs.sort(key=lambda r: r["leg_sequence"])
        day_offset, previous = 0, None

        def absolute(raw):
            nonlocal day_offset, previous
            base = _clock(raw)
            if base is None:
                return None
            if previous is not None and base + day_offset * 1440 < previous:
                day_offset += 1
            previous = base + day_offset * 1440
            return previous

        origin_dep = absolute(legs[0]["origin_dep_clock"])
        for leg in legs:
            # Same fallback as projection._scheduled_running_minutes: ONTD
            # often records only an arrival at intermediate stops, in
            # which case the arrival doubles as the departure. The to-stop
            # arrival has no fallback there either, so a missing one keeps
            # the offset walking and leaves the leg unmeasured.
            leg["dep_clock"] = leg["from_departure"] or leg["from_arrival"]
            leg["arr_clock"] = leg["to_arrival"]
            dep = absolute(leg["dep_clock"])
            arr = absolute(leg["arr_clock"])
            if arr is None:
                absolute(leg["to_departure"])
            leg["_dep"], leg["_arr"] = dep, arr
        dest_arr = absolute(legs[-1]["dest_arr_clock"])

        for leg in legs:
            shares = leg["country_time_shares"]
            if isinstance(shares, str):
                shares = json.loads(shares)
            shares = {k: v for k, v in (shares or {}).items() if k != "UNK"}
            reason, pct = _classify(
                leg["scheduled_running_min"],
                leg["routed_driving_min"],
                leg["routed_dynamics_min"],
                shares,
            )
            drive, dyn = leg["routed_driving_min"], leg["routed_dynamics_min"] or 0
            model = None if drive is None else drive + dyn
            out.append(
                {
                    "route_id": leg["route_id"],
                    "trip_id": trip_id,
                    "direction_id": leg["direction_id"],
                    "leg_sequence": leg["leg_sequence"],
                    "from_stop_id": leg["from_stop_id"],
                    "to_stop_id": leg["to_stop_id"],
                    "countries": "+".join(sorted(shares)),
                    "country_time_shares": json.dumps(shares),
                    "scheduled_running_min": leg["scheduled_running_min"],
                    "routed_driving_min": drive,
                    "routed_dynamics_min": dyn,
                    "routed_model_min": model,
                    "residual_min": (
                        None
                        if model is None or leg["scheduled_running_min"] is None
                        else leg["scheduled_running_min"] - model
                    ),
                    "residual_pct": None if pct is None else round(pct, 1),
                    "routed_distance_km": (
                        None
                        if leg["routed_distance_m"] is None
                        else round(leg["routed_distance_m"] / 1000.0, 1)
                    ),
                    "dep_clock": leg["dep_clock"],
                    "arr_clock": leg["arr_clock"],
                    "dep_abs_min": leg["_dep"],
                    "arr_abs_min": leg["_arr"],
                    "origin_dep_abs_min": origin_dep,
                    "dest_arr_abs_min": dest_arr,
                    "night_class": _night_class(
                        leg["_dep"], leg["_arr"], night_start, night_end
                    ),
                    "excluded_reason": reason,
                }
            )

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(out[0]))
        writer.writeheader()
        for row in out:
            writer.writerow({k: ("" if v is None else v) for k, v in row.items()})

    included = [r for r in out if not r["excluded_reason"]]
    classes = {}
    for r in included:
        classes[r["night_class"]] = classes.get(r["night_class"], 0) + 1
    print(f"  {len(included)} included legs by night_class: {classes}")
    print(f"  -> {OUTPUT}")


if __name__ == "__main__":
    main()
