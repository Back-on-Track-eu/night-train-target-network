"""
feedback.py
===========
Parameter feedback endpoint.

  POST /api/feedback — submit feedback on a model parameter

⚠️  NOT YET IMPLEMENTED — Phase 4.
Returns 501 Not Implemented.
"""

from flask import Blueprint, jsonify

bp = Blueprint("feedback", __name__)


@bp.post("/feedback")
def submit_feedback():
    return (
        jsonify(
            {"error": "not_implemented", "message": "Feedback not yet implemented."}
        ),
        501,
    )
