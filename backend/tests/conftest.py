"""
conftest.py
===========
Shared pytest fixtures for integration tests.

All tests in this suite are integration tests — they require the full
Docker stack to be running (postgres + openrailrouting + api).

Start the stack before running:
    cd backend/docker && docker-compose up -d

Run tests from backend/:
    uv run --group dev pytest tests/ -v
"""

import os
import pytest
import psycopg2
import psycopg2.extras

# ---------------------------------------------------------------------------
# Configuration — read from environment with sensible local defaults
# ---------------------------------------------------------------------------

API_BASE = os.environ.get("API_BASE_URL", "http://localhost:5000")

DB_CONFIG = {
    "host": os.environ.get("POSTGRES_HOST", "localhost"),
    "port": int(os.environ.get("POSTGRES_PORT", "5432")),
    "dbname": os.environ.get("POSTGRES_DB", "target_network_test_db"),
    "user": os.environ.get("POSTGRES_USER", "bot_admin"),
    "password": os.environ.get("POSTGRES_PASSWORD", "devpassword"),
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def api_base():
    """Base URL for the Flask API."""
    return API_BASE


@pytest.fixture(scope="session")
def db_conn():
    """
    Session-scoped PostgreSQL connection.
    Closed automatically after all tests complete.
    """
    conn = psycopg2.connect(**DB_CONFIG)
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def db_cur(db_conn):
    """Session-scoped RealDict cursor for convenient row access."""
    cur = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    yield cur
    cur.close()


@pytest.fixture(scope="session")
def loader():
    """
    Session-scoped DBDataLoader.
    Credentials are set as environment variables before construction so the
    loader picks them up — same pattern as when running inside Docker,
    but using the local defaults from DB_CONFIG.
    """
    # Set env vars from DB_CONFIG so DBDataLoader._connect() finds them
    os.environ.setdefault("POSTGRES_HOST", DB_CONFIG["host"])
    os.environ.setdefault("POSTGRES_PORT", str(DB_CONFIG["port"]))
    os.environ.setdefault("POSTGRES_DB", DB_CONFIG["dbname"])
    os.environ.setdefault("POSTGRES_USER", DB_CONFIG["user"])
    os.environ.setdefault("POSTGRES_PASSWORD", DB_CONFIG["password"])

    from adapters.data_loader_from_db import DBDataLoader

    _loader = DBDataLoader()
    yield _loader
    _loader.close()


@pytest.fixture(scope="session")
def base_scenario(db_cur):
    """
    The live is_current_base scenario row — gives tests the concrete
    per-table version numbers to filter on now that the eight versioned
    input_params tables carry no is_current flag of their own (see
    scenario.scenarios in create_scenario_schema.sql).
    """
    db_cur.execute("SELECT * FROM scenario.scenarios WHERE is_current_base = TRUE")
    row = db_cur.fetchone()
    assert row is not None, "No scenario has is_current_base = TRUE — seed data missing."
    return row


@pytest.fixture(autouse=True)
def rollback_after_test(db_conn):
    """Roll back any aborted transaction after each test to prevent cascade failures."""
    yield
    try:
        db_conn.rollback()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Trip-pairs → flat trips helper
# ---------------------------------------------------------------------------
# route_to_dict() (see api/helpers/serialize.py) exposes trip_pairs, not a
# flat "trips" list — each trip in outbound/return_trip only carries
# {trip_id, direction, segments}. This helper flattens trip_pairs and
# derives everything that IS reconstructible from segments data (stop
# times, dwell, per-country legs, distance/time/energy stats) so tests can
# still assert on those properties without the API needing to duplicate
# data it already exposes elsewhere. It does NOT fabricate data that has no
# source in the route JSON at all — model_versions, param_versions, and a
# full Composition object are not serialized into route JSON anywhere
# today (RouteProvenance travels separately from the Route); tests needing
# those are skipped with an explicit reason rather than faked here.


def _stop_times_from_trip(trip: dict) -> list[dict]:
    """Reconstruct an ordered stop_times-like list from a trip's segments."""
    segments = trip.get("segments", [])
    if not segments:
        return []
    stops = [segments[0]["from_stop"]] + [seg["to_stop"] for seg in segments]
    result = []
    for s in stops:
        arr = s.get("arrival_time_min")
        dep = s.get("departure_time_min")
        dwell = (dep - arr) if (arr is not None and dep is not None) else None
        result.append({**s, "dwell_time_min": dwell})
    return result


def _country_legs_from_segment(seg: dict) -> list[dict]:
    """
    Approximate per-country legs from a segment's distance/time shares.
    seg carries one energy_kwh for the whole segment (not split by country
    in the JSON) — split it proportionally by distance share for test
    purposes. This is an approximation of allocation, not a claim about how
    energy was originally computed per country.
    """
    legs = []
    for cc, dist_share in seg.get("country_distance_shares", {}).items():
        time_share = seg.get("country_time_shares", {}).get(cc, dist_share)
        leg_distance_m = seg["distance_m"] * dist_share
        leg_energy_kwh = seg["energy_kwh"] * dist_share
        leg_distance_km = leg_distance_m / 1000
        legs.append({
            "country_code": cc,
            "distance_m": leg_distance_m,
            "driving_time_min": seg["driving_time_min"] * time_share,
            "energy_kwh": leg_energy_kwh,
            "energy_kwh_per_km": (
                leg_energy_kwh / leg_distance_km if leg_distance_km > 0 else 0.0
            ),
        })
    return legs


def _trip_stats(trip: dict) -> dict:
    segments = trip.get("segments", [])
    total_distance_m = sum(s["distance_m"] for s in segments)
    total_driving_time_min = sum(s["driving_time_min"] for s in segments)
    total_energy_kwh = sum(s["energy_kwh"] for s in segments)
    stop_times = _stop_times_from_trip(trip)
    first_dep = stop_times[0]["departure_time_min"] if stop_times else None
    last_time = None
    if stop_times:
        last = stop_times[-1]
        last_time = (
            last["arrival_time_min"]
            if last["arrival_time_min"] is not None
            else last["departure_time_min"]
        )
    total_time_min = (
        (last_time - first_dep)
        if (first_dep is not None and last_time is not None)
        else total_driving_time_min
    )
    return {
        "total_distance_m": total_distance_m,
        "total_driving_time_min": total_driving_time_min,
        "total_time_min": total_time_min,
        "total_energy_kwh": total_energy_kwh,
    }


def inject_demand(route: dict, od_pairs: list[dict]) -> dict:
    """
    Embed od_pairs into every trip_pair in a route dict. Demand travels
    into evaluation/calc entirely inside the route JSON — od_pairs
    (with an explicit trip_id per entry) is the only mechanism; there is
    no separate route_demand/operating_days_year request field.
    Mirrors the proven-working pattern in test_evaluate.py.
    """
    route = dict(route)
    route["trip_pairs"] = [
        {**tp, "od_pairs": od_pairs} for tp in route["trip_pairs"]
    ]
    return route


def with_trip_ids(route: dict, od_template: list[dict]) -> list[dict]:
    """Fill trip_id in OD pair templates for every trip (outbound + return,
    all trip pairs) in a route dict."""
    ods = []
    for tp in route["trip_pairs"]:
        for trip in (tp["outbound"], tp["return_trip"]):
            trip_id = trip["trip_id"]
            for od in od_template:
                ods.append({**od, "trip_id": trip_id})
    return ods


def flatten_trips(route: dict) -> list[dict]:
    """
    Flatten route['trip_pairs'] into a list of trip dicts enriched with
    direction_id, departure_time_min, stop_times, stats, and
    path.segments[].country_legs — all derived from the segments data
    actually present in route_to_dict() output. See module docstring above
    for what this deliberately does NOT fabricate.
    """
    trips = []
    for pair in route["trip_pairs"]:
        for direction_trip in (pair["outbound"], pair["return_trip"]):
            stop_times = _stop_times_from_trip(direction_trip)
            trips.append({
                **direction_trip,
                "direction_id": direction_trip["direction"],
                "departure_time_min": (
                    stop_times[0]["departure_time_min"] if stop_times else None
                ),
                "stop_times": stop_times,
                "stats": _trip_stats(direction_trip),
                "path": {
                    "segments": [
                        {**seg, "country_legs": _country_legs_from_segment(seg)}
                        for seg in direction_trip.get("segments", [])
                    ]
                },
                "composition_id": pair["composition_id"],
            })
    return trips