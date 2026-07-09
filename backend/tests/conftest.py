"""
conftest.py
===========
Shared pytest fixtures. All tests are integration tests — they require the
full Docker stack (postgres + openrailrouting + api) to be running.

Start the stack before running:
    cd backend/docker && docker-compose up -d

Run tests from backend/:
    uv run --extra dev pytest tests/ -v

Expensive route builds (a POST /api/route/plan can take tens of seconds
against live OpenRailRouting) are session-scoped here and shared across
files — a test that only reads a route must use one of these fixtures
instead of building its own.
"""

import os

import psycopg2
import psycopg2.extras
import pytest
import requests

from tests.helpers import (
    ROUTE_URL,
    build_route,
    directional_od,
    evaluate,
    inject_demand,
)

# =============================================================================
# Configuration — from environment, with local-stack defaults
# =============================================================================

API_BASE = os.environ.get("API_BASE_URL", "http://localhost:5000")

DB_CONFIG = {
    "host": os.environ.get("POSTGRES_HOST", "localhost"),
    "port": int(os.environ.get("POSTGRES_PORT", "5432")),
    "dbname": os.environ.get("POSTGRES_DB", "target_network_test_db"),
    "user": os.environ.get("POSTGRES_USER", "bot_admin"),
    "password": os.environ.get("POSTGRES_PASSWORD", "devpassword"),
}

# Canonical stop lists — every seeded stop the suite routes between.
STOPS_BERLIN_WIEN = ["DE_BERLIN_HBF", "AT_WIEN_HBF"]
STOPS_BERLIN_DRESDEN_WIEN = ["DE_BERLIN_HBF", "DE_DRESDEN_HBF", "AT_WIEN_HBF"]
STOPS_BERLIN_ZUERICH_WIEN = ["DE_BERLIN_HBF", "CH_ZUERICH_HB", "AT_WIEN_HBF"]
STOPS_COPENHAGEN_STOCKHOLM = ["DK_COPENHAGEN", "SE_STOCKHOLM_C"]

DEFAULT_COMPOSITION = "STD-7.1"


# =============================================================================
# Infrastructure fixtures — API base, DB connection, loader, scenarios
# =============================================================================


@pytest.fixture(scope="session")
def api_base():
    """Base URL for the Flask API."""
    return API_BASE


# Set by db_conn while a session connection is live — lets the autouse
# rollback fixture stay a no-op for tests that never touch the DB (e.g. the
# static schema checks in test_03), instead of forcing a connection.
_active_conn = None


@pytest.fixture(scope="session")
def db_conn():
    """Session-scoped PostgreSQL connection, closed after all tests."""
    global _active_conn
    conn = psycopg2.connect(**DB_CONFIG)
    _active_conn = conn
    yield conn
    _active_conn = None
    conn.close()


@pytest.fixture(scope="session")
def db_cur(db_conn):
    """Session-scoped RealDict cursor for convenient row access."""
    cur = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    yield cur
    cur.close()


@pytest.fixture(autouse=True)
def rollback_after_test():
    """Roll back any aborted transaction after each test so one failing SQL
    statement can't cascade 'current transaction is aborted' into later
    tests. No-op if no DB connection has been opened."""
    yield
    if _active_conn is not None:
        try:
            _active_conn.rollback()
        except Exception:
            pass


@pytest.fixture(scope="session")
def loader():
    """Session-scoped DBDataLoader — same construction path as inside Docker,
    with credentials supplied via environment variables."""
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
    """The live is_current_base scenario row — supplies the pinned per-table
    version numbers tests filter on for the four scenario-versioned tables."""
    db_cur.execute("SELECT * FROM scenario.scenarios WHERE is_current_base = TRUE")
    row = db_cur.fetchone()
    assert (
        row is not None
    ), "No scenario has is_current_base = TRUE — seed data missing."
    return row


@pytest.fixture(scope="session")
def whatif_scenario(db_cur):
    """The seeded what-if scenario (scenario_key='whatif-de-track-infra') —
    pins track_infrastructures to version 1 (DE's original lower rates),
    everything else copied from base. Enables scenario override tests."""
    db_cur.execute(
        "SELECT * FROM scenario.scenarios "
        "WHERE scenario_key = 'whatif-de-track-infra' AND is_current_scenario = TRUE"
    )
    row = db_cur.fetchone()
    assert (
        row is not None
    ), "What-if scenario missing — see db/dev/seed.py: WHATIF_SCENARIO."
    return row


# =============================================================================
# Shared route fixtures — built once per session, read-only for tests
# =============================================================================


# proposal_id range convention (avoids collisions between real saved data
# and test fixtures across the whole suite):
#   1-99     seed_example_proposal() in db/dev/seed.py (currently just id=1)
#   100-999  draft placeholders for THIS file's session-scoped route fixtures
#   1000+    tests/test_50_proposals_api.py's own dynamically-saved proposals
@pytest.fixture(scope="session")
def route_berlin_wien(api_base):
    """2-stop, 2-country route: Berlin → Wien (DE, AT), STD-7.1."""
    return build_route(
        api_base,
        STOPS_BERLIN_WIEN,
        DEFAULT_COMPOSITION,
        proposal_id=101,
        proposal_version=1,
    )


@pytest.fixture(scope="session")
def route_berlin_dresden_wien(api_base):
    """3-stop route with one intermediate stop: Berlin → Dresden → Wien."""
    return build_route(
        api_base,
        STOPS_BERLIN_DRESDEN_WIEN,
        DEFAULT_COMPOSITION,
        proposal_id=102,
        proposal_version=1,
    )


@pytest.fixture(scope="session")
def route_berlin_zuerich_wien(api_base):
    """3-country route via Zürich: DE → CH → AT (plus transit countries)."""
    return build_route(
        api_base,
        STOPS_BERLIN_ZUERICH_WIEN,
        DEFAULT_COMPOSITION,
        proposal_id=103,
        proposal_version=1,
    )


@pytest.fixture(scope="session")
def route_copenhagen_stockholm(api_base):
    """Route touching SE, whose seed row has NULL tac/parking — exercises
    EU-average default resolution end to end.

    This crosses the Nordic network. If the deployed OpenRailRouting graph
    doesn't cover it, the build fails and the two route-level SE tests skip
    rather than error — SE default resolution is still covered at the loader,
    params-API, and evaluation levels (test_03/04/10/31). If you expect this
    route to build, check the API/OpenRailRouting container logs: the endpoint
    returning 500 (rather than a clean 'no route') on an unroutable pair is
    itself worth investigating."""
    body = {
        "stops": STOPS_COPENHAGEN_STOCKHOLM,
        "composition_id": DEFAULT_COMPOSITION,
        "proposal_id": 104,
        "proposal_version": 1,
    }
    resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=90)
    if resp.status_code != 200:
        pytest.skip(
            "Copenhagen→Stockholm did not build "
            f"(HTTP {resp.status_code}: {resp.text[:150]}) — likely the routing "
            "graph doesn't cover the Nordic network on this stack. SE default "
            "resolution is still tested at loader/params/eval level."
        )
    return resp.json()["route"]


# =============================================================================
# Shared evaluation fixture — the standard costed route most tests read
# =============================================================================

# Directional full-route demand on the 3-stop route: 40 Couchette + 30 Seat
# per trip, oriented in each trip's own travel direction so sold place-km is
# well-defined for every trip. places_sold is ANNUAL (see ODPair docs).
STANDARD_DEMAND = [("Couchette", 40, 89.0), ("Seat", 30, 49.0)]


@pytest.fixture(scope="session")
def eval_standard(api_base, route_berlin_dresden_wien):
    """Evaluation of route_berlin_dresden_wien under STANDARD_DEMAND.
    Returns (costed_route_dict_as_posted, evaluation_response)."""
    route = route_berlin_dresden_wien
    ods = []
    for class_main, places, price in STANDARD_DEMAND:
        ods += directional_od(route, class_main, places, price)
    costed = inject_demand(route, ods)
    return costed, evaluate(api_base, costed)