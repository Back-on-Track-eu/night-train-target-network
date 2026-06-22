"""
test_api_health.py
==================
Verifies the Docker stack is up, all services are healthy, and the
parameter endpoints return correct responses.

Tests:
  - API health endpoint returns 200
  - OpenRailRouting is reachable
  - Params endpoints respond correctly
"""

import requests
import pytest


@pytest.mark.timeout(10)
def test_api_health(api_base):
    """GET /api/health returns 200 and status ok."""
    resp = requests.get(f"{api_base}/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.timeout(10)
def test_openrailrouting_health():
    """OpenRailRouting health endpoint is reachable."""
    resp = requests.get("http://localhost:8989/health")
    assert resp.status_code == 200


@pytest.mark.timeout(10)
def test_params_stops_returns_200(api_base):
    """GET /api/params/stops returns 200."""
    resp = requests.get(f"{api_base}/api/params/stops")
    assert resp.status_code == 200


@pytest.mark.timeout(10)
def test_params_compositions_returns_200(api_base):
    """GET /api/params/compositions returns 200."""
    resp = requests.get(f"{api_base}/api/params/compositions")
    assert resp.status_code == 200


@pytest.mark.timeout(10)
def test_params_stops_no_charge_exposed(api_base):
    """stop_charge_eur must not be exposed — it is an internal cost model field."""
    resp = requests.get(f"{api_base}/api/params/stops")
    assert resp.status_code == 200
    for stop in resp.json()["stops"]:
        assert "stop_charge_eur" not in stop, \
            f"Stop '{stop['stop_id']}' exposes stop_charge_eur — should be internal"


@pytest.mark.timeout(10)
def test_params_compositions_has_classes(api_base):
    """Each composition has a non-empty classes list."""
    resp = requests.get(f"{api_base}/api/params/compositions")
    assert resp.status_code == 200
    for comp in resp.json()["compositions"]:
        assert len(comp["classes"]) > 0, \
            f"Composition '{comp['comp_id']}' has empty classes list"