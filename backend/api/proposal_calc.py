"""
proposal_calc.py
=================
POST /api/proposal/calc

The merged compute endpoint (PROPOSALS_DESIGN.md §2.1, WP2). One stateless
request -> route + evaluation, no side effects.

WP5 update: the actual build/evaluate/serialize pipeline moved out of this
module in two steps — domain orchestration into models/pipeline.py,
serialization into api/helpers/proposal_compute.py — so publish
(api/helpers/publish_dispatch.py) can compute exactly the same way this
endpoint does, with no risk of the two drifting apart. This view is now
just validation + a cache_hit stamp; see those two modules for what
actually happens.
"""

import logging

from flask import Blueprint, jsonify, request

from api.helpers.proposal_compute import compute_proposal
from models.route.routing.rail_router import VALID_ROUTING_MODES
from models.route.timetable import (
    VALID_AUTO_STOP_ADDITION_MODES,
    VALID_SCHEDULE_MODES,
    VALID_TIMETABLE_MODES,
)
from models.route.version import (
    DEFAULT_AUTO_STOP_ADDITION,
    DEFAULT_ROUTING_MODE,
    DEFAULT_SCHEDULE_MODE,
    DEFAULT_TIMETABLE_MODE,
)

logger = logging.getLogger(__name__)
bp = Blueprint("proposal_calc", __name__)


def validate_calc_body(body: dict) -> list[str]:
    """Request validation for the merged compute request (§2.1) — the
    former plan request's WHAT/HOW fields, minus proposal_id/
    proposal_version (publish-only, not a compute concern). Reused by
    api/helpers/publish_dispatch.py so both entry points reject the same
    malformed compute_request the same way."""
    errors = []

    if body.get("scenario_id") is not None and not isinstance(body["scenario_id"], int):
        errors.append("'scenario_id' must be an integer if provided.")

    stops = body.get("stops")
    if not isinstance(stops, list):
        errors.append("'stops' must be a list of stop_id strings.")
    elif len(stops) < 2:
        errors.append("'stops' must contain at least 2 entries.")
    elif not all(isinstance(s, str) for s in stops):
        errors.append("'stops' must be a list of stop_id strings.")

    if not isinstance(body.get("composition_id"), str):
        errors.append("'composition_id' must be a string.")

    timetable_mode = body.get("timetable_mode", DEFAULT_TIMETABLE_MODE)
    if timetable_mode not in VALID_TIMETABLE_MODES:
        errors.append(
            f"'timetable_mode' = '{timetable_mode}' is invalid. Must be one of: {sorted(VALID_TIMETABLE_MODES)}."
        )

    fixed_night_interval = body.get("fixed_night_interval")
    if timetable_mode == "simpleAutomaticWithFixedNight":
        if (
            not isinstance(fixed_night_interval, list)
            or len(fixed_night_interval) != 2
            or not all(isinstance(s, str) for s in fixed_night_interval)
            or fixed_night_interval[0] == fixed_night_interval[1]
        ):
            errors.append(
                "'fixed_night_interval' must be a list of exactly 2 distinct "
                "stop_id strings when timetable_mode is "
                "'simpleAutomaticWithFixedNight'."
            )
        elif isinstance(stops, list) and all(isinstance(s, str) for s in stops):
            missing = [s for s in fixed_night_interval if s not in stops]
            if missing:
                errors.append(
                    f"'fixed_night_interval' stops {missing} are not in 'stops'."
                )
            elif stops.index(fixed_night_interval[0]) >= stops.index(
                fixed_night_interval[1]
            ):
                errors.append(
                    "'fixed_night_interval' start must come before its end in "
                    "'stops' order."
                )
    elif fixed_night_interval is not None:
        errors.append(
            "'fixed_night_interval' is only allowed with timetable_mode "
            "'simpleAutomaticWithFixedNight'."
        )

    schedule_mode = body.get("schedule_mode", DEFAULT_SCHEDULE_MODE)
    if schedule_mode not in VALID_SCHEDULE_MODES:
        errors.append(
            f"'schedule_mode' = '{schedule_mode}' is invalid. Must be one of: {sorted(VALID_SCHEDULE_MODES)}."
        )

    routing_mode = body.get("routing_mode", DEFAULT_ROUTING_MODE)
    if routing_mode not in VALID_ROUTING_MODES:
        errors.append(
            f"'routing_mode' = '{routing_mode}' is invalid. Must be one of: {sorted(VALID_ROUTING_MODES)}."
        )

    auto_stop_addition = body.get("auto_stop_addition", DEFAULT_AUTO_STOP_ADDITION)
    if auto_stop_addition not in VALID_AUTO_STOP_ADDITION_MODES:
        errors.append(
            f"'auto_stop_addition' = '{auto_stop_addition}' is invalid. Must be one "
            f"of: {sorted(VALID_AUTO_STOP_ADDITION_MODES)}."
        )

    return errors


@bp.post("/calc")
def calc():
    """
    Plan a route and evaluate it in one call — see PROPOSALS_DESIGN.md
    §2.1 for the full request/response contract. Stateless: no
    persistence, no proposal_id/proposal_version in the request, no auth.

    Request body: identical to §2.1's WHAT/HOW fields (stops,
    composition_id, scenario_id, timetable_mode, fixed_night_interval,
    schedule_mode, routing_mode, auto_stop_addition) — see
    validate_calc_body() and docs/PROPOSALS_DESIGN.md §2.1 for field
    semantics.

    Response:
      {
        "route_builder_version": "...",
        "calc_version": "...",
        "route_fingerprint": "sha256:...",  // §3.1
        "cache_hit": false,            // always false until WP13 wires the real compute cache
        "request": { ... },            // resolved: defaults applied, scenario_id concrete
        "suggested_stops": [ ... ],    // only when auto_stop_addition="suggest"
        "route": { ... },              // route_to_dict() shape, neutral ids (R1, ...)
        "evaluation": {
          "models": { ... }, "input": { "parameters": { ... } }, "views": { ... }
        }
      }
    """
    body = request.get_json(silent=True)
    if not body:
        return (
            jsonify({"error": "bad_request", "message": "Request body must be JSON."}),
            400,
        )

    errors = validate_calc_body(body)
    if errors:
        logger.warning("proposal/calc validation failed — %s", errors)
        return jsonify({"error": "validation_error", "details": errors}), 400

    try:
        computed = compute_proposal(body)
    except ValueError as e:
        logger.warning("proposal/calc failed (domain error): %s", e)
        return jsonify({"error": "domain_error", "message": str(e)}), 422
    except Exception as e:
        logger.exception("proposal/calc failed (unexpected): %s", e)
        return jsonify({"error": "calc_error", "message": str(e)}), 500

    # Re-keyed (not just .update()) so cache_hit lands in its documented
    # §2.1 position between route_fingerprint and request rather than at
    # the end — app.json.sort_keys=False (main.py) means dict insertion
    # order is exactly the wire order. No compute cache yet (WP13) — every
    # call is necessarily a fresh compute, so this is always false rather
    # than absent, keeping the response shape stable ahead of WP13's logic
    # swap.
    payload = {
        "route_builder_version": computed["route_builder_version"],
        "calc_version": computed["calc_version"],
        "route_fingerprint": computed["route_fingerprint"],
        "cache_hit": False,
        "request": computed["request"],
    }
    if "suggested_stops" in computed:
        payload["suggested_stops"] = computed["suggested_stops"]
    payload["route"] = computed["route"]
    payload["evaluation"] = computed["evaluation"]

    return jsonify(payload), 200
