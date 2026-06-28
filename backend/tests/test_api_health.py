"""
test_api_health.py
==================
Verifies the Docker stack is up, all services are healthy, and the
parameter endpoints return correct responses.

Tests:
  - API health endpoint returns 200
  - OpenRailRouting is reachable
  - Params endpoints respond correctly with new field structure
"""

import requests
import pytest
import os


OPENRAILROUTING_PORT = os.environ.get("OPENRAILROUTING_HOST_PORT", "8989")


@pytest.mark.timeout(10)
def test_api_health(api_base):
    """GET /api/health returns 200 and status ok."""
    resp = requests.get(f"{api_base}/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.timeout(10)
def test_openrailrouting_health():
    """OpenRailRouting health endpoint is reachable."""
    resp = requests.get(f"http://localhost:{OPENRAILROUTING_PORT}/health")
    assert resp.status_code == 200


@pytest.mark.timeout(10)
def test_params_stop_infrastructures_returns_200(api_base):
    """GET /api/params/StopInfrastructures returns 200."""
    resp = requests.get(f"{api_base}/api/params/StopInfrastructures")
    assert resp.status_code == 200


@pytest.mark.timeout(10)
def test_params_compositions_returns_200(api_base):
    """GET /api/params/compositions returns 200."""
    resp = requests.get(f"{api_base}/api/params/compositions")
    assert resp.status_code == 200


@pytest.mark.timeout(10)
def test_params_track_infrastructures_returns_200(api_base):
    """GET /api/params/TrackInfrastructures returns 200."""
    resp = requests.get(f"{api_base}/api/params/TrackInfrastructures")
    assert resp.status_code == 200


@pytest.mark.timeout(10)
def test_params_stops_has_required_fields(api_base):
    """Each stop has required fields."""
    resp = requests.get(f"{api_base}/api/params/StopInfrastructures")
    assert resp.status_code == 200
    required = {"stop_id", "name", "country_code", "lat", "lon", "stop_charge_eur"}
    for stop in resp.json()["stops"]:
        missing = required - set(stop.keys())
        assert missing == set(), f"Stop '{stop['stop_id']}' missing fields: {missing}"


@pytest.mark.timeout(10)
def test_params_stops_charge_is_field_object(api_base):
    """stop_charge_eur is a field object with value, is_default, version, description."""
    resp = requests.get(f"{api_base}/api/params/StopInfrastructures")
    assert resp.status_code == 200
    for stop in resp.json()["stops"]:
        charge = stop["stop_charge_eur"]
        assert isinstance(charge, dict), \
            f"stop '{stop['stop_id']}' stop_charge_eur is not a field object"
        assert "value" in charge
        assert "is_default" in charge
        assert isinstance(charge["is_default"], bool)


@pytest.mark.timeout(10)
def test_params_track_infra_fields_are_field_objects(api_base):
    """Track infrastructure fields are field objects with value and is_default."""
    resp = requests.get(f"{api_base}/api/params/TrackInfrastructures")
    assert resp.status_code == 200
    field_keys = {
        "tac_eur_train_km", "energy_price_eur_kwh", "parking_eur_day",
        "terrain_score", "hsr_allowed", "buffer_quota_per",
    }
    for track in resp.json()["track_infrastructures"]:
        for key in field_keys:
            assert isinstance(track[key], dict), \
                f"country '{track['country_code']}' field '{key}' is not a field object"
            assert "value"      in track[key]
            assert "is_default" in track[key]


@pytest.mark.timeout(10)
def test_params_compositions_has_capacity(api_base):
    """Each composition has a non-empty capacity dict."""
    resp = requests.get(f"{api_base}/api/params/compositions")
    assert resp.status_code == 200
    for comp in resp.json()["compositions"]:
        assert len(comp["capacity"]) > 0, \
            f"Composition '{comp['comp_id']}' has empty capacity"


@pytest.mark.timeout(10)
def test_params_compositions_indicative_figures(api_base):
    """Compositions with a reference row include indicative figures."""
    resp = requests.get(f"{api_base}/api/params/compositions")
    assert resp.status_code == 200
    comps_with_indicative = [
        c for c in resp.json()["compositions"] if c.get("indicative") is not None
    ]
    assert len(comps_with_indicative) >= 1, \
        "Expected at least one composition with indicative figures"
    for comp in comps_with_indicative:
        ind = comp["indicative"]
        assert "cost_eur_per_seat_km"   in ind
        assert "cost_eur_per_place_km"  in ind
        assert "subsidy_eur_per_pax_km" in ind
        assert "breakeven_load_factor"  in ind
        assert ind["cost_eur_per_seat_km"] > 0, \
            f"Composition '{comp['comp_id']}' indicative cost_eur_per_seat_km is zero"


@pytest.mark.timeout(10)
def test_stub_endpoints_return_501(api_base):
    """Feedback stub still returns 501."""
    resp = requests.request("POST", f"{api_base}/api/feedback", json={}, timeout=5)
    assert resp.status_code == 501, f"POST /api/feedback returned {resp.status_code}, expected 501"


@pytest.mark.timeout(10)
def test_scenario_endpoints_require_auth(api_base):
    """Scenario endpoints require auth — return 401 without token."""
    for method, path in [
        ("POST", "/api/scenario"),
        ("GET",  "/api/scenarios"),
        ("POST", "/api/scenarios"),
    ]:
        resp = requests.request(method, f"{api_base}{path}", json={}, timeout=5)
        assert resp.status_code == 401, \
            f"{method} {path} returned {resp.status_code}, expected 401"

@pytest.mark.timeout(10)
def test_auth_endpoints_no_longer_stub(api_base):
    """Auth endpoints are implemented — must not return 501."""
    for method, path in [
        ("POST", "/api/auth/request-code"),
        ("POST", "/api/auth/verify"),
        ("POST", "/api/auth/guest"),
    ]:
        resp = requests.request(method, f"{api_base}{path}", json={}, timeout=5)
        assert resp.status_code != 501, \
            f"{method} {path} still returning 501 — not yet implemented"

# ---------------------------------------------------------------------------
# Request logging tests
# ---------------------------------------------------------------------------

@pytest.mark.timeout(10)
def test_request_log_records_successful_request(api_base, db_cur, db_conn):
    """A successful GET /api/health produces a log row with status 200 and NULL request_body."""
    resp = requests.get(f"{api_base}/api/health")
    assert resp.status_code == 200

    db_conn.commit()  # start a fresh snapshot so the API's insert is visible
    db_cur.execute(
        """
        SELECT status_code, method, endpoint, duration_ms, request_body, error_log
        FROM admin.api_request_log
        WHERE endpoint = '/api/health'
        ORDER BY ts DESC
        LIMIT 1
        """
    )
    row = db_cur.fetchone()

    assert row is not None, "No log row found for GET /api/health"
    assert row["status_code"] == 200
    assert row["method"]      == "GET"
    assert row["endpoint"]    == "/api/health"
    assert row["duration_ms"] >= 0
    assert row["request_body"] is None
    assert row["error_log"]    is None


@pytest.mark.timeout(10)
def test_request_log_records_400_with_request_body(api_base, db_cur, db_conn):
    """A 400 validation error logs the full request body and NULL error_log."""
    bad_payload = {"stops": "not-a-list", "composition_id": 999}
    resp = requests.post(f"{api_base}/api/route/planOrUpdate", json=bad_payload)
    assert resp.status_code == 400

    db_conn.commit()  # start a fresh snapshot so the API's insert is visible
    db_cur.execute(
        """
        SELECT status_code, request_body, error_log
        FROM admin.api_request_log
        WHERE endpoint = '/api/route/planOrUpdate'
        ORDER BY ts DESC
        LIMIT 1
        """
    )
    row = db_cur.fetchone()

    assert row is not None, "No log row found for POST /api/route/planOrUpdate"
    assert row["status_code"]  == 400
    assert row["request_body"] is not None
    assert row["request_body"]["stops"] == "not-a-list"
    assert row["error_log"] is None


@pytest.mark.timeout(10)
def test_request_log_records_404(api_base, db_cur, db_conn):
    """A 404 on an unknown endpoint produces a log row with NULL request_body."""
    resp = requests.get(f"{api_base}/api/does-not-exist")
    assert resp.status_code == 404

    db_conn.commit()  # start a fresh snapshot so the API's insert is visible
    db_cur.execute(
        """
        SELECT status_code, request_body, error_log
        FROM admin.api_request_log
        WHERE endpoint = '/api/does-not-exist'
        ORDER BY ts DESC
        LIMIT 1
        """
    )
    row = db_cur.fetchone()

    assert row is not None, "No log row found for 404 request"
    assert row["status_code"]  == 404
    assert row["request_body"] is None
    assert row["error_log"]    is None