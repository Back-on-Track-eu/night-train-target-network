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
    version.py STANDARD VALUES block (models/route, models/demand, …).
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
