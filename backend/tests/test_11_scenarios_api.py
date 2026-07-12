"""
test_11_scenarios_api.py
=========================
Response contract for the read-only scenario listing endpoint:

  GET /api/scenarios

Covers the three-group response layout (current_base / current_scenarios /
historical_scenarios), per-scenario field shape, count consistency, and
that the seeded base/what-if scenarios (see conftest.py: base_scenario,
whatif_scenario) land in the groups their flags dictate.
"""

import pytest
import requests

from tests.helpers import SCENARIOS_URL

# Every field a scenario dict must expose — mirrors
# scenario_serialize.scenario_to_dict().
SCENARIO_FIELDS = {
    "scenario_id",
    "scenario_key",
    "scenario_name",
    "description",
    "change_log",
    "editor",
    "created_at",
    "is_current_base",
    "is_current_scenario",
    "track_infrastructures_version",
    "track_infrastructure_defaults_version",
    "stop_infrastructures_version",
    "stop_infrastructure_defaults_version",
}

GROUPS = ("current_base", "current_scenarios", "historical_scenarios")


@pytest.fixture(scope="module")
def scenarios_body(api_base):
    resp = requests.get(f"{api_base}{SCENARIOS_URL}", timeout=15)
    assert resp.status_code == 200
    return resp.json()


class TestScenariosResponseLayout:

    def test_top_level_keys(self, scenarios_body):
        """Top level carries total_count plus the three groups."""
        assert set(scenarios_body) >= {"total_count", *GROUPS}

    def test_group_shape(self, scenarios_body):
        """Each group is {count, scenarios} with count matching the list."""
        for group in GROUPS:
            entry = scenarios_body[group]
            assert set(entry) >= {"count", "scenarios"}
            assert entry["count"] == len(entry["scenarios"])

    def test_total_count_matches_group_sum(self, scenarios_body):
        """total_count equals the sum of the three group counts — every
        scenario appears in exactly one group."""
        group_sum = sum(scenarios_body[group]["count"] for group in GROUPS)
        assert scenarios_body["total_count"] == group_sum

    def test_scenarios_have_required_fields(self, scenarios_body):
        """Every scenario, in every group, exposes the full column set."""
        for group in GROUPS:
            for scenario in scenarios_body[group]["scenarios"]:
                missing = SCENARIO_FIELDS - set(scenario)
                assert missing == set(), (
                    f"Scenario '{scenario.get('scenario_id')}' in "
                    f"'{group}' missing: {missing}"
                )


class TestScenariosGrouping:

    def test_current_base_group_flags(self, scenarios_body):
        """Every scenario in current_base has both flags True."""
        for scenario in scenarios_body["current_base"]["scenarios"]:
            assert scenario["is_current_base"] is True
            assert scenario["is_current_scenario"] is True

    def test_current_scenarios_group_flags(self, scenarios_body):
        """current_scenarios holds only non-base current lineage heads."""
        for scenario in scenarios_body["current_scenarios"]["scenarios"]:
            assert scenario["is_current_scenario"] is True
            assert scenario["is_current_base"] is False

    def test_historical_scenarios_group_flags(self, scenarios_body):
        """historical_scenarios holds only superseded versions."""
        for scenario in scenarios_body["historical_scenarios"]["scenarios"]:
            assert scenario["is_current_scenario"] is False

    def test_base_scenario_is_in_current_base_group(
        self, scenarios_body, base_scenario
    ):
        """The seeded is_current_base row appears in current_base, and
        current_base holds exactly that one row."""
        current_base = scenarios_body["current_base"]["scenarios"]
        assert len(current_base) == 1
        assert current_base[0]["scenario_id"] == base_scenario["scenario_id"]
        assert current_base[0]["scenario_key"] == base_scenario["scenario_key"]

    def test_whatif_scenario_is_in_current_scenarios_group(
        self, scenarios_body, whatif_scenario
    ):
        """The seeded what-if lineage head appears in current_scenarios,
        not current_base or historical_scenarios."""
        current_keys = {
            s["scenario_key"] for s in scenarios_body["current_scenarios"]["scenarios"]
        }
        assert whatif_scenario["scenario_key"] in current_keys
