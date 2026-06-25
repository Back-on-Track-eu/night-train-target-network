"""
auth.py
=======
Authentication endpoints — OTP / magic-link JWT.

  POST /api/auth/request-code  — send OTP to email
  POST /api/auth/verify        — verify OTP, return JWT

⚠️  NOT YET IMPLEMENTED — Phase 5.
All endpoints return 501 Not Implemented.
"""

from flask import Blueprint, jsonify

bp = Blueprint("auth", __name__)


@bp.post("/request-code")
def request_code():
    return jsonify({"error": "not_implemented", "message": "Auth not yet implemented."}), 501


@bp.post("/verify")
def verify():
    return jsonify({"error": "not_implemented", "message": "Auth not yet implemented."}), 501