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

import pytest
import requests

from dev_env import resolve_routing_urls, routing_base_url


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
    resp = requests.get(f"{routing_base_url()}/health")
    assert resp.status_code == 200


@pytest.mark.timeout(10)
def test_dev_env_resolves_every_routing_graph(monkeypatch):
    """Host-run tools resolve EVERY configured graph, not just the default.

    backend/docker/.env holds container-network URLs; on the host each has
    to be rewritten to localhost on that graph's own published port. Doing
    this for the default graph alone is the regression to catch — a second
    graph (infra_2032) would then be reached at a compose service name
    that does not resolve outside the stack, and a tool routing on it
    would fail with a DNS error rather than an honest configuration one.
    """
    # .invalid is reserved and guaranteed never to resolve (RFC 2606), so
    # the rewrite branch is exercised deterministically — a plain made-up
    # hostname can be answered by a wildcard-resolving DNS server.
    monkeypatch.setenv(
        "OPENRAILROUTING_URL_INFRA_TEST", "http://openrailrouting-test.invalid:8989"
    )
    monkeypatch.setenv("OPENRAILROUTING_HOST_PORT_INFRA_TEST", "18989")

    resolved = resolve_routing_urls()

    assert resolved["infra_test"] == "http://localhost:18989"
    # The default graph is resolved in the same pass, never special-cased.
    # It is present because conftest.py calls db_config() at import time,
    # which publishes the default URL through resolve_env().
    assert "infra_2026" in resolved


@pytest.mark.timeout(10)
def test_unknown_endpoint_returns_json_404(api_base):
    """Unknown paths return the global JSON 404 handler's body, not Flask's
    default HTML page (frontend relies on JSON error shapes everywhere)."""
    resp = requests.get(f"{api_base}/api/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["error"] == "not_found"


@pytest.mark.timeout(10)
def test_wrong_method_returns_json_405(api_base):
    """GET on a POST-only endpoint returns the global JSON 405 handler's
    body. /api/route/plan was removed in WP5 — /api/proposal/calc is its
    POST-only successor."""
    resp = requests.get(f"{api_base}/api/proposal/calc")
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
        assert resp.status_code == 400, (
            f"{method} {path} returned {resp.status_code}, expected 400 (empty body)"
        )
