"""
auth_middleware.py
==================
Flask decorators for JWT authentication.

  @require_auth    — endpoint requires a valid JWT; returns 401 otherwise
  @optional_auth   — endpoint works with or without a JWT;
                     sets g.user_id etc. when token is present

Usage
-----
    from api.auth_middleware import require_auth, optional_auth

    @bp.get("/api/scenarios")
    @require_auth
    def list_scenarios():
        user_id = g.user_id          # always set
        is_guest = g.is_guest        # True for guest tokens

    @bp.post("/api/route/planOrUpdate")
    @optional_auth
    def plan_route():
        if g.user_id:                # None when no token provided
            ...

Flask g context set by both decorators
---------------------------------------
    g.user_id      : int | None
    g.email        : str | None
    g.display_name : str | None
    g.is_guest     : bool
"""

from __future__ import annotations

import logging
from functools import wraps

from flask import g, jsonify, request

from api.auth_utils import AuthError, decode_jwt

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal: extract and decode token from request
# ---------------------------------------------------------------------------

def _load_user_from_request() -> dict | None:
    """
    Read the Authorization header, decode the JWT, return the payload.
    Returns None if no token is present.
    Raises AuthError if a token is present but invalid.

    Expected header format:
        Authorization: Bearer <token>
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header:
        return None

    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise AuthError(
            "Invalid Authorization header format. Expected: Bearer <token>"
        )

    return decode_jwt(parts[1])


def _set_g_from_payload(payload: dict) -> None:
    """Populate Flask g from a decoded JWT payload."""
    g.user_id      = int(payload["sub"])
    g.email        = payload.get("email")
    g.display_name = payload.get("display_name")
    g.is_guest     = bool(payload.get("is_guest", False))


def _clear_g() -> None:
    """Set all auth-related g values to their unauthenticated defaults."""
    g.user_id      = None
    g.email        = None
    g.display_name = None
    g.is_guest     = False


# ---------------------------------------------------------------------------
# @require_auth
# ---------------------------------------------------------------------------

def require_auth(f):
    """
    Decorator: endpoint requires a valid JWT.

    Sets g.user_id, g.email, g.display_name, g.is_guest on success.
    Returns 401 if token is missing, invalid, or expired.

    Works for both registered users and guests — the endpoint decides
    whether to allow guest access by checking g.is_guest if needed.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        try:
            payload = _load_user_from_request()
        except AuthError as e:
            return jsonify({"error": "unauthorized", "message": str(e)}), 401

        if payload is None:
            return jsonify({
                "error":   "unauthorized",
                "message": "Authentication required. Please log in.",
            }), 401

        _set_g_from_payload(payload)
        return f(*args, **kwargs)

    return decorated


# ---------------------------------------------------------------------------
# @optional_auth
# ---------------------------------------------------------------------------

def optional_auth(f):
    """
    Decorator: endpoint works with or without authentication.

    If a valid token is present, sets g.user_id etc. as normal.
    If no token is present, sets g.user_id = None (unauthenticated).
    If a token is present but invalid, returns 401 — a bad token is
    treated as an error, not silently ignored.

    Use this on endpoints that have richer behaviour when logged in
    but still work for anonymous users (e.g. route planning).
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        _clear_g()
        try:
            payload = _load_user_from_request()
        except AuthError as e:
            return jsonify({"error": "unauthorized", "message": str(e)}), 401

        if payload is not None:
            _set_g_from_payload(payload)

        return f(*args, **kwargs)

    return decorated