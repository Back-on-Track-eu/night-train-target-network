DROP SCHEMA IF EXISTS admin CASCADE;
CREATE SCHEMA admin;

CREATE TABLE admin.users (
    user_id      SERIAL PRIMARY KEY,
    email        TEXT UNIQUE,                        -- NULL for guest accounts; NOT NULL enforced in application layer for real users
    display_name TEXT NOT NULL UNIQUE,
    is_verified  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON COLUMN admin.users.email        IS 'NULL for guest accounts. Required for registered users — enforced by the API, not the DB constraint.';
COMMENT ON COLUMN admin.users.display_name IS 'User-chosen public name, unique across the tool. Guest names are prefixed with "guest_".';
COMMENT ON COLUMN admin.users.is_verified  IS 'Set TRUE on first successful OTP verification. Always FALSE for guests.';

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

COMMENT ON TABLE  admin.auth_tokens            IS 'Short-lived OTP tokens for magic-link login. One row per issued code; marked used on first successful verify.';
COMMENT ON COLUMN admin.auth_tokens.code_hash  IS 'SHA-256 hex digest of the 6-digit OTP. Never store the plaintext code.';
COMMENT ON COLUMN admin.auth_tokens.expires_at IS 'Hard expiry — tokens older than this are rejected even if not yet marked used.';
COMMENT ON COLUMN admin.auth_tokens.used       IS 'Set TRUE immediately on first successful verification. Single-use enforcement.';

CREATE TABLE admin.feedback (
    feedback_id   SERIAL PRIMARY KEY,
    user_id       INTEGER REFERENCES admin.users(user_id) ON DELETE SET NULL,
    category      TEXT,
    subject       TEXT,
    message       TEXT NOT NULL,
    notified_at   TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE admin.api_request_log (
    log_id       SERIAL PRIMARY KEY,
    ts           TIMESTAMPTZ NOT NULL DEFAULT now(),
    method       TEXT        NOT NULL,
    endpoint     TEXT        NOT NULL,
    status_code  INT         NOT NULL,
    duration_ms  INT         NOT NULL,
    request_body JSONB,
    error_log    TEXT
);

CREATE INDEX idx_api_request_log_ts
    ON admin.api_request_log (ts DESC);

CREATE INDEX idx_api_request_log_endpoint_status
    ON admin.api_request_log (endpoint, status_code);

COMMENT ON TABLE  admin.api_request_log              IS 'One row per API request. Used for usage stats and error monitoring.';
COMMENT ON COLUMN admin.api_request_log.request_body IS 'Full JSON request body — populated only on 4xx and 5xx responses.';
COMMENT ON COLUMN admin.api_request_log.error_log    IS 'Full Python traceback — populated only on 5xx responses. Always NULL currently; reserved for future use.';