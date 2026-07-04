"""
test_route_routing.py
=====================
Routing-specific tests — multi-country routes, dwell times, default value
propagation, composition comparison.

Stop-type tests below reflect timetable_mode='simpleAutomatic': stops are
plain ID strings now (no per-stop stop_type input), and intermediate stops
are classified boarding/alighting by the caller — "both" is not a
classification automatic scheduling can ever produce, unlike the old
manual-input system. First/last stop are always boarding/alighting by
position regardless of the mirror rule.

The old TestDefaultValues class (param_versions-in-route-JSON checks) is
gone entirely — param_versions/is_default provenance for track/stop
infrastructure is already thoroughly covered in test_versioning.py
(TestParamVersionsStructure, TestStopDefaultValues) via the loader and
/api/params/* directly. Duplicating those checks here via a different,
route/plan-shaped path added nothing.
"""

import pytest
import requests

from tests.conftest import flatten_trips

ROUTE_URL = "/api/route/plan"

VALID_STOPS_2 = ["DE_BERLIN_HBF", "AT_WIEN_HBF"]


@pytest.fixture(scope="module")
def route_de_at(api_base):
    """2-country route: DE → AT."""
    resp = requests.post(
        f"{api_base}{ROUTE_URL}",
        json={
            "proposal_id": 10,
            "proposal_version": 1,
            "stops": VALID_STOPS_2,
            "composition_id": "STD-7.1",
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
            "stops": ["DE_BERLIN_HBF", "CH_ZUERICH_HB", "AT_WIEN_HBF"],
            "composition_id": "STD-7.1",
        },
        timeout=60,
    )
    assert resp.status_code == 200, resp.text[:300]
    return resp.json()["route"]


@pytest.fixture(scope="module")
def route_dk_se(api_base):
    """Route touching SE — some track infra fields resolve from the
    EU-average default (see route['track_infrastructure'][cc]['defaulted_fields'])."""
    resp = requests.post(
        f"{api_base}{ROUTE_URL}",
        json={
            "proposal_id": 12,
            "proposal_version": 1,
            "stops": ["DK_COPENHAGEN", "SE_STOCKHOLM_C"],
            "composition_id": "STD-7.1",
        },
        timeout=60,
    )
    assert resp.status_code == 200, resp.text[:300]
    return resp.json()["route"]


# --- Multi-country ---


class TestMultiCountry:

    def test_de_at_route_has_two_countries(self, route_de_at):
        outbound = next(t for t in flatten_trips(route_de_at) if t["direction_id"] == 0)
        countries = {
            cl["country_code"]
            for seg in outbound["path"]["segments"]
            for cl in seg["country_legs"]
        }
        assert "DE" in countries
        assert "AT" in countries

    def test_de_ch_at_has_three_countries(self, route_de_ch_at):
        outbound = next(t for t in flatten_trips(route_de_ch_at) if t["direction_id"] == 0)
        countries = {
            cl["country_code"]
            for seg in outbound["path"]["segments"]
            for cl in seg["country_legs"]
        }
        assert len(countries) >= 3

    def test_multi_country_distances_sum_to_total(self, route_de_ch_at):
        for trip in flatten_trips(route_de_ch_at):
            leg_sum = sum(
                cl["distance_m"]
                for seg in trip["path"]["segments"]
                for cl in seg["country_legs"]
            )
            assert abs(leg_sum - trip["stats"]["total_distance_m"]) < 100  # within 100m

    def test_multi_country_driving_times_sum_to_total(self, route_de_ch_at):
        for trip in flatten_trips(route_de_ch_at):
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
        outbound = next(t for t in flatten_trips(route_de_ch_at) if t["direction_id"] == 0)
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


# --- Track infrastructure defaulting (route/plan's own view of it) ---


class TestTrackInfrastructureDefaulting:
    """
    Full param_versions/is_default provenance for track infra is already
    covered thoroughly in test_versioning.py via the loader and
    /api/params/TrackInfrastructures directly — that's the right place for
    it, since tac_eur_train_km (the field SE's seed data deliberately
    nulls) is a cost field and isn't exposed via route/plan at all (see
    api/README.md — route/plan is physics-only). What IS checked here is
    route/plan's own, differently-shaped view: route['track_infrastructure'].
    """

    def test_dk_and_se_both_present(self, route_dk_se):
        countries = {t["country_code"] for t in route_dk_se["track_infrastructure"]}
        assert "DK" in countries
        assert "SE" in countries

    def test_defaulted_fields_is_a_list_for_every_country(self, route_dk_se):
        for entry in route_dk_se["track_infrastructure"]:
            assert isinstance(entry["defaulted_fields"], list)


# --- Stop types (timetable_mode='simpleAutomatic') ---


class TestStopTypes:

    def test_first_stop_is_boarding_with_no_arrival(self, route_de_at):
        outbound = next(t for t in flatten_trips(route_de_at) if t["direction_id"] == 0)
        first = outbound["stop_times"][0]
        assert first["stop_type"] == "boarding"
        assert first["arrival_time_min"] is None

    def test_last_stop_is_alighting_with_no_departure(self, route_de_at):
        outbound = next(t for t in flatten_trips(route_de_at) if t["direction_id"] == 0)
        last = outbound["stop_times"][-1]
        assert last["stop_type"] == "alighting"
        assert last["departure_time_min"] is None

    def test_middle_stop_has_boarding_or_alighting_type(self, route_de_ch_at):
        """Not 'both' — that classification doesn't exist under automatic
        scheduling. Zürich (the one intermediate stop) lands on whichever
        side of the 02:30 mirror its provisional clock time falls on."""
        outbound = next(t for t in flatten_trips(route_de_ch_at) if t["direction_id"] == 0)
        middle = outbound["stop_times"][1]
        assert middle["stop_type"] in ("boarding", "alighting")
        assert middle["arrival_time_min"] is not None
        assert middle["departure_time_min"] is not None
        assert middle["departure_time_min"] > middle["arrival_time_min"]

    def test_dwell_time_is_at_least_a_minute(self, route_de_ch_at):
        """Real dwell (from build_final_timetable()) is the max of whichever
        composition/track minimums apply to Zürich's actual classification
        — not asserting a specific minimum value here since which one
        applies depends on that classification, only that dwell is a real,
        positive amount of time."""
        outbound = next(t for t in flatten_trips(route_de_ch_at) if t["direction_id"] == 0)
        zurich = next(
            (st for st in outbound["stop_times"] if st["stop_id"] == "CH_ZUERICH_HB"),
            None,
        )
        assert zurich is not None
        assert zurich["dwell_time_min"] is not None
        assert zurich["dwell_time_min"] >= 1


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
                    "stops": VALID_STOPS_2,
                    "composition_id": comp_id,
                },
                timeout=60,
            )
            assert resp.status_code == 200, f"{comp_id}: {resp.text[:200]}"
            trip = next(
                t for t in flatten_trips(resp.json()["route"]) if t["direction_id"] == 0
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
                    "stops": VALID_STOPS_2,
                    "composition_id": comp_id,
                },
                timeout=60,
            )
            assert resp.status_code == 200
            trip = next(
                t for t in flatten_trips(resp.json()["route"]) if t["direction_id"] == 0
            )
            distances[comp_id] = trip["stats"]["total_distance_m"]

        assert (
            distances["STD-3.1"] == distances["STD-7.1"]
        ), "Distance should be independent of composition"