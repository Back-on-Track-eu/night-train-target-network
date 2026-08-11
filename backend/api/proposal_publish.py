"""
proposal_publish.py
====================
POST /api/proposal/publish

The only user write path for proposals (adapters/proposal/README.md §2.2).
Thin view: validate the envelope, delegate to
api/helpers/publish_dispatch.py, shape the result via
api/helpers/proposal_serialize.py, return it in the same shape
GET /api/proposal/<id> (api/proposals.py) does.

@require_auth: guests included (a guest JWT still resolves g.user_id) —
the same trust floor the old persist-on-calc endpoints used. The acting
user is never read from the request body (§2.2, locked decision 5) — only
from g.user_id, set by the auth layer.
"""

import logging

from flask import Blueprint, g, jsonify, request

from adapters.proposal.repository import ProposalForbiddenError, ProposalNotFoundError
from api.auth_middleware import require_auth
from api.helpers.dependencies import get_proposal_engagement_repository
from api.helpers.proposal_serialize import proposal_to_response_dict
from api.helpers.publish_dispatch import (
    ScenarioNotBaseError,
    dispatch_publish,
    validate_publish_body,
)

logger = logging.getLogger(__name__)
bp = Blueprint("proposal_publish", __name__)


@bp.post("/publish")
@require_auth
def publish():
    """
    Publish a computed proposal — see adapters/proposal/README.md §2.2 for the
    full request/response contract.

    Request body:
      {
        "compute_request": { ... },       // the exact resolved request of §2.1
        "name": "Berlin–Roma via Brenner",
        "mode": "new" | "overwrite",
        "proposal_id": 123,                // overwrite only
        "based_on_proposal_id": 456        // optional, informational only
      }

    Response: the published proposal in full — see GET /api/proposal/<id>
    (api/proposals.py) for the exact shape; both return the identical
    structure by construction (api/helpers/proposal_serialize.py's
    proposal_to_response_dict()).
    """
    body = request.get_json(silent=True)
    if not body:
        return (
            jsonify({"error": "bad_request", "message": "Request body must be JSON."}),
            400,
        )

    errors = validate_publish_body(body)
    if errors:
        logger.warning("proposal/publish validation failed — %s", errors)
        return jsonify({"error": "validation_error", "details": errors}), 400

    try:
        record = dispatch_publish(body, user_id=g.user_id)
    except ScenarioNotBaseError as e:
        requested, current_base = e.args
        logger.warning(
            "proposal/publish rejected: scenario_id=%s is not current base (%s)",
            requested,
            current_base,
        )
        return (
            jsonify(
                {
                    "error": "scenario_not_base",
                    "message": (
                        f"compute_request.scenario_id ({requested}) is not the "
                        f"current base scenario ({current_base}). Published "
                        "proposals are always evaluated on the current base — "
                        "recompute without a scenario_id override, or omit it, "
                        "before publishing."
                    ),
                }
            ),
            422,
        )
    except ProposalNotFoundError as e:
        return (
            jsonify(
                {
                    "error": "not_found",
                    "message": f"No proposal with proposal_id {e.args[0]}.",
                }
            ),
            404,
        )
    except ProposalForbiddenError as e:
        return (
            jsonify(
                {
                    "error": "forbidden",
                    "message": f"proposal_id {e.args[0]} is not owned by the calling user.",
                }
            ),
            403,
        )
    except ValueError as e:
        logger.warning("proposal/publish failed (domain error): %s", e)
        return jsonify({"error": "domain_error", "message": str(e)}), 422
    except Exception as e:
        logger.exception("proposal/publish failed (unexpected): %s", e)
        return jsonify({"error": "publish_error", "message": str(e)}), 500

    if not g.is_guest:
        # Self-like on publish — logged-in only, best-effort: the proposal
        # is already committed at this point, so a like failure must not
        # turn into a publish failure.
        try:
            get_proposal_engagement_repository().add_like(
                record["proposal_id"], g.user_id
            )
        except Exception:
            logger.exception(
                "proposal/publish: self-like failed for proposal_id=%s",
                record["proposal_id"],
            )

    payload = proposal_to_response_dict(
        record, route=record["route"], evaluation=record["evaluation"]
    )
    return jsonify(payload), 200
