-- 2026-09-12_rolling_stock_source.sql
-- ---------------------------------------------------------------------
-- Re-point the rolling-stock tables at the composition cost calibration.
--
-- seed.py resolved SRC_CALIBRATION positionally (SOURCES[-1]) after the
-- infrastructure source registers had already been appended to SOURCES, so
-- every operator, coach and composition row was credited to whichever
-- infrastructure document happened to sort last — in practice the internal
-- route-context topography assessment, which prices nothing about a vehicle.
-- The calibration's own registry row existed but was referenced by nothing.
--
-- seed.py now names the constant, so fresh local databases are correct from
-- create/seed. Server databases are never reseeded, hence this file.
--
-- The five UPDATEs are unconditional, mirroring seed_sources(): seed.py stamps
-- every row in these tables with the calibration, so "which rows are wrong"
-- is not a question this file has to answer, and re-running it is a no-op.
-- The id is resolved by description because source_id is a SERIAL and differs
-- between environments; INTO STRICT fails the migration loudly if the
-- calibration row is absent or ambiguous, rather than writing NULL.
-- ---------------------------------------------------------------------

DO $$
DECLARE
    cal INTEGER;
BEGIN
    SELECT source_id INTO STRICT cal
    FROM input_params.sources
    WHERE source_description LIKE 'Back-on-Track (2026)%composition cost calibration%';

    UPDATE input_params.operators            SET source_id = cal;
    UPDATE input_params.operator_class_costs SET source_id = cal;
    UPDATE input_params.coach_types          SET source_id = cal;
    UPDATE input_params.coach_type_classes   SET source_id = cal;
    UPDATE input_params.composition_types    SET source_id = cal;
END $$;
