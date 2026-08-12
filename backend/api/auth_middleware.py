"""
auth_middleware.py
==================
Flask decorators for bearer-token authentication — the point where the
two auth planes meet and normalize:

  local plane : HS256 JWTs this app issues (OTP contributors + guests)
  OIDC plane  : RS256 JWTs from BoT's Keycloak (operators) — dormant
                until KEYCLOAK_ISSUER_URL is set, see auth_oidc.py

  @require_auth          — valid token required; 401 otherwise
  @optional_auth         — works with or without a token; a *present but
                           invalid* token is still a 401, not ignored
  @require_trust(level)  — valid token AND g.trust_level >= level

It also owns rate_limit_key(), the per-user bucket key the rate-limited
endpoints pass to @limiter.limit — identity resolution is this module's
job, and putting it here keeps api/limiter.py import-free (see its
docstring for why that matters).

Flask g context set by all decorators
--------------------------------------
    g.user_id      : int | None   — admin.users identity (both planes)
    g.email        : str | None
    g.display_name : str | None
    g.is_guest     : bool
    g.trust_level  : int          — TRUST_GUEST < TRUST_CONTRIBUTOR
                                    < TRUST_OPERATOR (auth_utils constants)
"""

from __future__ import annotations

import logging
from functools import wraps

from flask import g, jsonify, request
from flask_limiter.util import get_remote_address

from api import auth_oidc
from api.auth_utils import (
    TRUST_CONTRIBUTOR,
    TRUST_GUEST,
    TRUST_OPERATOR,
    AuthError,
    UnknownAccountError,
    decode_jwt,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal: extract and resolve identity from the request
# ---------------------------------------------------------------------------


def _bearer_token() -> str | None:
    """Read the Authorization header. Returns the raw token, or None when
    the header is absent. Raises AuthError on a malformed header."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header:
        return None

    parts = auth_header.split()
    if parts and parts[0].lower() != "bearer":
        # A different auth scheme (e.g. "Basic ..." injected by the browser
        # behind the staging basic-auth wall) is not ours to validate —
        # treat the request as anonymous instead of rejecting it.
        return None
    if len(parts) != 2:
        raise AuthError("Invalid Authorization header format. Expected: Bearer <token>")
    return parts[1]


def _load_identity_from_request() -> dict | None:
    """
    Resolve the request's bearer token to a normalized identity dict:
    {user_id, email, display_name, is_guest, trust_level}.

    Returns None if no token is present.
    Raises AuthError if a token is present but invalid on its plane.
    """
    token = _bearer_token()
    if token is None:
        return None

    # --- OIDC plane: token claims to come from BoT's Keycloak ---
    if auth_oidc.is_oidc_token(token):
        claims = auth_oidc.verify(token)
        # Late import — dependencies imports adapters at init time and the
        # repository is only needed on this (rarer) path.
        from api.helpers.dependencies import get_auth_repository

        user = get_auth_repository().get_or_create_sso_user(
            email=claims["email"],
            preferred_name=claims.get("preferred_username")
            or claims.get("name")
            or claims["email"].split("@")[0],
        )
        return {
            "user_id": user["user_id"],
            "email": user["email"],
            "display_name": user["display_name"],
            "is_guest": False,
            "trust_level": TRUST_OPERATOR,
        }

    # --- local plane: HS256 JWT issued by this app ---
    # A valid signature says the token was issued here, not that the
    # account it names still exists: a reseed recreates admin.users from
    # scratch while browsers keep their tokens, and a deleted account
    # leaves the same gap. Resolving the row makes both cases a clean 401
    # the client can act on, instead of a foreign-key violation surfacing
    # from whichever write the caller happened to attempt. Late import for
    # the same reason as the OIDC path above.
    from api.helpers.dependencies import get_auth_repository

    payload = decode_jwt(token)
    is_guest = bool(payload.get("is_guest", False))
    user = get_auth_repository().get_user(int(payload["sub"]))

    if user is None:
        raise UnknownAccountError(
            "This session belongs to an account that no longer exists. "
            "Please sign in again."
        )
    # A guest that verified an email was merged into that account
    # (auth.py: verify) — its still-valid guest token must fail loudly,
    # not act as the abandoned identity.
    if user["merged_into_user_id"] is not None:
        raise AuthError(
            "This guest session has been merged into a registered "
            "account. Please log in with your email."
        )

    # Identity fields come from the row, not the token: a display name
    # changed after the token was issued should not travel stale.
    return {
        "user_id": user["user_id"],
        "email": user["email"],
        "display_name": user["display_name"],
        "is_guest": is_guest,
        "trust_level": TRUST_GUEST if is_guest else TRUST_CONTRIBUTOR,
    }


def _set_g(identity: dict) -> None:
    g.user_id = identity["user_id"]
    g.email = identity["email"]
    g.display_name = identity["display_name"]
    g.is_guest = identity["is_guest"]
    g.trust_level = identity["trust_level"]


def _clear_g() -> None:
    g.user_id = None
    g.email = None
    g.display_name = None
    g.is_guest = False
    g.trust_level = TRUST_GUEST


def _unauthorized(message: str):
    return jsonify({"error": "unauthorized", "message": message}), 401


# ---------------------------------------------------------------------------
# Rate-limit bucket key
# ---------------------------------------------------------------------------


def rate_limit_key() -> str:
    """Which bucket the current request counts against: the authenticated
    user where one can be established cheaply, the client address
    otherwise.

    Flask-Limiter evaluates this in a before_request hook — BEFORE
    @require_auth has run — so g.user_id is not set yet and the token has
    to be read here. Only the local plane is resolved: that is a
    signature check on a small HS256 JWT and nothing more. OIDC tokens
    deliberately fall through to the address bucket rather than pay a
    JWKS verification on every request; operators are few, trusted, and
    not the abuse vector these limits exist for.
    """
    try:
        token = _bearer_token()
        if token is not None and not auth_oidc.is_oidc_token(token):
            return f"user:{decode_jwt(token)['sub']}"
    except AuthError:
        pass
    return get_remote_address()


# ---------------------------------------------------------------------------
# @require_auth
# ---------------------------------------------------------------------------


def require_auth(f):
    """
    Decorator: endpoint requires a valid token from either plane.

    Sets g.user_id, g.email, g.display_name, g.is_guest, g.trust_level.
    Returns 401 if the token is missing, invalid, or expired.

    Guests pass — an endpoint that needs more checks g.is_guest or uses
    @require_trust instead.
    """

    @wraps(f)
    def decorated(*args, **kwargs):
        try:
            identity = _load_identity_from_request()
        except AuthError as e:
            return _unauthorized(str(e))

        if identity is None:
            return _unauthorized("Authentication required. Please log in.")

        _set_g(identity)
        return f(*args, **kwargs)

    return decorated


# ---------------------------------------------------------------------------
# @optional_auth
# ---------------------------------------------------------------------------


def optional_auth(f):
    """
    Decorator: endpoint works with or without authentication.

    If a valid token is present, sets g.* as normal.
    If no token is present, sets g.user_id = None (unauthenticated).
    If a token is present but invalid, returns 401 — a bad token is
    treated as an error, not silently ignored.

    One exception to that last rule: a token naming an account that no
    longer exists (UnknownAccountError) degrades to anonymous instead.
    These endpoints are readable without any token at all, so rejecting
    one that is merely stale would take away a page the caller could
    have had — the dev stack reseeds on every container start, so a
    cookie outliving its row is ordinary rather than suspicious. The
    session still fails at the first write, which is where the caller
    needs to hear it.
    """

    @wraps(f)
    def decorated(*args, **kwargs):
        _clear_g()
        try:
            identity = _load_identity_from_request()
        except UnknownAccountError:
            identity = None
        except AuthError as e:
            return _unauthorized(str(e))

        if identity is not None:
            _set_g(identity)

        return f(*args, **kwargs)

    return decorated


# ---------------------------------------------------------------------------
# @require_trust
# ---------------------------------------------------------------------------


def require_trust(min_level: int):
    """
    Decorator factory: endpoint requires a valid token whose plane maps to
    at least `min_level` on the trust ladder. E.g. an operator-only action:

        @bp.post("/scenario")
        @require_trust(TRUST_OPERATOR)
        def save_scenario(): ...
    """

    def wrapper(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            try:
                identity = _load_identity_from_request()
            except AuthError as e:
                return _unauthorized(str(e))

            if identity is None:
                return _unauthorized("Authentication required. Please log in.")

            if identity["trust_level"] < min_level:
                return (
                    jsonify(
                        {
                            "error": "forbidden",
                            "message": "This action needs a higher-trust "
                            "account (BoT operator sign-in).",
                        }
                    ),
                    403,
                )

            _set_g(identity)
            return f(*args, **kwargs)

        return decorated

    return wrapper
