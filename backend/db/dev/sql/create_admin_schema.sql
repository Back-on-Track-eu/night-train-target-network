DROP SCHEMA IF EXISTS admin CASCADE;
CREATE SCHEMA admin;

CREATE TABLE admin.users (
    user_id      SERIAL PRIMARY KEY,
    email        TEXT UNIQUE,
    display_name TEXT NOT NULL UNIQUE,
    is_verified  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE  admin.users              IS 'Platform users — created by the auth endpoints (OTP registration, guest sessions, first Keycloak-SSO sign-in). user_id is the identity every other schema references — proposals and feedback both key on it.';
COMMENT ON COLUMN admin.users.user_id      IS 'Stable surrogate identity, referenced by proposals.proposals.user_id and admin.feedback.user_id.';
COMMENT ON COLUMN admin.users.email        IS 'Login identity — unique. NULL for guest accounts; required for registered users (enforced by the API, not a DB constraint).';
COMMENT ON COLUMN admin.users.display_name IS 'User-chosen public name (proposal lists, feedback), unique across the tool. Guest names carry the reserved "guest_" prefix.';
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