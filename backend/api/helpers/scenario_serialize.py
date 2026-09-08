"""
scenario_serialize.py
======================
Serialization (domain → dict) for GET /api/scenarios (api/scenarios.py)
and the scenario axis of POST /api/proposal/calc/matrix.

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
  scenario_axis_entry(scenario) → dict    (the compact matrix-axis shape)
  scenario_collection_to_dict(scenarios) → dict  (full body for GET /api/scenarios)
"""

from __future__ import annotations

from models.params import Scenario

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
# SCENARIO COLLECTION — serialize
# =============================================================================


def scenario_collection_to_dict(scenarios: list[Scenario]) -> dict:
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
    """
    current_base = [s for s in scenarios if s.is_current_base]
    current_scenarios = [
        s for s in scenarios if s.is_current_scenario and not s.is_current_base
    ]
    historical_scenarios = [s for s in scenarios if not s.is_current_scenario]

    return {
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
