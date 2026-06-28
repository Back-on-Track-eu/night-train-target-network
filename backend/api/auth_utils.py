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
  create_jwt(...)                     → signed JWT string
  decode_jwt(token)                   → payload dict (raises AuthError on failure)

Constants
---------
  GUEST_PREFIX   — "guest_"  (single definition used by generator + validator)

Startup check
-------------
  check_auth_config()  → called once from main.py; raises if env vars missing
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

_JWT_ALGORITHM      = "HS256"
_JWT_TTL_DAYS       = 7     # logged-in users
_GUEST_TTL_DAYS     = 30    # guests — longer window so proposals stay accessible
_OTP_DIGITS         = 6
_GUEST_SUFFIX_CHARS = string.ascii_lowercase + string.digits

# Display name rules
GUEST_PREFIX         = "guest_"   # reserved — real users may not use this prefix
_NAME_MIN_LEN        = 3
_NAME_MAX_LEN        = 30
_NAME_ALLOWED_RE     = re.compile(r"^[a-zA-Z0-9_\-]+$")


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
    Verify required auth environment variables are present at startup.
    Raises AuthError with a clear message if anything is missing so the
    process fails loudly rather than breaking at the first login attempt.
    """
    missing = []
    for var in ("JWT_SECRET", "RESEND_API_KEY", "RESEND_FROM_ADDRESS"):
        val = os.environ.get(var, "")
        if not val or val.startswith("replace-with"):
            missing.append(var)
    if missing:
        raise AuthError(
            f"Missing required auth environment variables: {', '.join(missing)}. "
            f"Check your .env file."
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
    return str(secrets.randbelow(10 ** _OTP_DIGITS)).zfill(_OTP_DIGITS)


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
        raise AuthError(
            f"Display name must be at least {_NAME_MIN_LEN} characters."
        )

    if len(name) > _NAME_MAX_LEN:
        raise AuthError(
            f"Display name must be at most {_NAME_MAX_LEN} characters."
        )

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
# JWT
# ---------------------------------------------------------------------------

def create_jwt(
    user_id:      int,
    email:        str | None,
    display_name: str,
    is_guest:     bool = False,
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
        "sub":          str(user_id),
        "email":        email,
        "display_name": display_name,
        "is_guest":     is_guest,
        "iat":          int(now.timestamp()),
        "exp":          int((now + timedelta(days=ttl)).timestamp()),
        "jti":          secrets.token_hex(16),
    }

    return jwt.encode(payload, _get_secret(), algorithm=_JWT_ALGORITHM)


def decode_jwt(token: str) -> dict:
    """
    Decode and verify a JWT. Returns the payload dict on success.

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
    Caught by the @require_auth decorator (Step 7) and converted to a 401.
    """
    pass