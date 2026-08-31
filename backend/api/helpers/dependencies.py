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
it. On top of it, one RailRouter PER CONFIGURED ROUTING GRAPH is built,
also once: each holds a requests.Session with a warm connection pool sized
for concurrent routing calls (see rail_router.py), and Session is safe for
concurrent use — a per-request RailRouter would start every compute on a
cold pool for no gain. Handlers call get_rail_router(graph_key), where
graph_key is a scenario's routing_graph_key pin (scenario.scenarios; None
→ the default graph).

Routing graph registry
----------------------
The key → URL mapping is deployment configuration, not database content.
Every graph is configured the same way — one OPENRAILROUTING_URL_<KEY>
variable, the key uppercased: OPENRAILROUTING_URL_INFRA_2026 serves key
"infra_2026", OPENRAILROUTING_URL_INFRA_2032 serves "infra_2032". The
default graph is not special-cased; it is simply the key a scenario gets
when it pins nothing. Empty values are skipped, so backend/docker/.env
can keep a variable present-but-blank while its instance is off.

The unsuffixed OPENRAILROUTING_URL is honoured for the default graph
only, as a compatibility path for the server stacks under deploy/ which
set it and know nothing about graph keys (rail_router.default_base_url).

A scenario pinning a key with no configured URL fails loudly at compute
time (RoutingGraphNotConfiguredError) — never a silent fallback to the
wrong graph, which would produce plausible routes and corrupt everything
downstream. All graphs share config.yml/custom_models, so the gauge
profile names are identical on every instance.

A ProposalRepository (write path for saved proposals), a
FeedbackRepository (write path for feedback submissions), a
ProposalEngagementRepository (write path for proposal likes/comments),
and a ComputeCacheRepository (the §2.3 compute cache, WP13) are
created alongside them — each holds its own connection to the same
database, keeping DBDataLoader strictly read-only. Route handlers call
get_proposal_repository() / get_feedback_repository() /
get_proposal_engagement_repository() to access them.

State
-----
  _loader          : DBDataLoader instance (created at startup)
  _country_index   : CountryIndex instance (built at startup from the loader)
  _passage_index   : PassageIndex instance (crossing polygons, same lifetime)
  _rail_routers    : dict[graph_key, RailRouter] (built at startup on the
                     CountryIndex, one per configured routing graph)
  _proposal_repo   : ProposalRepository instance (created at startup)
  _feedback_repo   : FeedbackRepository instance (created at startup)
  _engagement_repo : ProposalEngagementRepository instance (created at startup)
  _compute_cache   : ComputeCacheRepository instance (created at startup)
  _loaded          : bool — True after successful DB connection
  _loaded_at       : datetime | None — UTC timestamp of startup
  _load_error      : str | None — error message if startup failed
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Singleton state
# ---------------------------------------------------------------------------
_loader = None
_country_index = None
_passage_index = None
_rail_routers: dict = {}
_proposal_repo = None
_feedback_repo = None
_engagement_repo = None
_auth_repo = None
_compute_cache = None
_loaded: bool = False
_loaded_at: Optional[datetime] = None
_load_error: Optional[str] = None


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


class DataNotLoadedError(Exception):
    """Raised when an endpoint needs the DB loader but it is not available."""

    pass


class RoutingGraphNotConfiguredError(Exception):
    """Raised when a scenario pins a routing_graph_key this deployment
    serves no OpenRailRouting instance for — a configuration error, never
    something to paper over with a different graph."""

    pass


def _routing_graph_urls() -> dict:
    """graph_key → base URL, from the environment (see the registry
    contract in the module docstring, and the naming contract in
    rail_router.py). The default key is always present so a deployment
    that configures no graph at all still routes."""
    # Imported here, not at module scope, for the same reason init()'s
    # imports are deferred: rail_router pulls in the geometry stack.
    from models.route.routing.rail_router import (
        DEFAULT_ROUTING_GRAPH_KEY,
        ROUTING_URL_ENV_PREFIX,
        default_base_url,
    )

    urls = {
        var[len(ROUTING_URL_ENV_PREFIX) :].lower(): value.strip()
        for var, value in os.environ.items()
        if var.startswith(ROUTING_URL_ENV_PREFIX) and value.strip()
    }
    urls.setdefault(DEFAULT_ROUTING_GRAPH_KEY, default_base_url())
    return urls


def init() -> None:
    """
    Initialise the DBDataLoader and CountryIndex at startup.
    Called once from main.py before the Flask app starts serving requests.
    """
    global \
        _loader, \
        _country_index, \
        _passage_index, \
        _rail_routers, \
        _proposal_repo, \
        _feedback_repo, \
        _engagement_repo, \
        _auth_repo, \
        _compute_cache, \
        _loaded, \
        _loaded_at, \
        _load_error

    from adapters.data_loader_from_db import DBDataLoader
    from adapters.proposal.repository import ProposalRepository
    from adapters.feedback_repository import FeedbackRepository
    from adapters.proposal.engagement_repository import ProposalEngagementRepository
    from adapters.auth_repository import AuthRepository
    from adapters.proposal.compute_cache import ComputeCacheRepository
    from models.route.routing.rail_router import (
        CountryIndex,
        PassageIndex,
        RailRouter,
    )

    logger.info("Connecting to database...")

    try:
        _loader = DBDataLoader()
        _country_index = CountryIndex(_loader.get_country_geometries())
        # Crossing polygons are static reference data like the country
        # borders — a tunnel does not move between scenarios — so the index
        # is a startup singleton too. What a scenario pins are the charges,
        # resolved per request by DBDataLoader.build_all_passages().
        _passage_index = PassageIndex(_loader.get_passage_geometries())
        # One RailRouter per configured graph, all sharing the two static
        # indexes — border and crossing geometry are properties of the
        # planet, not of an OSM snapshot. Construction is cheap (a
        # Session each, no network call), so even a graph no scenario
        # pins yet costs nothing until routed on.
        _rail_routers = {
            key: RailRouter(_country_index, _passage_index, base_url=url)
            for key, url in _routing_graph_urls().items()
        }
        logger.info(
            "Routing graphs configured: %s",
            ", ".join(
                f"{key} → {router.base_url}"
                for key, router in sorted(_rail_routers.items())
            ),
        )
        _proposal_repo = ProposalRepository()
        _feedback_repo = FeedbackRepository()
        _engagement_repo = ProposalEngagementRepository()
        _auth_repo = AuthRepository()
        _compute_cache = ComputeCacheRepository()
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


def get_rail_router(graph_key: str | None = None):
    """
    Return the RailRouter for one routing graph — graph_key is a
    scenario's routing_graph_key pin; None → DEFAULT_ROUTING_GRAPH_KEY.
    Raises DataNotLoadedError if init() has not completed successfully,
    and RoutingGraphNotConfiguredError for a key this deployment serves
    no instance for (see the registry contract in the module docstring).
    """
    from models.route.routing.rail_router import (
        DEFAULT_ROUTING_GRAPH_KEY,
        routing_url_env_var,
    )

    if not _loaded or not _rail_routers:
        raise DataNotLoadedError("Data not loaded. Call POST /api/data/load first.")
    key = graph_key or DEFAULT_ROUTING_GRAPH_KEY
    router = _rail_routers.get(key)
    if router is None:
        raise RoutingGraphNotConfiguredError(
            f"No routing instance configured for graph '{key}' — expected "
            f"env {routing_url_env_var(key)} (see "
            f"backend/docker/.env.example). Configured: "
            f"{', '.join(sorted(_rail_routers))}."
        )
    return router


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


def get_proposal_engagement_repository():
    """
    Return the singleton ProposalEngagementRepository.
    Raises DataNotLoadedError if init() has not completed successfully.
    """
    if not _loaded or _engagement_repo is None:
        raise DataNotLoadedError("Data not loaded. Call POST /api/data/load first.")
    return _engagement_repo


def get_compute_cache():
    """
    Return the singleton ComputeCacheRepository (§2.3 compute cache).
    Raises DataNotLoadedError if init() has not completed successfully.
    """
    if not _loaded or _compute_cache is None:
        raise DataNotLoadedError("Data not loaded. Call POST /api/data/load first.")
    return _compute_cache


def get_auth_repository():
    """
    Return the singleton AuthRepository.
    Raises DataNotLoadedError if init() has not completed successfully.
    """
    if not _loaded or _auth_repo is None:
        raise DataNotLoadedError("Data not loaded. Call POST /api/data/load first.")
    return _auth_repo
