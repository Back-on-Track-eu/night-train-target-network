"""
dependencies.py
===============
Singleton state for the Flask API.

A DBDataLoader is created once at startup and held for the lifetime of the
process. All route handlers call get_loader() to access it.

Auth routes and other endpoints that need direct DB access call get_db()
which yields a psycopg2 RealDictCursor inside an auto-committed transaction.

State
-----
  _loader    : DBDataLoader instance (created at startup)
  _loaded    : bool — True after successful DB connection
  _loaded_at : datetime | None — UTC timestamp of startup
  _load_error: str | None — error message if startup failed
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Singleton state
# ---------------------------------------------------------------------------
_loader      = None
_loaded:     bool               = False
_loaded_at:  Optional[datetime] = None
_load_error: Optional[str]      = None


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

class DataNotLoadedError(Exception):
    """Raised when an endpoint needs the DB loader but it is not available."""
    pass


def init() -> None:
    """
    Initialise the DBDataLoader at startup.
    Called once from main.py before the Flask app starts serving requests.
    """
    global _loader, _loaded, _loaded_at, _load_error

    from adapters.data_loader_from_db import DBDataLoader

    logger.info("Connecting to database...")

    try:
        _loader     = DBDataLoader()
        _loaded     = True
        _loaded_at  = datetime.now(timezone.utc)
        _load_error = None
        logger.info("Database connection established at %s.", _loaded_at.isoformat())
    except Exception as e:
        _loaded     = False
        _load_error = str(e)
        logger.error("Database connection failed: %s", e)
        raise


def get_loader():
    """
    Return the singleton DBDataLoader.
    Raises DataNotLoadedError if init() has not completed successfully.
    """
    if not _loaded or _loader is None:
        raise DataNotLoadedError(
            "Database not available. Check the connection and restart the API."
        )
    return _loader


@contextmanager
def get_db():
    """
    Yield a psycopg2 RealDictCursor for direct DB access.

    Usage
    -----
        with get_db() as cur:
            cur.execute("SELECT ...")
            row = cur.fetchone()
        # connection is committed and closed automatically

    - Opens a fresh connection per call (auth operations are infrequent;
      a connection pool can be added later if needed).
    - Commits on clean exit, rolls back on exception.
    - Always closes the connection.
    - Raises psycopg2.Error on connection or query failure.
    """
    required = [
        "POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB",
        "POSTGRES_USER", "POSTGRES_PASSWORD",
    ]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise RuntimeError(
            f"Missing DB environment variable(s): {', '.join(missing)}. "
            f"Check your .env file."
        )

    conn = psycopg2.connect(
        host     = os.environ["POSTGRES_HOST"],
        port     = int(os.environ["POSTGRES_PORT"]),
        dbname   = os.environ["POSTGRES_DB"],
        user     = os.environ["POSTGRES_USER"],
        password = os.environ["POSTGRES_PASSWORD"],
    )
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()