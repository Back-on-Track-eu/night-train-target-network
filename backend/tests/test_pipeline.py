"""
test_pipeline.py
================
End-to-end integration tests for the two-step pipeline.

Step 1: POST /api/route/planOrUpdate  → Route
Step 2: POST /api/evaluation/calc     → EvaluationResult

Tests are organised in two groups:
  - Route builder: structure, physics values, timetable consistency
  - Evaluation: structure, revenue correctness, normalised matrix
"""

import pytest
import requests


ROUTE_URL      = "/api/route/planOrUpdate"
EVALUATION_URL = "/api/evaluation/calc"

# ---------------------------------------------------------------------------
# Known-good request using seeded test data
# ---------------------------------------------------------------------------

VALID_STOPS = [
    {"stop_id": "DE_BERLIN_HBF",  "stop_type": "boarding"},
    {"stop_id": "DE_DRESDEN_HBF", "stop_type": "both"},
    {"stop_id": "AT_WIEN_HBF",    "stop_type": "alighting"},
]

ROUTE_REQUEST = {
    "proposal_id":      1,
    "proposal_version": 1,
    "stops":            VALID_STOPS,
    "composition_id":   "STD-7.1",
    "departure_time":   "21:00",
}

# OD-pair demand — dummy values for testing
ROUTE_DEMAND_TEMPLATE = {
    "od_pairs": [
        {
            "origin_stop_id":      "DE_BERLIN_HBF",
            "destination_stop_id": "AT_WIEN_HBF",
            "class_main":          "Couchette",
            "places_sold":         40,
            "avg_price":           89.0,
        },
        {
            "origin_stop_id":      "DE_DRESDEN_HBF",
            "destination_stop_id": "AT_WIEN_HBF",
            "class_main":          "Seat",
            "places_sold":         20,
            "avg_price":           49.0,
        },
    ]
}

OPERATING_DAYS = 360


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def route_response(api_base):
    """POST /api/route/planOrUpdate — shared across route tests."""
    resp = requests.post(
        f"{api_base}{ROUTE_URL}",
        json=ROUTE_REQUEST,
        timeout=60,
    )
    assert resp.status_code == 200, \
        f"planOrUpdate failed: {resp.status_code} — {resp.text[:500]}"
    return resp.json()


@pytest.fixture(scope="module")
def route(route_response):
    return route_response["route"]


@pytest.fixture(scope="module")
def eval_response(api_base, route):
    """POST /api/evaluation/calc — shared across eval tests."""
    trip_ids = [t["trip_id"] for t in route["trips"]]
    route_demand = {trip_id: ROUTE_DEMAND_TEMPLATE for trip_id in trip_ids}

    body = {
        "route":               route,
        "route_demand":        route_demand,
        "operating_days_year": OPERATING_DAYS,
    }
    resp = requests.post(
        f"{api_base}{EVALUATION_URL}",
        json=body,
        timeout=30,
    )
    assert resp.status_code == 200, \
        f"evaluation/calc failed: {resp.status_code} — {resp.text[:500]}"
    return resp.json()


@pytest.fixture(scope="module")
def eval_result(eval_response):
    return eval_response["result"]


# =============================================================================
# ROUTE BUILDER TESTS
# =============================================================================

class TestRouteBuilder:

    def test_returns_200(self, api_base):
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=ROUTE_REQUEST, timeout=60)
        assert resp.status_code == 200

    def test_response_has_version(self, route_response):
        assert "route_builder_version" in route_response
        assert isinstance(route_response["route_builder_version"], str)

    def test_response_has_action_taken(self, route_response):
        """Response includes action_taken field."""
        assert "action_taken" in route_response
        assert route_response["action_taken"] in {"plan", "adjust"}

    def test_new_route_action_is_plan(self, route_response):
        """New route without existing route body → action_taken = plan."""
        assert route_response["action_taken"] == "plan"

    def test_route_has_two_trips(self, route):
        assert len(route["trips"]) == 2

    def test_trips_have_both_directions(self, route):
        directions = {t["direction_id"] for t in route["trips"]}
        assert directions == {0, 1}

    def test_trips_have_required_fields(self, route):
        required = {
            "trip_id", "direction_id", "departure_time", "departure_time_min",
            "model_versions", "param_versions",
            "composition", "stop_times", "shape", "path", "stats",
        }
        for trip in route["trips"]:
            missing = required - set(trip.keys())
            assert missing == set(), \
                f"Trip dir={trip.get('direction_id')} missing fields: {missing}"

    def test_trip_departure_time_min_matches_request(self, route):
        outbound = next(t for t in route["trips"] if t["direction_id"] == 0)
        assert outbound["departure_time_min"] == 1260  # 21:00

    def test_stop_times_count(self, route):
        for trip in route["trips"]:
            assert len(trip["stop_times"]) == 3

    def test_stop_times_monotonically_increasing(self, route):
        for trip in route["trips"]:
            times = [
                st["arrival_time_min"]
                for st in trip["stop_times"]
                if st["arrival_time_min"] is not None
            ]
            assert times == sorted(times), \
                f"Trip dir={trip['direction_id']} arrival times not monotonically increasing"

    def test_outbound_stop_ids_match_request(self, route):
        outbound = next(t for t in route["trips"] if t["direction_id"] == 0)
        returned = [st["stop_id"] for st in outbound["stop_times"]]
        expected = [s["stop_id"] for s in VALID_STOPS]
        assert returned == expected

    def test_return_trip_stop_ids_reversed(self, route):
        outbound = next(t for t in route["trips"] if t["direction_id"] == 0)
        return_t  = next(t for t in route["trips"] if t["direction_id"] == 1)
        assert [st["stop_id"] for st in return_t["stop_times"]] == \
               list(reversed([st["stop_id"] for st in outbound["stop_times"]]))

    def test_stats_distance_positive(self, route):
        for trip in route["trips"]:
            assert trip["stats"]["total_distance_m"] > 0

    def test_stats_total_time_gte_driving_time(self, route):
        for trip in route["trips"]:
            assert trip["stats"]["total_time_min"] >= trip["stats"]["total_driving_time_min"]

    def test_stats_no_monetary_values(self, route):
        monetary = {"total_tac_eur", "total_energy_eur", "station_charges_eur"}
        for trip in route["trips"]:
            present = monetary & set(trip["stats"].keys())
            assert present == set(), \
                f"Trip dir={trip['direction_id']} stats has monetary fields: {present}"

    def test_path_segments_count(self, route):
        for trip in route["trips"]:
            n_stops    = len(trip["stop_times"])
            n_segments = len(trip["path"]["segments"])
            assert n_segments == n_stops - 1

    def test_country_legs_no_cost_fields(self, route):
        monetary = {"tac_eur", "tac_eur_per_km", "energy_eur"}
        for trip in route["trips"]:
            for seg in trip["path"]["segments"]:
                for cl in seg["country_legs"]:
                    present = monetary & set(cl.keys())
                    assert present == set(), f"CountryLeg has monetary fields: {present}"

    def test_adjust_route_no_reroute(self, api_base, route):
        """Changing only departure_time triggers adjust, not plan."""
        body = {
            "proposal_id":      1,
            "proposal_version": 2,
            "route":            route,
            "departure_time":   "22:00",
        }
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=30)
        assert resp.status_code == 200
        assert resp.json()["action_taken"] == "adjust"

    def test_change_stops_triggers_plan(self, api_base, route):
        """Providing different stops triggers plan even with existing route."""
        different_stops = [
            {"stop_id": "DE_BERLIN_HBF",   "stop_type": "boarding"},
            {"stop_id": "AT_SALZBURG_HBF", "stop_type": "both"},
            {"stop_id": "AT_WIEN_HBF",     "stop_type": "alighting"},
        ]
        body = {
            "proposal_id":      1,
            "proposal_version": 2,
            "route":            route,
            "stops":            different_stops,
            "composition_id":   "STD-7.1",
            "departure_time":   "21:00",
        }
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=60)
        assert resp.status_code == 200
        assert resp.json()["action_taken"] == "plan"

    # --- validation ---

    def test_missing_stops_and_route_returns_400(self, api_base):
        body = {"proposal_id": 1, "proposal_version": 1, "composition_id": "STD-7.1"}
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=10)
        assert resp.status_code == 400

    def test_invalid_stop_type_returns_400(self, api_base):
        body = {**ROUTE_REQUEST, "stops": [
            {"stop_id": "DE_BERLIN_HBF", "stop_type": "INVALID"},
            {"stop_id": "AT_WIEN_HBF",   "stop_type": "alighting"},
        ]}
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=10)
        assert resp.status_code == 400

    def test_invalid_departure_time_returns_400(self, api_base):
        body = {**ROUTE_REQUEST, "departure_time": "21.00"}
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=10)
        assert resp.status_code == 400

    def test_unknown_composition_returns_422(self, api_base):
        body = {**ROUTE_REQUEST, "composition_id": "DOES-NOT-EXIST"}
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=30)
        assert resp.status_code == 422


# =============================================================================
# EVALUATION TESTS
# =============================================================================

class TestEvaluation:

    def test_returns_200(self, api_base, route):
        trip_ids = [t["trip_id"] for t in route["trips"]]
        body = {
            "route":               route,
            "route_demand":        {tid: ROUTE_DEMAND_TEMPLATE for tid in trip_ids},
            "operating_days_year": OPERATING_DAYS,
        }
        resp = requests.post(f"{api_base}{EVALUATION_URL}", json=body, timeout=30)
        assert resp.status_code == 200

    def test_response_has_metadata(self, eval_response):
        """Response includes calc_version, calc_formulas, model_versions, param_versions."""
        result = eval_response["result"]
        assert "calc_version"    in result
        assert "calc_formulas"   in result
        assert "model_versions"  in result
        assert "param_versions"  in result
        assert len(result["calc_formulas"]) > 0
        assert len(result["param_versions"]) > 0

    def test_calc_formulas_have_latex(self, eval_response):
        """Each calc formula has latex and description."""
        for key, formula in eval_response["result"]["calc_formulas"].items():
            assert "latex"       in formula, f"Formula '{key}' missing latex"
            assert "description" in formula, f"Formula '{key}' missing description"

    def test_param_versions_have_is_default(self, eval_response):
        """Each param version entry has is_default field."""
        for key, entry in eval_response["result"]["param_versions"].items():
            assert "is_default" in entry, f"param_versions['{key}'] missing is_default"
            assert isinstance(entry["is_default"], bool)

    def test_result_has_all_levels(self, eval_result):
        """Result has summary, by_trip, by_country, by_od."""
        assert "summary"    in eval_result
        assert "by_trip"    in eval_result
        assert "by_country" in eval_result
        assert "by_od"      in eval_result

    def test_summary_has_all_normalised_views(self, eval_result):
        """Summary contains all 10 normalised views."""
        expected_views = {
            "per_day", "per_year", "per_trip", "per_trip_km",
            "per_available_place_km", "per_sold_place_km",
            "per_available_place_of_class", "per_sold_place_of_class",
            "per_available_place_km_of_class", "per_sold_place_km_of_class",
        }
        missing = expected_views - set(eval_result["summary"].keys())
        assert missing == set(), f"Summary missing views: {missing}"

    def test_by_trip_has_two_entries(self, eval_result):
        assert len(eval_result["by_trip"]) == 2

    def test_by_trip_has_all_normalised_views(self, eval_result):
        """Each trip result has all 10 normalised views."""
        expected_views = {
            "per_day", "per_year", "per_trip", "per_trip_km",
            "per_available_place_km", "per_sold_place_km",
            "per_available_place_of_class", "per_sold_place_of_class",
            "per_available_place_km_of_class", "per_sold_place_km_of_class",
        }
        for i, trip_matrix in enumerate(eval_result["by_trip"]):
            missing = expected_views - set(trip_matrix.keys())
            assert missing == set(), f"by_trip[{i}] missing views: {missing}"

    def test_by_country_infrastructure_only(self, eval_result):
        """Country breakdowns are infrastructure-only (scope field)."""
        for cc, country_matrix in eval_result["by_country"].items():
            bd = country_matrix["per_day"]
            assert bd["scope"] == "infrastructure_only", \
                f"Country '{cc}' breakdown scope is not 'infrastructure_only'"

    def test_by_od_has_entries(self, eval_result):
        """OD pair results are present."""
        assert len(eval_result["by_od"]) > 0

    def test_by_od_has_all_normalised_views(self, eval_result):
        """Each OD pair result has all 10 normalised views."""
        expected_views = {
            "per_day", "per_year", "per_trip", "per_trip_km",
            "per_available_place_km", "per_sold_place_km",
            "per_available_place_of_class", "per_sold_place_of_class",
            "per_available_place_km_of_class", "per_sold_place_km_of_class",
        }
        for od in eval_result["by_od"]:
            missing = expected_views - set(od.keys())
            assert missing == set(), \
                f"OD pair {od.get('origin_stop_id')}→{od.get('destination_stop_id')} missing views: {missing}"

    def test_per_year_larger_than_per_day(self, eval_result):
        """per_year revenue > per_day revenue (multiplied by operating days)."""
        summary = eval_result["summary"]
        assert summary["per_year"]["revenue"]["total"] > \
               summary["per_day"]["revenue"]["total"]

    def test_revenue_positive(self, eval_result):
        """Total revenue per day is positive."""
        assert eval_result["summary"]["per_day"]["revenue"]["total"] > 0

    def test_cost_positive(self, eval_result):
        """Total cost per day is positive."""
        assert eval_result["summary"]["per_day"]["cost"]["total"] > 0

    def test_country_breakdown_has_tac_and_energy(self, eval_result):
        """Country breakdowns include track_access and energy."""
        for cc, matrix in eval_result["by_country"].items():
            bd = matrix["per_day"]
            assert bd["cost"]["infrastructure"]["track_access"] >= 0
            assert bd["cost"]["infrastructure"]["energy"] >= 0

    def test_calc_steps_reference_known_formulas(self, eval_response):
        """All formula_key values in calc_steps exist in calc_formulas."""
        result   = eval_response["result"]
        formulas = set(result["calc_formulas"].keys())
        bd       = result["summary"]["per_day"]
        for step in bd.get("calc_steps", []):
            assert step["formula_key"] in formulas, \
                f"Unknown formula_key '{step['formula_key']}' in calc_steps"

    def test_operating_days_year_matches_request(self, eval_result):
        assert eval_result["operating_days_year"] == OPERATING_DAYS

    # --- validation ---

    def test_missing_route_returns_400(self, api_base):
        body = {"route_demand": {}, "operating_days_year": 360}
        resp = requests.post(f"{api_base}{EVALUATION_URL}", json=body, timeout=10)
        assert resp.status_code == 400

    def test_invalid_class_main_returns_400(self, api_base, route):
        trip_ids = [t["trip_id"] for t in route["trips"]]
        bad_demand = {
            trip_ids[0]: {"od_pairs": [{
                "origin_stop_id":      "DE_BERLIN_HBF",
                "destination_stop_id": "AT_WIEN_HBF",
                "class_main":          "INVALID_CLASS",
                "places_sold":         10,
                "avg_price":           49.0,
            }]}
        }
        body = {"route": route, "route_demand": bad_demand, "operating_days_year": 360}
        resp = requests.post(f"{api_base}{EVALUATION_URL}", json=body, timeout=10)
        assert resp.status_code == 400

    def test_invalid_operating_days_returns_400(self, api_base, route):
        body = {"route": route, "route_demand": {}, "operating_days_year": 0}
        resp = requests.post(f"{api_base}{EVALUATION_URL}", json=body, timeout=10)
        assert resp.status_code == 400