-- ============================================================
-- 2026-07-22_composition_redesign.sql
-- Real-coach composition catalog (calib/CALIBRATION.md, workbook
-- 2026-07-22): composition-level crew/allocation/loco factors, coach
-- amenities and service-area geometry, per-section class entries, and
-- the retirement of the density column (density is now derived per
-- composition and class_main from real section geometry).
-- Behavioural counterpart: CALC_VERSION 0.9.8 (class-main allocation).
-- ============================================================

-- ---------------------------------------------------------------
-- composition_types: crew, loco, allocation and catering fields
-- ---------------------------------------------------------------
ALTER TABLE input_params.composition_types
    ADD COLUMN composition_type_n_locos SMALLINT NOT NULL DEFAULT 1,
    ADD COLUMN composition_type_zugchef_crew_factor NUMERIC(5,2) NOT NULL DEFAULT 1.19,
    ADD COLUMN composition_type_length_cost_prop NUMERIC(4,3) NOT NULL DEFAULT 0.700,
    ADD COLUMN composition_type_food_and_beverages VARCHAR(120);

COMMENT ON COLUMN input_params.composition_types.composition_type_n_locos IS
    'Number of locomotives the composition needs. Scales loco lease costs '
    'and, once the energy model is calibrated, adds n × standard loco '
    'weight to the energy weight basis. Unit: count';
COMMENT ON COLUMN input_params.composition_types.composition_type_zugchef_crew_factor IS
    'Train manager (Zugchef) crew factor in attendant-equivalents (83.15/'
    '69.67 = 1.19; doubled to 2.38 for formations of ten coaches and '
    'more). Total crew = Σ coach crew factors + this factor, priced at '
    'the attendant rate. Unit: attendant-equivalents';
COMMENT ON COLUMN input_params.composition_types.composition_type_length_cost_prop IS
    'X of the class cost allocation model: class shares = X · length '
    'share + (1−X) · weight share of the revenue space (excl. service '
    'areas); service-area costs are allocated per place. See '
    'calib/CALIBRATION.md, Class cost allocation model. Unit: fraction';
COMMENT ON COLUMN input_params.composition_types.composition_type_food_and_beverages IS
    'Catering concept of the composition (e.g. ''kiosk/ trolley service/ '
    'morning service'', ''dining car''). Structured composition-level '
    'field — aggregated coach amenities live on coach_types.';

-- ---------------------------------------------------------------
-- coach_types: wifi + service-area geometry (wo_service = full minus
-- servicing sections; basis of the class allocation and of composition
-- lengths/weights excl. service exposed by the API)
-- ---------------------------------------------------------------
ALTER TABLE input_params.coach_types
    ADD COLUMN coach_type_has_wifi BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN coach_type_length_wo_service_m NUMERIC(6,2),
    ADD COLUMN coach_type_weight_wo_service_t NUMERIC(8,3);
UPDATE input_params.coach_types
    SET coach_type_length_wo_service_m = coach_type_length_m,
        coach_type_weight_wo_service_t = coach_type_weight_gross_t
    WHERE coach_type_length_wo_service_m IS NULL;
ALTER TABLE input_params.coach_types
    ALTER COLUMN coach_type_length_wo_service_m SET NOT NULL,
    ALTER COLUMN coach_type_weight_wo_service_t SET NOT NULL;

COMMENT ON COLUMN input_params.coach_types.coach_type_has_wifi IS
    'Coach offers WiFi. Composition-level amenities are OR-aggregations '
    'over coaches (a composition has WiFi if any coach does).';
COMMENT ON COLUMN input_params.coach_types.coach_type_length_wo_service_m IS
    'Coach length excluding service areas (dining/shared sections). '
    'Equals coach_type_length_m for coaches without service areas. '
    'Revenue-space basis of the class cost allocation. Unit: m';
COMMENT ON COLUMN input_params.coach_types.coach_type_weight_wo_service_t IS
    'Coach weight excluding service areas. See length_wo_service. Unit: t';

-- ---------------------------------------------------------------
-- coach_type_classes: real section geometry + section crew
-- ---------------------------------------------------------------
ALTER TABLE input_params.coach_type_classes
    ADD COLUMN section_length_m NUMERIC(6,2),
    ADD COLUMN section_weight_t NUMERIC(8,3),
    ADD COLUMN section_crew_factor NUMERIC(5,2) NOT NULL DEFAULT 0;

COMMENT ON COLUMN input_params.coach_type_classes.section_length_m IS
    'Length of this class section within the coach. Σ over a coach''s '
    'sections = coach_type_length_wo_service_m. Basis of the class cost '
    'allocation and of derived per-class densities. Unit: m';
COMMENT ON COLUMN input_params.coach_type_classes.section_weight_t IS
    'Weight of this class section within the coach. Unit: t';
COMMENT ON COLUMN input_params.coach_type_classes.section_crew_factor IS
    'Crew factor natively attributable to this section — the class '
    'allocation attributes crew costs per section, not by space blend. '
    'Unit: attendant-equivalents';

-- ---------------------------------------------------------------
-- service_classes: density retired as a data column. Densities are now
-- DERIVED per composition and class_main from real section geometry, in
-- both variants (m/place and t/place), and exposed by the compositions
-- API. class_id granularity becomes one row per coach section
-- ("<coach_type_id> - <section label>") — seeded, not a schema change.
-- ---------------------------------------------------------------
ALTER TABLE input_params.service_classes
    DROP COLUMN service_class_density;

-- ---------------------------------------------------------------
-- service_class_id: widen to 200 chars. The per-section naming rule
-- ("<coach_type_id> - <section label>") produces ids up to 123 chars
-- for coaches with combined multi-berth section labels (e.g. the DD
-- sleepers). Widened here and on both referencing columns.
-- ---------------------------------------------------------------
ALTER TABLE input_params.service_classes
    ALTER COLUMN service_class_id TYPE VARCHAR(200);
ALTER TABLE input_params.coach_type_classes
    ALTER COLUMN service_class_id TYPE VARCHAR(200);
ALTER TABLE input_params.operator_class_costs
    ALTER COLUMN service_class_id TYPE VARCHAR(200);