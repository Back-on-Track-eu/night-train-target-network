"""
dependencies.py
===============
Singleton state for the Flask API.

A DBDataLoader is created once at startup and held for the lifetime of the
process. All route handlers call get_loader() to access it.

A CountryIndex (country border geometries, for routing/HSR-avoidance) is
built once at the same time — input_params.countries is static reference
data, not one of the scenario-versioned tables, so there's no need to
re-query it per request. Route handlers call get_country_index() to access
it.

A ProposalRepository (write path for saved proposals) and a
FeedbackRepository (write path for feedback submissions) are created
alongside them — each holds its own connection to the same database,
keeping DBDataLoader strictly read-only. Route handlers call
get_proposal_repository() / get_feedback_repository() to access them.

State
-----
  _loader        : DBDataLoader instance (created at startup)
  _country_index : CountryIndex instance (built at startup from the loader)
  _proposal_repo : ProposalRepository instance (created at startup)
  _feedback_repo : FeedbackRepository instance (created at startup)
  _loaded        : bool — True after successful DB connection
  _loaded_at     : datetime | None — UTC timestamp of startup
  _load_error    : str | None — error message if startup failed
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Singleton state
# ---------------------------------------------------------------------------
_loader = None
_country_index = None
_proposal_repo = None
_feedback_repo = None
_loaded: bool = False
_loaded_at: Optional[datetime] = None
_load_error: Optional[str] = None


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


class DataNotLoadedError(Exception):
    """Raised when an endpoint needs the DB loader but it is not available."""

    pass


def init() -> None:
    """
    Initialise the DBDataLoader and CountryIndex at startup.
    Called once from main.py before the Flask app starts serving requests.
    """
    global _loader, _country_index, _proposal_repo, _feedback_repo, _loaded, _loaded_at, _load_error

    from adapters.data_loader_from_db import DBDataLoader
    from adapters.proposal_repository import ProposalRepository
    from adapters.feedback_repository import FeedbackRepository
    from models.route.routing.rail_router import CountryIndex

    logger.info("Connecting to database...")

    try:
        _loader = DBDataLoader()
        _country_index = CountryIndex(_loader.get_country_geometries())
        _proposal_repo = ProposalRepository()
        _feedback_repo = FeedbackRepository()
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
    Return the singleton DBDataLoader.
    Raises DataNotLoadedError if init() has not completed successfully.
    """
    if not _loaded or _loader is None:
        raise DataNotLoadedError("Data not loaded. Call POST /api/data/load first.")
    return _loader


def get_country_index():
    """
    Return the singleton CountryIndex.
    Raises DataNotLoadedError if init() has not completed successfully.
    """
    if not _loaded or _country_index is None:
        raise DataNotLoadedError("Data not loaded. Call POST /api/data/load first.")
    return _country_index


def get_proposal_repository():
    """
    Return the singleton ProposalRepository.
    Raises DataNotLoadedError if init() has not completed successfully.
    """
    if not _loaded or _proposal_repo is None:
        raise DataNotLoadedError("Data not loaded. Call POST /api/data/load first.")
    return _proposal_repo


def get_feedback_repository():
    """
    Return the singleton FeedbackRepository.
    Raises DataNotLoadedError if init() has not completed successfully.
    """
    if not _loaded or _feedback_repo is None:
        raise DataNotLoadedError("Data not loaded. Call POST /api/data/load first.")
    return _feedback_repo
