"""
auth.py
=======
Authentication endpoints — the LOCAL plane of the dual-plane auth model:
OTP login for contributors and anonymous guest sessions.

  POST /api/auth/request-code   — register or log in: send OTP to email
  POST /api/auth/verify         — verify OTP, return JWT
  POST /api/auth/guest          — create a guest session, return JWT

The OPERATOR plane ("Sign in with BoT account", Keycloak OIDC) has no
endpoint here — operators obtain tokens from Keycloak directly and this
API only validates them (see auth_oidc.py + auth_middleware.py).

Flow
----
  Registration + login are the same endpoint (request-code).
  If the email is new, a user row is created (unverified).
  If it already exists, the existing user is used.
  Either way an OTP is issued and emailed (adapters/mailer.py — BoT SMTP,
  or logged when AUTH_EMAIL_DEV_MODE=true).

  On verify, the OTP is checked, the user is marked verified,
  and a JWT is returned.

  Guest flow is separate: POST /api/auth/guest creates an anonymous
  user row and returns a guest JWT immediately (no email needed).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request

from adapters import mailer
from api.auth_utils import (
    AuthError,
    create_jwt,
    decode_jwt,
    generate_guest_name,
    generate_otp,
    hash_otp,
    validate_display_name,
    verify_otp,
)
from api.helpers.dependencies import get_auth_repository
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

    email = (body.get("email") or "").strip().lower()
    display_name = (body.get("display_name") or "").strip()

    if not email:
        return jsonify({"error": "bad_request", "message": "email is required."}), 400

    if not _is_valid_email(email):
        return (
            jsonify({"error": "bad_request", "message": "Invalid email address."}),
            400,
        )

    repo = get_auth_repository()

    existing = repo.get_user_by_email(email)
    if existing:
        user_id = existing["user_id"]
    else:
        # --- new user: display_name required ---
        if not display_name:
            return (
                jsonify(
                    {
                        "error": "bad_request",
                        "message": "display_name is required for new accounts.",
                    }
                ),
                400,
            )

        try:
            validate_display_name(display_name)
        except AuthError as e:
            return jsonify({"error": "bad_request", "message": str(e)}), 400

        if repo.display_name_taken(display_name):
            return (
                jsonify(
                    {
                        "error": "bad_request",
                        "message": "That display name is already taken. Please choose another.",
                    }
                ),
                400,
            )

        user_id = repo.create_user(email=email, display_name=display_name)["user_id"]

    # --- invalidate old codes + store the new one (atomic) ---
    otp = generate_otp()
    repo.issue_otp(
        user_id=user_id,
        code_hash=hash_otp(otp),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=_OTP_TTL_MINUTES),
    )

    # --- send email (after commit — a stored-but-unsent code is retryable) ---
    if not mailer.send_otp_email(email, otp):
        logger.error("OTP email failed for user %d.", user_id)
        return (
            jsonify(
                {
                    "error": "email_failed",
                    "message": "Could not send login email. Please try again later.",
                }
            ),
            502,
        )

    return jsonify({}), 200


def _guest_user_id_from_bearer() -> int | None:
    """Guest user_id from an Authorization header on /verify, if present and
    valid — the signal that a guest session is registering and its proposals
    and feedback should be claimed. Anything else (no header, malformed,
    invalid/expired token, non-guest token) is None: an unusable bearer must
    never block the registration itself."""
    auth_header = request.headers.get("Authorization", "")
    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    try:
        payload = decode_jwt(parts[1])
    except AuthError:
        logger.info("verify: ignoring invalid bearer token during registration")
        return None
    if not payload.get("is_guest"):
        return None
    return int(payload["sub"])


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

    Guest merge: send the current guest session's JWT as the Authorization
    bearer on this call and, on success, everything that guest owns
    (proposals, feedback) is reassigned to the verified account and the
    guest row is marked merged (its token stops working with an explicit
    account-merged error). This covers registering as the last step after
    playing around, and equally logging in to an existing account from a
    guest session. An absent/invalid bearer never blocks verification.

    Response
    --------
    200  {"token": "...", "user_id": 42, "display_name": "railfan42",
          "is_guest": false, "merged_guest": null |
          {"guest_user_id": 99, "proposals_claimed": 2, "feedback_claimed": 0}}
    400  {"error": "bad_request"}     -- missing fields
    401  {"error": "invalid_code"}    -- wrong, expired, or already-used code
    """
    body = request.get_json(silent=True) or {}

    email = (body.get("email") or "").strip().lower()
    code = (body.get("code") or "").strip()

    if not email or not code:
        return (
            jsonify(
                {
                    "error": "bad_request",
                    "message": "email and code are required.",
                }
            ),
            400,
        )

    repo = get_auth_repository()

    # Return the same error whether the user doesn't exist, has no live
    # code, or the code is wrong — prevents user enumeration via verify.
    user = repo.get_user_by_email(email)
    if not user:
        return _invalid_code_response()

    token_row = repo.latest_valid_otp(user["user_id"])
    if not token_row:
        return _invalid_code_response()

    if not verify_otp(code, token_row["code_hash"]):
        return _invalid_code_response()

    repo.consume_otp(token_row["token_id"], user["user_id"])

    logger.info("User %d (%s) verified successfully.", user["user_id"], email)

    # Guest → registered merge (see docstring). Runs after the OTP is
    # consumed so a failed merge can never burn the code, and never fails
    # the verification itself.
    merged_guest = None
    guest_user_id = _guest_user_id_from_bearer()
    if guest_user_id is not None and guest_user_id != user["user_id"]:
        try:
            counts = repo.merge_guest_into(guest_user_id, user["user_id"])
        except Exception:
            logger.exception(
                "guest merge failed (guest %d -> user %d); verification "
                "proceeds without it",
                guest_user_id,
                user["user_id"],
            )
            counts = None
        if counts is not None:
            merged_guest = {"guest_user_id": guest_user_id, **counts}

    token = create_jwt(
        user_id=user["user_id"],
        email=email,
        display_name=user["display_name"],
        is_guest=False,
    )

    return (
        jsonify(
            {
                "token": token,
                "user_id": user["user_id"],
                "display_name": user["display_name"],
                "is_guest": False,
                "merged_guest": merged_guest,
            }
        ),
        200,
    )


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
    repo = get_auth_repository()

    display_name = None
    for _ in range(_MAX_GUEST_NAME_ATTEMPTS):
        candidate = generate_guest_name()
        if not repo.display_name_taken(candidate):
            display_name = candidate
            break

    if not display_name:
        logger.error(
            "Failed to generate a unique guest name after %d attempts.",
            _MAX_GUEST_NAME_ATTEMPTS,
        )
        return (
            jsonify(
                {
                    "error": "internal_error",
                    "message": "Could not create guest session. Please try again.",
                }
            ),
            500,
        )

    user = repo.create_user(email=None, display_name=display_name)

    token = create_jwt(
        user_id=user["user_id"],
        email=None,
        display_name=display_name,
        is_guest=True,
    )

    return (
        jsonify(
            {
                "token": token,
                "user_id": user["user_id"],
                "display_name": display_name,
                "is_guest": True,
            }
        ),
        200,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _invalid_code_response():
    """Unified 401 for all OTP failures — no information about what went wrong."""
    return (
        jsonify(
            {
                "error": "invalid_code",
                "message": "Invalid or expired code. Please request a new one.",
            }
        ),
        401,
    )


def _is_valid_email(email: str) -> bool:
    """
    Lightweight email format check — just enough to catch obvious typos.
    Full validation happens implicitly when the SMTP server accepts or
    rejects the recipient.
    """
    parts = email.split("@")
    if len(parts) != 2:
        return False
    local, domain = parts
    return bool(local) and "." in domain and bool(domain.split(".")[-1])
