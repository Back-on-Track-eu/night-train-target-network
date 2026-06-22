"""
test_pipeline.py
================
End-to-end integration tests for the Phase 3 two-step pipeline.

Step 1: POST /api/route-builder/build  → Route
Step 2: POST /api/cost-rev-calc/calc   → EvaluationResult

Tests are organised in two groups:
  - Route builder: structure, physics values, timetable consistency
  - Cost/rev calc: structure, revenue correctness, per-trip results

The route fixture is shared across all calc tests to avoid building
the route twice.
"""

import pytest
import requests


ROUTE_BUILDER_URL  = "/api/route-builder/build"
COST_REV_CALC_URL  = "/api/cost-rev-calc/calc"

# ---------------------------------------------------------------------------
# Known-good request using seeded test data
# ---------------------------------------------------------------------------

VALID_STOPS = [
    {"stop_id": "DE_BERLIN_HBF",  "stop_type": "boarding"},
    {"stop_id": "DE_DRESDEN_HBF", "stop_type": "both"},
    {"stop_id": "AT_WIEN_HBF",    "stop_type": "alighting"},
]

BUILD_REQUEST = {
    "stops":          VALID_STOPS,
    "composition_id": "STD-5.1",
    "departure_time": "21:00",
}

CALC_PARAMS = {
    "utilization_seat":       0.7,
    "utilization_couchette":  0.6,
    "utilization_sleeper":    0.5,
    "avg_fare_seat":          49.0,
    "avg_fare_couchette":     79.0,
    "avg_fare_sleeper":       129.0,
    "operating_days_year":    360,
}

# STD-5.1 capacity from seed data
COMP_SEATS      = 80
COMP_COUCHETTES = 144
COMP_SLEEPERS   = 24


# ---------------------------------------------------------------------------
# Fixtures — build route once, share across all tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def build_response(api_base):
    """POST /api/route-builder/build — shared across all route builder tests."""
    resp = requests.post(
        f"{api_base}{ROUTE_BUILDER_URL}",
        json=BUILD_REQUEST,
        timeout=60,
    )
    assert resp.status_code == 200, \
        f"build-route failed: {resp.status_code} — {resp.text[:500]}"
    return resp.json()


@pytest.fixture(scope="module")
def route(build_response):
    """Extracted route object."""
    return build_response["route"]


@pytest.fixture(scope="module")
def calc_response(api_base, route):
    """POST /api/cost-rev-calc/calc — shared across all calc tests."""
    body = {"route": route, **CALC_PARAMS}
    resp = requests.post(
        f"{api_base}{COST_REV_CALC_URL}",
        json=body,
        timeout=30,
    )
    assert resp.status_code == 200, \
        f"cost-rev-calc failed: {resp.status_code} — {resp.text[:500]}"
    return resp.json()


@pytest.fixture(scope="module")
def eval_result(calc_response):
    """Extracted evaluation result."""
    return calc_response["result"]


# =============================================================================
# ROUTE BUILDER TESTS
# =============================================================================

class TestRouteBuilder:

    # --- top level structure ---

    def test_returns_200(self, api_base):
        """POST /api/route-builder/build returns 200."""
        resp = requests.post(
            f"{api_base}{ROUTE_BUILDER_URL}",
            json=BUILD_REQUEST,
            timeout=60,
        )
        assert resp.status_code == 200

    def test_response_has_version(self, build_response):
        """Response includes route_builder_version."""
        assert "route_builder_version" in build_response
        assert isinstance(build_response["route_builder_version"], str)

    def test_response_has_route(self, build_response):
        """Response includes a route object."""
        assert "route" in build_response
        assert isinstance(build_response["route"], dict)

    def test_route_required_fields(self, route):
        """Route has all required top-level fields."""
        required = {"route_id", "operator_id", "parking_locations", "trips"}
        missing  = required - set(route.keys())
        assert missing == set(), f"Route missing fields: {missing}"

    # --- trips ---

    def test_route_has_two_trips(self, route):
        """Route contains exactly two trips (outbound + return)."""
        assert len(route["trips"]) == 2

    def test_trips_have_both_directions(self, route):
        """One outbound (0) and one return (1) trip."""
        directions = {t["direction_id"] for t in route["trips"]}
        assert directions == {0, 1}

    def test_trips_have_required_fields(self, route):
        """Each trip has all required fields."""
        required = {
            "trip_id", "direction_id", "departure_time", "departure_time_min",
            "params_snapshot", "composition", "stop_times", "shape", "path", "stats",
        }
        for trip in route["trips"]:
            missing = required - set(trip.keys())
            assert missing == set(), \
                f"Trip dir={trip.get('direction_id')} missing fields: {missing}"

    def test_trip_departure_time_fmt(self, route):
        """departure_time is formatted as HH:MM."""
        for trip in route["trips"]:
            fmt = trip["departure_time"]
            assert isinstance(fmt, str) and ":" in fmt, \
                f"Trip dir={trip['direction_id']} departure_time '{fmt}' not HH:MM"

    def test_trip_departure_time_min_matches_request(self, route):
        """Outbound departure_time_min matches request (21:00 = 1260 min)."""
        outbound = next(t for t in route["trips"] if t["direction_id"] == 0)
        assert outbound["departure_time_min"] == 1260

    # --- params snapshot ---

    def test_params_snapshot_fields(self, route):
        """params_snapshot has all required fields."""
        required = {
            "composition_id", "composition_version",
            "infra_generation", "stops_generation",
            "route_builder_version", "energy_calc_version",
        }
        for trip in route["trips"]:
            snap = trip["params_snapshot"]
            missing = required - set(snap.keys())
            assert missing == set(), \
                f"Trip dir={trip['direction_id']} snapshot missing: {missing}"

    def test_params_snapshot_composition_id(self, route):
        """params_snapshot.composition_id matches request."""
        for trip in route["trips"]:
            assert trip["params_snapshot"]["composition_id"] == BUILD_REQUEST["composition_id"]

    # --- stop_times ---

    def test_stop_times_count(self, route):
        """Each trip has 3 stop_times (matching the 3 input stops)."""
        for trip in route["trips"]:
            assert len(trip["stop_times"]) == 3, \
                f"Trip dir={trip['direction_id']} has {len(trip['stop_times'])} stop_times, expected 3"

    def test_stop_times_required_fields(self, route):
        """Each stop_time has all required fields."""
        required = {
            "stop_id", "stop_name", "lat", "lon", "stop_type",
            "arrival_time_min", "departure_time_min", "dwell_time_min",
            "arrival_time_fmt", "departure_time_fmt",
        }
        for trip in route["trips"]:
            for st in trip["stop_times"]:
                missing = required - set(st.keys())
                assert missing == set(), \
                    f"stop_time '{st.get('stop_id')}' missing fields: {missing}"

    def test_stop_times_origin_no_arrival(self, route):
        """Origin stop has no arrival_time_min."""
        outbound = next(t for t in route["trips"] if t["direction_id"] == 0)
        assert outbound["stop_times"][0]["arrival_time_min"] is None

    def test_stop_times_destination_no_departure(self, route):
        """Destination stop has no departure_time_min."""
        outbound = next(t for t in route["trips"] if t["direction_id"] == 0)
        assert outbound["stop_times"][-1]["departure_time_min"] is None

    def test_stop_times_monotonically_increasing(self, route):
        """Arrival times are monotonically increasing."""
        for trip in route["trips"]:
            times = [
                st["arrival_time_min"]
                for st in trip["stop_times"]
                if st["arrival_time_min"] is not None
            ]
            assert times == sorted(times), \
                f"Trip dir={trip['direction_id']} arrival times not monotonically increasing"

    def test_outbound_stop_ids_match_request(self, route):
        """Outbound trip stop IDs match the requested order."""
        outbound = next(t for t in route["trips"] if t["direction_id"] == 0)
        returned_ids = [st["stop_id"] for st in outbound["stop_times"]]
        expected_ids = [s["stop_id"] for s in VALID_STOPS]
        assert returned_ids == expected_ids

    def test_return_trip_stop_ids_reversed(self, route):
        """Return trip stop IDs are the reverse of outbound."""
        outbound = next(t for t in route["trips"] if t["direction_id"] == 0)
        return_t  = next(t for t in route["trips"] if t["direction_id"] == 1)
        out_ids   = [st["stop_id"] for st in outbound["stop_times"]]
        ret_ids   = [st["stop_id"] for st in return_t["stop_times"]]
        assert ret_ids == list(reversed(out_ids))

    # --- stats ---

    def test_stats_required_fields(self, route):
        """Each trip stats has required fields."""
        required = {
            "total_distance_m", "total_driving_time_min", "total_time_min",
            "total_energy_kwh", "total_distance_km",
            "total_driving_time_h", "total_time_h",
        }
        for trip in route["trips"]:
            missing = required - set(trip["stats"].keys())
            assert missing == set(), \
                f"Trip dir={trip['direction_id']} stats missing: {missing}"

    def test_stats_no_monetary_values(self, route):
        """Stats contain NO monetary values — physics only."""
        monetary_keys = {"total_tac_eur", "total_energy_eur", "station_charges_eur"}
        for trip in route["trips"]:
            present = monetary_keys & set(trip["stats"].keys())
            assert present == set(), \
                f"Trip dir={trip['direction_id']} stats has monetary fields: {present}"

    def test_stats_distance_positive(self, route):
        """Total distance is positive for both trips."""
        for trip in route["trips"]:
            assert trip["stats"]["total_distance_m"] > 0, \
                f"Trip dir={trip['direction_id']} has zero distance"

    def test_stats_total_time_gte_driving_time(self, route):
        """Total time >= driving time (buffer adds to driving)."""
        for trip in route["trips"]:
            assert trip["stats"]["total_time_min"] >= trip["stats"]["total_driving_time_min"], \
                f"Trip dir={trip['direction_id']} total_time < driving_time"

    def test_stats_energy_kwh_positive(self, route):
        """Energy consumption is positive."""
        for trip in route["trips"]:
            assert trip["stats"]["total_energy_kwh"] > 0, \
                f"Trip dir={trip['direction_id']} has zero energy"

    # --- path ---

    def test_path_has_shape(self, route):
        """Each trip has a shape (GeoJSON LineString)."""
        for trip in route["trips"]:
            assert "shape" in trip
            assert trip["shape"]["type"] == "LineString"
            assert len(trip["shape"]["coordinates"]) > 1

    def test_path_segments_count(self, route):
        """Each trip has n_stops - 1 segments."""
        for trip in route["trips"]:
            n_stops    = len(trip["stop_times"])
            n_segments = len(trip["path"]["segments"])
            assert n_segments == n_stops - 1, \
                f"Trip dir={trip['direction_id']}: {n_segments} segments for {n_stops} stops"

    def test_path_has_country_segments(self, route):
        """Each trip has at least one country segment."""
        for trip in route["trips"]:
            assert len(trip["path"]["countries"]) >= 1

    def test_country_leg_no_cost_fields(self, route):
        """Country legs carry no monetary values."""
        monetary = {"tac_eur", "tac_eur_per_km", "energy_eur"}
        for trip in route["trips"]:
            for seg in trip["path"]["segments"]:
                for cl in seg["country_legs"]:
                    present = monetary & set(cl.keys())
                    assert present == set(), \
                        f"CountryLeg has monetary fields: {present}"

    # --- parking locations ---

    def test_parking_locations_present(self, route):
        """Route has parking_locations list."""
        assert isinstance(route["parking_locations"], list)
        assert len(route["parking_locations"]) >= 1

    def test_parking_locations_fields(self, route):
        """Each parking location has stop_id, stop_name, country_code."""
        for loc in route["parking_locations"]:
            assert "stop_id" in loc
            assert "stop_name" in loc
            assert "country_code" in loc

    # --- composition ---

    def test_composition_matches_request(self, route):
        """Composition in trip matches the requested composition_id."""
        for trip in route["trips"]:
            assert trip["composition"]["comp_id"] == BUILD_REQUEST["composition_id"]

    # --- validation errors ---

    def test_missing_stops_returns_400(self, api_base):
        """Missing stops field returns 400."""
        body = {k: v for k, v in BUILD_REQUEST.items() if k != "stops"}
        resp = requests.post(f"{api_base}{ROUTE_BUILDER_URL}", json=body, timeout=10)
        assert resp.status_code == 400
        assert resp.json()["error"] == "validation_error"

    def test_single_stop_returns_400(self, api_base):
        """Only one stop returns 400."""
        body = {**BUILD_REQUEST, "stops": [VALID_STOPS[0]]}
        resp = requests.post(f"{api_base}{ROUTE_BUILDER_URL}", json=body, timeout=10)
        assert resp.status_code == 400

    def test_invalid_stop_type_returns_400(self, api_base):
        """Invalid stop_type returns 400."""
        body = {**BUILD_REQUEST, "stops": [
            {"stop_id": "DE_BERLIN_HBF", "stop_type": "INVALID"},
            {"stop_id": "AT_WIEN_HBF",   "stop_type": "alighting"},
        ]}
        resp = requests.post(f"{api_base}{ROUTE_BUILDER_URL}", json=body, timeout=10)
        assert resp.status_code == 400

    def test_invalid_departure_time_format_returns_400(self, api_base):
        """Invalid departure_time format returns 400."""
        body = {**BUILD_REQUEST, "departure_time": "21.00"}
        resp = requests.post(f"{api_base}{ROUTE_BUILDER_URL}", json=body, timeout=10)
        assert resp.status_code == 400

    def test_unknown_composition_returns_422(self, api_base):
        """Unknown composition_id returns 422 domain error."""
        body = {**BUILD_REQUEST, "composition_id": "DOES-NOT-EXIST"}
        resp = requests.post(f"{api_base}{ROUTE_BUILDER_URL}", json=body, timeout=30)
        assert resp.status_code == 422
        assert resp.json()["error"] == "domain_error"

    def test_no_body_returns_400(self, api_base):
        """Empty body returns 400."""
        resp = requests.post(
            f"{api_base}{ROUTE_BUILDER_URL}",
            data="",
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        assert resp.status_code == 400


# =============================================================================
# COST/REV CALC TESTS
# =============================================================================

class TestCostRevCalc:

    # --- top level structure ---

    def test_returns_200(self, api_base, route):
        """POST /api/cost-rev-calc/calc returns 200."""
        body = {"route": route, **CALC_PARAMS}
        resp = requests.post(f"{api_base}{COST_REV_CALC_URL}", json=body, timeout=30)
        assert resp.status_code == 200

    def test_response_has_version(self, calc_response):
        """Response includes calc_version."""
        assert "calc_version" in calc_response
        assert isinstance(calc_response["calc_version"], str)

    def test_response_has_result(self, calc_response):
        """Response includes a result object."""
        assert "result" in calc_response
        assert isinstance(calc_response["result"], dict)

    def test_result_required_fields(self, eval_result):
        """EvaluationResult has all required top-level fields."""
        required = {
            "calc_version", "operating_days_year", "parking_eur",
            "summary", "trip_results",
        }
        missing = required - set(eval_result.keys())
        assert missing == set(), f"EvaluationResult missing fields: {missing}"

    def test_summary_required_fields(self, eval_result):
        """Summary has all required fields."""
        required = {
            "total_revenue", "total_cost", "total_margin",
            "total_margin_pct", "annual_margin",
        }
        missing = required - set(eval_result["summary"].keys())
        assert missing == set(), f"Summary missing fields: {missing}"

    # --- trip results ---

    def test_has_two_trip_results(self, eval_result):
        """EvaluationResult contains two TripResults."""
        assert len(eval_result["trip_results"]) == 2

    def test_trip_results_both_directions(self, eval_result):
        """One TripResult per direction."""
        directions = {tr["direction_id"] for tr in eval_result["trip_results"]}
        assert directions == {0, 1}

    def test_trip_result_required_fields(self, eval_result):
        """Each TripResult has all required fields."""
        required = {
            "trip_id", "direction_id", "capacity",
            "revenue", "cost", "allocation",
            "margin", "margin_pct", "cost_per_seat_km",
        }
        for tr in eval_result["trip_results"]:
            missing = required - set(tr.keys())
            assert missing == set(), \
                f"TripResult dir={tr.get('direction_id')} missing: {missing}"

    # --- revenue ---

    def test_revenue_calculation_correct(self, eval_result):
        """Revenue totals match expected calculation from inputs × seed capacity."""
        for tr in eval_result["trip_results"]:
            rev = tr["revenue"]
            expected_seat      = COMP_SEATS      * CALC_PARAMS["utilization_seat"]      * CALC_PARAMS["avg_fare_seat"]
            expected_couchette = COMP_COUCHETTES * CALC_PARAMS["utilization_couchette"] * CALC_PARAMS["avg_fare_couchette"]
            expected_sleeper   = COMP_SLEEPERS   * CALC_PARAMS["utilization_sleeper"]   * CALC_PARAMS["avg_fare_sleeper"]

            assert rev["revenue_seat"]      == pytest.approx(expected_seat,      rel=1e-4)
            assert rev["revenue_couchette"] == pytest.approx(expected_couchette, rel=1e-4)
            assert rev["revenue_sleeper"]   == pytest.approx(expected_sleeper,   rel=1e-4)
            assert rev["total"]             == pytest.approx(
                expected_seat + expected_couchette + expected_sleeper, rel=1e-4
            )

    def test_capacity_matches_composition(self, eval_result):
        """Capacity in TripResult matches STD-5.1 seed data."""
        for tr in eval_result["trip_results"]:
            cap = tr["capacity"]
            assert cap["seats"]      == COMP_SEATS
            assert cap["couchettes"] == COMP_COUCHETTES
            assert cap["sleepers"]   == COMP_SLEEPERS

    # --- cost ---

    def test_cost_total_positive(self, eval_result):
        """Total cost is positive for both trips."""
        for tr in eval_result["trip_results"]:
            assert tr["cost"]["total"] > 0, \
                f"TripResult dir={tr['direction_id']} has zero cost"

    def test_cost_infra_total_positive(self, eval_result):
        """Infrastructure cost total (TAC + energy + station charges) is positive."""
        for tr in eval_result["trip_results"]:
            assert tr["cost"]["infra_total"] > 0, \
                f"TripResult dir={tr['direction_id']} has zero infra cost"

    def test_cost_track_access_positive(self, eval_result):
        """Track access charges are positive."""
        for tr in eval_result["trip_results"]:
            assert tr["cost"]["track_access"] > 0, \
                f"TripResult dir={tr['direction_id']} has zero TAC"

    def test_cost_energy_positive(self, eval_result):
        """Energy costs are positive."""
        for tr in eval_result["trip_results"]:
            assert tr["cost"]["energy"] > 0, \
                f"TripResult dir={tr['direction_id']} has zero energy cost"

    def test_parking_eur_at_result_level(self, eval_result):
        """parking_eur is at EvaluationResult level, not in trip cost."""
        assert eval_result["parking_eur"] >= 0

    # --- summary aggregates ---

    def test_summary_totals_consistent(self, eval_result):
        """Summary totals match sum of trip results."""
        total_rev  = sum(tr["revenue"]["total"] for tr in eval_result["trip_results"])
        total_cost = sum(tr["cost"]["total"]    for tr in eval_result["trip_results"])
        assert eval_result["summary"]["total_revenue"] == pytest.approx(total_rev,  rel=1e-4)
        assert eval_result["summary"]["total_cost"]    == pytest.approx(total_cost, rel=1e-4)

    def test_annual_margin_consistent(self, eval_result):
        """Annual margin equals total_margin × operating_days_year."""
        expected = (
            eval_result["summary"]["total_margin"]
            * eval_result["operating_days_year"]
        )
        assert eval_result["summary"]["annual_margin"] == pytest.approx(expected, rel=1e-4)

    def test_operating_days_matches_request(self, eval_result):
        """operating_days_year in result matches request."""
        assert eval_result["operating_days_year"] == CALC_PARAMS["operating_days_year"]

    # --- validation errors ---

    def test_missing_route_returns_400(self, api_base):
        """Missing route field returns 400."""
        body = {**CALC_PARAMS}
        resp = requests.post(f"{api_base}{COST_REV_CALC_URL}", json=body, timeout=10)
        assert resp.status_code == 400
        assert resp.json()["error"] == "validation_error"

    def test_utilization_out_of_range_returns_400(self, api_base, route):
        """Utilization > 1.0 returns 400."""
        body = {"route": route, **CALC_PARAMS, "utilization_seat": 1.5}
        resp = requests.post(f"{api_base}{COST_REV_CALC_URL}", json=body, timeout=10)
        assert resp.status_code == 400

    def test_negative_fare_returns_400(self, api_base, route):
        """Negative avg_fare returns 400."""
        body = {"route": route, **CALC_PARAMS, "avg_fare_seat": -10.0}
        resp = requests.post(f"{api_base}{COST_REV_CALC_URL}", json=body, timeout=10)
        assert resp.status_code == 400

    def test_invalid_operating_days_returns_400(self, api_base, route):
        """operating_days_year of 0 returns 400."""
        body = {"route": route, **CALC_PARAMS, "operating_days_year": 0}
        resp = requests.post(f"{api_base}{COST_REV_CALC_URL}", json=body, timeout=10)
        assert resp.status_code == 400

    def test_no_body_returns_400(self, api_base):
        """Empty body returns 400."""
        resp = requests.post(
            f"{api_base}{COST_REV_CALC_URL}",
            data="",
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        assert resp.status_code == 400