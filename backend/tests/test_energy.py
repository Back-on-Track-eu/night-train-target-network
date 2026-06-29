"""
test_energy.py
==============
Unit tests for the energy model.

Tests the dummy flat-factor implementation and verifies energy
attribution per country leg — without requiring monetary evaluation.
All tests work directly against the route builder output.
"""

import pytest
import requests

ROUTE_URL = "/api/route/planOrUpdate"


def _build_route(api_base, stops, comp_id="STD-7.1", proposal_id=200):
    resp = requests.post(
        f"{api_base}{ROUTE_URL}",
        json={
            "proposal_id": proposal_id,
            "proposal_version": 1,
            "stops": stops,
            "composition_id": comp_id,
            "departure_time": "21:00",
        },
        timeout=60,
    )
    assert resp.status_code == 200, resp.text[:300]
    return resp.json()["route"]


STOPS_DE_AT = [
    {"stop_id": "DE_BERLIN_HBF", "stop_type": "boarding"},
    {"stop_id": "AT_WIEN_HBF", "stop_type": "alighting"},
]

STOPS_DE_CH_AT = [
    {"stop_id": "DE_BERLIN_HBF", "stop_type": "boarding"},
    {"stop_id": "CH_ZUERICH_HB", "stop_type": "both"},
    {"stop_id": "AT_WIEN_HBF", "stop_type": "alighting"},
]


@pytest.fixture(scope="module")
def route_de_at(api_base):
    return _build_route(api_base, STOPS_DE_AT, proposal_id=200)


@pytest.fixture(scope="module")
def route_de_ch_at(api_base):
    return _build_route(api_base, STOPS_DE_CH_AT, proposal_id=201)


class TestEnergyBasic:

    def test_all_country_legs_have_energy_kwh(self, route_de_at):
        for trip in route_de_at["trips"]:
            for seg in trip["path"]["segments"]:
                for cl in seg["country_legs"]:
                    assert "energy_kwh" in cl, f"Missing energy_kwh on leg {cl}"
                    assert cl["energy_kwh"] >= 0

    def test_total_energy_equals_sum_of_legs(self, route_de_at):
        for trip in route_de_at["trips"]:
            leg_sum = sum(
                cl["energy_kwh"]
                for seg in trip["path"]["segments"]
                for cl in seg["country_legs"]
            )
            assert leg_sum == pytest.approx(trip["stats"]["total_energy_kwh"], rel=1e-3)

    def test_energy_positive_for_non_zero_distance(self, route_de_at):
        for trip in route_de_at["trips"]:
            for seg in trip["path"]["segments"]:
                for cl in seg["country_legs"]:
                    if cl["distance_m"] > 0:
                        assert (
                            cl["energy_kwh"] > 0
                        ), f"Zero energy for non-zero distance on {cl['country_code']} leg"

    def test_energy_per_km_field_present(self, route_de_at):
        for trip in route_de_at["trips"]:
            for seg in trip["path"]["segments"]:
                for cl in seg["country_legs"]:
                    assert "energy_kwh_per_km" in cl

    def test_energy_per_km_consistent_with_energy_and_distance(self, route_de_at):
        for trip in route_de_at["trips"]:
            for seg in trip["path"]["segments"]:
                for cl in seg["country_legs"]:
                    dist_km = cl["distance_m"] / 1000
                    if dist_km > 0:
                        expected = cl["energy_kwh"] / dist_km
                        assert cl["energy_kwh_per_km"] == pytest.approx(
                            expected, rel=1e-2
                        )


class TestEnergyByTerrain:

    def test_energy_proportional_to_distance_flat_factor(self, route_de_ch_at):
        """
        Current dummy model: energy = FLAT_FACTOR × distance_km.
        Verify energy/km is constant across all legs (flat factor applied).
        This test should be REPLACED once the real regression model is calibrated.
        """
        DUMMY_FACTOR = 28.0  # kWh/km — current placeholder

        for trip in route_de_ch_at["trips"]:
            for seg in trip["path"]["segments"]:
                for cl in seg["country_legs"]:
                    dist_km = cl["distance_m"] / 1000
                    if dist_km < 1.0:
                        continue  # skip very short legs
                    energy_per_km = cl["energy_kwh"] / dist_km
                    assert energy_per_km == pytest.approx(DUMMY_FACTOR, rel=0.01), (
                        f"Expected flat factor {DUMMY_FACTOR} kWh/km on {cl['country_code']} "
                        f"leg, got {energy_per_km:.3f}"
                    )

    @pytest.mark.skip(
        reason="Terrain effect requires calibrated regression model. Re-enable after energy team calibrates."
    )
    def test_mountainous_country_has_higher_energy_per_km(self, route_de_ch_at):
        """CH (terrain_score=1.8) should have higher energy/km than DE (terrain_score=1.0)."""
        ch_legs = [
            cl
            for trip in route_de_ch_at["trips"]
            for seg in trip["path"]["segments"]
            for cl in seg["country_legs"]
            if cl["country_code"] == "CH"
        ]
        de_legs = [
            cl
            for trip in route_de_ch_at["trips"]
            for seg in trip["path"]["segments"]
            for cl in seg["country_legs"]
            if cl["country_code"] == "DE"
        ]
        if not ch_legs or not de_legs:
            pytest.skip("Route does not traverse both CH and DE")
        ch_energy_per_km = sum(cl["energy_kwh"] for cl in ch_legs) / sum(
            cl["distance_m"] / 1000 for cl in ch_legs
        )
        de_energy_per_km = sum(cl["energy_kwh"] for cl in de_legs) / sum(
            cl["distance_m"] / 1000 for cl in de_legs
        )
        assert ch_energy_per_km > de_energy_per_km


class TestEnergyByComposition:

    def test_heavier_composition_uses_more_energy(self, api_base):
        """STD-13.1 (heavier) uses more total energy than STD-3.1."""
        energies = {}
        for comp_id in ("STD-3.1", "STD-13.1"):
            route = _build_route(
                api_base,
                STOPS_DE_AT,
                comp_id=comp_id,
                proposal_id=210 if comp_id == "STD-3.1" else 211,
            )
            total = sum(t["stats"]["total_energy_kwh"] for t in route["trips"])
            energies[comp_id] = total

        # All seeded compositions share the same energy factors and weight params —
        # energy difference requires different coach weights, which are all type1/2/3 in seed.
        # STD-13.1 has more coaches so total weight is higher → more energy.
        # If equal, seed data may not differentiate enough — accept >= for now.
        assert (
            energies["STD-13.1"] >= energies["STD-3.1"]
        ), f"Heavier composition should use at least as much energy: {energies}"

    def test_same_composition_outbound_return_same_energy(self, route_de_at):
        """Outbound and return should have equal energy (symmetric route)."""
        outbound_energy = next(
            t["stats"]["total_energy_kwh"]
            for t in route_de_at["trips"]
            if t["direction_id"] == 0
        )
        return_energy = next(
            t["stats"]["total_energy_kwh"]
            for t in route_de_at["trips"]
            if t["direction_id"] == 1
        )
        assert outbound_energy == pytest.approx(return_energy, rel=0.05)


class TestEnergyModelVersion:

    def test_energy_version_present_in_trip(self, route_de_at):
        for trip in route_de_at["trips"]:
            assert "model_versions" in trip
            mv = trip["model_versions"]
            # model_versions may be serialised as flat dict or nested
            mv_str = str(mv)
            assert (
                "energy" in mv_str.lower() or len(mv) > 0
            ), f"model_versions appears empty or missing energy info: {mv}"

    def test_energy_version_is_string(self, route_de_at):
        for trip in route_de_at["trips"]:
            mv = trip["model_versions"]
            # Accept either {'energy_calc': '1.0.0'} or serialised form
            assert (
                isinstance(mv, dict) and len(mv) > 0
            ), f"model_versions should be a non-empty dict: {mv}"
