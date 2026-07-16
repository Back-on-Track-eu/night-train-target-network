"""
auth_oidc.py
============
"Sign in with BoT account" — validation of Keycloak-issued OIDC access
tokens (the OPERATOR plane of the dual-plane auth model).

DORMANT BY DEFAULT. Everything here is a no-op until KEYCLOAK_ISSUER_URL
is set, so this ships ahead of the BoT central-identity rollout and
activates by configuration only — no code change at flip time:

    KEYCLOAK_ISSUER_URL=https://auth.back-on-track.eu/realms/bot
    KEYCLOAK_CLIENT_ID=target-network
    # optional override; derived from the issuer by default:
    KEYCLOAK_JWKS_URL=<issuer>/protocol/openid-connect/certs

Division of labour with the local plane (auth_utils.py):
  - Local plane: HS256 JWTs this app issues itself (OTP contributors +
    guests). Shared-secret verification, users originate in admin.users.
  - OIDC plane: RS256 JWTs issued by BoT's Keycloak. Verified against the
    realm's public keys (JWKS, fetched + cached by PyJWKClient), audience
    = our client id. Users originate in Keycloak; on first authenticated
    request they get a local admin.users row (email-matched, else created)
    so proposals/feedback FKs keep working — see
    AuthRepository.get_or_create_sso_user().

auth_middleware.py routes each bearer token to the right plane by
inspecting the token's unverified `iss` claim (see is_oidc_token()).
"""

from __future__ import annotations

import logging
import os
import threading

import jwt

from api.auth_utils import AuthError

logger = logging.getLogger(__name__)

_jwks_client: jwt.PyJWKClient | None = None
_jwks_lock = threading.Lock()


def issuer() -> str:
    """The configured Keycloak realm issuer URL, or '' when disabled."""
    return os.environ.get("KEYCLOAK_ISSUER_URL", "").rstrip("/")


def enabled() -> bool:
    """True when the OIDC plane is configured (KEYCLOAK_ISSUER_URL set)."""
    return bool(issuer())


def is_oidc_token(token: str) -> bool:
    """
    Cheap plane-routing check: does this bearer token claim to come from
    the configured Keycloak issuer? Reads the payload WITHOUT verifying
    the signature — routing only, never trust. A malformed token returns
    False and falls through to the local plane, which rejects it properly.
    """
    if not enabled():
        return False
    try:
        unverified = jwt.decode(token, options={"verify_signature": False})
    except jwt.InvalidTokenError:
        return False
    return unverified.get("iss", "").rstrip("/") == issuer()


def _get_jwks_client() -> jwt.PyJWKClient:
    """Lazily construct one PyJWKClient per process (it caches signing
    keys internally, so key fetches don't happen per-request)."""
    global _jwks_client
    if _jwks_client is None:
        with _jwks_lock:
            if _jwks_client is None:
                jwks_url = os.environ.get(
                    "KEYCLOAK_JWKS_URL",
                    f"{issuer()}/protocol/openid-connect/certs",
                )
                _jwks_client = jwt.PyJWKClient(jwks_url, cache_keys=True)
    return _jwks_client


def verify(token: str) -> dict:
    """
    Fully verify a Keycloak access token: RS256 signature against the
    realm's JWKS, issuer match, audience = KEYCLOAK_CLIENT_ID, expiry.
    Returns the verified claims dict. Raises AuthError on any failure.
    """
    if not enabled():
        raise AuthError("OIDC sign-in is not enabled on this deployment.")

    client_id = os.environ.get("KEYCLOAK_CLIENT_ID", "")
    try:
        signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=client_id,
            issuer=issuer(),
        )
    except jwt.ExpiredSignatureError:
        raise AuthError("Token has expired. Please sign in again.")
    except (jwt.InvalidTokenError, jwt.PyJWKClientError) as e:
        raise AuthError(f"Invalid BoT account token: {e}")

    if not claims.get("email"):
        # Keycloak includes email in access tokens via the default 'email'
        # client scope; without it we cannot map to a local user row.
        raise AuthError(
            "BoT account token carries no email claim — check the client's "
            "scope configuration in Keycloak."
        )
    return claims
