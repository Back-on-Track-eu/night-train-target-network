-- 2026-08-31_route_segment_cache.sql
-- ---------------------------------------------------------------------
-- route_cache schema: the per-graph stop-pair routing segment cache
-- (models/route/routing/segment_cache.py, adapters/route_segment_repository.py).
-- A cache, not a source of truth — disposable, refilled by
-- scripts/precompute_route_segments.py and by every live-routed miss.
-- UNLOGGED for the same reason the WP13 compute cache was: no WAL cost,
-- a crash loses nothing that a recompute cannot restore.
--
-- Mirrors db/schema.py's ROUTE_CACHE_TABLES exactly (dev databases get it
-- from there via seed.py; servers only ever move through migrations).
-- ---------------------------------------------------------------------

CREATE SCHEMA IF NOT EXISTS route_cache;

CREATE TABLE IF NOT EXISTS route_cache.graph_state (
    routing_graph_key  VARCHAR(50) PRIMARY KEY,
    import_date        TEXT NOT NULL,
    synced_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNLOGGED TABLE IF NOT EXISTS route_cache.route_segments (
    routing_graph_key   VARCHAR(50)  NOT NULL,
    stop_lo             VARCHAR(120) NOT NULL,
    stop_hi             VARCHAR(120) NOT NULL,
    variant_key         VARCHAR(80)  NOT NULL,
    distance_m          INTEGER      NOT NULL,
    country_distance_m  JSONB        NOT NULL,
    country_driving_ms  JSONB        NOT NULL,
    countries           JSONB        NOT NULL,
    passages            JSONB        NOT NULL,
    geometry            JSONB        NOT NULL,
    source              VARCHAR(10)  NOT NULL DEFAULT 'runtime',
    routed_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (routing_graph_key, stop_lo, stop_hi, variant_key)
);

COMMENT ON TABLE  route_cache.graph_state IS 'GraphHopper import_date each graph''s cached segments were routed against. RouteSegmentRepository.sync_graph_import() compares it with the live /info at API startup and purges that graph''s rows on a change — a re-import empties exactly the graph it touched.';
COMMENT ON TABLE  route_cache.route_segments IS 'Raw routed physics for one stop pair on one routing graph, canonical lo->hi orientation (stop ids sorted; direction is symmetric, one row serves both). Scenario-independent by design: buffer quotas, traction dynamics and energy are applied downstream, so parameter recalibrations invalidate zero rows. Grows from precompute loads (source=precompute) and from every live-routed miss (source=runtime).';
COMMENT ON COLUMN route_cache.route_segments.variant_key IS 'route_variant_key(): gauge profile + hash of the resolved custom model — everything that shapes the geometry on a graph. Unknown key -> miss -> live route + store: degraded, never wrong.';
COMMENT ON COLUMN route_cache.route_segments.country_driving_ms IS 'Unrounded per-country raw driving time (ms) — what buffer quotas and driving_time_min are recomputed from per request.';
COMMENT ON COLUMN route_cache.route_segments.geometry IS '[[lon, lat], ...] lo->hi. Deliberately the last column — large; keep it out of ad-hoc SELECTs.';
