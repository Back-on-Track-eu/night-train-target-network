"""
feedback.py
===========
Feedback endpoints.

  POST /api/feedback             — submit feedback; mails the working
                                    group and stores the submission
  GET  /api/feedback/categories  — suggested category/sub_category values
                                    for the feedback form

Response dict-building and validation for both endpoints lives in
api/helpers/feedback_serialize.py — see its module docstring. Mail
delivery is handled by adapters/mailer.py; storage by
adapters/feedback_repository.py.
"""

import logging

from flask import Blueprint, jsonify, request

from adapters import mailer
from api.helpers.dependencies import get_feedback_repository, get_loader
from api.helpers.feedback_serialize import (
    build_categories_payload,
    feedback_response_to_dict,
    validate_feedback_body,
)

logger = logging.getLogger(__name__)
bp = Blueprint("feedback", __name__)


@bp.post("/feedback")
def submit_feedback():
    """
    Submit feedback. Sends a notification mail to
    targetnetwork-wg@back-on-track.eu and stores the submission in
    admin.feedback either way — mail delivery is best-effort on top of
    storage, not a precondition for it (see feedback_repository.py).

    Request body:
      user_id      : int    (required unless 'email' is given — a logged-in
                              submitter's admin.users identity)
      email        : str    (required unless 'user_id' is given — reply-to
                              address for an anonymous submitter)
      subject      : str    (required, max 200 chars)
      category     : str    (required — see GET /api/feedback/categories
                              for suggested values; not a closed enum)
      sub_category : str    (required — see GET /api/feedback/categories,
                              e.g. a field name for 'Infrastructure')
      message      : str    (required — the feedback text)

    Response (201):
      {"feedback_id": int, "created_at": <ISO8601>, "email_sent": bool}
    email_sent reflects only whether the notification mail succeeded —
    the feedback is stored regardless (see module docstring).
    """
    body = request.get_json(silent=True)
    if not body:
        return (
            jsonify({"error": "bad_request", "message": "Request body must be JSON."}),
            400,
        )

    errors = validate_feedback_body(body)
    if errors:
        return jsonify({"error": "validation_error", "details": errors}), 400

    repo = get_feedback_repository()

    user_id = body.get("user_id")
    email = body.get("email")
    author_name = None
    if user_id is not None:
        user = repo.get_user(user_id)
        if user is None:
            return (
                jsonify(
                    {
                        "error": "domain_error",
                        "message": f"user_id {user_id} does not exist.",
                    }
                ),
                422,
            )
        author_name = user["user_name"]
        email = user["email"]  # used as mail Reply-To only, not stored twice

    try:
        record = repo.insert(
            user_id=user_id,
            email=body.get("email") if user_id is None else None,
            subject=body["subject"],
            message=body["message"],
            category=body["category"],
            sub_category=body["sub_category"],
        )
    except Exception as e:
        logger.exception("feedback insert failed: %s", e)
        return jsonify({"error": "feedback_error", "message": str(e)}), 500

    email_sent = mailer.send_feedback_email(
        feedback_id=record["feedback_id"],
        subject=body["subject"],
        message=body["message"],
        category=body["category"],
        sub_category=body["sub_category"],
        author_email=email,
        author_name=author_name,
    )
    if email_sent:
        repo.mark_notified(record["feedback_id"])

    return jsonify(feedback_response_to_dict(record, email_sent)), 201


@bp.get("/feedback/categories")
def list_feedback_categories():
    """
    Suggested category/sub_category values for the feedback form. See
    feedback_serialize.build_categories_payload() for the response
    layout and the full nine-category taxonomy — Infrastructure and
    Compositions each carry a live parameter-field list, "Evaluation —
    calculation method" and "Evaluation — results / view" are each
    derived from the evaluation model's own definitions, and the rest
    are static or free-text.

    Query params:
      scenario_id : int (optional) — pins the parameter versions the
                    Infrastructure/Compositions sub-category lists are
                    built from; omit for the live is_current_base scenario.
    """
    loader = get_loader()
    scenario_id = request.args.get("scenario_id", type=int)
    return jsonify(build_categories_payload(loader, scenario_id)), 200
