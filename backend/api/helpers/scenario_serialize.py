"""
scenario_serialize.py
======================
Serialization (domain → dict) for GET /api/scenarios (api/scenarios.py).

Public interface:
  scenario_collection_to_dict(scenarios) → dict  (full body for GET /api/scenarios)
"""

from __future__ import annotations

from models.params import Scenario

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
