"""
test_route_routing.py
=====================
Routing-specific tests — multi-country routes, stop types, dwell times,
default value propagation, composition comparison.
"""

import pytest
import requests

ROUTE_URL = "/api/route/planOrUpdate"


@pytest.fixture(scope="module")
def route_de_at(api_base):
    """2-country route: DE → AT."""
    resp = requests.post(
        f"{api_base}{ROUTE_URL}",
        json={
            "proposal_id": 10,
            "proposal_version": 1,
            "stops": [
                {"stop_id": "DE_BERLIN_HBF", "stop_type": "boarding"},
                {"stop_id": "AT_WIEN_HBF", "stop_type": "alighting"},
            ],
            "composition_id": "STD-7.1",
            "departure_time": "21:00",
        },
        timeout=60,
    )
    assert resp.status_code == 200, resp.text[:300]
    return resp.json()["route"]


@pytest.fixture(scope="module")
def route_de_ch_at(api_base):
    """3-country route: DE → CH → AT (via Zürich)."""
    resp = requests.post(
        f"{api_base}{ROUTE_URL}",
        json={
            "proposal_id": 11,
            "proposal_version": 1,
            "stops": [
                {"stop_id": "DE_BERLIN_HBF", "stop_type": "boarding"},
                {"stop_id": "CH_ZUERICH_HB", "stop_type": "both"},
                {"stop_id": "AT_WIEN_HBF", "stop_type": "alighting"},
            ],
            "composition_id": "STD-7.1",
            "departure_time": "21:00",
        },
        timeout=60,
    )
    assert resp.status_code == 200, resp.text[:300]
    return resp.json()["route"]


@pytest.fixture(scope="module")
def route_dk_se(api_base):
    """Route touching SE which has NULL TAC → default values applied."""
    resp = requests.post(
        f"{api_base}{ROUTE_URL}",
        json={
            "proposal_id": 12,
            "proposal_version": 1,
            "stops": [
                {"stop_id": "DK_COPENHAGEN", "stop_type": "boarding"},
                {"stop_id": "SE_STOCKHOLM_C", "stop_type": "alighting"},
            ],
            "composition_id": "STD-7.1",
            "departure_time": "20:00",
        },
        timeout=60,
    )
    assert resp.status_code == 200, resp.text[:300]
    return resp.json()["route"]


# --- Multi-country ---


class TestMultiCountry:

    def test_de_at_route_has_two_countries(self, route_de_at):
        outbound = next(t for t in route_de_at["trips"] if t["direction_id"] == 0)
        countries = {
            cl["country_code"]
            for seg in outbound["path"]["segments"]
            for cl in seg["country_legs"]
        }
        assert "DE" in countries
        assert "AT" in countries

    def test_de_ch_at_has_three_countries(self, route_de_ch_at):
        outbound = next(t for t in route_de_ch_at["trips"] if t["direction_id"] == 0)
        countries = {
            cl["country_code"]
            for seg in outbound["path"]["segments"]
            for cl in seg["country_legs"]
        }
        assert len(countries) >= 3

    def test_multi_country_distances_sum_to_total(self, route_de_ch_at):
        for trip in route_de_ch_at["trips"]:
            leg_sum = sum(
                cl["distance_m"]
                for seg in trip["path"]["segments"]
                for cl in seg["country_legs"]
            )
            assert abs(leg_sum - trip["stats"]["total_distance_m"]) < 100  # within 100m

    def test_multi_country_driving_times_sum_to_total(self, route_de_ch_at):
        for trip in route_de_ch_at["trips"]:
            leg_sum = sum(
                cl["driving_time_min"]
                for seg in trip["path"]["segments"]
                for cl in seg["country_legs"]
            )
            assert abs(leg_sum - trip["stats"]["total_driving_time_min"]) <= 1

    @pytest.mark.skip(
        reason="Dummy energy model uses flat 28 kWh/km — terrain effect not implemented yet. Re-enable after energy team calibrates."
    )
    def test_mountainous_country_has_higher_terrain_score(self, route_de_ch_at):
        outbound = next(t for t in route_de_ch_at["trips"] if t["direction_id"] == 0)
        ch_legs = [
            cl
            for seg in outbound["path"]["segments"]
            for cl in seg["country_legs"]
            if cl["country_code"] == "CH"
        ]
        de_legs = [
            cl
            for seg in outbound["path"]["segments"]
            for cl in seg["country_legs"]
            if cl["country_code"] == "DE"
        ]
        if ch_legs and de_legs:
            # CH terrain_score=1.8, DE terrain_score=1.0 — energy per km should be higher in CH
            ch_energy_per_km = sum(cl["energy_kwh"] for cl in ch_legs) / sum(
                cl["distance_m"] / 1000 for cl in ch_legs
            )
            de_energy_per_km = sum(cl["energy_kwh"] for cl in de_legs) / sum(
                cl["distance_m"] / 1000 for cl in de_legs
            )
            assert (
                ch_energy_per_km > de_energy_per_km
            ), "CH (mountainous) should have higher energy per km than DE (flat)"


# --- Default values ---


class TestDefaultValues:

    def test_se_route_has_param_versions(self, route_dk_se):
        outbound = next(t for t in route_dk_se["trips"] if t["direction_id"] == 0)
        assert len(outbound["param_versions"]) > 0

    def test_se_tac_is_default(self, route_dk_se):
        """SE has NULL tac in DB — trip param_versions should show is_default=True."""
        outbound = next(t for t in route_dk_se["trips"] if t["direction_id"] == 0)
        pv = outbound["param_versions"]
        se_tac_key = next((k for k in pv if "SE" in k and "tac" in k), None)
        if se_tac_key:
            assert (
                pv[se_tac_key]["is_default"] is True
            ), f"SE tac should be is_default=True, got: {pv[se_tac_key]}"
        else:
            pytest.skip("No SE tac entry in param_versions")

    def test_de_tac_is_not_default(self, route_de_at):
        """DE has explicit tac — trip param_versions should show is_default=False."""
        outbound = next(t for t in route_de_at["trips"] if t["direction_id"] == 0)
        pv = outbound["param_versions"]
        de_tac_key = next((k for k in pv if "DE" in k and "tac" in k), None)
        if de_tac_key:
            assert pv[de_tac_key]["is_default"] is False
        else:
            pytest.skip("No DE tac entry in param_versions")


# --- Stop types ---


class TestStopTypes:

    def test_boarding_only_stop_has_no_arrival(self, route_de_at):
        outbound = next(t for t in route_de_at["trips"] if t["direction_id"] == 0)
        first = outbound["stop_times"][0]
        assert first["stop_type"] == "boarding"
        assert first["arrival_time_min"] is None

    def test_alighting_only_stop_has_no_departure(self, route_de_at):
        outbound = next(t for t in route_de_at["trips"] if t["direction_id"] == 0)
        last = outbound["stop_times"][-1]
        assert last["stop_type"] == "alighting"
        assert last["departure_time_min"] is None

    def test_both_stop_has_arrival_and_departure(self, route_de_ch_at):
        outbound = next(t for t in route_de_ch_at["trips"] if t["direction_id"] == 0)
        middle = outbound["stop_times"][1]
        assert middle["stop_type"] == "both"
        assert middle["arrival_time_min"] is not None
        assert middle["departure_time_min"] is not None
        assert middle["departure_time_min"] > middle["arrival_time_min"]

    def test_dwell_time_respects_min_boarding(self, route_de_ch_at):
        """CH has 3min min boarding — dwell at Zürich should be >= 3 min."""
        outbound = next(t for t in route_de_ch_at["trips"] if t["direction_id"] == 0)
        zurich = next(
            (st for st in outbound["stop_times"] if st["stop_id"] == "CH_ZUERICH_HB"),
            None,
        )
        if zurich and zurich["dwell_time_min"] is not None:
            assert zurich["dwell_time_min"] >= 3


# --- Composition comparison ---


class TestCompositionComparison:

    def test_heavier_composition_has_more_energy(self, api_base):
        """STD-13.1 (13 coaches) should consume more energy than STD-3.1 (3 coaches)."""
        results = {}
        for comp_id in ("STD-3.1", "STD-13.1"):
            resp = requests.post(
                f"{api_base}{ROUTE_URL}",
                json={
                    "proposal_id": 20,
                    "proposal_version": 1,
                    "stops": [
                        {"stop_id": "DE_BERLIN_HBF", "stop_type": "boarding"},
                        {"stop_id": "AT_WIEN_HBF", "stop_type": "alighting"},
                    ],
                    "composition_id": comp_id,
                    "departure_time": "21:00",
                },
                timeout=60,
            )
            assert resp.status_code == 200, f"{comp_id}: {resp.text[:200]}"
            trip = next(
                t for t in resp.json()["route"]["trips"] if t["direction_id"] == 0
            )
            results[comp_id] = trip["stats"]["total_energy_kwh"]

        assert (
            results["STD-13.1"] >= results["STD-3.1"]
        ), f"STD-13.1 energy {results['STD-13.1']} should be >= STD-3.1 {results['STD-3.1']}"

    def test_same_stops_same_distance_different_compositions(self, api_base):
        """Same stops, different compositions → same distance."""
        distances = {}
        for comp_id in ("STD-3.1", "STD-7.1"):
            resp = requests.post(
                f"{api_base}{ROUTE_URL}",
                json={
                    "proposal_id": 21,
                    "proposal_version": 1,
                    "stops": VALID_STOPS_2 if True else [],  # noqa
                    "composition_id": comp_id,
                    "departure_time": "21:00",
                },
                timeout=60,
            )
            assert resp.status_code == 200
            trip = next(
                t for t in resp.json()["route"]["trips"] if t["direction_id"] == 0
            )
            distances[comp_id] = trip["stats"]["total_distance_m"]

        assert (
            distances["STD-3.1"] == distances["STD-7.1"]
        ), "Distance should be independent of composition"


VALID_STOPS_2 = [
    {"stop_id": "DE_BERLIN_HBF", "stop_type": "boarding"},
    {"stop_id": "AT_WIEN_HBF", "stop_type": "alighting"},
]
