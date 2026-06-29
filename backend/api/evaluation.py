"""
evaluation.py
=============
Cost and revenue evaluation endpoint.

  POST /api/evaluation/calc

Accepts a Route object (from POST /api/route/planOrUpdate) plus a demand
object with OD-pair level sold places and prices.
Returns EvaluationResult with full normalised matrix at route / trip /
country / OD-pair level.

For testing without a real demand model, populate route_demand with
simple dummy values — e.g. flat utilisation × capacity.
"""

import logging

from flask import Blueprint, jsonify, request

from api.dependencies import get_loader
from models.evaluation.calc import evaluate_route, RouteDemand, TripDemand, ODDemand
from models.evaluation.version import CALC_VERSION
from models.route.route import Route

logger = logging.getLogger(__name__)
bp = Blueprint("evaluation", __name__)

_VALID_CLASS_MAINS = {"Seat", "Couchette", "Sleeper", "Capsule", "Catering"}


def _validate(body: dict) -> list[str]:
    errors = []

    # route
    if not isinstance(body.get("route"), dict):
        errors.append("'route' must be an object (Route.to_dict() output).")

    # operating_days_year
    ody = body.get("operating_days_year")
    if not isinstance(ody, int):
        errors.append("'operating_days_year' must be an integer.")
    elif not (1 <= ody <= 366):
        errors.append("'operating_days_year' must be between 1 and 366.")

    # route_demand
    demand = body.get("route_demand")
    if not isinstance(demand, dict):
        errors.append("'route_demand' must be an object {trip_id: {od_pairs: [...]}}.")
    else:
        for trip_id, trip_d in demand.items():
            if not isinstance(trip_d, dict):
                errors.append(f"route_demand['{trip_id}'] must be an object.")
                continue
            od_pairs = trip_d.get("od_pairs", [])
            if not isinstance(od_pairs, list):
                errors.append(f"route_demand['{trip_id}'].od_pairs must be a list.")
                continue
            for i, od in enumerate(od_pairs):
                prefix = f"route_demand['{trip_id}'].od_pairs[{i}]"
                if not isinstance(od.get("origin_stop_id"), str):
                    errors.append(f"{prefix}.origin_stop_id must be a string.")
                if not isinstance(od.get("destination_stop_id"), str):
                    errors.append(f"{prefix}.destination_stop_id must be a string.")
                if od.get("class_main") not in _VALID_CLASS_MAINS:
                    errors.append(
                        f"{prefix}.class_main '{od.get('class_main')}' is invalid. "
                        f"Must be one of: {sorted(_VALID_CLASS_MAINS)}."
                    )
                if not isinstance(od.get("places_sold"), int) or od["places_sold"] < 0:
                    errors.append(
                        f"{prefix}.places_sold must be a non-negative integer."
                    )
                if (
                    not isinstance(od.get("avg_price"), (int, float))
                    or od["avg_price"] < 0
                ):
                    errors.append(f"{prefix}.avg_price must be a non-negative number.")

    return errors


def _parse_demand(demand_body: dict) -> RouteDemand:
    """Parse route_demand from request body into RouteDemand domain object."""
    trips: dict[str, TripDemand] = {}
    for trip_id, trip_d in demand_body.items():
        od_pairs = [
            ODDemand(
                origin_stop_id=od["origin_stop_id"],
                destination_stop_id=od["destination_stop_id"],
                class_main=od["class_main"],
                places_sold=int(od["places_sold"]),
                avg_price=float(od["avg_price"]),
            )
            for od in trip_d.get("od_pairs", [])
        ]
        trips[trip_id] = TripDemand(trip_id=trip_id, od_pairs=od_pairs)
    return RouteDemand(trips=trips)


@bp.post("/calc")
def calc():
    """
    Run cost and revenue evaluation for a Route.

    The 'route' object comes from POST /api/route/planOrUpdate.
    The 'route_demand' object provides OD-pair demand with sold places
    and average prices per class.

    For testing, use simple dummy demand values — e.g.:
      {
        "trip_id_outbound": {
          "od_pairs": [
            {"origin_stop_id": "DE_BERLIN_HBF", "destination_stop_id": "AT_WIEN_HBF",
             "class_main": "Couchette", "places_sold": 40, "avg_price": 89.0}
          ]
        }
      }
    """
    loader = get_loader()

    body = request.get_json(silent=True)
    if not body:
        return (
            jsonify({"error": "bad_request", "message": "Request body must be JSON."}),
            400,
        )

    errors = _validate(body)
    if errors:
        return jsonify({"error": "validation_error", "details": errors}), 400

    try:
        route = Route.from_dict(body["route"])
        route_demand = _parse_demand(body["route_demand"])

        result = evaluate_route(
            route=route,
            route_demand=route_demand,
            operating_days_year=int(body["operating_days_year"]),
            loader=loader,
        )

    except ValueError as e:
        logger.warning("evaluation/calc failed (domain error): %s", e)
        return jsonify({"error": "domain_error", "message": str(e)}), 422
    except Exception as e:
        logger.exception("evaluation/calc failed (unexpected): %s", e)
        return jsonify({"error": "calc_error", "message": str(e)}), 500

    return (
        jsonify(
            {
                "calc_version": CALC_VERSION,
                "result": result.to_dict(),
            }
        ),
        200,
    )
