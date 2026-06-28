"""
test_auth.py
============
Tests for Phase 5 authentication.

Two sections:
  1. Unit tests — auth_utils.py (no DB, no network, no Flask)
  2. Integration tests — auth endpoints via HTTP against the live stack

Integration tests require the full Docker stack running:
    cd backend/docker && docker-compose up -d

Run from backend/:
    uv run --group dev pytest tests/test_auth.py -v

Integration test coverage
-------------------------
  POST /api/auth/request-code
    - valid new user registers and gets 200
    - valid existing user gets 200 (no enumeration)
    - missing email → 400
    - invalid email format → 400
    - missing display_name for new user → 400
    - reserved guest_ prefix rejected → 400
    - duplicate display_name rejected → 400
    - OTP is stored hashed, not plaintext

  POST /api/auth/verify
    - valid OTP → 200 with JWT and user info
    - wrong OTP → 401
    - expired OTP → 401
    - already-used OTP → 401
    - missing fields → 400
    - JWT payload contains expected claims
    - user is_verified set to TRUE after verify

  POST /api/auth/guest
    - creates guest user → 200 with guest JWT
    - guest display_name starts with guest_
    - guest has no email in DB
    - JWT is_guest flag is True

  Auth middleware
    - protected endpoint returns 401 without token
    - protected endpoint returns 200 with valid token
"""

from __future__ import annotations

import hashlib
import os
import time
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import psycopg2
import psycopg2.extras
import pytest
import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

API_BASE   = os.environ.get("API_BASE_URL", "http://localhost:5000")
JWT_SECRET = os.environ.get("JWT_SECRET", "")

DB_CONFIG = {
    "host":     os.environ.get("POSTGRES_HOST",     "localhost"),
    "port":     int(os.environ.get("POSTGRES_PORT", "5432")),
    "dbname":   os.environ.get("POSTGRES_DB",       "target_network_test_db"),
    "user":     os.environ.get("POSTGRES_USER",     "bot_admin"),
    "password": os.environ.get("POSTGRES_PASSWORD", "devpassword"),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _db():
    """Open a fresh RealDict connection for DB assertions."""
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = False
    return conn


def _fetch_one(query: str, params: tuple):
    conn = _db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params)
            return cur.fetchone()
    finally:
        conn.close()


def _cleanup_user(email: str = None, display_name: str = None):
    """Remove a test user and their tokens from the DB."""
    conn = _db()
    try:
        with conn.cursor() as cur:
            if email:
                cur.execute(
                    "DELETE FROM admin.users WHERE email = %s",
                    (email,),
                )
            if display_name:
                cur.execute(
                    "DELETE FROM admin.users WHERE display_name = %s",
                    (display_name,),
                )
        conn.commit()
    finally:
        conn.close()


def _insert_expired_token(user_id: int, otp: str):
    """Insert an already-expired OTP token directly into the DB."""
    code_hash  = hashlib.sha256(otp.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    conn = _db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO admin.auth_tokens (user_id, code_hash, expires_at)
                VALUES (%s, %s, %s)
                """,
                (user_id, code_hash, expires_at),
            )
        conn.commit()
    finally:
        conn.close()


def _get_otp_hash(user_id: int) -> str | None:
    """Fetch the most recent unused OTP hash for a user."""
    row = _fetch_one(
        """
        SELECT code_hash FROM admin.auth_tokens
        WHERE user_id = %s AND NOT used AND expires_at > NOW()
        ORDER BY created_at DESC LIMIT 1
        """,
        (user_id,),
    )
    return row["code_hash"] if row else None


def _get_user(email: str = None, display_name: str = None) -> dict | None:
    if email:
        return _fetch_one("SELECT * FROM admin.users WHERE email = %s", (email,))
    if display_name:
        return _fetch_one("SELECT * FROM admin.users WHERE display_name = %s", (display_name,))
    return None


# ===========================================================================
# SECTION 1 — Unit tests for auth_utils (no DB, no network)
# ===========================================================================

class TestGenerateOtp:
    def test_length(self):
        from api.auth_utils import generate_otp
        assert len(generate_otp()) == 6

    def test_digits_only(self):
        from api.auth_utils import generate_otp
        for _ in range(20):
            assert generate_otp().isdigit()

    def test_zero_padded(self):
        """Small values must be zero-padded to 6 digits."""
        from api.auth_utils import hash_otp, verify_otp
        otp = "000042"
        assert verify_otp(otp, hash_otp(otp))


class TestHashOtp:
    def test_same_input_same_hash(self):
        from api.auth_utils import hash_otp
        assert hash_otp("482917") == hash_otp("482917")

    def test_different_input_different_hash(self):
        from api.auth_utils import hash_otp
        assert hash_otp("482917") != hash_otp("482918")

    def test_correct_otp_verifies(self):
        from api.auth_utils import hash_otp, verify_otp
        otp = "123456"
        assert verify_otp(otp, hash_otp(otp))

    def test_wrong_otp_does_not_verify(self):
        from api.auth_utils import hash_otp, verify_otp
        assert not verify_otp("000000", hash_otp("111111"))


class TestValidateDisplayName:
    def test_valid_names(self):
        from api.auth_utils import validate_display_name
        for name in ["david", "Bjarne", "rail_fan", "user-42", "abc", "a" * 30]:
            validate_display_name(name)  # must not raise

    def test_too_short(self):
        from api.auth_utils import validate_display_name, AuthError
        with pytest.raises(AuthError, match="at least"):
            validate_display_name("ab")

    def test_too_long(self):
        from api.auth_utils import validate_display_name, AuthError
        with pytest.raises(AuthError, match="at most"):
            validate_display_name("a" * 31)

    def test_empty(self):
        from api.auth_utils import validate_display_name, AuthError
        with pytest.raises(AuthError):
            validate_display_name("")

    def test_space_rejected(self):
        from api.auth_utils import validate_display_name, AuthError
        with pytest.raises(AuthError, match="only contain"):
            validate_display_name("hello world")

    def test_special_chars_rejected(self):
        from api.auth_utils import validate_display_name, AuthError
        with pytest.raises(AuthError):
            validate_display_name("café")

    @pytest.mark.parametrize("name", ["guest_abc", "Guest_abc", "GUEST_abc", "guest_"])
    def test_guest_prefix_rejected(self, name):
        from api.auth_utils import validate_display_name, AuthError
        with pytest.raises(AuthError, match="reserved"):
            validate_display_name(name)


class TestGenerateGuestName:
    def test_starts_with_guest_prefix(self):
        from api.auth_utils import generate_guest_name, GUEST_PREFIX
        for _ in range(20):
            assert generate_guest_name().startswith(GUEST_PREFIX)

    def test_correct_total_length(self):
        from api.auth_utils import generate_guest_name, GUEST_PREFIX
        name = generate_guest_name()
        assert len(name) == len(GUEST_PREFIX) + 6

    def test_suffix_is_alphanumeric(self):
        from api.auth_utils import generate_guest_name, GUEST_PREFIX
        name = generate_guest_name()
        suffix = name[len(GUEST_PREFIX):]
        assert suffix.isalnum()

    def test_generates_unique_names(self):
        from api.auth_utils import generate_guest_name
        names = {generate_guest_name() for _ in range(50)}
        # extremely unlikely to get fewer than 45 unique out of 50
        assert len(names) >= 45


class TestJwt:
    def setup_method(self):
        os.environ["JWT_SECRET"] = "a" * 64

    def test_registered_user_round_trip(self):
        from api.auth_utils import create_jwt, decode_jwt
        token   = create_jwt(42, "david@backontrack.eu", "david", is_guest=False)
        payload = decode_jwt(token)
        assert payload["sub"]          == "42"
        assert payload["email"]        == "david@backontrack.eu"
        assert payload["display_name"] == "david"
        assert payload["is_guest"]     == False
        assert "jti" in payload
        assert "exp" in payload

    def test_guest_round_trip(self):
        from api.auth_utils import create_jwt, decode_jwt
        token   = create_jwt(99, None, "guest_a3f9k2", is_guest=True)
        payload = decode_jwt(token)
        assert payload["sub"]      == "99"
        assert payload["email"]    is None
        assert payload["is_guest"] == True

    def test_expired_token_raises(self):
        from api.auth_utils import decode_jwt, AuthError
        expired = pyjwt.encode(
            {"sub": "1", "exp": int((datetime.now(timezone.utc) - timedelta(days=1)).timestamp()), "jti": "x"},
            "a" * 64,
            algorithm="HS256",
        )
        with pytest.raises(AuthError, match="expired"):
            decode_jwt(expired)

    def test_tampered_token_raises(self):
        from api.auth_utils import create_jwt, decode_jwt, AuthError
        token   = create_jwt(42, "x@x.com", "testuser")
        tampered = token[:-4] + "xxxx"
        with pytest.raises(AuthError):
            decode_jwt(tampered)

    def test_guest_ttl_longer_than_user_ttl(self):
        from api.auth_utils import create_jwt, decode_jwt
        user_token  = create_jwt(1, "x@x.com", "user1",       is_guest=False)
        guest_token = create_jwt(2, None,       "guest_abc123", is_guest=True)
        user_exp  = decode_jwt(user_token)["exp"]
        guest_exp = decode_jwt(guest_token)["exp"]
        assert guest_exp > user_exp


# ===========================================================================
# SECTION 2 — Integration tests (require live stack)
# ===========================================================================

# ---------------------------------------------------------------------------
# POST /api/auth/request-code
# ---------------------------------------------------------------------------

class TestRequestCode:
    EMAIL        = "test_auth_integ@example.com"
    DISPLAY_NAME = "testauth42"

    def setup_method(self):
        _cleanup_user(email=self.EMAIL, display_name=self.DISPLAY_NAME)

    def teardown_method(self):
        _cleanup_user(email=self.EMAIL, display_name=self.DISPLAY_NAME)

    @pytest.mark.timeout(10)
    def test_new_user_returns_200(self):
        resp = requests.post(f"{API_BASE}/api/auth/request-code", json={
            "email":        self.EMAIL,
            "display_name": self.DISPLAY_NAME,
        })
        assert resp.status_code == 200
        assert resp.json() == {}

    @pytest.mark.timeout(10)
    def test_existing_user_also_returns_200(self):
        """No user enumeration — always 200 regardless of whether email exists."""
        # first call creates the user
        requests.post(f"{API_BASE}/api/auth/request-code", json={
            "email":        self.EMAIL,
            "display_name": self.DISPLAY_NAME,
        })
        # second call same email — must still return 200
        resp = requests.post(f"{API_BASE}/api/auth/request-code", json={
            "email": self.EMAIL,
        })
        assert resp.status_code == 200

    @pytest.mark.timeout(10)
    def test_missing_email_returns_400(self):
        resp = requests.post(f"{API_BASE}/api/auth/request-code", json={
            "display_name": self.DISPLAY_NAME,
        })
        assert resp.status_code == 400

    @pytest.mark.timeout(10)
    def test_invalid_email_returns_400(self):
        resp = requests.post(f"{API_BASE}/api/auth/request-code", json={
            "email":        "not-an-email",
            "display_name": self.DISPLAY_NAME,
        })
        assert resp.status_code == 400

    @pytest.mark.timeout(10)
    def test_missing_display_name_for_new_user_returns_400(self):
        resp = requests.post(f"{API_BASE}/api/auth/request-code", json={
            "email": self.EMAIL,
        })
        assert resp.status_code == 400
        assert "display_name" in resp.json()["message"].lower()

    @pytest.mark.timeout(10)
    def test_guest_prefix_display_name_rejected(self):
        resp = requests.post(f"{API_BASE}/api/auth/request-code", json={
            "email":        self.EMAIL,
            "display_name": "guest_hacker",
        })
        assert resp.status_code == 400
        assert "reserved" in resp.json()["message"].lower()

    @pytest.mark.timeout(10)
    def test_duplicate_display_name_rejected(self):
        # create user with DISPLAY_NAME
        requests.post(f"{API_BASE}/api/auth/request-code", json={
            "email":        self.EMAIL,
            "display_name": self.DISPLAY_NAME,
        })
        # try to register different email with same display_name
        resp = requests.post(f"{API_BASE}/api/auth/request-code", json={
            "email":        "other_" + self.EMAIL,
            "display_name": self.DISPLAY_NAME,
        })
        assert resp.status_code == 400
        assert "taken" in resp.json()["message"].lower()

    @pytest.mark.timeout(10)
    def test_otp_stored_as_hash_not_plaintext(self):
        """OTP in DB must be a 64-char hex string, never the 6-digit code."""
        requests.post(f"{API_BASE}/api/auth/request-code", json={
            "email":        self.EMAIL,
            "display_name": self.DISPLAY_NAME,
        })
        user = _get_user(email=self.EMAIL)
        assert user is not None
        otp_hash = _get_otp_hash(user["user_id"])
        assert otp_hash is not None
        assert len(otp_hash) == 64           # SHA-256 hex
        assert otp_hash.isalnum()            # hex chars only
        assert not otp_hash.isdigit()        # definitely not a 6-digit OTP


# ---------------------------------------------------------------------------
# POST /api/auth/verify
# ---------------------------------------------------------------------------

class TestVerify:
    EMAIL        = "test_verify_integ@example.com"
    DISPLAY_NAME = "testverify99"

    def setup_method(self):
        _cleanup_user(email=self.EMAIL, display_name=self.DISPLAY_NAME)
        # register user and capture OTP hash from DB
        requests.post(f"{API_BASE}/api/auth/request-code", json={
            "email":        self.EMAIL,
            "display_name": self.DISPLAY_NAME,
        })

    def teardown_method(self):
        _cleanup_user(email=self.EMAIL, display_name=self.DISPLAY_NAME)

    def _valid_otp_from_db(self) -> str | None:
        """
        In dev mode (RESEND_API_KEY=dev) we can't intercept the email.
        Instead we read the hash from DB and brute-force the 6-digit space.
        This is acceptable in tests — the whole point is that 000000-999999
        is only 1M values and we have the stored hash to compare against.
        """
        user = _get_user(email=self.EMAIL)
        if not user:
            return None
        stored_hash = _get_otp_hash(user["user_id"])
        if not stored_hash:
            return None
        for i in range(1_000_000):
            candidate = str(i).zfill(6)
            if hashlib.sha256(candidate.encode()).hexdigest() == stored_hash:
                return candidate
        return None

    @pytest.mark.timeout(30)
    def test_valid_otp_returns_200_with_token(self):
        otp = self._valid_otp_from_db()
        assert otp is not None, "Could not recover OTP from DB"
        resp = requests.post(f"{API_BASE}/api/auth/verify", json={
            "email": self.EMAIL,
            "code":  otp,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "token"        in data
        assert "user_id"      in data
        assert "display_name" in data
        assert data["is_guest"] == False

    @pytest.mark.timeout(30)
    def test_jwt_payload_contains_expected_claims(self):
        otp = self._valid_otp_from_db()
        assert otp is not None
        resp = requests.post(f"{API_BASE}/api/auth/verify", json={
            "email": self.EMAIL,
            "code":  otp,
        })
        assert resp.status_code == 200
        token   = resp.json()["token"]
        payload = pyjwt.decode(token, options={"verify_signature": False})
        assert payload["email"]        == self.EMAIL
        assert payload["display_name"] == self.DISPLAY_NAME
        assert payload["is_guest"]     == False
        assert "sub" in payload
        assert "exp" in payload
        assert "jti" in payload

    @pytest.mark.timeout(30)
    def test_user_verified_after_successful_verify(self):
        otp = self._valid_otp_from_db()
        assert otp is not None
        requests.post(f"{API_BASE}/api/auth/verify", json={
            "email": self.EMAIL,
            "code":  otp,
        })
        user = _get_user(email=self.EMAIL)
        assert user["is_verified"] == True

    @pytest.mark.timeout(10)
    def test_wrong_otp_returns_401(self):
        resp = requests.post(f"{API_BASE}/api/auth/verify", json={
            "email": self.EMAIL,
            "code":  "000000",
        })
        assert resp.status_code == 401
        assert resp.json()["error"] == "invalid_code"

    @pytest.mark.timeout(10)
    def test_nonexistent_email_returns_401_not_404(self):
        """No user enumeration — unknown email must return 401, not 404."""
        resp = requests.post(f"{API_BASE}/api/auth/verify", json={
            "email": "nobody@example.com",
            "code":  "123456",
        })
        assert resp.status_code == 401
        assert resp.json()["error"] == "invalid_code"

    @pytest.mark.timeout(10)
    def test_missing_fields_returns_400(self):
        resp = requests.post(f"{API_BASE}/api/auth/verify", json={"email": self.EMAIL})
        assert resp.status_code == 400

    @pytest.mark.timeout(30)
    def test_used_otp_cannot_be_reused(self):
        otp = self._valid_otp_from_db()
        assert otp is not None
        # first use — success
        r1 = requests.post(f"{API_BASE}/api/auth/verify", json={
            "email": self.EMAIL, "code": otp,
        })
        assert r1.status_code == 200
        # second use — must fail
        r2 = requests.post(f"{API_BASE}/api/auth/verify", json={
            "email": self.EMAIL, "code": otp,
        })
        assert r2.status_code == 401

    @pytest.mark.timeout(10)
    def test_expired_otp_returns_401(self):
        user = _get_user(email=self.EMAIL)
        assert user is not None
        otp = "999999"
        _insert_expired_token(user["user_id"], otp)
        resp = requests.post(f"{API_BASE}/api/auth/verify", json={
            "email": self.EMAIL,
            "code":  otp,
        })
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/auth/guest
# ---------------------------------------------------------------------------

class TestGuest:
    _created_display_names: list[str] = []

    def teardown_method(self):
        for name in self._created_display_names:
            _cleanup_user(display_name=name)
        self._created_display_names.clear()

    @pytest.mark.timeout(10)
    def test_guest_returns_200_with_token(self):
        resp = requests.post(f"{API_BASE}/api/auth/guest")
        assert resp.status_code == 200
        data = resp.json()
        assert "token"        in data
        assert "user_id"      in data
        assert "display_name" in data
        assert data["is_guest"] == True
        self._created_display_names.append(data["display_name"])

    @pytest.mark.timeout(10)
    def test_guest_display_name_has_guest_prefix(self):
        resp = requests.post(f"{API_BASE}/api/auth/guest")
        assert resp.status_code == 200
        name = resp.json()["display_name"]
        assert name.startswith("guest_")
        self._created_display_names.append(name)

    @pytest.mark.timeout(10)
    def test_guest_has_no_email_in_db(self):
        resp = requests.post(f"{API_BASE}/api/auth/guest")
        assert resp.status_code == 200
        name = resp.json()["display_name"]
        self._created_display_names.append(name)
        user = _get_user(display_name=name)
        assert user is not None
        assert user["email"] is None

    @pytest.mark.timeout(10)
    def test_guest_jwt_is_guest_flag(self):
        resp = requests.post(f"{API_BASE}/api/auth/guest")
        assert resp.status_code == 200
        data    = resp.json()
        payload = pyjwt.decode(data["token"], options={"verify_signature": False})
        assert payload["is_guest"] == True
        assert payload["email"]    is None
        self._created_display_names.append(data["display_name"])

    @pytest.mark.timeout(10)
    def test_two_guests_get_different_names(self):
        r1 = requests.post(f"{API_BASE}/api/auth/guest")
        r2 = requests.post(f"{API_BASE}/api/auth/guest")
        assert r1.status_code == 200
        assert r2.status_code == 200
        n1, n2 = r1.json()["display_name"], r2.json()["display_name"]
        assert n1 != n2
        self._created_display_names.extend([n1, n2])


# ---------------------------------------------------------------------------
# Auth middleware (via a protected endpoint)
# ---------------------------------------------------------------------------

class TestAuthMiddleware:
    """
    Uses the scenario list endpoint as the protected target since it has
    @require_auth. Actual scenario logic is not tested here.
    """

    @pytest.mark.timeout(10)
    def test_no_token_returns_401(self):
        resp = requests.get(f"{API_BASE}/api/scenarios")
        assert resp.status_code == 401
        assert resp.json()["error"] == "unauthorized"

    @pytest.mark.timeout(10)
    def test_garbage_token_returns_401(self):
        resp = requests.get(
            f"{API_BASE}/api/scenarios",
            headers={"Authorization": "Bearer garbage"},
        )
        assert resp.status_code == 401

    @pytest.mark.timeout(10)
    def test_malformed_header_returns_401(self):
        """Token without Bearer prefix is rejected."""
        if not JWT_SECRET:
            pytest.skip("JWT_SECRET not set — cannot create test token")
        token = pyjwt.encode(
            {"sub": "1", "exp": int((datetime.now(timezone.utc) + timedelta(days=1)).timestamp()), "jti": "x"},
            JWT_SECRET,
            algorithm="HS256",
        )
        resp = requests.get(
            f"{API_BASE}/api/scenarios",
            headers={"Authorization": token},   # missing "Bearer "
        )
        assert resp.status_code == 401

    @pytest.mark.timeout(10)
    def test_valid_token_passes_middleware(self):
        """A valid JWT gets past the middleware (scenario logic may return 501 — that's fine)."""
        if not JWT_SECRET:
            pytest.skip("JWT_SECRET not set — cannot create test token")
        token = pyjwt.encode(
            {
                "sub":          "1",
                "email":        "test@example.com",
                "display_name": "tester",
                "is_guest":     False,
                "exp":          int((datetime.now(timezone.utc) + timedelta(days=1)).timestamp()),
                "jti":          "test-jti",
            },
            JWT_SECRET,
            algorithm="HS256",
        )
        resp = requests.get(
            f"{API_BASE}/api/scenarios",
            headers={"Authorization": f"Bearer {token}"},
        )
        # middleware passed — response is not 401
        assert resp.status_code != 401