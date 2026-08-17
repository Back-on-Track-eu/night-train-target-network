-- ============================================================
-- 2026-08-17_testing_gate_access_codes.sql
--
-- Testing gate (2026-08-13 session, Decision 2). A gate, NOT
-- authentication: a tester redeems a tester-specific code once per
-- browser, and behind the gate exercises the real OTP login flow as if
-- they were a real user. The two mechanisms stay separate on purpose.
--
-- Codes live in the database rather than in the reverse proxy so that
--   * more codes can be issued during a party without a deploy,
--   * each redemption is attributable to one tester (user agent), which
--     is what makes a browser-specific bug findable — the Safari-only
--     case that motivated the design,
--   * the snowball works: an attendee hands spare codes on, and we can
--     still see which code a given session came in through.
--
-- Replaces the shared `volunteer` basic_auth credential, which wrapped
-- even the OTP flow (and whose credential leaked in board minutes).
--
-- One table, no changes to anything existing.
-- ============================================================

CREATE TABLE IF NOT EXISTS admin.access_codes (
    code              TEXT PRIMARY KEY,
    label             TEXT,                       -- who it was handed to, free text
    issued_by         TEXT,                       -- who minted it
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at        TIMESTAMPTZ,                -- non-null = refused at the gate
    max_redemptions   INTEGER NOT NULL DEFAULT 0  -- 0 = unlimited (a code may be
                                                  -- used on phone + laptop)
        CHECK (max_redemptions >= 0)
);

COMMENT ON TABLE admin.access_codes IS
    'Testing-party gate codes (2026-08-13 Decision 2). Not credentials: '
    'the gate only decides who reaches the app; identity comes from the OTP flow.';

-- One row per (code, browser) redemption. Deliberately append-only: the
-- point is the audit trail, not a session store — the session itself is
-- the signed cookie the gate issues.
CREATE TABLE IF NOT EXISTS admin.access_code_redemptions (
    id            BIGSERIAL PRIMARY KEY,
    code          TEXT NOT NULL REFERENCES admin.access_codes(code) ON DELETE CASCADE,
    redeemed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_agent    TEXT,
    remote_addr   TEXT      -- the Caddy hop unless/until ProxyFix lands; recorded
                            -- for completeness, never used for identity
);

CREATE INDEX IF NOT EXISTS idx_access_code_redemptions_code
    ON admin.access_code_redemptions (code);
CREATE INDEX IF NOT EXISTS idx_access_code_redemptions_at
    ON admin.access_code_redemptions (redeemed_at DESC);

COMMENT ON TABLE admin.access_code_redemptions IS
    'Append-only log of gate redemptions — per-tester browser attribution.';
