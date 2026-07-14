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

auto_stop_addition is a three-value string enum since route builder 0.9.5
("off" / "add" / "suggest", default "add") — booleans are rejected with 400.
Every mode has its own test case below. The seed catalog deliberately
contains CZ_BRNO_HLN, which sits ~10m off the natural Berlin-Dresden-Wien
corridor (Dresden-Praha-Brno-Wien) and comfortably fits the detour budget —
so the actual insertion/auto_added/suggestion paths are all pinned end to
end, not just the "no candidates found" outcome. The module fixtures
therefore pin auto_stop_addition explicitly: plan_response uses "off"
(deterministic caller's-list route for the structural tests), and
plan_response_default_add omits the field to cover the "add" default.

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
    # Pinned off so the structural tests below see a deterministic
    # caller's-list route — CZ_BRNO_HLN would otherwise be auto-added
    # (see module docstring); the add/suggest paths have their own
    # fixture/requests in TestModeSwitches.
    "auto_stop_addition": "off",
}

# The stop list the "add" default actually produces on this corridor:
# CZ_BRNO_HLN merged in at its geographic position (between Dresden and
# Wien), everything else the caller's own.
STOPS_WITH_BRNO = [
    "DE_BERLIN_HBF",
    "DE_DRESDEN_HBF",
    "CZ_BRNO_HLN",
    "AT_WIEN_HBF",
]


@pytest.fixture(scope="module")
def plan_response(api_base):
    """One full response body (route_builder_version + request echo + route)
    for the standard 3-stop request with auto_stop_addition="off" — built
    once for this module."""
    resp = requests.post(f"{api_base}{ROUTE_URL}", json=BASE_REQUEST, timeout=90)
    assert resp.status_code == 200, f"Route build failed: {resp.text[:300]}"
    return resp.json()


@pytest.fixture(scope="module")
def plan_response_default_add(api_base):
    """Same request with auto_stop_addition omitted entirely — covers the
    "add" default, which inserts CZ_BRNO_HLN on this corridor. Built once
    for this module."""
    body = {k: v for k, v in BASE_REQUEST.items() if k != "auto_stop_addition"}
    resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=90)
    assert resp.status_code == 200, f"Route build failed: {resp.text[:300]}"
    return resp.json()


# =============================================================================
# Response structure
# =============================================================================


class TestResponseStructure:

    def test_top_level_keys(self, plan_response):
        """Response carries exactly route_builder_version, request, route —
        no suggested_stops outside auto_stop_addition='suggest' (that mode
        has its own envelope test in TestModeSwitches)."""
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
            "dynamics_time_min",
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

    def test_od_pairs_populated_by_stopgap_demand(self, plan_response):
        """plan_route() itself leaves od_pairs empty, but the endpoint then
        runs the stopgap demand distribution (see api/route.py and
        OPEN_TODOS["demand_model"] in models/route/version.py) so that
        evaluation returns non-zero revenue — od_pairs comes back populated
        with directional pairs for BOTH trips of the pair. Only structural
        properties are pinned here; the distribution itself is a stopgap."""
        for pair in plan_response["route"]["trip_pairs"]:
            od_pairs = pair["od_pairs"]
            assert od_pairs != []
            trip_ids = {
                pair["outbound"]["trip_id"],
                pair["return_trip"]["trip_id"],
            }
            assert {od["trip_id"] for od in od_pairs} == trip_ids
            for od in od_pairs:
                assert od["origin_stop_id"] != od["destination_stop_id"]
                assert od["class_main"]
                assert od["places_sold"] >= 0

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

    def test_general_parameters_shaped_and_consistent(self, plan_response):
        """Each trip carries a general_parameters section (trip_km,
        route_duration_min, average_speed_kmh), sitting between direction
        and segments, with figures internally consistent with each other
        and with the trip's own segments."""
        for trip in all_trips(plan_response["route"]):
            keys = list(trip)
            assert (
                keys.index("direction")
                < keys.index("general_parameters")
                < keys.index("segments")
            )

            stats = trip["general_parameters"]
            assert set(stats) == {
                "trip_km",
                "route_duration_min",
                "average_speed_kmh",
            }
            assert stats["trip_km"] > 0
            assert stats["route_duration_min"] > 0
            assert stats["average_speed_kmh"] > 0

            # trip_km matches the sum of the trip's own segment distances
            expected_km = sum(s["distance_m"] for s in trip["segments"]) / 1000
            assert stats["trip_km"] == pytest.approx(expected_km, abs=0.05)

            # average_speed_kmh is internally derived from trip_km and
            # route_duration_min (elapsed time), not recomputed independently
            expected_speed = stats["trip_km"] / (stats["route_duration_min"] / 60)
            assert stats["average_speed_kmh"] == pytest.approx(expected_speed, abs=0.05)


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
            "auto_stop_addition": "add",
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
        "field",
        ["routing_mode", "timetable_mode", "schedule_mode", "auto_stop_addition"],
    )
    def test_invalid_mode_returns_400(self, api_base, field):
        """An unknown value for any mode switch is rejected at validation."""
        body = {**BASE_REQUEST, field: "not-a-real-mode"}
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=10)
        assert resp.status_code == 400

    # --- auto_stop_addition — one case per enum value + bool rejection ------

    def test_auto_stop_addition_defaults_to_add_and_inserts_brno(
        self, plan_response_default_add
    ):
        """With auto_stop_addition omitted (the 'add' default), CZ_BRNO_HLN
        — ~10m off the routed corridor, comfortably within the detour
        budget — is inserted at its geographic position between Dresden and
        Wien, marked auto_added=true, everything else the caller's own.
        The return trip carries the same final stop list reversed with the
        same auto_added marking (the search runs once, from outbound — see
        _build_trip_pair() in route_factory.py)."""
        pair = plan_response_default_add["route"]["trip_pairs"][0]
        assert "suggested_stops" not in plan_response_default_add

        outbound = stop_times(pair["outbound"])
        assert [s["stop_id"] for s in outbound] == STOPS_WITH_BRNO
        assert [s["auto_added"] for s in outbound] == [False, False, True, False]

        return_stops = stop_times(pair["return_trip"])
        assert [s["stop_id"] for s in return_stops] == list(reversed(STOPS_WITH_BRNO))
        assert [s["auto_added"] for s in return_stops] == [
            False,
            True,
            False,
            False,
        ]

    def test_auto_stop_addition_add_explicit_accepted(self, api_base):
        """Explicit 'add' (the default spelled out) behaves identically to
        the omitted field — Brno inserted — and does not carry a
        suggested_stops section (that's exclusive to 'suggest')."""
        body = {**BASE_REQUEST, "auto_stop_addition": "add"}
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=90)
        assert resp.status_code == 200
        assert "suggested_stops" not in resp.json()
        outbound = resp.json()["route"]["trip_pairs"][0]["outbound"]
        assert [s["stop_id"] for s in stop_times(outbound)] == STOPS_WITH_BRNO

    def test_auto_stop_addition_off_returns_exact_caller_list(self, api_base):
        """Explicit opt-out: auto_stop_addition='off' skips the candidate
        search entirely and returns exactly the caller's own stop list,
        with no suggested_stops section."""
        body = {**BASE_REQUEST, "auto_stop_addition": "off"}
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=90)
        assert resp.status_code == 200
        assert "suggested_stops" not in resp.json()
        outbound = resp.json()["route"]["trip_pairs"][0]["outbound"]
        assert [s["stop_id"] for s in stop_times(outbound)] == STOPS_BERLIN_DRESDEN_WIEN

    def test_auto_stop_addition_suggest_returns_suggested_stops_section(
        self, api_base, plan_response_default_add
    ):
        """auto_stop_addition='suggest' routes exactly like 'off' (caller's
        own stop list, nothing added, auto_added false throughout) but
        carries a top-level suggested_stops list placed between request and
        route. On this corridor it contains exactly CZ_BRNO_HLN, with a
        positive added_time_min — and cross-mode consistency holds: the
        suggested stop ids equal the ids the 'add' default actually
        inserted (all candidates fit the budget here)."""
        body = {**BASE_REQUEST, "auto_stop_addition": "suggest"}
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=90)
        assert resp.status_code == 200
        payload = resp.json()

        assert set(payload) == {
            "route_builder_version",
            "request",
            "suggested_stops",
            "route",
        }
        keys = list(payload)
        assert (
            keys.index("request") < keys.index("suggested_stops") < keys.index("route")
        )

        suggested = payload["suggested_stops"]
        assert [s["stop_id"] for s in suggested] == ["CZ_BRNO_HLN"]
        for s in suggested:
            assert set(s) == {
                "stop_id",
                "stop_name",
                "country_code",
                "lat",
                "lon",
                "added_time_min",
            }
            assert s["added_time_min"] > 0

        # Route itself is exactly the caller's own list — nothing added.
        outbound = payload["route"]["trip_pairs"][0]["outbound"]
        assert [s["stop_id"] for s in stop_times(outbound)] == STOPS_BERLIN_DRESDEN_WIEN
        for stop in stop_times(outbound):
            assert stop["auto_added"] is False

        # Cross-mode consistency with the 'add' default.
        added = {
            s["stop_id"]
            for s in stop_times(
                plan_response_default_add["route"]["trip_pairs"][0]["outbound"]
            )
            if s["auto_added"]
        }
        assert {s["stop_id"] for s in suggested} == added

    def test_auto_added_field_false_throughout_when_off(self, plan_response):
        """With auto_stop_addition='off' (the module fixture), every stop is
        the caller's own — auto_added is present and false throughout."""
        outbound = plan_response["route"]["trip_pairs"][0]["outbound"]
        for stop in stop_times(outbound):
            assert stop["auto_added"] is False

    @pytest.mark.parametrize("legacy_bool", [True, False])
    def test_auto_stop_addition_bool_returns_400(self, api_base, legacy_bool):
        """Pre-0.9.5 booleans are rejected, not silently mapped to
        'add'/'off' — the request contract is the string enum only."""
        body = {**BASE_REQUEST, "auto_stop_addition": legacy_bool}
        resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=10)
        assert resp.status_code == 400

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