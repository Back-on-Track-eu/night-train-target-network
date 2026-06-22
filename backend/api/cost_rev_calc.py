"""
routes/cost_rev_calc.py
=======================
Cost and revenue evaluation endpoint.

  POST /api/cost-rev-calc/calc

Accepts a Route object (from POST /api/route-builder/build) plus financial
parameters (utilization, fares, operating days).
Returns EvaluationResult with per-trip cost/revenue breakdowns and
route-level aggregates.
"""

import logging

from flask import Blueprint, jsonify, request

from api.dependencies import get_loader
from models.cost_rev_eval.calc import evaluate_route
from models.cost_rev_eval.version import CALC_VERSION
from models.route.route import Route

logger = logging.getLogger(__name__)
bp = Blueprint("cost_rev_calc", __name__)

_REQUIRED_FINANCIAL = {
    "utilization_seat":       (int, float),
    "utilization_couchette":  (int, float),
    "utilization_sleeper":    (int, float),
    "avg_fare_seat":          (int, float),
    "avg_fare_couchette":     (int, float),
    "avg_fare_sleeper":       (int, float),
    "operating_days_year":    int,
}


def _validate(body: dict) -> list[str]:
    errors = []

    # route object
    if "route" not in body:
        errors.append("Missing required field: 'route'.")
    elif not isinstance(body["route"], dict):
        errors.append("'route' must be an object (Route.to_dict() output).")
    else:
        for required_key in ("route_id", "operator_id", "trips"):
            if required_key not in body["route"]:
                errors.append(f"'route.{required_key}' is required.")

    # financial fields
    for field, expected_type in _REQUIRED_FINANCIAL.items():
        if field not in body:
            errors.append(f"Missing required field: '{field}'.")
            continue
        if not isinstance(body[field], expected_type):
            type_name = (
                " or ".join(t.__name__ for t in expected_type)
                if isinstance(expected_type, tuple)
                else expected_type.__name__
            )
            errors.append(
                f"Field '{field}' must be {type_name}, "
                f"got {type(body[field]).__name__}."
            )

    if errors:
        return errors

    # utilization range
    for field in ("utilization_seat", "utilization_couchette", "utilization_sleeper"):
        val = body.get(field)
        if isinstance(val, (int, float)) and not (0.0 <= val <= 1.0):
            errors.append(f"'{field}' must be between 0.0 and 1.0.")

    # non-negative fares
    for field in ("avg_fare_seat", "avg_fare_couchette", "avg_fare_sleeper"):
        val = body.get(field)
        if isinstance(val, (int, float)) and val < 0:
            errors.append(f"'{field}' must be non-negative.")

    # operating days
    val = body.get("operating_days_year")
    if isinstance(val, int) and not (1 <= val <= 366):
        errors.append("'operating_days_year' must be between 1 and 366.")

    return errors


@bp.post("/calc")
def calc():
    """
    Run cost and revenue evaluation for a Route.

    The route object is passed back from POST /api/route-builder/build.
    All monetary calculations happen here — TAC, energy costs, station
    charges, parking, revenue, cost breakdown, class allocation.
    """
    loader = get_loader()

    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "bad_request", "message": "Request body must be JSON."}), 400

    errors = _validate(body)
    if errors:
        return jsonify({"error": "validation_error", "details": errors}), 400

    try:
        route = Route.from_dict(body["route"])

        result = evaluate_route(
            route                 = route,
            utilization_seat      = float(body["utilization_seat"]),
            utilization_couchette = float(body["utilization_couchette"]),
            utilization_sleeper   = float(body["utilization_sleeper"]),
            avg_fare_seat         = float(body["avg_fare_seat"]),
            avg_fare_couchette    = float(body["avg_fare_couchette"]),
            avg_fare_sleeper      = float(body["avg_fare_sleeper"]),
            operating_days_year   = int(body["operating_days_year"]),
            loader                = loader,
        )

    except ValueError as e:
        logger.warning("cost-rev-calc failed (domain error): %s", e)
        return jsonify({"error": "domain_error", "message": str(e)}), 422

    except Exception as e:
        logger.exception("cost-rev-calc failed (unexpected): %s", e)
        return jsonify({"error": "calc_error", "message": str(e)}), 500

    return jsonify({
        "calc_version": CALC_VERSION,
        "result":       result.to_dict(),
    }), 200