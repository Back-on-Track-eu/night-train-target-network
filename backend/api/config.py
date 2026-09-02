"""
config.py
=========
Operational limits for the API layer — the "how many / how long / how
much" this backend enforces on incoming requests.

Where a hard-coded parameter belongs
-------------------------------------
The project already had three homes for parameters before this module;
the rule is that a value lives with the code that ENFORCES it, and the
only reason to centralise would be a value enforced in more than one
place:

  * Secrets and service wiring (POSTGRES_*, SMTP_*, KEYCLOAK_*,
    JWT_SECRET, OPENRAILROUTING_*) — read via os.environ at their point
    of use, never as a module constant. They are per-environment,
    occasionally rotated, and sometimes absent at import time.
  * Calibrated domain and economic parameters — the input_params /
    scenario tables. They carry provenance and a version; code constants
    cannot.
  * Domain assumptions not yet in the database — the owning model's
    model.py STANDARD VALUES block (models/route, models/demand, …).
    They live there because they are versioned WITH the model: changing
    one bumps a model version, which is exactly what should not happen
    when a rate limit is retuned.
  * Operational limits that shape HTTP behaviour — here. Nothing in this
    module means anything outside the request/response cycle, which is
    why it sits in api/ rather than at the backend root.

An adapter or script with its own operational knob (a cache TTL, a batch
worker count) keeps it next to the implementation on the same principle,
not here.

backend/docker/.env.example is the deployment-facing counterpart: it
documents every variable that can be set per environment, grouped by the
module that reads it. Every constant below is overridable from there
under its own name.
"""

from __future__ import annotations

import os


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


def _env_str(name: str, default: str) -> str:
    return os.environ.get(name) or default


# =============================================================================
# Engagement — api/proposal_engagement.py
# =============================================================================

COMMENT_BODY_MAX_LEN = _env_int("COMMENT_BODY_MAX_LEN", 4000)

# Flask-Limiter limit strings (";"-separated for several windows on one
# endpoint), bucketed per authenticated user rather than per IP — see
# api/auth_middleware.py's rate_limit_key(). Sized to be invisible to a
# real discussion and useless to a script: 60 comments an hour is far
# past what anyone writes by hand. Edits are looser than posts (typo
# fixes come in bursts and cost nothing), likes looser still — a like is
# a toggle, so a fast clicker is normal behaviour.
COMMENT_RATE_LIMIT = _env_str("COMMENT_RATE_LIMIT", "10 per minute;60 per hour")
COMMENT_EDIT_RATE_LIMIT = _env_str(
    "COMMENT_EDIT_RATE_LIMIT", "20 per minute;120 per hour"
)
LIKE_RATE_LIMIT = _env_str("LIKE_RATE_LIMIT", "60 per minute")


# =============================================================================
# Auth — api/auth.py
# =============================================================================

# Both keyed per IP, not per user: neither endpoint has an authenticated
# caller to key on (rate_limit_key() falls back to the address there).
AUTH_REQUEST_CODE_RATE_LIMIT = _env_str("AUTH_REQUEST_CODE_RATE_LIMIT", "5 per hour")
AUTH_GUEST_RATE_LIMIT = _env_str("AUTH_GUEST_RATE_LIMIT", "20 per hour")

# How long an emailed OTP code stays redeemable. Short by design: the code
# is a single-use credential in a third-party inbox.
OTP_TTL_MINUTES = _env_int("OTP_TTL_MINUTES", 15)

# Session lifetimes for the local-plane JWTs (api/auth_utils.py). Guests get
# the longer window so their proposals stay accessible without an inbox to
# re-verify through. Deployment security policy, not a code fact — hence
# here rather than beside the JWT plumbing.
JWT_TTL_DAYS = _env_int("JWT_TTL_DAYS", 7)
GUEST_TTL_DAYS = _env_int("GUEST_TTL_DAYS", 30)


# =============================================================================
# Feedback — api/helpers/feedback_serialize.py
# =============================================================================

# Same family as COMMENT_BODY_MAX_LEN: a request-shaping cap, relaxable per
# deployment without invalidating anything already stored.
FEEDBACK_SUBJECT_MAX_LEN = _env_int("FEEDBACK_SUBJECT_MAX_LEN", 200)

# The one unauthenticated endpoint that sends mail, so the only one an
# anonymous caller can use to generate outbound traffic. Two windows: the
# per-minute cap stops a script within seconds, the hourly one still lets a
# reviewer working through the documentation file several corrections in a
# sitting. Keyed per user where a local-plane token is present, per address
# otherwise (rate_limit_key) — the form is offered to anonymous readers, so
# most submissions count against the address bucket.
#
# Read these numbers per gunicorn worker, not per deployment: limiter
# storage is in-process (api/limiter.py), so the real ceiling is
# (limit x workers) — 10/min and 40/hour at the servers' --workers 2. That
# is also why the six submitting tests in test_60_feedback_api.py do not
# trip it: they spread across workers.
FEEDBACK_RATE_LIMIT = _env_str("FEEDBACK_RATE_LIMIT", "5 per minute;20 per hour")


# =============================================================================
# Proposals listing — api/proposals.py
# =============================================================================

# Page size when the request body carries no "limit".
PROPOSALS_DEFAULT_LIMIT = _env_int("PROPOSALS_DEFAULT_LIMIT", 50)


# =============================================================================
# Response compression — main.py's Compress(app)
# =============================================================================

# The gallery's map sections are large GeoJSON, which compresses roughly an
# order of magnitude; nothing in front of the app compresses (gunicorn cannot,
# and the Caddy vhost in front of production has no `encode` directive), so
# Flask is the only layer that covers every environment.
#
# Level 1, not flask-compress's default 6. Gunicorn runs SYNC workers (4 in the
# dev stack, 2 in production), so a worker spending CPU on gzip is a worker
# serving nobody — and on JSON of this shape level 1 already gets most of the
# ratio for a fraction of the cost. Raise it only with a measurement in hand.
COMPRESS_LEVEL = _env_int("COMPRESS_LEVEL", 1)

# Responses below this many bytes are sent uncompressed — the round trip
# through zlib is not worth it, and most of this API's responses are small.
COMPRESS_MIN_SIZE = _env_int("COMPRESS_MIN_SIZE", 2048)


# =============================================================================
# Proposals statistics — api/proposal_stats.py
# =============================================================================

# How many countries and country-to-country relations the top and flop
# rankings return. Deliberately NOT request parameters: they shape a
# response, and letting two callers read different-length rankings off
# the same deployment buys nothing.
PROPOSALS_STATS_COUNTRY_TOP = _env_int("PROPOSALS_STATS_COUNTRY_TOP", 5)
PROPOSALS_STATS_COUNTRY_FLOP = _env_int("PROPOSALS_STATS_COUNTRY_FLOP", 5)

# How far apart two countries may be, measured on real track between
# their reference stations, and still count as a relation one night
# train could plausibly connect (§7.7). 1600 km is roughly the far edge
# of a single night at night-train speeds; above it the pair is a
# two-night journey and belongs to a different question.
#
# This is the API-side gate. scripts/build_country_relations.py applies
# the same number as its build ceiling — it prefilters candidate pairs on
# great-circle distance × a rail detour factor, then keeps only those
# whose ROUTED distance also comes in under it. Sea crossings therefore
# drop out on their own: Italy and Greece look close in a straight line
# and are 1900+ km apart by track.
PROPOSALS_STATS_RELATION_MAX_KM = float(
    os.environ.get("PROPOSALS_STATS_RELATION_MAX_KM") or 1600
)


# =============================================================================
# Effective-config boot log
# =============================================================================


def log_effective_config() -> None:
    """One INFO block of every resolved non-secret setting, emitted at boot
    (main.py) — so "what is this deployment actually running with" is
    answered by `docker logs`, not by reading four files. Secrets and
    credentials are deliberately absent; presence-only facts about them are
    already logged by api/auth_utils.check_auth_config()."""
    import logging

    logger = logging.getLogger(__name__)
    wiring = {
        "POSTGRES_HOST": os.environ.get("POSTGRES_HOST"),
        "POSTGRES_PORT": os.environ.get("POSTGRES_PORT"),
        "POSTGRES_DB": os.environ.get("POSTGRES_DB"),
        # Per-graph now; the boot line reports the DEFAULT graph, and
        # dependencies.py logs the full key -> URL map on startup.
        "OPENRAILROUTING_URL_INFRA_2026": os.environ.get(
            "OPENRAILROUTING_URL_INFRA_2026"
        ),
        "API_CONTAINER_PORT": os.environ.get("API_CONTAINER_PORT", "5000"),
        "ONTD_BOOTSTRAP": os.environ.get("ONTD_BOOTSTRAP", "auto"),
        "AUTH_EMAIL_DEV_MODE": os.environ.get("AUTH_EMAIL_DEV_MODE", "false"),
        "TESTING": os.environ.get("TESTING", "false"),
    }
    limits = {
        "COMMENT_BODY_MAX_LEN": COMMENT_BODY_MAX_LEN,
        "FEEDBACK_RATE_LIMIT": FEEDBACK_RATE_LIMIT,
        "COMMENT_RATE_LIMIT": COMMENT_RATE_LIMIT,
        "COMMENT_EDIT_RATE_LIMIT": COMMENT_EDIT_RATE_LIMIT,
        "LIKE_RATE_LIMIT": LIKE_RATE_LIMIT,
        "AUTH_REQUEST_CODE_RATE_LIMIT": AUTH_REQUEST_CODE_RATE_LIMIT,
        "AUTH_GUEST_RATE_LIMIT": AUTH_GUEST_RATE_LIMIT,
        "OTP_TTL_MINUTES": OTP_TTL_MINUTES,
        "JWT_TTL_DAYS": JWT_TTL_DAYS,
        "GUEST_TTL_DAYS": GUEST_TTL_DAYS,
        "FEEDBACK_SUBJECT_MAX_LEN": FEEDBACK_SUBJECT_MAX_LEN,
        "PROPOSALS_DEFAULT_LIMIT": PROPOSALS_DEFAULT_LIMIT,
        "COMPRESS_LEVEL": COMPRESS_LEVEL,
        "COMPRESS_MIN_SIZE": COMPRESS_MIN_SIZE,
        "PROPOSALS_STATS_COUNTRY_TOP": PROPOSALS_STATS_COUNTRY_TOP,
        "PROPOSALS_STATS_COUNTRY_FLOP": PROPOSALS_STATS_COUNTRY_FLOP,
        "PROPOSALS_STATS_RELATION_MAX_KM": PROPOSALS_STATS_RELATION_MAX_KM,
    }
    logger.info(
        "Effective config — wiring: %s",
        ", ".join(f"{k}={v}" for k, v in wiring.items()),
    )
    logger.info(
        "Effective config — API limits: %s",
        ", ".join(f"{k}={v}" for k, v in limits.items()),
    )
