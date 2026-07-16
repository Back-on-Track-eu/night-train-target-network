"""
test_71_auth_units.py
=====================
Pure unit tests for the auth building blocks — no Docker stack, no DB:
auth_utils (OTP, display names, local HS256 JWTs) and auth_oidc (plane
routing + Keycloak-token verification against a locally generated RSA
key). The only file in the suite runnable standalone:

    uv run --extra dev pytest tests/test_71_auth_units.py -v
"""

import datetime

import jwt as pyjwt
import pytest

from api import auth_oidc
from api.auth_utils import (
    AuthError,
    GUEST_PREFIX,
    create_jwt,
    decode_jwt,
    generate_guest_name,
    generate_otp,
    hash_otp,
    validate_display_name,
    verify_otp,
)

_SECRET = "unit-test-secret"


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", _SECRET)


# =============================================================================
# OTP
# =============================================================================


def test_otp_shape_and_randomness():
    codes = {generate_otp() for _ in range(50)}
    assert all(len(c) == 6 and c.isdigit() for c in codes)
    assert len(codes) > 40  # 50 draws from 10^6 — collisions ≈ never


def test_otp_hash_roundtrip():
    otp = generate_otp()
    stored = hash_otp(otp)
    assert stored != otp and len(stored) == 64
    assert verify_otp(otp, stored)
    assert not verify_otp("000000" if otp != "000000" else "111111", stored)


# =============================================================================
# Display names + guest names
# =============================================================================


@pytest.mark.parametrize(
    "bad", ["", "ab", "a" * 31, "has space", "hüsker", "guest_x9", "Guest_X9"]
)
def test_display_name_rejections(bad):
    with pytest.raises(AuthError):
        validate_display_name(bad)


@pytest.mark.parametrize("good", ["abc", "railfan42", "night-train_fan"])
def test_display_name_accepts(good):
    validate_display_name(good)  # must not raise


def test_guest_names_reserved_prefix_and_unique():
    names = {generate_guest_name() for _ in range(20)}
    assert all(n.startswith(GUEST_PREFIX) for n in names)
    assert len(names) == 20
    with pytest.raises(AuthError):
        validate_display_name(next(iter(names)))  # guests can't be chosen


# =============================================================================
# Local plane JWTs (HS256)
# =============================================================================


def test_local_jwt_roundtrip():
    token = create_jwt(user_id=7, email="a@b.eu", display_name="tester", is_guest=False)
    payload = decode_jwt(token)
    assert payload["sub"] == "7"
    assert payload["email"] == "a@b.eu"
    assert payload["is_guest"] is False
    assert payload["exp"] > payload["iat"]


def test_local_jwt_bad_signature_rejected():
    token = create_jwt(
        user_id=7, email=None, display_name="guest_ab12cd", is_guest=True
    )
    tampered = token[:-4] + ("aaaa" if not token.endswith("aaaa") else "bbbb")
    with pytest.raises(AuthError):
        decode_jwt(tampered)


def test_missing_secret_fails_loudly(monkeypatch):
    monkeypatch.delenv("JWT_SECRET")
    with pytest.raises(AuthError):
        create_jwt(user_id=1, email=None, display_name="x-y-z", is_guest=True)


# =============================================================================
# OIDC plane (auth_oidc) — dormant switch, routing, verification
# =============================================================================

_ISSUER = "https://auth.example.org/realms/bot"
_CLIENT = "target-network"


@pytest.fixture()
def rsa_key():
    cryptography = pytest.importorskip("cryptography")  # pyjwt[crypto]
    from cryptography.hazmat.primitives.asymmetric import rsa

    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _keycloak_token(key, **overrides):
    now = datetime.datetime.now(datetime.timezone.utc)
    claims = {
        "iss": _ISSUER,
        "aud": _CLIENT,
        "sub": "kc-uuid-123",
        "email": "operator@back-on-track.eu",
        "preferred_username": "operator",
        "iat": now,
        "exp": now + datetime.timedelta(minutes=5),
        **overrides,
    }
    claims = {k: v for k, v in claims.items() if v is not None}
    return pyjwt.encode(claims, key, algorithm="RS256")


class _FakeSigningKey:
    def __init__(self, key):
        self.key = key.public_key()


def test_oidc_dormant_by_default(monkeypatch):
    monkeypatch.delenv("KEYCLOAK_ISSUER_URL", raising=False)
    assert not auth_oidc.enabled()
    assert not auth_oidc.is_oidc_token("anything")
    with pytest.raises(AuthError):
        auth_oidc.verify("anything")


def test_oidc_plane_routing(monkeypatch, rsa_key):
    monkeypatch.setenv("KEYCLOAK_ISSUER_URL", _ISSUER)
    monkeypatch.setenv("KEYCLOAK_CLIENT_ID", _CLIENT)

    keycloak_token = _keycloak_token(rsa_key)
    local_token = create_jwt(user_id=1, email="a@b.eu", display_name="abc")

    assert auth_oidc.is_oidc_token(keycloak_token)
    assert not auth_oidc.is_oidc_token(local_token)  # different iss
    assert not auth_oidc.is_oidc_token("garbage")  # malformed → local plane


def test_oidc_verify_happy_path(monkeypatch, rsa_key):
    monkeypatch.setenv("KEYCLOAK_ISSUER_URL", _ISSUER)
    monkeypatch.setenv("KEYCLOAK_CLIENT_ID", _CLIENT)
    monkeypatch.setattr(
        auth_oidc,
        "_get_jwks_client",
        lambda: type(
            "C",
            (),
            {"get_signing_key_from_jwt": lambda self, t: _FakeSigningKey(rsa_key)},
        )(),
    )

    claims = auth_oidc.verify(_keycloak_token(rsa_key))
    assert claims["email"] == "operator@back-on-track.eu"


@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": "some-other-client"},  # wrong audience
        {"iss": "https://evil.example.org/realms/bot"},  # wrong issuer
        {
            "exp": datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(minutes=1)
        },  # expired
        {"email": None},  # no email claim
    ],
)
def test_oidc_verify_rejections(monkeypatch, rsa_key, overrides):
    monkeypatch.setenv("KEYCLOAK_ISSUER_URL", _ISSUER)
    monkeypatch.setenv("KEYCLOAK_CLIENT_ID", _CLIENT)
    monkeypatch.setattr(
        auth_oidc,
        "_get_jwks_client",
        lambda: type(
            "C",
            (),
            {"get_signing_key_from_jwt": lambda self, t: _FakeSigningKey(rsa_key)},
        )(),
    )

    bad = _keycloak_token(rsa_key, **overrides)
    if "iss" in overrides:
        # a foreign issuer wouldn't even route to this plane; verify() must
        # still reject it if called directly
        assert not auth_oidc.is_oidc_token(bad)
    with pytest.raises(AuthError):
        auth_oidc.verify(bad)
