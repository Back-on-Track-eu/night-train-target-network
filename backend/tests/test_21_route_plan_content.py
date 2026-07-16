"""
test_21_route_plan_content.py
=============================
Content-logic tests for POST /api/route/plan — verifies the numbers a route
carries are internally consistent and match the models that produced them,
using only data present in the response.

Covers:
  - Country attribution: shares sum to 1, expected countries present,
    per-country km sums to trip distance
  - Route geometry sanity: direct vs detour distance, outbound/return symmetry
  - Timetable math: arrival = departure + driving + dynamics + buffer, dwell at
    intermediate stops
  - Track infra defaulting as seen by route/plan (SE)
  - Energy model: flat 28 kWh/km dummy factor, composition-independent
    (REPLACE the flat-factor tests once the real regression model is calibrated)
  - Parkings/shuntings derivation
"""

import pytest

from tests.conftest import STOPS_BERLIN_WIEN
from tests.helpers import (
    all_trips,
    build_route,
    country_km,
    route_countries,
    stop_times,
    trip_by_direction,
    trip_distance_km,
    trip_energy_kwh,
)

# Current dummy energy model: flat factor, see models/energy/calc_energy_consumption.py.
DUMMY_KWH_PER_KM = 28.0


# =============================================================================
# Country attribution
# =============================================================================


class TestCountryAttribution:
    def test_shares_sum_to_one_per_segment(self, route_berlin_zuerich_wien):
        """country_distance_shares and country_time_shares each sum to 1.0
        on every segment — the allocation basis for TAC/energy costing."""
        for trip in all_trips(route_berlin_zuerich_wien):
            for seg in trip["segments"]:
                assert sum(seg["country_distance_shares"].values()) == pytest.approx(
                    1.0, abs=1e-3
                )
                assert sum(seg["country_time_shares"].values()) == pytest.approx(
                    1.0, abs=1e-3
                )

    def test_berlin_wien_crosses_de_and_at(self, route_berlin_wien):
        """Berlin → Wien touches at least DE and AT."""
        countries = route_countries(route_berlin_wien)
        assert {"DE", "AT"} <= countries

    def test_via_zuerich_crosses_three_countries(self, route_berlin_zuerich_wien):
        """Berlin → Zürich → Wien touches at least DE, CH, AT."""
        countries = route_countries(route_berlin_zuerich_wien)
        assert {"DE", "CH", "AT"} <= countries

    def test_country_km_sums_to_trip_distance(self, route_berlin_zuerich_wien):
        """Per-country km (distance × share) sums back to the trip's total
        distance — no distance is lost or double-counted in attribution."""
        for trip in all_trips(route_berlin_zuerich_wien):
            attributed = sum(country_km(trip).values())
            assert attributed == pytest.approx(trip_distance_km(trip), rel=1e-3)

    def test_track_infrastructure_matches_traversed_countries(
        self, route_berlin_zuerich_wien
    ):
        """route['track_infrastructure'] lists every country the segments
        touch (incl. transit-only), and nothing beyond segment + stop
        countries — mirrors Route.countries exactly."""
        route = route_berlin_zuerich_wien
        listed = {t["country_code"] for t in route["track_infrastructure"]}
        traversed = route_countries(route)
        stop_countries = {
            st["country_code"] for trip in all_trips(route) for st in stop_times(trip)
        }
        assert traversed <= listed
        assert listed <= traversed | stop_countries


# =============================================================================
# Route geometry sanity
# =============================================================================


class TestRouteGeometry:
    def test_outbound_and_return_distances_symmetric(self, route_berlin_wien):
        """Outbound and return follow (near-)identical rail paths — total
        distances agree within 5%."""
        out_km = trip_distance_km(trip_by_direction(route_berlin_wien, 0))
        ret_km = trip_distance_km(trip_by_direction(route_berlin_wien, 1))
        assert out_km == pytest.approx(ret_km, rel=0.05)

    def test_detour_not_shorter_than_direct(
        self, route_berlin_wien, route_berlin_zuerich_wien
    ):
        """Berlin → Wien via Zürich cannot be shorter than the direct routing
        — a violation would mean the direct route wasn't actually optimised."""
        direct_km = trip_distance_km(trip_by_direction(route_berlin_wien, 0))
        detour_km = trip_distance_km(trip_by_direction(route_berlin_zuerich_wien, 0))
        assert detour_km >= direct_km

    def test_distance_independent_of_composition(self, api_base):
        """Same stops, different compositions with identical routing flags
        (both STD, hsr_allowed=True) → identical route distance."""
        distances = {}
        for i, comp_id in enumerate(("STD-3.1", "STD-7.1")):
            route = build_route(
                api_base,
                STOPS_BERLIN_WIEN,
                comp_id,
                proposal_id=21,
                proposal_version=i + 1,
            )
            distances[comp_id] = trip_distance_km(trip_by_direction(route, 0))
        assert distances["STD-3.1"] == distances["STD-7.1"]


# =============================================================================
# Timetable math
# =============================================================================


class TestTimetableMath:
    def test_arrival_equals_departure_plus_driving_plus_buffer(
        self, route_berlin_dresden_wien
    ):
        """For every segment: to_stop.arrival = from_stop.departure +
        driving_time + buffer_time — the exact build_final_timetable() math."""
        for trip in all_trips(route_berlin_dresden_wien):
            for seg in trip["segments"]:
                dep = seg["from_stop"]["departure_time_min"]
                arr = seg["to_stop"]["arrival_time_min"]
                assert (
                    arr
                    == dep
                    + seg["driving_time_min"]
                    + seg["dynamics_time_min"]
                    + seg["buffer_time_min"]
                )

    def test_intermediate_dwell_at_least_one_minute(self, route_berlin_dresden_wien):
        """Dresden (the intermediate stop) has a real positive dwell —
        departure strictly after arrival. The exact minimum depends on which
        boarding/alighting minimum applies, so only positivity is asserted."""
        for trip in all_trips(route_berlin_dresden_wien):
            dresden = next(
                s for s in stop_times(trip) if s["stop_id"] == "DE_DRESDEN_HBF"
            )
            assert dresden["dwell_time_min"] is not None
            assert dresden["dwell_time_min"] >= 1

    def test_buffer_time_non_negative(self, route_berlin_dresden_wien):
        """Buffer time (schedule padding) is never negative."""
        for trip in all_trips(route_berlin_dresden_wien):
            for seg in trip["segments"]:
                assert seg["buffer_time_min"] >= 0
                assert seg["dynamics_time_min"] >= 0


# =============================================================================
# Track infrastructure defaulting as seen by route/plan
# =============================================================================


class TestTrackInfraDefaulting:
    def test_se_route_lists_dk_and_se(self, route_copenhagen_stockholm):
        """Copenhagen → Stockholm lists both DK and SE track infra entries."""
        countries = {
            t["country_code"]
            for t in route_copenhagen_stockholm["track_infrastructure"]
        }
        assert {"DK", "SE"} <= countries

    def test_defaulted_fields_only_contain_exposed_fields(
        self, route_copenhagen_stockholm
    ):
        """defaulted_fields entries are restricted to the physics fields the
        response actually shows — never a cost field like tac_eur_train_km."""
        exposed = {
            "hsr_allowed",
            "min_boarding_time_min",
            "min_alighting_time_min",
            "terrain_score",
            "terrain_category",
            "buffer_quota_per",
        }
        for entry in route_copenhagen_stockholm["track_infrastructure"]:
            assert set(entry["defaulted_fields"]) <= exposed, (
                f"{entry['country_code']}: unexpected defaulted field"
            )


# =============================================================================
# Energy model (current dummy implementation)
# =============================================================================


class TestEnergyModel:
    """Pins the DUMMY flat-factor model (28 kWh/km, ignoring weight/speed/
    terrain). Both tests here must be REPLACED when the calibrated regression
    model lands — they exist to fail loudly the moment energy semantics change
    without the suite being updated."""

    def test_energy_is_flat_factor_times_distance(self, route_berlin_zuerich_wien):
        """Every segment's energy equals exactly 28 kWh/km × distance."""
        for trip in all_trips(route_berlin_zuerich_wien):
            for seg in trip["segments"]:
                expected = DUMMY_KWH_PER_KM * seg["distance_m"] / 1000.0
                assert seg["energy_kwh"] == pytest.approx(expected, rel=1e-6)

    def test_energy_independent_of_composition(self, api_base):
        """The dummy model ignores composition weight entirely — same stops,
        different compositions → identical total energy."""
        energies = {}
        for i, comp_id in enumerate(("STD-3.1", "STD-13.1")):
            route = build_route(
                api_base,
                STOPS_BERLIN_WIEN,
                comp_id,
                proposal_id=22,
                proposal_version=i + 1,
            )
            energies[comp_id] = sum(trip_energy_kwh(t) for t in all_trips(route))
        assert energies["STD-3.1"] == pytest.approx(energies["STD-13.1"], rel=1e-6)


# =============================================================================
# Parkings and shuntings
# =============================================================================


class TestParkingsAndShuntings:
    def test_two_shuntings_per_trip(self, route_berlin_wien):
        """Current rule: 2 shuntings per trip (one per trip end/start), no
        deduplication → one round-trip pair produces 4 shuntings."""
        n_trips = len(all_trips(route_berlin_wien))
        assert len(route_berlin_wien["shuntings"]) == 2 * n_trips

    def test_shuntings_at_trip_terminals(self, route_berlin_wien):
        """Every shunting sits at a terminal stop of the trip it belongs to."""
        terminals_by_trip = {
            trip["trip_id"]: {
                stop_times(trip)[0]["stop_id"],
                stop_times(trip)[-1]["stop_id"],
            }
            for trip in all_trips(route_berlin_wien)
        }
        for s in route_berlin_wien["shuntings"]:
            assert s["stop_id"] in terminals_by_trip[s["trip_id"]], (
                f"Shunting at non-terminal stop {s['stop_id']} for {s['trip_id']}"
            )

    def test_parkings_deduplicated_by_stop(self, route_berlin_wien):
        """Parkings exist and are deduplicated by stop_id, each listing the
        trips whose formation parks there."""
        parkings = route_berlin_wien["parkings"]
        assert len(parkings) > 0
        stop_ids = [p["stop_id"] for p in parkings]
        assert len(stop_ids) == len(set(stop_ids)), "Duplicate parking stop_ids"
        for p in parkings:
            assert len(p["trip_ids"]) >= 1
