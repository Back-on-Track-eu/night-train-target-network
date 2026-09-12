"""
test_21_schedule_and_trainsets.py
=================================
ROUTE_BUILDER 0.9.35: the per-month schedule and the cycle-time trainset
rule, exercised in-process on the domain objects — no database, no router.
The request-boundary half (validate_schedule / normalize_schedule) is here
too, since it is pure.
"""

from types import MethodType, SimpleNamespace as NS

import pytest

from api.helpers.member_compute import normalize_schedule, validate_schedule
from models.route.route import Schedule, TripPair
from models.route.trip import Segment, Stop, StopType, Trip
from models.route.timetable import (
    always_daily_schedule,
    legacy_seasonal_schedules,
    schedule_from_dict,
)


def _pair(out_dep, out_arr, ret_dep, ret_arr, avail=0.87):
    """A TripPair stand-in carrying only what the fleet rule reads: each
    trip's departure_time_min / arrival_time_min — the properties the real
    Trip derives from its first and last segment — and the composition's
    availability."""

    # Same surface the real Trip exposes: its terminal times as properties.
    def trip(dep, arr):
        return NS(departure_time_min=dep, arrival_time_min=arr)

    p = NS(
        outbound=trip(out_dep, out_arr),
        return_trip=trip(ret_dep, ret_arr),
        composition=NS(coach_avail_per=avail, comp_id="X"),
    )
    for name in ("cycle_days", "trainsets", "composition_count"):
        setattr(p, name, MethodType(getattr(TripPair, name), p))
    return p


def _flat(days, turnaround=180):
    return Schedule({m: days for m in range(1, 13)}, turnaround)


H = 60
DAY = 24 * H


class TestSchedule:
    def test_always_daily_is_every_day_of_the_year(self):
        s = always_daily_schedule(180)
        assert s.operating_days_per_year == 366  # the evaluation year is a leap year
        assert s.peak_days_per_week == 7 and s.is_daily_any_season

    def test_summer_only_counts_its_months(self):
        s = Schedule({m: (7 if 4 <= m <= 9 else 0) for m in range(1, 13)})
        assert s.operating_days_per_year == pytest.approx(183)
        assert s.is_operating

    def test_missing_month_is_rejected(self):
        with pytest.raises(ValueError):
            Schedule({m: 7 for m in range(1, 12)})

    def test_legacy_shape_round_trips_through_the_months(self):
        s = Schedule({m: (7 if 4 <= m <= 9 else 3) for m in range(1, 13)})
        legacy = legacy_seasonal_schedules(s)
        assert legacy == [
            {"season": "summer", "frequency": "daily"},
            {"season": "winter", "frequency": "three_per_week"},
        ]
        back = schedule_from_dict({"seasonal_schedules": legacy})
        assert back.days_per_week(7) == 7 and back.days_per_week(1) == 3

    def test_month_map_wins_over_legacy_block(self):
        s = schedule_from_dict(
            {
                "days_per_week_by_month": {str(m): 5 for m in range(1, 13)},
                "seasonal_schedules": [{"season": "summer", "frequency": "daily"}],
                "min_turnaround_min": 240,
            }
        )
        assert s.days_per_week(6) == 5 and s.min_turnaround_min == 240


class TestTrainsets:
    # Depart 20:00, arrive 08:00 next morning, both directions: the normal
    # night train, a two-day cycle.
    night = _pair(20 * H, DAY + 8 * H, 20 * H, DAY + 8 * H)
    # Outbound arrives 18:00; the return leaves 20:00 — two hours, under a
    # three-hour minimum, so the rake waits for tomorrow's slot.
    tight = _pair(20 * H, DAY + 18 * H, 20 * H, DAY + 8 * H)

    def test_night_train_cycles_in_two_days(self):
        assert self.night.cycle_days(180) == 2

    def test_short_turnaround_costs_a_day(self):
        assert self.tight.cycle_days(180) == 3
        assert self.tight.cycle_days(60) == 2  # a one-hour minimum fits the slot

    @pytest.mark.parametrize(
        "days_per_week, expected", [(7, 2), (4, 2), (3, 1), (1, 1), (0, 0)]
    )
    def test_fleet_follows_frequency(self, days_per_week, expected):
        assert self.night.trainsets(_flat(days_per_week)) == expected

    def test_tight_turnaround_needs_a_third_rake_daily(self):
        assert self.tight.trainsets(_flat(7)) == 3

    def test_fleet_is_sized_to_the_peak_month(self):
        one_busy_month = Schedule({m: (7 if m == 8 else 3) for m in range(1, 13)})
        assert self.night.trainsets(one_busy_month) == 2

    def test_cost_basis_divides_the_physical_count_by_availability(self):
        assert self.night.composition_count(_flat(7))["X"] == pytest.approx(2 / 0.87)


class TestRequestBoundary:
    def test_custom_needs_a_complete_month_map(self):
        assert validate_schedule("custom", None)
        assert validate_schedule("custom", {str(m): 7 for m in range(1, 12)})
        assert validate_schedule("custom", {str(m): 8 for m in range(1, 13)})
        assert validate_schedule("custom", {str(m): 0 for m in range(1, 13)})
        assert validate_schedule("custom", {str(m): 7 for m in range(1, 13)}) == []

    def test_schedule_is_rejected_outside_custom(self):
        assert validate_schedule("alwaysDaily", {str(m): 7 for m in range(1, 13)})
        assert validate_schedule("alwaysDaily", None) == []

    def test_normalisation_makes_spellings_hash_equal(self):
        a = normalize_schedule("custom", {m: 7 for m in range(1, 13)})
        b = normalize_schedule("custom", {str(m): 7 for m in reversed(range(1, 13))})
        assert a == b and list(a) == [str(m) for m in range(1, 13)]
        assert normalize_schedule("alwaysDaily", {"1": 7}) is None


class TestAgainstRealObjects:
    """The stub above mirrors Trip's surface; this pins that it does. The
    first cut of cycle_days() read a `stops` list the real Trip does not
    have and only the stub did — every evaluation raised, and the stub
    tests passed. One real pair is cheap insurance."""

    @staticmethod
    def _stop(sid, arr, dep):
        return Stop(
            stop_id=sid,
            stop_name=sid,
            country_code="DE",
            lat=52.0,
            lon=13.0,
            stop_type=list(StopType)[0],
            arrival_time_min=arr,
            departure_time_min=dep,
            auto_added=False,
        )

    @classmethod
    def _trip(cls, tid, direction, dep, arr):
        a, b = cls._stop("A", None, dep), cls._stop("B", arr, None)
        return Trip(
            trip_id=tid,
            direction=direction,
            segments=[
                Segment(
                    from_stop=a,
                    to_stop=b,
                    geometry=[[13.0, 52.0], [14.0, 52.0]],
                    distance_m=600_000,
                    driving_time_min=arr - dep,
                    dynamics_time_min=0,
                    buffer_time_min=0,
                    energy_kwh=0.0,
                    country_distance_shares={"DE": 1.0},
                    country_time_shares={"DE": 1.0},
                )
            ],
        )

    def test_night_train_on_real_dataclasses(self):
        pair = TripPair(
            outbound=self._trip("T0", 0, 20 * H, DAY + 8 * H),
            return_trip=self._trip("T1", 1, 20 * H, DAY + 8 * H),
            composition=NS(coach_avail_per=0.87, comp_id="X"),
            od_pairs=[],
        )
        assert pair.cycle_days(180) == 2
        assert pair.trainsets(_flat(7)) == 2
        assert pair.composition_count(_flat(7))["X"] == pytest.approx(2 / 0.87)


class TestFares:
    """CALC 0.9.27 — fares_eur_per_km at the request boundary. Pure; the
    evaluation-level effect (a dearer sleeper raises revenue) is covered by
    test_39's cache-miss case and the integration suite."""

    def test_partial_override_resolves_against_the_defaults(self):
        from api.helpers.member_compute import normalize_fares
        from models.demand.model import STOPGAP_FARE_PER_KM_BY_CLASS

        out = normalize_fares({"Sleeper": 0.25})
        assert out["Sleeper"] == 0.25
        assert out["Seat"] == STOPGAP_FARE_PER_KM_BY_CLASS["Seat"]
        assert list(out) == ["Seat", "Couchette", "Sleeper", "Capsule"]

    def test_spellings_that_mean_the_same_hash_the_same(self):
        from api.helpers.member_compute import normalize_fares

        assert normalize_fares(None) == normalize_fares(
            {"Seat": 0.10, "Couchette": 0.13, "Sleeper": 0.18, "Capsule": 0.12}
        )

    def test_validation(self):
        from api.helpers.member_compute import validate_fares

        assert validate_fares(None) == []
        assert validate_fares({"Seat": 0.12}) == []
        assert validate_fares({"Catering": 1.0})  # not a fare class
        assert validate_fares({"Seat": -0.1})
        assert validate_fares({"Seat": True})
        assert validate_fares("0.1")

    def test_catering_cannot_be_priced(self):
        from models.demand.model import resolve_fares

        assert resolve_fares({"Catering": 9.0})["Catering"] == 0.0


class TestSummarySupply:
    """CALC 0.9.28 — the summary sizes the fleet from the route DICT with the
    same rule TripPair uses, for both trip shapes it can be handed."""

    @staticmethod
    def _route(min_turnaround=180, shape="segments"):
        def stop(dep=None, arr=None):
            return {"stop_id": "x", "departure_time_min": dep, "arrival_time_min": arr}

        # trip_id is on every real route dict; the supply KPIs only reach for
        # it once a pair carries demand, which is why it went unnoticed until
        # the passenger count below.
        def trip(dep, arr, trip_id="t"):
            if shape == "stops":
                return {
                    "trip_id": trip_id,
                    "stops": [stop(dep=dep), stop(arr=arr)],
                    "segments": [],
                    "od_pairs": [],
                }
            return {
                "trip_id": trip_id,
                "segments": [
                    {
                        "from_stop": stop(dep=dep),
                        "to_stop": stop(arr=arr),
                        "distance_m": 600_000,
                    }
                ],
                "od_pairs": [],
            }

        return {
            "schedule": {
                "days_per_week_by_month": {str(m): 7 for m in range(1, 13)},
                "min_turnaround_min": min_turnaround,
            },
            "trip_pairs": [
                {
                    "composition": {"places_by_class": {"Seat": 100}},
                    "outbound": trip(20 * H, DAY + 8 * H, "t"),
                    "return_trip": trip(20 * H, DAY + 8 * H, "t_return"),
                }
            ],
        }

    def test_departures_and_fleet_from_the_dict(self):
        from models.evaluation.summary import _supply_kpis

        s = _supply_kpis(self._route())
        assert s["operating_days_per_year"] == 366
        assert s["departures_per_year"] == 732
        assert s["trainsets_physical"] == 2

    def test_pure_rule_matches_the_pair_method(self):
        from models.route.route import cycle_days_between, trainsets_for_cycle

        assert cycle_days_between(20 * H, DAY + 8 * H, 20 * H, DAY + 8 * H, 180) == 2
        assert cycle_days_between(20 * H, DAY + 18 * H, 20 * H, DAY + 8 * H, 180) == 3
        assert trainsets_for_cycle(3, _flat(7)) == 3

    def test_passengers_are_the_places_actually_sold(self):
        """CALC 0.9.29 — the base the catering contribution multiplies.
        Counted over every OD pair, whatever its ride range resolves to."""
        from models.evaluation.summary import _supply_kpis

        route = self._route()
        route["trip_pairs"][0]["od_pairs"] = [
            {
                "trip_id": "t",
                "origin_stop_id": "x",
                "destination_stop_id": "y",
                "places_sold": 1200,
            },
            {
                "trip_id": "t",
                "origin_stop_id": "x",
                "destination_stop_id": "y",
                "places_sold": 800,
            },
        ]
        assert _supply_kpis(route)["passengers_per_year"] == 2000

    def test_no_demand_is_no_passengers(self):
        from models.evaluation.summary import _supply_kpis

        assert _supply_kpis(self._route())["passengers_per_year"] == 0


class TestCatering:
    """CALC 0.9.29 — the signed net contribution per passenger, at the
    request boundary. The arithmetic on a real route is test_30's."""

    def test_defaults_are_the_demand_model_standard_values(self):
        from api.helpers.member_compute import normalize_catering
        from models.demand.model import STOPGAP_CATERING_EUR_PER_PAX_BY_CLASS

        assert normalize_catering(None) == {
            k: round(v, 2) for k, v in STOPGAP_CATERING_EUR_PER_PAX_BY_CLASS.items()
        }

    def test_an_omitted_field_and_its_default_hash_alike(self):
        from api.helpers.member_compute import normalize_catering
        from models.demand.model import STOPGAP_CATERING_EUR_PER_PAX_BY_CLASS

        assert normalize_catering(
            dict(STOPGAP_CATERING_EUR_PER_PAX_BY_CLASS)
        ) == normalize_catering(None)

    def test_a_partial_override_leaves_the_other_classes_alone(self):
        from api.helpers.member_compute import normalize_catering
        from models.demand.model import STOPGAP_CATERING_EUR_PER_PAX_BY_CLASS

        resolved = normalize_catering({"Sleeper": -0.80})
        assert resolved["Sleeper"] == -0.80
        assert resolved["Seat"] == round(
            STOPGAP_CATERING_EUR_PER_PAX_BY_CLASS["Seat"], 2
        )

    def test_negative_catering_is_accepted_and_kept(self):
        """A restaurant carried by the tickets it helps sell is the usual
        night-train case, not an input error."""
        from api.helpers.member_compute import normalize_catering, validate_catering

        assert validate_catering({"Seat": -0.80}) == []
        assert normalize_catering({"Seat": -0.80})["Seat"] == -0.80

    def test_services_and_fixed_fares_may_not_be_negative(self):
        """Nobody is paid to travel, and nobody is paid to bring a bike —
        only catering is signed."""
        from api.helpers.member_compute import validate_fares_per_pax, validate_services

        assert validate_services({"Seat": 2.0}) == []
        assert validate_services({"Seat": -2.0})
        assert validate_fares_per_pax({"Seat": 8.0}) == []
        assert validate_fares_per_pax({"Seat": -8.0})

    def test_validation_rejects_the_wrong_shape(self):
        from api.helpers.member_compute import validate_catering, validate_services

        assert validate_catering(None) == []
        assert validate_catering({"Seat": 0}) == []
        assert validate_catering({"Seat": True})  # bool is not a price
        assert validate_catering({"Lounge": 1.2})  # not a fare class
        assert validate_services("2.00")

    def test_the_old_scalar_shape_is_rejected_by_name(self):
        """catering_eur_per_pax was one number for the whole train until
        CALC 0.9.30. A stored request carrying that shape should be told
        what changed, not fail as a bare type error."""
        from api.helpers.member_compute import validate_catering

        errors = validate_catering(1.20)
        assert errors and "object of class_main" in errors[0]

    def test_all_three_are_part_of_the_family_key(self):
        """A different tariff is a different family — the numbers move, so
        the document must not be reused."""
        from models.family.key import REQUEST_KEY_FIELDS

        for field in (
            "fares_eur_per_pax",
            "services_eur_per_pax",
            "catering_eur_per_pax",
        ):
            assert field in REQUEST_KEY_FIELDS
