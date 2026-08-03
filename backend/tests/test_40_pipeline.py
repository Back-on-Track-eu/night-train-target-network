"""
test_40_pipeline.py
===================
Thin end-to-end smoke test — one pass through the full two-step pipeline
(plan -> cost) verifying the pieces plug into each other. Everything
asserted in depth elsewhere (route content: test_20, evaluation content:
test_30) is deliberately NOT repeated here.

The "cost" half runs at the model layer (tests/helpers.py:
compute_evaluation_domain()) — see test_30's module docstring for the
rationale. "Plan" goes through a live POST /api/proposal/calc
(route_berlin_dresden_wien, conftest.py), so this remains a genuine
plan-then-cost smoke test, just with the cost step's HTTP hop removed.
"""

import pytest

from tests.helpers import all_trips, compute_evaluation_domain, route_bd


@pytest.fixture(scope="module")
def pipeline_result(loader, route_berlin_dresden_wien):
    """Plan (shared session route) -> inject demand -> evaluate."""
    _, result = compute_evaluation_domain(
        route_berlin_dresden_wien, loader, demand=[("Couchette", 40, 89.0)]
    )
    return result


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
