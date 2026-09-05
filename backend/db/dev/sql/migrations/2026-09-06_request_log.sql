-- ============================================================
-- 2026-09-06_request_log.sql
--
-- admin.request_log — one row per served API request.
--
-- Purpose, in order of weight:
--   1. Usage evidence. How many people used the tool, which parts of it,
--      and when. This is the number the DG MOVE submission needs, and
--      nothing else in the database can answer it: proposals record what
--      was PUBLISHED, which is a small fraction of what was tried.
--   2. Operations. status_code + duration_ms + response_bytes per
--      endpoint, so the slow tail is queryable rather than guessed at.
--   3. Abuse. client_hash correlates a client within one UTC day.
--
-- NOT a security log and NOT an audit trail: writes are best-effort and a
-- failed insert is swallowed (api/request_log.py), because a logging sink
-- must never turn a served request into an error. A gap in this table
-- means the logger had a bad day, not that the request did not happen.
--
-- Privacy. No IP address is stored. client_hash is
-- HMAC-SHA256(secret, "<UTC date>|<client address>"), so it correlates
-- requests from one client within a day and is unlinkable across days;
-- there is no reverse lookup without the secret, and rotating the date
-- into the message means even the secret does not recover yesterday's
-- clients as today's. user_id is ON DELETE SET NULL so erasing an account
-- anonymises its rows while preserving the usage counts.
--
-- Retention is not optional: at roughly 200 bytes a row this grows
-- without bound. scripts/purge_request_log.py deletes beyond
-- REQUEST_LOG_RETENTION_DAYS and belongs on a cron — see
-- docs/DEPLOY_HANDOVER.md.
--
-- Mirrors dev/sql/create_admin_schema.sql, which is its counterpart for
-- databases born from a fresh seed. Both must exist: a seed followed by
-- `migrate.py --baseline` records this migration as applied WITHOUT
-- executing it.
--
-- One table, no changes to anything existing.
-- ============================================================

CREATE TABLE IF NOT EXISTS admin.request_log (
    request_id      BIGSERIAL PRIMARY KEY,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id         INTEGER REFERENCES admin.users(user_id) ON DELETE SET NULL,
    is_guest        BOOLEAN NOT NULL DEFAULT FALSE,
    trust_level     SMALLINT,
    client_hash     CHAR(64),
    method          VARCHAR(8) NOT NULL,
    endpoint        VARCHAR(80),
    route_rule      VARCHAR(200),
    status_code     SMALLINT NOT NULL,
    duration_ms     INTEGER NOT NULL,
    response_bytes  INTEGER,
    user_agent      VARCHAR(400)
);

-- The three questions this table is asked, one index each. All three lead
-- with their grouping key and end on occurred_at DESC, because every
-- question is "over the last N days" — a plain (occurred_at) index would
-- force a filter-then-sort on the other two.
CREATE INDEX IF NOT EXISTS idx_request_log_at
    ON admin.request_log (occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_request_log_endpoint_at
    ON admin.request_log (endpoint, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_request_log_user_at
    ON admin.request_log (user_id, occurred_at DESC)
    WHERE user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_request_log_client_at
    ON admin.request_log (client_hash, occurred_at DESC)
    WHERE client_hash IS NOT NULL;

COMMENT ON TABLE  admin.request_log                IS 'One row per served API request — usage evidence first (which endpoints, by whom, when), operations second (status, latency, size), abuse detection third. Best-effort: a failed insert is swallowed, so a gap means the logger failed, not the request. Excluded by design: /api/health (polled by the frontend and by container healthchecks) and /api/gate/* (testing-party gate, hit on every page request by Caddy forward_auth) — both would dominate the table without saying anything about usage. CORS preflight (OPTIONS) is excluded for the same reason.';
COMMENT ON COLUMN admin.request_log.occurred_at    IS 'When the response was written, not when the request arrived — the two differ by duration_ms.';
COMMENT ON COLUMN admin.request_log.user_id        IS 'admin.users identity, registered or guest — guests get a real user row from POST /api/auth/guest, so they are attributable here like anyone else. NULL means no usable token was presented. ON DELETE SET NULL: erasing an account anonymises its history rather than deleting it, so usage counts survive a GDPR erasure.';
COMMENT ON COLUMN admin.request_log.is_guest       IS 'TRUE for a guest session. Registered and guest users are both counted in user_id; this is what separates them when the question is "how many people committed to an account".';
COMMENT ON COLUMN admin.request_log.trust_level    IS 'auth_utils trust ladder at request time: 0 guest, 1 contributor, 2 operator. NULL when unauthenticated. Denormalised on purpose — a user''s level changes over time and the log records what it was.';
COMMENT ON COLUMN admin.request_log.client_hash    IS 'HMAC-SHA256(secret, "<UTC date>|<client address>") hex — a per-day pseudonym, never an address. Correlates one client''s requests within a UTC day and is unlinkable across days by construction. Use user_id, not this, to count distinct people: a guest JWT outlives the day. NULL when no address could be read or no secret is configured.';
COMMENT ON COLUMN admin.request_log.method         IS 'HTTP method. OPTIONS never appears — CORS preflight is excluded.';
COMMENT ON COLUMN admin.request_log.endpoint       IS 'Flask endpoint name, "<blueprint>.<view>" (e.g. proposals.list_proposals). THE grouping key: stable across URL changes, low cardinality, and blueprint-prefixed so it groups by API for free. NULL when no rule matched (404 on an unknown path).';
COMMENT ON COLUMN admin.request_log.route_rule     IS 'The matched rule with its parameters intact, e.g. /api/proposal/<int:proposal_id>. Groups where the raw path would not; the raw path is deliberately NOT stored, nor is the query string or the request body (a /calc body is an entire proposal, and published ones are already persisted).';
COMMENT ON COLUMN admin.request_log.duration_ms    IS 'Wall time in the Flask request, measured from before_request. 0 when the request was rejected before that hook ran — a rate-limited 429 is the normal case.';
COMMENT ON COLUMN admin.request_log.response_bytes IS 'Response body length BEFORE gzip: this hook runs ahead of Flask-Compress (after_request functions run in reverse registration order), which makes it the payload size rather than the transfer size. NULL for streamed responses.';
COMMENT ON COLUMN admin.request_log.user_agent     IS 'Truncated to REQUEST_LOG_USER_AGENT_MAX_LEN (api/config.py). Kept for the same reason admin.access_code_redemptions keeps it: a browser-specific bug is only findable if the browser is recorded.';
