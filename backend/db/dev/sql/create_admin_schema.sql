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
    category      TEXT,
    subject       TEXT,
    message       TEXT NOT NULL,
    notified_at   TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);