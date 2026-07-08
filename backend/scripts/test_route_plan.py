"""
test_route_plan.py
===================
Manual test script for POST /api/route/plan.

Usage:
    python scripts/test_route_plan.py <path/to/request.json>

Reads the request body from the given JSON file, POSTs it to
/api/route/plan, and writes the response (pretty-printed) to a sibling
file named <request>_output.json — e.g. tc_1_route_input.json produces
tc_1_route_input_output.json alongside it. The request file itself is
left untouched.

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
# TEST
# =============================================================================


def test_route_plan(path: str):
    with open(path, "r", encoding="utf-8") as f:
        request_body = json.load(f)

    base, _ = os.path.splitext(path)
    output_path = f"{base}_output.json"

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

    if response.status_code == 200:
        route = response_body["route"]
        print(f"\n--- ROUTE ---")
        print(f"  route_id:     {route['route_id']}")
        print(f"  scenario_id:  {route['scenario_id']}")
        print(f"  trip_pairs:   {len(route['trip_pairs'])}")
    else:
        print(f"\nError response:")
        print(json.dumps(response_body, indent=2))

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(response_body, f, indent=2, ensure_ascii=False)
    print(f"\nResponse written to {output_path}")


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
