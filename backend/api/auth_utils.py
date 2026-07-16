"""
auth_utils.py
=============
Pure utility functions for authentication.
No Flask, no DB — fully unit-testable in isolation.

Functions
---------
  generate_otp()                      → 6-digit string
  hash_otp(otp)                       → SHA-256 hex digest
  verify_otp(submitted, stored_hash)  → bool (constant-time)
  validate_display_name(name)         → None or raises AuthError
  generate_guest_name()               → "guest_<6 random chars>"
  create_jwt(...)                     → signed JWT string (local HS256 plane)
  decode_jwt(token)                   → payload dict (raises AuthError on failure)

Constants
---------
  GUEST_PREFIX   — "guest_"  (single definition used by generator + validator)
  TRUST_GUEST / TRUST_CONTRIBUTOR / TRUST_OPERATOR — the trust ladder both
  auth planes normalize to (see auth_middleware.py): anonymous guest tokens <
  email-verified OTP contributors < Keycloak-SSO BoT operators.

Startup check
-------------
  check_auth_config()  → called once from main.py; fails fast on a missing
  JWT_SECRET, warns (but does not fail) when no OTP mail lane is configured,
  and validates the optional Keycloak OIDC config when it is enabled.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
import string
from datetime import datetime, timedelta, timezone

import jwt

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_JWT_ALGORITHM = "HS256"
_JWT_TTL_DAYS = 7  # logged-in users
_GUEST_TTL_DAYS = 30  # guests — longer window so proposals stay accessible
_OTP_DIGITS = 6
_GUEST_SUFFIX_CHARS = string.ascii_lowercase + string.digits

# Display name rules
GUEST_PREFIX = "guest_"  # reserved — real users may not use this prefix
_NAME_MIN_LEN = 3
_NAME_MAX_LEN = 30
_NAME_ALLOWED_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")

# Trust ladder — both auth planes (local OTP/guest JWTs and Keycloak OIDC
# tokens) normalize to one of these levels on g.trust_level.
TRUST_GUEST = 0
TRUST_CONTRIBUTOR = 1
TRUST_OPERATOR = 2


def _get_secret() -> str:
    secret = os.environ.get("JWT_SECRET", "")
    if not secret or secret.startswith("replace-with"):
        raise AuthError("JWT_SECRET is not configured. Set it in your .env file.")
    return secret


# ---------------------------------------------------------------------------
# Startup check — call once from main.py
# ---------------------------------------------------------------------------


def check_auth_config() -> None:
    """
    Verify auth configuration at startup so the process fails loudly (or
    warns loudly) rather than breaking at the first login attempt.

    - JWT_SECRET missing            → raises AuthError (hard requirement:
      guest sessions and OTP logins are both dead without it).
    - No OTP mail lane              → logs a WARNING only. Guest sessions and
      OIDC sign-in still work; POST /api/auth/request-code will return 502
      until SMTP_* is configured or AUTH_EMAIL_DEV_MODE=true is set. Warning
      instead of failure so existing deployments without SMTP keep booting.
    - KEYCLOAK_ISSUER_URL set but KEYCLOAK_CLIENT_ID missing → raises
      AuthError (the audience check is not optional once OIDC is enabled).
    """
    _get_secret()  # raises with a clear message when missing

    dev_mode = os.environ.get("AUTH_EMAIL_DEV_MODE", "").lower() == "true"
    smtp_missing = [
        var
        for var in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD")
        if not os.environ.get(var)
    ]
    if dev_mode:
        logger.warning(
            "AUTH_EMAIL_DEV_MODE is on — OTP codes are LOGGED, not emailed. "
            "Never enable this on a public deployment."
        )
    elif smtp_missing:
        logger.warning(
            "No OTP mail lane: missing %s and AUTH_EMAIL_DEV_MODE is off — "
            "POST /api/auth/request-code will return 502 until configured.",
            ", ".join(smtp_missing),
        )

    issuer = os.environ.get("KEYCLOAK_ISSUER_URL", "")
    if issuer:
        if not os.environ.get("KEYCLOAK_CLIENT_ID"):
            raise AuthError(
                "KEYCLOAK_ISSUER_URL is set but KEYCLOAK_CLIENT_ID is not — "
                "OIDC token validation needs the client id for the audience "
                "check. Set both or neither."
            )
        logger.info("OIDC operator sign-in ENABLED (issuer: %s).", issuer)
    else:
        logger.info(
            "OIDC operator sign-in disabled (KEYCLOAK_ISSUER_URL not set) — "
            "local OTP/guest plane only."
        )

    logger.info("Auth config OK.")


# ---------------------------------------------------------------------------
# OTP
# ---------------------------------------------------------------------------


def generate_otp() -> str:
    """
    Return a cryptographically random 6-digit OTP as a zero-padded string.
    e.g. "048291"
    Uses secrets.randbelow — not random.randint — for cryptographic safety.
    """
    return str(secrets.randbelow(10**_OTP_DIGITS)).zfill(_OTP_DIGITS)


def hash_otp(otp: str) -> str:
    """
    Return the SHA-256 hex digest of the OTP string.
    Store this in the DB — never the plaintext OTP.

    SHA-256 is appropriate here (not bcrypt) because:
      - OTPs expire in 15 minutes
      - They are single-use
      - The input space (000000–999999) is small but the time window
        is too short for a brute-force to matter in practice
    """
    return hashlib.sha256(otp.encode()).hexdigest()


def verify_otp(submitted: str, stored_hash: str) -> bool:
    """
    Constant-time comparison of a submitted OTP against the stored hash.
    Constant-time prevents timing attacks that could leak whether a guess
    was "close" to the correct value.
    """
    submitted_hash = hashlib.sha256(submitted.encode()).hexdigest()
    return secrets.compare_digest(submitted_hash, stored_hash)


# ---------------------------------------------------------------------------
# Display name validation
# ---------------------------------------------------------------------------


def validate_display_name(name: str) -> None:
    """
    Validate a user-supplied display name. Raises AuthError with a
    user-friendly message on any violation.

    Rules
    -----
    - Must be a non-empty string
    - Length between 3 and 30 characters
    - Only letters, digits, underscores, hyphens (no spaces or special chars)
    - Must not start with the reserved guest prefix "guest_"
      (case-insensitive — "Guest_abc" is also rejected)

    Uniqueness is NOT checked here — that requires a DB query and is
    the caller's responsibility (auth route handler).
    """
    if not isinstance(name, str) or not name:
        raise AuthError("Display name must be a non-empty string.")

    if len(name) < _NAME_MIN_LEN:
        raise AuthError(f"Display name must be at least {_NAME_MIN_LEN} characters.")

    if len(name) > _NAME_MAX_LEN:
        raise AuthError(f"Display name must be at most {_NAME_MAX_LEN} characters.")

    if not _NAME_ALLOWED_RE.match(name):
        raise AuthError(
            "Display name may only contain letters, digits, underscores, "
            "and hyphens — no spaces or special characters."
        )

    if name.lower().startswith(GUEST_PREFIX):
        raise AuthError(
            f'Display name may not start with "{GUEST_PREFIX}" — '
            f"that prefix is reserved for guest accounts."
        )


# ---------------------------------------------------------------------------
# Guest name
# ---------------------------------------------------------------------------


def generate_guest_name() -> str:
    """
    Return a random guest display name using the reserved GUEST_PREFIX,
    e.g. "guest_a3f9k2".

    6-char suffix → 36^6 ≈ 2 billion combinations. Collision probability
    is negligible at the expected scale of this tool, but the caller
    (auth route handler) must still check uniqueness in the DB and retry
    if a collision occurs.
    """
    suffix = "".join(secrets.choice(_GUEST_SUFFIX_CHARS) for _ in range(6))
    return f"{GUEST_PREFIX}{suffix}"


# ---------------------------------------------------------------------------
# JWT — local plane (HS256). Keycloak OIDC tokens are handled by
# auth_oidc.py; auth_middleware.py decides which plane a bearer token
# belongs to.
# ---------------------------------------------------------------------------


def create_jwt(
    user_id: int,
    email: str | None,
    display_name: str,
    is_guest: bool = False,
) -> str:
    """
    Issue a signed JWT for a verified or guest user.

    Payload claims
    --------------
    sub          : str(user_id)   — standard JWT subject
    email        : str | None     — None for guests
    display_name : str            — shown in UI without extra DB call
    is_guest     : bool           — frontend uses this to show "log in" prompt
    iat          : int            — issued-at (UTC unix timestamp)
    exp          : int            — expiry   (UTC unix timestamp)
    jti          : str            — unique token ID (enables revocation later)
    """
    now = datetime.now(timezone.utc)
    ttl = _GUEST_TTL_DAYS if is_guest else _JWT_TTL_DAYS

    payload = {
        "sub": str(user_id),
        "email": email,
        "display_name": display_name,
        "is_guest": is_guest,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=ttl)).timestamp()),
        "jti": secrets.token_hex(16),
    }

    return jwt.encode(payload, _get_secret(), algorithm=_JWT_ALGORITHM)


def decode_jwt(token: str) -> dict:
    """
    Decode and verify a locally-issued JWT. Returns the payload dict.

    Raises AuthError for any failure:
      - invalid signature
      - expired token
      - malformed token
      - missing JWT_SECRET

    PyJWT validates exp automatically — no manual timestamp check needed.
    """
    try:
        payload = jwt.decode(
            token,
            _get_secret(),
            algorithms=[_JWT_ALGORITHM],
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise AuthError("Token has expired. Please log in again.")
    except jwt.InvalidTokenError as e:
        raise AuthError(f"Invalid token: {e}")


# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------


class AuthError(Exception):
    """
    Raised by auth utilities for any authentication failure.
    Caught by the auth_middleware decorators and converted to a 401.
    """

    pass
