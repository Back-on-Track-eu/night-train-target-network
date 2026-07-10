"""
test_30_evaluation_api.py
=========================
Contract tests for POST /api/evaluation/calc — response structure, the
"models" and "input" documentation sections, view metadata, and request
validation.

Response shape (CALC_VERSION >= 1.2.0):
  calc_version, route_id,
  models.{route_builder|energy|evaluation}.{version, description, formulas},
  input.{route, parameters.{track_infrastructures, stop_infrastructures, compositions}},
  views.{route|per_trip_pair|per_trip_pair_per_country|per_trip_pair_per_od|
         per_trip_per_stop}.{description, normalisations, data}
"""

import re

import pytest
import requests

from tests.helpers import EVAL_URL, inject_demand, route_bd

NORMALISATIONS = (
    "per_year",
    "per_operating_day",
    "per_trip_km",
    "per_available_place_km",
    "per_sold_place_km",
)

# Every leaf field breakdown_to_dict() emits — the evaluation model must
# document a formula for each (models.evaluation.formulas is filtered to
# exactly the fields present under "views").
BREAKDOWN_LEAF_FIELDS = {
    "driver_eur",
    "crew_eur",
    "coach_maintenance_eur",
    "loco_eur",
    "svc_stockings_eur",
    "var_overhead_eur",
    "coach_amortisation_eur",
    "financing_eur",
    "fix_overhead_eur",
    "cleaning_eur",
    "shunting_eur",
    "tac_eur",
    "energy_eur",
    "station_charge_eur",
    "parking_eur",
    "ticket_revenue_eur",
    "ebit_margin_eur",
}


# =============================================================================
# Response structure
# =============================================================================


class TestResponseStructure:

    def test_top_level_keys(self, eval_standard):
        """Response carries calc_version, route_id, models, input, views."""
        _, result = eval_standard
        assert set(result) >= {"calc_version", "route_id", "models", "input", "views"}

    def test_calc_version_is_semver(self, eval_standard):
        """calc_version is a semver string."""
        _, result = eval_standard
        assert re.fullmatch(r"\d+\.\d+\.\d+", result["calc_version"])

    def test_route_id_echoes_input(self, eval_standard):
        """route_id equals the posted route's own route_id."""
        costed, result = eval_standard
        assert result["route_id"] == costed["route_id"]

    def test_views_has_all_five(self, eval_standard):
        """All five view dimensions are present."""
        _, result = eval_standard
        assert set(result["views"]) == {
            "route",
            "per_trip_pair",
            "per_trip_pair_per_country",
            "per_trip_pair_per_od",
            "per_trip_per_stop",
        }

    def test_every_view_carries_description_and_normalisation_docs(self, eval_standard):
        """Each view carries its description and per-normalisation
        documentation alongside the data — no separate views_meta."""
        _, result = eval_standard
        for view_name, view in result["views"].items():
            assert view["description"], f"{view_name}: empty description"
            assert set(view["normalisations"]) == set(NORMALISATIONS)
            assert "data" in view

    def test_route_view_has_all_normalisations(self, eval_standard):
        _, result = eval_standard
        assert set(result["views"]["route"]["data"]) == set(NORMALISATIONS)

    def test_breakdown_tree_shape(self, eval_standard):
        """The route-level per_year breakdown carries the full cost/revenue/
        margin tree plus the summary totals."""
        _, result = eval_standard
        bd = route_bd(result)
        assert {
            "cost",
            "revenue",
            "margin",
            "total_cost_eur",
            "total_revenue_eur",
            "net_eur",
        } <= set(bd)
        assert {"operator", "infrastructure", "total_eur"} <= set(bd["cost"])
        assert {"variable", "fixed", "total_eur"} <= set(bd["cost"]["operator"])

    def test_matrix_views_have_all_keys_and_filters(self, eval_standard):
        """Every matrix view has the 'all' aggregation key, and every data
        point carries a human-readable 'filter' dict beside its 'values'."""
        _, result = eval_standard
        for view_name in (
            "per_trip_pair",
            "per_trip_pair_per_country",
            "per_trip_pair_per_od",
            "per_trip_per_stop",
        ):
            data = result["views"][view_name]["data"]
            assert "all" in data, f"{view_name}: no 'all' key"
            for key, cell in data.items():
                # per_trip_pair is one level deep; the others two levels.
                cells = [cell] if "values" in cell else list(cell.values())
                for c in cells:
                    assert (
                        "filter" in c and "values" in c
                    ), f"{view_name}[{key}]: missing filter/values"


# =============================================================================
# "models" documentation section
# =============================================================================


class TestModelsSection:

    def test_three_models_with_version_and_description(self, eval_standard):
        """route_builder, energy, and evaluation each carry a semver version
        and a non-empty description."""
        _, result = eval_standard
        assert set(result["models"]) == {"route_builder", "energy", "evaluation"}
        for name, model in result["models"].items():
            assert re.fullmatch(
                r"\d+\.\d+\.\d+", model["version"]
            ), f"{name}: bad version"
            assert model["description"], f"{name}: empty description"
            assert isinstance(model["formulas"], dict)

    def test_evaluation_formulas_cover_all_breakdown_leaves(self, eval_standard):
        """Every leaf field in the breakdown tree has a documented formula
        under models.evaluation.formulas — the frontend maps views fields
        straight to formulas by key."""
        _, result = eval_standard
        formulas = result["models"]["evaluation"]["formulas"]
        missing = BREAKDOWN_LEAF_FIELDS - set(formulas)
        assert missing == set(), f"Leaf fields without a formula: {missing}"

    def test_formulas_have_latex_and_description(self, eval_standard):
        """Every formula entry carries non-empty latex and description, and
        the latex actually looks like LaTeX (contains a backslash command
        or math operator)."""
        _, result = eval_standard
        for key, f in result["models"]["evaluation"]["formulas"].items():
            assert f["latex"], f"{key}: empty latex"
            assert f["description"], f"{key}: empty description"
            assert "\\" in f["latex"] or any(
                op in f["latex"] for op in "=+-×"
            ), f"{key}: latex does not look like a formula: {f['latex']!r}"


# =============================================================================
# "input" documentation section
# =============================================================================


class TestInputSection:

    def test_route_echoed_verbatim(self, eval_standard):
        """input.route is the route JSON exactly as posted — a faithful
        record of the request, not a re-serialization."""
        costed, result = eval_standard
        assert result["input"]["route"] == costed

    def test_parameters_carry_all_three_collections(self, eval_standard):
        """input.parameters documents every parameter collection used to cost
        the route, in the same shape as the /api/params/* endpoints."""
        _, result = eval_standard
        params = result["input"]["parameters"]
        assert set(params) == {
            "track_infrastructures",
            "stop_infrastructures",
            "compositions",
        }
        assert params["track_infrastructures"]["count"] > 0
        assert params["stop_infrastructures"]["count"] > 0
        assert params["compositions"]["count"] > 0


# =============================================================================
# Validation
# =============================================================================


class TestValidation:

    def test_missing_route_returns_400(self, api_base):
        resp = requests.post(f"{api_base}{EVAL_URL}", json={}, timeout=10)
        assert resp.status_code == 400

    def test_non_json_body_returns_400(self, api_base):
        resp = requests.post(
            f"{api_base}{EVAL_URL}",
            data="not json",
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        assert resp.status_code == 400

    def test_empty_trip_pairs_returns_400(self, api_base):
        resp = requests.post(
            f"{api_base}{EVAL_URL}",
            json={
                "route": {
                    "route_id": "test",
                    "schedule": {"seasonal_schedules": []},
                    "trip_pairs": [],
                }
            },
            timeout=10,
        )
        assert resp.status_code == 400

    def test_scenario_override_wrong_type_returns_400(
        self, api_base, route_berlin_wien
    ):
        resp = requests.post(
            f"{api_base}{EVAL_URL}",
            json={"route": route_berlin_wien, "scenario_id": "not-an-int"},
            timeout=10,
        )
        assert resp.status_code == 400

    def test_route_without_demand_evaluates(self, api_base, route_berlin_wien):
        """A fresh route with empty od_pairs is valid input — costs exist
        without revenue (asserted in detail in test_31)."""
        resp = requests.post(
            f"{api_base}{EVAL_URL}",
            json={"route": inject_demand(route_berlin_wien, [])},
            timeout=60,
        )
        assert resp.status_code == 200
