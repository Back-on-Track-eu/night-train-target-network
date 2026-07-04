"""
test_route.py
=============
Tests for POST /api/route/plan — structure, mode validation, and the
automatic (timetable_mode='simpleAutomatic') scheduling contract.

Adjust-mode tests are gone entirely: adjust_route() is no longer reachable
from this endpoint (route/plan is always a full, stateless build) — see
api/README.md. departure_time / per-stop stop_type / stop_type_changes are
gone from the request for the same reason: timing and boarding/alighting
are derived automatically now, not supplied by the caller.

Exact departure_time_min values aren't asserted anywhere here — they're a
function of live OpenRailRouting output (real driving/buffer time), which
this suite has no way to predict. What IS asserted is the *contract* the
automatic scheduling makes: first stop boarding, last stop alighting, a
real (non-null) time assigned, monotonically increasing stop times.
"""

import pytest
import requests

from tests.conftest import flatten_trips

ROUTE_URL = "/api/route/plan"

VALID_STOPS_3 = ["DE_BERLIN_HBF", "DE_DRESDEN_HBF", "AT_WIEN_HBF"]
VALID_STOPS_2 = ["DE_BERLIN_HBF", "AT_WIEN_HBF"]

BASE_REQUEST = {
    "stops": VALID_STOPS_3,
    "composition_id": "STD-7.1",
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

    def test_response_has_expected_top_level_keys(self, api_base):
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=BASE_REQUEST, timeout=60)
        assert set(resp.json().keys()) == {"route_builder_version", "request", "route"}

    def test_response_echoes_request(self, api_base):
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=BASE_REQUEST, timeout=60)
        assert resp.json()["request"] == BASE_REQUEST

    def test_has_route_builder_version(self, api_base):
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=BASE_REQUEST, timeout=60)
        assert "route_builder_version" in resp.json()

    def test_route_has_two_trips(self, route):
        assert len(flatten_trips(route)) == 2

    def test_trips_have_both_directions(self, route):
        directions = {t["direction_id"] for t in flatten_trips(route)}
        assert directions == {0, 1}

    def test_trip_has_required_fields(self, route):
        # model_versions, param_versions, and a full composition object are
        # not serialized into route JSON anywhere (RouteProvenance travels
        # separately from Route) — not asserted here for that reason.
        required = {
            "trip_id",
            "direction_id",
            "departure_time_min",
            "composition_id",
            "stop_times",
            "path",
            "stats",
        }
        for trip in flatten_trips(route):
            missing = required - set(trip.keys())
            assert (
                missing == set()
            ), f"Trip dir={trip['direction_id']} missing: {missing}"

    def test_outbound_stop_order_matches_request(self, route):
        outbound = next(t for t in flatten_trips(route) if t["direction_id"] == 0)
        stop_ids = [st["stop_id"] for st in outbound["stop_times"]]
        assert stop_ids == VALID_STOPS_3

    def test_return_trip_stops_reversed(self, route):
        outbound = next(t for t in flatten_trips(route) if t["direction_id"] == 0)
        return_t = next(t for t in flatten_trips(route) if t["direction_id"] == 1)
        assert [st["stop_id"] for st in return_t["stop_times"]] == list(
            reversed([st["stop_id"] for st in outbound["stop_times"]])
        )

    def test_stop_times_count(self, route):
        for trip in flatten_trips(route):
            assert len(trip["stop_times"]) == 3

    def test_stop_times_monotonically_increasing(self, route):
        for trip in flatten_trips(route):
            times = [
                st["arrival_time_min"]
                for st in trip["stop_times"]
                if st["arrival_time_min"] is not None
            ]
            assert times == sorted(times)

    def test_stats_distance_positive(self, route):
        for trip in flatten_trips(route):
            assert trip["stats"]["total_distance_m"] > 0

    def test_stats_total_time_gte_driving_time(self, route):
        for trip in flatten_trips(route):
            assert (
                trip["stats"]["total_time_min"]
                >= trip["stats"]["total_driving_time_min"]
            )

    def test_no_monetary_values_in_stats(self, route):
        monetary = {"total_tac_eur", "total_energy_eur", "station_charges_eur"}
        for trip in flatten_trips(route):
            assert not (monetary & set(trip["stats"].keys()))

    def test_path_segment_count_equals_stops_minus_one(self, route):
        for trip in flatten_trips(route):
            assert len(trip["path"]["segments"]) == len(trip["stop_times"]) - 1

    def test_country_legs_have_no_monetary_fields(self, route):
        monetary = {"tac_eur", "energy_eur"}
        for trip in flatten_trips(route):
            for seg in trip["path"]["segments"]:
                for cl in seg["country_legs"]:
                    assert not (monetary & set(cl.keys()))

    def test_country_legs_have_energy_kwh(self, route):
        for trip in flatten_trips(route):
            for seg in trip["path"]["segments"]:
                for cl in seg["country_legs"]:
                    assert "energy_kwh" in cl
                    assert cl["energy_kwh"] >= 0

    def test_composition_embedded_with_no_cost_fields(self, route):
        for pair in route["trip_pairs"]:
            comp = pair["composition"]
            assert comp["comp_id"] == "STD-7.1"
            monetary_looking = {k for k in comp if "eur" in k.lower() or "cost" in k.lower()}
            assert not monetary_looking, f"Unexpected cost-like fields on composition: {monetary_looking}"

    def test_od_pairs_empty(self, route):
        for pair in route["trip_pairs"]:
            assert pair["od_pairs"] == []

    def test_track_infrastructure_present_and_shaped(self, route):
        assert len(route["track_infrastructure"]) > 0
        for entry in route["track_infrastructure"]:
            assert "country_code" in entry
            assert "defaulted_fields" in entry
            assert isinstance(entry["defaulted_fields"], list)
            assert "hsr_allowed" in entry

    def test_geometries_referenced_by_every_segment(self, route):
        geometry_ids = {g["id"] for g in route["geometries"]}
        for trip in flatten_trips(route):
            for seg in trip["segments"]:
                assert seg["geometry_id"] in geometry_ids


# --- Automatic scheduling contract (timetable_mode='simpleAutomatic') ---


class TestAutomaticScheduling:
    """
    No departure_time or per-stop stop_type is supplied in the request —
    both are derived. Exact minute values depend on live routing output,
    so only the contract is asserted, not specific numbers.
    """

    def test_departure_time_is_assigned(self, route):
        for trip in flatten_trips(route):
            assert trip["departure_time_min"] is not None
            assert 0 <= trip["departure_time_min"] < 48 * 60

    def test_first_stop_is_boarding(self, route):
        for trip in flatten_trips(route):
            assert trip["stop_times"][0]["stop_type"] == "boarding"

    def test_last_stop_is_alighting(self, route):
        for trip in flatten_trips(route):
            assert trip["stop_times"][-1]["stop_type"] == "alighting"

    def test_middle_stop_has_valid_type(self, route):
        for trip in flatten_trips(route):
            middle = trip["stop_times"][1:-1]
            for st in middle:
                assert st["stop_type"] in ("boarding", "alighting")

    def test_outbound_and_return_can_have_independent_departure_times(self, route):
        # Not asserting they DIFFER (that depends on routing symmetry for this
        # specific corridor) — just that each direction's timetable was built
        # from its own scheduling pass rather than being forced identical.
        outbound = next(t for t in flatten_trips(route) if t["direction_id"] == 0)
        return_t = next(t for t in flatten_trips(route) if t["direction_id"] == 1)
        assert outbound["departure_time_min"] is not None
        assert return_t["departure_time_min"] is not None


# --- Mode switches ---


class TestModeSwitches:

    def test_default_modes_applied_when_omitted(self, api_base):
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=BASE_REQUEST, timeout=60)
        assert resp.status_code == 200

    def test_explicit_default_values_accepted(self, api_base):
        body = {
            **BASE_REQUEST,
            "routing_mode": "fullRouting",
            "timetable_mode": "simpleAutomatic",
            "schedule_mode": "alwaysDaily",
            "auto_stop_addition": False,
        }
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=60)
        assert resp.status_code == 200

    def test_simple_routing_mode_accepted(self, api_base):
        body = {**BASE_REQUEST, "routing_mode": "simpleRouting"}
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=60)
        assert resp.status_code == 200

    def test_invalid_routing_mode_returns_400(self, api_base):
        body = {**BASE_REQUEST, "routing_mode": "not-a-real-mode"}
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=10)
        assert resp.status_code == 400

    def test_invalid_timetable_mode_returns_400(self, api_base):
        body = {**BASE_REQUEST, "timetable_mode": "not-a-real-mode"}
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=10)
        assert resp.status_code == 400

    def test_invalid_schedule_mode_returns_400(self, api_base):
        body = {**BASE_REQUEST, "schedule_mode": "not-a-real-mode"}
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=10)
        assert resp.status_code == 400

    def test_auto_stop_addition_true_accepted_as_noop(self, api_base):
        body = {**BASE_REQUEST, "auto_stop_addition": True}
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=60)
        assert resp.status_code == 200
        stop_ids = [
            st["stop_id"]
            for st in flatten_trips(resp.json()["route"])[0]["stop_times"]
        ]
        assert stop_ids == VALID_STOPS_3  # no-op today — list must be unchanged

    def test_auto_stop_addition_wrong_type_returns_400(self, api_base):
        body = {**BASE_REQUEST, "auto_stop_addition": "yes"}
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=10)
        assert resp.status_code == 400


# --- Proposal / scenario handling ---


class TestProposalAndScenario:

    def test_omitted_proposal_id_gets_draft_placeholder(self, api_base):
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=BASE_REQUEST, timeout=60)
        assert resp.status_code == 200
        route_id = resp.json()["route"]["route_id"]
        # P{proposal_id}_V1_R1 — proposal_id is a random int above one billion
        assert route_id.startswith("P")
        proposal_id = int(route_id.split("_")[0][1:])
        assert proposal_id > 1_000_000_000
        assert "_V1_R1" in route_id  # version forced to 1 for a draft

    def test_explicit_proposal_id_used_in_route_id(self, api_base):
        body = {**BASE_REQUEST, "proposal_id": 42, "proposal_version": 7}
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=60)
        assert resp.status_code == 200
        assert resp.json()["route"]["route_id"] == "P42_V7_R1"

    def test_omitted_scenario_id_resolves_to_a_concrete_int(self, route):
        assert isinstance(route["scenario_id"], int)


# --- Validation ---


class TestRouteValidation:

    def test_single_stop_returns_400(self, api_base):
        body = {**BASE_REQUEST, "stops": ["DE_BERLIN_HBF"]}
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=10)
        assert resp.status_code == 400

    def test_missing_stops_returns_400(self, api_base):
        body = {"composition_id": "STD-7.1"}
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=10)
        assert resp.status_code == 400

    def test_missing_composition_id_returns_400(self, api_base):
        body = {"stops": VALID_STOPS_3}
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=10)
        assert resp.status_code == 400

    def test_stops_as_old_style_objects_rejected(self, api_base):
        """Regression guard: the pre-redesign {stop_id, stop_type} object
        format must NOT be silently accepted — stops are plain ID strings now."""
        body = {
            **BASE_REQUEST,
            "stops": [{"stop_id": "DE_BERLIN_HBF", "stop_type": "boarding"},
                      {"stop_id": "AT_WIEN_HBF", "stop_type": "alighting"}],
        }
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=10)
        assert resp.status_code == 400

    def test_scenario_id_wrong_type_returns_400(self, api_base):
        body = {**BASE_REQUEST, "scenario_id": "not-an-int"}
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