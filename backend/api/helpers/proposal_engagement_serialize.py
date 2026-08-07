"""
proposal_engagement_serialize.py
=================================
Validation and dict-shaping for the proposal engagement endpoints —
mirrors the existing feedback_serialize.py / proposal_serialize.py split:
all body validation and response shaping lives here, none of it in
api/proposal_engagement.py or the repository.

WP11 rewrite: the two read endpoints (likes, comments) collapsed into one
aggregate — engagement_to_dict() shapes the whole GET response, including
the merged timeline (§7.5). comment_to_dict() lost `is_deleted`: a
soft-deleted comment is no longer returned anywhere, so the flag was
always false on every row that reached a client.

Public interface:
  validate_comment_body(body)   → list[str]
  comment_to_dict(row)          → dict
  likes_to_dict(summary)        → dict
  engagement_to_dict(pid, e)    → dict
"""

from __future__ import annotations

from api import config


def validate_comment_body(body: dict) -> list[str]:
    """Structural validation of a POST/PATCH comment payload — just the
    one required field, kept as its own module-level check rather than
    inlined in the blueprint for the same reason as the other endpoints
    (see feedback_serialize.validate_feedback_body)."""
    errors = []

    text = body.get("body")
    if not isinstance(text, str) or not text.strip():
        errors.append("'body' is required and must be a non-empty string.")
    elif len(text) > config.COMMENT_BODY_MAX_LEN:
        errors.append(
            f"'body' must be at most {config.COMMENT_BODY_MAX_LEN} characters."
        )

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
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }


def likes_to_dict(summary: dict) -> dict:
    """{count, liked_by_me} passed straight through — kept as a function
    (rather than inlined) so the response shape has one place to change."""
    return {"count": summary["count"], "liked_by_me": summary["liked_by_me"]}


def engagement_to_dict(proposal_id: int, engagement: dict) -> dict:
    """The full GET /api/proposal/<id>/engagements body: like summary,
    live comment thread with its own count, and the merged timeline."""
    return {
        "proposal_id": proposal_id,
        "likes": likes_to_dict(engagement["likes"]),
        "comments": {
            "count": engagement["comments"]["count"],
            "items": [comment_to_dict(row) for row in engagement["comments"]["items"]],
        },
        "timeline": [timeline_event_to_dict(row) for row in engagement["timeline"]],
    }


def timeline_event_to_dict(row: dict) -> dict:
    """One merged timeline row → API shape. `detail` is the event's own
    context, passed through as stored (update_log's JSONB, or the
    comment_id/edited pair the timeline query builds) — see §4.1 for the
    per-event contents."""
    return {
        "event": row["event"],
        "at": row["occurred_at"].isoformat(),
        "proposal_version": row["proposal_version"],
        "actor": _actor(row),
        "detail": row["detail"],
    }


def _actor(row: dict) -> dict | None:
    """Who acted. A null actor means the SYSTEM acted — a version-bump or
    base-scenario refresh (§4.2), which only update_log rows can be. A
    null user_id on an engagement row means something else entirely (the
    account was deleted), so it keeps the placeholder the comment thread
    uses rather than being mistaken for a system event."""
    if row["user_id"] is not None:
        return {"user_id": row["user_id"], "user_name": row["user_name"]}
    if row["source"] == "update_log":
        return None
    return {"user_id": None, "user_name": "[deleted]"}
