"""
proposals.py
============
Proposal endpoints — saving, listing, and loading night train proposals
(formerly the "scenarios" API; renamed to avoid colliding with the
parameter-versioning scenario.scenarios concept).

  POST /api/proposal        — save a proposal (create / new version / branch)
  GET  /api/proposals       — list current proposal versions
  POST /api/proposals       — filtered/sorted/paginated list
  GET  /api/proposal/<id>   — load the current version of a proposal

Save semantics (implemented in adapters/proposal_repository.py):
the posted route_body.route's own proposal_id decides the
outcome. Unknown or draft placeholder id → "created". Known id owned by
the saving user → new version of the same proposal ("versioned"). Known
id owned by someone else → duplicate under a new proposal_id
("branched"). Rows are append-only in all three cases; nothing is ever
updated in place.

No authentication yet — the request body carries user_id directly.
Every user can see and load every proposal.
"""

import logging

from flask import Blueprint, jsonify, request

from api.helpers.dependencies import get_proposal_repository
from api.helpers.proposal_serialize import (
    validate_save_body,
    validate_list_body,
    proposal_meta_to_dict,
    proposal_summary_to_dict,
)

logger = logging.getLogger(__name__)
bp = Blueprint("proposals", __name__)

_DEFAULT_LIMIT = 50


@bp.post("/proposal")
def save_proposal():
    """
    Save a proposal.

    Request body — post the WHOLE response of each upstream API call, not
    a hand-picked subset:
      user_id           : int   (required — admin.users identity of the saver)
      change_log        : str   (optional — what changed in this version)
      route_body        : dict  (required — the entire POST /api/route/plan
                                  response: {route_builder_version, request, route})
      evaluation_body   : dict  (optional — the entire POST /api/evaluation/calc
                                  response: {calc_version, route_id, models, input, views}.
                                  Its route_id and input.route must exactly match
                                  route_body.route — see
                                  proposal_serialize.validate_route_evaluation_sync)

    A proposal can be saved without evaluation_body — its financial
    fields are simply null until a version with one is saved.

    Response (201):
      {
        "action": "created" | "versioned" | "branched",
        "proposal": {proposal_id, proposal_version, is_current, user_id,
                     user_name, change_log, created_at},
        "route_id": "P{proposal_id}_V{proposal_version}_R1"
      }
    All draft IDs in the posted route (route_id, trip_ids, geometry_ids, ...)
    are rewritten to the real proposal_id/version — the returned route_id is
    the one to use from here on.
    """
    body = request.get_json(silent=True)
    if not body:
        return (
            jsonify({"error": "bad_request", "message": "Request body must be JSON."}),
            400,
        )

    errors = validate_save_body(body)
    if errors:
        return jsonify({"error": "validation_error", "details": errors}), 400

    repo = get_proposal_repository()

    user = repo.get_user(body["user_id"])
    if user is None:
        return (
            jsonify(
                {
                    "error": "domain_error",
                    "message": f"user_id {body['user_id']} does not exist.",
                }
            ),
            422,
        )

    try:
        record = repo.save(
            route_body=body["route_body"],
            user_id=body["user_id"],
            change_log=body.get("change_log"),
            evaluation_body=body.get("evaluation_body"),
        )
    except ValueError as e:
        logger.warning("proposal save failed (domain error): %s", e)
        return jsonify({"error": "domain_error", "message": str(e)}), 422
    except Exception as e:
        logger.exception("proposal save failed (unexpected): %s", e)
        return jsonify({"error": "proposal_error", "message": str(e)}), 500

    return (
        jsonify(
            {
                "action": record["action"],
                "proposal": proposal_meta_to_dict({**record, **user}),
                "route_id": record["route_id"],
            }
        ),
        201,
    )


@bp.get("/proposals")
def list_proposals():
    """All current proposal versions, newest first, as summaries — same
    shape as POST /api/proposals with an empty body."""
    return _list_response(filters={}, sort=[], limit=None, offset=0)


@bp.post("/proposals")
def filter_proposals():
    """
    Filtered/sorted/paginated proposal list.

    Request body (all fields optional):
      {
        "filter": {
          "user_ids":  [int, ...],   proposals whose current version was saved by any of these users
          "countries": [str, ...],   routes touching any of these country codes (incl. transit-only)
          "stop_ids":  [str, ...]    routes serving any of these stops
        },
        "sort":   [{"by": "created_at" | "total_distance_km" | "total_time_h" |
                          "total_revenue_eur" | "total_cost_eur" | "margin_eur",
                    "dir": "asc" | "desc"}, ...],
        "limit":  int (default 50),
        "offset": int (default 0)
      }

    Response: {"total": <count after filtering>, "proposals": [<summary>, ...]}
    Each summary carries metadata, route metrics (name, total_distance_km,
    total_driving_time_h, total_time_h, countries, stops), and financial
    metrics (total_revenue_eur, total_cost_eur, margin_eur, margin_per) —
    the latter null unless the proposal was saved with an evaluation
    snapshot. Proposals without one sort as if their financial fields were
    zero rather than being excluded from a financial sort.
    """
    body = request.get_json(silent=True) or {}
    errors = validate_list_body(body)
    if errors:
        return jsonify({"error": "validation_error", "details": errors}), 400

    return _list_response(
        filters=body.get("filter", {}),
        sort=body.get("sort", []),
        limit=body.get("limit", _DEFAULT_LIMIT),
        offset=body.get("offset", 0),
    )


@bp.get("/proposal/<int:proposal_id>")
def get_proposal(proposal_id: int):
    """
    Load the current version of a proposal.

    Response returns the two stored envelopes directly — the exact
    payloads that were originally posted to POST /api/route/plan and
    POST /api/evaluation/calc (after draft-ID rewriting), unchanged:
      {
        "proposal": {proposal_id, proposal_version, ...},
        "route_body": {route_builder_version, request, route},
        "evaluation_body": {calc_version, route_id, models, input, views} | null
      }
    `evaluation_body` is null if the proposal was saved without one.
    """
    record = get_proposal_repository().get_current(proposal_id)
    if record is None:
        return (
            jsonify(
                {
                    "error": "not_found",
                    "message": f"No proposal with proposal_id {proposal_id}.",
                }
            ),
            404,
        )

    return (
        jsonify(
            {
                "proposal": proposal_meta_to_dict(record),
                "route_body": record["route_body"],
                "evaluation_body": record["evaluation_body"],
            }
        ),
        200,
    )


# =============================================================================
# List assembly — shared by GET and POST /api/proposals
# =============================================================================


def _list_response(filters: dict, sort: list, limit: int | None, offset: int):
    """Build summaries from the repository, apply content filters and
    sorting in Python (row volumes are small — dozens, not thousands), and
    paginate. user_ids is the one filter pushed down to SQL."""
    rows = get_proposal_repository().list_current(user_ids=filters.get("user_ids"))
    summaries = [proposal_summary_to_dict(row) for row in rows]

    countries = set(filters.get("countries") or [])
    if countries:
        summaries = [s for s in summaries if countries & set(s["countries"])]
    stop_ids = set(filters.get("stop_ids") or [])
    if stop_ids:
        summaries = [
            s for s in summaries if stop_ids & {stop["stop_id"] for stop in s["stops"]}
        ]

    # Multi-key sort: apply keys in reverse so the first entry wins overall —
    # Python's sort is stable. Default order (created_at DESC) comes from SQL.
    # Financial fields are null for proposals saved without an evaluation;
    # they sort as if 0 rather than raising or being excluded.
    for entry in reversed(sort):
        by = entry["by"]
        summaries.sort(
            key=lambda s: s[by] or 0, reverse=entry.get("dir", "asc") == "desc"
        )

    total = len(summaries)
    if limit is not None:
        summaries = summaries[offset : offset + limit]

    return jsonify({"total": total, "proposals": summaries}), 200
