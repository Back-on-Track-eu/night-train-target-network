"""
test_40_pipeline.py
===================
Thin end-to-end smoke test — one pass through the full two-step pipeline
(plan → cost) verifying the pieces plug into each other. Everything asserted
in depth elsewhere (route content: test_20/21, evaluation content:
test_30/31) is deliberately NOT repeated here.
"""

import pytest

from tests.helpers import all_trips, directional_od, evaluate, inject_demand, route_bd


@pytest.fixture(scope="module")
def pipeline_result(api_base, route_berlin_dresden_wien):
    """Plan (shared session route) → inject demand → evaluate."""
    route = route_berlin_dresden_wien
    ods = directional_od(route, "Couchette", 40, 89.0)
    return evaluate(api_base, inject_demand(route, ods))


def test_pipeline_completes_with_two_trips(route_berlin_dresden_wien):
    """The planned route carries one pair = two trips, ready for costing."""
    assert len(all_trips(route_berlin_dresden_wien)) == 2


def test_pipeline_produces_all_views(pipeline_result):
    """The evaluation of a freshly planned route carries all six views."""
    assert set(pipeline_result["views"]) == {
        "route",
        "per_trip_pair",
        "per_trip_pair_per_country",
        "per_trip_pair_per_od",
        "per_trip_pair_per_section",
        "per_trip_per_stop",
    }


def test_pipeline_revenue_and_cost_positive(pipeline_result):
    """With demand injected, both sides of the ledger are populated."""
    bd = route_bd(pipeline_result)
    assert bd["total_revenue_eur"] > 0
    assert bd["total_cost_eur"] > 0
