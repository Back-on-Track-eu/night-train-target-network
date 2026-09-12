-- 2026-09-10_scenario_variants.sql
-- ---------------------------------------------------------------------
-- scenario.measure_sets + scenario.scenario_variants (WP18 phase A).
--
-- A scenario pins what the infrastructure IS; a measure set says what the
-- state DOES about it (VAT, energy tax, direct-cost track access). The
-- two multiply into scenario_variants, the flattened axis the API and the
-- frontend address by a single id.
--
-- Seeded with one measure set, 'none' — no lever pulled, which is what
-- every evaluation before this migration implicitly ran under. The three
-- flags therefore change no number anywhere until WP17 prices them; the
-- rates themselves will live in their own versioned input_params table,
-- pinned by the scenario like every other calibrated parameter.
--
-- Mirrors backend/db/schema.py (SCENARIO_TABLES), which fresh local seeds
-- render their DDL from; the comment texts below are that file's.
-- scenario_variants is derived data — db/dev/seed.py's
-- materialise_scenario_variants() rebuilds it with the same cross product
-- after every scenario or measure-set insert.
--
-- NOT idempotent by itself; migrate.py applies each file exactly once and
-- records it in admin.schema_migrations, inside the same transaction.
-- ---------------------------------------------------------------------

CREATE TABLE scenario.measure_sets (
    measure_set_id    SERIAL PRIMARY KEY,
    key               VARCHAR(50) NOT NULL,
    vat_exempt        BOOLEAN NOT NULL DEFAULT FALSE,
    energy_tax_exempt BOOLEAN NOT NULL DEFAULT FALSE,
    tac_direct_cost   BOOLEAN NOT NULL DEFAULT FALSE,
    description       TEXT,
    UNIQUE (key)
);

COMMENT ON TABLE  scenario.measure_sets                   IS 'A named bundle of political measures an evaluation runs under — what the state DOES, where a scenario pins what the infrastructure IS. Unversioned definitions: the flags say which levers are pulled, never by how much. The rates themselves (VAT per country of sale, electricity tax share, direct-cost floor per infrastructure manager) get their own versioned input_params table with WP17 and are pinned by the scenario like every other calibrated parameter. One row today, ''none'' — no lever pulled, which is what every evaluation before WP18 implicitly ran under.';
COMMENT ON COLUMN scenario.measure_sets.key               IS 'Stable identifier, e.g. "none", "vat-exempt". What the API and the frontend name a measure set by; ids are database-assigned and not portable between environments.';
COMMENT ON COLUMN scenario.measure_sets.vat_exempt        IS 'Night train fares exempt from value-added tax. Raises the operator''s retained revenue per ticket.';
COMMENT ON COLUMN scenario.measure_sets.energy_tax_exempt IS 'Traction electricity exempt from energy/electricity tax. Lowers the energy price the operator pays.';
COMMENT ON COLUMN scenario.measure_sets.tac_direct_cost   IS 'Track access charged at the direct cost of running the train only, the floor Directive 2012/34/EU permits — not a discount on the full charge but a different component selection (models/infrastructure/tac/calc_tac.py).';
COMMENT ON COLUMN scenario.measure_sets.description       IS 'What this bundle of measures represents, in the words a reader of the results needs.';

CREATE TABLE scenario.scenario_variants (
    scenario_variant_id SERIAL PRIMARY KEY,
    scenario_id         INTEGER NOT NULL REFERENCES scenario.scenarios(scenario_id),
    measure_set_id      INTEGER NOT NULL REFERENCES scenario.measure_sets(measure_set_id),
    UNIQUE (scenario_id, measure_set_id)
);

COMMENT ON TABLE  scenario.scenario_variants                IS 'The flattened (scenario x measure set) axis the API and the frontend address by a single id — one dropdown value instead of two. Materialised as the full cross product (db/dev/seed.py materialise_scenario_variants(), re-run after every scenario or measure-set insert), so it is derived data: truncating and rebuilding it loses nothing except the ids themselves, which nothing persists.';
COMMENT ON COLUMN scenario.scenario_variants.scenario_id    IS 'The infrastructure pin this variant evaluates on.';
COMMENT ON COLUMN scenario.scenario_variants.measure_set_id IS 'The measures this variant evaluates under.';

INSERT INTO scenario.measure_sets (key, description)
VALUES ('none', 'No political measures — today''s tax and charging regime.');

-- The cross product, exactly as materialise_scenario_variants() builds it:
-- every scenario row (current, historical and superseded alike) against
-- every measure set. Ordered so variant ids follow scenario ids on a fresh
-- database and on a server alike.
INSERT INTO scenario.scenario_variants (scenario_id, measure_set_id)
SELECT s.scenario_id, m.measure_set_id
FROM scenario.scenarios s
CROSS JOIN scenario.measure_sets m
ORDER BY s.scenario_id, m.measure_set_id
ON CONFLICT (scenario_id, measure_set_id) DO NOTHING;
