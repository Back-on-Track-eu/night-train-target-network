"""
test_pipeline.py
================
End-to-end integration test for the full evaluate pipeline.

Tests:
  - POST /api/evaluate returns 200 with a valid ModelResult
  - All result fields are present and have sensible values
  - Revenue calculation is correct given inputs
  - Capacity matches the composition
  - Validation errors are returned correctly for bad input
"""

import requests
import pytest


API_EVALUATE = "/api/evaluate"

# ---------------------------------------------------------------------------
# Known-good request using seeded test data
# ---------------------------------------------------------------------------

VALID_REQUEST = {
    "stops": [
        {"stop_id": "DE_BERLIN_HBF",  "stop_type": "boarding"},
        {"stop_id": "DE_DRESDEN_HBF", "stop_type": "both"},
        {"stop_id": "AT_WIEN_HBF",    "stop_type": "alighting"},
    ],
    "composition_id":        "STD-5.1",
    "departure_time_h":      21.0,
    "utilization_seat":      0.7,
    "utilization_couchette": 0.6,
    "utilization_sleeper":   0.5,
    "avg_fare_seat":         49.0,
    "avg_fare_couchette":    79.0,
    "avg_fare_sleeper":      129.0,
    "operating_days_year":   360,
}

# STD-5.1 capacity from seed data
COMP_SEATS      = 80
COMP_COUCHETTES = 144
COMP_SLEEPERS   = 24


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def evaluate_result(api_base):
    """Run the evaluate endpoint once and share the result across tests."""
    resp = requests.post(
        f"{api_base}{API_EVALUATE}",
        json=VALID_REQUEST,
        timeout=30,
    )
    assert resp.status_code == 200, \
        f"Evaluate failed: {resp.status_code} — {resp.text}"
    return resp.json()["result"]


def test_evaluate_returns_200(api_base):
    """POST /api/evaluate returns 200 for a valid request."""
    resp = requests.post(f"{api_base}{API_EVALUATE}", json=VALID_REQUEST, timeout=30)
    assert resp.status_code == 200


def test_result_has_required_keys(evaluate_result):
    """Result contains all expected top-level keys."""
    required = {
        "composition_id", "total_distance_km", "total_driving_time_h",
        "total_time_h", "operating_days_year", "revenue", "cost",
        "allocation", "capacity", "margin", "margin_pct",
        "annual_margin", "cost_per_seat_km",
    }
    missing = required - set(evaluate_result.keys())
    assert missing == set(), f"Missing result keys: {missing}"


def test_composition_id_matches_request(evaluate_result):
    """Result composition_id matches the requested composition."""
    assert evaluate_result["composition_id"] == VALID_REQUEST["composition_id"]


def test_capacity_matches_composition(evaluate_result):
    """Returned capacity matches the STD-5.1 seed data."""
    cap = evaluate_result["capacity"]
    assert cap["seats"]      == COMP_SEATS
    assert cap["couchettes"] == COMP_COUCHETTES
    assert cap["sleepers"]   == COMP_SLEEPERS


def test_revenue_calculation_correct(evaluate_result):
    """Revenue totals match the expected calculation from inputs."""
    rev = evaluate_result["revenue"]

    expected_seat      = COMP_SEATS      * VALID_REQUEST["utilization_seat"]      * VALID_REQUEST["avg_fare_seat"]
    expected_couchette = COMP_COUCHETTES * VALID_REQUEST["utilization_couchette"] * VALID_REQUEST["avg_fare_couchette"]
    expected_sleeper   = COMP_SLEEPERS   * VALID_REQUEST["utilization_sleeper"]   * VALID_REQUEST["avg_fare_sleeper"]

    assert rev["revenue_seat"]      == pytest.approx(expected_seat,      rel=1e-4)
    assert rev["revenue_couchette"] == pytest.approx(expected_couchette, rel=1e-4)
    assert rev["revenue_sleeper"]   == pytest.approx(expected_sleeper,   rel=1e-4)
    assert rev["total"]             == pytest.approx(
        expected_seat + expected_couchette + expected_sleeper, rel=1e-4
    )


def test_distance_is_positive(evaluate_result):
    """Route produced a positive distance."""
    assert evaluate_result["total_distance_km"] > 0


def test_driving_time_is_positive(evaluate_result):
    """Route produced a positive driving time."""
    assert evaluate_result["total_driving_time_h"] > 0


def test_total_time_gte_driving_time(evaluate_result):
    """Total time (including dwell) is >= driving time."""
    assert evaluate_result["total_time_h"] >= evaluate_result["total_driving_time_h"]


def test_annual_margin_consistent(evaluate_result):
    """Annual margin equals per-trip margin × operating days."""
    assert evaluate_result["annual_margin"] == pytest.approx(
        evaluate_result["margin"] * VALID_REQUEST["operating_days_year"], rel=1e-4
    )


def test_cost_total_is_positive(evaluate_result):
    """Total cost is positive."""
    assert evaluate_result["cost"]["total"] > 0


def test_operating_days_matches_request(evaluate_result):
    """Operating days in result matches the request."""
    assert evaluate_result["operating_days_year"] == VALID_REQUEST["operating_days_year"]


# ---------------------------------------------------------------------------
# Validation error cases
# ---------------------------------------------------------------------------

def test_evaluate_missing_stops_returns_400(api_base):
    """Missing stops field returns 400 validation error."""
    body = {**VALID_REQUEST}
    del body["stops"]
    resp = requests.post(f"{api_base}{API_EVALUATE}", json=body, timeout=10)
    assert resp.status_code == 400
    assert resp.json()["error"] == "validation_error"


def test_evaluate_single_stop_returns_400(api_base):
    """Only one stop returns 400 — minimum is two."""
    body = {**VALID_REQUEST, "stops": [{"stop_id": "DE_BERLIN_HBF", "stop_type": "boarding"}]}
    resp = requests.post(f"{api_base}{API_EVALUATE}", json=body, timeout=10)
    assert resp.status_code == 400
    assert resp.json()["error"] == "validation_error"


def test_evaluate_invalid_stop_type_returns_400(api_base):
    """Invalid stop_type value returns 400."""
    body = {**VALID_REQUEST, "stops": [
        {"stop_id": "DE_BERLIN_HBF", "stop_type": "INVALID"},
        {"stop_id": "AT_WIEN_HBF",   "stop_type": "alighting"},
    ]}
    resp = requests.post(f"{api_base}{API_EVALUATE}", json=body, timeout=10)
    assert resp.status_code == 400


def test_evaluate_utilization_out_of_range_returns_400(api_base):
    """Utilization > 1.0 returns 400."""
    body = {**VALID_REQUEST, "utilization_seat": 1.5}
    resp = requests.post(f"{api_base}{API_EVALUATE}", json=body, timeout=10)
    assert resp.status_code == 400


def test_evaluate_unknown_composition_returns_422(api_base):
    """Unknown composition_id returns 422 domain error."""
    body = {**VALID_REQUEST, "composition_id": "DOES-NOT-EXIST"}
    resp = requests.post(f"{api_base}{API_EVALUATE}", json=body, timeout=30)
    assert resp.status_code == 422
    assert resp.json()["error"] == "domain_error"


def test_evaluate_no_body_returns_400(api_base):
    """Empty body returns 400."""
    resp = requests.post(
        f"{api_base}{API_EVALUATE}",
        data="",
        headers={"Content-Type": "application/json"},
        timeout=10,
    )
    assert resp.status_code == 400
