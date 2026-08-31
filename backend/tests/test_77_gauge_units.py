"""
Unit tests for models/route/routing/gauge.py — trip gauge resolution, the
strict/permissive split, and the profile-name contract. No DB, no Docker:
the routed end (a 1524 trip actually routing, a mismatch actually
answering 422 gauge_mismatch) lives in test_78_gauge_api.py against the
live stack.
"""

import pytest

from models.params import StopInfrastructure
from models.route.model import STANDARD_GAUGE_MM, SUPPORTED_GAUGES_MM
from models.route.routing.gauge import (
    GaugeMismatchError,
    resolve_trip_gauge,
    stop_supports_gauge,
)


def _stop(stop_id: str, gauges: list[int] | None) -> StopInfrastructure:
    return StopInfrastructure(
        stop_id=stop_id,
        stop_name=stop_id,
        stop_country_code="XX",
        lat=0.0,
        lon=0.0,
        stop_charge_eur=0.0,
        gauges_mm=gauges,
    )


class TestResolveTripGauge:
    def test_all_standard(self):
        stops = [_stop("berlin", [1435]), _stop("wien", [1435])]
        assert resolve_trip_gauge(stops) == 1435

    def test_all_broad(self):
        stops = [_stop("kyiv", [1520]), _stop("lviv", [1520])]
        assert resolve_trip_gauge(stops) == 1520

    def test_finnish_resolves_to_the_family_representative(self):
        # 1524 folds into the 1520 family (GAUGE_FAMILY_MM): interoperable
        # in practice, tagged separately in OSM.
        stops = [_stop("rovaniemi", [1524]), _stop("helsinki", [1524])]
        assert resolve_trip_gauge(stops) == 1520

    def test_estonian_seam_is_passable(self):
        # The case that forced the family: Tartu is tagged {1520, 1524},
        # Šiauliai {1520} — as separate networks the intersection resolved
        # 1520 while Tartu's platform track was 1524-tagged, and the trip
        # failed to snap at Tartu. One family, one profile, no seam.
        stops = [
            _stop("helsinki", [1524]),
            _stop("tartu", [1520, 1524]),
            _stop("siauliai", [1520]),
        ]
        assert resolve_trip_gauge(stops) == 1520

    def test_dual_gauge_border_stop_prefers_standard(self):
        # Kaunas carries both; with Warszawa the intersection is {1435}.
        stops = [_stop("kaunas", [1435, 1520]), _stop("warszawa", [1435])]
        assert resolve_trip_gauge(stops) == 1435

    def test_tie_prefers_standard(self):
        # A trip entirely over dual-gauge stops is a standard-gauge trip.
        stops = [_stop("kaunas", [1435, 1520]), _stop("mockava", [1435, 1520])]
        assert resolve_trip_gauge(stops) == STANDARD_GAUGE_MM

    def test_unknown_does_not_constrain(self):
        # The catalog's gauge-NULL stops include Ukrainian ones — a NULL
        # must ride on its co-stops' gauge, never default to 1435.
        stops = [_stop("kyiv", [1520]), _stop("kramatorsk", None)]
        assert resolve_trip_gauge(stops) == 1520

    def test_empty_list_counts_as_unknown(self):
        stops = [_stop("kyiv", [1520]), _stop("odd", [])]
        assert resolve_trip_gauge(stops) == 1520

    def test_all_unknown_falls_back_to_standard(self):
        # route_geometry()'s synthetic ONTD stops carry no gauges at all.
        stops = [_stop("a", None), _stop("b", None)]
        assert resolve_trip_gauge(stops) == STANDARD_GAUGE_MM

    def test_mismatch_raises_with_every_stop_listed(self):
        stops = [
            _stop("kyiv", [1520]),
            _stop("kramatorsk", None),
            _stop("warszawa", [1435]),
        ]
        with pytest.raises(GaugeMismatchError) as excinfo:
            resolve_trip_gauge(stops)
        conflicting = excinfo.value.conflicting_stops
        # The full picture, unknown included — which side is "wrong" is
        # the user's call, and the frontend marks stops from this dict.
        assert conflicting == {
            "kyiv": [1520],
            "kramatorsk": None,
            "warszawa": [1435],
        }
        assert "kyiv" in str(excinfo.value)
        assert "1520" in str(excinfo.value)

    def test_mismatch_is_a_value_error(self):
        # An unaware caller must still land in the generic 422
        # domain_error arm, not a 500.
        stops = [_stop("kyiv", [1520]), _stop("warszawa", [1435])]
        with pytest.raises(ValueError):
            resolve_trip_gauge(stops)

    def test_family_member_never_reaches_profile_selection(self):
        from models.route.model import GAUGE_FAMILY_MM

        # Every family member maps to a supported representative, so no
        # resolved gauge can name a profile that does not exist.
        for member, representative in GAUGE_FAMILY_MM.items():
            assert member not in SUPPORTED_GAUGES_MM
            assert representative in SUPPORTED_GAUGES_MM

    def test_unsupported_resolved_gauge_raises_plain_value_error(self):
        # Catalog data naming a gauge no profile exists for is a data
        # defect, not a user mismatch — different error, no
        # conflicting_stops payload.
        stops = [_stop("a", [1000]), _stop("b", [1000])]
        with pytest.raises(ValueError) as excinfo:
            resolve_trip_gauge(stops)
        assert not isinstance(excinfo.value, GaugeMismatchError)
        assert "1000" in str(excinfo.value)


class TestStopSupportsGauge:
    def test_supporting(self):
        assert stop_supports_gauge(_stop("madrid", [1435, 1668]), 1668)

    def test_not_supporting(self):
        assert not stop_supports_gauge(_stop("madrid", [1668]), 1435)

    def test_family_member_supports_the_representative(self):
        # A Finnish stop tagged {1524} must pass the auto-stop filter of a
        # 1520-family trip.
        assert stop_supports_gauge(_stop("tampere", [1524]), 1520)

    def test_unknown_is_strictly_false(self):
        # The auto-stop filter must never add a gauge-unknown stop: the
        # trip resolves permissively, additions are judged strictly.
        assert not stop_supports_gauge(_stop("kramatorsk", None), 1435)
        assert not stop_supports_gauge(_stop("odd", []), 1435)


class TestContracts:
    def test_supported_gauges_cover_the_profile_set(self):
        # Mirror of docker/config.yml's four profiles — the naming
        # contract rail_router.profile_for_gauge() builds on. 1524 is
        # deliberately absent: it is a family member, not a profile.
        assert SUPPORTED_GAUGES_MM == (1435, 1520, 1600, 1668)
        assert STANDARD_GAUGE_MM in SUPPORTED_GAUGES_MM

    def test_profile_names(self):
        from models.route.routing.rail_router import CountryIndex, RailRouter

        router = RailRouter(CountryIndex([]))
        base = router.profile
        assert router.profile_for_gauge(STANDARD_GAUGE_MM) == base
        for gauge in SUPPORTED_GAUGES_MM:
            if gauge == STANDARD_GAUGE_MM:
                continue
            assert router.profile_for_gauge(gauge) == f"{base}_{gauge}"
