-- 2026-09-10_family_members.sql
-- ---------------------------------------------------------------------
-- family.members replaces proposals.compute_cache_pointer/_result
-- (WP18 phase B2b).
--
-- The member cache — one cached compute_member() result per resolved
-- request — moves into the family schema as ONE table. The two-table
-- split (a pointer keyed by request, a result keyed by route identity)
-- shared payloads between requests that converged on one route; the
-- family document has taken over that role, and a member is now read one
-- request at a time. The key gains measure_set_id: the request echo names
-- no measure set, so two members of one scenario under different
-- measures must not share a row.
--
-- Both are caches, so nothing is migrated across: the old tables are
-- dropped, the new one starts empty and fills on demand. Mirrors
-- backend/db/schema.py (FAMILY_TABLES) and the removal from
-- backend/db/dev/sql/create_proposal_schema.sql.
--
-- NOT idempotent by itself; migrate.py applies each file exactly once and
-- records it in admin.schema_migrations, inside the same transaction.
-- ---------------------------------------------------------------------

CREATE UNLOGGED TABLE family.members (
    request_hash      VARCHAR(80) PRIMARY KEY,
    route_fingerprint VARCHAR(80) NOT NULL,
    scenario_id       INTEGER NOT NULL,
    measure_set_id    INTEGER NOT NULL,
    composition_id    VARCHAR(50) NOT NULL,
    resolved_request  JSONB NOT NULL,
    suggested_stops   JSONB,
    payload           JSONB NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_family_members_created ON family.members (created_at);

COMMENT ON TABLE  family.members                   IS 'The member cache: one cached compute_member() result per resolved request (api/helpers/member_compute.py), keyed by a hash of the resolved request plus the measure set. Read by the family views endpoint, publish, compare and refresh. UNLOGGED, TTL on read (COMPUTE_CACHE_TTL_HOURS), swept on write, truncated by scripts/refresh_proposals.py on every version bump. Never a source of truth.';
COMMENT ON COLUMN family.members.request_hash      IS 'canonical_request_hash(): sha256 over the resolved request echo and the measure_set_id.';
COMMENT ON COLUMN family.members.route_fingerprint IS 'The member''s route fingerprint, for a targeted manual sweep and for reading which requests converged on one route.';
COMMENT ON COLUMN family.members.resolved_request  IS 'The request echo for this member — defaults applied, scenario_id concrete.';
COMMENT ON COLUMN family.members.suggested_stops   IS 'auto_stop_addition="suggest" output for this request. NULL outside suggest mode.';
COMMENT ON COLUMN family.members.payload           IS 'The member payload: versions, summary, route, evaluation.views.';

DROP TABLE proposals.compute_cache_pointer;
DROP TABLE proposals.compute_cache_result;
