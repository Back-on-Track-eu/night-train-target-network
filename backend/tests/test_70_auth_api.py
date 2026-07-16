"""
test_70_auth_api.py
===================
Integration tests for the local auth plane (api/auth.py) — request-code,
verify, guest — plus the identity-override wiring on feedback/proposal
submission. Follows the suite's convention: requests against the running
stack (API_BASE_URL) + direct DB assertions via the session cursor.

OTPs are never exposed by the API (hashed at rest, mailed or logged
server-side), so the verify-flow tests inject a token row with a KNOWN
plaintext's hash through the DB fixture and then verify against it —
same trust boundary as the server, no mail lane needed.

Rate limits: the stack under test should run TESTING=true (CI does).
Against a stack with limits on, request-code tests may 429 — they skip
rather than fail in that case.
"""

import uuid

import pytest
import requests

from api.auth_utils import hash_otp
from tests.helpers import PROPOSAL_URL, evaluate

_TIMEOUT = 15


def _unique_email() -> str:
    return f"test-{uuid.uuid4().hex[:12]}@example.org"


def _unique_name() -> str:
    return f"tester-{uuid.uuid4().hex[:8]}"


def _post(api_base, path, body):
    return requests.post(f"{api_base}{path}", json=body, timeout=_TIMEOUT)


def _skip_if_rate_limited(resp):
    if resp.status_code == 429:
        pytest.skip("auth endpoint rate-limited on this stack (TESTING!=true)")


# =============================================================================
# POST /api/auth/request-code
# =============================================================================


def test_request_code_requires_email(api_base):
    resp = _post(api_base, "/api/auth/request-code", {})
    _skip_if_rate_limited(resp)
    assert resp.status_code == 400
    assert resp.json()["error"] == "bad_request"


def test_request_code_rejects_bad_email(api_base):
    resp = _post(api_base, "/api/auth/request-code", {"email": "not-an-email"})
    _skip_if_rate_limited(resp)
    assert resp.status_code == 400


def test_request_code_new_user_requires_display_name(api_base):
    resp = _post(api_base, "/api/auth/request-code", {"email": _unique_email()})
    _skip_if_rate_limited(resp)
    assert resp.status_code == 400
    assert "display_name" in resp.json()["message"]


def test_request_code_rejects_guest_prefixed_name(api_base):
    resp = _post(
        api_base,
        "/api/auth/request-code",
        {"email": _unique_email(), "display_name": "guest_impostor"},
    )
    _skip_if_rate_limited(resp)
    assert resp.status_code == 400


def test_request_code_creates_user_and_token(api_base, db_cur):
    """Happy path: user row (unverified) + one live OTP row appear. The
    endpoint returns 200 when the mail lane works (dev mode) or 502 when
    unconfigured — the DB writes happen either way, by design (the code
    is stored before the send so a failed mail is retryable)."""
    email, name = _unique_email(), _unique_name()
    resp = _post(
        api_base, "/api/auth/request-code", {"email": email, "display_name": name}
    )
    _skip_if_rate_limited(resp)
    assert resp.status_code in (200, 502)

    db_cur.execute(
        "SELECT user_id, display_name, is_verified FROM admin.users WHERE email = %s",
        (email,),
    )
    user = db_cur.fetchone()
    assert user is not None
    assert user["display_name"] == name
    assert user["is_verified"] is False

    db_cur.execute(
        "SELECT COUNT(*) AS n FROM admin.auth_tokens "
        "WHERE user_id = %s AND NOT used AND expires_at > NOW()",
        (user["user_id"],),
    )
    assert db_cur.fetchone()["n"] == 1


def test_request_code_no_user_enumeration(api_base, db_cur):
    """Same 200 for an existing email (no display_name needed) — response
    body leaks nothing about whether the account existed."""
    email, name = _unique_email(), _unique_name()
    first = _post(
        api_base, "/api/auth/request-code", {"email": email, "display_name": name}
    )
    _skip_if_rate_limited(first)
    second = _post(api_base, "/api/auth/request-code", {"email": email})
    _skip_if_rate_limited(second)
    assert second.status_code == first.status_code
    assert second.json() == first.json()

    # Re-request invalidated the first code: exactly one live token remains.
    db_cur.execute(
        "SELECT COUNT(*) AS n FROM admin.auth_tokens t "
        "JOIN admin.users u ON u.user_id = t.user_id "
        "WHERE u.email = %s AND NOT t.used AND t.expires_at > NOW()",
        (email,),
    )
    assert db_cur.fetchone()["n"] == 1


# =============================================================================
# POST /api/auth/verify
# =============================================================================


@pytest.fixture()
def user_with_known_otp(db_cur, db_conn):
    """A registered user with a live OTP whose plaintext the test knows —
    injected DB-side because the API (correctly) never returns codes."""
    email, name, otp = _unique_email(), _unique_name(), "271828"
    db_cur.execute(
        "INSERT INTO admin.users (email, display_name, is_verified) "
        "VALUES (%s, %s, FALSE) RETURNING user_id",
        (email, name),
    )
    user_id = db_cur.fetchone()["user_id"]
    db_cur.execute(
        "INSERT INTO admin.auth_tokens (user_id, code_hash, expires_at) "
        "VALUES (%s, %s, NOW() + INTERVAL '15 minutes')",
        (user_id, hash_otp(otp)),
    )
    db_conn.commit()
    return {"email": email, "display_name": name, "otp": otp, "user_id": user_id}


def test_verify_wrong_code_401(api_base, user_with_known_otp):
    resp = _post(
        api_base,
        "/api/auth/verify",
        {"email": user_with_known_otp["email"], "code": "000000"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"] == "invalid_code"


def test_verify_unknown_email_same_error(api_base):
    """Unknown email and wrong code are indistinguishable (no enumeration)."""
    resp = _post(
        api_base, "/api/auth/verify", {"email": _unique_email(), "code": "123456"}
    )
    assert resp.status_code == 401
    assert resp.json()["error"] == "invalid_code"


def test_verify_happy_path_and_single_use(api_base, db_cur, user_with_known_otp):
    fixture = user_with_known_otp
    resp = _post(
        api_base,
        "/api/auth/verify",
        {"email": fixture["email"], "code": fixture["otp"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == fixture["user_id"]
    assert body["display_name"] == fixture["display_name"]
    assert body["is_guest"] is False
    assert body["token"].count(".") == 2  # JWT shape

    db_cur.execute(
        "SELECT is_verified FROM admin.users WHERE user_id = %s",
        (fixture["user_id"],),
    )
    assert db_cur.fetchone()["is_verified"] is True

    # Same code again → consumed, 401.
    replay = _post(
        api_base,
        "/api/auth/verify",
        {"email": fixture["email"], "code": fixture["otp"]},
    )
    assert replay.status_code == 401


# =============================================================================
# POST /api/auth/guest
# =============================================================================


def test_guest_session(api_base, db_cur):
    resp = _post(api_base, "/api/auth/guest", {})
    _skip_if_rate_limited(resp)
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_guest"] is True
    assert body["display_name"].startswith("guest_")
    assert body["token"].count(".") == 2

    db_cur.execute(
        "SELECT email, is_verified FROM admin.users WHERE user_id = %s",
        (body["user_id"],),
    )
    row = db_cur.fetchone()
    assert row["email"] is None
    assert row["is_verified"] is False


# =============================================================================
# Token-over-body identity on feedback
# =============================================================================


def test_feedback_token_overrides_body_user_id(api_base, db_cur, user_with_known_otp):
    """A bearer token pins the author identity — the body's user_id is
    ignored, so tokens can't be used to impersonate other users."""
    fixture = user_with_known_otp
    verify = _post(
        api_base,
        "/api/auth/verify",
        {"email": fixture["email"], "code": fixture["otp"]},
    )
    assert verify.status_code == 200
    token = verify.json()["token"]

    resp = requests.post(
        f"{api_base}/api/feedback",
        json={
            "user_id": 1,  # someone else — must be overridden by the token
            "subject": "auth wiring test",
            "category": "Bug report",
            "sub_category": "auth",
            "message": "token-over-body identity check",
        },
        headers={"Authorization": f"Bearer {token}"},
        timeout=_TIMEOUT,
    )
    assert resp.status_code == 201
    feedback_id = resp.json()["feedback_id"]

    db_cur.execute(
        "SELECT user_id FROM admin.feedback WHERE feedback_id = %s", (feedback_id,)
    )
    assert db_cur.fetchone()["user_id"] == fixture["user_id"]


def test_feedback_garbage_token_401(api_base):
    resp = requests.post(
        f"{api_base}/api/feedback",
        json={
            "email": "anon@example.org",
            "subject": "x",
            "category": "Bug report",
            "sub_category": "auth",
            "message": "y",
        },
        headers={"Authorization": "Bearer not-a-jwt"},
        timeout=_TIMEOUT,
    )
    assert resp.status_code == 401


# =============================================================================
# Guest → registered merge on verify (persist-on-calc, 2026-07-16)
# =============================================================================
#
# The frontend's register-as-last-step flow: play around as a guest
# (persisting proposals along the way), then verify an email WITH the guest
# JWT attached as the bearer — everything the guest owns is reassigned to
# the verified account, and the guest session dies with an explicit
# account-merged error. Exercised against the permanent seed proposal so no
# route build is needed: a guest evaluating a foreign, not-yet-evaluated
# proposal branches it, which makes the guest an owner in one cheap call.

_SEED_PROPOSAL_ID = 1


def _fresh_otp_for(db_cur, db_conn, user_id: int, otp: str) -> None:
    db_cur.execute(
        "INSERT INTO admin.auth_tokens (user_id, code_hash, expires_at) "
        "VALUES (%s, %s, NOW() + INTERVAL '15 minutes')",
        (user_id, hash_otp(otp)),
    )
    db_conn.commit()


@pytest.mark.timeout(120)
def test_verify_with_guest_bearer_merges_guest_assets(api_base, db_cur, db_conn):
    """End to end: guest persists a proposal (branch-by-eval off the seed
    proposal), registers with the guest bearer attached, and afterwards the
    proposal belongs to the new account, the guest row is marked merged,
    the old guest token is rejected with the account-merged error, and a
    repeat merge attempt is an idempotent no-op. Sequential by design —
    each step is the precondition of the next."""
    # --- a guest who owns something ---
    resp = requests.post(f"{api_base}/api/auth/guest", timeout=10)
    _skip_if_rate_limited(resp)
    guest = resp.json()
    guest_headers = {"Authorization": f"Bearer {guest['token']}"}

    seed_route = requests.get(
        f"{api_base}{PROPOSAL_URL}/{_SEED_PROPOSAL_ID}", timeout=10
    ).json()["route_body"]["route"]
    branched = evaluate(api_base, seed_route, headers=guest_headers, timeout=90)
    branch_pid = branched["proposal"]["proposal_id"]
    assert branched["proposal"]["action"] == "branched"

    try:
        # --- register with the guest bearer attached ---
        email, name, otp = _unique_email(), _unique_name(), "314159"
        db_cur.execute(
            "INSERT INTO admin.users (email, display_name, is_verified) "
            "VALUES (%s, %s, FALSE) RETURNING user_id",
            (email, name),
        )
        user_id = db_cur.fetchone()["user_id"]
        db_conn.commit()
        _fresh_otp_for(db_cur, db_conn, user_id, otp)

        resp = requests.post(
            f"{api_base}/api/auth/verify",
            json={"email": email, "code": otp},
            headers=guest_headers,
            timeout=10,
        )
        assert resp.status_code == 200
        merged = resp.json()["merged_guest"]
        assert merged == {
            "guest_user_id": guest["user_id"],
            "proposals_claimed": 1,
            "feedback_claimed": 0,
        }

        # --- the proposal changed hands; the guest row is marked ---
        db_cur.execute(
            "SELECT user_id FROM proposals.proposals "
            "WHERE proposal_id = %s AND is_current",
            (branch_pid,),
        )
        assert db_cur.fetchone()["user_id"] == user_id
        db_cur.execute(
            "SELECT merged_into_user_id FROM admin.users WHERE user_id = %s",
            (guest["user_id"],),
        )
        assert db_cur.fetchone()["merged_into_user_id"] == user_id
        db_conn.rollback()

        # --- the old guest token now fails loudly, everywhere ---
        resp = requests.post(
            f"{api_base}/api/evaluation/calc",
            json={},
            headers=guest_headers,
            timeout=10,
        )
        assert resp.status_code == 401
        assert "merged" in resp.json()["message"].lower()

        # --- a second merge attempt is an idempotent no-op ---
        _fresh_otp_for(db_cur, db_conn, user_id, "271801")
        resp = requests.post(
            f"{api_base}/api/auth/verify",
            json={"email": email, "code": "271801"},
            headers=guest_headers,
            timeout=10,
        )
        assert resp.status_code == 200
        assert resp.json()["merged_guest"] is None
    finally:
        # Local cleanup — this file runs after test_50's module purge, so
        # the branch (proposal row + GTFS decomposition) is ours to remove.
        cur = db_conn.cursor()
        for table, column in (
            ("proposals.routes", "route_id"),
            ("proposals.shapes", "shape_id"),
            ("proposals.services", "service_id"),
        ):
            cur.execute(
                f"DELETE FROM {table} WHERE {column} LIKE %s",
                (f"P{branch_pid}" + r"\_%",),
            )
        cur.execute(
            "DELETE FROM proposals.proposals WHERE proposal_id = %s", (branch_pid,)
        )
        db_conn.commit()
        cur.close()


@pytest.mark.timeout(30)
def test_verify_with_invalid_bearer_still_succeeds(api_base, db_cur, db_conn):
    """An unusable Authorization header must never block the registration
    itself — merged_guest simply stays null."""
    email, name, otp = _unique_email(), _unique_name(), "161803"
    db_cur.execute(
        "INSERT INTO admin.users (email, display_name, is_verified) "
        "VALUES (%s, %s, FALSE) RETURNING user_id",
        (email, name),
    )
    user_id = db_cur.fetchone()["user_id"]
    db_conn.commit()
    _fresh_otp_for(db_cur, db_conn, user_id, otp)

    resp = requests.post(
        f"{api_base}/api/auth/verify",
        json={"email": email, "code": otp},
        headers={"Authorization": "Bearer not-a-jwt"},
        timeout=10,
    )
    assert resp.status_code == 200
    assert resp.json()["merged_guest"] is None