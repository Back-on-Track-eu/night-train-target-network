"""
dependencies.py
===============
Singleton state for the Flask API.

A DBDataLoader is created once at startup and held for the lifetime of the
process. All route handlers call get_loader() to access it.

State
-----
  _loader       : DBDataLoader instance (created at startup)
  _loaded       : bool — True after successful DB connection
  _loaded_at    : datetime | None — UTC timestamp of startup
  _load_error   : str | None — error message if startup failed
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Singleton state
# ---------------------------------------------------------------------------
_loader = None  # SheetDataLoader, created lazily on first load()
_loaded: bool = False
_loaded_at: Optional[datetime] = None
_load_error: Optional[str] = None


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


class DataNotLoadedError(Exception):
    """Raised when an endpoint needs data that hasn't been loaded yet."""

    pass


def status() -> dict:
    """Return the current data loading status as a plain dict."""
    return {
        "loaded": _loaded,
        "loaded_at": _loaded_at.isoformat() if _loaded_at else None,
        "error": _load_error,
    }


def init() -> None:
    """
    Initialise the DBDataLoader at startup.
    Called once from main.py before the Flask app starts serving requests.
    """
    global _loader, _loaded, _loaded_at, _load_error

    from adapters.data_loader_from_db import DBDataLoader

    logger.info("Connecting to database...")

    try:
        _loader = DBDataLoader()
        _loaded = True
        _loaded_at = datetime.now(timezone.utc)
        _load_error = None
        logger.info("Database connection established at %s.", _loaded_at.isoformat())
    except Exception as e:
        _loaded = False
        _load_error = str(e)
        logger.error("Database connection failed: %s", e)
        raise


def get_loader():
    """
    Return the DBDataLoader.
    Raises DataNotLoadedError if init() has not completed successfully.
    """
    if not _loaded or _loader is None:
        raise DataNotLoadedError("Data not loaded. Call POST /api/data/load first.")
    return _loader
