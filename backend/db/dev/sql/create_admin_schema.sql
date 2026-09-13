DROP SCHEMA IF EXISTS admin CASCADE;
CREATE SCHEMA admin;

CREATE TABLE admin.users (
    user_id      SERIAL PRIMARY KEY,
    email        TEXT UNIQUE,
    display_name TEXT NOT NULL UNIQUE,
    is_verified  BOOLEAN NOT NULL DEFAULT FALSE,
    merged_into_user_id INTEGER REFERENCES admin.users(user_id),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE  admin.users              IS 'Platform users — created by the auth endpoints (OTP registration, guest sessions, first Keycloak-SSO sign-in). user_id is the identity every other schema references — proposals and feedback both key on it.';
COMMENT ON COLUMN admin.users.user_id      IS 'Stable surrogate identity, referenced by proposals.proposals.user_id and admin.feedback.user_id.';
COMMENT ON COLUMN admin.users.email        IS 'Login identity — unique. NULL for guest accounts; required for registered users (enforced by the API, not a DB constraint).';
COMMENT ON COLUMN admin.users.display_name IS 'User-chosen public name (proposal lists, feedback), unique across the tool. Guest names carry the reserved "guest_" prefix.';
COMMENT ON COLUMN admin.users.merged_into_user_id IS 'Set when this (guest) account was merged into a registered account on OTP verification — proposals and feedback were reassigned to that user_id. A token for a merged user is rejected with an explicit account-merged error. NULL for live accounts.';
COMMENT ON COLUMN admin.users.is_verified  IS 'TRUE after the first successful OTP verification (and always for Keycloak-SSO rows). FALSE for guests.';

CREATE TABLE admin.auth_tokens (
    token_id    SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES admin.users(user_id) ON DELETE CASCADE,
    code_hash   TEXT NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    used        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_auth_tokens_lookup
    ON admin.auth_tokens (user_id, expires_at)
    WHERE NOT used;

COMMENT ON TABLE  admin.auth_tokens            IS 'Short-lived OTP tokens for email login. One row per issued code; marked used on first successful verify (or superseded when a newer code is requested).';
COMMENT ON COLUMN admin.auth_tokens.code_hash  IS 'SHA-256 hex digest of the 6-digit OTP. Never store the plaintext code.';
COMMENT ON COLUMN admin.auth_tokens.expires_at IS 'Hard expiry — tokens older than this are rejected even if not yet marked used.';
COMMENT ON COLUMN admin.auth_tokens.used       IS 'Set TRUE on first successful verification, or when a newer code supersedes this one. Single-use enforcement.';

CREATE TABLE admin.feedback (
    feedback_id   SERIAL PRIMARY KEY,
    user_id       INTEGER REFERENCES admin.users(user_id) ON DELETE SET NULL,
    email         TEXT,
    category      TEXT NOT NULL,
    sub_category  TEXT NOT NULL,
    subject       TEXT NOT NULL,
    message       TEXT NOT NULL,
    notified_at   TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- A submission identifies its author one of two ways: a logged-in
    -- user_id, or a free-text email for anonymous feedback. At least one
    -- must be present so every row can always be replied to.
    CONSTRAINT feedback_identity_present CHECK (user_id IS NOT NULL OR email IS NOT NULL)
);

COMMENT ON TABLE  admin.feedback              IS 'User feedback submissions — POST /api/feedback. Sent to targetnetwork-wg@back-on-track.eu and stored here; notified_at is set once that mail send succeeds.';
COMMENT ON COLUMN admin.feedback.user_id      IS 'admin.users identity of a logged-in submitter, or NULL for anonymous feedback (see feedback_identity_present).';
COMMENT ON COLUMN admin.feedback.email        IS 'Reply-to address for an anonymous (not logged-in) submitter. NULL when user_id is set — the author''s email is looked up from admin.users instead.';
COMMENT ON COLUMN admin.feedback.category     IS 'Top-level topic, e.g. ''Infrastructure'', ''Compositions'', ''Evaluation — calculation method'', ''Bug report''. Free text — GET /api/feedback/categories returns the current nine-category taxonomy, but new categories are accepted as they come up.';
COMMENT ON COLUMN admin.feedback.sub_category IS 'Detail within category — e.g. a field name for ''Infrastructure''/''Compositions'', or a cost component for ''Evaluation — calculation method''. Free text, same rationale as category.';
COMMENT ON COLUMN admin.feedback.notified_at  IS 'When the feedback mail to targetnetwork-wg@back-on-track.eu succeeded. NULL if the send failed or has not been attempted — the row is still kept either way, since storing feedback must not depend on mail delivery.';
-- ------------------------------------------------------------------
-- Testing gate (2026-08-13 Decision 2). Mirrors
-- migrations/2026-08-17_testing_gate_access_codes.sql, which is its
-- counterpart for server databases (never reseeded). Both must exist:
-- a fresh seed followed by `migrate.py --baseline` records that
-- migration as applied WITHOUT executing it, so a DB born from this
-- file has to carry the tables already.
--
-- A gate, not authentication: identity still comes from the OTP flow.
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS admin.access_codes (
    code              TEXT PRIMARY KEY,
    label             TEXT,
    issued_by         TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at        TIMESTAMPTZ,
    max_redemptions   INTEGER NOT NULL DEFAULT 0
        CHECK (max_redemptions >= 0)
);

CREATE TABLE IF NOT EXISTS admin.access_code_redemptions (
    id            BIGSERIAL PRIMARY KEY,
    code          TEXT NOT NULL REFERENCES admin.access_codes(code) ON DELETE CASCADE,
    redeemed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_agent    TEXT,
    remote_addr   TEXT
);

CREATE INDEX IF NOT EXISTS idx_access_code_redemptions_code
    ON admin.access_code_redemptions (code);
CREATE INDEX IF NOT EXISTS idx_access_code_redemptions_at
    ON admin.access_code_redemptions (redeemed_at DESC);

COMMENT ON TABLE admin.access_codes IS 'Testing-party gate codes (2026-08-13 Decision 2). Not credentials: the gate only decides who reaches the app; identity comes from the OTP flow.';
COMMENT ON TABLE admin.access_code_redemptions IS 'Append-only log of gate redemptions — per-tester browser attribution.';

-- ------------------------------------------------------------------
-- Request log (2026-09-06). Mirrors
-- migrations/2026-09-06_request_log.sql, which is its counterpart for
-- server databases (never reseeded). Both must exist, for the same
-- reason as the testing gate above: a fresh seed followed by
-- `migrate.py --baseline` records that migration as applied WITHOUT
-- executing it, so a DB born from this file has to carry the table
-- already.
--
-- One row per served API request. Usage evidence first, operations
-- second, abuse detection third. No IP address is stored — client_hash
-- is a per-day HMAC pseudonym. Written best-effort by
-- api/request_log.py; retention is enforced by
-- scripts/purge_request_log.py, not by the database.
-- ------------------------------------------------------------------
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
