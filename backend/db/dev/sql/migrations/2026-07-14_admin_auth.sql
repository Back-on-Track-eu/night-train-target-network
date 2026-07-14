-- Migration: admin schema, pre-auth → auth (2026-07-14)
-- For EXISTING databases only (the demo/prod instances on bot-server) —
-- fresh seeds get this shape from create_admin_schema.sql directly.
--
-- What changes:
--   admin.users: user_name → display_name (rename), + is_verified,
--                email becomes nullable (guests), display_name UNIQUE
--   admin.auth_tokens: new table (OTP store)
--
-- Pre-flight (run first — a duplicate display_name blocks the UNIQUE):
--   SELECT LOWER(user_name), COUNT(*) FROM admin.users
--   GROUP BY 1 HAVING COUNT(*) > 1;
--
-- Apply inside one transaction:
--   docker exec -i <db-container> psql -U <user> -d <db> < this_file.sql

BEGIN;

ALTER TABLE admin.users RENAME COLUMN user_name TO display_name;
ALTER TABLE admin.users ALTER COLUMN email DROP NOT NULL;
ALTER TABLE admin.users
    ADD COLUMN IF NOT EXISTS is_verified BOOLEAN NOT NULL DEFAULT FALSE;
-- Existing seeded users predate OTP — treat them as verified so their
-- first real login doesn't behave like a fresh registration.
UPDATE admin.users SET is_verified = TRUE WHERE email IS NOT NULL;
ALTER TABLE admin.users
    ADD CONSTRAINT users_display_name_key UNIQUE (display_name);

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

COMMIT;
