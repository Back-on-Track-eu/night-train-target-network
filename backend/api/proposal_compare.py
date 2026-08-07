"""
proposal_compare.py
====================
POST /api/proposals/compare

The compare endpoint (adapters/proposal/README.md §7.3). Two sides, each
anchored on one stored proposal, each optionally overriding
scenario_id/composition_id — an override side is computed ephemerally
(never persisted, published: false), a bare side is the stored proposal
itself. Same anchor on both sides = variant compare on one route;
different anchors = cross-proposal compare.

All actual work lives in api/helpers/proposal_compare.py (validation,
per-side resolution, diff building) — this view is thin delegation plus
error mapping, like every other blueprint file. Stateless and
unauthenticated: comparing writes nothing, same policy as
POST /api/proposal/calc.
"""

import logging

from flask import Blueprint, jsonify, request

from api.helpers.dependencies import get_loader, get_proposal_repository
from api.helpers.proposal_compare import (
    SideNotFoundError,
    build_diff,
    build_route_context,
    resolve_side,
    validate_compare_body,
)

logger = logging.getLogger(__name__)
bp = Blueprint("proposal_compare", __name__)


@bp.post("/proposals/compare")
def compare():
    """
    Compare two proposal-anchored sides — see adapters/proposal/README.md §7.3
    and api/README.md for the full contract. The diff is side B minus
    side A (sides[1] - sides[0]).

    Request body:
      {
        "sides": [
          {"proposal_id": 123},                     // the stored proposal as-is
          {"proposal_id": 123, "scenario_id": 4}    // ephemeral what-if compute
        ]                                           // overridable: scenario_id,
      }                                             //   composition_id

    Response:
      {
        "sides": [<side>, <side>],   // full compute-response shape each,
                                     //   + published flag + summary block
        "diff": {
          "summary": {...},          // {a, b, abs, rel} per gallery KPI
          "views": {...},            // per-leaf deltas over the shared views trees
          "views_unmatched": {"a_only": [...], "b_only": [...]}
        },
        "route_context": {"fingerprints": [...], "route_identical": bool,
                          "differing_request_fields": [...]}
      }
    """
    body = request.get_json(silent=True)
    if not body:
        return (
            jsonify({"error": "bad_request", "message": "Request body must be JSON."}),
            400,
        )

    errors = validate_compare_body(body)
    if errors:
        logger.warning("proposals/compare validation failed — %s", errors)
        return jsonify({"error": "validation_error", "details": errors}), 400

    repo = get_proposal_repository()
    loader = get_loader()

    sides = []
    for index, side_spec in enumerate(body["sides"]):
        try:
            sides.append(resolve_side(index, side_spec, repo, loader))
        except SideNotFoundError as e:
            return jsonify({"error": "not_found", "message": str(e)}), 404
        except ValueError as e:
            logger.warning(
                "proposals/compare side %d failed (domain error): %s", index, e
            )
            return (
                jsonify({"error": "domain_error", "message": f"sides[{index}]: {e}"}),
                422,
            )
        except Exception as e:
            logger.exception(
                "proposals/compare side %d failed (unexpected): %s", index, e
            )
            return jsonify({"error": "compare_error", "message": str(e)}), 500

    payload = {
        "sides": sides,
        "diff": build_diff(sides[0], sides[1]),
        "route_context": build_route_context(sides[0], sides[1]),
    }
    return jsonify(payload), 200
