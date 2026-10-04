-- crowdsourcing_report_export_pgadmin.sql
-- ---------------------------------------------------------------------
-- GENERATED from crowdsourcing_report_export.sql by
--   uv run python scripts/crowdsourcing_report.py --emit-pgadmin-sql
-- Do not edit by hand.
--
-- pgAdmin variant of the crowdsourcing report export: ONE statement,
-- one result row per section (section name + JSON array of rows).
--
-- How to run in pgAdmin:
--   1. Open the Query Tool on the production database.
--   2. Paste this whole file, press F5 (Execute). Only the final SELECT
--      produces a grid; the SET line just fixes the timezone.
--   3. In the result grid toolbar choose "Save results to file"
--      (download icon) -> CSV. Keep the default quoting.
--   4. uv run python scripts/crowdsourcing_report.py --from-csv <that csv>
--
-- Read-only. No e-mails, no IP material, no OTP data are exported;
-- display names only where already public in the gallery (proposal and
-- comment authors). Feedback rows carry text but no author identity.
-- ---------------------------------------------------------------------

SET TIME ZONE 'Europe/Berlin';

SELECT 'meta_now'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT now() AS exported_at, current_setting('TIMEZONE') AS tz
  ) t
) AS data
UNION ALL
SELECT 'meta_migrations'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT filename, applied_at
    FROM admin.schema_migrations
    ORDER BY applied_at
  ) t
) AS data
UNION ALL
SELECT 'meta_first_last'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT 'users'          AS what, min(created_at) AS first_at, max(created_at) AS last_at, count(*) AS n FROM admin.users
    UNION ALL
    SELECT 'gate_redemptions', min(redeemed_at), max(redeemed_at), count(*) FROM admin.access_code_redemptions
    UNION ALL
    SELECT 'proposals',      min(created_at), max(created_at), count(*) FROM proposals.proposals
    UNION ALL
    SELECT 'likes',          min(created_at), max(created_at), count(*) FROM proposals.likes
    UNION ALL
    SELECT 'comments',       min(created_at), max(created_at), count(*) FROM proposals.comments
    UNION ALL
    SELECT 'feedback',       min(created_at), max(created_at), count(*) FROM admin.feedback
    UNION ALL
    SELECT 'request_log',    min(occurred_at), max(occurred_at), count(*) FROM admin.request_log
  ) t
) AS data
UNION ALL
SELECT 'users_totals'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT
      count(*) FILTER (WHERE is_verified AND merged_into_user_id IS NULL)                  AS registered_accounts,
      count(*) FILTER (WHERE NOT is_verified AND merged_into_user_id IS NULL)              AS guest_accounts_live,
      count(*) FILTER (WHERE merged_into_user_id IS NOT NULL)                              AS guests_merged_into_accounts,
      count(*)                                                                             AS user_rows_total
    FROM admin.users
  ) t
) AS data
UNION ALL
SELECT 'users_per_day'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT
      date(created_at) AS day,
      count(*) FILTER (WHERE is_verified AND merged_into_user_id IS NULL)     AS registered,
      count(*) FILTER (WHERE NOT is_verified OR merged_into_user_id IS NOT NULL) AS guests
    FROM admin.users
    GROUP BY 1 ORDER BY 1
  ) t
) AS data
UNION ALL
SELECT 'gate_codes'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT c.code, c.label, c.created_at, c.revoked_at, c.max_redemptions,
           count(r.id) AS redemptions, min(r.redeemed_at) AS first_redeemed, max(r.redeemed_at) AS last_redeemed
    FROM admin.access_codes c
    LEFT JOIN admin.access_code_redemptions r USING (code)
    GROUP BY c.code ORDER BY c.created_at
  ) t
) AS data
UNION ALL
SELECT 'gate_redemptions_per_day'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT date(redeemed_at) AS day, count(*) AS redemptions
    FROM admin.access_code_redemptions
    GROUP BY 1 ORDER BY 1
  ) t
) AS data
UNION ALL
SELECT 'proposals_totals'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT
      count(*)                                              AS proposals,
      count(DISTINCT user_id)                               AS distinct_authors,
      sum(proposal_version - 1)                             AS overwrite_publishes,
      count(*) FILTER (WHERE proposal_version > 1)          AS proposals_edited_after_publish,
      max(proposal_version)                                 AS max_versions_one_proposal
    FROM proposals.proposals
  ) t
) AS data
UNION ALL
SELECT 'proposals_per_day'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT date(created_at) AS day, count(*) AS published
    FROM proposals.proposals
    GROUP BY 1 ORDER BY 1
  ) t
) AS data
UNION ALL
SELECT 'proposals_per_hour_of_day'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT extract(hour FROM created_at)::int AS hour_local, count(*) AS published
    FROM proposals.proposals
    GROUP BY 1 ORDER BY 1
  ) t
) AS data
UNION ALL
SELECT 'proposals_per_author_histogram'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT n_proposals, count(*) AS n_authors
    FROM (SELECT user_id, count(*) AS n_proposals FROM proposals.proposals GROUP BY user_id) t
    GROUP BY 1 ORDER BY 1
  ) t
) AS data
UNION ALL
SELECT 'proposals_author_type'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT
      CASE WHEN u.user_id IS NULL THEN 'deleted'
           WHEN u.is_verified THEN 'registered' ELSE 'guest' END AS author_type,
      count(*) AS proposals
    FROM proposals.proposals p
    LEFT JOIN admin.users u USING (user_id)
    GROUP BY 1
  ) t
) AS data
UNION ALL
SELECT 'update_log_events'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT event, count(*) AS n, count(*) FILTER (WHERE user_id IS NULL) AS system_events
    FROM proposals.update_log
    GROUP BY 1 ORDER BY 2 DESC
  ) t
) AS data
UNION ALL
SELECT 'update_log_per_day'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT date(created_at) AS day, event, count(*) AS n
    FROM proposals.update_log
    GROUP BY 1, 2 ORDER BY 1, 2
  ) t
) AS data
UNION ALL
SELECT 'summaries_aggregates'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    -- Route figures (total_distance_km, total_time_h) sum BOTH directions of the
    -- pair (models/evaluation/summary.py::_route_metrics); the generator halves
    -- them. Distinct counts come from separate subqueries so the unnests do not
    -- multiply the row count.
    SELECT
      count(*)                                   AS proposals,
      round(sum(total_distance_km))              AS sum_distance_km_both_directions,
      round(avg(total_distance_km))              AS avg_distance_km_both_directions,
      round(max(total_distance_km))              AS max_distance_km_both_directions,
      round(avg(total_time_h)::numeric, 1)       AS avg_time_h_both_directions,
      round(avg(avg_speed_kmh)::numeric, 1)      AS avg_speed_kmh,
      round(avg(n_stops)::numeric, 1)            AS avg_stops,
      max(n_stops)                               AS max_stops,
      (SELECT count(DISTINCT s) FROM proposals.proposal_summaries, unnest(stop_ids) AS s)  AS distinct_stops_used,
      (SELECT count(DISTINCT c) FROM proposals.proposal_summaries, unnest(countries) AS c) AS distinct_countries,
      sum(train_km_per_year)                     AS sum_train_km_per_year,
      sum(departures_per_year)                   AS sum_departures_per_year,
      sum(trainsets_physical)                    AS sum_trainsets,
      sum(available_place_km_per_year)           AS sum_available_place_km_per_year,
      round(avg(cost_eur_per_train_km), 2)       AS avg_cost_eur_per_train_km
    FROM proposals.proposal_summaries
  ) t
) AS data
UNION ALL
SELECT 'summaries_distance_buckets'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT width_bucket(total_distance_km, 0, 3000, 6) AS bucket_500km, count(*) AS proposals,
           min(total_distance_km) AS min_km, max(total_distance_km) AS max_km
    FROM proposals.proposal_summaries GROUP BY 1 ORDER BY 1
  ) t
) AS data
UNION ALL
SELECT 'summaries_stops_histogram'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT n_stops, count(*) AS proposals FROM proposals.proposal_summaries GROUP BY 1 ORDER BY 1
  ) t
) AS data
UNION ALL
SELECT 'summaries_countries_per_proposal'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT cardinality(countries) AS n_countries, count(*) AS proposals
    FROM proposals.proposal_summaries GROUP BY 1 ORDER BY 1
  ) t
) AS data
UNION ALL
SELECT 'countries_frequency'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT country, count(*) AS proposals
    FROM proposals.proposal_summaries, unnest(countries) AS country
    GROUP BY 1 ORDER BY 2 DESC
  ) t
) AS data
UNION ALL
SELECT 'country_relations_frequency'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT relation, count(*) AS proposals
    FROM proposals.proposal_summaries, unnest(country_relations) AS relation
    GROUP BY 1 ORDER BY 2 DESC
  ) t
) AS data
UNION ALL
SELECT 'stops_frequency'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    WITH names AS (
      SELECT DISTINCT ON (stop_id) stop_id, stop_name, country_code
      FROM input_params.stop_infrastructures
      ORDER BY stop_id, stop_infra_row_id DESC
    )
    SELECT u.stop_id, n.stop_name, n.country_code, count(*) AS proposals
    FROM proposals.proposal_summaries ps, unnest(ps.stop_ids) AS u(stop_id)
    LEFT JOIN names n USING (stop_id)
    GROUP BY 1, 2, 3 ORDER BY 4 DESC, 2
  ) t
) AS data
UNION ALL
SELECT 'endpoints_frequency'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    -- first and last stop of each proposal (termini)
    WITH names AS (
      SELECT DISTINCT ON (stop_id) stop_id, stop_name, country_code
      FROM input_params.stop_infrastructures
      ORDER BY stop_id, stop_infra_row_id DESC
    ), termini AS (
      SELECT stop_ids[1] AS stop_id FROM proposals.proposal_summaries
      UNION ALL
      SELECT stop_ids[cardinality(stop_ids)] FROM proposals.proposal_summaries
    )
    SELECT t.stop_id, n.stop_name, n.country_code, count(*) AS as_terminus
    FROM termini t LEFT JOIN names n USING (stop_id)
    GROUP BY 1, 2, 3 ORDER BY 4 DESC, 2
  ) t
) AS data
UNION ALL
SELECT 'compositions_frequency'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT ps.composition_id, ct.composition_type_description, count(*) AS proposals
    FROM proposals.proposal_summaries ps
    LEFT JOIN (SELECT DISTINCT ON (composition_type_id) composition_type_id, composition_type_description
               FROM input_params.composition_types ORDER BY composition_type_id, composition_type_row_id DESC) ct
           ON ct.composition_type_id = ps.composition_id
    GROUP BY 1, 2 ORDER BY 3 DESC
  ) t
) AS data
UNION ALL
SELECT 'scenarios_frequency'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT ps.scenario_id, s.scenario_key, s.scenario_name, count(*) AS proposals
    FROM proposals.proposal_summaries ps
    LEFT JOIN scenario.scenarios s USING (scenario_id)
    GROUP BY 1, 2, 3 ORDER BY 4 DESC
  ) t
) AS data
UNION ALL
SELECT 'gauges_frequency'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT track_gauge_mm, count(DISTINCT route_id) AS routes
    FROM proposals.trips GROUP BY 1 ORDER BY 2 DESC
  ) t
) AS data
UNION ALL
SELECT 'operating_days_histogram'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT operating_days_per_year, count(*) AS proposals
    FROM proposals.proposal_summaries GROUP BY 1 ORDER BY 1
  ) t
) AS data
UNION ALL
SELECT 'proposals_list'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT ps.proposal_id, ps.name, u.display_name AS author,
           CASE WHEN u.is_verified THEN 'registered' ELSE 'guest' END AS author_type,
           ps.created_at, ps.updated_at, ps.proposal_version,
           ps.total_distance_km, ps.total_time_h, ps.avg_speed_kmh, ps.n_stops,
           array_to_string(ps.countries, '|') AS countries,
           array_to_string(ps.country_relations, '|') AS country_relations,
           ps.stop_ids[1] AS first_stop, ps.stop_ids[cardinality(ps.stop_ids)] AS last_stop,
           array_to_string(ps.stop_ids, '|') AS stop_ids,
           ps.composition_id, ps.scenario_id, ps.operating_days_per_year, ps.departures_per_year,
           ps.trainsets_physical, ps.train_km_per_year, ps.available_place_km_per_year, ps.sold_place_km_per_year, ps.passengers_per_year,
           ps.cost_eur_per_train_km, ps.revenue_eur_per_train_km, ps.margin_eur_per_train_km,
           ps.net_eur_per_year, ps.subsidy_eur_per_year,
           ps.demand_trips_per_year, ps.shift_air_trips_per_year, ps.demand_kpis_placeholder,
           (SELECT count(*) FROM proposals.likes l WHERE l.proposal_id = ps.proposal_id) AS likes,
           (SELECT count(*) FROM proposals.comments c WHERE c.proposal_id = ps.proposal_id AND NOT c.is_deleted) AS comments
    FROM proposals.proposal_summaries ps
    LEFT JOIN admin.users u USING (user_id)
    ORDER BY ps.created_at
  ) t
) AS data
UNION ALL
SELECT 'scenario_summaries_status'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT status, error_code, count(*) AS members
    FROM proposals.proposal_scenario_summaries GROUP BY 1, 2 ORDER BY 3 DESC
  ) t
) AS data
UNION ALL
SELECT 'engagement_totals'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT
      (SELECT count(*) FROM proposals.likes)                                  AS likes,
      (SELECT count(DISTINCT user_id) FROM proposals.likes)                   AS distinct_likers,
      (SELECT count(DISTINCT proposal_id) FROM proposals.likes)               AS proposals_liked,
      (SELECT count(*) FROM proposals.comments WHERE NOT is_deleted)          AS comments,
      (SELECT count(*) FROM proposals.comments WHERE is_deleted)              AS comments_deleted,
      (SELECT count(DISTINCT user_id) FROM proposals.comments WHERE NOT is_deleted) AS distinct_commenters,
      (SELECT count(DISTINCT proposal_id) FROM proposals.comments WHERE NOT is_deleted) AS proposals_commented
  ) t
) AS data
UNION ALL
SELECT 'engagement_per_day'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT day, sum(likes) AS likes, sum(comments) AS comments
    FROM (
      SELECT date(created_at) AS day, count(*) AS likes, 0 AS comments FROM proposals.likes GROUP BY 1
      UNION ALL
      SELECT date(created_at), 0, count(*) FROM proposals.comments WHERE NOT is_deleted GROUP BY 1
    ) t GROUP BY 1 ORDER BY 1
  ) t
) AS data
UNION ALL
SELECT 'comments_list'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT c.comment_id, c.proposal_id, p.name AS proposal_name, u.display_name AS author,
           c.created_at, c.updated_at, length(c.body) AS body_len, c.body
    FROM proposals.comments c
    LEFT JOIN proposals.proposals p USING (proposal_id)
    LEFT JOIN admin.users u ON u.user_id = c.user_id
    WHERE NOT c.is_deleted
    ORDER BY c.created_at
  ) t
) AS data
UNION ALL
SELECT 'feedback_by_category'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT category, sub_category, count(*) AS n
    FROM admin.feedback GROUP BY 1, 2 ORDER BY 1, 3 DESC
  ) t
) AS data
UNION ALL
SELECT 'feedback_per_day'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT date(created_at) AS day, count(*) AS n FROM admin.feedback GROUP BY 1 ORDER BY 1
  ) t
) AS data
UNION ALL
SELECT 'feedback_list'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT feedback_id, created_at, category, sub_category,
           CASE WHEN user_id IS NOT NULL THEN 'logged_in' ELSE 'anonymous' END AS submitter_type,
           notified_at IS NOT NULL AS mail_sent,
           subject, message
    FROM admin.feedback ORDER BY created_at
  ) t
) AS data
UNION ALL
SELECT 'usage_per_day'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT date(occurred_at) AS day,
           count(*)                                         AS requests,
           count(DISTINCT user_id)                          AS distinct_users,
           count(DISTINCT user_id) FILTER (WHERE NOT is_guest) AS distinct_registered,
           count(DISTINCT user_id) FILTER (WHERE is_guest)  AS distinct_guests,
           count(*) FILTER (WHERE endpoint LIKE 'proposal_family.%') AS family_calls,
           count(*) FILTER (WHERE endpoint = 'proposal_family.post_family') AS family_builds,
           count(*) FILTER (WHERE endpoint = 'proposal_publish.publish')   AS publishes,
           count(*) FILTER (WHERE endpoint = 'proposals.get_proposal')     AS proposal_views,
           count(*) FILTER (WHERE endpoint = 'proposal_compare.compare')   AS compares,
           count(*) FILTER (WHERE endpoint = 'proposal_share.share' OR endpoint LIKE 'proposal_share.%') AS share_previews,
           count(*) FILTER (WHERE status_code >= 500)       AS server_errors,
           count(*) FILTER (WHERE status_code = 429)        AS rate_limited
    FROM admin.request_log
    GROUP BY 1 ORDER BY 1
  ) t
) AS data
UNION ALL
SELECT 'usage_by_endpoint'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT endpoint, method, count(*) AS requests,
           count(DISTINCT user_id) AS distinct_users,
           count(*) FILTER (WHERE status_code >= 400) AS errors,
           percentile_cont(0.5)  WITHIN GROUP (ORDER BY duration_ms) AS p50_ms,
           percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95_ms,
           max(duration_ms) AS max_ms,
           round(avg(response_bytes)) AS avg_bytes
    FROM admin.request_log
    GROUP BY 1, 2 ORDER BY 3 DESC
  ) t
) AS data
UNION ALL
SELECT 'usage_by_hour_local'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT extract(hour FROM occurred_at)::int AS hour_local, count(*) AS requests,
           count(DISTINCT user_id) AS distinct_users
    FROM admin.request_log GROUP BY 1 ORDER BY 1
  ) t
) AS data
UNION ALL
SELECT 'usage_by_weekday_local'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT extract(isodow FROM occurred_at)::int AS isodow, to_char(occurred_at, 'Dy') AS weekday,
           count(*) AS requests, count(DISTINCT user_id) AS distinct_users
    FROM admin.request_log GROUP BY 1, 2 ORDER BY 1
  ) t
) AS data
UNION ALL
SELECT 'usage_status_codes'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT status_code, count(*) AS n FROM admin.request_log GROUP BY 1 ORDER BY 1
  ) t
) AS data
UNION ALL
SELECT 'usage_browsers'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT
      CASE
        WHEN user_agent ILIKE '%Edg/%'                 THEN 'Edge'
        WHEN user_agent ILIKE '%OPR/%'                 THEN 'Opera'
        WHEN user_agent ILIKE '%Firefox/%'             THEN 'Firefox'
        WHEN user_agent ILIKE '%Chrome/%' AND user_agent NOT ILIKE '%Chromium%' THEN 'Chrome'
        WHEN user_agent ILIKE '%Safari/%' AND user_agent ILIKE '%Version/%' THEN 'Safari'
        WHEN user_agent IS NULL                        THEN 'unknown'
        ELSE 'other'
      END AS browser,
      CASE
        WHEN user_agent ILIKE '%iPhone%' OR user_agent ILIKE '%iPad%' THEN 'iOS'
        WHEN user_agent ILIKE '%Android%'   THEN 'Android'
        WHEN user_agent ILIKE '%Windows%'   THEN 'Windows'
        WHEN user_agent ILIKE '%Mac OS X%'  THEN 'macOS'
        WHEN user_agent ILIKE '%Linux%'     THEN 'Linux'
        ELSE 'other'
      END AS os,
      count(*) AS requests, count(DISTINCT user_id) AS distinct_users
    FROM admin.request_log
    GROUP BY 1, 2 ORDER BY 3 DESC
  ) t
) AS data
UNION ALL
SELECT 'usage_mobile_share'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT
      (user_agent ILIKE '%Mobile%' OR user_agent ILIKE '%iPhone%' OR user_agent ILIKE '%Android%') AS is_mobile,
      count(*) AS requests, count(DISTINCT user_id) AS distinct_users
    FROM admin.request_log GROUP BY 1
  ) t
) AS data
UNION ALL
SELECT 'usage_per_user_profile'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT
      count(*) FILTER (WHERE family_builds > 0)                      AS users_who_planned,
      count(*) FILTER (WHERE family_builds >= 5)                     AS users_5plus_plans,
      count(*) FILTER (WHERE family_builds >= 20)                    AS users_20plus_plans,
      count(*) FILTER (WHERE publishes > 0)                          AS users_who_published,
      count(*) FILTER (WHERE active_days >= 2)                       AS users_returned_2plus_days,
      count(*) FILTER (WHERE active_days >= 5)                       AS users_returned_5plus_days,
      max(family_builds)                                             AS max_plans_one_user,
      max(active_days)                                               AS max_active_days_one_user,
      round(avg(active_days)::numeric, 2)                            AS avg_active_days,
      sum(family_builds)                                             AS total_family_builds
    FROM (
      SELECT user_id,
             count(DISTINCT date(occurred_at)) AS active_days,
             count(*) FILTER (WHERE endpoint = 'proposal_family.post_family') AS family_builds,
             count(*) FILTER (WHERE endpoint = 'proposal_publish.publish' AND status_code < 300) AS publishes
      FROM admin.request_log WHERE user_id IS NOT NULL GROUP BY user_id
    ) t
  ) t
) AS data
UNION ALL
SELECT 'usage_active_days_histogram'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT active_days, count(*) AS users
    FROM (SELECT user_id, count(DISTINCT date(occurred_at)) AS active_days
          FROM admin.request_log WHERE user_id IS NOT NULL GROUP BY user_id) t
    GROUP BY 1 ORDER BY 1
  ) t
) AS data
UNION ALL
SELECT 'usage_compute_totals'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT
      count(*) FILTER (WHERE endpoint = 'proposal_family.post_family')                      AS family_builds,
      sum(duration_ms) FILTER (WHERE endpoint = 'proposal_family.post_family') / 1000.0 / 3600 AS family_build_hours_server_time,
      sum(response_bytes) / 1024.0 / 1024 AS total_mb_served,
      sum(duration_ms) / 1000.0 / 3600    AS total_server_hours
    FROM admin.request_log
  ) t
) AS data
UNION ALL
SELECT 'stop_coords'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    -- Coordinates for every stop the map may draw (whole catalogue, latest row per
    -- stop), with the city the gallery's city tab filters by.
    SELECT DISTINCT ON (stop_id) stop_id, stop_lat, stop_lon, city_osm_id
    FROM input_params.stop_infrastructures
    ORDER BY stop_id, stop_infra_row_id DESC
  ) t
) AS data
UNION ALL
SELECT 'family_cache_live'::text AS section, (
  SELECT jsonb_agg(t) FROM (

    SELECT count(*) AS cached_family_documents, min(created_at) AS oldest, max(created_at) AS newest
    FROM family.documents
  ) t
) AS data;
