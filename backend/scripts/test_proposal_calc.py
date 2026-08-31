"""
test_proposal_calc.py
======================
Manual test script for POST /api/proposal/calc — the FULL merged response
(route + evaluation), not just the route-building half. Renamed and
rewritten from the former test_route_plan.py, which only inspected
route/geometry and left the evaluation block unexamined; this version
prints and validates both halves and exercises the error paths too.

Usage:
    python scripts/test_proposal_calc.py <path/to/request.json>

Reads the request body from the given JSON file, POSTs it to
/api/proposal/calc, and writes, alongside the request file (same base
name, e.g. tc_1_route_input.json):
  <base>_output.json             — the full raw response, pretty-printed
  <base>_eval_summary.json       — a flattened per_year cost/revenue/
                                    margin summary, machine-diffable
                                    across runs (see summarize_evaluation())
  <base>_lines.geojson           — every trip segment as a LineString,
                                    tagged trip_id/direction/from/to/timing
  <base>_stops.geojson           — every stop actually on the route (from
                                    both directions, deduped) as a Point,
                                    tagged auto_added so QGIS can style
                                    caller-supplied vs. auto-added stops
                                    differently
  <base>_suggested_stops.geojson — ONLY written when the request's
                                    auto_stop_addition="suggest": every
                                    candidate in the response's
                                    suggested_stops list as a Point, tagged
                                    added_time_min

On a non-200 response, no files are written except <base>_output.json
(the raw error body) — the script prints a shape-appropriate summary for
each of the endpoint's four documented error cases (validation_error,
domain_error, calc_error, or a non-JSON body) and exits non-zero.

On 200, in addition to printing route/evaluation summaries, the script
runs a lightweight structural check of the response (every top-level key
present, all six evaluation views present, route/evaluation numbers
internally consistent — see validate_response()) and reports any
violation rather than silently printing partial data.

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
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dev_env import api_base_url, routing_base_url  # noqa: E402

API_BASE = api_base_url()
ROUTING_URL = routing_base_url()
CONTAINER_NAME = "openrailrouting-infra-2026"

# The six views every evaluation response must carry — see
# models/evaluation/views.py's VIEW_META / api/README.md's "Proposal
# Compute (merged)" section.
EXPECTED_VIEWS = (
    "route",
    "per_trip_pair",
    "per_trip_pair_per_country",
    "per_trip_pair_per_od",
    "per_trip_pair_per_section",
    "per_trip_per_stop",
)

# Top-level keys every 200 response carries — suggested_stops is
# conditional (auto_stop_addition="suggest" only) and checked separately.
EXPECTED_TOP_LEVEL_KEYS = (
    "route_builder_version",
    "calc_version",
    "route_fingerprint",
    "cache_hit",
    "request",
    "route",
    "evaluation",
)


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
        f"[✗] Flask API not reachable at {API_BASE}. Start it with: uv run python main.py"
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
# EVALUATION SUMMARY
# =============================================================================


def route_breakdown(evaluation: dict, normalisation: str = "per_year") -> dict:
    """The whole-route, all-classes breakdown at one normalisation —
    evaluation.views.route.data[normalisation]["all"]. Every normalisation
    is class-keyed since CALC 0.9.9 ({"all": <breakdown>, class_main:
    <breakdown>, ...}; see models/evaluation/README.md's "Class axis"
    section) — there is no bare-breakdown form at any level, so this
    helper is the one place that reaches into the class axis rather than
    every caller repeating the ["all"] indexing."""
    return evaluation["views"]["route"]["data"][normalisation]["all"]


def summarize_evaluation(evaluation: dict) -> dict:
    """Flatten the route-level per_year breakdown (evaluation.views.route.
    data.per_year.all) down to the handful of numbers most useful for
    eyeballing a compute — the same fields
    scripts/test_scenario_comparison_paris_berlin.py diffs across scenarios.
    Written alongside the raw output so two runs' bottom lines can be
    diffed without wading through the full nested breakdown."""
    bd = route_breakdown(evaluation, "per_year")
    return {
        "total_cost_eur": bd["total_cost_eur"],
        "total_revenue_eur": bd["total_revenue_eur"],
        "net_eur": bd["net_eur"],
        "ebit_margin_eur": bd["margin"]["ebit_margin_eur"],
        "cost": {
            "operator_variable_eur": bd["cost"]["operator"]["variable"]["total_eur"],
            "operator_fixed_eur": bd["cost"]["operator"]["fixed"]["total_eur"],
            "infrastructure_eur": bd["cost"]["infrastructure"]["total_eur"],
            "tac_eur": bd["cost"]["infrastructure"]["tac_eur"],
            "energy_eur": bd["cost"]["infrastructure"]["energy_eur"],
            "station_charge_eur": bd["cost"]["infrastructure"]["station_charge_eur"],
            "parking_eur": bd["cost"]["infrastructure"]["parking_eur"],
        },
        "revenue": {
            "ticket_revenue_eur": bd["revenue"]["ticket_revenue_eur"],
        },
    }


def print_evaluation_summary(summary: dict) -> None:
    print("\n--- EVALUATION (per_year, EUR) ---")
    print(f"  {'total_cost_eur':24}{summary['total_cost_eur']:>16,.2f}")
    print(f"  {'total_revenue_eur':24}{summary['total_revenue_eur']:>16,.2f}")
    print(f"  {'net_eur':24}{summary['net_eur']:>16,.2f}")
    print(f"  {'ebit_margin_eur':24}{summary['ebit_margin_eur']:>16,.2f}")
    print("\n  cost breakdown:")
    for field, value in summary["cost"].items():
        print(f"    {field:22}{value:>16,.2f}")


# =============================================================================
# STRUCTURAL VALIDATION
# =============================================================================


def validate_response(body: dict) -> list[str]:
    """Lightweight structural check of a 200 response — not a replacement
    for tests/test_35_proposal_calc_api.py's real contract tests, just a
    fast sanity net so a broken response doesn't get skimmed over during
    manual testing. Returns a list of problems found (empty = clean)."""
    problems = []

    for key in EXPECTED_TOP_LEVEL_KEYS:
        if key not in body:
            problems.append(f"missing top-level key '{key}'")

    request_echo = body.get("request", {})
    if request_echo.get("auto_stop_addition") == "suggest":
        if "suggested_stops" not in body:
            problems.append(
                "auto_stop_addition='suggest' but 'suggested_stops' is absent"
            )
    elif "suggested_stops" in body:
        problems.append(
            f"'suggested_stops' present but auto_stop_addition="
            f"'{request_echo.get('auto_stop_addition')}' (only 'suggest' should carry it)"
        )

    route = body.get("route", {})
    if not route.get("trip_pairs"):
        problems.append("route.trip_pairs is empty or missing")

    evaluation = body.get("evaluation", {})
    for section in ("models", "input", "views"):
        if section not in evaluation:
            problems.append(f"evaluation.{section} is missing")
    if "route" in evaluation.get("input", {}):
        problems.append(
            "evaluation.input.route is present — should be omitted "
            "(include_route=False), the route already appears once as a "
            "sibling of 'evaluation'"
        )

    views = evaluation.get("views", {})
    for view_name in EXPECTED_VIEWS:
        if view_name not in views:
            problems.append(f"evaluation.views.{view_name} is missing")

    if not problems:
        try:
            bd = route_breakdown(evaluation, "per_year")
            expected_net = round(
                bd["total_revenue_eur"]
                - bd["total_cost_eur"]
                - bd["margin"]["ebit_margin_eur"],
                2,
            )
            if abs(bd["net_eur"] - expected_net) > 0.01:
                problems.append(
                    f"net_eur ({bd['net_eur']}) != total_revenue_eur - "
                    f"total_cost_eur - ebit_margin_eur ({expected_net})"
                )
        except KeyError as e:
            problems.append(f"could not check net_eur identity — missing key {e}")

    return problems


# =============================================================================
# ERROR RESPONSE HANDLING
# =============================================================================


def print_error_response(status_code: int, body: dict) -> None:
    """Prints a shape-appropriate summary for each of the endpoint's
    documented error cases (api/proposal_calc.py) rather than a generic
    JSON dump, so a manual test run makes it obvious which failure mode
    was hit."""
    error = body.get("error")
    if error == "bad_request":
        print(f"\n[400 bad_request] {body.get('message')}")
    elif error == "validation_error":
        print(f"\n[400 validation_error] {len(body.get('details', []))} problem(s):")
        for detail in body.get("details", []):
            print(f"  - {detail}")
    elif error == "domain_error":
        print(f"\n[422 domain_error] {body.get('message')}")
    elif error == "calc_error":
        print(f"\n[500 calc_error] {body.get('message')}")
    else:
        print(f"\n[{status_code}] Unrecognized error shape:")
        print(json.dumps(body, indent=2))


# =============================================================================
# TEST
# =============================================================================


def test_proposal_calc(path: str) -> bool:
    """Returns True if the compute succeeded and the response passed
    structural validation, False otherwise — the exit code the __main__
    block reports."""
    with open(path, "r", encoding="utf-8") as f:
        request_body = json.load(f)

    base, _ = os.path.splitext(path)
    output_path = f"{base}_output.json"
    eval_summary_path = f"{base}_eval_summary.json"
    lines_path = f"{base}_lines.geojson"
    stops_path = f"{base}_stops.geojson"
    suggested_stops_path = f"{base}_suggested_stops.geojson"

    print("\nPOST /api/proposal/calc")
    print(f"Request: {path}")
    print("-" * 60)

    response = requests.post(f"{API_BASE}/api/proposal/calc", json=request_body)
    print(f"Status: {response.status_code}")

    try:
        response_body = response.json()
    except requests.exceptions.JSONDecodeError:
        # Not a JSON body at all — most likely a raw Flask/Werkzeug error page,
        # meaning the exception happened outside api/proposal_calc.py's own try/except.
        # Check the Flask server's own terminal for the actual traceback.
        print("\nNon-JSON response body (raw Flask error page?) — check the Flask")
        print("server's terminal for the actual traceback. Raw response body:\n")
        print(response.text)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(response.text)
        return False

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(response_body, f, indent=2, ensure_ascii=False)

    if response.status_code != 200:
        print_error_response(response.status_code, response_body)
        print(f"\nWrote raw error body to {output_path}")
        return False

    problems = validate_response(response_body)
    if problems:
        print(f"\n--- STRUCTURAL VALIDATION FAILED ({len(problems)} problem(s)) ---")
        for p in problems:
            print(f"  - {p}")
    else:
        print("\n--- STRUCTURAL VALIDATION: OK ---")

    route = response_body["route"]
    evaluation = response_body["evaluation"]

    print("\n--- COMPUTE META ---")
    print(f"  route_builder_version: {response_body['route_builder_version']}")
    print(f"  calc_version:          {response_body['calc_version']}")
    print(f"  route_fingerprint:     {response_body['route_fingerprint']}")
    print(f"  cache_hit:             {response_body['cache_hit']}")

    print("\n--- ROUTE ---")
    print(f"  route_id:     {route['route_id']}")
    print(f"  scenario_id:  {route['scenario_id']}")
    print(f"  trip_pairs:   {len(route['trip_pairs'])}")

    eval_summary = summarize_evaluation(evaluation)
    print_evaluation_summary(eval_summary)
    with open(eval_summary_path, "w", encoding="utf-8") as f:
        json.dump(eval_summary, f, indent=2, ensure_ascii=False)

    lines_fc, stops_fc = route_to_geojson(route)
    with open(lines_path, "w", encoding="utf-8") as f:
        json.dump(lines_fc, f, indent=2, ensure_ascii=False)
    with open(stops_path, "w", encoding="utf-8") as f:
        json.dump(stops_fc, f, indent=2, ensure_ascii=False)
    print(
        f"\n--- GEOJSON ---\n  {len(lines_fc['features'])} line segment(s), "
        f"{len(stops_fc['features'])} stop(s)"
    )

    written = [output_path, eval_summary_path, lines_path, stops_path]

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

    print(f"\nWrote {len(written)} file(s):")
    for w in written:
        print(f"  {w}")

    return not problems


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/test_proposal_calc.py <path/to/request.json>")
        sys.exit(1)

    print("=" * 60)
    print("  Night Train — POST /api/proposal/calc (full response) test")
    print("=" * 60)

    if not check_flask():
        sys.exit(1)
    if not ensure_data_loaded():
        sys.exit(1)
    if not ensure_routing_running():
        sys.exit(1)

    ok = test_proposal_calc(sys.argv[1])
    sys.exit(0 if ok else 1)
