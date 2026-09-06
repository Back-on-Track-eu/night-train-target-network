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

CALC_VERSION: str = "0.9.23"

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
    "0.9.23": {
        "date": "2026-08-30",
        "author": "david",
        "changes": "VALUES CHANGE, no logic change here: the energy model "
        "replaced its flat 28 kWh/km placeholder with the calibrated model "
        "(ENERGY_CALC_VERSION 1.1.0), so every segment's energy_kwh moves "
        "and every figure derived from it moves with it. Fleet-weighted "
        "intensity is 9.19 kWh/km against the 28 assumed before, so "
        "traction energy cost falls by roughly two thirds and every cost "
        "total, margin and net figure that contains it changes. Energy is "
        "now composition-dependent: a heavier or longer train costs more "
        "to move, where the placeholder charged every train the same per "
        "kilometre. Pricing itself is untouched - calc_energy_price.py "
        "multiplies the same rates by different kilowatt-hours. Bumped so "
        "the compute cache misses and stored proposals refresh rather than "
        "serving placeholder-era energy costs as current. See "
        "models/energy/model.py CHANGELOG 1.1.0 and "
        "models/energy/calib/README.md.",
    },
    "0.9.22": {
        "date": "2026-08-17",
        "author": "david",
        "changes": "VALUES CHANGE: shunting and stabling are priced from the "
        "facility calibration instead of two flat placeholder rates. A "
        "shunting event costs what the infrastructure manager charges plus the "
        "market cost of what it does not supply (115-321 EUR/event across "
        "Europe against a flat 575 before, so most routes get cheaper here). "
        "A stabling occupation is priced on the country's own basis against "
        "the scheduled layover and the train's length, so Norway and Croatia "
        "cost nothing on a twelve-hour turnaround where their free allowances "
        "cover it, and the power drawn while standing is charged on top at "
        "14.94 EUR/stabled hour. The flat track_parking_eur_day and the "
        "reference figures are display-only from here. Implementation: "
        "models/infrastructure/facility/calc_facility.py.",
    },
    "0.9.21": {
        "date": "2026-08-17",
        "author": "david",
        "changes": "VALUES CHANGE: traction energy is priced from the "
        "calibrated energy model instead of one flat rate per country. "
        "Three things change per country leg. The electricity price is the "
        "calibrated one (ENERGY_PRICING_CALIBRATION.md) rather than the "
        "placeholder the seed carried — Germany moves 0.142 to 0.2336 "
        "EUR/kWh, Switzerland 0.165 to 0.1527, the EU fallback 0.150 to "
        "0.1553. Austria, Switzerland and Croatia band their tariff, so the "
        "share of a country run inside 22:00-06:00 is priced at the night "
        "rate pro rata, the same clock mechanism the German track access "
        "night rate uses (and independent of it — the two bands differ by "
        "country). And the charge for using the catenary and traction "
        "power-supply installations is now levied where a country levies "
        "it: thirteen do, in three different units, and the track access "
        "calibration excludes every one of them as energy, so until now "
        "nothing priced them. Per-country cost cells also attribute energy "
        "to the country that supplied it rather than spreading a segment "
        "total by distance share — the same correction track access got in "
        "0.9.18. Implementation: "
        "models/infrastructure/energy_pricing/calc_energy_price.py.",
    },
    "0.9.20": {
        "date": "2026-08-13",
        "author": "david",
        "changes": "VALUES CHANGE: per-country and per-OD cells now "
        "normalise against their OWN physics instead of the whole trip "
        "pair's. The NormalisationScope machinery already did this for "
        "route sections; countries and OD pairs were never wired to it and "
        "silently fell back to the pair-wide denominators, which scaled "
        "every per-unit figure down by that cell's share of the route. On "
        "an Amsterdam-Warsaw run, Dutch track access read 0.38 EUR/train-km "
        "where the applied Dutch rate is 2.58, because 190 of 1,310 km were "
        "Dutch. A country cell now divides by the kilometres run in that "
        "country; an OD cell by the span it actually rides, not the cycle "
        "the train runs regardless of who is aboard. per_available_place_km "
        "and per_sold_place_km get the same treatment, so an OD pair's "
        "per-sold figures reflect its own occupancy rather than the pair "
        "average. per_year and per_operating_day are untouched. "
        "CONSEQUENCE: per-unit country and OD cells no longer sum to the "
        "route total and cannot — rates over different denominators are "
        "not additive. The additive identity is now the weighted form, "
        "Sum(cell rate x cell km) = route rate x route km, pinned in "
        "tests/test_30_evaluation_content.py. No response key changes.",
    },
    "0.9.19": {
        "date": "2026-08-13",
        "author": "david",
        "changes": "Locomotive cost is summed over the machines a "
        "composition actually hauls, each at its operator's rate for that "
        "machine, replacing n_locos x one flat operator rate. The rate "
        "moves from input_params.operators to input_params."
        "operator_loco_costs, keyed by (operator, locomotive type) — the "
        "same shape as operator_class_costs, and for the same reason: a "
        "lease price is a commercial term of a pairing, not a property of "
        "either side alone. NO VALUE CHANGE at the seeded catalog: every "
        "composition runs one machine and each operator has exactly one "
        "priced pairing, so the sum equals the old product. An unpriced "
        "pairing now fails the load loudly instead of resolving to a "
        "default. Response change: the operator block exposes "
        "loco_lease_eur_h per machine plus a locos list, in place of the "
        "single loco_full_service_lease_eur_h field.",
    },
    "0.9.18": {
        "date": "2026-08-13",
        "author": "david",
        "changes": "Track access charges are priced from the calibrated "
        "component model instead of one flat per-country rate. Each "
        "country run of a segment is now charged its own day/night "
        "train-km rate, gross-tonne-km rate, seat-km, per-stop, flat "
        "per-train-km and revenue-share terms, plus a peak multiplier or "
        "congestion surcharge where the country declares peak bands; the "
        "separately charged crossings (Storebælt, Øresund, Channel "
        "Tunnel) are billed per traverse, attributed to one segment per "
        "trip at routing time. Night rates split each country run pro "
        "rata by the clock time it spends inside the national band, with "
        "the German rule widening the night rate to the whole German run "
        "for a train carrying night accommodation. Values are seeded in "
        "EUR at 2032 from models/infrastructure/tac/calib. "
        "SEQUENCING: the traffic pre-pass now runs BEFORE segment costs, "
        "since the Swiss revenue share and the Channel Tunnel's "
        "per-passenger fee price traffic rather than distance; "
        "compute_segment_passenger_loads() reads the Route's segments "
        "directly instead of the computed SegmentCosts, which is what "
        "makes that possible. VALUES CHANGE: tac_eur moves substantially "
        "in both directions per country, and the per-country cost view "
        "now attributes the charge each country actually levied instead "
        "of spreading the segment total by distance share (crossing "
        "charges keep the distance split — they have no levying "
        "country). No response key is added or removed; the "
        "CALC_FORMULAS legend gains entries, which is additive. "
        "SegmentCost carries the component breakdown internally as "
        "SegmentCost.tac.",
    },
    "0.9.17": {
        "date": "2026-08-13",
        "author": "david",
        "changes": "Driver and crew rates are route-dependent: the "
        "Dienstplanwirkungsgrad (roster efficiency) is computed per trip "
        "instead of being baked into the seeded hourly rate as a flat "
        "60/70%. operator_driver_costs_eur_h and operator_crew_costs_eur_h "
        "now hold RAW productive-hour wages (54.16 / 48.75 rather than "
        "90.33 / 69.67); five new operators columns carry the roster "
        "parameters. A duty is capped by driving time for drivers "
        "(Directive 2005/47/EC: 8 h on a night shift) and by working time "
        "for onboard staff, so a trip crossing a duty boundary needs relief "
        "crews and each relief adds a fixed unproductive allowance — "
        "efficiency steps down at every boundary and recovers as that "
        "allowance amortises over a longer trip. VALUES CHANGE: driver_eur "
        "and crew_eur rise on trips longer than one duty (reference night "
        "route ~+17% on both rates, ~+4% on total operator cost) and are "
        "unchanged on short ones; refurbished seat coaches additionally "
        "carry 0.25 attendants for door-sensor-less despatch. No response "
        "key is added or removed — the CALC_FORMULAS legend gains entries, "
        "which is additive. Numbered 0.9.17 rather than 0.9.15: this work "
        "was developed in parallel on the calib branch, where it briefly "
        "carried 0.9.15, and staging independently used 0.9.15 and 0.9.16 "
        "in the meantime.",
    },
    "0.9.16": {
        "date": "2026-08-12",
        "author": "david",
        "changes": "per_trip_pair_per_section fix: sections were enumerated "
        "from ticketed OD relations, so any stop range bounded by a night "
        "stop (excluded from OD generation by the stopgap demand model) had "
        "no cell — the frontend section slider showed 'No data' for it. "
        "Sections are now every ordered pair of a trip's stops, independent "
        "of demand. Section keys are additionally canonicalised to the "
        "outbound trip's stop order, folding both directions of a pair into "
        "one undirected cell (Breakdown values and NormalisationScope "
        "physics accumulate) — previously keys were directional and the "
        "frontend's outbound-ordered lookup silently showed the outbound "
        "direction only. Allocation rules per section are unchanged. "
        "Frontend-visible: section cell values roughly double (both "
        "directions), reverse-ordered keys disappear, cells exist for every "
        "slider range.",
    },
    "0.9.15": {
        "date": "2026-08-12",
        "author": "david",
        "changes": "ADDITIVE output change: the gallery summary row "
        "(summary.py's build_summary_row(), returned as 'summary' by "
        "POST /api/proposal/calc and stored in "
        "proposals.proposal_summaries) gains country_relations — the "
        "sorted 'AA__BB' keys of every country-to-country relation the "
        "route actually serves, derived from od_pairs so a merely "
        "transited country contributes nothing. Ranking dimension behind "
        "the new GET /api/proposals/stats (§7.7). No cost, revenue, "
        "margin or demand number changes; the bump exists so the version "
        "refresh (§4.2) rewrites every stored summary with the new "
        "column.",
    },
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
    # Roster efficiency is not itself a cost leaf — it is documented as a
    # formula so the driver/crew legend can link to its derivation.
    "roster_efficiency_driver": Formula(
        latex=r"\eta = \eta_{ref} \cdot \frac{t_{train,h}}"
        r"{t_{train,h} + t_{relief} \cdot (n_{duty} - 1)}, \quad "
        r"n_{duty} = \left\lceil \frac{t_{basis,h}}{t_{duty,max}} \right\rceil",
        description="Dienstplanwirkungsgrad — the share of paid staff "
        "hours that is actually productive. Paid time exceeds time on the "
        "train because of sign-on and sign-off, positioning to and from "
        "the train, rest away from the home base, and reserve cover. A "
        "shift may not exceed a legal maximum, so a long trip has to be "
        "worked by two or more crews in succession; each handover adds a "
        "fixed unproductive allowance. The value therefore drops at every "
        "shift boundary and then recovers as that fixed allowance is "
        "spread over a longer trip.",
        inputs=(
            FormulaParam(
                symbol="eta_ref",
                ref="column:input_params.operators.operator_driver_roster_eff_ref",
                description="Efficiency when the trip fits a single shift "
                "(operator_crew_roster_eff_ref for onboard staff)",
                unit="–",
            ),
            FormulaParam(
                symbol="t_train,h",
                description="Time the staff member is on the train",
                unit="h",
            ),
            FormulaParam(
                symbol="t_basis,h",
                description="Hours measured against the shift cap — "
                "driving time for drivers, time on train for onboard staff",
                unit="h",
            ),
            FormulaParam(
                symbol="t_duty,max",
                ref="column:input_params.operators.operator_driver_max_duty_h",
                description="Longest permitted shift "
                "(operator_crew_max_duty_h for onboard staff)",
                unit="h",
            ),
            FormulaParam(
                symbol="t_relief",
                ref="column:input_params.operators.operator_relief_allowance_h",
                description="Unproductive hours added per crew handover",
                unit="h",
            ),
        ),
        output=FormulaParam(
            symbol="eta",
            description="Productive share of paid hours for this trip",
            unit="–",
        ),
    ),
    "driver_eur": Formula(
        latex=r"C_{driver} = \frac{c_{driver/h}}{\eta_{driver}} \times "
        r"\left( \sum_{seg} t_{drive,h} \cdot f_{driver} + \sum_{stop} "
        r"t_{dwell,h} \cdot f_{driver} \right)",
        description="Driver cost: the driver wage per productive hour, "
        "divided by the share of paid hours that is productive, times all "
        "hours the driver is on duty — driving between stops and waiting "
        "at them. Trips too long for one driver shift need a relief "
        "driver, which lowers that share and raises the effective rate.",
        inputs=(
            FormulaParam(
                symbol="c_driver/h",
                ref="column:input_params.operators.operator_driver_costs_eur_h",
                description="Driver wage per productive hour",
                unit="€/h",
            ),
            FormulaParam(
                symbol="eta_driver",
                ref="formula:calc.roster_efficiency_driver",
                description="Share of paid driver hours that is productive",
                unit="–",
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
        latex=r"C_{crew} = \frac{c_{crew/h}}{\eta_{crew}} \times \left( "
        r"\sum_{seg} t_{drive,h} \cdot n_{crew} + \sum_{stop} "
        r"t_{dwell,h} \cdot n_{crew} \right)",
        description="Cabin crew cost: the crew wage per productive hour, "
        "divided by the share of paid hours that is productive, times all "
        "hours the crew is on board — while driving and while waiting at "
        "stops. Trips too long for one shift need a relief crew, which "
        "lowers that share and raises the effective rate.",
        inputs=(
            FormulaParam(
                symbol="c_crew/h",
                ref="column:input_params.operators.operator_crew_costs_eur_h",
                description="Crew wage per productive hour, per attendant",
                unit="€/h",
            ),
            FormulaParam(
                symbol="eta_crew",
                ref="formula:calc.roster_efficiency_driver",
                description="Share of paid crew hours that is productive",
                unit="–",
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
                ref="column:input_params.operator_loco_costs.operator_loco_lease_eur_h",
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
        latex=r"C_{TAC} = \sum_{seg}\Big[\sum_{c \in seg} \big( "
        r"d_{c}\,(1{-}\nu_c)\,b_{day,c}\,\mu_c + d_{c}\,\nu_c\,b_{night,c} "
        r"+ d_{c}\,(\gamma_c m_{gross} + \sigma_c P + \phi_c + \kappa_c \pi_c) "
        r"\big) + \sum_{stop} h_{country(stop)} "
        r"+ \rho_{c}\,R_{seg,c} + \sum_{x \in seg}\big(F_x + f_x n_{seg}\big)\Big]",
        description="Track access charge — what the operator pays each "
        "country's infrastructure company for using the track. Every "
        "country charges its own mix: a rate per kilometre driven (higher "
        "or lower at night), a rate per tonne of train weight and "
        "kilometre, in some countries a rate per seat, a flat "
        "administrative add-on, a fee per stop made, a share of the "
        "ticket revenue earned there, and a surcharge for running through "
        "a congested area at rush hour. Crossings billed separately — the "
        "Storebælt and Øresund links and the Channel Tunnel — are added "
        "per crossing, one of them also per passenger carried. A term a "
        "country does not levy is simply absent.",
        inputs=(
            FormulaParam(
                symbol="d_c",
                description="Distance driven in this country on this segment",
                unit="km",
            ),
            FormulaParam(
                symbol="nu_c",
                ref="formula:calc.tac_night_share",
                description="Share of the run in this country priced at the night rate",
                unit="–",
            ),
            FormulaParam(
                symbol="b_day,c",
                ref="column:input_params.track_infrastructures.track_tac_b_day",
                description="The country's day rate per train-kilometre",
                unit="€/train-km",
            ),
            FormulaParam(
                symbol="b_night,c",
                ref="column:input_params.track_infrastructures.track_tac_b_night",
                description="The country's night rate per train-kilometre",
                unit="€/train-km",
            ),
            FormulaParam(
                symbol="gamma_c",
                ref="column:input_params.track_infrastructures.track_tac_gamma",
                description="The country's rate per tonne of train weight "
                "and kilometre",
                unit="€/(t·km)",
            ),
            FormulaParam(
                symbol="m_gross",
                ref="column:input_params.loco_types.loco_type_weight_t",
                description="Weight of the whole train — coaches plus locomotives",
                unit="t",
            ),
            FormulaParam(
                symbol="sigma_c",
                ref="column:input_params.track_infrastructures.track_tac_seat_km",
                description="The country's rate per place and kilometre",
                unit="€/(place·km)",
            ),
            FormulaParam(
                symbol="P",
                description="Places the train offers",
                unit="places",
            ),
            FormulaParam(
                symbol="phi_c",
                ref="column:input_params.track_infrastructures.track_tac_fixed_per_train_km",
                description="The country's flat administrative add-on per "
                "train-kilometre",
                unit="€/train-km",
            ),
            FormulaParam(
                symbol="kappa_c",
                ref="column:input_params.track_infrastructures.track_tac_congestion_surcharge_eur_km",
                description="The country's congestion surcharge per train-kilometre",
                unit="€/train-km",
            ),
            FormulaParam(
                symbol="pi_c",
                ref="formula:calc.tac_peak_share",
                description="Share of the run in this country falling in rush hour",
                unit="–",
            ),
            FormulaParam(
                symbol="mu_c",
                ref="column:input_params.track_infrastructures.track_tac_peak_multiplier",
                description="Factor the day rate is multiplied by over the "
                "rush-hour share of the run (1 outside it)",
                unit="factor",
            ),
            FormulaParam(
                symbol="h_country(stop)",
                ref="column:input_params.track_infrastructures.track_tac_per_stop",
                description="Fee for making one stop, at that stop's own "
                "country rate. A trip's first segment pays for both of its "
                "ends, since no other segment owns the starting station",
                unit="€/stop",
            ),
            FormulaParam(
                symbol="rho_c",
                ref="column:input_params.track_infrastructures.track_tac_revenue_share",
                description="Share of the ticket revenue earned in this "
                "country that the infrastructure manager takes",
                unit="fraction",
            ),
            FormulaParam(
                symbol="R_seg,c",
                description="Ticket revenue attributable to this segment in "
                "this country, per train run",
                unit="€/trip",
            ),
            FormulaParam(
                symbol="F_x",
                ref="column:input_params.passage_charges.passage_fixed_eur",
                description="Charge for crossing a separately billed link, per train",
                unit="€/traverse",
            ),
            FormulaParam(
                symbol="f_x",
                ref="column:input_params.passage_charges.passage_per_passenger_eur",
                description="Charge for crossing a separately billed link, "
                "per passenger",
                unit="€/passenger",
            ),
            FormulaParam(
                symbol="n_seg",
                description="Passengers aboard on this segment, per train run",
                unit="passengers",
            ),
        ),
        output=FormulaParam(
            symbol="C_TAC",
            description="Annual track access charges",
            unit="€/year",
        ),
    ),
    "tac_night_share": Formula(
        latex=r"\nu_c = \begin{cases} 0 & \text{no night tariff} \\ "
        r"1 & \text{widening applies} \\ "
        r"\dfrac{|[t_{in}, t_{out}) \cap B_{night,c}|}{t_{out} - t_{in}} "
        r"& \text{otherwise}\end{cases}",
        description="How much of a country run is charged at the night "
        "rate. Countries with a night tariff define a band — Germany "
        "23:00 to 06:00, for instance — and the run is split between day "
        "and night rate in proportion to the clock time it actually "
        "spends inside it, rather than being priced entirely one way "
        "based on where its middle falls. Germany adds a rule of its own: "
        "a train carrying couchettes, sleepers or capsules is charged the "
        "night rate over its whole German run, whatever the clock says.",
        inputs=(
            FormulaParam(
                symbol="t_in, t_out",
                description="When the train enters and leaves the country "
                "on this segment",
                unit="min",
            ),
            FormulaParam(
                symbol="B_night,c",
                ref="column:input_params.track_infrastructures.track_tac_night_band_start",
                description="The country's night tariff band (band end: "
                "track_tac_night_band_end)",
                unit="time of day",
            ),
        ),
        output=FormulaParam(
            symbol="nu_c",
            description="Share of the country run priced at the night rate",
            unit="–",
        ),
    ),
    "tac_peak_share": Formula(
        latex=r"\pi_c = w \cdot \frac{\sum_{j} |[t_{in}, t_{out}) "
        r"\cap B_{peak,c,j}|}{t_{out} - t_{in}}, \quad "
        r"w = \tfrac{5}{7} \text{ if weekdays only, else } 1",
        description="How much of a country run falls in rush hour. Austria "
        "and Switzerland charge extra for running through a congested area "
        "during the morning or evening commuter peak. Because the tool "
        "knows a departure's clock time but not which day of the week it "
        "runs, a peak that applies Monday to Friday only is charged at "
        "five sevenths of the overlap — the average over a week — rather "
        "than all or nothing.",
        inputs=(
            FormulaParam(
                symbol="t_in, t_out",
                description="When the train enters and leaves the country "
                "on this segment",
                unit="min",
            ),
            FormulaParam(
                symbol="B_peak,c,j",
                ref="column:input_params.track_infrastructures.track_tac_peak_band1_start",
                description="The country's two daily peak bands "
                "(track_tac_peak_band1_* and track_tac_peak_band2_*)",
                unit="time of day",
            ),
            FormulaParam(
                symbol="w",
                ref="standard:INFRASTRUCTURE.WEEKDAY_BLEND",
                description="Weekday blend, applied where the bands run "
                "Monday to Friday only",
                unit="–",
            ),
        ),
        output=FormulaParam(
            symbol="pi_c",
            description="Share of the country run falling in rush hour",
            unit="–",
        ),
    ),
    # Energy per leg comes from the energy model (models/energy/model.py),
    # carried on the route input; this prices it.
    "energy_night_share": Formula(
        latex=r"\nu^{E}_{c} = \frac{|[t_{in},t_{out}] \cap B^{E}_{c}|}{t_{out}-t_{in}}",
        description="Share of a country leg whose electricity is billed at "
        "the night rate: how much of the time the train spends in the "
        "country falls inside that country's electricity night tariff "
        "window. Only Austria, Switzerland and Croatia have one. The share "
        "of the clock is applied to the kilowatt-hours drawn, which is exact "
        "at constant speed — the routed geometry does not record where along "
        "the leg the clock crossed the boundary. This window is not the "
        "track access night band: Germany discounts track access at night "
        "and not electricity, Switzerland the reverse.",
        inputs=(
            FormulaParam(
                symbol="t_in, t_out",
                description="When the train enters and leaves the country "
                "on this segment",
                unit="min",
            ),
            FormulaParam(
                symbol="B^E_c",
                ref="column:input_params.track_infrastructures.track_energy_night_band_start",
                description="The country's electricity night band "
                "(track_energy_night_band_start and _end)",
                unit="time of day",
            ),
        ),
        output=FormulaParam(
            symbol="nu^E_c",
            description="Share of the country leg billed at the night rate",
            unit="–",
        ),
    ),
    "energy_eur": Formula(
        latex=r"C_{energy} = \sum_{seg} \sum_{c \in seg} \left[ E_{kWh,c} \left( (1-\nu^{E}_{c}) p_{c} + \nu^{E}_{c} p^{night}_{c} \right) + d_{c} \left( e_{c} + e^{gt}_{c} m_{gross} \right) \right]",
        description="Traction energy cost: the electricity the train uses in "
        "each country at that country's price, plus what the "
        "infrastructure manager charges for supplying it through the "
        "catenary. The electricity is billed at the day rate outside the "
        "national night window and at the night rate inside it. The supply "
        "charge is levied per kilometre by nine countries and on the weight "
        "moved by three; it is kept in the unit each one publishes rather "
        "than converted into a price per kilowatt-hour, since converting it "
        "would depend on an assumed consumption.",
        inputs=(
            FormulaParam(
                symbol="E_kWh,c",
                ref="formula:energy.energy_per_leg",
                description="Energy used in the country (from the energy model)",
                unit="kWh",
            ),
            FormulaParam(
                symbol="p_c",
                ref="column:input_params.track_infrastructures.track_energy_price_eur_kwh",
                description="The country's day traction electricity price",
                unit="€/kWh",
            ),
            FormulaParam(
                symbol="p^night_c",
                ref="column:input_params.track_infrastructures.track_energy_price_night_eur_kwh",
                description="Its night-band price, where the tariff is banded",
                unit="€/kWh",
            ),
            FormulaParam(
                symbol="nu^E_c",
                ref="formula:calc.energy_night_share",
                description="Share of the country leg billed at the night rate",
                unit="–",
            ),
            FormulaParam(
                symbol="e_c",
                ref="column:input_params.track_infrastructures.track_energy_catenary_eur_train_km",
                description="Charge for using the catenary and traction "
                "power-supply installations, per train-kilometre",
                unit="€/train-km",
            ),
            FormulaParam(
                symbol="e^gt_c",
                ref="column:input_params.track_infrastructures.track_energy_catenary_eur_gross_tonne_km",
                description="The same charge where the country levies it on "
                "the weight moved instead",
                unit="€/gross-tonne-km",
            ),
            FormulaParam(
                symbol="m_gross",
                description="Gross weight of the whole consist, coaches plus "
                "locomotives",
                unit="t",
            ),
            FormulaParam(
                symbol="d_c",
                description="Kilometres run in the country on this segment",
                unit="km",
            ),
        ),
        output=FormulaParam(
            symbol="C_energy",
            description="Annual traction energy cost",
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
