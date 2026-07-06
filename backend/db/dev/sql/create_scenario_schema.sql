DROP SCHEMA IF EXISTS scenario CASCADE;
CREATE SCHEMA scenario;

-- ---------------------------------------------------------------
-- scenarios
--
-- A scenario is a container that pins exactly one version of each
-- versioned input_params table. Every read of infrastructure data goes
-- through a scenario — there is no other notion of "current" left in
-- the database for track/stop infrastructure (see
-- create_input_params_schema.sql: the four versioned parameter tables
-- carry no is_current flag of their own).
--
-- Scope: infrastructure only
-- ------------------------------------------------------------
-- Scenarios exist to model changes to real-world infrastructure that
-- happens in place — energy prices, track access charges, a new
-- stop's charge, terrain data. Compositions, coach types, operators,
-- and composition reference profiles are NOT scenario-versioned:
-- they're a catalog you add to, not history you edit. Wanting a train
-- with different settings means creating a new composition_type_id,
-- not bumping a version — see create_input_params_schema.sql for
-- those four tables. A scenario therefore only ever pins the four
-- infrastructure tables below.
--
-- Versioning contract for the four tables referenced below
-- ------------------------------------------------------------
-- Each *_version column is a per-table version number, not a
-- per-entity one. A version bump is a FULL-TABLE SNAPSHOT: any edit
-- to any single row in a versioned table must duplicate every other
-- row of that table forward into the new version number too, so
-- that e.g. "track_infrastructures WHERE track_infra_version = 7"
-- always returns a complete, self-consistent set — one row per
-- entity, no exceptions. Resolution is therefore always an exact
-- match, never "highest version <= N". This is what makes branching
-- (two different scenarios each bumping the same table in
-- incompatible directions) safe: a version number is never
-- reinterpreted differently depending on which scenario is asking.
--
-- This is a deliberate storage-for-simplicity trade: editing one
-- stop's charge duplicates every row in stop_infrastructures into a
-- new version. Given table sizes here (~40 countries, a few hundred
-- stops) this is negligible.
--
-- Every *_version column below is NOT NULL — the same full-snapshot
-- discipline applies one level up. A scenario row is always a
-- complete, self-contained pin of every table, never a partial diff
-- resolved against "whatever is current right now". Creating a new
-- scenario (base correction or what-if) means copying forward every
-- pointer from the scenario it's derived from, then overriding only
-- the ones actually changing. This is what makes a scenario
-- reproducible indefinitely: re-evaluating it next year returns the
-- same numbers even if the base has moved on, because nothing on the
-- row is resolved at read time.
--
-- scenario_key / is_current_scenario
-- ------------------------------------------------------------
-- scenario_id is a surrogate key — every edit to a scenario inserts
-- a new row, it never updates one in place (same discipline as the
-- four parameter tables). scenario_key is the stable identifier for
-- one lineage of such edits (e.g. "base", "whatif-de-track-infra"),
-- shared across every row that belongs to that lineage.
-- is_current_scenario marks the newest row within its scenario_key —
-- exactly one TRUE per key, enforced by
-- idx_scenarios_one_current_per_key. This lets many what-if lineages
-- coexist, each independently kept up to date, without needing to
-- know a specific scenario_id.
--
-- is_current_base
-- ------------------------------------------------------------
-- Exactly one scenario row in the whole table is "the base" — the
-- live default used whenever an API call isn't given an explicit
-- scenario_id. Corrections to the base ("something was wrong") and
-- deliberate what-ifs ("what if power tax is reduced") both work the
-- same way: insert a new scenarios row (same scenario_key as its
-- predecessor if it's an update to an existing lineage, a new
-- scenario_key if it's a fresh what-if), copy forward every pointer,
-- override what changed, flip is_current_scenario for that key, and
-- flip is_current_base too only if it's meant to replace the live
-- default.
-- ---------------------------------------------------------------
CREATE TABLE scenario.scenarios (
    scenario_id          SERIAL PRIMARY KEY,
    scenario_key         VARCHAR(100) NOT NULL,
    scenario_name        TEXT NOT NULL,
    description          TEXT,
    change_log           TEXT,
    editor                VARCHAR(100),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_current_base       BOOLEAN NOT NULL DEFAULT FALSE,
    is_current_scenario   BOOLEAN NOT NULL DEFAULT TRUE,

    track_infrastructures_version           INTEGER NOT NULL,
    track_infrastructure_defaults_version   INTEGER NOT NULL,
    stop_infrastructures_version            INTEGER NOT NULL,
    stop_infrastructure_defaults_version    INTEGER NOT NULL
);

CREATE UNIQUE INDEX idx_scenarios_one_current_base
    ON scenario.scenarios (is_current_base) WHERE is_current_base;
CREATE UNIQUE INDEX idx_scenarios_one_current_per_key
    ON scenario.scenarios (scenario_key) WHERE is_current_scenario;

COMMENT ON TABLE  scenario.scenarios IS 'Container pinning one version of each versioned infrastructure table. Exactly one row has is_current_base = TRUE (the live default); exactly one row per scenario_key has is_current_scenario = TRUE (the head of that what-if lineage). All four *_version columns are per-table full-snapshot version numbers, resolved by exact match, and are NOT NULL — a scenario is always a complete, self-contained pin, never a partial diff. Compositions/coach types/operators/composition references are not covered here — see create_input_params_schema.sql.';
COMMENT ON COLUMN scenario.scenarios.scenario_key   IS 'Stable identifier for one lineage of scenario edits, e.g. "base", "whatif-de-track-infra". Shared across every row belonging to that lineage; scenario_id changes on every edit, scenario_key does not.';
COMMENT ON COLUMN scenario.scenarios.scenario_name  IS 'Short human-readable label, e.g. "2027 base", "What-if: DE power tax -10%".';
COMMENT ON COLUMN scenario.scenarios.description    IS 'Free-text explanation of what this scenario represents and why it exists.';
COMMENT ON COLUMN scenario.scenarios.change_log     IS 'Free-text summary of what changed relative to the scenario this was derived from — the batch-level narrative; per-value rationale lives in each parameter table''s own change_log.';
COMMENT ON COLUMN scenario.scenarios.editor         IS 'User who created this scenario.';
COMMENT ON COLUMN scenario.scenarios.is_current_base IS 'TRUE for the single live default scenario, used whenever an API call is not given an explicit scenario_id.';
COMMENT ON COLUMN scenario.scenarios.is_current_scenario IS 'TRUE for the newest row within this scenario_key. Exactly one per key.';
COMMENT ON COLUMN scenario.scenarios.track_infrastructures_version         IS 'Pinned input_params.track_infrastructures version (full-table snapshot).';
COMMENT ON COLUMN scenario.scenarios.track_infrastructure_defaults_version IS 'Pinned input_params.track_infrastructure_defaults version (full-table snapshot).';
COMMENT ON COLUMN scenario.scenarios.stop_infrastructures_version          IS 'Pinned input_params.stop_infrastructures version (full-table snapshot).';
COMMENT ON COLUMN scenario.scenarios.stop_infrastructure_defaults_version  IS 'Pinned input_params.stop_infrastructure_defaults version (full-table snapshot).';