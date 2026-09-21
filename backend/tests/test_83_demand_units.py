"""
test_83_demand_units.py
=======================
DEMAND 0.1.0 (docs/2026-09-18_manual_demand_guide.md), in-process on the
domain objects — no database, no router. The reference values of the
guide's §3 (Berlin – Verona, 9 stops, 17 sellable pairs, Medium, 3 days a
week, even spread, D31 tariff) are reproduced to the cent, the findings
that came out of the sketch are pinned, and the request boundary
(validate_demand / normalize_demand) is covered because it is pure.

The same cases are written to tests/fixtures/demand_reference.json by
test_fixture_is_current; the frontend's parity tests
(frontend/src/lib/demandAllocation.test.ts, odMatrix.test.ts) read that
file, so the two ports of the sketch cannot drift apart.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.helpers.member_compute import (
    demand_inputs,
    normalize_demand,
    validate_demand,
)
from models.demand.groups import allocate, split_by_group
from models.demand.model import (
    CATERING_EUR_PER_PAX_BY_CLASS,
    DEFAULT_GROUP_SHARES_PCT,
    DEMAND_LEVELS,
    FARE_PER_KM_BY_CLASS,
    FARE_PER_PAX_BY_CLASS,
    GROUP_ORDER,
    SERVICES_EUR_PER_PAX_BY_CLASS,
)
from models.demand.od_matrix import (
    SellablePair,
    average_distance_km,
    drop_stale_pins,
    od_shares,
    pin_pair,
    preset_weights,
    sellable_pairs,
)
from models.demand.sources import air_share, split_sources
from models.demand.distribute import DemandInputs, distribute_demand
from models.family.key import REQUEST_KEY_FIELDS, family_key
from models.route.route import Route, Schedule, TripPair
from models.route.trip import Segment, Stop, StopType, Trip
from types import SimpleNamespace as NS

FIXTURE = Path(__file__).parent / "fixtures" / "demand_reference.json"

# The sketch's compositions (COMPOSITION_CATALOG_OVERVIEW_2026-09-06).
COMPS = {
    "NEW-BAL-7": {"Seat": 96, "Couchette": 40, "Sleeper": 40, "Capsule": 84},
    "REF-POD-14": {"Seat": 0, "Couchette": 0, "Sleeper": 230, "Capsule": 528},
    "NEW-BAL-14": {"Seat": 192, "Couchette": 80, "Sleeper": 80, "Capsule": 168},
}
# Berlin – Verona: cumulative km and stop type (B boards, A alights, X
# both, N night — sells nothing).
STOPS = [
    ("Berlin", 0, "B"),
    ("Leipzig", 190, "B"),
    ("Nürnberg", 470, "B"),
    ("München", 640, "N"),
    ("Rosenheim", 705, "N"),
    ("Kufstein", 745, "X"),
    ("Innsbruck", 820, "X"),
    ("Bolzano", 940, "A"),
    ("Verona", 1080, "A"),
]
DAYS_IN_YEAR = 366
FREQ = 3
OPERATING_DAYS = DAYS_IN_YEAR * FREQ / 7
DEPARTURES = OPERATING_DAYS * 2
TOTAL = DEMAND_LEVELS["medium"]


def _stop(name, km, kind):
    stop_type = {
        "B": StopType.BOARDING,
        "A": StopType.ALIGHTING,
        "X": StopType.BOTH,
        "N": StopType.NIGHT,
    }[kind]
    return Stop(
        stop_id=name,
        stop_name=name,
        country_code="DE",
        lat=50.0,
        lon=10.0,
        stop_type=stop_type,
        arrival_time_min=None,
        departure_time_min=None,
        auto_added=False,
    )


def berlin_verona() -> Trip:
    stops = [_stop(*s) for s in STOPS]
    segments = [
        Segment(
            from_stop=stops[i],
            to_stop=stops[i + 1],
            geometry=[[10.0, 50.0], [11.0, 50.0]],
            distance_m=(STOPS[i + 1][1] - STOPS[i][1]) * 1000,
            driving_time_min=60,
            dynamics_time_min=0,
            buffer_time_min=0,
            energy_kwh=0.0,
            country_distance_shares={"DE": 1.0},
            country_time_shares={"DE": 1.0},
        )
        for i in range(len(stops) - 1)
    ]
    return Trip(trip_id="T1", direction="outbound", segments=segments)


def verona_berlin() -> Trip:
    """The return trip: the same stops reversed, boarding and alighting
    roles swapped, so the outbound's matrix mirrors onto it exactly."""
    flip = {"B": "A", "A": "B", "X": "X", "N": "N"}
    rev = list(reversed(STOPS))
    stops = [_stop(name, 0, flip[kind]) for name, _, kind in rev]
    total = STOPS[-1][1]
    km = [total - k for _, k, _ in rev]
    segments = [
        Segment(
            from_stop=stops[i],
            to_stop=stops[i + 1],
            geometry=[[10.0, 50.0], [11.0, 50.0]],
            distance_m=(km[i + 1] - km[i]) * 1000,
            driving_time_min=60,
            dynamics_time_min=0,
            buffer_time_min=0,
            energy_kwh=0.0,
            country_distance_shares={"DE": 1.0},
            country_time_shares={"DE": 1.0},
        )
        for i in range(len(stops) - 1)
    ]
    return Trip(trip_id="T2", direction="return", segments=segments)


def route_with(comp_id: str) -> Route:
    """A Route at the reference frequency carrying one trip pair on the
    named composition — the domain object distribute_demand() takes."""
    composition = NS(
        comp_id=comp_id,
        places_by_class=dict(COMPS[comp_id]),
        operator_id="OP",
        coach_avail_per=0.9,
    )
    pair = TripPair(
        outbound=berlin_verona(),
        return_trip=verona_berlin(),
        composition=composition,
        od_pairs=[],
    )
    return Route._create(
        route_id="R1",
        schedule=Schedule({m: FREQ for m in range(1, 13)}),
        trip_pairs=[pair],
        parkings=[],
        shuntings=[],
    )


def per_trip_groups() -> dict[str, float]:
    return split_by_group(TOTAL / DEPARTURES, DEFAULT_GROUP_SHARES_PCT)


# =============================================================================
# The allocation rule (D14–D19) against the reference table
# =============================================================================


class TestAllocation:
    def test_demand_per_departure(self):
        g = per_trip_groups()
        assert sum(g.values()) == pytest.approx(TOTAL / DEPARTURES)
        assert sum(g.values()) == pytest.approx(637.52, abs=0.01)
        assert g["comfort"] == pytest.approx(318.76, abs=0.01)
        assert g["business"] == pytest.approx(31.88, abs=0.01)

    def test_new_bal_7_by_class(self):
        a = allocate(COMPS["NEW-BAL-7"], per_trip_groups())
        assert a.by_class == pytest.approx(
            {"Seat": 96, "Couchette": 40, "Sleeper": 40, "Capsule": 84}
        )
        assert a.served == pytest.approx(260)
        assert a.not_served == pytest.approx(377.52, abs=0.01)

    def test_new_bal_7_by_group(self):
        a = allocate(COMPS["NEW-BAL-7"], per_trip_groups())
        b = a.by_group_by_class
        assert b["comfort"]["Couchette"] == pytest.approx(35.38, abs=0.01)
        assert b["comfort"]["Sleeper"] == pytest.approx(40)
        assert b["comfort"]["Capsule"] == pytest.approx(84)
        assert b["group"]["Seat"] == pytest.approx(75.07, abs=0.01)
        assert b["group"]["Couchette"] == pytest.approx(4.62, abs=0.01)
        assert b["budget"]["Seat"] == pytest.approx(20.93, abs=0.01)
        assert sum(b["senior"].values()) == 0 and sum(b["business"].values()) == 0
        left = a.not_served_by_group
        assert left["comfort"] == pytest.approx(159.38, abs=0.01)
        assert left["group"] == pytest.approx(79.69, abs=0.01)
        assert left["senior"] == pytest.approx(63.75, abs=0.01)
        assert left["budget"] == pytest.approx(42.82, abs=0.01)
        assert left["business"] == pytest.approx(31.88, abs=0.01)

    def test_ref_pod_14_strict_lists_dominate_unserved(self):
        """Finding 2: with no Seat and no Couchette, Leisure – group and
        Leisure – budget cannot sit at all."""
        a = allocate(COMPS["REF-POD-14"], per_trip_groups())
        assert a.by_class["Sleeper"] == pytest.approx(230)
        assert a.by_class["Capsule"] == pytest.approx(152.51, abs=0.01)
        assert a.served == pytest.approx(382.51, abs=0.01)
        assert a.not_served == pytest.approx(255.01, abs=0.01)
        g = per_trip_groups()
        assert a.not_served_by_group["group"] == pytest.approx(g["group"])
        assert a.not_served_by_group["budget"] == pytest.approx(g["budget"])
        assert a.not_served_by_group["comfort"] == 0.0  # never -0.0

    def test_new_bal_14(self):
        a = allocate(COMPS["NEW-BAL-14"], per_trip_groups())
        assert a.by_class["Seat"] == pytest.approx(159.38, abs=0.01)
        assert a.by_class["Couchette"] == pytest.approx(80)
        assert a.by_class["Sleeper"] == pytest.approx(80)
        assert a.by_class["Capsule"] == pytest.approx(168)
        assert a.served == pytest.approx(487.38, abs=0.01)
        assert a.not_served == pytest.approx(150.14, abs=0.01)

    def test_rounds_interleave_the_groups(self):
        """Finding 1: senior leisure gets a share of the Sleeper on
        REF-POD-14 although Leisure – comfort, walked first, wants more
        than the whole car. A single pass would have given it nothing."""
        a = allocate(COMPS["REF-POD-14"], per_trip_groups())
        assert a.by_group_by_class["senior"]["Sleeper"] > 30

    def test_a_group_sits_only_in_the_classes_it_lists(self):
        a = allocate(
            {"Seat": 1000, "Couchette": 0, "Sleeper": 0, "Capsule": 0},
            per_trip_groups(),
        )
        assert a.by_group_by_class["comfort"]["Seat"] == 0
        assert a.by_group_by_class["business"]["Seat"] == 0
        assert a.by_group_by_class["budget"]["Seat"] == pytest.approx(
            per_trip_groups()["budget"]
        )

    def test_no_demand_no_places(self):
        a = allocate(COMPS["NEW-BAL-7"], {g: 0.0 for g in GROUP_ORDER})
        assert a.served == 0 and a.not_served == 0

    def test_served_plus_not_served_is_the_demand(self):
        for places in COMPS.values():
            a = allocate(places, per_trip_groups())
            assert a.served + a.not_served == pytest.approx(a.demand)

    def test_shares_not_summing_to_100_ask_for_the_sum(self):
        """D15: no rebalancing."""
        g = split_by_group(
            1000,
            {"comfort": 50, "group": 25, "senior": 10, "budget": 10, "business": 10},
        )
        assert sum(g.values()) == pytest.approx(1050)


# =============================================================================
# The OD spread (D25–D30)
# =============================================================================


class TestOdMatrix:
    def test_seventeen_sellable_pairs_in_route_order(self):
        pairs = sellable_pairs(berlin_verona())
        assert len(pairs) == 17
        assert pairs[0].key == ("Berlin", "Kufstein")
        assert pairs[-1].key == ("Innsbruck", "Verona")
        assert not any("München" in p.key or "Rosenheim" in p.key for p in pairs)
        assert (
            max(p.distance_km for p in pairs) == 1080
            and min(p.distance_km for p in pairs) == 75
        )

    def test_even_spread(self):
        pairs = sellable_pairs(berlin_verona())
        board, alight = preset_weights(
            ["Berlin", "Leipzig", "Nürnberg", "Kufstein", "Innsbruck"],
            ["Kufstein", "Innsbruck", "Bolzano", "Verona"],
            "even",
        )
        assert set(board.values()) == {1.0} and set(alight.values()) == {1.0}
        shares = od_shares(pairs, board, alight)
        assert all(v == pytest.approx(1 / 17) for v in shares.values())
        assert sum(shares.values()) == pytest.approx(1)
        assert average_distance_km(pairs, shares) == pytest.approx(535.29, abs=0.01)

    def test_presets_write_one_decimal_weights(self):
        board, alight = preset_weights(["a", "b", "c"], ["x", "y"], "long")
        # 0.3 + 2.7 × 0.5 is 1.6500000000000001 in binary, so it rounds UP —
        # in Python and in the sketch's toFixed(1) alike.
        assert board == {"a": 3.0, "b": 1.7, "c": 0.3}
        assert alight == {"x": 0.3, "y": 3.0}
        board, _ = preset_weights(["a", "b", "c"], ["x"], "mid")
        assert board == {"a": 0.3, "b": 3.0, "c": 0.3}
        assert preset_weights(["a"], ["x"], "short") == ({"a": 1.7}, {"x": 1.7})
        with pytest.raises(ValueError):
            preset_weights(["a"], ["x"], "nope")

    def test_pin_rescales_the_rest_and_keeps_the_sum(self):
        """Finding 6: other pins scale by (100 − v) / (100 − old)."""
        pairs = sellable_pairs(berlin_verona())
        board = {
            s: 1.0 for s in ["Berlin", "Leipzig", "Nürnberg", "Kufstein", "Innsbruck"]
        }
        alight = {s: 1.0 for s in ["Kufstein", "Innsbruck", "Bolzano", "Verona"]}
        pins = pin_pair(pairs, board, alight, {}, ("Berlin", "Verona"), 20)
        assert pins == {("Berlin", "Verona"): 20.0}
        shares = od_shares(pairs, board, alight, pins)
        assert shares[("Berlin", "Verona")] == pytest.approx(0.2)
        assert shares[("Leipzig", "Verona")] == pytest.approx(0.8 / 16)
        pins = pin_pair(pairs, board, alight, pins, ("Leipzig", "Verona"), 30)
        assert pins[("Berlin", "Verona")] == round(20 * (100 - 30) / (100 - 5), 2)
        shares = od_shares(pairs, board, alight, pins)
        assert sum(shares.values()) == pytest.approx(1)
        assert shares[("Leipzig", "Verona")] == pytest.approx(0.3)

    def test_pins_are_clamped_and_leave_nothing_negative(self):
        pairs = sellable_pairs(berlin_verona())
        board = {
            s: 1.0 for s in ["Berlin", "Leipzig", "Nürnberg", "Kufstein", "Innsbruck"]
        }
        alight = {s: 1.0 for s in ["Kufstein", "Innsbruck", "Bolzano", "Verona"]}
        pins = pin_pair(pairs, board, alight, {}, ("Berlin", "Verona"), 140)
        assert pins[("Berlin", "Verona")] == 100
        shares = od_shares(pairs, board, alight, pins)
        assert shares[("Berlin", "Verona")] == 1 and sum(
            shares.values()
        ) == pytest.approx(1)

    def test_stale_pins_are_dropped_and_reported(self):
        pairs = sellable_pairs(berlin_verona())
        kept, dropped = drop_stale_pins(
            {("Berlin", "Verona"): 10, ("Berlin", "München"): 5, ("Gone", "Verona"): 5},
            pairs,
        )
        assert kept == {("Berlin", "Verona"): 10}
        assert dropped == [("Berlin", "München"), ("Gone", "Verona")]

    def test_all_weights_zero_sell_nothing_rather_than_dividing_by_zero(self):
        pairs = [SellablePair("a", "b", 100.0)]
        assert od_shares(pairs, {"a": 0.0}, {"b": 0.0}) == {("a", "b"): 0.0}


# =============================================================================
# The per-year figures of the reference table
# =============================================================================


class TestPerYear:
    def test_new_bal_7_per_year(self):
        a = allocate(COMPS["NEW-BAL-7"], per_trip_groups())
        pairs = sellable_pairs(berlin_verona())
        shares = od_shares(
            pairs,
            {
                s: 1.0
                for s in ("Berlin", "Leipzig", "Nürnberg", "Kufstein", "Innsbruck")
            },
            {s: 1.0 for s in ("Kufstein", "Innsbruck", "Bolzano", "Verona")},
        )
        avg_km = average_distance_km(pairs, shares)
        pax = a.served * DEPARTURES
        ticket = sum(
            a.by_class[c]
            * DEPARTURES
            * (
                FARE_PER_PAX_BY_CLASS[c]
                + FARE_PER_KM_BY_CLASS[c] * avg_km
                + SERVICES_EUR_PER_PAX_BY_CLASS[c]
            )
            for c in a.by_class
        )
        catering = sum(
            a.by_class[c] * DEPARTURES * CATERING_EUR_PER_PAX_BY_CLASS[c]
            for c in a.by_class
        )
        assert round(pax) == 81566
        assert round(pax * avg_km) == 43661647
        assert ticket == pytest.approx(6840558.45, abs=0.01)
        assert catering == pytest.approx(135524.57, abs=0.01)

    def test_operating_days_and_train_km(self):
        assert OPERATING_DAYS == pytest.approx(156.857, abs=0.001)
        assert DEPARTURES == pytest.approx(313.714, abs=0.001)
        assert round(OPERATING_DAYS * 2160) == 338811


# =============================================================================
# distribute_demand() on a Route — the pipeline's call
# =============================================================================


class TestDistributeOnARoute:
    def _inputs(self, **overrides) -> DemandInputs:
        return DemandInputs(
            **{
                "passengers_per_year": TOTAL,
                "group_shares_pct": DEFAULT_GROUP_SHARES_PCT,
                **overrides,
            }
        )

    def test_reference_route_sells_the_reference_figures(self):
        route = route_with("NEW-BAL-7")
        result = distribute_demand(
            route, self._inputs(), FARE_PER_KM_BY_CLASS, FARE_PER_PAX_BY_CLASS
        )
        assert result.departures_per_year == pytest.approx(DEPARTURES)
        assert result.per_trip_demand == pytest.approx(637.52, abs=0.01)
        pair = route.trip_pairs[0]
        # 17 pairs × 4 served classes × 2 trips, every one fractional
        assert len(pair.od_pairs) == 17 * 4 * 2
        assert sum(od.places_sold for od in pair.od_pairs) == pytest.approx(
            81565.71, abs=0.01
        )
        assert sum(
            od.places_sold * od.avg_price for od in pair.od_pairs
        ) == pytest.approx(
            6840558.45
            - 260 * DEPARTURES * 0
            - sum(
                COMPS["NEW-BAL-7"][c] * DEPARTURES * SERVICES_EUR_PER_PAX_BY_CLASS[c]
                for c in COMPS["NEW-BAL-7"]
            ),
            abs=0.01,
        )
        demand = result.trip_pairs[0]
        assert demand.average_distance_km == pytest.approx(535.29, abs=0.01)
        assert demand.dropped_pins == []
        # the source split follows the pairs, not the route length
        assert demand.sources.air_trips + demand.sources.other_trips == pytest.approx(
            81565.71, abs=0.01
        )
        assert 0 < demand.sources.air_trips < 81565

    def test_return_trip_mirrors_the_outbound_matrix(self):
        route = route_with("NEW-BAL-7")
        distribute_demand(
            route, self._inputs(), FARE_PER_KM_BY_CLASS, FARE_PER_PAX_BY_CLASS
        )
        pair = route.trip_pairs[0]
        out = {
            (od.origin_stop_id, od.destination_stop_id, od.class_main): od.places_sold
            for od in pair.od_pairs
            if od.trip_id == "T1"
        }
        ret = {
            (od.destination_stop_id, od.origin_stop_id, od.class_main): od.places_sold
            for od in pair.od_pairs
            if od.trip_id == "T2"
        }
        assert out.keys() == ret.keys()
        assert all(out[k] == pytest.approx(ret[k]) for k in out)

    def test_weights_pins_and_a_night_stop(self):
        route = route_with("NEW-BAL-7")
        result = distribute_demand(
            route,
            self._inputs(
                board_weights={"Berlin": 3.0, "München": 5.0},
                pins_pct={("Leipzig", "Verona"): 10.0, ("Berlin", "München"): 5.0},
            ),
            FARE_PER_KM_BY_CLASS,
            FARE_PER_PAX_BY_CLASS,
        )
        demand = result.trip_pairs[0]
        # the night stop is neither a boarding stop nor a sellable destination
        assert "München" not in demand.board_weights
        assert demand.dropped_pins == [("Berlin", "München")]
        assert demand.pins_pct == {("Leipzig", "Verona"): 10.0}
        assert demand.shares[("Leipzig", "Verona")] == pytest.approx(0.10)
        assert sum(demand.shares.values()) == pytest.approx(1)
        berlin = sum(v for (o, _), v in demand.shares.items() if o == "Berlin")
        nuernberg = sum(v for (o, _), v in demand.shares.items() if o == "Nürnberg")
        assert berlin == pytest.approx(3 * nuernberg)

    def test_a_level_and_a_share_edit_move_the_load(self):
        small = distribute_demand(
            route_with("NEW-BAL-7"),
            self._inputs(passengers_per_year=100000),
            FARE_PER_KM_BY_CLASS,
            FARE_PER_PAX_BY_CLASS,
        )
        assert small.trip_pairs[0].allocation.served < 260
        skewed = distribute_demand(
            route_with("NEW-BAL-7"),
            self._inputs(
                group_shares_pct={
                    "comfort": 0,
                    "group": 0,
                    "senior": 0,
                    "budget": 100,
                    "business": 0,
                }
            ),
            FARE_PER_KM_BY_CLASS,
            FARE_PER_PAX_BY_CLASS,
        )
        assert skewed.trip_pairs[0].allocation.by_class == pytest.approx(
            {"Seat": 96, "Couchette": 0, "Sleeper": 0, "Capsule": 0}
        )

    def test_the_composition_without_a_class_sells_none_of_it(self):
        route = route_with("REF-POD-14")
        distribute_demand(
            route, self._inputs(), FARE_PER_KM_BY_CLASS, FARE_PER_PAX_BY_CLASS
        )
        classes = {od.class_main for od in route.trip_pairs[0].od_pairs}
        assert classes == {"Sleeper", "Capsule"}


# =============================================================================
# Sources by journey length
# =============================================================================


class TestSources:
    @pytest.mark.parametrize(
        "km, share",
        [(0, 0.0), (299, 0.0), (300, 0.25), (750, 0.625), (1200, 1.0), (2000, 1.0)],
    )
    def test_air_share_curve(self, km, share):
        assert air_share(km) == pytest.approx(share)

    def test_split_sums_to_the_passengers(self):
        split = split_sources([(300, 100), (1080, 50), (75, 20)])
        assert split.air_trips + split.other_trips == pytest.approx(170)
        assert split.car_trips == pytest.approx(split.induced_trips)
        assert split.air_trips == pytest.approx(25 + 50 * (0.25 + 0.75 * 780 / 900))
        assert split.air_trip_km + split.other_trip_km == pytest.approx(
            300 * 100 + 1080 * 50 + 75 * 20
        )


# =============================================================================
# The request boundary
# =============================================================================


class TestRequestBoundary:
    def test_defaults(self):
        n = normalize_demand(None)
        assert n["level"] == "medium" and n["passengers_per_year"] == 200000
        assert n["group_shares_pct"] == DEFAULT_GROUP_SHARES_PCT
        assert n["od"] == {
            "preset": "custom",
            "stop_weights": {"board": {}, "alight": {}},
            "pinned_shares_pct": {},
        }
        assert normalize_demand({}) == n
        assert normalize_demand({"level": "medium", "od": {"stop_weights": {}}}) == n

    def test_level_follows_the_total(self):
        assert normalize_demand({"level": "xl"})["passengers_per_year"] == 500000
        assert normalize_demand({"passengers_per_year": 300000})["level"] == "large"
        assert (
            normalize_demand({"level": "large", "passengers_per_year": 300001})["level"]
            == "custom"
        )
        assert (
            normalize_demand({"level": "custom", "passengers_per_year": 123})["level"]
            == "custom"
        )

    def test_canonical_form(self):
        n = normalize_demand(
            {
                "od": {
                    "preset": "long",
                    "stop_weights": {"board": {"b": 0.30000000000000004, "a": 1}},
                    "pinned_shares_pct": {"y": {"z": 12.499999}, "x": {}},
                }
            }
        )
        assert n["od"]["preset"] == "long"
        assert list(n["od"]["stop_weights"]["board"]) == ["a", "b"]
        assert n["od"]["stop_weights"]["board"]["b"] == 0.3
        assert n["od"]["pinned_shares_pct"] == {"y": {"z": 12.5}}

    def test_validation(self):
        assert validate_demand(None) == []
        assert validate_demand({"level": "medium", "passengers_per_year": 0}) == []
        assert validate_demand({"level": "huge"})
        assert validate_demand({"passengers_per_year": -1})
        assert validate_demand({"group_shares_pct": {"vip": 10}})
        assert validate_demand({"group_shares_pct": {"comfort": -1}})
        assert validate_demand({"group_shares_pct": {"comfort": 60, "group": 60}}) == []
        assert validate_demand({"od": {"preset": "diagonal"}})
        assert validate_demand({"od": {"stop_weights": {"board": {"a": -0.1}}}})
        assert validate_demand(
            {"od": {"pinned_shares_pct": {"a": {"b": 60}, "c": {"d": 50}}}}
        )
        assert validate_demand({"od": {"pinned_shares_pct": {"a": {"b": 101}}}})
        assert (
            validate_demand(
                {"od": {"pinned_shares_pct": {"a": {"b": 60}, "c": {"d": 40}}}}
            )
            == []
        )
        assert validate_demand({"extra": 1})
        assert validate_demand({"demand": 3})  # unknown key
        assert validate_demand(3)

    def test_inputs_from_the_echo(self):
        i = demand_inputs(
            normalize_demand({"od": {"pinned_shares_pct": {"a": {"b": 5}}}})
        )
        assert i.passengers_per_year == 200000 and i.pins_pct == {("a", "b"): 5.0}

    def test_labels_stay_out_of_the_family_key(self):
        assert "demand" in REQUEST_KEY_FIELDS
        base = {f: None for f in REQUEST_KEY_FIELDS}
        a = {
            **base,
            "demand": normalize_demand({"level": "medium", "od": {"preset": "even"}}),
        }
        b = {
            **base,
            "demand": normalize_demand(
                {"passengers_per_year": 200000, "od": {"preset": "custom"}}
            ),
        }
        c = {**base, "demand": normalize_demand({"passengers_per_year": 200001})}
        assert family_key(a, [1], ["X"], 7) == family_key(b, [1], ["X"], 7)
        assert family_key(a, [1], ["X"], 7) != family_key(c, [1], ["X"], 7)


# =============================================================================
# The parity fixture the frontend tests read
# =============================================================================


def _fixture() -> dict:
    """Every case above the frontend has to reproduce, from the backend's
    own arithmetic."""
    groups = per_trip_groups()
    pairs = sellable_pairs(berlin_verona())
    board_ids = ["Berlin", "Leipzig", "Nürnberg", "Kufstein", "Innsbruck"]
    alight_ids = ["Kufstein", "Innsbruck", "Bolzano", "Verona"]
    even = preset_weights(board_ids, alight_ids, "even")
    shares = od_shares(pairs, *even)
    pins1 = pin_pair(pairs, *even, {}, ("Berlin", "Verona"), 20)
    pins2 = pin_pair(pairs, *even, pins1, ("Leipzig", "Verona"), 30)
    presets = {
        k: [dict(w) for w in preset_weights(board_ids, alight_ids, k)]
        for k in ("even", "long", "mid", "short")
    }
    return {
        "description": "DEMAND 0.1.0 reference values — written by tests/test_83_demand_units.py, read by the frontend parity tests",
        "days_in_year": DAYS_IN_YEAR,
        "days_per_week": FREQ,
        "departures_per_year": DEPARTURES,
        "passengers_per_year": TOTAL,
        "group_shares_pct": DEFAULT_GROUP_SHARES_PCT,
        "per_trip_by_group": groups,
        "compositions": COMPS,
        "allocations": {
            comp: {
                "by_group_by_class": allocate(places, groups).by_group_by_class,
                "by_class": allocate(places, groups).by_class,
                "served": allocate(places, groups).served,
                "not_served_by_group": allocate(places, groups).not_served_by_group,
                "not_served": allocate(places, groups).not_served,
            }
            for comp, places in COMPS.items()
        },
        "stops": [{"stop_id": s, "km": km, "kind": k} for s, km, k in STOPS],
        "boarding_stop_ids": board_ids,
        "alighting_stop_ids": alight_ids,
        "sellable_pairs": [
            {
                "origin_stop_id": p.origin_stop_id,
                "destination_stop_id": p.destination_stop_id,
                "distance_km": p.distance_km,
            }
            for p in pairs
        ],
        "presets": presets,
        "even_shares": [shares[p.key] for p in pairs],
        "average_distance_km": average_distance_km(pairs, shares),
        "pin_steps": [
            {
                "pin": ["Berlin", "Verona"],
                "value_pct": 20,
                "pins_after": [[list(k), v] for k, v in pins1.items()],
                "shares_after": [od_shares(pairs, *even, pins1)[p.key] for p in pairs],
            },
            {
                "pin": ["Leipzig", "Verona"],
                "value_pct": 30,
                "pins_after": [[list(k), v] for k, v in pins2.items()],
                "shares_after": [od_shares(pairs, *even, pins2)[p.key] for p in pairs],
            },
        ],
        "tariff": {
            "fares_eur_per_pax": {
                c: FARE_PER_PAX_BY_CLASS[c] for c in COMPS["NEW-BAL-7"]
            },
            "fares_eur_per_km": {
                c: FARE_PER_KM_BY_CLASS[c] for c in COMPS["NEW-BAL-7"]
            },
            "services_eur_per_pax": SERVICES_EUR_PER_PAX_BY_CLASS,
            "catering_eur_per_pax": CATERING_EUR_PER_PAX_BY_CLASS,
        },
        "new_bal_7_per_year": {
            "passengers": 81565.71428571428,
            "place_km_sold": 43661647.058823526,
            "ticket_revenue_eur": 6840558.453781512,
            "catering_eur": 135524.57142857142,
        },
        "air_share": {str(km): air_share(km) for km in (0, 299, 300, 750, 1200, 2000)},
    }


def test_fixture_is_current():
    """The test writes the file when it is absent and rewrites it (and
    fails once) when it differs, so a changed constant cannot silently
    orphan the frontend's parity tests: rerun, run the frontend tests,
    commit the file."""
    current = json.dumps(_fixture(), indent=2, ensure_ascii=False, sort_keys=True)
    if not FIXTURE.exists():
        FIXTURE.parent.mkdir(exist_ok=True)
        FIXTURE.write_text(current + "\n", encoding="utf-8")
    stored = FIXTURE.read_text(encoding="utf-8")
    if stored != current + "\n":
        FIXTURE.write_text(current + "\n", encoding="utf-8")
        pytest.fail(
            f"{FIXTURE.name} was out of date and has been rewritten — rerun the "
            "frontend parity tests and commit it."
        )
