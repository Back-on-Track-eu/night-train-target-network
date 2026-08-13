-- ============================================================
-- 2026-08-12_stats_country_relations.sql
--
-- GET /api/proposals/stats (adapters/proposal/README.md §7.7).
--
-- Two additions, no changes to anything existing:
--
--   1. input_params.country_relations — the candidate set of
--      country-to-country relations a night train could plausibly
--      serve, one row per unordered country pair, rebuilt from the
--      pinned stop catalog by scripts/build_country_relations.py.
--      Mirrors the definition in db/schema.py (the source of truth for
--      input_params; this file is its migration counterpart for server
--      databases, which are never reseeded).
--
--   2. proposals.proposal_summaries.country_relations — which of those
--      relations each proposal actually serves. Backfilled below from
--      proposals.od_pairs, which already carries exactly the
--      boarding-capable-origin → alighting-capable-destination pairs
--      the projection derives the column from; the version refresh
--      (CALC_VERSION 0.9.15) rewrites it from the model on the next
--      pass either way, so this backfill only exists to keep the
--      gallery correct in the meantime.
--
--   3. ontd.route_summaries.country_relations — the same column on the
--      existing-trains side of the gallery union, added below.
-- ============================================================

CREATE TABLE IF NOT EXISTS input_params.country_relations (
    country_a           CHAR(2) NOT NULL REFERENCES input_params.countries(country_code),
    country_b           CHAR(2) NOT NULL REFERENCES input_params.countries(country_code),
    ref_stop_a          VARCHAR(120) NOT NULL,
    ref_stop_b          VARCHAR(120) NOT NULL,
    great_circle_km     NUMERIC(8,1) NOT NULL,
    rail_km             NUMERIC(8,1),
    rail_time_h         NUMERIC(6,2),
    routing_status      VARCHAR(20) NOT NULL,
    stop_infra_version  INTEGER NOT NULL,
    built_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (country_a, country_b, stop_infra_version),
    CHECK (country_a < country_b)
);

CREATE INDEX IF NOT EXISTS idx_country_relations_rail_km
    ON input_params.country_relations (stop_infra_version, rail_km);

COMMENT ON TABLE input_params.country_relations IS 'Which pairs of countries are close enough to each other for one night train to plausibly connect them — the candidate set the proposal statistics rank top and flop relations over (GET /api/proposals/stats). Derived, rebuildable data: scripts/build_country_relations.py rebuilds it from the pinned stop catalog.';

ALTER TABLE proposals.proposal_summaries
    ADD COLUMN IF NOT EXISTS country_relations TEXT[] NOT NULL DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_summaries_relations
    ON proposals.proposal_summaries USING GIN (country_relations);

COMMENT ON COLUMN proposals.proposal_summaries.country_relations IS 'Country-to-country relations this proposal actually serves, as sorted "AA__BB" keys — derived from od_pairs (boarding-capable origin before alighting-capable destination), so a merely transited country contributes nothing. Ranking dimension of GET /api/proposals/stats (§7.7).';

-- ontd.route_summaries gains the same column. It is NOT enough to add it
-- to db/ontd/sql/create_ontd_schema.sql: that file is only re-applied by
-- a full ONTD load (it DROPs the refreshed tables), and db/dev/seed.py
-- deliberately skips it when the schema already exists — so a reseeded
-- or migrated database would keep the old shape while
-- proposals.proposal_summaries had the new one, and the gallery's UNION
-- of the two would fail outright. db/dev/seed.py's sync_ontd_schema()
-- is the local counterpart of this statement.
DO $$
BEGIN
    IF to_regclass('ontd.route_summaries') IS NOT NULL THEN
        ALTER TABLE ontd.route_summaries
            ADD COLUMN IF NOT EXISTS country_relations TEXT[] NOT NULL DEFAULT '{}';
    END IF;
END
$$;

-- Backfill from stored demand: one relation per distinct pair of
-- countries an OD pair connects, self-pairs excluded. Stop countries
-- come from the proposal's own pinned stop snapshot, resolved through
-- proposals.proposals.scenario_id rather than the current base scenario
-- — a proposal that has not been refreshed yet still reads its own
-- world.
WITH stop_country AS (
    SELECT p.proposal_id, si.stop_id, si.country_code
      FROM proposals.proposals p
      JOIN scenario.scenarios sc ON sc.scenario_id = p.scenario_id
      JOIN input_params.stop_infrastructures si
        ON si.stop_infra_version = sc.stop_infrastructures_version
), relations AS (
    SELECT p.proposal_id,
           array_agg(DISTINCT LEAST(o.country_code, d.country_code)
                     || '__'
                     || GREATEST(o.country_code, d.country_code)) AS relations
      FROM proposals.proposals p
      JOIN proposals.trips t
        ON t.route_id = 'P' || p.proposal_id || '_V' || p.proposal_version || '_R1'
      JOIN proposals.od_pairs od       ON od.trip_id = t.trip_id
      JOIN stop_country o              ON o.proposal_id = p.proposal_id
                                      AND o.stop_id = od.origin_stop_id
      JOIN stop_country d              ON d.proposal_id = p.proposal_id
                                      AND d.stop_id = od.destination_stop_id
     WHERE o.country_code <> d.country_code
     GROUP BY p.proposal_id
)
UPDATE proposals.proposal_summaries s
   SET country_relations = r.relations
  FROM relations r
 WHERE r.proposal_id = s.proposal_id;
