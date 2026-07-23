"""
test_scenario_comparison_paris_berlin.py
=========================================
Manual test script comparing two scenarios on the same corridor:

  Paris Gare de l'Est -> Bruxelles-Midi -> Hamburg Hbf -> Berlin Hbf

By default this compares the two *current* scenarios:
  - "base"                      2032 Base Line (track_hsr_allowed=False
                                 everywhere — night trains may not use
                                 HSR infrastructure)
  - "2032-baseline-hsr-allowed" 2032 Base Line + Night Trains on HSR
                                 allowed (identical to base except
                                 track_hsr_allowed=True everywhere)

track_hsr_allowed feeds directly into route PLANNING, not just cost —
rail_router.py penalizes track segments whose permitted speed exceeds
HSR_TRACK_SPEED_THRESHOLD_KMH (models/route/version.py) in every country
where HSR is not allowed (composition.hsr_allowed AND that country's
track hsr_allowed, transited-only countries included).
So the two scenarios can legitimately produce different routed paths
(distance/time), not just different tac_eur figures. This script surfaces
both: the routing-level diff (distance, driving time, per-country
hsr_allowed) and the cost-level diff (POST /api/evaluation/calc).

The 2026 Base Line ("2026-baseline") is deliberately excluded — it's a
deprecated historical reference, not a live policy comparison.

Usage:
    python scripts/test_scenario_comparison_paris_berlin.py
    python scripts/test_scenario_comparison_paris_berlin.py --scenario-a base --scenario-b 2032-baseline-hsr-allowed

Writes raw route/evaluation responses, a comparison summary, and per-scenario
GeoJSON layers (routed lines + stops) to scripts/data/ (tc_2_paris_berlin_*).
Same GeoJSON shape/logic as scripts/test_route_plan.py's route_to_geojson()
— kept in sync deliberately so outputs from both scripts drag into the same
QGIS project consistently (Layer > Add Layer > Add Vector Layer) to compare
routed paths visually. Pre-flight:
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

STOPS = ["FR_PARIS_EST", "BE_BRUSSELS_M", "DE_HAMBURG_HBF", "DE_BERLIN_HBF"]
COMPOSITION_ID = "STD-7.1"

DEFAULT_SCENARIO_A = "base"
DEFAULT_SCENARIO_B = "2032-baseline-hsr-allowed"


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
# ROUTE + EVALUATION
# =============================================================================


def build_route(scenario_id: int) -> dict:
    body = {
        "scenario_id": scenario_id,
        "stops": STOPS,
        "composition_id": COMPOSITION_ID,
        "routing_mode": "fullRouting",
        "timetable_mode": "simpleAutomatic",
        "schedule_mode": "alwaysDaily",
        # Fixed stop list — isolates the comparison to what the scenario
        # itself changes (routing/parameters), not auto-added stops.
        "auto_stop_addition": "off",
    }
    resp = requests.post(f"{API_BASE}/api/route/plan", json=body, timeout=90)
    if resp.status_code != 200:
        print(f"[✗] route/plan failed for scenario_id={scenario_id}: {resp.text[:300]}")
        sys.exit(1)
    return resp.json()["route"]


def evaluate_route(route: dict, scenario_id: int) -> dict:
    body = {"route": route, "scenario_id": scenario_id}
    resp = requests.post(f"{API_BASE}/api/evaluation/calc", json=body, timeout=60)
    if resp.status_code != 200:
        print(
            f"[✗] evaluation/calc failed for scenario_id={scenario_id}: {resp.text[:300]}"
        )
        sys.exit(1)
    return resp.json()


def outbound_trip_summary(route: dict) -> dict:
    """Sum distance/time across the outbound trip's segments — one number
    per direction is enough to see whether the routed path itself changed."""
    outbound = route["trip_pairs"][0]["outbound"]
    segments = outbound["segments"]
    return {
        "distance_km": sum(s["distance_m"] for s in segments) / 1000,
        "driving_time_min": sum(s["driving_time_min"] for s in segments),
        "dynamics_time_min": sum(s["dynamics_time_min"] for s in segments),
        "buffer_time_min": sum(s["buffer_time_min"] for s in segments),
        "segment_count": len(segments),
    }


def track_hsr_flags(route: dict) -> dict:
    return {t["country_code"]: t["hsr_allowed"] for t in route["track_infrastructure"]}


# =============================================================================
# GEOJSON EXPORT (for QGIS)
# =============================================================================


def route_to_geojson(route: dict, scenario_key: str) -> tuple[dict, dict]:
    """Build two GeoJSON FeatureCollections for one route — a LineString
    layer (every routed segment, outbound + return, every trip pair) and a
    Point layer (every stop it touches). Returned separately rather than as
    one mixed FeatureCollection: QGIS's "Add Vector Layer" renders only the
    first feature's geometry type from a mixed file, silently dropping the
    rest, so lines and points need their own files to both show up.

    Segment.geometry is already stored as [[lon, lat], ...] (see
    models/route/trip.py) — GeoJSON coordinate order, no conversion needed.
    Every feature carries scenario_key as a property, so loading both
    scenarios' layers into the same QGIS project lets you style/filter by
    scenario without renaming layers."""
    geometry_by_id = {g["id"]: g["coords"] for g in route["geometries"]}

    line_features = []
    stop_features = {}  # keyed by stop_id — dedupes a stop reused across trips

    for pair in route["trip_pairs"]:
        for direction_key in ("outbound", "return_trip"):
            trip = pair[direction_key]
            for seg in trip["segments"]:
                coords = geometry_by_id.get(seg["geometry_id"])
                if not coords:
                    continue
                line_features.append(
                    {
                        "type": "Feature",
                        "geometry": {"type": "LineString", "coordinates": coords},
                        "properties": {
                            "scenario_key": scenario_key,
                            "trip_id": trip["trip_id"],
                            "direction": trip["direction"],
                            "from_stop_id": seg["from_stop"]["stop_id"],
                            "to_stop_id": seg["to_stop"]["stop_id"],
                            "distance_km": round(seg["distance_m"] / 1000, 3),
                            "driving_time_min": seg["driving_time_min"],
                            "dynamics_time_min": seg["dynamics_time_min"],
                            "buffer_time_min": seg["buffer_time_min"],
                        },
                    }
                )
                for stop in (seg["from_stop"], seg["to_stop"]):
                    stop_features.setdefault(
                        stop["stop_id"],
                        {
                            "type": "Feature",
                            "geometry": {
                                "type": "Point",
                                "coordinates": [stop["lon"], stop["lat"]],
                            },
                            "properties": {
                                "scenario_key": scenario_key,
                                "stop_id": stop["stop_id"],
                                "stop_name": stop["stop_name"],
                                "country_code": stop["country_code"],
                                "auto_added": stop["auto_added"],
                            },
                        },
                    )

    lines_fc = {"type": "FeatureCollection", "features": line_features}
    stops_fc = {"type": "FeatureCollection", "features": list(stop_features.values())}
    return lines_fc, stops_fc


# =============================================================================
# COMPARISON
# =============================================================================


def compare(scenario_a: dict, scenario_b: dict) -> None:
    label_a = f"{scenario_a['scenario_key']} ({scenario_a['scenario_name']})"
    label_b = f"{scenario_b['scenario_key']} ({scenario_b['scenario_name']})"

    print(f"\nComparing scenarios on {' -> '.join(STOPS)}")
    print(f"  A: {label_a}  [scenario_id={scenario_a['scenario_id']}]")
    print(f"  B: {label_b}  [scenario_id={scenario_b['scenario_id']}]")
    print("-" * 72)

    route_a = build_route(scenario_a["scenario_id"])
    route_b = build_route(scenario_b["scenario_id"])
    eval_a = evaluate_route(route_a, scenario_a["scenario_id"])
    eval_b = evaluate_route(route_b, scenario_b["scenario_id"])

    trip_a = outbound_trip_summary(route_a)
    trip_b = outbound_trip_summary(route_b)
    hsr_a = track_hsr_flags(route_a)
    hsr_b = track_hsr_flags(route_b)

    bd_a = eval_a["views"]["route"]["data"]["per_year"]
    bd_b = eval_b["views"]["route"]["data"]["per_year"]
    tac_a = bd_a["cost"]["infrastructure"]["tac_eur"]
    tac_b = bd_b["cost"]["infrastructure"]["tac_eur"]

    print(f"\n--- ROUTING ---")
    print(f"  {'':20}{'A':>18}{'B':>18}{'delta':>14}")
    print(f"  {'route_id':20}{route_a['route_id']:>18}{route_b['route_id']:>18}")
    print(
        f"  {'distance_km':20}{trip_a['distance_km']:>18.1f}"
        f"{trip_b['distance_km']:>18.1f}"
        f"{trip_b['distance_km'] - trip_a['distance_km']:>14.1f}"
    )
    print(
        f"  {'driving_time_min':20}{trip_a['driving_time_min']:>18.1f}"
        f"{trip_b['driving_time_min']:>18.1f}"
        f"{trip_b['driving_time_min'] - trip_a['driving_time_min']:>14.1f}"
    )
    print(
        f"  {'segment_count':20}{trip_a['segment_count']:>18}{trip_b['segment_count']:>18}"
    )

    print(f"\n--- track_hsr_allowed per transited country ---")
    for cc in sorted(set(hsr_a) | set(hsr_b)):
        flag_a = hsr_a.get(cc)
        flag_b = hsr_b.get(cc)
        marker = "  <-- differs" if flag_a != flag_b else ""
        print(f"  {cc}: A={flag_a!s:<6} B={flag_b!s:<6}{marker}")

    print(f"\n--- COST (per_year, EUR) ---")
    print(f"  {'':22}{'A':>16}{'B':>16}{'delta':>14}")
    for field in ("total_cost_eur", "total_revenue_eur", "net_eur"):
        va, vb = bd_a[field], bd_b[field]
        print(f"  {field:22}{va:>16,.2f}{vb:>16,.2f}{vb - va:>14,.2f}")
    print(
        f"  {'tac_eur (infra)':22}{tac_a:>16,.2f}{tac_b:>16,.2f}{tac_b - tac_a:>14,.2f}"
    )

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    lines_a, stops_a = route_to_geojson(route_a, scenario_a["scenario_key"])
    lines_b, stops_b = route_to_geojson(route_b, scenario_b["scenario_key"])
    files = {
        f"tc_2_paris_berlin_{scenario_a['scenario_key']}_route_output.json": route_a,
        f"tc_2_paris_berlin_{scenario_b['scenario_key']}_route_output.json": route_b,
        f"tc_2_paris_berlin_{scenario_a['scenario_key']}_eval_output.json": eval_a,
        f"tc_2_paris_berlin_{scenario_b['scenario_key']}_eval_output.json": eval_b,
        f"tc_2_paris_berlin_{scenario_a['scenario_key']}_lines.geojson": lines_a,
        f"tc_2_paris_berlin_{scenario_a['scenario_key']}_stops.geojson": stops_a,
        f"tc_2_paris_berlin_{scenario_b['scenario_key']}_lines.geojson": lines_b,
        f"tc_2_paris_berlin_{scenario_b['scenario_key']}_stops.geojson": stops_b,
    }
    summary = {
        "stops": STOPS,
        "composition_id": COMPOSITION_ID,
        "scenario_a": {
            "scenario_id": scenario_a["scenario_id"],
            "scenario_key": scenario_a["scenario_key"],
            "route_id": route_a["route_id"],
            **trip_a,
            "track_hsr_allowed": hsr_a,
            "total_cost_eur": bd_a["total_cost_eur"],
            "total_revenue_eur": bd_a["total_revenue_eur"],
            "net_eur": bd_a["net_eur"],
            "tac_eur": tac_a,
        },
        "scenario_b": {
            "scenario_id": scenario_b["scenario_id"],
            "scenario_key": scenario_b["scenario_key"],
            "route_id": route_b["route_id"],
            **trip_b,
            "track_hsr_allowed": hsr_b,
            "total_cost_eur": bd_b["total_cost_eur"],
            "total_revenue_eur": bd_b["total_revenue_eur"],
            "net_eur": bd_b["net_eur"],
            "tac_eur": tac_b,
        },
    }
    files["tc_2_paris_berlin_comparison_summary.json"] = summary

    for filename, payload in files.items():
        path = os.path.join(OUTPUT_DIR, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

    print(f"\nWrote {len(files)} files to {OUTPUT_DIR}/ (tc_2_paris_berlin_*.json,")
    print("  plus *_lines.geojson / *_stops.geojson per scenario — drag")
    print("  straight into QGIS: Layer > Add Layer > Add Vector Layer. Each")
    print("  scenario gets its own LineString layer (routed segments) and")
    print("  Point layer (stops), both tagged scenario_key, so you can load")
    print("  all four into one project and style/filter by scenario.)")


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Compare two scenarios on Paris -> Brussels -> Hamburg -> Berlin."
    )
    parser.add_argument("--scenario-a", default=DEFAULT_SCENARIO_A)
    parser.add_argument("--scenario-b", default=DEFAULT_SCENARIO_B)
    args = parser.parse_args()

    print("=" * 72)
    print("  Night Train — scenario comparison: Paris -> Brussels -> Hamburg -> Berlin")
    print("=" * 72)

    if not check_flask():
        sys.exit(1)
    if not ensure_data_loaded():
        sys.exit(1)
    if not ensure_routing_running():
        sys.exit(1)

    scenario_a = fetch_scenario(args.scenario_a)
    scenario_b = fetch_scenario(args.scenario_b)
    compare(scenario_a, scenario_b)
