-- ============================================================
-- 2026-08-13_segment_countries_passages.sql
-- Ordered country list and owned crossings on stored segments
-- (ROUTE_BUILDER_VERSION 0.9.21).
--
-- country_distance_shares is a JSON object and so cannot carry order,
-- but the calibrated track access charge model needs it: a night rate
-- applies to the clock time a run spends in one country, and placing
-- each country on the clock requires knowing which was entered first.
-- passages carries the separately charged crossings a segment owns,
-- matched by polygon at routing time rather than recomputed here.
--
-- Both default to an empty array, which is exactly what a route stored
-- before 0.9.21 should reload as: api/helpers/route_serialize.py falls
-- back to the share dict's keys for ordering and charges no crossing, so
-- an existing proposal stays evaluable rather than failing. Such a
-- proposal is refreshed on next load anyway (the stored
-- route_builder_version is below current), which is what repopulates
-- these columns with real values.
-- ============================================================

ALTER TABLE proposals.segments
    ADD COLUMN IF NOT EXISTS countries JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS passages  JSONB NOT NULL DEFAULT '[]'::jsonb;

COMMENT ON COLUMN proposals.segments.countries IS 'The same countries as country_distance_shares, but IN PATH ORDER, which a JSON object cannot express. Track access charges need it: a night rate applies to the clock time a run spends in one country, and placing each country on the clock requires knowing which was entered first. Empty for routes stored before ROUTE_BUILDER 0.9.21.';
COMMENT ON COLUMN proposals.segments.passages IS 'Separately charged crossings this segment owns (STOREBAELT, OERESUND_DK, OERESUND_SE, CHANNEL_TUNNEL), matched by polygon intersection at routing time. A crossing is attributed to exactly one segment per trip, so one split by an intermediate stop is not charged twice. Empty for routes stored before ROUTE_BUILDER 0.9.21.';
