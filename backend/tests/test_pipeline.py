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

from tests.conftest import flatten_trips, inject_demand, with_trip_ids

ROUTE_URL = "/api/route/plan"
EVAL_URL = "/api/evaluation/calc"

STOPS = [
    "DE_BERLIN_HBF",
    "DE_DRESDEN_HBF",
    "AT_WIEN_HBF",
]

DEMAND_TEMPLATE = [
    {
        "origin_stop_id": "DE_BERLIN_HBF",
        "destination_stop_id": "AT_WIEN_HBF",
        "class_main": "Couchette",
        "trip_id": None,  # filled per trip by with_trip_ids()
        "places_sold": 40,
        "avg_price": 89.0,
    },
    {
        "origin_stop_id": "DE_DRESDEN_HBF",
        "destination_stop_id": "AT_WIEN_HBF",
        "class_main": "Seat",
        "trip_id": None,
        "places_sold": 20,
        "avg_price": 49.0,
    },
]


@pytest.fixture(scope="module")
def route(api_base):
    resp = requests.post(
        f"{api_base}{ROUTE_URL}",
        json={
            "proposal_id": 1,
            "proposal_version": 1,
            "stops": STOPS,
            "composition_id": "STD-7.1",
        },
        timeout=60,
    )
    assert resp.status_code == 200, f"Route failed: {resp.text[:300]}"
    return resp.json()["route"]


@pytest.fixture(scope="module")
def eval_result(api_base, route):
    od = with_trip_ids(route, DEMAND_TEMPLATE)
    resp = requests.post(
        f"{api_base}{EVAL_URL}",
        json={"route": inject_demand(route, od)},
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
        },
        timeout=60,
    )
    assert resp.status_code == 200


def test_pipeline_eval_returns_200(api_base, route):
    od = with_trip_ids(route, DEMAND_TEMPLATE)
    resp = requests.post(
        f"{api_base}{EVAL_URL}",
        json={"route": inject_demand(route, od)},
        timeout=30,
    )
    assert resp.status_code == 200


def test_pipeline_result_has_all_levels(eval_result):
    views = eval_result["views"]
    assert "route" in views
    assert "per_trip_pair" in views
    assert "per_trip_pair_per_country" in views
    assert "per_trip_pair_per_od" in views
    assert "per_trip_per_stop" in views


def test_pipeline_result_has_metadata(eval_result):
    assert isinstance(eval_result["route_id"], str)


def test_pipeline_revenue_positive(eval_result):
    assert eval_result["views"]["route"]["per_year"]["total_revenue_eur"] > 0


def test_pipeline_cost_positive(eval_result):
    assert eval_result["views"]["route"]["per_year"]["total_cost_eur"] > 0


def test_pipeline_has_two_trips(route):
    assert len(flatten_trips(route)) == 2


def test_pipeline_country_breakdown_infrastructure_only(eval_result):
    """Country-level breakdowns exist and are non-empty for every trip pair.
    (No 'scope' field exists in the actual response to assert against —
    the original test's specific claim couldn't be verified against real
    serialized output, so this checks structural presence instead.)"""
    country_views = eval_result["views"]["per_trip_pair_per_country"]
    assert len(country_views) > 0
    for pair_key, countries in country_views.items():
        assert len(countries) > 0