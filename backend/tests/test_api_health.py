"""
test_api_health.py
==================
Verifies the Docker stack is up and the API is healthy.

Tests:
  - API health endpoint returns 200 and {"status": "ok"}
  - Database connection is established (data/status shows loaded=True)
  - OpenRailRouting health endpoint is reachable
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
def test_api_db_connection(api_base):
    """GET /api/data/status shows database connection established."""
    resp = requests.get(f"{api_base}/api/data/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["loaded"] is True, \
        f"Database not connected — error: {data.get('error')}"
    assert data["loaded_at"] is not None
    assert data["error"] is None


@pytest.mark.timeout(10)
def test_openrailrouting_health():
    """OpenRailRouting health endpoint is reachable."""
    resp = requests.get("http://localhost:8989/health")
    assert resp.status_code == 200
