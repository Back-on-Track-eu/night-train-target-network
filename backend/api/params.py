"""
params.py
=========
Read-only parameter endpoints.

  GET /api/params/StopInfrastructures  — all stops
  GET /api/params/compositions         — all composition types
  GET /api/params/TrackInfrastructures — all country track infrastructure

Response dict-building for all three endpoints lives in
api/helpers/params_serialize.py — see its module docstring.
"""

import logging

from flask import Blueprint, jsonify, request

from api.helpers.dependencies import get_loader
from api.helpers.params_serialize import (
    stop_infra_to_dict,
    track_infra_to_dict,
    composition_collection_to_dict,
)

logger = logging.getLogger(__name__)
bp = Blueprint("params", __name__)


@bp.get("/StopInfrastructures")
def get_stop_infrastructures():
    """
    Return all available stops with routing-relevant fields and parameter
    provenance. Fields resolved from a default row are marked with
    is_default=True. See params_serialize.stop_infra_to_dict() for the
    response layout.

    Query params:
      scenario_id : int (optional) — pins parameter versions; omit for the
                    live is_current_base scenario.
    """
    loader = get_loader()
    scenario_id = request.args.get("scenario_id", type=int)
    stop_infra = loader.build_all_stops(scenario_id)
    return jsonify(stop_infra_to_dict(stop_infra)), 200


@bp.get("/compositions")
def get_compositions():
    """
    Return all available composition types with full parameters, plus a
    top-level list of the operators they reference. Capacity and density
    expressed per service class. Staff overhead converted to hours for
    display. See params_serialize.composition_collection_to_dict() for
    the response layout.

    Query params:
      scenario_id : int (optional) — compositions/operators/coach types
                    are not scenario-versioned (see CompositionCollection);
                    this only affects the "indicative" KPIs, which are
                    computed using track/stop infrastructure costs. Omit
                    for the live is_current_base scenario.
    """
    loader = get_loader()
    scenario_id = request.args.get("scenario_id", type=int)
    compositions = loader.build_all_compositions(scenario_id)
    return jsonify(composition_collection_to_dict(compositions)), 200


@bp.get("/TrackInfrastructures")
def get_track_infrastructures():
    """
    Return all country track infrastructure parameters with per-field
    provenance. Fields resolved from the EU-average default row are marked
    with is_default=True, and the default row's source/version is shown
    instead of the country row's. See
    params_serialize.track_infra_to_dict() for the response layout.

    Query params:
      scenario_id : int (optional) — pins parameter versions; omit for the
                    live is_current_base scenario.
    """
    loader = get_loader()
    scenario_id = request.args.get("scenario_id", type=int)
    track_infra = loader.build_all_tracks(scenario_id)
    return jsonify(track_infra_to_dict(track_infra)), 200