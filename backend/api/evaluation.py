"""
evaluation.py
=============
POST /api/evaluation/calc

Accepts a pre-built Route JSON (from POST /api/route/plan) and
returns the full cost/revenue evaluation with all Breakdown views and
normalisations.

Pipeline steps — each logged individually:
  1. Validate + deserialize Route JSON
  2. Load track + stop infrastructure from DB
  3. Evaluate: calc.evaluate_route → EvaluationResult
  4. Build views: all Breakdown matrices
  5. Serialize → response
"""

import logging
import time

from flask import Blueprint, jsonify, request

from api.helpers.dependencies import get_loader
from api.helpers.serialize import (
    validate_route_dict,
    route_from_dict,
    matrix_to_dict,
    normalise_all_to_dict,
)
from models.evaluation.calc import evaluate_route
from models.evaluation.views import (
    build_breakdown,
    build_breakdown_per_trip_pair,
    build_breakdown_per_trip_pair_per_country,
    build_breakdown_per_trip_pair_per_od,
    build_breakdown_per_trip_per_stop,
)
from models.evaluation.version import CALC_VERSION

logger = logging.getLogger(__name__)
bp = Blueprint("evaluation", __name__)

def _validate_body(body: dict) -> list[str]:
    if not isinstance(body.get("route"), dict):
        return ["'route' must be an object (route_to_dict() output)."]
    return validate_route_dict(body["route"])

@bp.post("/calc")
def calc():
    """
    Run cost/revenue evaluation for a Route.

    Request body:
      {
        "route": <route_to_dict() output from POST /api/route/plan>,
        "scenario_id": <optional int — overrides the route's own embedded
                        scenario_id; omit to cost the route under the same
                        scenario it was planned with>
      }

    Response:
      { "calc_version": "...", "result": { "route_id": "...", "views": {...} } }
    """
    loader = get_loader()
    t_start = time.monotonic()

    # Step 1 — validate + deserialize (hand in hand)
    body = request.get_json(silent=True)
    errors = ["Request body must be JSON."] if not body else _validate_body(body)
    if errors:
        logger.warning("evaluation/calc [1/5] validation failed — %s", errors)
        return jsonify({"error": "validation_error", "details": errors}), 400

    scenario_override = body.get("scenario_id")
    if scenario_override is not None and not isinstance(scenario_override, int):
        return (
            jsonify({
                "error": "validation_error",
                "details": ["'scenario_id' must be an integer if provided."],
            }),
            400,
        )

    try:
        route = route_from_dict(body["route"], loader, scenario_id=scenario_override)
    except ValueError as e:
        logger.warning("evaluation/calc [1/5] scenario resolution failed: %s", e)
        return jsonify({"error": "validation_error", "details": [str(e)]}), 400
    logger.info("evaluation/calc [1/5] route %s deserialized (%.3fs)",
                route.route_id, time.monotonic() - t_start)

    # Step 2 — load infrastructure, same scenario the route was reconstructed under
    resolved_scenario_id = scenario_override if scenario_override is not None else body["route"].get("scenario_id")
    try:
        tracks, _ = loader.build_all_tracks(resolved_scenario_id)
        stop_infra, _ = loader.build_all_stops(resolved_scenario_id)
    except Exception as e:
        logger.exception("evaluation/calc [2/5] infrastructure load failed: %s", e)
        return jsonify({"error": "infrastructure_error", "message": str(e)}), 503

    logger.info("evaluation/calc [2/5] infrastructure loaded (%.3fs)", time.monotonic() - t_start)

    # Step 3 — evaluate
    try:
        result = evaluate_route(route=route, tracks=tracks, stop_infra=stop_infra)
    except ValueError as e:
        logger.warning("evaluation/calc [3/5] domain error: %s", e)
        return jsonify({"error": "domain_error", "message": str(e)}), 422
    except Exception as e:
        logger.exception("evaluation/calc [3/5] evaluation failed: %s", e)
        return jsonify({"error": "calc_error", "message": str(e)}), 500

    logger.info("evaluation/calc [3/5] evaluated route %s (%.3fs)",
                route.route_id, time.monotonic() - t_start)

    # Step 4 — build views
    try:
        bd_all = build_breakdown(route, result)
        bd_per_pair = build_breakdown_per_trip_pair(route, result)
        matrix_country = build_breakdown_per_trip_pair_per_country(route, result)
        matrix_od = build_breakdown_per_trip_pair_per_od(route, result)
        matrix_stop = build_breakdown_per_trip_per_stop(route, result)
    except Exception as e:
        logger.exception("evaluation/calc [4/5] view building failed: %s", e)
        return jsonify({"error": "view_error", "message": str(e)}), 500

    logger.info("evaluation/calc [4/5] views built (%.3fs)", time.monotonic() - t_start)

    # Step 5 — serialize
    try:
        trip_pair_by_key = {p.outbound.trip_id: p for p in route.trip_pairs}

        pair_views: dict[str, dict] = {
            pair_key: normalise_all_to_dict(bd, route, trip_pair_by_key.get(pair_key))
            for pair_key, bd in bd_per_pair.items()
        }

        response_body = {
            "route_id": route.route_id,
            "views": {
                "route": normalise_all_to_dict(bd_all, route),
                "per_trip_pair": pair_views,
                "per_trip_pair_per_country": matrix_to_dict(matrix_country, route, trip_pair_by_key),
                "per_trip_pair_per_od": matrix_to_dict(matrix_od, route, trip_pair_by_key),
                "per_trip_per_stop": matrix_to_dict(matrix_stop, route, trip_pair_by_key),
            },
        }
    except Exception as e:
        logger.exception("evaluation/calc [5/5] serialization failed: %s", e)
        return jsonify({"error": "serialization_error", "message": str(e)}), 500

    logger.info("evaluation/calc [5/5] done route %s (%.3fs total)",
                route.route_id, time.monotonic() - t_start)

    return jsonify({"calc_version": CALC_VERSION, "result": response_body}), 200