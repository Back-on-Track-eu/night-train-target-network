"""
proposal_engagement_serialize.py
=================================
Validation and dict-shaping for the proposal likes/comments endpoints —
mirrors the existing feedback_serialize.py / proposal_serialize.py split:
all body validation and response shaping lives here, none of it in
api/proposal_engagement.py or the repository.

Public interface:
  validate_comment_body(body)   → list[str]
  comment_to_dict(row)          → dict
  likes_to_dict(summary)        → dict
"""

from __future__ import annotations

_COMMENT_BODY_MAX_LEN = 4000


def validate_comment_body(body: dict) -> list[str]:
    """Structural validation of a POST/PATCH comment payload — just the
    one required field, kept as its own module-level check rather than
    inlined in the blueprint for the same reason as the other endpoints
    (see feedback_serialize.validate_feedback_body)."""
    errors = []

    text = body.get("body")
    if not isinstance(text, str) or not text.strip():
        errors.append("'body' is required and must be a non-empty string.")
    elif len(text) > _COMMENT_BODY_MAX_LEN:
        errors.append(f"'body' must be at most {_COMMENT_BODY_MAX_LEN} characters.")

    return errors


def comment_to_dict(row: dict) -> dict:
    """One comment row → API shape. A null user_id (account deleted, see
    create_proposal_schema.sql) renders as a deleted-user placeholder
    rather than omitting the field."""
    return {
        "comment_id": row["comment_id"],
        "proposal_id": row["proposal_id"],
        "proposal_version": row["proposal_version"],
        "user_id": row["user_id"],
        "user_name": row["user_name"] if row["user_id"] is not None else "[deleted]",
        "body": row["body"],
        "is_deleted": row["is_deleted"],
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }


def likes_to_dict(summary: dict) -> dict:
    """{count, liked_by_me} passed straight through — kept as a function
    (rather than inlined) so the response shape has one place to change."""
    return {"count": summary["count"], "liked_by_me": summary["liked_by_me"]}
