"""
scenario_serialize.py
======================
Serialization (domain → dict) for GET /api/scenarios (api/scenarios.py)
and the scenario axis of the proposal family.

The `dimensions` block
----------------------
The six selectable scenarios are a grid — two rail networks × three
operating conditions (db/dev/seed.py, models/scenarios/README.md) — but
scenario.scenarios stores no grid coordinates, only a scenario_key
following the convention `infra-<network>[-hsr[-opt-tt]]` and the
routing_graph_key pin. scenario_dimensions() derives the coordinates
from those two fields in this one place so the frontend's scenario
switches (network / HSR / optimised timetable) never parse a key
themselves. The key vocabulary is a contract: a scenario whose key does
not follow it gets `dimensions: null` rather than a guess, and
tests/test_11_scenarios_api.py pins every seeded row. Dedicated columns
become the right home once a condition outside this vocabulary exists.

Public interface:
  scenario_to_dict(scenario) → dict       (one row, every column + dimensions)
  scenario_dimensions(scenario) → dict | None
  scenario_axis_entry(scenario) → dict    (the compact axis shape)
  measure_set_to_dict(measure_set) → dict
  scenario_variant_to_dict(variant) → dict
  scenario_collection_to_dict(scenarios, measure_sets, variants) → dict
      (full body for GET /api/scenarios)
"""

from __future__ import annotations

from models.params import MeasureSet, Scenario, ScenarioVariant

_KEY_PREFIX = "infra-"
_HSR_SUFFIX = "-hsr"
_OPT_TT_SUFFIX = "-hsr-opt-tt"


def scenario_dimensions(scenario: Scenario) -> dict | None:
    """{network, hsr_allowed, optimised_timetable} for a key in the
    `infra-<network>[-hsr[-opt-tt]]` vocabulary — network is the graph
    key's suffix ("infra_2026" → "2026"), so it stays consistent with
    what the scenario actually routes on. None for any other key."""
    key = scenario.scenario_key
    graph = scenario.routing_graph_key or ""
    if not key.startswith(_KEY_PREFIX) or not graph.startswith("infra_"):
        return None
    rest = key[len(_KEY_PREFIX) :]
    if rest.endswith(_OPT_TT_SUFFIX):
        network, hsr, opt_tt = rest[: -len(_OPT_TT_SUFFIX)], True, True
    elif rest.endswith(_HSR_SUFFIX):
        network, hsr, opt_tt = rest[: -len(_HSR_SUFFIX)], True, False
    else:
        network, hsr, opt_tt = rest, False, False
    if not network or network != graph[len("infra_") :]:
        return None
    return {"network": network, "hsr_allowed": hsr, "optimised_timetable": opt_tt}


# =============================================================================
# SINGLE SCENARIO — serialize
# =============================================================================


def scenario_to_dict(scenario: Scenario) -> dict:
    """One scenario.scenarios row as a dict — every column, verbatim."""
    return {
        "scenario_id": scenario.scenario_id,
        "scenario_key": scenario.scenario_key,
        "scenario_name": scenario.scenario_name,
        "description": scenario.description,
        "change_log": scenario.change_log,
        "editor": scenario.editor,
        "created_at": scenario.created_at,
        "is_current_base": scenario.is_current_base,
        "is_current_scenario": scenario.is_current_scenario,
        "track_infrastructures_version": scenario.track_infrastructures_version,
        "track_infrastructure_defaults_version": scenario.track_infrastructure_defaults_version,
        "stop_infrastructures_version": scenario.stop_infrastructures_version,
        "stop_infrastructure_defaults_version": scenario.stop_infrastructure_defaults_version,
        "passage_charges_version": scenario.passage_charges_version,
        "routing_graph_key": scenario.routing_graph_key,
        "dimensions": scenario_dimensions(scenario),
    }


def scenario_axis_entry(scenario: Scenario) -> dict:
    """The scenario as a matrix-axis entry (api/helpers/matrix_serialize.py):
    identity, display name, the two things a cell needs to be understood
    (which graph it routed on, where it sits in the grid) — nothing the
    frontend already holds from GET /api/scenarios."""
    return {
        "scenario_id": scenario.scenario_id,
        "scenario_key": scenario.scenario_key,
        "scenario_name": scenario.scenario_name,
        "is_current_base": scenario.is_current_base,
        "routing_graph_key": scenario.routing_graph_key,
        "dimensions": scenario_dimensions(scenario),
    }


# =============================================================================
# MEASURE SETS AND VARIANTS — serialize
# =============================================================================


def measure_set_to_dict(measure_set: MeasureSet) -> dict:
    """One scenario.measure_sets row as a dict — the flags verbatim, and
    the three factors they resolve to. The factors are on the wire so a
    reader never has to know which flag scales what: today they are all
    1.0 and the flags all false, and WP17 changes both together."""
    return {
        "measure_set_id": measure_set.measure_set_id,
        "key": measure_set.key,
        "description": measure_set.description,
        "vat_exempt": measure_set.vat_exempt,
        "energy_tax_exempt": measure_set.energy_tax_exempt,
        "tac_direct_cost": measure_set.tac_direct_cost,
        "factors": {
            "ticket_revenue": measure_set.ticket_revenue_factor,
            "energy_cost": measure_set.energy_cost_factor,
            "track_access": measure_set.track_access_factor,
        },
    }


def scenario_variant_to_dict(
    variant: ScenarioVariant, scenario: Scenario | None = None
) -> dict:
    """One scenario.scenario_variants row as the axis entry the family
    document and the frontend's variant switch address.

    scenario: the variant's Scenario, when the caller has it — its
    display fields are inlined so a switch can be rendered from the
    variant list alone, without joining against the scenario groups. The
    ids alone (scenario omitted) are the fallback for callers that do not.
    """
    entry = {
        "scenario_variant_id": variant.scenario_variant_id,
        "scenario_id": variant.scenario_id,
        "measure_set_id": variant.measure_set_id,
    }
    if scenario is not None:
        entry.update(scenario_axis_entry(scenario))
        entry["scenario_id"] = scenario.scenario_id
    return entry


# =============================================================================
# SCENARIO COLLECTION — serialize
# =============================================================================


def scenario_collection_to_dict(
    scenarios: list[Scenario],
    measure_sets: list[MeasureSet] | None = None,
    scenario_variants: list[ScenarioVariant] | None = None,
) -> dict:
    """
    Full body for GET /api/scenarios, split into three groups instead of a
    flat is_current=true/false list — scenario.scenarios carries two
    independent current-flags (see Scenario's docstring), so a plain
    boolean split would either collapse or misrepresent one of them:

      current_base       — is_current_base=True (the live default; always
                            exactly one row, or zero if the DB is unseeded)
      current_scenarios   — is_current_scenario=True and is_current_base=False
                            (heads of every other what-if lineage)
      historical_scenarios — is_current_scenario=False (superseded versions
                            within a lineage)

    Every row appears in exactly one group. Each group carries its own
    count alongside total_count for convenience.

    measure_sets / scenario_variants: the second axis and the flattened
    (scenario x measure set) product over it (WP18). Both are flat lists
    beside the groups rather than nested inside them — a variant spans the
    grouping, and the client addresses variants by id. Omitted (None) they
    are absent from the body entirely, which is what a caller that only
    wants the scenario groups gets.
    """
    current_base = [s for s in scenarios if s.is_current_base]
    current_scenarios = [
        s for s in scenarios if s.is_current_scenario and not s.is_current_base
    ]
    historical_scenarios = [s for s in scenarios if not s.is_current_scenario]

    by_scenario_id = {s.scenario_id: s for s in scenarios}
    body = {
        "total_count": len(scenarios),
        "current_base": {
            "count": len(current_base),
            "scenarios": [scenario_to_dict(s) for s in current_base],
        },
        "current_scenarios": {
            "count": len(current_scenarios),
            "scenarios": [scenario_to_dict(s) for s in current_scenarios],
        },
        "historical_scenarios": {
            "count": len(historical_scenarios),
            "scenarios": [scenario_to_dict(s) for s in historical_scenarios],
        },
    }
    if measure_sets is not None:
        body["measure_sets"] = [measure_set_to_dict(m) for m in measure_sets]
    if scenario_variants is not None:
        body["scenario_variants"] = [
            scenario_variant_to_dict(v, by_scenario_id.get(v.scenario_id))
            for v in scenario_variants
        ]
    return body
