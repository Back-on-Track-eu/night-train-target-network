"""
routes/evaluate.py
==================
Full pipeline endpoint: route + cost model in one call.

  POST /api/evaluate

Request body (JSON)
-------------------
{
  "stops": [
    {"stop_id": "wien-hbf",    "stop_type": "boarding"},
    {"stop_id": "salzburg-hbf","stop_type": "both"},
    {"stop_id": "hamburg-hbf", "stop_type": "alighting"}
  ],
  "composition_id":    "NJ-3.1",
  "departure_time_h":  21.0,
  "utilization_seat":       0.7,
  "utilization_couchette":  0.6,
  "utilization_sleeper":    0.5,
  "avg_fare_seat":          49.0,
  "avg_fare_couchette":     79.0,
  "avg_fare_sleeper":      129.0,
  "operating_days_year":   360
}

Response body (JSON)
--------------------
{
  "result":   { ...ModelResult.to_dict() },
  "route":    { ...route geometry for map rendering },
  "schedule": [ ...ScheduleStop list ]
}
"""

from flask import Blueprint, jsonify, request
import logging

from api.dependencies import require_data
from models.route_evaluation_model.run_model import run

logger = logging.getLogger(__name__)
bp = Blueprint("evaluate", __name__)

# ---------------------------------------------------------------------------
# Required and optional fields with their types
# ---------------------------------------------------------------------------
_REQUIRED_FIELDS = {
    "stops":                  list,
    "composition_id":         str,
    "departure_time_h":       (int, float),
    "utilization_seat":       (int, float),
    "utilization_couchette":  (int, float),
    "utilization_sleeper":    (int, float),
    "avg_fare_seat":          (int, float),
    "avg_fare_couchette":     (int, float),
    "avg_fare_sleeper":       (int, float),
    "operating_days_year":    int,
}

_VALID_STOP_TYPES = {"boarding", "alighting", "both"}


@bp.post("")
def evaluate():
    """
    Run the full night train pipeline: route + cost model.
    Reuses the cached SheetDataLoader from dependencies — no reload.
    Returns ModelResult.
    """
    # --- require loaded data, get cached loader ---
    loader = require_data()

    # --- parse + validate request ---
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "bad_request", "message": "Request body must be JSON."}), 400

    errors = _validate(body)
    if errors:
        return jsonify({"error": "validation_error", "details": errors}), 400

    # --- extract inputs ---
    stops_input = [
        (s["stop_id"], s["stop_type"])
        for s in body["stops"]
    ]

    # --- run pipeline ---
    try:
        result = run(
            loader                = loader,
            stop_inputs           = stops_input,
            composition_id        = body["composition_id"],
            departure_time_h      = float(body["departure_time_h"]),
            utilization_seat      = float(body["utilization_seat"]),
            utilization_couchette = float(body["utilization_couchette"]),
            utilization_sleeper   = float(body["utilization_sleeper"]),
            avg_fare_seat         = float(body["avg_fare_seat"]),
            avg_fare_couchette    = float(body["avg_fare_couchette"]),
            avg_fare_sleeper      = float(body["avg_fare_sleeper"]),
            operating_days_year   = int(body["operating_days_year"]),
        )

    except ValueError as e:
        logger.warning("Evaluate failed (domain error): %s", e)
        return jsonify({"error": "domain_error", "message": str(e)}), 422

    except Exception as e:
        logger.exception("Evaluate failed (unexpected): %s", e)
        return jsonify({"error": "pipeline_error", "message": str(e)}), 500

    return jsonify({
        "result": result.to_dict(),
    }), 200


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate(body: dict) -> list[str]:
    errors = []

    # required top-level fields
    for field, expected_type in _REQUIRED_FIELDS.items():
        if field not in body:
            errors.append(f"Missing required field: '{field}'.")
            continue
        if not isinstance(body[field], expected_type):
            errors.append(
                f"Field '{field}' must be {_type_name(expected_type)}, "
                f"got {type(body[field]).__name__}."
            )

    if errors:
        return errors  # stop early if structure is broken

    # stops list
    stops = body["stops"]
    if len(stops) < 2:
        errors.append("'stops' must contain at least 2 entries.")
    for i, s in enumerate(stops):
        if not isinstance(s, dict):
            errors.append(f"stops[{i}] must be an object.")
            continue
        if "stop_id" not in s or not isinstance(s["stop_id"], str):
            errors.append(f"stops[{i}].stop_id must be a string.")
        if "stop_type" not in s:
            errors.append(f"stops[{i}].stop_type is required.")
        elif s["stop_type"] not in _VALID_STOP_TYPES:
            errors.append(
                f"stops[{i}].stop_type '{s['stop_type']}' is invalid. "
                f"Must be one of: {sorted(_VALID_STOP_TYPES)}."
            )

    # utilization range
    for field in ("utilization_seat", "utilization_couchette", "utilization_sleeper"):
        val = body.get(field)
        if isinstance(val, (int, float)) and not (0.0 <= val <= 1.0):
            errors.append(f"'{field}' must be between 0.0 and 1.0.")

    # positive fares
    for field in ("avg_fare_seat", "avg_fare_couchette", "avg_fare_sleeper"):
        val = body.get(field)
        if isinstance(val, (int, float)) and val < 0:
            errors.append(f"'{field}' must be non-negative.")

    # operating days
    val = body.get("operating_days_year")
    if isinstance(val, int) and not (1 <= val <= 366):
        errors.append("'operating_days_year' must be between 1 and 366.")

    return errors


def _type_name(t) -> str:
    if isinstance(t, tuple):
        return " or ".join(x.__name__ for x in t)
    return t.__name__