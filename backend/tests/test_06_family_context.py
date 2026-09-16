"""
test_06_family_context.py
=========================
The memo boundary a family build shares (models/family/context.py):

  _SingleFlight  concurrent callers of one key wait for one computation
  MemoRouter     RailRouter.route() runs once per variant and hands out
                 independent copies; everything else delegates
  MemoLoader     one object per (builder, scenario); delegation
  FamilyContext  one MemoRouter per graph; prewarm fills both memos for
                 a real corridor and the member loop then hits every time

The first three run on fakes — they pin the contract, not the stack.
The last two run on the live loader + router registry, the way
api/helpers/family_compute.py drives them.
"""

from __future__ import annotations

import threading
import time

import pytest

from models.family.context import FamilyContext, MemoLoader, MemoRouter, _SingleFlight
from models.route.routing.rail_router import RoutedLeg, StopInput
from tests.conftest import DEFAULT_COMPOSITION, STOPS_BERLIN_WIEN


class _FakeStop:
    def __init__(self, stop_id: str) -> None:
        self.stop_id = stop_id


class _FakeRouter:
    graph_key = "fake"

    def __init__(self) -> None:
        self.calls = 0

    def route(self, stops, max_speed_kmh, avoid_hsr, gauge_mm, routing_mode):
        self.calls += 1
        return [
            RoutedLeg(
                geometry=[[0.0, 0.0], [1.0, 1.0]],
                distance_m=1000,
                driving_time_min=10,
                dynamics_time_min=0,
                buffer_time_min=0,
                energy_kwh=0.0,
                country_distance_shares={"DE": 1.0},
                country_time_shares={"DE": 1.0},
            )
        ]


class _FakeLoader:
    def __init__(self) -> None:
        self.calls = 0

    def build_all_stops(self, scenario_id=None):
        self.calls += 1
        return object()

    def list_all_scenarios(self):
        return "not memoised"


def _stops(*ids: str) -> list[StopInput]:
    return [StopInput(stop=_FakeStop(i), stop_type=None) for i in ids]


class TestSingleFlight:
    def test_concurrent_callers_share_one_computation(self):
        memo = _SingleFlight()
        computed = []

        def slow():
            computed.append(1)
            time.sleep(0.1)
            return 42

        results = []
        threads = [
            threading.Thread(target=lambda: results.append(memo.get("k", slow)))
            for _ in range(8)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert results == [42] * 8
        assert computed == [1], "the computation ran more than once"

    def test_a_raising_computation_leaves_nothing_behind(self):
        """The first caller's failure is its own; the next caller computes
        again rather than reading a value that was never stored."""
        memo = _SingleFlight()
        attempts = []

        def flaky():
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("first attempt fails")
            return "ok"

        with pytest.raises(RuntimeError):
            memo.get("k", flaky)
        assert memo.get("k", flaky) == "ok"
        assert len(memo) == 1


class TestMemoRouter:
    def test_routes_once_per_variant(self):
        router = _FakeRouter()
        memo = MemoRouter(router)
        stops = _stops("a", "b")
        memo.route(stops, 200, {"DE": False}, 1435, "fullRouting")
        memo.route(stops, 200, {"DE": False}, 1435, "fullRouting")
        assert router.calls == 1
        memo.route(stops, 230, {"DE": False}, 1435, "fullRouting")
        assert router.calls == 2, "a different speed cap is a different variant"
        memo.route(_stops("b", "a"), 200, {"DE": False}, 1435, "fullRouting")
        assert router.calls == 3, "the reverse direction is a different variant"

    def test_hands_out_independent_copies(self):
        """route_trip() and calc_energy_consumption() write buffer,
        dynamics and energy onto the legs they get — one member's physics
        must never leak into the next member's raw legs."""
        memo = MemoRouter(_FakeRouter())
        stops = _stops("a", "b")
        first = memo.route(stops, 200, {"DE": False}, 1435, "fullRouting")
        first[0].buffer_time_min = 99
        first[0].energy_kwh = 12.5
        second = memo.route(stops, 200, {"DE": False}, 1435, "fullRouting")
        assert second[0].buffer_time_min == 0
        assert second[0].energy_kwh == 0.0
        assert second[0] is not first[0]

    def test_delegates_everything_else(self):
        memo = MemoRouter(_FakeRouter())
        assert memo.graph_key == "fake"


class TestMemoLoader:
    def test_same_object_per_scenario(self):
        loader = _FakeLoader()
        memo = MemoLoader(loader)
        assert memo.build_all_stops(1) is memo.build_all_stops(1)
        assert loader.calls == 1
        memo.build_all_stops(2)
        assert loader.calls == 2

    def test_unlisted_methods_delegate_uncached(self):
        memo = MemoLoader(_FakeLoader())
        assert memo.list_all_scenarios() == "not memoised"


@pytest.fixture(scope="module")
def routers():
    """The API's router registry, initialised the way scripts do it."""
    from api.helpers import dependencies

    dependencies.init()
    return dependencies.get_rail_router


class TestFamilyContextLive:
    def test_prewarm_fills_both_memos_then_members_hit(self, loader, routers):
        """After prewarm, a run_compute() on the context loads no catalog
        and routes nothing — the property the family's member loop relies
        on to cost ~4 ms per member."""
        from models.pipeline import run_compute
        from models.route.model import (
            DEFAULT_ROUTING_MODE,
            DEFAULT_SCHEDULE_MODE,
            DEFAULT_TIMETABLE_MODE,
            NEUTRAL_PROPOSAL_ID,
            NEUTRAL_PROPOSAL_VERSION,
        )

        base_id = loader.resolve_scenario_id(None)
        scenarios = [s for s in loader.list_all_scenarios() if s.scenario_id == base_id]
        composition = loader.build_all_compositions(include_indicative=False).get(
            DEFAULT_COMPOSITION
        )
        context = FamilyContext(loader, routers)
        context.prewarm(
            scenarios, [composition], STOPS_BERLIN_WIEN, DEFAULT_ROUTING_MODE, 4
        )
        warmed = context.stats
        assert warmed["n_leg_variants"] == 2, "outbound + return, once each"

        run_compute(
            proposal_id=NEUTRAL_PROPOSAL_ID,
            proposal_version=NEUTRAL_PROPOSAL_VERSION,
            stops=STOPS_BERLIN_WIEN,
            composition_id=DEFAULT_COMPOSITION,
            scenario_id=base_id,
            timetable_mode=DEFAULT_TIMETABLE_MODE,
            fixed_night_interval=None,
            schedule_mode=DEFAULT_SCHEDULE_MODE,
            routing_mode=DEFAULT_ROUTING_MODE,
            auto_stop_addition="off",
            loader=context.loader,
            router=context.router(scenarios[0].routing_graph_key),
        )
        after = context.stats
        assert after["n_leg_variants"] == warmed["n_leg_variants"], (
            "the member routed live"
        )
        assert after["loader_hits"] > warmed["loader_hits"]
        assert after["loader_calls"] - after["loader_hits"] == (
            warmed["loader_calls"] - warmed["loader_hits"]
        ), "the member loaded a catalog"

    def test_one_router_per_graph(self, loader, routers):
        context = FamilyContext(loader, routers)
        assert context.router("infra_2026") is context.router("infra_2026")
