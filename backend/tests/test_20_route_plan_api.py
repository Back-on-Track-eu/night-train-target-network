"""
test_20_route_plan_api.py
=========================
Contract tests for POST /api/route/plan — response structure, the automatic
scheduling contract, mode switches, proposal/scenario handling, and request
validation.

route/plan is stateless and always a full build (no adjust mode), takes a
plain list of stop IDs (boarding/alighting and departure time are derived —
see timetable_mode), and returns NO monetary values — those belong to
POST /api/evaluation/calc.

Exact departure_time_min values are never asserted here — they're a function
of live OpenRailRouting output. What IS asserted is the contract automatic
scheduling makes: first stop boarding, last stop alighting, a real time
assigned, monotonically increasing stop times.
"""

import pytest
import requests

from tests.conftest import STOPS_BERLIN_DRESDEN_WIEN
from tests.helpers import ROUTE_URL, all_trips, stop_times

BASE_REQUEST = {
    "stops": STOPS_BERLIN_DRESDEN_WIEN,
    "composition_id": "STD-7.1",
}


@pytest.fixture(scope="module")
def plan_response(api_base):
    """One full response body (route_builder_version + request echo + route)
    for the standard 3-stop request — built once for this module."""
    resp = requests.post(f"{api_base}{ROUTE_URL}", json=BASE_REQUEST, timeout=90)
    assert resp.status_code == 200, f"Route build failed: {resp.text[:300]}"
    return resp.json()


# =============================================================================
# Response structure
# =============================================================================


class TestResponseStructure:

    def test_top_level_keys(self, plan_response):
        """Response carries exactly route_builder_version, request, route."""
        assert set(plan_response) == {"route_builder_version", "request", "route"}

    def test_request_echoed_verbatim(self, plan_response):
        """The request body is echoed back unchanged."""
        assert plan_response["request"] == BASE_REQUEST

    def test_route_top_level_keys(self, plan_response):
        """The route dict carries the full route_to_dict() layout, including
        the newer parkings/shuntings/track_infrastructure/geometries sections."""
        assert set(plan_response["route"]) >= {
            "route_id",
            "scenario_id",
            "schedule",
            "trip_pairs",
            "parkings",
            "shuntings",
            "track_infrastructure",
            "geometries",
        }

    def test_one_trip_pair_with_both_directions(self, plan_response):
        """One trip pair with outbound (direction 0) and return (direction 1)."""
        route = plan_response["route"]
        assert len(route["trip_pairs"]) == 1
        directions = {t["direction"] for t in all_trips(route)}
        assert directions == {0, 1}

    def test_outbound_stop_order_matches_request(self, plan_response):
        """Outbound trip visits exactly the requested stops in order."""
        outbound = plan_response["route"]["trip_pairs"][0]["outbound"]
        assert [s["stop_id"] for s in stop_times(outbound)] == STOPS_BERLIN_DRESDEN_WIEN

    def test_return_trip_stops_reversed(self, plan_response):
        """Return trip visits the same stops in reverse order."""
        pair = plan_response["route"]["trip_pairs"][0]
        out_ids = [s["stop_id"] for s in stop_times(pair["outbound"])]
        ret_ids = [s["stop_id"] for s in stop_times(pair["return_trip"])]
        assert ret_ids == list(reversed(out_ids))

    def test_segment_count_equals_stops_minus_one(self, plan_response):
        """N stops → N-1 segments per trip."""
        for trip in all_trips(plan_response["route"]):
            assert len(trip["segments"]) == len(stop_times(trip)) - 1

    def test_segments_carry_physics_fields(self, plan_response):
        """Every segment carries distance/time/buffer/energy and the
        per-country distance/time shares."""
        required = {
            "from_stop",
            "to_stop",
            "geometry_id",
            "distance_m",
            "driving_time_min",
            "buffer_time_min",
            "energy_kwh",
            "country_distance_shares",
            "country_time_shares",
        }
        for trip in all_trips(plan_response["route"]):
            for seg in trip["segments"]:
                missing = required - set(seg)
                assert missing == set(), f"Segment missing fields: {missing}"
                assert seg["distance_m"] > 0

    def test_no_monetary_values_anywhere(self, plan_response):
        """route/plan is physics-only: no *_eur / *cost* keys anywhere in the
        route dict except the endpoint's own key names (none exist today)."""

        def monetary_keys(node, path=""):
            found = []
            if isinstance(node, dict):
                for k, v in node.items():
                    if "eur" in k.lower() or "cost" in k.lower():
                        found.append(f"{path}.{k}")
                    found += monetary_keys(v, f"{path}.{k}")
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    found += monetary_keys(v, f"{path}[{i}]")
            return found

        route = {k: v for k, v in plan_response["route"].items() if k != "geometries"}
        assert monetary_keys(route) == []

    def test_geometries_and_segments_reference_each_other(self, plan_response):
        """geometry_id resolution is bijective in practice: every segment
        references an existing geometry, ids are unique, and every geometry
        has non-empty coordinates."""
        route = plan_response["route"]
        ids = [g["id"] for g in route["geometries"]]
        assert len(ids) == len(set(ids)), "Duplicate geometry ids"
        for g in route["geometries"]:
            assert len(g["coords"]) > 0, f"Geometry {g['id']} has no coordinates"
        id_set = set(ids)
        for trip in all_trips(route):
            for seg in trip["segments"]:
                assert seg["geometry_id"] in id_set

    def test_composition_embedded_without_cost_fields(self, plan_response):
        """The embedded composition is the physics-relevant subset only —
        no cost fields, but capacity/density per class present."""
        comp = plan_response["route"]["trip_pairs"][0]["composition"]
        assert comp["comp_id"] == "STD-7.1"
        cost_like = {k for k in comp if "eur" in k.lower() or "cost" in k.lower()}
        assert cost_like == set(), f"Cost-like fields on composition: {cost_like}"
        assert sum(comp["places_by_class"].values()) > 0
        assert len(comp["density_by_class"]) > 0

    def test_od_pairs_empty_on_fresh_plan(self, plan_response):
        """A freshly planned route carries no demand — od_pairs is []."""
        for pair in plan_response["route"]["trip_pairs"]:
            assert pair["od_pairs"] == []

    def test_track_infrastructure_present_and_shaped(self, plan_response):
        """route['track_infrastructure'] lists each touched country with the
        physics subset and its defaulted_fields list."""
        entries = plan_response["route"]["track_infrastructure"]
        assert len(entries) > 0
        for entry in entries:
            assert {
                "country_code",
                "defaulted_fields",
                "hsr_allowed",
                "terrain_score",
                "buffer_quota_per",
            } <= set(entry)
            assert isinstance(entry["defaulted_fields"], list)


# =============================================================================
# Automatic scheduling contract (timetable_mode='simpleAutomatic')
# =============================================================================


class TestAutomaticScheduling:

    def test_departure_time_assigned(self, plan_response):
        """Every trip gets a real departure time on the continuous
        minutes-from-midnight scale (< 48h)."""
        for trip in all_trips(plan_response["route"]):
            dep = stop_times(trip)[0]["departure_time_min"]
            assert dep is not None
            assert 0 <= dep < 48 * 60

    def test_terminal_stop_types(self, plan_response):
        """First stop is always boarding (no arrival), last stop always
        alighting (no departure) — by position, regardless of the mirror rule."""
        for trip in all_trips(plan_response["route"]):
            stops = stop_times(trip)
            assert stops[0]["stop_type"] == "boarding"
            assert stops[0]["arrival_time_min"] is None
            assert stops[-1]["stop_type"] == "alighting"
            assert stops[-1]["departure_time_min"] is None

    def test_intermediate_stops_boarding_or_alighting(self, plan_response):
        """Intermediate stops are classified boarding OR alighting — 'both'
        cannot be produced by automatic scheduling."""
        for trip in all_trips(plan_response["route"]):
            for st in stop_times(trip)[1:-1]:
                assert st["stop_type"] in ("boarding", "alighting")
                assert st["arrival_time_min"] is not None
                assert st["departure_time_min"] is not None

    def test_stop_times_monotonically_increasing(self, plan_response):
        """Arrival times increase strictly along every trip."""
        for trip in all_trips(plan_response["route"]):
            arrivals = [
                s["arrival_time_min"]
                for s in stop_times(trip)
                if s["arrival_time_min"] is not None
            ]
            assert arrivals == sorted(arrivals)

    def test_schedule_is_daily_both_seasons(self, plan_response):
        """schedule_mode default 'alwaysDaily' → daily frequency in both
        seasons (summer + winter)."""
        schedules = plan_response["route"]["schedule"]["seasonal_schedules"]
        assert {s["season"] for s in schedules} == {"summer", "winter"}
        assert all(s["frequency"] == "daily" for s in schedules)


# =============================================================================
# Mode switches
# =============================================================================


class TestModeSwitches:

    def test_explicit_default_values_accepted(self, api_base):
        """Spelling out every default mode explicitly is accepted."""
        body = {
            **BASE_REQUEST,
            "routing_mode": "fullRouting",
            "timetable_mode": "simpleAutomatic",
            "schedule_mode": "alwaysDaily",
            "auto_stop_addition": True,
        }
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=90)
        assert resp.status_code == 200

    def test_simple_routing_mode_accepted(self, api_base):
        """routing_mode='simpleRouting' (cheap single-pass routing) is a
        valid alternative and still produces a full route."""
        body = {**BASE_REQUEST, "routing_mode": "simpleRouting"}
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=90)
        assert resp.status_code == 200
        assert len(resp.json()["route"]["trip_pairs"]) == 1

    @pytest.mark.parametrize(
        "field", ["routing_mode", "timetable_mode", "schedule_mode"]
    )
    def test_invalid_mode_returns_400(self, api_base, field):
        """An unknown value for any mode switch is rejected at validation."""
        body = {**BASE_REQUEST, field: "not-a-real-mode"}
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=10)
        assert resp.status_code == 400

    def test_auto_stop_addition_default_true_with_no_nearby_candidates_is_noop(
        self, plan_response
    ):
        """auto_stop_addition defaults to true and is implemented (see
        models/route/timetable.py), but the seed catalog only has 8 stops
        total and every one besides this request's own is far from the
        Berlin-Dresden-Wien corridor — none falls within AUTO_STOP_BUFFER_M
        of the routed path. So the module fixture's stop list (built with
        no auto_stop_addition field at all, i.e. the true default) still
        comes back unchanged — a real 'no candidates found' outcome, not a
        skipped/disabled one. This can't tell 'no candidates existed' apart
        from 'a real candidate was found and correctly rejected' — see
        tests/README.md's Suggested seed-data additions for what closing
        that gap needs.
        """
        outbound = plan_response["route"]["trip_pairs"][0]["outbound"]
        assert [s["stop_id"] for s in stop_times(outbound)] == STOPS_BERLIN_DRESDEN_WIEN

    def test_auto_stop_addition_false_returns_exact_caller_list(self, api_base):
        """Explicit opt-out: auto_stop_addition=false skips the algorithm
        entirely and returns exactly the caller's own stop list."""
        body = {**BASE_REQUEST, "auto_stop_addition": False}
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=90)
        assert resp.status_code == 200
        outbound = resp.json()["route"]["trip_pairs"][0]["outbound"]
        assert [s["stop_id"] for s in stop_times(outbound)] == STOPS_BERLIN_DRESDEN_WIEN

    def test_auto_added_field_present_and_false_with_default_request(
        self, plan_response
    ):
        """Every Stop carries auto_added, false for every stop on the module
        fixture's default request (auto_stop_addition omitted → true, but no
        candidates exist near this corridor in the seed catalog — see the
        noop test above)."""
        outbound = plan_response["route"]["trip_pairs"][0]["outbound"]
        for stop in stop_times(outbound):
            assert stop["auto_added"] is False

    def test_auto_added_field_false_when_disabled(self, api_base):
        """With auto_stop_addition explicitly false, every stop is the
        caller's own — auto_added is false throughout."""
        body = {**BASE_REQUEST, "auto_stop_addition": False}
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=90)
        assert resp.status_code == 200
        outbound = resp.json()["route"]["trip_pairs"][0]["outbound"]
        for stop in stop_times(outbound):
            assert stop["auto_added"] is False

    def test_auto_stop_addition_wrong_type_returns_400(self, api_base):
        body = {**BASE_REQUEST, "auto_stop_addition": "yes"}
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=10)
        assert resp.status_code == 400


# =============================================================================
# Proposal / scenario handling
# =============================================================================


class TestProposalAndScenario:

    def test_omitted_proposal_id_gets_draft_placeholder(self, plan_response):
        """Without a proposal_id, a random draft placeholder above one billion
        is minted and proposal_version forced to 1 — route_id P{id}_V1_R1."""
        route_id = plan_response["route"]["route_id"]
        assert route_id.startswith("P")
        proposal_id = int(route_id.split("_")[0][1:])
        assert proposal_id > 1_000_000_000
        assert "_V1_R1" in route_id

    def test_explicit_proposal_id_used_in_route_id(self, api_base):
        """An explicit proposal_id/version pair appears verbatim in route_id."""
        body = {**BASE_REQUEST, "proposal_id": 42, "proposal_version": 7}
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=90)
        assert resp.status_code == 200
        assert resp.json()["route"]["route_id"] == "P42_V7_R1"

    def test_omitted_scenario_id_resolves_to_base(self, plan_response, base_scenario):
        """Without a scenario_id, the route embeds the concrete resolved id
        of the live is_current_base scenario — never None."""
        assert plan_response["route"]["scenario_id"] == base_scenario["scenario_id"]

    def test_explicit_scenario_id_embedded(self, api_base, hsr_scenario):
        """An explicit scenario_id (the seeded HSR-allowed scenario) is
        embedded verbatim."""
        body = {**BASE_REQUEST, "scenario_id": hsr_scenario["scenario_id"]}
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=90)
        assert resp.status_code == 200
        assert resp.json()["route"]["scenario_id"] == hsr_scenario["scenario_id"]


# =============================================================================
# Validation
# =============================================================================


class TestValidation:

    def test_single_stop_returns_400(self, api_base):
        body = {**BASE_REQUEST, "stops": ["DE_BERLIN_HBF"]}
        assert (
            requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=10).status_code
            == 400
        )

    def test_missing_stops_returns_400(self, api_base):
        body = {"composition_id": "STD-7.1"}
        assert (
            requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=10).status_code
            == 400
        )

    def test_missing_composition_id_returns_400(self, api_base):
        body = {"stops": STOPS_BERLIN_DRESDEN_WIEN}
        assert (
            requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=10).status_code
            == 400
        )

    def test_old_style_stop_objects_rejected(self, api_base):
        """Regression guard: the pre-redesign {stop_id, stop_type} object
        format must NOT be silently accepted — stops are plain ID strings."""
        body = {
            **BASE_REQUEST,
            "stops": [
                {"stop_id": "DE_BERLIN_HBF", "stop_type": "boarding"},
                {"stop_id": "AT_WIEN_HBF", "stop_type": "alighting"},
            ],
        }
        assert (
            requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=10).status_code
            == 400
        )

    def test_scenario_id_wrong_type_returns_400(self, api_base):
        body = {**BASE_REQUEST, "scenario_id": "not-an-int"}
        assert (
            requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=10).status_code
            == 400
        )

    def test_unknown_composition_returns_422(self, api_base):
        """A syntactically valid but unknown composition_id is a domain error
        (422), not a validation error (400)."""
        body = {**BASE_REQUEST, "composition_id": "DOES-NOT-EXIST"}
        assert (
            requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=30).status_code
            == 422
        )

    def test_non_json_body_returns_400(self, api_base):
        resp = requests.post(
            f"{api_base}{ROUTE_URL}",
            data="not-json",
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        assert resp.status_code == 400