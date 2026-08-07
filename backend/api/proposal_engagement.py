"""
proposal_engagement.py
=======================
Engagement on published proposals — likes, comments, and the merged
event timeline.

  GET    /api/proposal/<id>/engagements     — likes + comments + timeline
  POST   /api/proposal/<id>/like            — like (idempotent)
  DELETE /api/proposal/<id>/like            — unlike (idempotent)
  POST   /api/proposal/<id>/comment         — add a comment
  PATCH  /api/proposal/<id>/comment/<cid>   — edit own comment
  DELETE /api/proposal/<id>/comment/<cid>   — soft-delete own comment

One read endpoint, five writes (WP11). The GET is open, same as proposal
loading (api/proposals.py); every write needs @require_auth at the
TRUST_GUEST floor — the same bar POST /api/proposal/publish already
clears for a guest to publish a proposal. Writes are additionally rate
limited per authenticated user (api/config.py holds the numbers,
api/auth_middleware.py the per-user bucket key).

Every resource keys on proposal_id (a soft reference, see
adapters/proposal/engagement_repository.py) rather than a specific
proposal_version, so a like or a discussion survives the proposal being
overwritten or refreshed into a new state.

The timeline merges update_log, likes and comments (§7.5). It is a
projection of current state, not an audit trail: withdrawn likes and
deleted comments disappear from it, and an edited comment moves to its
edit time. Only update_log is genuinely append-only, which is what makes
"commented on state 3, route overwritten afterwards, then recalculated on
a new calc version" reconstructible at all (§4.1).

Gallery rows carry `likes_count` and `comments_count` (POST /api/proposals)
so a list view never needs one call per row; the bodies and the timeline
live here.
"""

import logging

from flask import Blueprint, g, jsonify, request

from api import config
from api.auth_middleware import optional_auth, rate_limit_key, require_auth
from api.helpers.dependencies import get_proposal_engagement_repository
from api.helpers.proposal_engagement_serialize import (
    comment_to_dict,
    engagement_to_dict,
    likes_to_dict,
    validate_comment_body,
)
from api.limiter import limiter

logger = logging.getLogger(__name__)
bp = Blueprint("proposal_engagement", __name__)


def _not_found(proposal_id: int):
    return (
        jsonify(
            {
                "error": "not_found",
                "message": f"No proposal with proposal_id {proposal_id}.",
            }
        ),
        404,
    )


# =============================================================================
# Aggregate read
# =============================================================================


@bp.get("/proposal/<int:proposal_id>/engagements")
@optional_auth
def get_engagements(proposal_id: int):
    """Likes, comments and the event timeline for one proposal.
    liked_by_me is always False for an unauthenticated caller."""
    engagement = get_proposal_engagement_repository().get_engagement(
        proposal_id, g.user_id
    )
    if engagement is None:
        return _not_found(proposal_id)
    return jsonify(engagement_to_dict(proposal_id, engagement)), 200


# =============================================================================
# Likes
# =============================================================================


@bp.post("/proposal/<int:proposal_id>/like")
@limiter.limit(config.LIKE_RATE_LIMIT, key_func=rate_limit_key)
@require_auth
def add_like(proposal_id: int):
    """Like a proposal. Idempotent — liking twice is a no-op, not an
    error. 404 if proposal_id doesn't exist."""
    result = get_proposal_engagement_repository().add_like(proposal_id, g.user_id)
    if result is None:
        return _not_found(proposal_id)
    return jsonify(likes_to_dict(result)), 200


@bp.delete("/proposal/<int:proposal_id>/like")
@limiter.limit(config.LIKE_RATE_LIMIT, key_func=rate_limit_key)
@require_auth
def remove_like(proposal_id: int):
    """Unlike a proposal. Idempotent — unliking when no like exists is a
    no-op, not an error."""
    repo = get_proposal_engagement_repository()
    if not repo.proposal_exists(proposal_id):
        return _not_found(proposal_id)
    return jsonify(likes_to_dict(repo.remove_like(proposal_id, g.user_id))), 200


# =============================================================================
# Comments
# =============================================================================


@bp.post("/proposal/<int:proposal_id>/comment")
@limiter.limit(config.COMMENT_RATE_LIMIT, key_func=rate_limit_key)
@require_auth
def add_comment(proposal_id: int):
    """Add a comment. Request body: {"body": str}, length-capped by
    config.COMMENT_BODY_MAX_LEN."""
    body = request.get_json(silent=True) or {}
    errors = validate_comment_body(body)
    if errors:
        return jsonify({"error": "validation_error", "details": errors}), 400

    row = get_proposal_engagement_repository().add_comment(
        proposal_id, g.user_id, body["body"].strip()
    )
    if row is None:
        return _not_found(proposal_id)
    return jsonify(comment_to_dict(row)), 201


@bp.patch("/proposal/<int:proposal_id>/comment/<int:comment_id>")
@limiter.limit(config.COMMENT_EDIT_RATE_LIMIT, key_func=rate_limit_key)
@require_auth
def edit_comment(proposal_id: int, comment_id: int):
    """Edit a comment. Author-only — 403 for anyone else, 404 if the
    comment doesn't exist (under this proposal_id) or was deleted. The
    comment's timeline event moves to the edit time."""
    body = request.get_json(silent=True) or {}
    errors = validate_comment_body(body)
    if errors:
        return jsonify({"error": "validation_error", "details": errors}), 400

    repo = get_proposal_engagement_repository()
    existing = repo.get_comment(comment_id)
    error_response = _authorize_comment(existing, proposal_id, comment_id)
    if error_response:
        return error_response

    row = repo.edit_comment(comment_id, body["body"].strip())
    return jsonify(comment_to_dict(row)), 200


@bp.delete("/proposal/<int:proposal_id>/comment/<int:comment_id>")
@limiter.limit(config.COMMENT_EDIT_RATE_LIMIT, key_func=rate_limit_key)
@require_auth
def delete_comment(proposal_id: int, comment_id: int):
    """Delete a comment. Author-only — see edit_comment above. Stored as
    a soft delete (stable comment_id) but invisible from here on: the
    comment leaves both the thread and the timeline."""
    repo = get_proposal_engagement_repository()
    existing = repo.get_comment(comment_id)
    error_response = _authorize_comment(existing, proposal_id, comment_id)
    if error_response:
        return error_response

    repo.delete_comment(comment_id)
    return "", 204


def _authorize_comment(existing: dict | None, proposal_id: int, comment_id: int):
    """Shared 404/403 checks for edit/delete. Returns a Flask response
    tuple on failure, or None to proceed."""
    if (
        existing is None
        or existing["proposal_id"] != proposal_id
        or existing["is_deleted"]
    ):
        return (
            jsonify(
                {
                    "error": "not_found",
                    "message": f"No comment {comment_id} on proposal {proposal_id}.",
                }
            ),
            404,
        )
    if existing["user_id"] != g.user_id:
        return (
            jsonify(
                {
                    "error": "forbidden",
                    "message": "You can only edit or delete your own comments.",
                }
            ),
            403,
        )
    return None
