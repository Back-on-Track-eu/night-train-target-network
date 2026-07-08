"""
test_evaluation_calc.py
========================
Manual test script for POST /api/evaluation/calc.

Usage:
    python scripts/test_evaluation_calc.py <path/to/request.json>

Reads the request body from the given JSON file (a
{"route": <route_to_dict() output>, "scenario_id": <optional int>}
payload — see scripts/data/tc_1_evaluation_input.json), POSTs it to
/api/evaluation/calc, and writes the response (pretty-printed) to a
sibling file named <request>_output.json — e.g. tc_1_evaluation_input.json
produces tc_1_evaluation_input_output.json alongside it. The request
file itself is left untouched.

Pre-flight:
  1. Checks Flask API is reachable
  2. Loads data if not already loaded

Note: unlike test_route_plan.py, this does not need OpenRailRouting —
evaluation/calc costs an already-built Route JSON, it doesn't route.
"""

import json
import os
import sys
import requests

API_BASE = "http://localhost:5000"


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


def test_evaluation_calc(path: str):
    with open(path, "r", encoding="utf-8") as f:
        request_body = json.load(f)

    base, _ = os.path.splitext(path)
    output_path = f"{base}_output.json"

    print(f"\nPOST /api/evaluation/calc")
    print(f"Request: {path}")
    print("-" * 60)

    response = requests.post(f"{API_BASE}/api/evaluation/calc", json=request_body)
    print(f"Status: {response.status_code}")

    try:
        response_body = response.json()
    except requests.exceptions.JSONDecodeError:
        # Not a JSON body at all — most likely a raw Flask/Werkzeug error page,
        # meaning the exception happened outside api/evaluation.py's own try/except.
        # Check the Flask server's own terminal for the actual traceback.
        print("\nNon-JSON response body (raw Flask error page?) — check the Flask")
        print("server's terminal for the actual traceback. Raw response body:\n")
        print(response.text)
        sys.exit(1)

    if response.status_code == 200:
        # As of CALC_VERSION 1.1.0 the response is flat: calc_version,
        # route_id, models, input, and views are all top-level — there is
        # no "result" wrapper. As of the views_meta merge, each view is
        # {"description", "normalisations", "data"} — actual numbers live
        # under "data" (and, for filtered views, under "data"."<key>"."values").
        route_view = response_body["views"]["route"]["data"]["per_year"]
        pair_count = len(response_body["views"]["per_trip_pair"]["data"])
        model_names = list(response_body["models"].keys())
        print(f"\n--- EVALUATION RESULT ---")
        print(f"  calc_version:      {response_body['calc_version']}")
        print(f"  route_id:          {response_body['route_id']}")
        print(f"  models:            {', '.join(model_names)}")
        print(f"  trip_pairs:        {pair_count}")
        print(f"  total_cost_eur:    {route_view['total_cost_eur']:,.2f}")
        print(f"  total_revenue_eur: {route_view['total_revenue_eur']:,.2f}")
        print(f"  net_eur:           {route_view['net_eur']:,.2f}")
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
        print("Usage: python scripts/test_evaluation_calc.py <path/to/request.json>")
        sys.exit(1)

    print("=" * 60)
    print("  Night Train — evaluation/calc endpoint test")
    print("=" * 60)

    if not check_flask():
        sys.exit(1)
    if not ensure_data_loaded():
        sys.exit(1)

    test_evaluation_calc(sys.argv[1])
