"""
proposal_calc.py
=================
POST /api/proposal/calc

The merged compute endpoint (PROPOSALS_DESIGN.md §2.1, WP2). One stateless
request -> route + evaluation, no side effects.

The actual pipeline lives two layers down — domain orchestration in
models/pipeline.py, validation + serialization in api/helpers/
proposal_compute.py — so publish (api/helpers/publish_dispatch.py)
computes exactly the same way this endpoint does, with no risk of the two
drifting apart. This view is thin delegation + a cache_hit stamp only.
"""

import logging

from flask import Blueprint, jsonify, request

from api.helpers.proposal_compute import compute_proposal, validate_calc_body

logger = logging.getLogger(__name__)
bp = Blueprint("proposal_calc", __name__)


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
