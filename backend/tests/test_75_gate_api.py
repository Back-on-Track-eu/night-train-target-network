"""
test_75_gate_api.py
===================
Integration tests for the testing-party access gate (api/gate.py, added
2026-08-17 per the 2026-08-13 session Decision 2).

The gate is NOT authentication: it decides who reaches the app at all, and
behind it testers exercise the real OTP flow as if they were real users. The
two planes must stay independent — the wrong-audience test below is the one
that pins that down, since a user's login JWT must not open the gate.

Follows the suite's convention: requests against the running stack
(API_BASE_URL) plus direct DB assertions via the session cursor. Codes are
inserted through the DB fixture and committed, because the API validates them
on its own connection.

Note on redirects: every negative gate answer is a 302 to /gate rather than a
401, because Caddy's forward_auth hands a non-2xx response straight to the
browser — so the redirect IS the user-visible behaviour. All requests here use
allow_redirects=False to assert on that status directly.
"""

import os
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
import requests

_TIMEOUT = 15
COOKIE = "tn_gate"


def _code() -> str:
    return f"zzt-{uuid.uuid4().hex[:8]}"


def _redeem(api_base, code, **kw):
    return requests.post(
        f"{api_base}/api/gate/redeem",
        data={"code": code},
        timeout=_TIMEOUT,
        allow_redirects=False,
        **kw,
    )


def _check(api_base, cookies=None, headers=None):
    return requests.get(
        f"{api_base}/api/gate/check",
        cookies=cookies or {},
        headers=headers or {},
        timeout=_TIMEOUT,
        allow_redirects=False,
    )


def _insert_code(db_cur, db_conn, *, revoked=False, max_redemptions=0):
    code = _code()
    db_cur.execute(
        "INSERT INTO admin.access_codes (code, label, issued_by, revoked_at, "
        "max_redemptions) VALUES (%s, %s, %s, %s, %s)",
        (
            code,
            "pytest fixture",
            "pytest",
            datetime.now(timezone.utc) if revoked else None,
            max_redemptions,
        ),
    )
    db_conn.commit()
    return code


def _drop_code(db_cur, db_conn, code):
    db_cur.execute("DELETE FROM admin.access_code_redemptions WHERE code = %s", (code,))
    db_cur.execute("DELETE FROM admin.access_codes WHERE code = %s", (code,))
    db_conn.commit()


@pytest.fixture
def live_code(db_cur, db_conn):
    code = _insert_code(db_cur, db_conn)
    yield code
    _drop_code(db_cur, db_conn, code)


# =============================================================================
# Code validation
# =============================================================================


def test_valid_code_redeems_and_sets_cookie(api_base, live_code):
    resp = _redeem(api_base, live_code)
    assert resp.status_code == 302
    assert COOKIE in resp.cookies
    # The gate cookie must not be readable by scripts, must not travel in the
    # clear, and must not ride cross-site requests.
    raw = resp.headers.get("Set-Cookie", "")
    assert "HttpOnly" in raw
    assert "Secure" in raw
    assert "SameSite=Lax" in raw


def test_unknown_code_rejected(api_base):
    assert _redeem(api_base, _code()).status_code == 403


def test_revoked_code_rejected(api_base, db_cur, db_conn):
    code = _insert_code(db_cur, db_conn, revoked=True)
    try:
        assert _redeem(api_base, code).status_code == 403
    finally:
        _drop_code(db_cur, db_conn, code)


def test_empty_code_is_a_bad_request(api_base):
    assert _redeem(api_base, "").status_code == 400


def test_code_match_is_case_insensitive_and_trimmed(api_base, live_code):
    assert _redeem(api_base, f"  {live_code.upper()}  ").status_code == 302


def test_single_use_code_is_exhausted_after_one_redemption(api_base, db_cur, db_conn):
    code = _insert_code(db_cur, db_conn, max_redemptions=1)
    try:
        assert _redeem(api_base, code).status_code == 302
        assert _redeem(api_base, code).status_code == 403
    finally:
        _drop_code(db_cur, db_conn, code)


def test_unlimited_code_allows_a_second_device(api_base, live_code):
    # max_redemptions = 0 is deliberate: one tester, phone AND laptop.
    assert _redeem(api_base, live_code).status_code == 302
    assert _redeem(api_base, live_code).status_code == 302


def test_json_client_gets_json(api_base, live_code):
    resp = requests.post(
        f"{api_base}/api/gate/redeem",
        json={"code": live_code},
        timeout=_TIMEOUT,
        allow_redirects=False,
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


# =============================================================================
# Cookie handling — what forward_auth actually consults
# =============================================================================


def test_check_passes_with_a_freshly_issued_cookie(api_base, live_code):
    issued = _redeem(api_base, live_code)
    resp = _check(api_base, cookies={COOKIE: issued.cookies[COOKIE]})
    assert resp.status_code == 204


def test_check_without_cookie_redirects_to_gate(api_base):
    resp = _check(api_base)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/gate")


def test_check_rejects_garbage_cookie(api_base):
    assert _check(api_base, cookies={COOKIE: "not-a-jwt"}).status_code == 302


def test_check_rejects_tampered_signature(api_base, live_code):
    token = _redeem(api_base, live_code).cookies[COOKIE]
    # Flip a character in the MIDDLE of the signature segment. The final
    # base64url character encodes only 4 significant bits, so flipping it
    # sometimes decodes to the identical signature bytes (U/V/W -> X) and
    # the check rightly returns 204 — a ~3/64 flake, not a security hole.
    header, payload, sig = token.split(".")
    mid = len(sig) // 2
    flipped = "X" if sig[mid] != "X" else "Y"
    tampered = f"{header}.{payload}.{sig[:mid]}{flipped}{sig[mid + 1:]}"
    assert _check(api_base, cookies={COOKIE: tampered}).status_code == 302


# The forged-token cases need the same signing key the API uses. Skipped rather
# than failed where the suite runs without it in the environment.
_SECRET = os.environ.get("JWT_SECRET", "")
_needs_secret = pytest.mark.skipif(
    not _SECRET, reason="JWT_SECRET not in the test environment"
)


def _forge(payload, secret=None):
    return jwt.encode(payload, secret or _SECRET, algorithm="HS256")


@_needs_secret
def test_check_rejects_token_signed_with_another_secret(api_base):
    token = _forge(
        {
            "aud": "tn-gate",
            "code": "anything",
            "exp": datetime.now(timezone.utc) + timedelta(days=1),
        },
        secret="a-different-secret-entirely",
    )
    assert _check(api_base, cookies={COOKIE: token}).status_code == 302


@_needs_secret
def test_check_rejects_expired_token(api_base):
    token = _forge(
        {
            "aud": "tn-gate",
            "code": "anything",
            "exp": datetime.now(timezone.utc) - timedelta(seconds=10),
        }
    )
    assert _check(api_base, cookies={COOKIE: token}).status_code == 302


@_needs_secret
def test_a_user_token_cannot_open_the_gate(api_base):
    """The gate and the auth plane are separate mechanisms. A correctly-signed
    token for any other audience must not satisfy the gate."""
    token = _forge(
        {
            "aud": "tn-user",
            "code": "anything",
            "exp": datetime.now(timezone.utc) + timedelta(days=1),
        }
    )
    assert _check(api_base, cookies={COOKIE: token}).status_code == 302


# =============================================================================
# Open paths, and the audit trail
# =============================================================================


def test_gate_page_is_reachable_without_a_cookie(api_base):
    resp = requests.get(f"{api_base}/gate", timeout=_TIMEOUT)
    assert resp.status_code == 200
    assert "Testing code" in resp.text


def test_health_stays_open_without_a_cookie(api_base):
    resp = requests.get(f"{api_base}/api/health", timeout=_TIMEOUT)
    assert resp.status_code == 200


def test_redemption_is_logged_with_the_browser(api_base, live_code, db_cur):
    ua = f"pytest-agent/{uuid.uuid4().hex[:6]}"
    _redeem(api_base, live_code, headers={"User-Agent": ua})
    db_cur.execute(
        "SELECT user_agent FROM admin.access_code_redemptions "
        "WHERE code = %s ORDER BY id DESC LIMIT 1",
        (live_code,),
    )
    row = db_cur.fetchone()
    assert row is not None, "redemption was not recorded"
    # Per-tester browser attribution is the whole point of the table: it is what
    # makes a browser-specific bug findable during a testing party.
    assert row["user_agent"] == ua


def test_rejected_code_writes_no_redemption(api_base, db_cur):
    unknown = _code()
    _redeem(api_base, unknown)
    db_cur.execute(
        "SELECT count(*) AS n FROM admin.access_code_redemptions WHERE code = %s",
        (unknown,),
    )
    assert db_cur.fetchone()["n"] == 0
