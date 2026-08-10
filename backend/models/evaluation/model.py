"""
model.py
========
Version constant and full calculation model definition for the
Night Train Cost/Revenue Evaluation model.

This file is the authoritative source for:
  - CALC_VERSION: bump when any EvaluationResult output changes
  - CALC_FORMULAS: LaTeX + plain-language description + input/output
    legend for every calculation step (models/formula.py)
  - CHANGELOG: what changed in each version

Bump CALC_VERSION when:
  - Revenue or cost calculation logic changes
  - New cost/revenue line items are added or removed
  - Normalisation logic changes
  - Any change to EvaluationResult or its nested dataclasses

CALC_FORMULAS is embedded into every calc response by
api/helpers/evaluation_serialize.py (models_to_dict()) so the frontend
can render the full calculation tree with LaTeX, descriptions, and
per-formula legends.

TODO: GIT_SHA injected at build time by CI — see .github/workflows/backend-tests.yml
"""

from __future__ import annotations

from models.formula import Formula, FormulaParam

# =============================================================================
# VERSION
# =============================================================================

CALC_VERSION: str = "0.9.14"

GIT_SHA: str = "unknown"  # injected by CI

# Decimal places for the EUR leaves of each normalised Breakdown — precision
# must scale with the divisor. Annual figures are naturally 2dp currency, but
# €/place-km values on a realistic route are of order 1e-3 to 1e-2 per leaf,
# so rounding them to 2dp quantizes real differences into noise (the root
# cause of the 0.9.4 per_available_place_km divergence — see CHANGELOG 0.9.5).
# Class cells (CALC 0.9.9: every norm is class-keyed) use their norm's digits.
NORMALISATION_NDIGITS: dict[str, int] = {
    "per_year": 2,
    "per_operating_day": 2,
    "per_train_km": 4,
    "per_available_place_km": 6,
    "per_sold_place_km": 6,
}

# Decimal places for the total_eur / total_cost_eur / total_revenue_eur /
# net_eur properties — fine enough for every leaf precision above, coarse
# enough to absorb float summation noise.
BREAKDOWN_TOTAL_NDIGITS: int = 6

# Short, plain-language summary of what this model computes — embedded as-is
# in the "models" section of POST /api/proposal/calc's response, alongside
# CALC_VERSION and CALC_FORMULAS.
CALC_MODEL_DESCRIPTION: str = (
    "Cost and revenue evaluation: computes the operator's fixed and "
    "variable costs, the charges paid to infrastructure companies, and "
    "the ticket revenue of a route, then aggregates the result into views "
    "per route, trip pair, country, connection, route section, and stop."
)

CHANGELOG: dict = {
    "0.9.14": {
        "date": "2026-08-10",
        "author": "david",
        "changes": "version.py renamed to model.py (every model now anchors "
        "version, description, changelog, and formulas in a model.py). "
        "CALC_FORMULAS rebuilt on the shared Formula/FormulaParam "
        "dataclasses (models/formula.py): every formula carries a full "
        "input/output legend with units, descriptions rewritten in plain "
        "language for tool users (code references moved into comments). "
        "ADDITIVE response change once serialized: each "
        "models.evaluation.formulas entry gains 'inputs' and 'output', and "
        "input params carry an optional 'ref' source pointer "
        "(models/formula.py). Four subtotal formulas added — "
        "operator_variable_total_eur, operator_fixed_total_eur, "
        "operator_total_eur, infrastructure_total_eur — mirroring the "
        "Breakdown tree in views.py exactly, so docs/MODEL.md renders "
        "the cost/revenue tree with every subtotal linked to its "
        "children. Bjarne coordination batch (new formula keys + refs). "
        "No computed number changes. (Jumps "
        "from 0.9.11 in this file: 0.9.12/0.9.13 are taken by the WP13 "
        "state on staging.)",
    },
    "0.9.11": {
        "date": "2026-08-05",
        "author": "david",
        "changes": "WP10 step 5 — emission KPIs for proposals. ADDITIVE "
        "response changes, coordinate with Bjarne (WP12 batch): (1) POST "
        "/api/proposal/calc gains a 'summary' block (between "
        "suggested_stops and route) carrying the full §5.4 gallery KPI "
        "row — route metrics, financial KPIs, placeholder demand KPIs, "
        "co2_g_per_pax_km — built by the same "
        "models/evaluation/summary.py: build_summary_row() the publish "
        "projection uses, so calc and gallery cannot drift; deliberately "
        "NO geom_simplified (the response already carries full "
        "per-segment geometry). (2) evaluation.models gains an "
        "'emissions' entry ({version, description, factors} — 'factors' "
        "instead of 'formulas': sourced per-mode constants, decision 24) "
        "with the night_train/air/car g CO2e/pax-km reference values "
        "(EEA TERM 2020: 33/160/143). (3) Gallery summary rows and "
        "compare summaries/deltas gain co2_g_per_pax_km (flat night-"
        "train factor until the energy-based, country-resolved model). "
        "(4) Placeholder co2_savings_t_per_year values shift: the "
        "former unsourced factors (air 200 g, car 70 g) are replaced by "
        "the sourced EEA set, and savings now subtract the night "
        "train's own emissions from each shifted mode "
        "(shifted_km × (mode − night_train)) — previously the shifted "
        "modes' gross emissions were counted as savings.",
    },
    "0.9.10": {
        "date": "2026-07-27",
        "author": "david",
        "changes": "Three bug fixes flagged by review, no shape change but "
        "cost values shift on every route: (1) total_crew() on "
        "CompositionType was accidentally defined twice — the second "
        "definition silently dropped zugchef_crew_factor, undercounting "
        "driver/crew_eur ~25-37%. (2) _calc_composition_fleet_costs() "
        "multiplied purchase_coach_eur/cleaning_services_eur_day (both "
        "per-coach rates since 0.9.8's composition catalog) by the "
        "trainset/rake share instead of coach count — "
        "coach_amortisation_eur/financing_eur/cleaning_eur were 6-14x "
        "low. (3) loco_eur in views.py's per-trip-pair, per-OD, and "
        "per-stop-section builders (plus the route-level fixed-cost-"
        "share total) didn't apply composition.n_locos — harmless while "
        "every composition is single-loco, but would have silently "
        "halved cost for the first double-headed composition.",
    },
    "0.9.9": {
        "date": "2026-07-24",
        "author": "david",
        "changes": "Class_main becomes an orthogonal axis on EVERY "
        "normalisation. BREAKING for the frontend: each of per_year, "
        "per_operating_day, per_train_km, per_available_place_km and "
        "per_sold_place_km is now a dict keyed by class_main plus 'all' "
        "('all' = the whole cell as before; class cells = its allocation "
        "split). Divisors: class-independent for per_year/per_operating_"
        "day/per_train_km (class cells sum back to 'all'); a class's OWN "
        "capacity resp. sold place-km for per_available/per_sold ('all' "
        "under per_sold is the fleet-wide weighted average — restored "
        "after its 0.9.8 removal). The by_class_main view is retired — "
        "identical to per_year's class cells. Class splits are exact "
        "(builder cells) for section/OD-scoped data — a class-scoped "
        "cell's own axis is the identity — and calibration-shares-based "
        "elsewhere. NormalisationScope carries "
        "available_place_km_by_class alongside sold_place_km_by_class.",
    },
    "0.9.8": {
        "date": "2026-07-22",
        "author": "david",
        "changes": "Class-main cost allocation (calibration model, "
        "calib/CALIBRATION.md): every cost leaf is attributable to "
        "class_mains on five bases — hardware (X·length + (1−X)·weight of "
        "revenue space, service areas per head; covers driver, loco, "
        "maintenance, cleaning, capital, fix overhead, shunting, tac, "
        "station charges, parking — the 0.9.4 revenue-share rule for "
        "shunting/parking is retired), crew (per-coach factors), energy "
        "(per-coach weight by places), stockings (native class rates), "
        "revenue (ticket revenue; var_overhead/EBIT). BREAKING for the "
        "frontend: per_sold_place_km is now a dict per class_main — each "
        "class's allocated cost over ITS OWN sold place-km (50% couchette "
        "occupancy doubles per-sold-couchette cost); new by_class_main "
        "view carries the full per-class breakdown. Values in all "
        "class-dimensioned cells shift (structure otherwise stable): "
        "real-geometry allocation replaces the density proxy — e.g. seat "
        "share in REF-PREM-12 rises from 4.0% (density) to 9.4%.",
    },
    "0.9.7": {
        "date": "2026-07-21",
        "author": "david",
        "changes": "Composition cost calibration v2 (calib/CALIBRATION.md). "
        "BREAKING for stored evaluations and frontend: (1) fix_overhead_eur "
        "moved from CompositionFleetCost (calc.py) to views.py "
        "_build_breakdown() and changed base — now quota × all other "
        "annualised operator operating costs (variable excl. var_overhead + "
        "fixed), per the operators DDL semantics, instead of quota × coach "
        "amortisation only. evaluation_body's composition_fleet_costs lose "
        "the fix_overhead_eur key; the breakdown leaf stays. (2) driver/crew "
        "overhead hours removed end to end (schema columns dropped — roster "
        "inefficiency is embedded in the deployment-hour rates). (3) Seed "
        "recalibrated throughout (operators STD-REF/STD-NEW with "
        "material-tiered loco lease 161/174, EBIT 0.10, per-metre purchase "
        "model, 2032 price basis) — all evaluated figures shift. (4) "
        "IndicativeFigures carries seeded calibration KPIs "
        "(cost_eur_per_train_km, cost_ct_per_place_km) instead of "
        "placeholders; cost_eur_per_place_km_by_class dropped.",
    },
    "1.0.0": {
        "date": "2026-06-25",
        "author": "david",
        "changes": "Initial implementation. Normalised matrix output (raw, per_trip, "
        "per_trip_km, per_place_km_avg, per_place_of_class, "
        "per_place_km_of_class) at route / trip / country level. "
        "CalcStep and CalcFormula for full calculation transparency. "
        "Revenue and allocation generic over service_class_main. "
        "Country breakdown infrastructure-only, clearly scoped.",
    },
    "1.1.0": {
        "date": "2026-07-06",
        "author": "david",
        "changes": "EUR values in every Breakdown (leaves and total_eur/net_eur) now "
        "rounded to exactly 2 decimal places in views.py, before serialization. "
        "Response body restructured: added 'models' (version + description + "
        "formulas for route_builder, energy, and evaluation) and 'input' (the "
        "posted route JSON plus every track/stop/composition parameter actually "
        "used, each with description + source). 'views' restructured: each view "
        "(route, per_trip_pair, per_trip_pair_per_country, per_trip_pair_per_od, "
        "per_trip_per_stop) is now {description, normalisations, data} — "
        "normalisation documentation (one description + processing_sequence per "
        "normalisation) lives inline per view rather than in a separate top-level "
        "'views_meta'. Every filtered data point under 'data' now also carries a "
        "'filter' dict, one entry per filter dimension keyed by dimension name "
        "(e.g. {'trip_pair': 'Berlin Hbf \u2194 Wien Hbf', 'country': 'AT'}) — \u2194 for "
        "trip pairs (always both directions), \u2192 for OD pairs and single trips "
        "(genuinely one-way; single-trip labels also carry an explicit "
        "'(outbound)'/'(return)' tag). CALC_FORMULAS rewritten from scratch, keyed "
        "exactly to breakdown_to_dict() field names (driver_eur, tac_eur, "
        "total_cost_eur, etc.) instead of the old free-form step names "
        "(driver_cost, track_access_charge, ...) — api/helpers/"
        "evaluation_serialize.py now filters CALC_FORMULAS/ENERGY_FORMULAS/"
        "ROUTE_FORMULAS down to only keys present in EVALUATION_OUTPUT_FIELDS, so "
        "'models.evaluation.formulas' shows exactly (and only) the fields that "
        "actually appear under 'views', letting the frontend map one to the "
        "other by key. Several formulas describing unimplemented or superseded "
        "behavior removed (loco_amortisation, loco_maintenance, "
        "passengers_per_class, revenue_per_class, space_units_per_class, "
        "cost_allocated_per_class, cost_per_place, the old per_trip/per_place_* "
        "normalisation names); loco_eur, ticket_revenue_eur, total_eur, "
        "total_cost_eur, total_revenue_eur, and net_eur added to match actual "
        "calc.py behavior and actual output fields. Frontend consumers must "
        "update to the new response shape (see TestCalcFormulas in "
        "tests/test_versioning.py, still skipped pending a route+eval test "
        "fixture — skip reasons there describe this exact gap).",
    },
    "1.2.0": {
        "date": "2026-07-06",
        "author": "david",
        "changes": "Composition.places_by_class / density_by_class / "
        "svc_stockings_eur_place now aggregated up to class_main (Seat, "
        "Couchette, Sleeper, Capsule, Catering) instead of the more granular "
        "class_id (e.g. 'seat (reclining)', 'couchette (6-berth)') — see "
        "models/params.py: Composition.from_type(), "
        "CompositionType.weighted_avg_by_main_class(). Model approach: classes "
        "within one class_main are assumed served at the same cost factor, so "
        "the class_main figure is the places-weighted average of the "
        "underlying class_id values actually present in a composition's coach "
        "mix — not a max, not an unweighted average. This changes computed "
        "svc_stockings_eur (and any class-keyed density/place-km figure "
        "derived from it) whenever a composition mixes multiple class_ids "
        "under one class_main with different per-place service costs — "
        "previously only an exact class_id match against ODPair.class_main "
        "produced a non-zero cost/density lookup in calc.py, which in practice "
        "meant OD pairs had to target class_id, contradicting ODPair's own "
        "docstring (always documented class_main as a top-level category). "
        "BREAKING for consumers of GET /api/params/compositions and POST "
        "/api/route/plan too, not just this endpoint: their 'capacity' / "
        "'places_by_class' / 'density_by_class' output is keyed by class_main "
        "now, losing the previous class_id-level granularity — needs frontend "
        "coordination (see project notes on auditing Bjarne's frontend before "
        "Phase 4/5) since it's a real API contract change, not additive.",
    },
    "0.9.6": {
        "date": "2026-07-16",
        "author": "david",
        "changes": "Persist-on-calc: POST /api/evaluation/calc now persists its "
        "own response for any authenticated caller (guest or registered) — "
        "POST /api/proposal is gone. Two response additions: a top-level "
        "'scenario_id' (the scenario the evaluation actually ran under, "
        "override applied — the posted route's embedded scenario_id is NOT "
        "updated by an override) between route_id and models, and a trailing "
        "'proposal' block ({persisted, action, proposal_id, "
        "proposal_version}). Persistence contract: the evaluation fills its "
        "own version row in place when that version has none yet (the one "
        "sanctioned in-place write on the append-only proposals table); "
        "identical inputs (same route incl. demand, same resolved scenario, "
        "same calc version) are a no-op ('unchanged'); changed inputs create "
        "a new version carrying the unchanged route_body ('versioned' / "
        "'branched' per ownership); unpersisted, historical, or hand-edited "
        "routes are answered but never stored. Tokenless requests compute "
        "only. BREAKING for frontend: save flow removed, Authorization "
        "header now expected on calc — coordinate with Bjarne.",
    },
    "0.9.5": {
        "date": "2026-07-16",
        "author": "david",
        "changes": "Normalisation precision now scales with the divisor "
        "(NORMALISATION_NDIGITS in version.py): per_year and per_operating_day "
        "leaves stay at 2dp, per_train_km moves to 4dp, per_available_place_km "
        "and per_sold_place_km to 6dp; the total_eur / total_cost_eur / "
        "total_revenue_eur / net_eur properties round at 6dp everywhere "
        "(BREAKDOWN_TOTAL_NDIGITS). Previously every leaf and total was rounded "
        "to 2dp — a 1.1.0-era rule that predates 0.9.4's annualised place-km "
        "divisors. At €/place-km magnitude (order 1e-3 to 1e-2 per leaf) that "
        "quantization turned the per-place-km views into rounding noise, off by "
        "roughly 9% in aggregate on the standard test route — the root cause of "
        "the long-open test_per_available_place_km_divisor_is_unweighted xfail "
        "(the divisor itself was always exact; the numerator leaves were "
        "quantized). No response shape change; per_year and per_operating_day "
        "values unchanged; per_train_km and per-place-km values gain decimal "
        "places.",
    },
    "0.9.4": {
        "date": "2026-07-14",
        "author": "david",
        "changes": "Views pipeline overhaul — four numeric fixes and one new view. "
        "(1) Parking now included in every pair-filtered scope (matched via "
        "ParkingCost.trip_ids) — previously only 'all trips' carried parking, "
        "single trip-pair selections silently dropped it; the country and OD "
        "matrices additionally pair-filter parking so multi-pair routes no "
        "longer multiply-count it. (2) Pair-filtered fleet costs "
        "(coach_amortisation, financing, fix_overhead, cleaning) scaled to the "
        "pair's own coach share of a possibly shared composition fleet "
        "(views.py: _pair_fleet_share) — previously each pair carried the "
        "combined fleet cost. (3) per_trip_km normalisation RENAMED to "
        "per_train_km and its divisor annualised (cycle km × operating days); "
        "per_available_place_km divisor annualised the same way — both "
        "previously divided €/year values by one cycle's physics, inflating "
        "the result by a factor of operating_days (per_sold_place_km was "
        "already annual and is unchanged). (4) per_trip_pair_per_od allocation "
        "shares now sum to exactly 1 across a pair's OD cells: fixed fleet by "
        "pair-wide weighted place-km share (was raw od-distance / pair-distance, "
        "which over-allocated arbitrarily), loco and cleaning by pair-wide "
        "weighted place-hours share (was per-trip, double-counting across the "
        "two directions); stop costs at stops where nobody boards or alights "
        "now fall back to the OD pairs riding through, instead of being "
        "dropped — with these, OD cells sum to exactly the pair total. "
        "(5) NEW view per_trip_pair_per_section: a section is "
        "a physical piece of a trip between two stops — it carries every cost "
        "occurring there plus a share of route-level costs, and the "
        "km-proportional revenue of everyone on board (tickets extending "
        "beyond the section contribute their overlap fraction). Sections carry "
        "per-class_main sub-cells (train-level costs split by density-weighted "
        "place-km) summing to the section 'all' cell, and normalise per-unit "
        "figures against their OWN annual train-km / place-km "
        "(NormalisationScope). BREAKING for frontend: normalisation key "
        "per_trip_km → per_train_km, new views key, changed values in every "
        "pair-filtered cell — needs coordination with Bjarne before merge.",
    },
    "0.9.3": {
        "date": "2026-07-14",
        "author": "david",
        "changes": "Driver/crew billable hours now computed from time in motion — "
        "raw router driving time plus the route builder's new per-segment "
        "traction dynamics component (accel/brake time loss, route builder "
        "0.9.8: Segment.dynamics_time_min) — instead of raw driving time "
        "alone; accelerating and braking is time the driver drives and the "
        "crew is on duty. SegmentCost.driving_time_min (and the "
        "SegmentPassengerLoad copy views.py aggregates loco/country hours "
        "from) carries this in-motion figure. Staff, and any per-hour-derived "
        "figure, grow by roughly 1-2min per segment vs 0.9.2. Loco lease was "
        "already billed on segment total_time_min, which now includes "
        "dynamics via the route model itself. No response shape change.",
    },
}


# =============================================================================
# CALC FORMULA REGISTRY — LaTeX + plain-language description + input/output
# legend per formula (models/formula.py). Descriptions are written for tool
# users; developer detail lives in the comments next to each entry.
#
# Cost and revenue leaves are annual figures for the part of the route the
# view is filtered to (whole route, one trip pair, one country, one
# connection, one section, one stop) — the legends therefore state €/year.
# =============================================================================

CALC_FORMULAS: dict[str, Formula] = {
    # Internal allocation step, surfaced for transparency: how shared
    # costs split across accommodation classes. Crew, energy, stockings
    # and revenue leaves use their own native bases — see
    # views.ClassMainShares. X = composition_type_length_cost_prop (0.7).
    "class_main_allocation": Formula(
        latex=r"s_{c} = (1-f_{svc})\left(X \frac{L_c}{L_{rev}} "
        r"+ (1-X)\frac{W_c}{W_{rev}}\right) + f_{svc}\frac{P_c}{P}",
        description="How costs shared by the whole train are split between "
        "accommodation classes (seat, couchette, sleeper, ...): mostly by "
        "how much of the train's length and weight a class occupies; "
        "dining and service areas are split evenly per place.",
        inputs=(
            FormulaParam(
                symbol="L_c",
                description="Length of the class's sections in the train",
                unit="m",
                ref="column:input_params.coach_type_classes.section_length_m",
            ),
            FormulaParam(
                symbol="L_rev",
                description="Length of all passenger space in the train",
                unit="m",
                ref="column:input_params.coach_types.coach_type_length_wo_service_m",
            ),
            FormulaParam(
                symbol="W_c",
                description="Weight of the class's sections in the train",
                unit="t",
                ref="column:input_params.coach_type_classes.section_weight_t",
            ),
            FormulaParam(
                symbol="W_rev",
                description="Weight of all passenger space in the train",
                unit="t",
                ref="column:input_params.coach_types.coach_type_weight_wo_service_t",
            ),
            FormulaParam(
                symbol="X",
                ref="column:input_params.composition_types.composition_type_length_cost_prop",
                description="Weighting between length and weight (0.7 = 70% length)",
                unit="fraction",
            ),
            FormulaParam(
                symbol="f_svc",
                description="Share of the train that is service area (dining etc.)",
                unit="fraction",
            ),
            FormulaParam(
                symbol="P_c",
                description="Places of this class on the train",
                unit="places",
                ref="column:input_params.coach_type_classes.coach_type_class_places",
            ),
            FormulaParam(
                symbol="P",
                description="All places on the train",
                unit="places",
                ref="column:input_params.coach_type_classes.coach_type_class_places",
            ),
        ),
        output=FormulaParam(
            symbol="s_c",
            description="Share of a shared cost carried by the class",
            unit="fraction",
        ),
    ),
    "per_sold_place_km_by_class": Formula(
        latex=r"c_{c} = \frac{s_{c} \cdot C}{pkm^{sold}_{c}}",
        description="Cost per sold place-kilometre of one class: the "
        "class's share of a cost divided by the place-kilometres it "
        "actually sells. Empty berths make the sold ones more expensive.",
        inputs=(
            FormulaParam(
                symbol="s_c",
                ref="formula:calc.class_main_allocation",
                description="Share of the cost carried by the class",
                unit="fraction",
            ),
            FormulaParam(
                symbol="C",
                description="The cost being normalised",
                unit="€/year",
            ),
            FormulaParam(
                symbol="pkm_sold,c",
                ref="user",
                description="Sold place-kilometres of the class per year",
                unit="place-km/year",
            ),
        ),
        output=FormulaParam(
            symbol="c_c",
            description="Cost per sold place-kilometre of the class",
            unit="€/place-km",
        ),
    ),
    # ------------------------------------------------------------------
    # Every key below matches, verbatim, a field name in breakdown_to_dict()
    # output (models/evaluation views under the "views" section) — see
    # api/helpers/evaluation_serialize.py: EVALUATION_OUTPUT_FIELDS.
    # Formulas for internal-only concepts that don't correspond to any
    # output field were removed with CALC 1.1.0 — see views_meta in the
    # response for normalisation descriptions instead.
    # ------------------------------------------------------------------
    # OPERATOR — VARIABLE
    # ------------------------------------------------------------------
    "driver_eur": Formula(
        latex=r"C_{driver} = c_{driver/h} \times \left( \sum_{seg} "
        r"t_{drive,h} \cdot f_{driver} + \sum_{stop} t_{dwell,h} \cdot "
        r"f_{driver} \right)",
        description="Driver cost: the hourly driver rate times all hours "
        "the driver is on duty — driving between stops and waiting at "
        "them.",
        inputs=(
            FormulaParam(
                symbol="c_driver/h",
                ref="column:input_params.operators.operator_driver_costs_eur_h",
                description="Driver cost per hour on duty",
                unit="€/h",
            ),
            FormulaParam(
                symbol="t_drive,h",
                description="Driving time between stops",
                unit="h",
            ),
            FormulaParam(
                symbol="t_dwell,h",
                ref="formula:route.dwell_time_both",
                description="Waiting time at stops",
                unit="h",
            ),
            FormulaParam(
                symbol="f_driver",
                ref="column:input_params.composition_types.composition_type_driver_factor",
                description="Number of drivers the train needs",
                unit="persons",
            ),
        ),
        output=FormulaParam(
            symbol="C_driver",
            description="Annual driver cost",
            unit="€/year",
        ),
    ),
    # n_crew includes the train manager as +1.19 attendant-equivalents —
    # see composition_type_zugchef_crew_factor.
    "crew_eur": Formula(
        latex=r"C_{crew} = c_{crew/h} \times \left( \sum_{seg} t_{drive,h} "
        r"\cdot n_{crew} + \sum_{stop} t_{dwell,h} \cdot n_{crew} \right)",
        description="Cabin crew cost: the hourly rate per crew member "
        "times all hours the crew is on board — while driving and while "
        "waiting at stops.",
        inputs=(
            FormulaParam(
                symbol="c_crew/h",
                ref="column:input_params.operators.operator_crew_costs_eur_h",
                description="Cost per crew member per hour on duty",
                unit="€/h",
            ),
            FormulaParam(
                symbol="t_drive,h",
                description="Driving time between stops",
                unit="h",
            ),
            FormulaParam(
                symbol="t_dwell,h",
                ref="formula:route.dwell_time_both",
                description="Waiting time at stops",
                unit="h",
            ),
            FormulaParam(
                symbol="n_crew",
                ref="column:input_params.coach_types.coach_type_crew_factor",
                description="Crew members on board (train manager counted "
                "with a factor)",
                unit="persons",
            ),
        ),
        output=FormulaParam(
            symbol="C_crew",
            description="Annual cabin crew cost",
            unit="€/year",
        ),
    ),
    "coach_maintenance_eur": Formula(
        latex=r"C_{coach,maint} = \sum_{seg} c_{coach,maint/km} \times d_{km,seg}",
        description="Coach maintenance: a per-kilometre rate for the whole "
        "train times the distance driven. Locomotive maintenance is "
        "included in the locomotive rental instead.",
        inputs=(
            FormulaParam(
                symbol="c_coach,maint/km",
                ref="column:input_params.composition_types.composition_type_coach_maint_eur_km",
                description="Maintenance rate for all coaches of the train, "
                "per kilometre",
                unit="€/train-km",
            ),
            FormulaParam(
                symbol="d_km,seg",
                description="Distance driven",
                unit="km",
            ),
        ),
        output=FormulaParam(
            symbol="C_coach,maint",
            description="Annual coach maintenance cost",
            unit="€/year",
        ),
    ),
    # Propulsion minutes are deduplicated route-wide (Route.loco_
    # propulsion_min): a locomotive shared across trip pairs is billed
    # once, not once per pair.
    "loco_eur": Formula(
        latex=r"C_{loco} = c_{loco,lease/h} \times \frac{t_{loco,propulsion,min}}{60}",
        description="Locomotive rental: an all-inclusive hourly rate "
        "(maintenance and insurance included) times the hours the "
        "locomotive is in use. A locomotive shared between several trips "
        "is only counted once.",
        inputs=(
            FormulaParam(
                symbol="c_loco,lease/h",
                ref="column:input_params.operators.operator_loco_lease_eur_h",
                description="All-inclusive locomotive rental rate per hour in use",
                unit="€/h",
            ),
            FormulaParam(
                symbol="t_loco,propulsion,min",
                description="Minutes the locomotive is in use",
                unit="min",
            ),
        ),
        output=FormulaParam(
            symbol="C_loco",
            description="Annual locomotive rental cost",
            unit="€/year",
        ),
    ),
    "svc_stockings_eur": Formula(
        latex=r"C_{svc} = \sum_{od} c_{svc,class(od)/place} \times n_{places\_sold,od}",
        description="Onboard service cost — bedding, breakfast, amenities: "
        "a per-passenger rate for each accommodation class times the "
        "tickets sold in that class.",
        inputs=(
            FormulaParam(
                symbol="c_svc,class/place",
                ref="column:input_params.operator_class_costs.operator_class_svc_stockings_eur_place",
                description="Service cost per sold place, by class",
                unit="€/place",
            ),
            FormulaParam(
                symbol="n_places_sold,od",
                ref="user",
                description="Places sold per connection and year",
                unit="places/year",
            ),
        ),
        output=FormulaParam(
            symbol="C_svc",
            description="Annual onboard service cost",
            unit="€/year",
        ),
    ),
    "var_overhead_eur": Formula(
        latex=r"C_{var,oh} = \sum_{od} R_{od} \times q_{var,oh}",
        description="Variable overhead — ticket sales, distribution, "
        "customer service: a fixed share of ticket revenue.",
        inputs=(
            FormulaParam(
                symbol="R_od",
                ref="formula:calc.ticket_revenue_eur",
                description="Ticket revenue per connection and year",
                unit="€/year",
            ),
            FormulaParam(
                symbol="q_var,oh",
                ref="column:input_params.operators.operator_var_overhead_per",
                description="Overhead share of revenue",
                unit="fraction",
            ),
        ),
        output=FormulaParam(
            symbol="C_var,oh",
            description="Annual variable overhead",
            unit="€/year",
        ),
    ),
    # ------------------------------------------------------------------
    # OPERATOR — FIXED
    # ------------------------------------------------------------------
    "coach_amortisation_eur": Formula(
        latex=r"C_{coach,amort} = \frac{C_{coach,purchase}}{T_{coach,amort}} \times n",
        description="Annual write-off of the coaches: purchase price "
        "divided by their useful life, times the number of coaches the "
        "service needs — including a reserve for coaches in the "
        "workshop.",
        inputs=(
            FormulaParam(
                symbol="C_coach,purchase",
                ref="column:input_params.composition_types.composition_type_purchase_coach_eur",
                description="Purchase price per coach",
                unit="€/coach",
            ),
            FormulaParam(
                symbol="T_coach,amort",
                ref="column:input_params.composition_types.composition_type_coach_amort_years",
                description="Useful life over which the coach is written off",
                unit="years",
            ),
            FormulaParam(
                symbol="n",
                description="Coaches needed for the service, incl. reserve",
                unit="coaches",
            ),
        ),
        output=FormulaParam(
            symbol="C_coach,amort",
            description="Annual coach write-off",
            unit="€/year",
        ),
    ),
    "financing_eur": Formula(
        latex=r"C_{fin} = C_{coach,purchase} \times q_{fin} \times n",
        description="Cost of financing the coaches: purchase price times "
        "an annual financing rate, times the number of coaches.",
        inputs=(
            FormulaParam(
                symbol="C_coach,purchase",
                ref="column:input_params.composition_types.composition_type_purchase_coach_eur",
                description="Purchase price per coach",
                unit="€/coach",
            ),
            FormulaParam(
                symbol="q_fin",
                ref="column:input_params.operators.operator_financing_quota_per",
                description="Annual financing rate on the purchase price",
                unit="fraction/year",
            ),
            FormulaParam(
                symbol="n",
                description="Coaches needed for the service, incl. reserve",
                unit="coaches",
            ),
        ),
        output=FormulaParam(
            symbol="C_fin",
            description="Annual financing cost",
            unit="€/year",
        ),
    ),
    # Computed per breakdown cell in views.py (additive, so cells sum to
    # the route total); base changed from share-of-amortisation with 0.9.7.
    "fix_overhead_eur": Formula(
        latex=r"C_{fix,oh} = q_{fix,oh} \times "
        r"\left(C_{op,var} - C_{var,oh} + C_{op,fix}\right)",
        description="Fixed overhead — administration, management, "
        "planning: a fixed share on top of all other operator costs. "
        "Charges paid to infrastructure companies are not part of the "
        "base.",
        inputs=(
            FormulaParam(
                symbol="q_fix,oh",
                ref="column:input_params.operators.operator_fix_overhead_quota_per",
                description="Fixed overhead share",
                unit="fraction",
            ),
            FormulaParam(
                symbol="C_op,var",
                description="All variable operator costs",
                unit="€/year",
            ),
            FormulaParam(
                symbol="C_var,oh",
                ref="formula:calc.var_overhead_eur",
                description="Variable overhead (excluded from the base)",
                unit="€/year",
            ),
            FormulaParam(
                symbol="C_op,fix",
                description="All fixed operator costs",
                unit="€/year",
            ),
        ),
        output=FormulaParam(
            symbol="C_fix,oh",
            description="Annual fixed overhead",
            unit="€/year",
        ),
    ),
    "cleaning_eur": Formula(
        latex=r"C_{clean} = c_{clean/day} \times n \times d_{op}",
        description="Cleaning and preparing the train for the next night: "
        "a daily rate per coach times the number of coaches and the "
        "operating days per year.",
        inputs=(
            FormulaParam(
                symbol="c_clean/day",
                ref="column:input_params.composition_types.composition_type_cleaning_eur_day",
                description="Cleaning and preparation rate per coach and day",
                unit="€/coach/day",
            ),
            FormulaParam(
                symbol="n",
                description="Coaches needed for the service",
                unit="coaches",
            ),
            FormulaParam(
                symbol="d_op",
                description="Operating days per year",
                unit="days/year",
            ),
        ),
        output=FormulaParam(
            symbol="C_clean",
            description="Annual cleaning cost",
            unit="€/year",
        ),
    ),
    # n_events is currently 2 per trip — a placeholder rule, see
    # Route.shunting_count and OPEN_TODOS["shunting_y_shape"] in
    # models/route/model.py.
    "shunting_eur": Formula(
        latex=r"C_{shunt} = c_{shunt/event} \times n_{events}",
        description="Moving the train around in stations and yards — "
        "coupling, uncoupling, parking moves: a rate per movement times "
        "the number of movements.",
        inputs=(
            FormulaParam(
                symbol="c_shunt/event",
                ref="column:input_params.track_infrastructures.track_shunting_eur_event",
                description="Cost per shunting movement",
                unit="€/event",
            ),
            FormulaParam(
                symbol="n_events",
                description="Shunting movements per year",
                unit="events/year",
            ),
        ),
        output=FormulaParam(
            symbol="C_shunt",
            description="Annual shunting cost",
            unit="€/year",
        ),
    ),
    # ------------------------------------------------------------------
    # INFRASTRUCTURE
    # ------------------------------------------------------------------
    "tac_eur": Formula(
        latex=r"C_{TAC} = \sum_{seg} \sum_{l \in seg} d_{km,l} \times p_{TAC,country(l)}",
        description="Track access charge — the 'rail toll' paid to each "
        "country's infrastructure company: the distance driven in the "
        "country times its per-kilometre rate.",
        inputs=(
            FormulaParam(
                symbol="d_km,l",
                description="Distance driven in the country",
                unit="km",
            ),
            FormulaParam(
                symbol="p_TAC,country(l)",
                ref="column:input_params.track_infrastructures.track_tac_eur_train_km",
                description="The country's track access charge per train-kilometre",
                unit="€/train-km",
            ),
        ),
        output=FormulaParam(
            symbol="C_TAC",
            description="Annual track access charges",
            unit="€/year",
        ),
    ),
    # Energy per leg comes from the energy model (models/energy/model.py),
    # carried on the route input.
    "energy_eur": Formula(
        latex=r"C_{energy} = \sum_{seg} \sum_{l \in seg} E_{kWh,l} \times p_{energy,country(l)}",
        description="Electricity cost for traction: the energy the train "
        "uses in each country times that country's electricity price.",
        inputs=(
            FormulaParam(
                symbol="E_kWh,l",
                ref="formula:energy.energy_per_leg",
                description="Energy used in the country (from the energy model)",
                unit="kWh",
            ),
            FormulaParam(
                symbol="p_energy,country(l)",
                ref="column:input_params.track_infrastructures.track_energy_price_eur_kwh",
                description="The country's traction electricity price",
                unit="€/kWh",
            ),
        ),
        output=FormulaParam(
            symbol="C_energy",
            description="Annual traction electricity cost",
            unit="€/year",
        ),
    ),
    "station_charge_eur": Formula(
        latex=r"C_{station} = \sum_{stop} c_{stop,charge}",
        description="Station charge: the fee paid for every scheduled "
        "stop at a station, added up over all stops.",
        inputs=(
            FormulaParam(
                symbol="c_stop,charge",
                ref="column:input_params.stop_infrastructures.stop_charge_eur",
                description="Station fee per scheduled stop",
                unit="€/stop",
            ),
        ),
        output=FormulaParam(
            symbol="C_station",
            description="Annual station charges",
            unit="€/year",
        ),
    ),
    "parking_eur": Formula(
        latex=r"C_{park} = \sum_{l \in \text{endpoints}} p_{park,country(l)}",
        description="Overnight parking of the train between two nights of "
        "service: a daily rate at each end point of the route.",
        inputs=(
            FormulaParam(
                symbol="p_park,country(l)",
                ref="column:input_params.track_infrastructures.track_parking_eur_day",
                description="Daily parking rate in the end point's country",
                unit="€/day",
            ),
        ),
        output=FormulaParam(
            symbol="C_park",
            description="Annual overnight parking cost",
            unit="€/year",
        ),
    ),
    # ------------------------------------------------------------------
    # REVENUE / MARGIN
    # ------------------------------------------------------------------
    "ticket_revenue_eur": Formula(
        latex=r"R = \sum_{od} n_{places\_sold,od} \times \bar{f}_{od}",
        description="Ticket income: tickets sold per connection times the "
        "average ticket price. Both are set by the user of the tool — "
        "they are not yet predicted by a demand model.",
        inputs=(
            FormulaParam(
                symbol="n_places_sold,od",
                ref="user",
                description="Places sold per connection and year",
                unit="places/year",
            ),
            FormulaParam(
                symbol="f̄_od",
                ref="user",
                description="Average ticket price on the connection",
                unit="€/ticket",
            ),
        ),
        output=FormulaParam(
            symbol="R",
            description="Annual ticket revenue",
            unit="€/year",
        ),
    ),
    "ebit_margin_eur": Formula(
        latex=r"C_{EBIT} = \sum_{od} R_{od} \times q_{EBIT}",
        description="The operator's profit requirement: a share of ticket "
        "revenue that must remain as operating profit. It is deducted in "
        "the net result — it is not a cost paid to anyone.",
        inputs=(
            FormulaParam(
                symbol="R_od",
                ref="formula:calc.ticket_revenue_eur",
                description="Ticket revenue per connection and year",
                unit="€/year",
            ),
            FormulaParam(
                symbol="q_EBIT",
                ref="column:input_params.operators.operator_ebit_margin_per",
                description="Required operating profit as a share of revenue",
                unit="fraction",
            ),
        ),
        output=FormulaParam(
            symbol="C_EBIT",
            description="Annual profit requirement",
            unit="€/year",
        ),
    ),
    # ------------------------------------------------------------------
    # SUBTOTALS — mirror the Breakdown tree in models/evaluation/views.py
    # exactly (OperatorVariableCost.total_eur, OperatorFixedCost.total_eur,
    # OperatorCost.total_eur, InfrastructureCost.total_eur). Each subtotal
    # is a plain sum of its children — kept as separate formulas (rather
    # than reusing the generic "total_eur" below) so the tree in
    # docs/MODEL.md can link every subtotal to exactly the leaves views.py
    # actually sums.
    # ------------------------------------------------------------------
    "operator_variable_total_eur": Formula(
        latex=r"C_{op,var} = C_{driver} + C_{crew} + C_{coach,maint} + "
        r"C_{loco} + C_{svc} + C_{var,oh}",
        description="Costs that scale with how much the train runs — "
        "driving and staffing hours, kilometres, tickets sold.",
        inputs=(
            FormulaParam(
                symbol="C_driver",
                ref="formula:calc.driver_eur",
                description="Driver cost",
                unit="€/year",
            ),
            FormulaParam(
                symbol="C_crew",
                ref="formula:calc.crew_eur",
                description="Cabin crew cost",
                unit="€/year",
            ),
            FormulaParam(
                symbol="C_coach,maint",
                ref="formula:calc.coach_maintenance_eur",
                description="Coach maintenance cost",
                unit="€/year",
            ),
            FormulaParam(
                symbol="C_loco",
                ref="formula:calc.loco_eur",
                description="Locomotive rental cost",
                unit="€/year",
            ),
            FormulaParam(
                symbol="C_svc",
                ref="formula:calc.svc_stockings_eur",
                description="Onboard service cost",
                unit="€/year",
            ),
            FormulaParam(
                symbol="C_var,oh",
                ref="formula:calc.var_overhead_eur",
                description="Variable overhead",
                unit="€/year",
            ),
        ),
        output=FormulaParam(
            symbol="C_op,var",
            description="Total variable operator cost",
            unit="€/year",
        ),
    ),
    "operator_fixed_total_eur": Formula(
        latex=r"C_{op,fix} = C_{coach,amort} + C_{fin} + C_{fix,oh} + "
        r"C_{clean} + C_{shunt}",
        description="Costs that stay the same regardless of how much the train runs.",
        inputs=(
            FormulaParam(
                symbol="C_coach,amort",
                ref="formula:calc.coach_amortisation_eur",
                description="Coach write-off",
                unit="€/year",
            ),
            FormulaParam(
                symbol="C_fin",
                ref="formula:calc.financing_eur",
                description="Financing cost",
                unit="€/year",
            ),
            FormulaParam(
                symbol="C_fix,oh",
                ref="formula:calc.fix_overhead_eur",
                description="Fixed overhead",
                unit="€/year",
            ),
            FormulaParam(
                symbol="C_clean",
                ref="formula:calc.cleaning_eur",
                description="Cleaning cost",
                unit="€/year",
            ),
            FormulaParam(
                symbol="C_shunt",
                ref="formula:calc.shunting_eur",
                description="Shunting cost",
                unit="€/year",
            ),
        ),
        output=FormulaParam(
            symbol="C_op,fix",
            description="Total fixed operator cost",
            unit="€/year",
        ),
    ),
    "operator_total_eur": Formula(
        latex=r"C_{operator} = C_{op,var} + C_{op,fix}",
        description="Everything the operator spends: variable costs plus fixed costs.",
        inputs=(
            FormulaParam(
                symbol="C_op,var",
                ref="formula:calc.operator_variable_total_eur",
                description="Total variable operator cost",
                unit="€/year",
            ),
            FormulaParam(
                symbol="C_op,fix",
                ref="formula:calc.operator_fixed_total_eur",
                description="Total fixed operator cost",
                unit="€/year",
            ),
        ),
        output=FormulaParam(
            symbol="C_operator",
            description="Total operator cost",
            unit="€/year",
        ),
    ),
    "infrastructure_total_eur": Formula(
        latex=r"C_{infrastructure} = C_{TAC} + C_{energy} + C_{station} + C_{park}",
        description="Everything paid to infrastructure companies: track "
        "access charges, traction electricity, station charges, and "
        "overnight parking.",
        inputs=(
            FormulaParam(
                symbol="C_TAC",
                ref="formula:calc.tac_eur",
                description="Track access charges",
                unit="€/year",
            ),
            FormulaParam(
                symbol="C_energy",
                ref="formula:calc.energy_eur",
                description="Traction electricity cost",
                unit="€/year",
            ),
            FormulaParam(
                symbol="C_station",
                ref="formula:calc.station_charge_eur",
                description="Station charges",
                unit="€/year",
            ),
            FormulaParam(
                symbol="C_park",
                ref="formula:calc.parking_eur",
                description="Overnight parking cost",
                unit="€/year",
            ),
        ),
        output=FormulaParam(
            symbol="C_infrastructure",
            description="Total infrastructure cost",
            unit="€/year",
        ),
    ),
    # ------------------------------------------------------------------
    # AGGREGATES (appear at multiple nesting levels / at the top level)
    # ------------------------------------------------------------------
    "total_eur": Formula(
        latex=r"x_{total} = \sum_i x_i",
        description="Sum of the items directly below it in the cost "
        "breakdown — the same rule applies at every level.",
        inputs=(
            FormulaParam(
                symbol="x_i",
                description="The individual items on that level",
                unit="€/year",
            ),
        ),
        output=FormulaParam(
            symbol="x_total",
            description="Sum of the level's items",
            unit="€/year",
        ),
    ),
    "total_cost_eur": Formula(
        latex=r"C_{total} = C_{operator} + C_{infrastructure}",
        description="Total annual cost: everything the operator spends "
        "plus everything paid to infrastructure companies.",
        inputs=(
            FormulaParam(
                symbol="C_operator",
                ref="formula:calc.operator_total_eur",
                description="All operator costs, fixed and variable",
                unit="€/year",
            ),
            FormulaParam(
                symbol="C_infrastructure",
                ref="formula:calc.infrastructure_total_eur",
                description="All charges paid to infrastructure companies",
                unit="€/year",
            ),
        ),
        output=FormulaParam(
            symbol="C_total",
            description="Total annual cost",
            unit="€/year",
        ),
    ),
    "total_revenue_eur": Formula(
        latex=r"R_{total} = R_{ticket}",
        description="Total annual revenue — currently ticket income is "
        "the only revenue source.",
        inputs=(
            FormulaParam(
                symbol="R_ticket",
                ref="formula:calc.ticket_revenue_eur",
                description="Annual ticket revenue",
                unit="€/year",
            ),
        ),
        output=FormulaParam(
            symbol="R_total",
            description="Total annual revenue",
            unit="€/year",
        ),
    ),
    "net_eur": Formula(
        latex=r"N = R_{total} - C_{total} - C_{EBIT}",
        description="Net annual result: revenue minus all costs minus the "
        "operator's profit requirement. A negative value is the subsidy "
        "the route would need.",
        inputs=(
            FormulaParam(
                symbol="R_total",
                ref="formula:calc.total_revenue_eur",
                description="Total annual revenue",
                unit="€/year",
            ),
            FormulaParam(
                symbol="C_total",
                ref="formula:calc.total_cost_eur",
                description="Total annual cost",
                unit="€/year",
            ),
            FormulaParam(
                symbol="C_EBIT",
                ref="formula:calc.ebit_margin_eur",
                description="The operator's profit requirement",
                unit="€/year",
            ),
        ),
        output=FormulaParam(
            symbol="N",
            description="Net annual result",
            unit="€/year",
        ),
    ),
}
