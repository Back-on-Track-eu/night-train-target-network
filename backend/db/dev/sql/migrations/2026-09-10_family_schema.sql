-- 2026-09-10_family_schema.sql
-- ---------------------------------------------------------------------
-- family schema + family.documents (WP18 phase B2a).
--
-- Layer L5 of the proposal design: a FAMILY is every member (scenario
-- variant x composition) of one stop list + HOW under the current pins,
-- built once and served as one document (POST /api/proposal/family).
-- The document is a pure function of those pins, so this table is a
-- cache in the same sense as proposals.compute_cache_*: UNLOGGED, TTL
-- on read, opportunistic sweep, always safe to TRUNCATE. The member
-- cache (compute_cache_pointer/_result) joins this schema in B2b as
-- family.members; until then both caches coexist.
--
-- Mirrors backend/db/schema.py (FAMILY_TABLES), which fresh local seeds
-- render their DDL from; the comment texts below are that file's.
--
-- NOT idempotent by itself; migrate.py applies each file exactly once and
-- records it in admin.schema_migrations, inside the same transaction.
-- ---------------------------------------------------------------------

CREATE SCHEMA family;

CREATE UNLOGGED TABLE family.documents (
    family_key            VARCHAR(80) PRIMARY KEY,
    route_builder_version VARCHAR(20) NOT NULL,
    calc_version          VARCHAR(20) NOT NULL,
    payload               JSONB NOT NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_family_documents_created ON family.documents (created_at);

COMMENT ON TABLE  family.documents                       IS 'One serialised family document per family key (models/family/key.py): every member of one stop list + HOW under the current pins, as POST /api/proposal/family returns it. A pure function of the pins, so a cache: UNLOGGED, TTL enforced on read (COMPUTE_CACHE_TTL_HOURS), swept opportunistically on write, truncated by scripts/refresh_proposals.py on every version bump. Never a source of truth.';
COMMENT ON COLUMN family.documents.family_key            IS 'sha256 over the resolved request, the resolved axes and the two model versions — a version bump changes the key, so a stale document is never found again.';
COMMENT ON COLUMN family.documents.route_builder_version IS 'ROUTE_BUILDER_VERSION the document was built under. Informational: the key already carries it; kept as a column so a sweep can target a version by hand.';
COMMENT ON COLUMN family.documents.calc_version          IS 'CALC_VERSION the document was built under. Same role as route_builder_version.';
COMMENT ON COLUMN family.documents.payload               IS 'The document (api/helpers/family_serialize.py): request echo, suggestions, axes, geometry pool, compact routes, members with summaries, stats.';
