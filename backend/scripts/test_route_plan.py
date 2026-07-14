"""
test_route_plan.py
===================
Manual test script for POST /api/route/plan.

Usage:
    python scripts/test_route_plan.py <path/to/request.json>

Reads the request body from the given JSON file, POSTs it to
/api/route/plan, and writes, alongside the request file (same base name,
e.g. tc_1_route_input.json):
  <base>_output.json           — the full raw response, pretty-printed
  <base>_lines.geojson         — every trip segment as a LineString,
                                  tagged trip_id/direction/from/to/timing
  <base>_stops.geojson         — every stop actually on the route (from
                                  both directions, deduped) as a Point,
                                  tagged auto_added so QGIS can style
                                  caller-supplied vs. auto-added stops
                                  differently
  <base>_suggested_stops.geojson — ONLY written when the request's
                                  auto_stop_addition="suggest": every
                                  candidate in the response's
                                  suggested_stops list as a Point, tagged
                                  added_time_min

Same GeoJSON shape/logic as
scripts/test_scenario_comparison_paris_berlin.py's route_to_geojson(), so
outputs from both scripts drag into the same QGIS project consistently
(Layer > Add Layer > Add Vector Layer). The request file itself is left
untouched.

Pre-flight:
  1. Checks Flask API is reachable
  2. Loads data if not already loaded
  3. Checks OpenRailRouting is running; starts it if not
"""

import json
import os
import subprocess
import sys
import time
import requests

API_BASE = "http://localhost:5000"
ROUTING_URL = "http://localhost:8989"
CONTAINER_NAME = "openrailrouting"


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
        print(f"    ...waiting ({(i+1)*2}s)")

    print("[✗] OpenRailRouting did not become ready in time.")
    return False


# =============================================================================
# GEOJSON CONVERSION
# =============================================================================
# Same shape/logic as test_scenario_comparison_paris_berlin.py's
# route_to_geojson() — kept in sync deliberately so outputs from both
# scripts load into the same QGIS project consistently. This script has
# no scenario_key to tag features with (single route, not a comparison),
# so that property is simply omitted here.


def route_to_geojson(route: dict) -> tuple[dict, dict]:
    """(lines_fc, stops_fc) — every trip segment as a LineString feature,
    every stop actually on the route as a Point feature (deduped across
    outbound/return by stop_id, both directions cover the same stops)."""
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


def suggested_stops_to_geojson(suggested_stops: list[dict]) -> dict:
    """suggested_stops (auto_stop_addition="suggest" only) as a Point
    FeatureCollection, tagged with the added_time_min each stop would cost
    if implemented — separate file/layer from the route's own stops.geojson
    since these were never added to the route."""
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [s["lon"], s["lat"]]},
            "properties": {
                "stop_id": s["stop_id"],
                "stop_name": s["stop_name"],
                "country_code": s["country_code"],
                "added_time_min": s["added_time_min"],
            },
        }
        for s in suggested_stops
    ]
    return {"type": "FeatureCollection", "features": features}


# =============================================================================
# TEST
# =============================================================================


def test_route_plan(path: str):
    with open(path, "r", encoding="utf-8") as f:
        request_body = json.load(f)

    base, _ = os.path.splitext(path)
    output_path = f"{base}_output.json"
    lines_path = f"{base}_lines.geojson"
    stops_path = f"{base}_stops.geojson"
    suggested_stops_path = f"{base}_suggested_stops.geojson"

    print(f"\nPOST /api/route/plan")
    print(f"Request: {path}")
    print("-" * 60)

    response = requests.post(f"{API_BASE}/api/route/plan", json=request_body)
    print(f"Status: {response.status_code}")

    try:
        response_body = response.json()
    except requests.exceptions.JSONDecodeError:
        # Not a JSON body at all — most likely a raw Flask/Werkzeug error page,
        # meaning the exception happened outside api/route.py's own try/except.
        # Check the Flask server's own terminal for the actual traceback.
        print("\nNon-JSON response body (raw Flask error page?) — check the Flask")
        print("server's terminal for the actual traceback. Raw response body:\n")
        print(response.text)
        sys.exit(1)

    written = [output_path]

    if response.status_code == 200:
        route = response_body["route"]
        print(f"\n--- ROUTE ---")
        print(f"  route_id:     {route['route_id']}")
        print(f"  scenario_id:  {route['scenario_id']}")
        print(f"  trip_pairs:   {len(route['trip_pairs'])}")

        lines_fc, stops_fc = route_to_geojson(route)
        with open(lines_path, "w", encoding="utf-8") as f:
            json.dump(lines_fc, f, indent=2, ensure_ascii=False)
        with open(stops_path, "w", encoding="utf-8") as f:
            json.dump(stops_fc, f, indent=2, ensure_ascii=False)
        written += [lines_path, stops_path]
        print(
            f"\n--- GEOJSON ---\n  {len(lines_fc['features'])} line segment(s), "
            f"{len(stops_fc['features'])} stop(s)"
        )

        # Only present for auto_stop_addition="suggest" in the request.
        if "suggested_stops" in response_body:
            suggested = response_body["suggested_stops"]
            print(f"\n--- SUGGESTED STOPS ({len(suggested)}) ---")
            for s in suggested:
                print(
                    f"  {s['stop_id']:<24} {s['stop_name']:<28} "
                    f"+{s['added_time_min']:.1f} min"
                )
            with open(suggested_stops_path, "w", encoding="utf-8") as f:
                json.dump(
                    suggested_stops_to_geojson(suggested),
                    f,
                    indent=2,
                    ensure_ascii=False,
                )
            written.append(suggested_stops_path)
    else:
        print(f"\nError response:")
        print(json.dumps(response_body, indent=2))

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(response_body, f, indent=2, ensure_ascii=False)

    print(f"\nWrote {len(written)} file(s):")
    for w in written:
        print(f"  {w}")


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/test_route_plan.py <path/to/request.json>")
        sys.exit(1)

    print("=" * 60)
    print("  Night Train — route/plan endpoint test")
    print("=" * 60)

    if not check_flask():
        sys.exit(1)
    if not ensure_data_loaded():
        sys.exit(1)
    if not ensure_routing_running():
        sys.exit(1)

    test_route_plan(sys.argv[1])