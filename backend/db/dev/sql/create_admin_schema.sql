DROP SCHEMA IF EXISTS admin CASCADE;
CREATE SCHEMA admin;

CREATE TABLE admin.users (
    user_id     SERIAL PRIMARY KEY,
    user_name   TEXT NOT NULL,
    email       TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE  admin.users            IS 'Platform users. Rows are created on user registration (Phase 5 OTP/magic-link auth); until then they are seeded manually. user_id is the identity every other schema references — proposals and feedback both key on it.';
COMMENT ON COLUMN admin.users.user_id    IS 'Stable surrogate identity, referenced by proposals.proposals.user_id and admin.feedback.user_id.';
COMMENT ON COLUMN admin.users.user_name  IS 'Display name shown in the frontend (proposal lists, feedback), decoupled from the login email.';
COMMENT ON COLUMN admin.users.email      IS 'Login identity — unique; the future magic-link auth flow is email-based.';

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