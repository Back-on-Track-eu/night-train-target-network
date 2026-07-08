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

CALC_VERSION: str = "1.2.0"

GIT_SHA: str = "unknown"  # injected by CI

# Short, plain-English summary of what this model computes — embedded as-is
# in the "models" section of POST /api/evaluation/calc's response, alongside
# CALC_VERSION and CALC_FORMULAS.
CALC_MODEL_DESCRIPTION: str = (
    "Cost/revenue evaluation model: computes fixed and variable operator costs, "
    "third-party infrastructure charges, and OD-pair ticket revenue for a "
    "fully-built Route, then aggregates and normalises the result into "
    "route / trip-pair / country / OD-pair / stop views."
)

CHANGELOG: dict = {
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
        latex=r"C_{fix,oh} = C_{coach,amort} \times q_{fix,oh}",
        description="Fixed overhead: applied as a share of this composition's own "
        "annual coach amortisation cost.",
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
