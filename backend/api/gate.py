"""gate.py — testing-party access gate (2026-08-13 session, Decision 2).

A **gate, not authentication**. A tester redeems a tester-specific code
once per browser; behind the gate they exercise the real OTP login flow as
if they were a real user. Keeping the two mechanisms separate is the whole
point: the party has to test signup for real, so the gate must not be a
login.

It replaces the shared ``volunteer`` basic_auth credential, which wrapped
even the OTP flow (a tester who entered their emailed code was then asked
for a second, unrelated password) and whose credential leaked in board
minutes.

Endpoints — all three are reachable *without* a cookie; everything else on
the site sits behind ``forward_auth`` pointing at ``/api/gate/check``:

    GET  /gate               the public countdown page, with the code form
                             demoted into its footer. Inline rather than a Vue
                             view so the gate does not depend on a frontend
                             build or a template directory -- and, since
                             forward_auth redirects every cookie-less visitor
                             here before the SPA loads, a Vue implementation
                             would never be seen by the audience it is for.
    POST /api/gate/redeem    code -> signed cookie + a redemption row.
    GET  /api/gate/check     forward_auth target. 204 when the cookie is
                             valid, 302 to /gate when it is not, so Caddy
                             hands the redirect straight to the browser.

Two deliberate choices worth stating:

* **No Flask-Limiter decorator here.** The limiter keys on
  ``get_remote_address``, which behind Caddy is the proxy hop, so a limit
  would be a single room-wide bucket — at a party of 15-30 that locks
  people out rather than protecting anything. The code itself is the
  control, and an invalid code costs one indexed primary-key lookup.
* **Short-lived connections, autocommit, always closed.** Not the
  module-level singleton pattern used elsewhere in the api: that pattern
  is what leaves connections idle-in-transaction (``DBDataLoader`` holds
  two on staging, four days old), which in turn blocks DDL. A gate that
  every request touches must not add to that.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

import jwt
import psycopg2
from flask import Blueprint, Response, jsonify, make_response, redirect, request

from api.gate_page import page_html

log = logging.getLogger(__name__)

bp = Blueprint("gate", __name__)

COOKIE_NAME = "tn_gate"
_AUDIENCE = "tn-gate"
_TTL_DAYS = 30


def _secret() -> str:
    secret = os.environ.get("JWT_SECRET", "")
    if not secret:
        # Same hard requirement as the auth plane: fail loudly, never
        # fall back to an unsigned or default-keyed cookie.
        raise RuntimeError("JWT_SECRET is not configured.")
    return secret


def _connect():
    conn = psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST"),
        port=os.environ.get("POSTGRES_PORT", "5432"),
        dbname=os.environ.get("POSTGRES_DB"),
        user=os.environ.get("POSTGRES_USER"),
        password=os.environ.get("POSTGRES_PASSWORD"),
    )
    conn.autocommit = True
    return conn


def _issue_cookie(response: Response, code: str) -> Response:
    payload = {
        "aud": _AUDIENCE,
        "code": code,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(days=_TTL_DAYS),
    }
    token = jwt.encode(payload, _secret(), algorithm="HS256")
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=_TTL_DAYS * 24 * 3600,
        secure=True,
        httponly=True,
        samesite="Lax",
        path="/",
    )
    return response


def _cookie_code() -> str | None:
    """The code a valid gate cookie names, or None."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    try:
        payload = jwt.decode(token, _secret(), algorithms=["HS256"], audience=_AUDIENCE)
    except jwt.PyJWTError:
        return None
    return payload.get("code")


def _render(error: str | None = None, status: int = 200) -> Response:
    resp = make_response(page_html(error), status)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.get("/gate")
def gate_page() -> Response:
    if _cookie_code():
        return redirect("/", code=302)
    return _render()


@bp.get("/api/gate/check")
def gate_check() -> Response:
    """forward_auth target. 204 = let the request through."""
    if _cookie_code():
        return Response(status=204)
    # Caddy forwards a non-2xx response to the client verbatim, so this
    # redirect is what an ungated visitor actually receives.
    return redirect("/gate", code=302)


@bp.post("/api/gate/redeem")
def gate_redeem() -> Response:
    submitted = (request.form.get("code") or "").strip()
    if not submitted and request.is_json:
        submitted = str((request.get_json(silent=True) or {}).get("code", "")).strip()
    wants_json = request.is_json or "application/json" in request.headers.get(
        "Accept", ""
    )

    if not submitted:
        return (
            jsonify(error="code required")
            if wants_json
            else _render("Please enter a code.", 400)
        )

    conn = None
    try:
        conn = _connect()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.code,
                       c.revoked_at,
                       c.max_redemptions,
                       (SELECT count(*) FROM admin.access_code_redemptions r
                         WHERE r.code = c.code) AS used
                  FROM admin.access_codes c
                 WHERE lower(c.code) = lower(%s)
                """,
                (submitted,),
            )
            row = cur.fetchone()

            if row is None:
                log.info("gate: rejected unknown code")
                return (
                    (jsonify(error="unknown code"), 403)
                    if wants_json
                    else _render("That code is not valid.", 403)
                )

            code, revoked_at, max_redemptions, used = row
            if revoked_at is not None:
                log.info("gate: rejected revoked code %s", code)
                return (
                    (jsonify(error="code revoked"), 403)
                    if wants_json
                    else _render("That code has been revoked.", 403)
                )
            if max_redemptions and used >= max_redemptions:
                log.info("gate: code %s exhausted (%s/%s)", code, used, max_redemptions)
                return (
                    (jsonify(error="code exhausted"), 403)
                    if wants_json
                    else _render("That code has already been used.", 403)
                )

            cur.execute(
                """
                INSERT INTO admin.access_code_redemptions
                            (code, user_agent, remote_addr)
                     VALUES (%s, %s, %s)
                """,
                (
                    code,
                    (request.headers.get("User-Agent") or "")[:500],
                    request.remote_addr,
                ),
            )
        log.info("gate: code %s redeemed", code)
    except psycopg2.Error:
        log.exception("gate: database error on redeem")
        return (
            (jsonify(error="internal error"), 500)
            if wants_json
            else _render("Something went wrong. Please try again.", 500)
        )
    finally:
        if conn is not None:
            conn.close()

    resp = jsonify(ok=True) if wants_json else redirect("/", code=302)
    return _issue_cookie(make_response(resp), code)
