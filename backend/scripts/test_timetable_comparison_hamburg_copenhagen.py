"""
test_timetable_comparison_hamburg_copenhagen.py
===============================================
Manual test script comparing the two timetable modes on the same corridor
and the same scenario:

  München Hbf -> Berlin Hbf -> Hamburg Hbf -> København H

  A: timetable_mode="simpleAutomatic"
       The whole trip's duration is mirrored around 02:30 (MIRROR_MIN) —
       demand-wise unfavourable departure times at Berlin/Hamburg, which
       land in the middle of the night.
  B: timetable_mode="simpleAutomaticWithFixedNight"
       fixed_night_interval=["DE_HAMBURG_HBF", "DK_COPENHAGEN"] — the
       Hamburg->København section is what gets centered on 02:30 instead,
       so the German feeder (München/Berlin/Hamburg) keeps evening
       departures. The interval must depart Hamburg by 23:59 and arrive
       København at 05:00 or later (NIGHT_START_MIN / NIGHT_END_MIN in
       models/route/version.py); a naturally shorter interval is stretched
       with per-segment slack_time_min, and an over-stretched one carries a
       fixed_night_stretch_slow entry in general_parameters.
       timetable_warnings.

Both requests pin the same scenario and auto_stop_addition="off", so the
routed path and physics are IDENTICAL between A and B — everything this
script prints differs by timetable only. That's also why, unlike
test_scenario_comparison_paris_berlin.py, no GeoJSON layers are written
here: the two modes draw the exact same lines on a map.

Usage:
    python scripts/test_timetable_comparison_hamburg_copenhagen.py
    python scripts/test_timetable_comparison_hamburg_copenhagen.py --interval DE_BERLIN_HBF DK_COPENHAGEN
    python scripts/test_timetable_comparison_hamburg_copenhagen.py --scenario 2032-baseline-hsr-allowed

Writes raw route responses and a comparison summary to scripts/data/
(tc_3_muc_cph_*). Pre-flight:
  1. Checks Flask API is reachable
  2. Loads data if not already loaded
  3. Checks OpenRailRouting is running; starts it if not
"""

import argparse
import json
import os
import subprocess
import sys
import time

import requests

API_BASE = "http://localhost:5000"
ROUTING_URL = "http://localhost:8989"
CONTAINER_NAME = "openrailrouting"

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "data")

STOPS = ["DE_MUENCHEN_HBF", "DE_BERLIN_HBF", "DE_HAMBURG_HBF", "DK_COPENHAGEN"]
COMPOSITION_ID = "STD-7.1"

DEFAULT_INTERVAL = ["DE_HAMBURG_HBF", "DK_COPENHAGEN"]
DEFAULT_SCENARIO = "base"

# Mirrors NIGHT_START_MIN / NIGHT_END_MIN in models/route/version.py —
# restated as literals: this script observes the API contract from outside,
# same as the test suite.
NIGHT_START = 24 * 60  # 00:00 (+1)
NIGHT_END = 29 * 60  # 05:00 (+1)


# =============================================================================
# PRE-FLIGHT CHECKS
# =============================================================================


def check_flask():
    print("[ ] Checking Flask API...")
    try:
        r = requests.get(f"{API_BASE}/api/health", timeout=3)
        if r.status_code == 200:
            print("[✓] Flask API is running.")
            return True
    except requests.ConnectionError:
        pass
    print(
        "[✗] Flask API not reachable at localhost:5000. Start it with: uv run python main.py"
    )
    return False


def ensure_data_loaded():
    print("[ ] Checking data status...")
    r = requests.get(f"{API_BASE}/api/data/status")
    status = r.json()

    if status.get("loaded"):
        print(f"[✓] Data already loaded at {status.get('loaded_at')}.")
        return True

    print("[ ] Data not loaded — loading now...")
    r = requests.post(f"{API_BASE}/api/data/load")
    result = r.json()

    if r.status_code == 200:
        print(f"[✓] Data loaded at {result.get('loaded_at')}.")
        return True
    else:
        print(f"[✗] Data load failed: {result.get('message')}")
        return False


def ensure_routing_running():
    print("[ ] Checking OpenRailRouting...")
    try:
        r = requests.get(f"{ROUTING_URL}/health", timeout=3)
        if r.status_code == 200:
            print("[✓] OpenRailRouting is running.")
            return True
    except requests.ConnectionError:
        pass

    print(f"[ ] OpenRailRouting not running — starting container '{CONTAINER_NAME}'...")
    result = subprocess.run(
        ["docker", "start", CONTAINER_NAME], capture_output=True, text=True
    )

    if result.returncode != 0:
        print(f"[✗] Failed to start container: {result.stderr.strip()}")
        return False

    print("[ ] Waiting for OpenRailRouting to be ready...")
    for i in range(30):
        time.sleep(2)
        try:
            r = requests.get(f"{ROUTING_URL}/health", timeout=2)
            if r.status_code == 200:
                print("[✓] OpenRailRouting is ready.")
                return True
        except requests.ConnectionError:
            pass
        print(f"    ...waiting ({(i + 1) * 2}s)")

    print("[✗] OpenRailRouting did not become ready in time.")
    return False


# =============================================================================
# SCENARIO LOOKUP
# =============================================================================


def fetch_scenario(scenario_key: str) -> dict:
    """GET /api/scenarios and return the row matching scenario_key, whichever
    of the three response groups it lands in. Exits if not found — this is a
    setup/seed problem, not something to compare around."""
    resp = requests.get(f"{API_BASE}/api/scenarios", timeout=15)
    resp.raise_for_status()
    body = resp.json()

    for group in ("current_base", "current_scenarios", "historical_scenarios"):
        for scenario in body[group]["scenarios"]:
            if scenario["scenario_key"] == scenario_key:
                return scenario

    print(f"[✗] No scenario found with scenario_key='{scenario_key}'.")
    print("    Available keys:", end=" ")
    keys = [
        s["scenario_key"]
        for group in ("current_base", "current_scenarios", "historical_scenarios")
        for s in body[group]["scenarios"]
    ]
    print(", ".join(keys))
    sys.exit(1)


# =============================================================================
# ROUTE BUILDING
# =============================================================================


def build_route(scenario_id: int, fixed_night_interval: list[str] | None) -> dict:
    """One POST /api/route/plan — mode A (interval=None, simpleAutomatic) or
    mode B (interval set, simpleAutomaticWithFixedNight). Everything else is
    pinned identical so the timetable is the only thing that differs."""
    body = {
        "scenario_id": scenario_id,
        "stops": STOPS,
        "composition_id": COMPOSITION_ID,
        "routing_mode": "fullRouting",
        "schedule_mode": "alwaysDaily",
        # Fixed stop list — isolates the comparison to the timetable mode,
        # not auto-added stops (which would also shift dwell/clock times).
        "auto_stop_addition": "off",
    }
    if fixed_night_interval is None:
        body["timetable_mode"] = "simpleAutomatic"
    else:
        body["timetable_mode"] = "simpleAutomaticWithFixedNight"
        body["fixed_night_interval"] = fixed_night_interval

    resp = requests.post(f"{API_BASE}/api/route/plan", json=body, timeout=90)
    if resp.status_code != 200:
        print(
            f"[✗] route/plan failed for timetable_mode={body['timetable_mode']}: "
            f"{resp.text[:300]}"
        )
        sys.exit(1)
    return resp.json()["route"]


# =============================================================================
# TIMETABLE EXTRACTION
# =============================================================================


def hhmm(minutes: int | None) -> str:
    """Clock display for the continuous minutes-from-midnight-day-1 scale —
    '(+1)' marks the second calendar day, e.g. 1590 -> '02:30(+1)'."""
    if minutes is None:
        return "—"
    day = minutes // (24 * 60)
    m = minutes % (24 * 60)
    return f"{m // 60:02d}:{m % 60:02d}" + ("(+1)" if day else "")


def trip_stops(trip: dict) -> list[dict]:
    """Ordered stop list of a trip, reconstructed from its segments (same
    logic as tests/helpers.stop_times, restated here — scripts stay
    standalone, importable without the test suite)."""
    segments = trip["segments"]
    return [segments[0]["from_stop"]] + [seg["to_stop"] for seg in segments]


def trips_by_direction(route: dict) -> dict[int, dict]:
    pair = route["trip_pairs"][0]
    return {t["direction"]: t for t in (pair["outbound"], pair["return_trip"])}


def interval_times(trip: dict, interval: list[str]) -> tuple[int, int]:
    """(departure at interval start, arrival at interval end) — interval
    given in THIS direction's travel order."""
    by_id = {s["stop_id"]: s for s in trip_stops(trip)}
    return (
        by_id[interval[0]]["departure_time_min"],
        by_id[interval[1]]["arrival_time_min"],
    )


# =============================================================================
# COMPARISON
# =============================================================================


def print_direction(direction: int, trip_a: dict, trip_b: dict, interval: list[str]):
    """One side-by-side timetable table per direction — mode A vs mode B per
    stop, then mode B's slack/interval/warning details underneath."""
    label = "OUTBOUND (D0)" if direction == 0 else "RETURN (D1)"
    trip_interval = interval if direction == 0 else interval[::-1]

    print(f"\n--- {label}:  {' -> '.join(s['stop_id'] for s in trip_stops(trip_a))}")
    print(
        f"  {'stop':18}{'A arr':>10}{'A dep':>10}{'A type':>10}"
        f"{'B arr':>12}{'B dep':>10}{'B type':>10}"
    )
    for sa, sb in zip(trip_stops(trip_a), trip_stops(trip_b)):
        marker = " *" if sa["stop_id"] in trip_interval else ""
        print(
            f"  {sa['stop_name'][:17]:18}"
            f"{hhmm(sa['arrival_time_min']):>10}{hhmm(sa['departure_time_min']):>10}"
            f"{sa['stop_type']:>10}"
            f"{hhmm(sb['arrival_time_min']):>12}{hhmm(sb['departure_time_min']):>10}"
            f"{sb['stop_type']:>10}{marker}"
        )
    print("  (* = fixed_night_interval endpoint)")

    dep_a_int, arr_b_int = interval_times(trip_b, trip_interval)
    span = arr_b_int - dep_a_int
    slack = {
        f"{s['from_stop']['stop_id']}->{s['to_stop']['stop_id']}": s["slack_time_min"]
        for s in trip_b["segments"]
        if s["slack_time_min"] > 0
    }
    dep_ok = dep_a_int < NIGHT_START
    arr_ok = arr_b_int >= NIGHT_END
    print(
        f"\n  B interval [{trip_interval[0]} -> {trip_interval[1]}]: "
        f"dep {hhmm(dep_a_int)} ({'OK, < 00:00' if dep_ok else 'VIOLATION, >= 00:00'}), "
        f"arr {hhmm(arr_b_int)} ({'OK, >= 05:00' if arr_ok else 'VIOLATION, < 05:00'}), "
        f"span {span}min"
    )
    print(f"  B slack per segment: {slack if slack else 'none (no stretch needed)'}")

    gp_a = trip_a["general_parameters"]
    gp_b = trip_b["general_parameters"]
    print(
        f"  duration/speed: A {gp_a['route_duration_min']}min @ "
        f"{gp_a['average_speed_kmh']}km/h   B {gp_b['route_duration_min']}min @ "
        f"{gp_b['average_speed_kmh']}km/h"
    )
    if gp_b["timetable_warnings"]:
        for w in gp_b["timetable_warnings"]:
            print(
                f"  B WARNING {w['code']}: interval {w['interval']} "
                f"timetable {w['timetable_speed_kmh']}km/h vs routing "
                f"{w['routing_speed_kmh']}km/h (ratio {w['ratio']})"
            )
    else:
        print("  B warnings: none")


def compare(scenario: dict, interval: list[str]) -> None:
    print(f"\nComparing timetable modes on {' -> '.join(STOPS)}")
    print(
        f"  scenario: {scenario['scenario_key']} ({scenario['scenario_name']}) "
        f"[scenario_id={scenario['scenario_id']}]"
    )
    print(f"  A: simpleAutomatic (mirror full trip around 02:30)")
    print(f"  B: simpleAutomaticWithFixedNight, interval {interval}")
    print("-" * 72)

    route_a = build_route(scenario["scenario_id"], None)
    route_b = build_route(scenario["scenario_id"], interval)

    trips_a = trips_by_direction(route_a)
    trips_b = trips_by_direction(route_b)
    for direction in (0, 1):
        print_direction(direction, trips_a[direction], trips_b[direction], interval)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    summary = {
        "stops": STOPS,
        "composition_id": COMPOSITION_ID,
        "scenario_id": scenario["scenario_id"],
        "scenario_key": scenario["scenario_key"],
        "fixed_night_interval": interval,
        "directions": {},
    }
    for direction in (0, 1):
        trip_interval = interval if direction == 0 else interval[::-1]
        dep_int, arr_int = interval_times(trips_b[direction], trip_interval)
        summary["directions"][f"D{direction}"] = {
            "timetable_a": [
                {
                    "stop_id": s["stop_id"],
                    "arrival_time_min": s["arrival_time_min"],
                    "departure_time_min": s["departure_time_min"],
                    "stop_type": s["stop_type"],
                }
                for s in trip_stops(trips_a[direction])
            ],
            "timetable_b": [
                {
                    "stop_id": s["stop_id"],
                    "arrival_time_min": s["arrival_time_min"],
                    "departure_time_min": s["departure_time_min"],
                    "stop_type": s["stop_type"],
                }
                for s in trip_stops(trips_b[direction])
            ],
            "b_interval_departure_min": dep_int,
            "b_interval_arrival_min": arr_int,
            "b_slack_per_segment": [
                s["slack_time_min"] for s in trips_b[direction]["segments"]
            ],
            "b_timetable_warnings": trips_b[direction]["general_parameters"][
                "timetable_warnings"
            ],
        }

    files = {
        "tc_3_muc_cph_simpleAutomatic_route_output.json": route_a,
        "tc_3_muc_cph_fixedNight_route_output.json": route_b,
        "tc_3_muc_cph_comparison_summary.json": summary,
    }
    for filename, payload in files.items():
        path = os.path.join(OUTPUT_DIR, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

    print(f"\nWrote {len(files)} files to {OUTPUT_DIR}/ (tc_3_muc_cph_*.json).")
    print("  No GeoJSON here — both modes route the identical path, only the")
    print("  timetable differs; use test_scenario_comparison_paris_berlin.py")
    print("  for map-level comparisons.")


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Compare simpleAutomatic vs simpleAutomaticWithFixedNight on "
            "München -> Berlin -> Hamburg -> København."
        )
    )
    parser.add_argument(
        "--interval",
        nargs=2,
        metavar=("START", "END"),
        default=DEFAULT_INTERVAL,
        help=(
            "fixed_night_interval stop IDs in outbound travel order "
            f"(default: {' '.join(DEFAULT_INTERVAL)})"
        ),
    )
    parser.add_argument("--scenario", default=DEFAULT_SCENARIO)
    args = parser.parse_args()

    for stop_id in args.interval:
        if stop_id not in STOPS:
            print(f"[✗] --interval stop '{stop_id}' is not in the route: {STOPS}")
            sys.exit(1)

    print("=" * 72)
    print("  Night Train — timetable mode comparison: München -> København")
    print("=" * 72)

    if not check_flask():
        sys.exit(1)
    if not ensure_data_loaded():
        sys.exit(1)
    if not ensure_routing_running():
        sys.exit(1)

    scenario = fetch_scenario(args.scenario)
    compare(scenario, list(args.interval))
