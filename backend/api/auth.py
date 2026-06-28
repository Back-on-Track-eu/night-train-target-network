"""
auth.py
=======
Authentication endpoints — OTP login and guest session creation.

  POST /api/auth/request-code   — register or log in: send OTP to email
  POST /api/auth/verify         — verify OTP, return JWT
  POST /api/auth/guest          — create a guest session, return JWT

Flow
----
  Registration + login are the same endpoint (request-code).
  If the email is new, a user row is created (unverified).
  If it already exists, the existing user is used.
  Either way an OTP is issued and emailed.

  On verify, the OTP is checked, the user is marked verified,
  and a JWT is returned.

  Guest flow is separate: POST /api/auth/guest creates an anonymous
  user row and returns a guest JWT immediately (no email needed).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from flask import Blueprint, g, jsonify, request

from api.auth_utils import (
    AuthError,
    GUEST_PREFIX,
    create_jwt,
    generate_guest_name,
    generate_otp,
    hash_otp,
    validate_display_name,
    verify_otp,
)
from api.dependencies import get_db
from api.email_sender import EmailError, send_otp_email
from api.limiter import limiter

logger = logging.getLogger(__name__)

bp = Blueprint("auth", __name__)

# OTP expires after 15 minutes
_OTP_TTL_MINUTES = 15

# Max guest name generation attempts before giving up
_MAX_GUEST_NAME_ATTEMPTS = 10


# ---------------------------------------------------------------------------
# POST /api/auth/request-code
# ---------------------------------------------------------------------------

@bp.post("/request-code")
@limiter.limit("5 per hour")
def request_code():
    """
    Register a new user or log in an existing one.

    Request body
    ------------
    {
        "email":        "user@example.com",   -- required
        "display_name": "railfan42"           -- required on first call only;
    }                                            ignored if user already exists

    Response
    --------
    200  {}                          -- always; no info leaked about existence
    400  {"error": "bad_request"}    -- missing/invalid fields
    502  {"error": "email_failed"}   -- OTP email could not be sent

    Security
    --------
    Always returns 200 whether the email exists or not (no user enumeration).
    Old unused OTPs for this user are invalidated before issuing a new one.
    """
    body = request.get_json(silent=True) or {}

    email        = (body.get("email") or "").strip().lower()
    display_name = (body.get("display_name") or "").strip()

    if not email:
        return jsonify({"error": "bad_request", "message": "email is required."}), 400

    if not _is_valid_email(email):
        return jsonify({"error": "bad_request", "message": "Invalid email address."}), 400

    with get_db() as cur:
        # --- look up existing user ---
        cur.execute(
            "SELECT user_id, display_name FROM admin.users WHERE email = %s",
            (email,),
        )
        existing = cur.fetchone()

        if existing:
            user_id      = existing["user_id"]
            display_name = existing["display_name"]  # ignore submitted name for existing users
        else:
            # --- new user: display_name required ---
            if not display_name:
                return jsonify({
                    "error":   "bad_request",
                    "message": "display_name is required for new accounts.",
                }), 400

            try:
                validate_display_name(display_name)
            except AuthError as e:
                return jsonify({"error": "bad_request", "message": str(e)}), 400

            # --- uniqueness check ---
            cur.execute(
                "SELECT 1 FROM admin.users WHERE LOWER(display_name) = LOWER(%s)",
                (display_name,),
            )
            if cur.fetchone():
                return jsonify({
                    "error":   "bad_request",
                    "message": "That display name is already taken. Please choose another.",
                }), 400

            # --- create unverified user ---
            cur.execute(
                """
                INSERT INTO admin.users (email, display_name, is_verified)
                VALUES (%s, %s, FALSE)
                RETURNING user_id
                """,
                (email, display_name),
            )
            user_id = cur.fetchone()["user_id"]
            logger.info("Created new user %d (%s)", user_id, email)

        # --- invalidate any existing unused OTPs for this user ---
        cur.execute(
            "UPDATE admin.auth_tokens SET used = TRUE WHERE user_id = %s AND NOT used",
            (user_id,),
        )

        # --- generate and store new OTP ---
        otp       = generate_otp()
        otp_hash  = hash_otp(otp)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=_OTP_TTL_MINUTES)

        cur.execute(
            """
            INSERT INTO admin.auth_tokens (user_id, code_hash, expires_at)
            VALUES (%s, %s, %s)
            """,
            (user_id, otp_hash, expires_at),
        )

    # --- send email (outside transaction — DB already committed) ---
    try:
        send_otp_email(email, otp)
    except EmailError as e:
        logger.error("OTP email failed for user %d: %s", user_id, e)
        return jsonify({
            "error":   "email_failed",
            "message": "Could not send login email. Please try again later.",
        }), 502

    return jsonify({}), 200


# ---------------------------------------------------------------------------
# POST /api/auth/verify
# ---------------------------------------------------------------------------

@bp.post("/verify")
def verify():
    """
    Verify an OTP and issue a JWT.

    Request body
    ------------
    {
        "email": "user@example.com",
        "code":  "482917"
    }

    Response
    --------
    200  {"token": "...", "user_id": 42, "display_name": "railfan42", "is_guest": false}
    400  {"error": "bad_request"}     -- missing fields
    401  {"error": "invalid_code"}    -- wrong, expired, or already-used code
    """
    body = request.get_json(silent=True) or {}

    email = (body.get("email") or "").strip().lower()
    code  = (body.get("code")  or "").strip()

    if not email or not code:
        return jsonify({
            "error":   "bad_request",
            "message": "email and code are required.",
        }), 400

    with get_db() as cur:
        # --- look up user ---
        cur.execute(
            "SELECT user_id, display_name FROM admin.users WHERE email = %s",
            (email,),
        )
        user = cur.fetchone()

        # Return the same error whether the user doesn't exist or the code
        # is wrong — prevents user enumeration via the verify endpoint.
        if not user:
            return _invalid_code_response()

        user_id      = user["user_id"]
        display_name = user["display_name"]

        # --- find the most recent unused, unexpired token for this user ---
        cur.execute(
            """
            SELECT token_id, code_hash
            FROM   admin.auth_tokens
            WHERE  user_id    = %s
              AND  NOT used
              AND  expires_at > NOW()
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (user_id,),
        )
        token_row = cur.fetchone()

        if not token_row:
            return _invalid_code_response()

        # --- constant-time OTP check ---
        if not verify_otp(code, token_row["code_hash"]):
            return _invalid_code_response()

        # --- mark token used + mark user verified (single round-trip) ---
        cur.execute(
            "UPDATE admin.auth_tokens SET used = TRUE WHERE token_id = %s",
            (token_row["token_id"],),
        )
        cur.execute(
            "UPDATE admin.users SET is_verified = TRUE WHERE user_id = %s",
            (user_id,),
        )

    logger.info("User %d (%s) verified successfully.", user_id, email)

    token = create_jwt(
        user_id      = user_id,
        email        = email,
        display_name = display_name,
        is_guest     = False,
    )

    return jsonify({
        "token":        token,
        "user_id":      user_id,
        "display_name": display_name,
        "is_guest":     False,
    }), 200


# ---------------------------------------------------------------------------
# POST /api/auth/guest
# ---------------------------------------------------------------------------

@bp.post("/guest")
@limiter.limit("20 per hour")
def guest():
    """
    Create an anonymous guest session.

    No request body needed.

    Response
    --------
    200  {"token": "...", "user_id": 99, "display_name": "guest_a3f9k2", "is_guest": true}
    500  {"error": "internal_error"}  -- could not generate a unique guest name

    The guest user row is created with email = NULL and is_verified = FALSE.
    Guest tokens expire after 30 days. If the user later registers, their
    proposals can be claimed by updating user_id on those rows.
    """
    with get_db() as cur:
        # --- generate a unique guest display name ---
        display_name = _unique_guest_name(cur)
        if not display_name:
            logger.error("Failed to generate a unique guest name after %d attempts.", _MAX_GUEST_NAME_ATTEMPTS)
            return jsonify({
                "error":   "internal_error",
                "message": "Could not create guest session. Please try again.",
            }), 500

        # --- create guest user row ---
        cur.execute(
            """
            INSERT INTO admin.users (email, display_name, is_verified)
            VALUES (NULL, %s, FALSE)
            RETURNING user_id
            """,
            (display_name,),
        )
        user_id = cur.fetchone()["user_id"]
        logger.info("Created guest user %d (%s)", user_id, display_name)

    token = create_jwt(
        user_id      = user_id,
        email        = None,
        display_name = display_name,
        is_guest     = True,
    )

    return jsonify({
        "token":        token,
        "user_id":      user_id,
        "display_name": display_name,
        "is_guest":     True,
    }), 200


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _invalid_code_response():
    """Unified 401 for all OTP failures — no information about what went wrong."""
    return jsonify({
        "error":   "invalid_code",
        "message": "Invalid or expired code. Please request a new one.",
    }), 401


def _is_valid_email(email: str) -> bool:
    """
    Lightweight email format check — just enough to catch obvious typos.
    Full validation happens implicitly when Resend accepts or rejects it.
    """
    parts = email.split("@")
    if len(parts) != 2:
        return False
    local, domain = parts
    return bool(local) and "." in domain and bool(domain.split(".")[-1])


def _unique_guest_name(cur) -> str | None:
    """
    Generate a guest display name that is not already taken.
    Returns None if no unique name could be found within the attempt limit
    (astronomically unlikely in practice).
    """
    for _ in range(_MAX_GUEST_NAME_ATTEMPTS):
        name = generate_guest_name()
        cur.execute(
            "SELECT 1 FROM admin.users WHERE display_name = %s",
            (name,),
        )
        if not cur.fetchone():
            return name
    return None