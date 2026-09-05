-- 2026-09-05_stop_uic_ref_multi_value.sql
-- ---------------------------------------------------------------------
-- input_params.stop_infrastructures.uic_ref: VARCHAR(12) -> VARCHAR(120).
--
-- uic_ref is OSM's tag verbatim, and that tag is multi-valued: a station
-- holding more than one UIC code carries them semicolon-separated (Paris
-- CDG 2 TGV: 8727149;8700147 — 15 characters). The 2026-09-05 catalogue
-- is the first to contain one, and the seed aborted on it. A single-code
-- width was never right for a list.
--
-- Widening a varchar neither rewrites the table nor revalidates rows
-- (PostgreSQL >= 9.2), and no existing value can fail the wider type, so
-- this is a safe online change on production.
--
-- Mirrors db/schema.py, which is where dev databases get the width from
-- via seed.py; the comment text below is that column's description.
-- ---------------------------------------------------------------------

ALTER TABLE input_params.stop_infrastructures
    ALTER COLUMN uic_ref TYPE VARCHAR(120);

COMMENT ON COLUMN input_params.stop_infrastructures.uic_ref IS 'UIC station code from OSM, where tagged — the tag verbatim, so a station holding more than one code carries them all, semicolon-separated (Paris CDG 2 TGV: 8727149;8700147). Intended join key for station-charge tariff documents, not normalised yet: split on the semicolon before matching, and note that a few stops carry a national number rather than the country-prefixed UIC code.';
