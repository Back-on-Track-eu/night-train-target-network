DROP SCHEMA IF EXISTS admin CASCADE;
CREATE SCHEMA admin;

CREATE TABLE admin.users (
    user_id     SERIAL PRIMARY KEY,
    email       TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE admin.feedback (
    feedback_id   SERIAL PRIMARY KEY,
    user_id       INTEGER REFERENCES admin.users(user_id) ON DELETE SET NULL,
    category      TEXT,
    subject       TEXT,
    message       TEXT NOT NULL,
    notified_at   TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);