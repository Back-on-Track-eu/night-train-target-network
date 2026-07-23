"""
version.py
==========
Version constant and full calculation model definition for the
Night Train Cost/Revenue Evaluation model.

This file is the authoritative source for:
  - CALC_VERSION: bump when any EvaluationResult output changes
  - CALC_FORMULAS: LaTeX + description for every calculation step
  - CHANGELOG: what changed in each version

Bump CALC_VERSION when:
  - Revenue or cost calculation logic changes
  - New cost/revenue line items are added or removed
  - Normalisation logic changes
  - Any change to EvaluationResult or its nested dataclasses

CALC_FORMULAS is imported by calc.py and embedded in every
EvaluationResult so the frontend can render the full calculation
tree with LaTeX formulas and descriptions.

TODO: Injected at build time by CI — see .github/workflows/backend-tests.yml
"""

from __future__ import annotations
from dataclasses import dataclass

# =============================================================================
# VERSION
# =============================================================================

CALC_VERSION: str = "0.9.8"

GIT_SHA: str = "unknown"  # injected by CI

# Decimal places for the EUR leaves of each normalised Breakdown — precision
# must scale with the divisor. Annual figures are naturally 2dp currency, but
# €/place-km values on a realistic route are of order 1e-3 to 1e-2 per leaf,
# so rounding them to 2dp quantizes real differences into noise (the root
# cause of the 0.9.4 per_available_place_km divergence — see CHANGELOG 0.9.5).
NORMALISATION_NDIGITS: dict[str, int] = {
    "by_class_main": 2,
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

# Short, plain-English summary of what this model computes — embedded as-is
# in the "models" section of POST /api/evaluation/calc's response, alongside
# CALC_VERSION and CALC_FORMULAS.
CALC_MODEL_DESCRIPTION: str = (
    "Cost/revenue evaluation model: computes fixed and variable operator costs, "
    "third-party infrastructure charges, and OD-pair ticket revenue for a "
    "fully-built Route, then aggregates and normalises the result into "
    "route / trip-pair / country / OD-pair / route-section / stop views."
)

CHANGELOG: dict = {
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
# CALC FORMULA REGISTRY
# =============================================================================


@dataclass(frozen=True)
class CalcFormula:
    """
    One entry in the calculation model — LaTeX formula + plain-English description.
    Keyed by a short snake_case identifier in CALC_FORMULAS.

    latex       — KaTeX/MathJax-compatible LaTeX string
    description — plain English explanation of what this step calculates
    """

    latex: str
    description: str


CALC_FORMULAS: dict[str, CalcFormula] = {
    "class_main_allocation": CalcFormula(
        latex=r"s_{c} = (1-f_{svc})\left(X \frac{L_c}{L_{rev}} + (1-X)\frac{W_c}{W_{rev}}\right) + f_{svc}\frac{P_c}{P}",
        description="Hardware-cost share of class_main c: X-blend of its "
        "section length/weight over the revenue space (excl. service "
        "areas), plus the service-area fraction f_svc allocated per "
        "place. X = composition_type_length_cost_prop (0.7). Crew, "
        "energy, stockings and revenue leaves use their own native bases "
        "— see views.ClassMainShares.",
    ),
    "per_sold_place_km_by_class": CalcFormula(
        latex=r"c_{c} = \frac{s_{c} \cdot C}{pkm^{sold}_{c}}",
        description="Per-sold-place-km cost of class_main c: its "
        "allocated cost share over its OWN annual sold place-km. Unsold "
        "capacity concentrates cost on sold places within the class.",
    ),
    # ------------------------------------------------------------------
    # Every key below matches, verbatim, a field name in breakdown_to_dict()
    # output (models/evaluation views under the "views" section) — see
    # api/helpers/evaluation_serialize.py: EVALUATION_OUTPUT_FIELDS.
    # Formulas for internal-only concepts (per-class allocation, capacity-
    # based demand modelling, old normalisation names) were removed here
    # since they don't correspond to any field actually output under
    # "views" — see views_meta in the response for normalisation
    # descriptions instead.
    # ------------------------------------------------------------------
    # OPERATOR — VARIABLE
    # ------------------------------------------------------------------
    "driver_eur": CalcFormula(
        latex=r"C_{driver} = c_{driver/h} \times \left( \sum_{seg} t_{drive,h} \cdot f_{driver} "
        r"+ \sum_{stop} t_{dwell,h} \cdot f_{driver} \right)",
        description="Driver cost: hourly driver rate multiplied by driver-factor-weighted "
        "driving time (all segments) plus dwell time (all stop calls) in scope.",
    ),
    "crew_eur": CalcFormula(
        latex=r"C_{crew} = c_{crew/h} \times \left( \sum_{seg} t_{drive,h} \cdot n_{crew} "
        r"+ \sum_{stop} t_{dwell,h} \cdot n_{crew} \right)",
        description="Cabin crew cost: hourly crew rate multiplied by crew-count-weighted "
        "driving time (all segments) plus dwell time (all stop calls) in scope.",
    ),
    "coach_maintenance_eur": CalcFormula(
        latex=r"C_{coach,maint} = \sum_{seg} c_{coach,maint/km} \times d_{km,seg}",
        description="Variable coach maintenance: per-km maintenance rate multiplied by "
        "segment distance, summed across all segments in scope. Locomotive maintenance "
        "is bundled into loco_eur (full-service lease), not charged separately here.",
    ),
    "loco_eur": CalcFormula(
        latex=r"C_{loco} = c_{loco,lease/h} \times \frac{t_{loco,propulsion,min}}{60}",
        description="Locomotive full-service lease cost: hourly lease rate multiplied by "
        "locomotive propulsion minutes, deduplicated route-wide (see Route.loco_propulsion_min) "
        "so a locomotive shared across trip pairs is billed once, not once per pair.",
    ),
    "svc_stockings_eur": CalcFormula(
        latex=r"C_{svc} = \sum_{od} c_{svc,class(od)/place} \times n_{places\_sold,od}",
        description="Onboard service and stockings cost: per-place service cost for the "
        "OD pair's class, multiplied by places sold, summed across all OD pairs in scope.",
    ),
    "var_overhead_eur": CalcFormula(
        latex=r"C_{var,oh} = \sum_{od} R_{od} \times q_{var,oh}",
        description="Variable overhead: each OD pair's ticket revenue multiplied by the "
        "operator's variable overhead quota, summed across all OD pairs in scope.",
    ),
    # ------------------------------------------------------------------
    # OPERATOR — FIXED
    # ------------------------------------------------------------------
    "coach_amortisation_eur": CalcFormula(
        latex=r"C_{coach,amort} = \frac{C_{coach,purchase}}{T_{coach,amort}} \times n",
        description="Annual coach amortisation: purchase cost divided by amortisation "
        "period in years, multiplied by the number of coaches required for this "
        "composition's fleet (already availability-adjusted).",
    ),
    "financing_eur": CalcFormula(
        latex=r"C_{fin} = C_{coach,purchase} \times q_{fin} \times n",
        description="Annual financing cost: coach purchase cost multiplied by the "
        "operator's financing quota and the number of coaches required.",
    ),
    "fix_overhead_eur": CalcFormula(
        latex=r"C_{fix,oh} = q_{fix,oh} \times \left(C_{op,var} - C_{var,oh} + C_{op,fix}\right)",
        description="Fixed overhead: the operator's quota applied to all other "
        "annualised operator operating costs — variable costs excluding the "
        "revenue-side variable overhead, plus fixed costs. Third-party "
        "infrastructure charges are outside the base. Computed per breakdown "
        "cell in views.py (additive, so cells sum to the route total); "
        "changed from share-of-amortisation with CALC_VERSION 0.9.7.",
    ),
    "cleaning_eur": CalcFormula(
        latex=r"C_{clean} = c_{clean/day} \times n \times d_{op}",
        description="Cleaning and service preparation cost: daily cleaning rate per "
        "coach multiplied by coach count and operating days per year.",
    ),
    "shunting_eur": CalcFormula(
        latex=r"C_{shunt} = c_{shunt/event} \times n_{events}",
        description="Shunting cost: per-event rate multiplied by the number of "
        "shunting events for this trip (currently 2 per trip — a placeholder rule, "
        "see Route.shunting_count).",
    ),
    # ------------------------------------------------------------------
    # INFRASTRUCTURE
    # ------------------------------------------------------------------
    "tac_eur": CalcFormula(
        latex=r"C_{TAC} = \sum_{seg} \sum_{l \in seg} d_{km,l} \times p_{TAC,country(l)}",
        description="Track access charge: distance multiplied by the country's TAC "
        "rate, summed over every country leg of every segment in scope.",
    ),
    "energy_eur": CalcFormula(
        latex=r"C_{energy} = \sum_{seg} \sum_{l \in seg} E_{kWh,l} \times p_{energy,country(l)}",
        description="Traction energy cost: energy consumed (from the energy model — "
        "see 'models.energy' — carried on the route input) multiplied by the "
        "country's electricity price, summed over every country leg of every "
        "segment in scope.",
    ),
    "station_charge_eur": CalcFormula(
        latex=r"C_{station} = \sum_{stop} c_{stop,charge}",
        description="Station access charge: sum of the per-call station charge for "
        "every stop call on the trips in scope.",
    ),
    "parking_eur": CalcFormula(
        latex=r"C_{park} = \sum_{l \in \text{endpoints}} p_{park,country(l)}",
        description="Overnight stabling cost: sum of the daily parking rate for each "
        "unique overnight parking location in scope.",
    ),
    # ------------------------------------------------------------------
    # REVENUE / MARGIN
    # ------------------------------------------------------------------
    "ticket_revenue_eur": CalcFormula(
        latex=r"R = \sum_{od} n_{places\_sold,od} \times \bar{f}_{od}",
        description="Ticket revenue: annual places sold multiplied by average fare, "
        "summed across all OD pairs in scope. places_sold and avg_price are "
        "user-supplied route inputs, not derived from a utilisation/capacity model.",
    ),
    "ebit_margin_eur": CalcFormula(
        latex=r"C_{EBIT} = \sum_{od} R_{od} \times q_{EBIT}",
        description="EBIT margin target: each OD pair's ticket revenue multiplied by "
        "the operator's required EBIT margin quota, summed across all OD pairs in "
        "scope. A deduction from the net result, not a cost paid to any third party.",
    ),
    # ------------------------------------------------------------------
    # AGGREGATES (appear at multiple nesting levels / at the top level)
    # ------------------------------------------------------------------
    "total_eur": CalcFormula(
        latex=r"x_{total} = \sum_i x_i",
        description="Sum of the sibling fields in this branch of the breakdown tree — "
        "e.g. cost.operator.variable.total_eur sums driver_eur through var_overhead_eur; "
        "cost.total_eur sums operator.total_eur and infrastructure.total_eur. Same "
        "formula at every nesting level where 'total_eur' appears.",
    ),
    "total_cost_eur": CalcFormula(
        latex=r"C_{total} = C_{operator} + C_{infrastructure}",
        description="Total annual cost: sum of all operator costs (variable + fixed) "
        "and all infrastructure costs.",
    ),
    "total_revenue_eur": CalcFormula(
        latex=r"R_{total} = R_{ticket}",
        description="Total annual revenue — currently ticket revenue is the only "
        "revenue line.",
    ),
    "net_eur": CalcFormula(
        latex=r"N = R_{total} - C_{total} - C_{EBIT}",
        description="Net annual result: total revenue minus total cost minus the "
        "EBIT margin carve-out.",
    ),
}
