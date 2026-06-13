"""
dependencies.py
===============
Singleton state for the Flask API.

The SheetDataLoader is created once at import time but NOT loaded.
Data is loaded on demand via POST /api/data/load (or /reload).

All route handlers call require_data() which raises DataNotLoadedError
if load() has not been called successfully yet.

State
-----
  _loader       : SheetDataLoader instance (always exists)
  _loaded       : bool — True after a successful load_all()
  _loaded_at    : datetime | None — UTC timestamp of last successful load
  _load_error   : str | None — error message from last failed load attempt
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config path — resolved relative to this file's location so it works
# regardless of the working directory the app is started from.
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(
    _HERE, "..", "models", "route_evaluation_model", "model_config.yml"
)

# ---------------------------------------------------------------------------
# Singleton state
# ---------------------------------------------------------------------------
_loader = None          # SheetDataLoader, created lazily on first load()
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
        "loaded":     _loaded,
        "loaded_at":  _loaded_at.isoformat() if _loaded_at else None,
        "error":      _load_error,
    }


def load() -> dict:
    """
    Load (or reload) all parameter sheets from Google Sheets.

    Blocking call — returns when loading is complete or raises on error.
    Updates module-level state in place.

    Returns the status dict.
    """
    global _loader, _loaded, _loaded_at, _load_error

    from models.route_evaluation_model.data_loader_from_spreadsheet import SheetDataLoader

    logger.info("Loading data from Google Sheets...")

    try:
        _loader = SheetDataLoader(_CONFIG_PATH)
        _loader.load_all()
        _loaded = True
        _loaded_at = datetime.now(timezone.utc)
        _load_error = None
        logger.info("Data loaded successfully at %s.", _loaded_at.isoformat())
    except Exception as e:
        _loaded = False
        _load_error = str(e)
        logger.error("Data load failed: %s", e)
        raise

    return status()


def require_data():
    """
    Return the SheetDataLoader if data is loaded.
    Raises DataNotLoadedError otherwise — caught by the error handler in app.py.
    """
    if not _loaded or _loader is None:
        raise DataNotLoadedError(
            "Data not loaded. Call POST /api/data/load first."
        )
    return _loader