-- ============================================================
-- 2026-07-21_calibration_v2.sql
-- Schema changes for the composition cost calibration v2
-- (backend/models/compositions/calib/CALIBRATION.md).
-- Behavioural counterpart: calc.py fix-overhead base change and
-- overhead-hour removal; CALC_VERSION bump in the same unit of work.
-- ============================================================

-- ---------------------------------------------------------------
-- operators: drop overhead hours (roster inefficiency is embedded
-- in the S17 deployment-hour rates), update role semantics.
-- ---------------------------------------------------------------
ALTER TABLE input_params.operators
    DROP COLUMN operator_driver_overhead_h,
    DROP COLUMN operator_crew_overhead_h;

COMMENT ON COLUMN input_params.operators.operator_driver_costs_eur_h IS
    'Driver staff cost per deployment hour (roster inefficiency embedded '
    '— no separate overhead hours). Billable hours = trip time. Unit: €/h';
COMMENT ON COLUMN input_params.operators.operator_crew_costs_eur_h IS
    'Cabin crew cost per deployment hour, attendant rate. The train '
    'manager is carried as +1.19 attendant-equivalents inside the '
    'composition crew factor sums. Unit: €/h';
COMMENT ON COLUMN input_params.operators.operator_loco_lease_eur_h IS
    'Full-service locomotive lease rate, utilization-based — bundles '
    'capital, maintenance, and insurance. Billed per loco operating hour '
    '(driving + buffer + dwell). Configuration-tiered by fleet material: '
    'base <=200 km/h config vs 230 km/h config, represented as separate '
    'operator rows (STD-REF / STD-NEW). Unit: €/h';

-- ---------------------------------------------------------------
-- composition_types: material strategy + indicative comparison KPIs.
-- ---------------------------------------------------------------
ALTER TABLE input_params.composition_types
    ADD COLUMN composition_type_material_strategy VARCHAR(15)
        NOT NULL DEFAULT 'refurbished'
        CHECK (composition_type_material_strategy IN ('new', 'refurbished')),
    ADD COLUMN composition_type_indicative_cost_eur_train_km NUMERIC(8,2),
    ADD COLUMN composition_type_indicative_cost_ct_place_km  NUMERIC(6,2);

ALTER TABLE input_params.composition_types
    ALTER COLUMN composition_type_material_strategy DROP DEFAULT;

COMMENT ON COLUMN input_params.composition_types.composition_type_material_strategy IS
    'Rolling stock material strategy: ''new'' (230 km/h-capable, 30y '
    'amortisation, 0.909 availability) or ''refurbished'' (200 km/h cap, '
    '12y, 0.80). Drives the operator row selection (STD-NEW / STD-REF) '
    'and the parameter family — see calib/CALIBRATION.md.';
COMMENT ON COLUMN input_params.composition_types.composition_type_indicative_cost_eur_train_km IS
    'Indicative operator-controllable cost per train-km on the S41 '
    'reference route (1,000 km, 14.5 h trip, 350 operating days, 2 '
    'trainsets), 2032 prices, excluding infrastructure access, energy, '
    'variable overhead and EBIT. Comparison KPI between compositions — '
    'not a route evaluation. Derivation: calib/CALIBRATION.md. Unit: €/train-km';
COMMENT ON COLUMN input_params.composition_types.composition_type_indicative_cost_ct_place_km IS
    'Same cost basis divided by places. Unit: ct/place-km';
COMMENT ON COLUMN input_params.composition_types.composition_type_purchase_coach_eur IS
    'Average purchase price per coach, derived from the per-metre model '
    '(new 145 / refurbished 53 k€ per metre of coach, double-deck ×1.12) '
    'applied to the composition''s coach lengths. Derivation: '
    'calib/CALIBRATION.md, Coach purchase cost. Unit: €/coach';
COMMENT ON COLUMN input_params.composition_types.composition_type_coach_maint_eur_km IS
    'Coach maintenance for the whole composition per train-km '
    '(per-coach rate × number of coaches; new 1.00 / refurbished 1.30 '
    '€/coach-km, nominal 2032). Unit: €/train-km';
COMMENT ON COLUMN input_params.composition_types.composition_type_cleaning_eur_day IS
    'Cleaning & overnight service preparation per coach per operating '
    'day, nominal 2032. Unit: €/coach/day';

-- ---------------------------------------------------------------
-- coach_types: length (basis of the per-metre purchase model and of
-- composition total length exposed by the compositions API).
-- ---------------------------------------------------------------
ALTER TABLE input_params.coach_types
    ADD COLUMN coach_type_length_m NUMERIC(6,2) NOT NULL DEFAULT 26.40;
ALTER TABLE input_params.coach_types
    ALTER COLUMN coach_type_length_m DROP DEFAULT;
COMMENT ON COLUMN input_params.coach_types.coach_type_length_m IS
    'Coach length over buffers. Basis of the per-metre purchase model '
    'and of composition total length. Unit: m';

-- ---------------------------------------------------------------
-- composition_references: retired. The indicative KPIs are seeded
-- calibration values on composition_types; their basis (reference
-- route, price basis, scope) lives in the indicative column comments
-- and calib/CALIBRATION.md — no per-composition reference profile needed.
-- ---------------------------------------------------------------
DROP TABLE IF EXISTS input_params.composition_references;