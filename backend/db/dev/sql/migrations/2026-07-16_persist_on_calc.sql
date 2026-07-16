-- Persist-on-calc migration (2026-07-16)
-- ---------------------------------------
-- 1. Guest-to-registered merge marker: when a guest verifies an email,
--    everything owned by the guest user is reassigned and the guest row is
--    kept, pointing at the account it became. Kept (not deleted) so a still
--    valid guest JWT resolves to an explicit "account merged" rejection
--    instead of a confusing generic 401, and so the merge stays auditable
--    and idempotent.
-- 2. proposals.evaluation_body gains one sanctioned in-place write: filling
--    a NULL evaluation_body on the exact version the evaluation was computed
--    for (POST /api/evaluation/calc auto-persist). Everything else about the
--    proposals table stays append-only.

ALTER TABLE admin.users
    ADD COLUMN merged_into_user_id INTEGER REFERENCES admin.users(user_id);

COMMENT ON COLUMN admin.users.merged_into_user_id IS
    'Set when this (guest) account was merged into a registered account on '
    'OTP verification — proposals and feedback were reassigned to that '
    'user_id. A token for a merged user is rejected by the API with an '
    'explicit account-merged error. NULL for live accounts.';

COMMENT ON COLUMN proposals.proposals.evaluation_body IS
    'JSON (not JSONB — see column type note above): the exact, whole POST '
    '/api/evaluation/calc response for this version. Auto-persisted since '
    'persist-on-calc (2026-07-16): filled in place on the version row it was '
    'computed for when still NULL (the one sanctioned in-place write on this '
    'otherwise append-only table); an evaluation under changed inputs '
    '(scenario, demand, calc version) creates a new version instead. Same '
    'draft-ID rewrite applied as route_body; a snapshot, not re-derived. '
    'List summaries read total_revenue_eur/total_cost_eur/net_eur out of '
    'views.route.data.per_year here. GET /api/proposal/<id> returns this '
    'column verbatim (null if absent), key order included.';