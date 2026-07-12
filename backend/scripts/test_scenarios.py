"""
test_scenarios.py
==================
Manual test script for the read-only scenario listing endpoint:

  GET /api/scenarios

Usage:
    python scripts/test_scenarios.py

Writes the response (pretty-printed) to scripts/data/scenarios_output.json.

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
OUTPUT_PATH = os.path.join(OUTPUT_DIR, "scenarios_output.json")

ENDPOINT = "/api/scenarios"
GROUPS = ("current_base", "current_scenarios", "historical_scenarios")


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


def _print_group(name: str, group: dict) -> None:
    scenarios = group["scenarios"]
    print(f"\n--- {name.upper()} ({group['count']}) ---")
    for s in scenarios:
        print(
            f"  {s['scenario_id']:>4}  {s['scenario_key']:<28} "
            f"'{s['scenario_name']}'  base={s['is_current_base']}  "
            f"current={s['is_current_scenario']}  created={s['created_at']}"
        )


def test_scenarios():
    print(f"\nGET {ENDPOINT}")
    print("-" * 60)

    response = requests.get(f"{API_BASE}{ENDPOINT}")
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
        print(f"\ntotal_count: {response_body['total_count']}")
        for group_name in GROUPS:
            _print_group(group_name, response_body[group_name])
    else:
        print(f"\nError response:")
        print(json.dumps(response_body, indent=2))

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(response_body, f, indent=2, ensure_ascii=False)
    print(f"\nResponse written to {OUTPUT_PATH}")


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    if len(sys.argv) > 1:
        print("Usage: python scripts/test_scenarios.py")
        sys.exit(1)

    print("=" * 60)
    print("  Night Train — scenarios endpoint test")
    print("=" * 60)

    if not check_flask():
        sys.exit(1)
    if not ensure_data_loaded():
        sys.exit(1)

    test_scenarios()
