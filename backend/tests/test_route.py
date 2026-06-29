"""
test_route.py
=============
Tests for POST /api/route/planOrUpdate — structure, validation,
adjust vs plan auto-detection.
"""

import pytest
import requests

ROUTE_URL = "/api/route/planOrUpdate"

VALID_STOPS_3 = [
    {"stop_id": "DE_BERLIN_HBF", "stop_type": "boarding"},
    {"stop_id": "DE_DRESDEN_HBF", "stop_type": "both"},
    {"stop_id": "AT_WIEN_HBF", "stop_type": "alighting"},
]

VALID_STOPS_2 = [
    {"stop_id": "DE_BERLIN_HBF", "stop_type": "boarding"},
    {"stop_id": "AT_WIEN_HBF", "stop_type": "alighting"},
]

BASE_REQUEST = {
    "proposal_id": 1,
    "proposal_version": 1,
    "stops": VALID_STOPS_3,
    "composition_id": "STD-7.1",
    "departure_time": "21:00",
}


@pytest.fixture(scope="module")
def route(api_base):
    resp = requests.post(f"{api_base}{ROUTE_URL}", json=BASE_REQUEST, timeout=60)
    assert resp.status_code == 200, f"Route build failed: {resp.text[:300]}"
    return resp.json()["route"]


# --- Basic structure ---


class TestRouteStructure:

    def test_returns_200(self, api_base):
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=BASE_REQUEST, timeout=60)
        assert resp.status_code == 200

    def test_action_taken_is_plan(self, api_base):
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=BASE_REQUEST, timeout=60)
        assert resp.json()["action_taken"] == "plan"

    def test_has_route_builder_version(self, api_base):
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=BASE_REQUEST, timeout=60)
        assert "route_builder_version" in resp.json()

    def test_route_has_two_trips(self, route):
        assert len(route["trips"]) == 2

    def test_trips_have_both_directions(self, route):
        directions = {t["direction_id"] for t in route["trips"]}
        assert directions == {0, 1}

    def test_trip_has_required_fields(self, route):
        required = {
            "trip_id",
            "direction_id",
            "departure_time",
            "departure_time_min",
            "model_versions",
            "param_versions",
            "composition",
            "stop_times",
            "shape",
            "path",
            "stats",
        }
        for trip in route["trips"]:
            missing = required - set(trip.keys())
            assert (
                missing == set()
            ), f"Trip dir={trip['direction_id']} missing: {missing}"

    def test_outbound_departure_matches_request(self, route):
        outbound = next(t for t in route["trips"] if t["direction_id"] == 0)
        assert outbound["departure_time_min"] == 21 * 60  # 21:00

    def test_outbound_stop_order_matches_request(self, route):
        outbound = next(t for t in route["trips"] if t["direction_id"] == 0)
        stop_ids = [st["stop_id"] for st in outbound["stop_times"]]
        assert stop_ids == [s["stop_id"] for s in VALID_STOPS_3]

    def test_return_trip_stops_reversed(self, route):
        outbound = next(t for t in route["trips"] if t["direction_id"] == 0)
        return_t = next(t for t in route["trips"] if t["direction_id"] == 1)
        assert [st["stop_id"] for st in return_t["stop_times"]] == list(
            reversed([st["stop_id"] for st in outbound["stop_times"]])
        )

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
            assert times == sorted(times)

    def test_stats_distance_positive(self, route):
        for trip in route["trips"]:
            assert trip["stats"]["total_distance_m"] > 0

    def test_stats_total_time_gte_driving_time(self, route):
        for trip in route["trips"]:
            assert (
                trip["stats"]["total_time_min"]
                >= trip["stats"]["total_driving_time_min"]
            )

    def test_no_monetary_values_in_stats(self, route):
        monetary = {"total_tac_eur", "total_energy_eur", "station_charges_eur"}
        for trip in route["trips"]:
            assert not (monetary & set(trip["stats"].keys()))

    def test_path_segment_count_equals_stops_minus_one(self, route):
        for trip in route["trips"]:
            assert len(trip["path"]["segments"]) == len(trip["stop_times"]) - 1

    def test_country_legs_have_no_monetary_fields(self, route):
        monetary = {"tac_eur", "energy_eur"}
        for trip in route["trips"]:
            for seg in trip["path"]["segments"]:
                for cl in seg["country_legs"]:
                    assert not (monetary & set(cl.keys()))

    def test_country_legs_have_energy_kwh(self, route):
        for trip in route["trips"]:
            for seg in trip["path"]["segments"]:
                for cl in seg["country_legs"]:
                    assert "energy_kwh" in cl
                    assert cl["energy_kwh"] >= 0


# --- Adjust vs plan ---


class TestAdjustVsPlan:

    def test_departure_time_change_triggers_adjust(self, api_base, route):
        body = {
            "proposal_id": 1,
            "proposal_version": 2,
            "route": route,
            "departure_time": "22:00",
        }
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=30)
        assert resp.status_code == 200
        assert resp.json()["action_taken"] == "adjust"

    def test_adjust_preserves_distance(self, api_base, route):
        body = {
            "proposal_id": 1,
            "proposal_version": 2,
            "route": route,
            "departure_time": "22:00",
        }
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=30)
        assert resp.status_code == 200
        adjusted = resp.json()["route"]
        for orig, adj in zip(route["trips"], adjusted["trips"]):
            assert orig["stats"]["total_distance_m"] == adj["stats"]["total_distance_m"]

    def test_adjusted_departure_time_updated(self, api_base, route):
        body = {
            "proposal_id": 1,
            "proposal_version": 2,
            "route": route,
            "departure_time": "22:30",
        }
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=30)
        assert resp.status_code == 200
        adjusted = resp.json()["route"]
        outbound = next(t for t in adjusted["trips"] if t["direction_id"] == 0)
        assert outbound["departure_time_min"] == 22 * 60 + 30

    def test_stop_type_change_triggers_adjust(self, api_base, route):
        body = {
            "proposal_id": 1,
            "proposal_version": 2,
            "route": route,
            "stop_type_changes": {"DE_DRESDEN_HBF": "alighting"},
        }
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=30)
        assert resp.status_code == 200
        assert resp.json()["action_taken"] == "adjust"

    def test_new_stops_trigger_plan(self, api_base, route):
        body = {
            "proposal_id": 1,
            "proposal_version": 2,
            "route": route,
            "stops": [
                {"stop_id": "DE_BERLIN_HBF", "stop_type": "boarding"},
                {"stop_id": "CH_ZUERICH_HB", "stop_type": "both"},
                {"stop_id": "AT_WIEN_HBF", "stop_type": "alighting"},
            ],
            "composition_id": "STD-7.1",
            "departure_time": "21:00",
        }
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=60)
        assert resp.status_code == 200
        assert resp.json()["action_taken"] == "plan"

    def test_composition_change_triggers_plan(self, api_base, route):
        body = {
            "proposal_id": 1,
            "proposal_version": 2,
            "route": route,
            "composition_id": "STD-9.1",
            "departure_time": "21:00",
        }
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=60)
        assert resp.status_code == 200
        assert resp.json()["action_taken"] == "plan"

    def test_new_route_without_existing_triggers_plan(self, api_base):
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=BASE_REQUEST, timeout=60)
        assert resp.status_code == 200
        assert resp.json()["action_taken"] == "plan"


# --- Validation ---


class TestRouteValidation:

    def test_single_stop_returns_400(self, api_base):
        body = {
            **BASE_REQUEST,
            "stops": [{"stop_id": "DE_BERLIN_HBF", "stop_type": "boarding"}],
        }
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=10)
        assert resp.status_code == 400

    def test_missing_stops_and_route_returns_400(self, api_base):
        body = {
            "proposal_id": 1,
            "proposal_version": 1,
            "composition_id": "STD-7.1",
            "departure_time": "21:00",
        }
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=10)
        assert resp.status_code == 400

    def test_invalid_stop_type_returns_400(self, api_base):
        body = {
            **BASE_REQUEST,
            "stops": [
                {"stop_id": "DE_BERLIN_HBF", "stop_type": "WRONG"},
                {"stop_id": "AT_WIEN_HBF", "stop_type": "alighting"},
            ],
        }
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=10)
        assert resp.status_code == 400

    def test_invalid_departure_time_returns_400(self, api_base):
        body = {**BASE_REQUEST, "departure_time": "21.00"}
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=10)
        assert resp.status_code == 400

    def test_overnight_departure_time_accepted(self, api_base):
        """Night trains depart after midnight — 25:30 = 01:30 next day."""
        body = {**BASE_REQUEST, "departure_time": "25:30"}
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=60)
        assert resp.status_code == 200

    def test_overnight_departure_time_stored_correctly(self, api_base):
        """25:30 should be stored as 1530 minutes."""
        body = {**BASE_REQUEST, "departure_time": "25:30"}
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=60)
        assert resp.status_code == 200
        outbound = next(
            t for t in resp.json()["route"]["trips"] if t["direction_id"] == 0
        )
        assert outbound["departure_time_min"] == 25 * 60 + 30  # 1530

    def test_departure_time_48h_rejected(self, api_base):
        """Times >= 48:00 should be rejected."""
        body = {**BASE_REQUEST, "departure_time": "48:00"}
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=10)
        assert resp.status_code == 400

    def test_unknown_composition_returns_422(self, api_base):
        body = {**BASE_REQUEST, "composition_id": "DOES-NOT-EXIST"}
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=30)
        assert resp.status_code == 422

    def test_empty_body_returns_400(self, api_base):
        resp = requests.post(
            f"{api_base}{ROUTE_URL}",
            data="not-json",
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        assert resp.status_code == 400
