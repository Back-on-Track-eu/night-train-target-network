-- 2026-09-20 — proposal_scenario_summaries (adapters/proposal/README.md
-- §5.4a): the gallery projection once per current scenario variant, so
-- POST /api/proposals can list summaries and draw corridors for the
-- scenario a reader picks instead of the base only.
--
-- Additive: a new table, nothing existing touched. proposal_summaries
-- stays the base projection every existing consumer reads. Rows arrive
-- with every publish/refresh from the api version that ships this file;
-- proposals published before it have no rows until
--
--     uv run scripts/refresh_proposals.py --scenario-summaries
--
-- has run (idempotent; needs the routing instances the deployment serves —
-- a variant whose graph is not configured is stored as status 'error').
-- Until then a gallery request with a scenario_variant_id omits those
-- proposals; the default (base) request is unaffected.
--
-- Deploy order: migration, then api, then the backfill.
--
-- Dev counterpart: db/dev/sql/create_proposal_schema.sql.

-- ---------------------------------------------------------------
-- proposal_scenario_summaries (§5.4a) — the §5.4 projection once per
-- current scenario variant, for the gallery's scenario panel. Same
-- discipline as proposal_summaries: derived, rebuildable, written in
-- the same transaction as every publish and refresh
-- (adapters/proposal/repository.py: _write_state() ->
-- _replace_scenario_summaries()) and backfilled by
-- scripts/refresh_proposals.py --scenario-summaries. The base variant's
-- row duplicates proposal_summaries so the gallery has ONE read path per
-- variant. A member the family could not compute on a variant (its
-- routing graph not served here, an unroutable pair on that network) is
-- still a row — status 'error' with the member's code and NULL figures —
-- so the gallery can say "not computable on this scenario" rather than
-- lose the proposal.
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS proposals.proposal_scenario_summaries (
    proposal_id             INTEGER NOT NULL REFERENCES proposals.proposals(proposal_id) ON DELETE CASCADE,
    proposal_version        INTEGER NOT NULL,
    scenario_variant_id     INTEGER NOT NULL,
    scenario_id             INTEGER NOT NULL,
    measure_set_id          INTEGER NOT NULL,
    composition_id          TEXT NOT NULL,
    route_builder_version   TEXT NOT NULL,
    calc_version            TEXT NOT NULL,
    status                  TEXT NOT NULL CHECK (status IN ('ok', 'error')),
    error_code              TEXT,

    total_distance_km       NUMERIC(8, 1),
    total_time_h            NUMERIC(6, 2),
    avg_speed_kmh           NUMERIC(5, 1),
    n_stops                 SMALLINT,
    countries               TEXT[],
    country_relations       TEXT[],
    stop_ids                TEXT[],
    geom_simplified         geometry(MultiLineString, 4326),
    segments                JSONB,

    cost_eur_per_train_km       NUMERIC(10, 2),
    revenue_eur_per_train_km    NUMERIC(10, 2),
    margin_eur_per_train_km     NUMERIC(10, 2),
    net_eur_per_year            NUMERIC(14, 2),
    subsidy_eur_per_year        NUMERIC(14, 2),
    services_revenue_eur        NUMERIC(14, 2),
    catering_contribution_eur   NUMERIC(14, 2),

    operating_days_per_year     SMALLINT,
    departures_per_year         INTEGER,
    trainsets_physical          SMALLINT,
    train_km_per_year           NUMERIC(12, 0),
    available_place_km_per_year NUMERIC(16, 0),
    sold_place_km_per_year      NUMERIC(16, 0),
    passengers_per_year         NUMERIC(12, 0),

    demand_trips_per_year       NUMERIC(12, 0),
    demand_trip_km_per_year     NUMERIC(16, 0),
    shift_air_trips_per_year    NUMERIC(12, 0),
    shift_air_trip_km_per_year  NUMERIC(16, 0),
    shift_other_trips_per_year  NUMERIC(12, 0),
    shift_other_trip_km_per_year NUMERIC(16, 0),
    co2_savings_t_per_year      NUMERIC(12, 1),
    subsidy_eur_per_t_co2       NUMERIC(10, 2),
    demand_kpis_placeholder     BOOLEAN,

    co2_g_per_pax_km            NUMERIC(6, 1),

    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (proposal_id, scenario_variant_id)
);

CREATE INDEX IF NOT EXISTS idx_scenario_summaries_variant ON proposals.proposal_scenario_summaries (scenario_variant_id);
CREATE INDEX IF NOT EXISTS idx_scenario_summaries_geom    ON proposals.proposal_scenario_summaries USING GIST (geom_simplified);

COMMENT ON TABLE  proposals.proposal_scenario_summaries             IS 'The §5.4 projection once per current scenario variant (§5.4a) — what POST /api/proposals serves when a scenario_variant_id is requested. Derived, NOT a source of truth: replaced wholesale in the same transaction as every publish/refresh, backfilled by scripts/refresh_proposals.py --scenario-summaries. The base variant''s row duplicates proposal_summaries.';
COMMENT ON COLUMN proposals.proposal_scenario_summaries.status      IS 'ok: the member computed and every figure is set. error: the family could not compute this proposal on this variant (error_code says why — routing_graph_not_configured, routing_error, gauge_mismatch, domain_error); the figures and geometry are NULL.';
COMMENT ON COLUMN proposals.proposal_scenario_summaries.error_code  IS 'The member''s error code (api/helpers/member_compute.py classify_compute_error()) when status = error, else NULL.';
COMMENT ON COLUMN proposals.proposal_scenario_summaries.segments    IS 'Corridor geometry for the gallery''s map_lines on this variant: a JSON object keyed "STOP_A__STOP_B" (stop ids sorted, direction collapsed) whose values are GeoJSON LineStrings — the per-segment shapes proposals.segments/shapes hold for the base route, which a non-base variant has nowhere else to keep.';
COMMENT ON COLUMN proposals.proposal_scenario_summaries.geom_simplified IS 'Same simplification as proposal_summaries.geom_simplified, on this variant''s route.';
