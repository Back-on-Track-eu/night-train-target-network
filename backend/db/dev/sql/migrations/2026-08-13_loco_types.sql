-- ============================================================
-- 2026-08-13_loco_types.sql
--
-- Locomotives become catalog entities instead of a hardcoded 90 t
-- constant plus a per-composition count plus a per-operator flat rate.
-- Mirrors db/schema.py, which is the source of truth for input_params;
-- this file is its migration counterpart for server databases, which are
-- never reseeded.
--
--   loco_types             the machine: mass, design speed, traction
--   operator_loco_costs    rental rate per (operator, machine) — the
--                          locomotive counterpart of operator_class_costs
--   composition_type_locos which machines a composition hauls, in order
--
-- The backfill below reconstructs the current state exactly: two machines
-- at the mass the traction model already assumed, the existing per-
-- operator rate attached to whichever machine that operator's fleet
-- strategy implies, and one wiring row per locomotive per composition
-- (generate_series, so a composition with two locomotives gets two rows
-- rather than silently collapsing to one).
--
-- Only then are the three superseded columns dropped — the backfill reads
-- composition_type_n_locos and operator_loco_lease_eur_h before they go.
--
-- NO VALUE CHANGE: every seeded composition runs a single 90 t machine,
-- so gross weight and locomotive cost are arithmetically unchanged. The
-- expressions diverge only once a composition gains a second machine or a
-- per-type mass is sourced, which is the reason to do this now.
-- ============================================================

CREATE TABLE input_params.loco_types (
    loco_type_row_id SERIAL PRIMARY KEY,
    loco_type_id VARCHAR(50) NOT NULL UNIQUE,
    loco_type_description TEXT NOT NULL,
    loco_type_traction VARCHAR(50) NOT NULL,
    loco_type_weight_t NUMERIC(8,3) NOT NULL,
    loco_type_max_speed_kmh SMALLINT NOT NULL,
    source_id INTEGER REFERENCES input_params.sources(source_id),
    change_log TEXT
);
COMMENT ON TABLE input_params.loco_types IS 'Locomotive types — the physical machine, independent of who runs it. Weight and speed live here; the rental rate does not, because it is a commercial term that varies by operator (operator_loco_costs), exactly as onboard service cost varies by operator over service_classes. A catalog, not history: loco_type_id is a permanent natural key — a changed spec means a new loco_type_id, never editing a row in place.';
COMMENT ON COLUMN input_params.loco_types.loco_type_id IS 'Stable natural key, e.g. VECTRON-MS-230.';
COMMENT ON COLUMN input_params.loco_types.loco_type_description IS 'Machine and configuration in plain words, including the national class designation where the calibration pins one and an explicit note where it does not.';
COMMENT ON COLUMN input_params.loco_types.loco_type_traction IS 'Traction system, e.g. ''electric multi-system''. Not yet read by any model — recorded so a future electrification or traction-change model has it.';
COMMENT ON COLUMN input_params.loco_types.loco_type_weight_t IS 'Mass of one locomotive. Completes the gross weight the weight-dependent track access charge and the traction dynamics both work on — coach weight alone is not what gets hauled or weighed. Unit: t';
COMMENT ON COLUMN input_params.loco_types.loco_type_max_speed_kmh IS 'Design maximum speed. The composition''s own max speed still governs the timetable; this records what the machine could do. Unit: km/h';
COMMENT ON COLUMN input_params.loco_types.source_id IS 'Source for all values in this row.';
COMMENT ON COLUMN input_params.loco_types.change_log IS 'Free-text description of what changed in this version and why.';
CREATE TABLE input_params.operator_loco_costs (
    operator_row_id INTEGER NOT NULL REFERENCES input_params.operators(operator_row_id) ON DELETE CASCADE,
    loco_type_row_id INTEGER NOT NULL REFERENCES input_params.loco_types(loco_type_row_id),
    operator_loco_lease_eur_h NUMERIC(10,3) NOT NULL,
    source_id INTEGER REFERENCES input_params.sources(source_id),
    PRIMARY KEY (operator_row_id, loco_type_row_id)
);
COMMENT ON TABLE input_params.operator_loco_costs IS 'Locomotive rental rate per operator and machine — the locomotive counterpart of operator_class_costs. A pairing with no row is not priced, and the loader refuses to resolve a composition that needs one rather than substituting a fallback: a missing pairing is a wiring error, and a silent default would hide exactly the mistake this table exists to catch.';
COMMENT ON COLUMN input_params.operator_loco_costs.operator_loco_lease_eur_h IS 'All-inclusive rental rate (maintenance and insurance included), billed per hour the locomotive is in use. Unit: €/h';
COMMENT ON COLUMN input_params.operator_loco_costs.source_id IS 'Source for all values in this row.';
CREATE TABLE input_params.composition_type_locos (
    composition_type_row_id INTEGER NOT NULL REFERENCES input_params.composition_types(composition_type_row_id) ON DELETE CASCADE,
    position SMALLINT NOT NULL,
    loco_type_row_id INTEGER NOT NULL REFERENCES input_params.loco_types(loco_type_row_id),
    PRIMARY KEY (composition_type_row_id, position)
);
COMMENT ON TABLE input_params.composition_type_locos IS 'Ordered locomotive slots per composition type — the locomotive counterpart of composition_type_coaches. The number of locomotives is the number of rows here, never a stored column, so the two cannot disagree. position expresses machines hauling TOGETHER (double heading); a traction change part-way along a route is route-dependent and cannot be expressed on a composition type at all — that belongs on the trip when it is modelled.';
COMMENT ON COLUMN input_params.composition_type_locos.position IS '1-based position in the consist.';

-- ---------------------------------------------------------------
-- Backfill: two machines, at the mass the traction model assumed.
-- ---------------------------------------------------------------
INSERT INTO input_params.loco_types
    (loco_type_id, loco_type_description, loco_type_traction,
     loco_type_weight_t, loco_type_max_speed_kmh)
VALUES
    ('VECTRON-MS-200',
     'Siemens Vectron MS, standard 200 km/h configuration. The baseline multi-system machine assumed for refurbished-fleet operation. TO_VERIFY: no specific national Baureihe is pinned by the calibration — the rate derivation is Vectron-class generic.',
     'electric multi-system', 90.0, 200),
    ('VECTRON-MS-230',
     'Siemens Vectron MS in the 230 km/h configuration, CD class 384 — an adjusted gear ratio over the 200 km/h machine. Assumed for new-fleet operation.',
     'electric multi-system', 90.0, 230);

-- Each operator keeps its existing rate, attached to the machine its
-- fleet strategy implies. Diagonal: the off-diagonal pairings were never
-- priced and deliberately get no row.
INSERT INTO input_params.operator_loco_costs
    (operator_row_id, loco_type_row_id, operator_loco_lease_eur_h, source_id)
SELECT o.operator_row_id,
       l.loco_type_row_id,
       o.operator_loco_lease_eur_h,
       o.source_id
FROM input_params.operators o
JOIN input_params.loco_types l
  ON l.loco_type_id = CASE
        WHEN o.operator_id LIKE '%%-NEW' THEN 'VECTRON-MS-230'
        ELSE 'VECTRON-MS-200'
     END;

-- One wiring row per locomotive, preserving n_locos > 1 if any exists.
INSERT INTO input_params.composition_type_locos
    (composition_type_row_id, position, loco_type_row_id)
SELECT ct.composition_type_row_id,
       g.position,
       l.loco_type_row_id
FROM input_params.composition_types ct
CROSS JOIN LATERAL generate_series(1, ct.composition_type_n_locos) AS g(position)
JOIN input_params.loco_types l
  ON l.loco_type_id = CASE
        WHEN ct.composition_type_material_strategy = 'new' THEN 'VECTRON-MS-230'
        ELSE 'VECTRON-MS-200'
     END;

-- ---------------------------------------------------------------
-- Superseded columns. n_locos is now COUNT(*) over the wiring; the mass
-- and the rate now live on the two tables above.
-- ---------------------------------------------------------------
ALTER TABLE input_params.composition_types
    DROP COLUMN composition_type_n_locos,
    DROP COLUMN composition_type_loco_weight_t;

ALTER TABLE input_params.operators
    DROP COLUMN operator_loco_lease_eur_h;
