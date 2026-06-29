"""
test_pipeline.py
================
Thin end-to-end smoke test — verifies the full two-step pipeline
(route → evaluate) completes successfully.

Detailed tests live in test_route.py, test_route_routing.py,
test_evaluate.py, and test_energy.py.
"""

import pytest
import requests

ROUTE_URL = "/api/route/planOrUpdate"
EVAL_URL = "/api/evaluation/calc"

STOPS = [
    {"stop_id": "DE_BERLIN_HBF", "stop_type": "boarding"},
    {"stop_id": "DE_DRESDEN_HBF", "stop_type": "both"},
    {"stop_id": "AT_WIEN_HBF", "stop_type": "alighting"},
]

DEMAND = {
    "od_pairs": [
        {
            "origin_stop_id": "DE_BERLIN_HBF",
            "destination_stop_id": "AT_WIEN_HBF",
            "class_main": "Couchette",
            "places_sold": 40,
            "avg_price": 89.0,
        },
        {
            "origin_stop_id": "DE_DRESDEN_HBF",
            "destination_stop_id": "AT_WIEN_HBF",
            "class_main": "Seat",
            "places_sold": 20,
            "avg_price": 49.0,
        },
    ]
}


@pytest.fixture(scope="module")
def route(api_base):
    resp = requests.post(
        f"{api_base}{ROUTE_URL}",
        json={
            "proposal_id": 1,
            "proposal_version": 1,
            "stops": STOPS,
            "composition_id": "STD-7.1",
            "departure_time": "21:00",
        },
        timeout=60,
    )
    assert resp.status_code == 200, f"Route failed: {resp.text[:300]}"
    return resp.json()["route"]


@pytest.fixture(scope="module")
def eval_result(api_base, route):
    trip_ids = [t["trip_id"] for t in route["trips"]]
    resp = requests.post(
        f"{api_base}{EVAL_URL}",
        json={
            "route": route,
            "route_demand": {tid: DEMAND for tid in trip_ids},
            "operating_days_year": 360,
        },
        timeout=30,
    )
    assert resp.status_code == 200, f"Eval failed: {resp.text[:300]}"
    return resp.json()["result"]


def test_pipeline_route_returns_200(api_base):
    resp = requests.post(
        f"{api_base}{ROUTE_URL}",
        json={
            "proposal_id": 1,
            "proposal_version": 1,
            "stops": STOPS,
            "composition_id": "STD-7.1",
            "departure_time": "21:00",
        },
        timeout=60,
    )
    assert resp.status_code == 200


def test_pipeline_eval_returns_200(api_base, route):
    trip_ids = [t["trip_id"] for t in route["trips"]]
    resp = requests.post(
        f"{api_base}{EVAL_URL}",
        json={
            "route": route,
            "route_demand": {tid: DEMAND for tid in trip_ids},
            "operating_days_year": 360,
        },
        timeout=30,
    )
    assert resp.status_code == 200


def test_pipeline_result_has_all_levels(eval_result):
    assert "summary" in eval_result
    assert "by_trip" in eval_result
    assert "by_country" in eval_result
    assert "by_od" in eval_result


def test_pipeline_result_has_metadata(eval_result):
    assert "calc_version" in eval_result
    assert "calc_formulas" in eval_result
    assert len(eval_result["calc_formulas"]) > 0


def test_pipeline_revenue_positive(eval_result):
    assert eval_result["summary"]["per_day"]["revenue"]["total"] > 0


def test_pipeline_cost_positive(eval_result):
    assert eval_result["summary"]["per_day"]["cost"]["total"] > 0


def test_pipeline_has_two_trips(eval_result):
    assert len(eval_result["by_trip"]) == 2


def test_pipeline_country_breakdown_infrastructure_only(eval_result):
    for cc, matrix in eval_result["by_country"].items():
        assert matrix["per_day"]["scope"] == "infrastructure_only"
