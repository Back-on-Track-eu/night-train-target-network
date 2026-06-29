"""
test_evaluate.py
================
Test script for POST /api/evaluation.

Pre-flight:
  1. Checks Flask API is reachable
  2. Loads data if not already loaded
  3. Checks OpenRailRouting is running; starts it if not
  4. Runs the evaluation endpoint

Route: Wien Hbf → Salzburg Hbf → München Hbf → Paris Est
Composition: NJ-5.1
"""

import json
import subprocess
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


def test_evaluate():
    payload = {
        "stops": [
            {"stop_id": "Wien Hbf", "stop_type": "boarding"},
            {"stop_id": "Salzburg Hbf", "stop_type": "both"},
            {"stop_id": "München Hbf", "stop_type": "both"},
            {"stop_id": "Paris Est", "stop_type": "alighting"},
        ],
        "composition_id": "NJ-5.1",
        "departure_time_h": 21.0,
        "utilization_seat": 0.7,
        "utilization_couchette": 0.6,
        "utilization_sleeper": 0.5,
        "avg_fare_seat": 49.0,
        "avg_fare_couchette": 79.0,
        "avg_fare_sleeper": 129.0,
        "operating_days_year": 360,
    }

    print("\nPOST /api/evaluation")
    print("Route: Wien Hbf → Salzburg Hbf → München Hbf → Paris Est")
    print("Composition: NJ-5.1")
    print("-" * 60)

    response = requests.post(f"{API_BASE}/api/evaluation", json=payload)
    print(f"Status: {response.status_code}")

    if response.status_code == 200:
        data = response.json()
        r = data["result"]
        print(f"\n--- ROUTE ---")
        print(f"  Distance:      {r['total_distance_km']:,.1f} km")
        print(f"  Driving time:  {r['total_driving_time_h']:.2f} h")
        print(f"  Total time:    {r['total_time_h']:.2f} h")
        print(f"\n--- REVENUE ---")
        print(f"  Seats:         {r['revenue']['revenue_seat']:,.0f} €")
        print(f"  Couchettes:    {r['revenue']['revenue_couchette']:,.0f} €")
        print(f"  Sleepers:      {r['revenue']['revenue_sleeper']:,.0f} €")
        print(f"  TOTAL:         {r['revenue']['total']:,.0f} €")
        print(f"\n--- COSTS ---")
        print(f"  Fixed/day:     {r['cost']['fixed_day_total']:,.0f} €")
        print(f"  Variable/km:   {r['cost']['variable_km_total']:,.0f} €")
        print(f"  Variable/h:    {r['cost']['variable_hour_total']:,.0f} €")
        print(f"  Variable/tkt:  {r['cost']['variable_ticket_total']:,.0f} €")
        print(f"  Infra:         {r['cost']['infra_total']:,.0f} €")
        print(f"  EBIT target:   {r['cost']['ebit_margin']:,.0f} €")
        print(f"  TOTAL:         {r['cost']['total']:,.0f} €")
        print(f"\n--- RESULT ---")
        print(f"  Margin/trip:   {r['margin']:,.0f} €  ({r['margin_pct']:.1%})")
        print(f"  Margin/year:   {r['annual_margin']:,.0f} €")
        print(f"  Cost/seat-km:  {r['cost_per_seat_km']:.4f} €")
    else:
        print(f"\nError response:")
        print(json.dumps(response.json(), indent=2))


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  Night Train — evaluation endpoint test")
    print("=" * 60)

    if not check_flask():
        exit(1)
    if not ensure_data_loaded():
        exit(1)
    if not ensure_routing_running():
        exit(1)

    test_evaluate()
