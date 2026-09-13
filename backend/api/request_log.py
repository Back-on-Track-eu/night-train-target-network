"""
request_log.py
==============
Writes one admin.request_log row per served API request — the Flask hook
pair, the exclusion rule, and the client pseudonym. The row itself is
described in db/dev/sql/create_admin_schema.sql; this module is only
about how it gets there.

What it is for, in order of weight:
  1. Usage evidence for the network proposal — how many people used the
     tool, which parts, when. Nothing else in the database answers it:
     proposals record what was PUBLISHED, a small fraction of what was
     tried.
  2. Operations — status, latency and payload size per endpoint.
  3. Abuse — client_hash correlates one client within a UTC day.

Three rules it never breaks
---------------------------
1. It cannot fail a request. Every write is wrapped; a broken database
   costs a log line, never a 500. This is why get_request_log_repository()
   returns None instead of raising, unlike every other accessor in
   api/helpers/dependencies.py.
2. It cannot change auth behaviour. Identity is taken from `g` when a
   decorator already resolved it, and otherwise from
   auth_middleware.resolve_identity_quietly(), which swallows what the
   decorators raise on. An invalid token still 401s where it always did;
   here it simply logs as anonymous.
3. It stores no IP address. _client_hash() is an HMAC over the UTC date
   and the client address, so it correlates within a day and is
   unlinkable across days — see the column comment.

Hook ordering
-------------
Flask runs after_request functions in REVERSE registration order, and
main.py calls Compress(app) before register(app). Ours therefore runs
FIRST, and reads content_length before gzip — the payload size rather
than the transfer size, which is the more meaningful of the two here.

before_request only stamps a clock. Identity resolution and the hash are
deferred to after_request so an excluded endpoint (health, gate) costs
nothing but a perf_counter() call.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from datetime import datetime, timezone

from flask import Flask, Response, g, request

from api import config

logger = logging.getLogger(__name__)

# Consecutive write failures, reset by the next success. A database
# outage would otherwise emit one WARNING per request: the first failure
# is the incident, the next thousand are the same incident.
_failures = 0
_FAILURE_LOG_EVERY = 200


def register(app: Flask) -> None:
    """Attach the hooks. A no-op when REQUEST_LOG_ENABLED is false, so
    switching the log off costs nothing per request rather than costing a
    branch."""
    if not config.REQUEST_LOG_ENABLED:
        logger.info("Request log disabled (REQUEST_LOG_ENABLED=false).")
        return
    app.before_request(_stamp_start)
    app.after_request(_write_row)


# ---------------------------------------------------------------------------
# Hooks
# ---------------------------------------------------------------------------


def _stamp_start() -> None:
    g._request_log_start = time.perf_counter()


def _write_row(response: Response) -> Response:
    global _failures
    try:
        _insert(response)
    except Exception:
        _failures += 1
        if _failures == 1 or _failures % _FAILURE_LOG_EVERY == 0:
            logger.warning(
                "Request log write failed (%d consecutive). The request was "
                "served normally.",
                _failures,
                exc_info=True,
            )
    else:
        _failures = 0
    return response


def _insert(response: Response) -> None:
    endpoint = request.endpoint
    if is_excluded(endpoint, request.method):
        return

    # Late import: api.helpers.dependencies pulls in the adapters at
    # module load, and main.py imports this module while building the app.
    from api.helpers.dependencies import get_request_log_repository

    repo = get_request_log_repository()
    if repo is None:
        return

    user_id, is_guest, trust_level = _identity()
    repo.insert(
        method=request.method,
        endpoint=endpoint,
        route_rule=request.url_rule.rule if request.url_rule else None,
        status_code=response.status_code,
        duration_ms=_duration_ms(),
        user_id=user_id,
        is_guest=is_guest,
        trust_level=trust_level,
        client_hash=_client_hash(),
        response_bytes=response.content_length,
        user_agent=_truncate(request.headers.get("User-Agent")),
    )


# ---------------------------------------------------------------------------
# Row fields
# ---------------------------------------------------------------------------


def is_excluded(endpoint: str | None, method: str) -> bool:
    """Whether this request is deliberately not logged.

    OPTIONS is CORS preflight — it doubles every cross-origin call and
    says nothing about usage. The endpoint prefixes come from
    REQUEST_LOG_EXCLUDED_ENDPOINTS and exist for traffic that would
    dominate the table by volume alone: /api/health is polled by the
    frontend's useApiHealth and by container healthchecks, and /api/gate/*
    is hit on every page request by Caddy's forward_auth (and is testing
    scaffolding besides).

    An unmatched path (endpoint None, i.e. a 404) IS logged — a client
    calling an endpoint that does not exist is worth seeing.
    """
    if method == "OPTIONS":
        return True
    if endpoint is None:
        return False
    return endpoint.startswith(config.REQUEST_LOG_EXCLUDED_ENDPOINTS)


def _identity() -> tuple[int | None, bool, int | None]:
    """(user_id, is_guest, trust_level) for this request.

    An endpoint carrying @require_auth / @optional_auth / @require_trust
    has already resolved identity onto g — reuse it rather than decode the
    token twice. Most read endpoints carry no decorator at all, and those
    are exactly the ones this log exists to attribute, so the fallback
    does the work: one quiet resolution that cannot raise and cannot
    change the response.
    """
    if "user_id" in g:
        return (
            g.user_id,
            bool(getattr(g, "is_guest", False)),
            getattr(g, "trust_level", None),
        )

    from api.auth_middleware import resolve_identity_quietly

    identity = resolve_identity_quietly()
    if identity is None:
        return None, False, None
    return identity["user_id"], bool(identity["is_guest"]), identity["trust_level"]


def _duration_ms() -> int:
    """0 when _stamp_start never ran — a rate-limited 429 is rejected in
    Flask-Limiter's own before_request, which may come first. The row is
    still worth having; the duration is not."""
    start = g.get("_request_log_start")
    if start is None:
        return 0
    return int((time.perf_counter() - start) * 1000)


def _client_address() -> str | None:
    """Leftmost X-Forwarded-For, else the socket address.

    Behind Caddy every socket address is the proxy's, so without the
    header this would hash one value for the whole internet. XFF is
    client-spoofable, which is acceptable precisely because the value is
    only ever hashed for analytics — a spoofed header costs a correlation,
    not an authorisation. Note that Flask-Limiter reads remote_addr
    directly and is NOT covered by this; see api/README.md.
    """
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    return request.remote_addr


def _client_hash() -> str | None:
    """A per-day pseudonym for the client, or None.

    HMAC-SHA256 over "<UTC date>|<address>". Rotating the date into the
    MESSAGE rather than the key is what makes yesterday's clients
    unrecoverable even to someone holding the secret: the same address
    hashes differently every day and there is no key to un-rotate.

    The secret is REQUEST_LOG_HASH_SECRET, falling back to JWT_SECRET —
    not to a random per-process value, which would differ across gunicorn
    workers and make the column meaningless, and not to no salt at all,
    since an unsalted hash of an IPv4 address is a lookup table.
    """
    address = _client_address()
    secret = os.environ.get("REQUEST_LOG_HASH_SECRET") or os.environ.get("JWT_SECRET")
    if not address or not secret:
        return None
    day = datetime.now(timezone.utc).date().isoformat()
    return hmac.new(
        secret.encode("utf-8"),
        f"{day}|{address}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _truncate(value: str | None) -> str | None:
    if not value:
        return None
    return value[: config.REQUEST_LOG_USER_AGENT_MAX_LEN]
