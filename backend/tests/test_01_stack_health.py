"""
test_01_stack_health.py
=======================
Verifies the Docker stack came up correctly — the very first thing to check
before any functional test can be meaningful.

Covers:
  - API liveness (GET /api/health)
  - DB loader initialisation (GET /api/data/status)
  - OpenRailRouting reachability (its own /health, on the host port)
  - Global error handling contract (JSON 404/405 bodies)
  - Phase 5 stub endpoints (auth) returning 501
"""

import os

import pytest
import requests

OPENRAILROUTING_PORT = os.environ.get("OPENRAILROUTING_HOST_PORT", "8989")


@pytest.mark.timeout(10)
def test_api_health(api_base):
    """GET /api/health returns 200 with {"status": "ok"} — API process is up."""
    resp = requests.get(f"{api_base}/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.timeout(10)
def test_data_status_loaded(api_base):
    """GET /api/data/status reports the DBDataLoader initialised successfully
    at startup (loaded=True, a loaded_at timestamp, no error)."""
    resp = requests.get(f"{api_base}/api/data/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["loaded"] is True
    assert "loaded_at" in body
    assert "error" not in body


@pytest.mark.timeout(10)
def test_openrailrouting_health():
    """OpenRailRouting's own health endpoint is reachable on the host port —
    routing requests from the API have somewhere to go."""
    resp = requests.get(f"http://localhost:{OPENRAILROUTING_PORT}/health")
    assert resp.status_code == 200


@pytest.mark.timeout(10)
def test_unknown_endpoint_returns_json_404(api_base):
    """Unknown paths return the global JSON 404 handler's body, not Flask's
    default HTML page (frontend relies on JSON error shapes everywhere)."""
    resp = requests.get(f"{api_base}/api/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["error"] == "not_found"


@pytest.mark.timeout(10)
def test_wrong_method_returns_json_405(api_base):
    """GET on a POST-only endpoint returns the global JSON 405 handler's body."""
    resp = requests.get(f"{api_base}/api/route/plan")
    assert resp.status_code == 405
    assert resp.json()["error"] == "method_not_allowed"


@pytest.mark.timeout(10)
def test_no_stub_endpoints_remain(api_base):
    """No endpoint returns 501 anymore — auth (the last Phase 5 stub) is a
    real implementation now, covered by test_70_auth_api.py. An empty
    body on the auth endpoints is a 400 validation error, not a 501; a
    501 reappearing here would mean a registered blueprint regressed to
    a stub without the suite noticing."""
    former_stubs = [
        ("POST", "/api/auth/request-code"),
        ("POST", "/api/auth/verify"),
    ]
    for method, path in former_stubs:
        resp = requests.request(method, f"{api_base}{path}", json={}, timeout=5)
        assert (
            resp.status_code == 400
        ), f"{method} {path} returned {resp.status_code}, expected 400 (empty body)"
