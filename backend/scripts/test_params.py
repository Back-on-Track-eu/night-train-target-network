"""
test_params.py
===============
Manual test script for the read-only params endpoints:

  GET /api/params/StopInfrastructures
  GET /api/params/compositions
  GET /api/params/TrackInfrastructures

Usage:
    python scripts/test_params.py [endpoint] [scenario_id]

    endpoint    : stops | compositions | tracks | all (default: all)
    scenario_id : int (optional) — pins parameter versions; omit for the
                  live is_current_base scenario.

Writes the response (pretty-printed) to scripts/data/params_<endpoint>_output.json.

Pre-flight:
  1. Checks Flask API is reachable
  2. Loads data if not already loaded
"""

import json
import os
import sys
import requests

API_BASE = "http://localhost:5000"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "data")

ENDPOINTS = {
    "stops": "/api/params/StopInfrastructures",
    "compositions": "/api/params/compositions",
    "tracks": "/api/params/TrackInfrastructures",
}


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


# =============================================================================
# TEST
# =============================================================================


def test_params(endpoint: str, scenario_id: int | None):
    path = ENDPOINTS[endpoint]
    output_path = os.path.join(OUTPUT_DIR, f"params_{endpoint}_output.json")

    params = {"scenario_id": scenario_id} if scenario_id is not None else {}

    print(f"\nGET {path}")
    if scenario_id is not None:
        print(f"scenario_id: {scenario_id}")
    print("-" * 60)

    response = requests.get(f"{API_BASE}{path}", params=params)
    print(f"Status: {response.status_code}")

    try:
        response_body = response.json()
    except requests.exceptions.JSONDecodeError:
        # Not a JSON body at all — most likely a raw Flask/Werkzeug error page,
        # meaning the exception happened outside the blueprint's own try/except.
        # Check the Flask server's own terminal for the actual traceback.
        print("\nNon-JSON response body (raw Flask error page?) — check the Flask")
        print("server's terminal for the actual traceback. Raw response body:\n")
        print(response.text)
        return

    if response.status_code == 200:
        if endpoint == "stops":
            stops = response_body["stops"]
            print(f"\n--- STOPS ({len(stops)}) ---")
            if stops:
                s = stops[0]
                print(f"  first: {s['stop_id']} ({s['name']}, {s['country_code']})")
        elif endpoint == "compositions":
            comps = response_body["compositions"]
            print(f"\n--- COMPOSITIONS ({len(comps)}) ---")
            if comps:
                c = comps[0]
                print(f"  first: {c['comp_id']} ({c['description']})")
        elif endpoint == "tracks":
            tracks = response_body["track_infrastructures"]
            print(f"\n--- TRACK INFRASTRUCTURES ({len(tracks)}) ---")
            if tracks:
                t = tracks[0]
                print(f"  first: {t['country_code']}")
    else:
        print(f"\nError response:")
        print(json.dumps(response_body, indent=2))

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(response_body, f, indent=2, ensure_ascii=False)
    print(f"\nResponse written to {output_path}")


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    if len(sys.argv) > 3:
        print("Usage: python scripts/test_params.py [endpoint] [scenario_id]")
        print("  endpoint: stops | compositions | tracks | all (default: all)")
        sys.exit(1)

    endpoint_arg = sys.argv[1] if len(sys.argv) >= 2 else "all"
    scenario_id_arg = int(sys.argv[2]) if len(sys.argv) == 3 else None

    if endpoint_arg != "all" and endpoint_arg not in ENDPOINTS:
        print(f"Unknown endpoint '{endpoint_arg}'. Choose from: stops, compositions, tracks, all")
        sys.exit(1)

    print("=" * 60)
    print("  Night Train — params endpoints test")
    print("=" * 60)

    if not check_flask():
        sys.exit(1)
    if not ensure_data_loaded():
        sys.exit(1)

    targets = ENDPOINTS.keys() if endpoint_arg == "all" else [endpoint_arg]
    for ep in targets:
        test_params(ep, scenario_id_arg)