"""
scenarios.py
============
Read-only scenario listing.

  GET /api/scenarios — all scenario.scenarios rows, grouped by current
                        status, plus the measure sets and the flattened
                        (scenario x measure set) variant axis (see
                        scenario_serialize.scenario_collection_to_dict)

Not to be confused with the proposals API (formerly named "scenarios" —
see api/proposals.py's module docstring) — this endpoint covers the
parameter-versioning scenario.scenarios table.
"""

import logging

from flask import Blueprint, jsonify

from api.helpers.dependencies import get_loader
from api.helpers.scenario_serialize import scenario_collection_to_dict

logger = logging.getLogger(__name__)
bp = Blueprint("scenarios", __name__)


@bp.get("/scenarios")
def get_scenarios():
    """
    Return every scenario, grouped into current_base / current_scenarios /
    historical_scenarios, each with its own count plus name, description,
    and full attributes; then measure_sets and scenario_variants, the
    axis a proposal family is computed over. See
    scenario_serialize.scenario_collection_to_dict() for the response
    layout.
    """
    loader = get_loader()
    return jsonify(
        scenario_collection_to_dict(
            loader.list_all_scenarios(),
            list(loader.build_all_measure_sets().all().values()),
            loader.list_scenario_variants(),
        )
    ), 200
