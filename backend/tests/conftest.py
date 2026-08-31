"""
conftest.py
===========
Shared pytest fixtures. All tests are integration tests — they require the
full Docker stack (postgres + openrailrouting-infra-2026 + api) to be running.

Start the stack before running:
    cd backend/docker && docker-compose up -d

Run tests from backend/:
    uv run --extra dev pytest tests/ -v

Expensive route builds (a POST /api/proposal/calc can take tens of seconds
against live OpenRailRouting) are session-scoped here and shared across
files — a test that only reads a route must use one of these fixtures
instead of building its own.
"""

import os

import psycopg2
import psycopg2.extras
import pytest
import requests

from dev_env import api_base_url, db_config
from tests.helpers import (
    PROPOSAL_CALC_URL,
    build_route,
    compute_evaluation_domain,
    purge_saved_proposals,
)

# =============================================================================
# Configuration — from environment, with local-stack defaults
# =============================================================================

# Resolved by backend/dev_env.py — the single home for dev-side connection
# defaults. Reads backend/docker/.env; real environment variables (CI) win.
API_BASE = api_base_url()

DB_CONFIG = db_config()

# Canonical stop lists — every seeded stop the suite routes between.
STOPS_BERLIN_WIEN = ["osm:n3856100103", "osm:w423692233"]
STOPS_BERLIN_DRESDEN_WIEN = ["osm:n3856100103", "osm:n25397500", "osm:w423692233"]
STOPS_BERLIN_ZUERICH_WIEN = ["osm:n3856100103", "osm:n1236383343", "osm:w423692233"]
STOPS_COPENHAGEN_STOCKHOLM = ["osm:n3739700410", "osm:n25948183"]

# Two calibrated test compositions — one per material strategy, so the
# suite exercises both mechanics end to end: STD-NEW operator (loco 174,
# 30y/0.909 amortisation/availability, maint 1.00×n, hsr_allowed) vs
# STD-REF (161, 12y/0.80, 1.30×n, no HSR, v_max 200).
DEFAULT_COMPOSITION = "NEW-BAL-7"
REF_COMPOSITION = "REF-BUD-6"


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


# =============================================================================
# Script identity — the user the suite publishes as
# =============================================================================
#
# The suite authenticates as the seeded 'test_script' user so published
# rows from test runs are identifiable (and purgeable) by owner. The
# session route fixtures below are TOKENLESS: POST /api/proposal/calc is
# stateless and leaves no rows — persistence is exercised solely by the
# dedicated publish tests (test_50, test_70).


@pytest.fixture(scope="session")
def script_user_id(db_cur, db_conn):
    """user_id of the seeded 'test_script' identity — resolved by email,
    never hard-coded (mirrors test_50's old user_ids pattern)."""
    db_cur.execute(
        "SELECT user_id FROM admin.users WHERE email = 'test_script@dev.local'"
    )
    row = db_cur.fetchone()
    assert row is not None, (
        "Seed user test_script missing — reseed the DB (db/dev/seed.py)."
    )
    db_conn.rollback()
    return row["user_id"]


@pytest.fixture(scope="session")
def script_headers(api_base, db_cur, db_conn, script_user_id):
    """Authorization header for 'test_script', with a real JWT obtained from
    the live API: an OTP is injected DB-side (the API correctly never
    returns codes — same pattern as test_70's user_with_known_otp) and
    exchanged via POST /api/auth/verify. No JWT_SECRET needed on the host.

    Session teardown purges every proposal the suite persisted (the seeded
    example proposal excepted) so dev-DB growth stays bounded — the last
    run's rows exist for inspection only until the next run starts."""
    from api.auth_utils import hash_otp

    otp = "424242"
    db_cur.execute(
        "INSERT INTO admin.auth_tokens (user_id, code_hash, expires_at) "
        "VALUES (%s, %s, NOW() + INTERVAL '15 minutes')",
        (script_user_id, hash_otp(otp)),
    )
    db_conn.commit()

    resp = requests.post(
        f"{API_BASE}/api/auth/verify",
        json={"email": "test_script@dev.local", "code": otp},
        timeout=10,
    )
    assert resp.status_code == 200, f"test_script login failed: {resp.text[:200]}"

    yield {"Authorization": f"Bearer {resp.json()['token']}"}

    purge_saved_proposals(db_conn)


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
    assert row is not None, (
        "No scenario has is_current_base = TRUE — seed data missing."
    )
    return row


@pytest.fixture(scope="session")
def historical_scenario(db_cur):
    """The superseded revision of the infra-2026 lineage (scenario_key=
    'infra-2026', is_current_scenario=FALSE) — pins every table to version
    4, carrying Germany's pre-correction track access rates. The only
    seeded snapshot whose TARIFFS differ from the base, so it is what the
    scenario-override tests pin to; the HSR and optimised-timetable
    scenarios differ in routing and timetabling, not in charges."""
    db_cur.execute(
        "SELECT * FROM scenario.scenarios "
        "WHERE scenario_key = 'infra-2026' AND is_current_scenario = FALSE"
    )
    row = db_cur.fetchone()
    assert row is not None, (
        "Superseded infra-2026 revision missing — see db/dev/seed.py: "
        "SUPERSEDED_BASE_REVISION."
    )
    return row


@pytest.fixture(scope="session")
def hsr_scenario(db_cur):
    """The seeded 'NT on HSR' scenario (scenario_key='infra-2026-hsr') —
    a second current lineage head (is_current_scenario=TRUE,
    is_current_base=FALSE), identical to the live base except
    track_hsr_allowed=True everywhere. Enables tests of the non-base
    'current_scenarios' API group and of pinning to a live-but-non-default
    scenario_id."""
    db_cur.execute(
        "SELECT * FROM scenario.scenarios "
        "WHERE scenario_key = 'infra-2026-hsr' AND is_current_scenario = TRUE"
    )
    row = db_cur.fetchone()
    assert row is not None, (
        "NT-on-HSR scenario missing — see db/dev/seed.py: HSR_SCENARIO."
    )
    return row


@pytest.fixture(scope="session")
def opt_tt_scenario(db_cur):
    """The seeded optimised-timetable scenario (scenario_key=
    'infra-2026-hsr-opt-tt') — the third current lineage head, identical
    to hsr_scenario except for a reduced track_buffer_quota_per. The only
    seeded scenario carrying a numeric value difference from the base, so
    it is what cross-version resolution tests pin to (see
    models/scenarios/README.md for the reduction itself)."""
    db_cur.execute(
        "SELECT * FROM scenario.scenarios "
        "WHERE scenario_key = 'infra-2026-hsr-opt-tt' AND is_current_scenario = TRUE"
    )
    row = db_cur.fetchone()
    assert row is not None, (
        "Optimised-timetable scenario missing — see db/dev/seed.py: OPT_TT_SCENARIO."
    )
    return row


# =============================================================================
# Shared route fixtures — built once per session, read-only for tests
# =============================================================================


# All fixtures pin auto_stop_addition="off": these are fixed-corridor
# physics fixtures whose stop lists downstream tests (test_20 content
# math, test_50 GTFS decomposition) rely on being exactly as requested —
# the seeded osm:n3325029085 would otherwise be auto-added to any corridor
# passing through Brno. The add/suggest behaviour has its own dedicated
# tests in test_35's TestSuggestMode / TestModeSwitches-equivalent classes.
#
# WP5: these are now built via POST /api/proposal/calc (stateless,
# neutral structural ids) — proposal_id/proposal_version no longer exist
# as request fields (those are publish-only concerns, §2.1), so the old
# draft-placeholder-id range convention that used to live here is gone.
@pytest.fixture(scope="session")
def route_berlin_wien(api_base):
    """2-stop, 2-country route: Berlin → Wien (DE, AT), NEW-BAL-7."""
    return build_route(
        api_base,
        STOPS_BERLIN_WIEN,
        DEFAULT_COMPOSITION,
        auto_stop_addition="off",
    )


@pytest.fixture(scope="session")
def route_berlin_dresden_wien(api_base):
    """3-stop route with one intermediate stop: Berlin → Dresden → Wien."""
    return build_route(
        api_base,
        STOPS_BERLIN_DRESDEN_WIEN,
        DEFAULT_COMPOSITION,
        auto_stop_addition="off",
    )


@pytest.fixture(scope="session")
def route_berlin_zuerich_wien(api_base):
    """3-country route via Zürich: DE → CH → AT (plus transit countries)."""
    return build_route(
        api_base,
        STOPS_BERLIN_ZUERICH_WIEN,
        DEFAULT_COMPOSITION,
        auto_stop_addition="off",
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
        "auto_stop_addition": "off",
    }
    resp = requests.post(f"{api_base}{PROPOSAL_CALC_URL}", json=body, timeout=90)
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
def eval_standard(loader, route_berlin_dresden_wien):
    """Evaluation of route_berlin_dresden_wien under STANDARD_DEMAND.
    Returns (costed_route_dict, evaluation_response), computed at the
    model layer — see tests/helpers.py:compute_evaluation_domain()."""
    return compute_evaluation_domain(
        route_berlin_dresden_wien, loader, demand=STANDARD_DEMAND
    )
