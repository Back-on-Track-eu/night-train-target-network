"""
routes/route_builder.py
=======================
Route builder endpoint.

  POST /api/route-builder/build

Accepts a stop list, composition ID and departure time.
Returns a fully built Route with both trips (outbound + return),
including geometry, timetable and physics stats.
NO monetary values in the response — use POST /api/cost-rev-calc/calc
to evaluate costs and revenue.
"""

import logging
import os
import re

from flask import Blueprint, jsonify, request

from api.dependencies import get_loader
from models.route.route_factory import build_route
from models.route.routing.rail_router import RailRouter
from models.route.version import ROUTE_BUILDER_VERSION

logger = logging.getLogger(__name__)
bp = Blueprint("route_builder", __name__)

_VALID_STOP_TYPES = {"boarding", "alighting", "both"}
_HHMM_RE          = re.compile(r"^\d{1,2}:\d{2}$")


def _parse_departure_time(value: str) -> int:
    """
    Parse "HH:MM" string to minutes from midnight day 1.
    Raises ValueError if format is invalid.
    """
    if not _HHMM_RE.match(value):
        raise ValueError(
            f"departure_time '{value}' is not a valid HH:MM time. "
            f"Examples: '21:00', '06:30'."
        )
    h, m = value.split(":")
    h, m = int(h), int(m)
    if not (0 <= h <= 47 and 0 <= m <= 59):
        raise ValueError(
            f"departure_time '{value}': hours must be 0–47 "
            f"(supports next-day departures), minutes 0–59."
        )
    return h * 60 + m


def _validate(body: dict) -> list[str]:
    errors = []

    # ToDo: Should we include also a check whether composition id and stop_id exists in the data?

    if "stops" not in body:
        errors.append("Missing required field: 'stops'.")
    elif not isinstance(body["stops"], list):
        errors.append("'stops' must be a list.")
    else:
        stops = body["stops"]
        if len(stops) < 2:
            errors.append("'stops' must contain at least 2 entries.")
        for i, s in enumerate(stops):
            if not isinstance(s, dict):
                errors.append(f"stops[{i}] must be an object.")
                continue
            if not isinstance(s.get("stop_id"), str):
                errors.append(f"stops[{i}].stop_id must be a string.")
            if s.get("stop_type") not in _VALID_STOP_TYPES:
                errors.append(
                    f"stops[{i}].stop_type '{s.get('stop_type')}' is invalid. "
                    f"Must be one of: {sorted(_VALID_STOP_TYPES)}."
                )

    if "composition_id" not in body:
        errors.append("Missing required field: 'composition_id'.")
    elif not isinstance(body["composition_id"], str):
        errors.append("'composition_id' must be a string.")

    if "departure_time" not in body:
        errors.append("Missing required field: 'departure_time' (format: HH:MM).")
    elif not isinstance(body["departure_time"], str):
        errors.append("'departure_time' must be a string in HH:MM format.")
    else:
        try:
            _parse_departure_time(body["departure_time"])
        except ValueError as e:
            errors.append(str(e))

    return errors


@bp.post("/build")
def build():
    """
    Build a Route from stop list, composition and departure time.

    Returns Route with outbound and return trips — geometry, timetable,
    physics stats. No monetary values.
    """
    loader = get_loader()

    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "bad_request", "message": "Request body must be JSON."}), 400

    errors = _validate(body)
    if errors:
        return jsonify({"error": "validation_error", "details": errors}), 400

    stop_inputs = [
        (s["stop_id"], s["stop_type"])
        for s in body["stops"]
    ]

    try:
        departure_time_min = _parse_departure_time(body["departure_time"])

        router = RailRouter(
            base_url=os.environ.get("OPENRAILROUTING_URL", "http://localhost:8989")
        )

        route = build_route(
            stop_inputs        = stop_inputs,
            composition_id     = body["composition_id"],
            departure_time_min = departure_time_min,
            loader             = loader,
            router             = router,
        )

    except ValueError as e:
        logger.warning("build-route failed (domain error): %s", e)
        return jsonify({"error": "domain_error", "message": str(e)}), 422

    except Exception as e:
        logger.exception("build-route failed (unexpected): %s", e)
        return jsonify({"error": "build_error", "message": str(e)}), 500

    return jsonify({
        "route_builder_version": ROUTE_BUILDER_VERSION,
        "route":                 route.to_dict(),
    }), 200