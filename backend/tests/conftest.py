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


@pytest.fixture(autouse=True)
def rollback_after_test(db_conn):
    """Roll back any aborted transaction after each test to prevent cascade failures."""
    yield
    try:
        db_conn.rollback()
    except Exception:
        pass
