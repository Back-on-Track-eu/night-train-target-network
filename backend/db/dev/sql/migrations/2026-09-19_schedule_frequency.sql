-- 2026-09-19 — one frequency on the wire, the month grid underneath
-- ROUTE_BUILDER 0.9.40 (docs/2026-09-18_manual_demand_guide.md, phase A):
-- the compute request loses schedule_mode ('alwaysDaily' | 'custom') and
-- posts `schedule` as {"days_per_week": n} or a month map; the resolved
-- request always carries the month map. proposals.routes.schedule_months
-- becomes the ONE home of a stored plan and the two-season projection
-- (proposals.seasonal_schedules) goes.
--
-- Three steps, all in this one transaction (db/migrate.py wraps the file):
--   1. fold the projection into schedule_months where a route row written
--      before ROUTE_BUILDER 0.9.35 still has NULL there (summer = April..
--      September; daily -> 7, three_per_week -> 3), then NOT NULL, then
--      drop the table
--   2. rewrite every stored compute_request: drop schedule_mode; a request
--      that ran 'alwaysDaily' (or carried no schedule block) gets the flat
--      seven it meant, a 'custom' one keeps its map
--   3. one proposals.update_log row per rewritten proposal (event
--      'migrated', user_id NULL, no version bump: nothing was recomputed)
--
-- Nothing here changes a number: a flat seven is what 'alwaysDaily' always
-- evaluated to. The version bump marks every proposal outdated anyway, and
-- scripts/refresh_proposals.py (run by deploy after this) recomputes them
-- from the rewritten request. Idempotent: a second run finds no NULL map,
-- no table, no schedule_mode and therefore no proposal to log.

-- 1. schedule_months is the one home ---------------------------------------

UPDATE proposals.routes r
SET schedule_months = (
    SELECT jsonb_object_agg(
        m::text,
        CASE
            WHEN m BETWEEN 4 AND 9 THEN COALESCE(f.summer, 0)
            ELSE COALESCE(f.winter, 0)
        END
    )
    FROM generate_series(1, 12) AS m,
         (
             SELECT
                 MAX(CASE WHEN s.season = 'summer' THEN
                     CASE s.frequency WHEN 'daily' THEN 7 WHEN 'three_per_week' THEN 3 ELSE 0 END
                 END) AS summer,
                 MAX(CASE WHEN s.season = 'winter' THEN
                     CASE s.frequency WHEN 'daily' THEN 7 WHEN 'three_per_week' THEN 3 ELSE 0 END
                 END) AS winter
             FROM proposals.seasonal_schedules s
             WHERE s.route_id = r.route_id
         ) AS f
)
WHERE r.schedule_months IS NULL
  AND EXISTS (SELECT 1 FROM proposals.seasonal_schedules s WHERE s.route_id = r.route_id);

-- A route row with neither a map nor a projection cannot be evaluated;
-- there is none on any seeded or deployed database (every publish since
-- WP5 wrote the projection). Should one exist, the constraint below fails
-- the migration loudly rather than letting a NULL plan through.
ALTER TABLE proposals.routes
    ALTER COLUMN schedule_months SET NOT NULL;

COMMENT ON COLUMN proposals.routes.schedule_months IS 'Days per week for each month, {"1": 7, ..., "12": 0} (models/route/route.py Schedule). The one home of the operating plan since ROUTE_BUILDER 0.9.40; a request posting one frequency stores the same number in every month.';

DROP TABLE IF EXISTS proposals.seasonal_schedules;

-- 2. the stored request loses schedule_mode ---------------------------------

-- Which proposals this run rewrites, captured before the rewrite so step 3
-- logs exactly those and nothing published afterwards.
CREATE TEMP TABLE migrated_2026_09_19 ON COMMIT DROP AS
SELECT proposal_id, proposal_version
FROM proposals.proposals
WHERE compute_request::jsonb ? 'schedule_mode';

-- compute_request is JSON, not JSONB (verbatim echo, key order kept); the
-- rewrite goes through jsonb and back. refresh_proposals.py replaces the
-- whole column with the fresh echo on recompute, so the reordered keys are
-- transient.
UPDATE proposals.proposals
SET compute_request = (
    (compute_request::jsonb - 'schedule_mode')
    || jsonb_build_object(
        'schedule',
        CASE
            WHEN compute_request::jsonb ->> 'schedule_mode' = 'custom'
                 AND jsonb_typeof(compute_request::jsonb -> 'schedule') = 'object'
            THEN compute_request::jsonb -> 'schedule'
            ELSE '{"1": 7, "2": 7, "3": 7, "4": 7, "5": 7, "6": 7, "7": 7, "8": 7, "9": 7, "10": 7, "11": 7, "12": 7}'::jsonb
        END
    )
)::json
WHERE compute_request::jsonb ? 'schedule_mode';

-- 3. the history ------------------------------------------------------------

INSERT INTO proposals.update_log (proposal_id, proposal_version, user_id, event, detail)
SELECT p.proposal_id,
       p.proposal_version,
       NULL,
       'migrated',
       jsonb_build_object(
           'trigger', 'schedule_mode_removed',
           'route_builder_version', '0.9.40',
           'to', jsonb_build_object('schedule', p.compute_request::jsonb -> 'schedule')
       )
FROM proposals.proposals p
JOIN migrated_2026_09_19 m USING (proposal_id);

COMMENT ON COLUMN proposals.update_log.event  IS 'One of: published, overwritten, recalculated, branched_from, branched_to, migrated.';
COMMENT ON COLUMN proposals.update_log.detail IS 'Event-specific context. branched_*: {"source_proposal_id": …}. recalculated: {"trigger": "calc_version"|"route_builder_version"|"base_scenario_moved", "from": …, "to": …}. migrated (a data migration rewrote the stored request without recomputing, user_id NULL): {"trigger": …, "from": …, "to": …}.';
