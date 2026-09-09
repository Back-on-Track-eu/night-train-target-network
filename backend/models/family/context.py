"""
context.py
==========
FamilyContext — what every member of one family build shares: the
catalogs of each scenario and the raw routed legs of each leg variant.
Build-scoped and in-memory; nothing here touches the database or the
router except through the objects it wraps.

Why it exists (scripts/bench_member.py, 2026-09-09): a member costs
~238 ms plain, of which ~208 ms is reloading five catalogs from the
database and ~35 ms is fetching legs — the trip build, timetable, demand
and evaluation together are 4 ms. Sharing the two expensive parts across
the 72 members of a family is the whole design; the pipeline itself
(models/pipeline.py, models/route/route_factory.py) is unchanged and does
not know it is running on a memo.

Two memos, one boundary each:

  MemoLoader   the loader's per-scenario catalog builders and the two
               scenario-row resolutions a compute makes. Catalogs are
               read-only collections, so one object per (builder,
               scenario) serves every member.
  MemoRouter   RailRouter.route() — layer 1, raw legs as a pure function
               of (stops, speed cap, HSR vector, gauge, mode) on one
               graph. Everything downstream of route() mutates legs in
               place (route_trip()'s buffer and dynamics, calc_energy_
               consumption()), so the memo hands out COPIES; a shallow
               dataclasses.replace() suffices because only scalar fields
               are ever written.

Both memos are single-flight: concurrent callers of one key wait for the
first computation instead of repeating it. That is what makes the
prewarm phase (FamilyContext.prewarm) safe to fan out — the bench's
naive memo did the same catalog load once per thread when four threads
started cold, and lost to serial.

Thread-safety contract: the memo dicts and the per-key locks are the only
shared mutable state, and both live under _lock. Handed-out catalogs are
shared by reference and never written; handed-out legs are copies.
"""

from __future__ import annotations

import dataclasses
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Hashable, Iterable

from models.params import Composition, Scenario
from models.route.routing.rail_router import (
    RailRouter,
    build_router_stops,
    route_trip,
)


class _SingleFlight:
    """A memo where the first caller of a key computes and every
    concurrent caller of the same key waits for that result. Values are
    stored as computed; callers copy on the way out if they must."""

    def __init__(self) -> None:
        self._values: dict = {}
        self._in_flight: dict[Hashable, threading.Lock] = {}
        self._lock = threading.Lock()
        self.calls = 0
        self.hits = 0

    def get(self, key: Hashable, compute: Callable[[], object]):
        with self._lock:
            self.calls += 1
            if key in self._values:
                self.hits += 1
                return self._values[key]
            gate = self._in_flight.get(key)
            if gate is None:
                gate = self._in_flight[key] = threading.Lock()
                gate.acquire()
                owner = True
            else:
                owner = False
        if not owner:
            # Someone else is computing this key: wait for their gate, then
            # look again. Recursing rather than reading the value directly
            # means a computation that RAISED leaves nothing behind and the
            # waiter simply becomes the next owner.
            with gate:
                pass
            return self.get(key, compute)
        try:
            value = compute()
            with self._lock:
                self._values[key] = value
            return value
        finally:
            with self._lock:
                del self._in_flight[key]
            gate.release()

    def __len__(self) -> int:
        return len(self._values)


class MemoLoader:
    """Build-scoped memo over DBDataLoader. Only the methods named in
    _MEMOISED are cached — the catalog builders run_compute() calls and
    the two scenario-row resolutions api/helpers/proposal_compute.py
    makes; everything else delegates to the wrapped loader untouched."""

    _MEMOISED = frozenset(
        {
            "build_all_compositions",
            "build_all_tracks",
            "build_all_stops",
            "build_all_passages",
            "resolve_scenario_id",
            "resolve_routing_graph_key",
        }
    )

    def __init__(self, loader) -> None:
        self._loader = loader
        self._memo = _SingleFlight()

    def __getattr__(self, name):
        target = getattr(self._loader, name)
        if name not in self._MEMOISED:
            return target

        def memoised(*args, **kwargs):
            key = (name, args, tuple(sorted(kwargs.items())))
            return self._memo.get(key, lambda: target(*args, **kwargs))

        return memoised

    @property
    def stats(self) -> tuple[int, int]:
        """(calls, hits) — for the bench and the document's stats block."""
        return self._memo.calls, self._memo.hits


class MemoRouter:
    """Build-scoped memo over one RailRouter's route(). Delegates every
    other attribute (graph_key, check_server, …) to the wrapped router."""

    def __init__(self, router: RailRouter) -> None:
        self._router = router
        self._memo = _SingleFlight()

    def __getattr__(self, name):
        return getattr(self._router, name)

    def route(self, stops, max_speed_kmh, avoid_hsr, gauge_mm, routing_mode):
        key = (
            tuple(s.stop.stop_id for s in stops),
            max_speed_kmh,
            None if avoid_hsr is None else tuple(sorted(avoid_hsr.items())),
            gauge_mm,
            routing_mode,
        )
        legs = self._memo.get(
            key,
            lambda: self._router.route(
                stops, max_speed_kmh, avoid_hsr, gauge_mm, routing_mode
            ),
        )
        return [dataclasses.replace(leg) for leg in legs]

    @property
    def stats(self) -> tuple[int, int]:
        return self._memo.calls, self._memo.hits


class FamilyContext:
    """One family build's shared state: a MemoLoader and one MemoRouter
    per routing graph, created on first use.

    router_for: graph_key -> RailRouter, injected by the API layer
    (api/helpers/dependencies.get_rail_router) so this module stays free
    of Flask and of the router registry. It may raise for a graph this
    deployment does not run; the builder turns that into an error member.
    """

    def __init__(self, loader, router_for: Callable[[str], RailRouter]) -> None:
        self.loader = MemoLoader(loader)
        self._router_for = router_for
        self._routers: dict[str, MemoRouter] = {}
        self._lock = threading.Lock()

    def router(self, graph_key: str) -> MemoRouter:
        with self._lock:
            router = self._routers.get(graph_key)
            if router is None:
                router = self._routers[graph_key] = MemoRouter(
                    self._router_for(graph_key)
                )
            return router

    def prewarm(
        self,
        scenarios: Iterable[Scenario],
        compositions: Iterable[Composition],
        stop_ids: list[str],
        routing_mode: str,
        workers: int,
    ) -> None:
        """Fill both memos in parallel before the serial member loop: every
        scenario's catalogs and every distinct leg variant, both directions.

        One task per (scenario, composition) — 72 for the default family,
        each routing outbound THEN return. Almost all are memo hits: the
        single-flight memos collapse the 72 catalog loads to 6 and the 144
        route calls to the distinct variants (12 on Berlin–Wien). Threads
        pay off here and only here, because this is the I/O — the database
        and the routing engine — and the member loop that follows is pure
        Python.

        The two directions run in ORDER inside one task rather than as two
        independent tasks, and that ordering is load-bearing:
        route_cache.route_segments keys a stop pair lo→hi and serves the
        other direction by reversing it, so whichever direction routes
        first decides the corridor for both. Two threads missing the same
        pair at once would each route their own direction live, and the
        return would then be its own path in this build but the reverse of
        the outbound's in every later one — a family that quietly changed
        shape once its legs were cached. Sequential per pair, the first
        build is already the cached one.

        Failures are swallowed on purpose: a scenario whose graph is not
        configured, or a stop pair that cannot be routed, fails again in
        the member loop, where the builder records it as an error member
        with the right code. Prewarm exists to be fast, not to decide.
        """
        tasks = [
            (scenario, composition)
            for scenario in scenarios
            for composition in compositions
        ]
        directions = (list(stop_ids), list(reversed(stop_ids)))

        def warm(task) -> None:
            scenario, composition = task
            try:
                loader = self.loader
                tracks = loader.build_all_tracks(scenario.scenario_id)
                stop_infra = loader.build_all_stops(scenario.scenario_id)
                loader.build_all_passages(scenario.scenario_id)
                loader.build_all_compositions(
                    scenario.scenario_id, include_indicative=False
                )
                router = self.router(scenario.routing_graph_key)
                for stops in directions:
                    route_trip(
                        router,
                        stops=build_router_stops(stops, stop_infra),
                        composition=composition,
                        tracks=tracks,
                        routing_mode=routing_mode,
                    )
            except Exception:  # noqa: BLE001 — see the docstring
                return

        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            list(pool.map(warm, tasks))

    @property
    def stats(self) -> dict:
        loader_calls, loader_hits = self.loader.stats
        route_calls = sum(r.stats[0] for r in self._routers.values())
        route_hits = sum(r.stats[1] for r in self._routers.values())
        return {
            "loader_calls": loader_calls,
            "loader_hits": loader_hits,
            "route_calls": route_calls,
            "route_hits": route_hits,
            # Distinct (stops, speed cap, HSR vector, gauge, mode) tuples
            # actually routed — leg variants, not member routes.
            "n_leg_variants": route_calls - route_hits,
        }
