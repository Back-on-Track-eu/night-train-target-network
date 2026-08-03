"""
proposal_engagement.py
=======================
Rating (thumbs-up "like") and commenting on saved proposals.

  GET    /api/proposal/<id>/likes           — like count + whether the
                                               caller has liked it
  POST   /api/proposal/<id>/likes           — like (idempotent)
  DELETE /api/proposal/<id>/likes           — unlike (idempotent)

  GET    /api/proposal/<id>/comments        — flat comment thread, oldest first
  POST   /api/proposal/<id>/comments        — add a comment
  PATCH  /api/proposal/<id>/comments/<cid>  — edit own comment
  DELETE /api/proposal/<id>/comments/<cid>  — soft-delete own comment

GETs are open, same as proposal loading (api/proposals.py). Writes need
@require_auth at the TRUST_GUEST floor — the same bar POST /api/proposal/
publish already clears for a guest to publish a proposal. Both resources
key on proposal_id (a soft reference, see
adapters/proposal/engagement_repository.py)
rather than a specific proposal_version, so a like or a discussion survives
the proposal being edited into a new version.
"""

import logging

from flask import Blueprint, g, jsonify, request

from api.auth_middleware import optional_auth, require_auth
from api.helpers.dependencies import get_proposal_engagement_repository
from api.helpers.proposal_engagement_serialize import (
    comment_to_dict,
    likes_to_dict,
    validate_comment_body,
)

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
# Likes
# =============================================================================


@bp.get("/proposal/<int:proposal_id>/likes")
@optional_auth
def get_likes(proposal_id: int):
    """Like count and whether the caller has liked this proposal.
    liked_by_me is always False for an unauthenticated caller."""
    repo = get_proposal_engagement_repository()
    if not repo.proposal_exists(proposal_id):
        return _not_found(proposal_id)
    return jsonify(likes_to_dict(repo.get_likes(proposal_id, g.user_id))), 200


@bp.post("/proposal/<int:proposal_id>/likes")
@require_auth
def add_like(proposal_id: int):
    """Like a proposal. Idempotent — liking twice is a no-op, not an
    error. 404 if proposal_id doesn't exist."""
    result = get_proposal_engagement_repository().add_like(proposal_id, g.user_id)
    if result is None:
        return _not_found(proposal_id)
    return jsonify(likes_to_dict(result)), 200


@bp.delete("/proposal/<int:proposal_id>/likes")
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


@bp.get("/proposal/<int:proposal_id>/comments")
def list_comments(proposal_id: int):
    """Flat comment thread, oldest first. Includes soft-deleted comments
    (body already cleared in storage) so the thread stays chronologically
    intact — see create_proposal_schema.sql."""
    repo = get_proposal_engagement_repository()
    if not repo.proposal_exists(proposal_id):
        return _not_found(proposal_id)
    comments = [comment_to_dict(row) for row in repo.list_comments(proposal_id)]
    return jsonify({"proposal_id": proposal_id, "comments": comments}), 200


@bp.post("/proposal/<int:proposal_id>/comments")
@require_auth
def add_comment(proposal_id: int):
    """Add a comment. Request body: {\"body\": str, max 4000 chars}."""
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


@bp.patch("/proposal/<int:proposal_id>/comments/<int:comment_id>")
@require_auth
def edit_comment(proposal_id: int, comment_id: int):
    """Edit a comment. Author-only — 403 for anyone else, 404 if the
    comment doesn't exist (under this proposal_id) or was soft-deleted."""
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


@bp.delete("/proposal/<int:proposal_id>/comments/<int:comment_id>")
@require_auth
def delete_comment(proposal_id: int, comment_id: int):
    """Soft-delete a comment. Author-only — see edit_comment above."""
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
