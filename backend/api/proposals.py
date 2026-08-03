"""
proposals.py
============
Proposal listing and loading (PROPOSALS_DESIGN.md §7.1/§7.2, WP5-minimal
— the full gallery/map filter contract is WP6, the on-load version-
refresh fallback is WP7/WP8).

  GET  /api/proposals       — list, no filters
  POST /api/proposals       — list with the one WP5 filter (user_ids) + pagination
  GET  /api/proposal/<id>   — load one proposal, reconstructed from GTFS + summary

There is no save endpoint here — POST /api/proposal/publish
(api/proposal_publish.py) is the only write path (§2.2). Every user can
see and load every proposal; loading is unauthenticated (GETs are open,
same policy as api/proposal_engagement.py's GETs).
"""

import logging

from flask import Blueprint, jsonify, request

from api.helpers.dependencies import get_loader, get_proposal_repository
from api.helpers.proposal_serialize import (
    proposal_to_response_dict,
    summary_row_to_dict,
    validate_list_body,
)

logger = logging.getLogger(__name__)
bp = Blueprint("proposals", __name__)

_DEFAULT_LIMIT = 50


@bp.get("/proposals")
def list_proposals():
    """All proposals, most recently updated first, as summaries — same
    shape as POST /api/proposals with an empty body."""
    return _list_response(user_ids=None, limit=None, offset=0)


@bp.post("/proposals")
def filter_proposals():
    """
    List proposals — WP5-minimal: one filter (user_ids) + pagination.
    The full §7.1 contract (range/list/substring filters over every
    summary column, map sections, trip_windows) is WP6.

    Request body (all fields optional):
      {
        "filter": {"user_ids": [int, ...]},   // e.g. "my proposals"
        "limit":  int (default 50),
        "offset": int
      }

    Response: {"total": <count before pagination>, "proposals": [<summary>, ...]}
    """
    body = request.get_json(silent=True) or {}
    errors = validate_list_body(body)
    if errors:
        return jsonify({"error": "validation_error", "details": errors}), 400

    return _list_response(
        user_ids=body.get("filter", {}).get("user_ids"),
        limit=body.get("limit", _DEFAULT_LIMIT),
        offset=body.get("offset", 0),
    )


@bp.get("/proposal/<int:proposal_id>")
def get_proposal(proposal_id: int):
    """
    Load a proposal — reconstructed compute-response shape (§2.1) plus
    proposal metadata (§7.2). Route/evaluation are rebuilt from storage
    (GTFS + sidecars, evaluation_output + the scenario pin) rather than
    read back verbatim — see adapters/proposal_repository.py's
    reconstruct_route()/reconstruct_evaluation() and
    api/helpers/route_gtfs_serialize.py for what "rebuilt" means for each
    section.

    Response: identical shape to POST /api/proposal/publish's response
    (api/helpers/proposal_serialize.py's proposal_to_response_dict()).
    """
    repo = get_proposal_repository()
    container = repo.get_container(proposal_id)
    if container is None:
        return (
            jsonify(
                {
                    "error": "not_found",
                    "message": f"No proposal with proposal_id {proposal_id}.",
                }
            ),
            404,
        )

    loader = get_loader()
    route = repo.reconstruct_route(
        proposal_id, container["proposal_version"], container["scenario_id"], loader
    )
    evaluation = repo.reconstruct_evaluation(container, loader)

    payload = proposal_to_response_dict(container, route=route, evaluation=evaluation)
    return jsonify(payload), 200


# =============================================================================
# List assembly — shared by GET and POST /api/proposals
# =============================================================================


def _list_response(user_ids: list | None, limit: int | None, offset: int):
    rows, total = get_proposal_repository().list_summaries(
        user_ids=user_ids, limit=limit, offset=offset
    )
    summaries = [summary_row_to_dict(row) for row in rows]
    return jsonify({"total": total, "proposals": summaries}), 200
