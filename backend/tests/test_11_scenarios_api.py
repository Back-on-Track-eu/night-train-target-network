"""
test_11_scenarios_api.py
=========================
Response contract for the read-only scenario listing endpoint:

  GET /api/scenarios

Covers the three-group response layout (current_base / current_scenarios /
historical_scenarios), per-scenario field shape, count consistency, and
that the seeded scenarios (see conftest.py: base_scenario, hsr_scenario,
historical_scenario, scenarios_2032) land in the groups their flags
dictate. Six scenarios are selectable — three operating conditions on
each of the two networks — plus one superseded revision.

Since WP18 the body also carries the second axis: measure_sets (what the
state does) and scenario_variants, the materialised cross product the
proposal family is computed over.
"""

from collections import Counter

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
    "passage_charges_version",
    "routing_graph_key",
    "dimensions",
}

# scenario_key → dimensions, for every seeded row (db/dev/seed.py) — the
# derivation contract of scenario_serialize.scenario_dimensions().
EXPECTED_DIMENSIONS = {
    "infra-2026": {
        "network": "2026",
        "hsr_allowed": False,
        "optimised_timetable": False,
    },
    "infra-2026-hsr": {
        "network": "2026",
        "hsr_allowed": True,
        "optimised_timetable": False,
    },
    "infra-2026-hsr-opt-tt": {
        "network": "2026",
        "hsr_allowed": True,
        "optimised_timetable": True,
    },
    "infra-2032": {
        "network": "2032",
        "hsr_allowed": False,
        "optimised_timetable": False,
    },
    "infra-2032-hsr": {
        "network": "2032",
        "hsr_allowed": True,
        "optimised_timetable": False,
    },
    "infra-2032-hsr-opt-tt": {
        "network": "2032",
        "hsr_allowed": True,
        "optimised_timetable": True,
    },
}

GROUPS = ("current_base", "current_scenarios", "historical_scenarios")

# Mirrors scenario_serialize.measure_set_to_dict() / scenario_variant_to_dict().
MEASURE_SET_FIELDS = {
    "measure_set_id",
    "key",
    "description",
    "vat_exempt",
    "energy_tax_exempt",
    "tac_direct_cost",
    "factors",
}
MEASURE_SET_FACTORS = {"ticket_revenue", "energy_cost", "track_access"}
VARIANT_FIELDS = {"scenario_variant_id", "scenario_id", "measure_set_id"}


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


class TestScenariosRoutingGraphPin:
    def test_every_scenario_pins_a_known_routing_graph(self, scenarios_body):
        """routing_graph_key is one of the two seeded graphs on every
        scenario, in every group (db/dev/seed.py's scenario section). A
        key outside that set means the API is serving a scenario no
        deployment can route."""
        for group in GROUPS:
            for scenario in scenarios_body[group]["scenarios"]:
                assert scenario["routing_graph_key"] in {"infra_2026", "infra_2032"}

    def test_both_networks_are_offered(self, scenarios_body):
        """Both networks reach the API as selectable scenarios — three
        operating conditions each, per the version grid in db/dev/seed.py.
        Catches a seed that inserted only one half of it."""
        selectable = [
            *scenarios_body["current_base"]["scenarios"],
            *scenarios_body["current_scenarios"]["scenarios"],
        ]
        by_graph = Counter(s["routing_graph_key"] for s in selectable)
        assert by_graph == {"infra_2026": 3, "infra_2032": 3}, by_graph


class TestScenarioDimensions:
    def test_every_seeded_scenario_has_grid_coordinates(self, scenarios_body):
        """dimensions is derived from scenario_key + routing_graph_key
        (scenario_serialize.py) — every seeded row, superseded revision
        included, lands on its grid position."""
        for group in GROUPS:
            for scenario in scenarios_body[group]["scenarios"]:
                key = scenario["scenario_key"]
                assert scenario["dimensions"] == EXPECTED_DIMENSIONS[key], key

    def test_selectable_scenarios_cover_the_grid_once(self, scenarios_body):
        """2 networks × 3 operating conditions, each exactly once among the
        selectable rows — what the frontend's switches map onto."""
        selectable = [
            *scenarios_body["current_base"]["scenarios"],
            *scenarios_body["current_scenarios"]["scenarios"],
        ]
        cells = Counter(
            (d["network"], d["hsr_allowed"], d["optimised_timetable"])
            for d in (s["dimensions"] for s in selectable)
        )
        assert set(cells.values()) == {1}
        assert len(cells) == 6
        # opt-tt never appears without HSR in the seed
        assert all(hsr or not opt for _, hsr, opt in cells)


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

    def test_hsr_scenario_is_in_current_scenarios_group(
        self, scenarios_body, hsr_scenario
    ):
        """The seeded HSR-allowed lineage head appears in
        current_scenarios, not current_base or historical_scenarios."""
        current_keys = {
            s["scenario_key"] for s in scenarios_body["current_scenarios"]["scenarios"]
        }
        assert hsr_scenario["scenario_key"] in current_keys

    def test_historical_scenario_is_in_historical_scenarios_group(
        self, scenarios_body, historical_scenario
    ):
        """The superseded infra-2026 revision (is_current_scenario=
        FALSE) appears in historical_scenarios, not current_base or
        current_scenarios."""
        historical_keys = {
            s["scenario_key"]
            for s in scenarios_body["historical_scenarios"]["scenarios"]
        }
        assert historical_scenario["scenario_key"] in historical_keys


class TestMeasureSets:
    """The measure-set axis: one seeded row until WP17 prices the levers."""

    def test_measure_sets_present_and_shaped(self, scenarios_body):
        assert "measure_sets" in scenarios_body
        for measure_set in scenarios_body["measure_sets"]:
            assert MEASURE_SET_FIELDS - set(measure_set) == set()
            assert set(measure_set["factors"]) == MEASURE_SET_FACTORS

    def test_only_the_empty_set_is_seeded(self, scenarios_body):
        """db/dev/seed.py MEASURE_SETS and the migration seed exactly
        'none'. A second row here means WP17 landed and the identity
        assertions below need revisiting, not silent passing."""
        assert [m["key"] for m in scenarios_body["measure_sets"]] == ["none"]

    def test_no_lever_is_pulled_and_every_factor_is_identity(self, scenarios_body):
        """'none' is the regime every evaluation before WP18 ran under —
        so its three flags are false and its three factors are 1.0. This
        is what makes CALC 0.9.26 a signature change and not a value
        change (models/params.py MeasureSet)."""
        none = scenarios_body["measure_sets"][0]
        assert not none["vat_exempt"]
        assert not none["energy_tax_exempt"]
        assert not none["tac_direct_cost"]
        assert set(none["factors"].values()) == {1.0}


class TestScenarioVariants:
    """The flattened (scenario x measure set) axis the family is built
    over — materialised as the full cross product."""

    def test_variants_present_and_shaped(self, scenarios_body):
        assert "scenario_variants" in scenarios_body
        for variant in scenarios_body["scenario_variants"]:
            assert VARIANT_FIELDS - set(variant) == set()

    def test_variant_count_is_the_full_cross_product(self, scenarios_body):
        expected = scenarios_body["total_count"] * len(scenarios_body["measure_sets"])
        assert len(scenarios_body["scenario_variants"]) == expected

    def test_every_pair_appears_exactly_once(self, scenarios_body):
        pairs = [
            (v["scenario_id"], v["measure_set_id"])
            for v in scenarios_body["scenario_variants"]
        ]
        assert len(set(pairs)) == len(pairs)

    def test_variant_ids_are_unique(self, scenarios_body):
        ids = [v["scenario_variant_id"] for v in scenarios_body["scenario_variants"]]
        assert len(set(ids)) == len(ids)

    def test_variants_reference_known_scenarios_and_measure_sets(self, scenarios_body):
        scenario_ids = {
            s["scenario_id"]
            for group in GROUPS
            for s in scenarios_body[group]["scenarios"]
        }
        measure_set_ids = {m["measure_set_id"] for m in scenarios_body["measure_sets"]}
        for variant in scenarios_body["scenario_variants"]:
            assert variant["scenario_id"] in scenario_ids
            assert variant["measure_set_id"] in measure_set_ids

    def test_variants_inline_their_scenario_display_fields(self, scenarios_body):
        """A variant carries scenario_key/name/graph/dimensions, so the
        frontend renders its switch from this list alone rather than
        joining it against the three groups."""
        for variant in scenarios_body["scenario_variants"]:
            assert {
                "scenario_key",
                "scenario_name",
                "is_current_base",
                "routing_graph_key",
                "dimensions",
            } - set(variant) == set()

    def test_the_base_scenario_has_a_variant(self, scenarios_body, base_scenario):
        """Every family defaults to the base scenario's variant, so it
        must exist — the one variant nothing works without."""
        base_variants = [
            v
            for v in scenarios_body["scenario_variants"]
            if v["scenario_id"] == base_scenario["scenario_id"]
        ]
        assert len(base_variants) == len(scenarios_body["measure_sets"])
        assert any(v["is_current_base"] for v in base_variants)
