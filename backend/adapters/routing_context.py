"""
routing_context.py
==================
Routing with a REFERENCE composition, for the batch jobs that need real
track distances but have no composition of their own to route with.

Two callers today, both run at seed time:

  * db/ontd/projection.py — draws every existing (ONTD) night train on
    the gallery map. The ONTD catalog carries no speed or HSR data, so
    one reference composition stands in for every existing train
    (adapters/proposal/README.md decision 25).
  * scripts/build_country_relations.py — measures the rail distance
    between two countries' reference stations to decide whether a night
    train could plausibly connect them (§7.7).

Neither is a proposal: nothing here is ever part of an evaluated route,
and RailRouter.route() reads exactly two fields off the composition
(max_speed_kmh, hsr_allowed). Sharing one context builder keeps both
jobs on the same routing rules — anything less would measure the same
physical track differently depending on which script asked.

Everything is soft: build_reference_context() returns None when the
router is down or the parameters are not seeded, and route_stops()
reports a status instead of raising, so a batch job degrades (straight
lines, an unmeasured pair) rather than aborting work that is otherwise
good.

Public interface:
  build_reference_context(composition_id=None) → ReferenceContext | None
  route_stops(context, points)                 → RoutingResult
  route_all(context, jobs, workers)            → dict[key, RoutingResult]

Both `points` and every job's points are plain
(id, lat, lon) triples — callers hold their own stop objects.
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Sequence

logger = logging.getLogger(__name__)

# Reference composition family. Resolved at runtime rather than
# hardcoded to an id: composition ids are a calibration output and do rot
# (STD-7.1, cited across the docs, had been dropped from the catalog by
# the time the ONTD projection first ran). 'refurbished' matches what
# existing night trains actually run, so routed times stay comparable to
# real schedules.
REFERENCE_MATERIAL_STRATEGY = "refurbished"

# Independent HTTP round-trips per job (fullRouting snaps, then routes),
# so throughput is bound by router latency, not by anything local.
# RailRouter's session pool holds 64; the router container is shared, so
# the default stays modest.
DEFAULT_WORKERS = int(os.environ.get("REFERENCE_ROUTING_WORKERS", "8"))


@dataclass(frozen=True)
class ReferenceContext:
    """Everything RailRouter.route() needs, assembled once and read-only
    afterwards — safe to share across worker threads."""

    router: Any
    tracks: Any
    composition: Any


@dataclass(frozen=True)
class RoutingResult:
    """One routing attempt. legs is empty unless status == 'routed'."""

    legs: list
    status: str
    error: Optional[str] = None

    @property
    def routed(self) -> bool:
        return self.status == "routed"

    @property
    def distance_km(self) -> Optional[float]:
        if not self.routed:
            return None
        return sum(leg.distance_m for leg in self.legs) / 1000.0

    @property
    def time_h(self) -> Optional[float]:
        if not self.routed:
            return None
        return sum(leg.total_time_min for leg in self.legs) / 60.0


def build_reference_context(
    composition_id: Optional[str] = None,
) -> Optional[ReferenceContext]:
    """Router + tracks + reference composition, or None if anything is
    unavailable (router down, parameters not seeded, unknown id) — the
    caller decides how to degrade."""
    try:
        from adapters.data_loader_from_db import DBDataLoader
        from dev_env import resolve_service_url
        from models.route.routing.rail_router import CountryIndex, RailRouter

        # RailRouter reads OPENRAILROUTING_URL at construction, so a
        # host-run caller needs the compose service name translated to
        # localhost before that. No-op inside the stack.
        resolve_service_url()

        loader = DBDataLoader()
        composition = _select_composition(
            loader.build_all_compositions(), composition_id
        )
        if composition is None:
            return None

        router = RailRouter(CountryIndex(loader.get_country_geometries()))
        router.check_server()
        logger.info(
            "Reference routing with composition '%s' (%s, max %.0f km/h, "
            "hsr_allowed=%s)",
            composition.comp_id,
            composition.material_strategy,
            composition.max_speed_kmh,
            composition.hsr_allowed,
        )
        return ReferenceContext(
            router=router, tracks=loader.build_all_tracks(), composition=composition
        )
    except Exception as e:
        logger.warning("Reference routing unavailable (%s: %s).", type(e).__name__, e)
        return None


def _select_composition(collection, requested: Optional[str]):
    """An explicit id if given, else the first REFERENCE_MATERIAL_STRATEGY
    composition by id. Deterministic (sorted) so successive rebuilds stay
    comparable — a dataset silently routed with a different composition
    than the previous run is worse than useless."""
    catalog = collection.all()
    if requested:
        composition = collection.get(requested)
        if composition is None:
            available = ", ".join(sorted(catalog)[:12])
            logger.warning(
                "Composition '%s' not found — pass a valid id. "
                "Available (first 12): %s",
                requested,
                available,
            )
        return composition

    matching = sorted(
        (
            c
            for c in catalog.values()
            if c.material_strategy == REFERENCE_MATERIAL_STRATEGY
        ),
        key=lambda c: c.comp_id,
    )
    if matching:
        return matching[0]

    fallback = sorted(catalog.values(), key=lambda c: c.comp_id)
    if not fallback:
        logger.warning("Composition catalog is empty.")
        return None
    logger.warning(
        "No '%s' composition in the catalog — falling back to '%s'.",
        REFERENCE_MATERIAL_STRATEGY,
        fallback[0].comp_id,
    )
    return fallback[0]


def route_stops(
    context: ReferenceContext,
    points: Sequence[tuple],
) -> RoutingResult:
    """Route an ordered stop sequence with the reference composition, full
    two-pass routing.

    Each point is (stop_id, lat, lon) or (stop_id, lat, lon, gauges_mm).
    PASS THE GAUGES WHENEVER THE CALLER HAS THEM. Without them every stop
    looks gauge-unknown, resolve_trip_gauge() falls back to standard gauge
    (its documented all-unknown rule), and the call routes on the
    standard-gauge profile — which is right for ONTD's raw stops, whose
    gauges nothing knows, but silently wrong for callers working from the
    catalog: broad-gauge stations then fail to snap exactly as they did
    before per-gauge profiles existed.

    Never raises: a failure comes back as a status, so one unroutable
    entry in a batch cannot lose the rest. The router distinguishes
    "could not snap a stop to usable track" (usually the 1435mm gauge
    filter) from "snapped fine but no path exists" (a genuinely
    disconnected network) — worth keeping apart, since the second is a
    real answer about the network and the first is a data problem.
    """
    from models.params import StopInfrastructure
    from models.route.routing.rail_router import StopInput
    from models.route.trip import StopType

    located = [p for p in points if p[1] is not None and p[2] is not None]
    if len(located) < 2:
        return RoutingResult([], "too_few_stops", "fewer than two located stops")

    router_stops = [
        StopInput(
            stop=StopInfrastructure(
                stop_id=point[0],
                stop_name=point[0],
                stop_country_code="",
                lat=float(point[1]),
                lon=float(point[2]),
                # Never read while routing — charges belong to
                # evaluation, which never runs on these.
                stop_charge_eur=0.0,
                # Fourth element when the caller has it; None otherwise,
                # which resolve_trip_gauge() reads as "unknown".
                gauges_mm=point[3] if len(point) > 3 else None,
            ),
            stop_type=StopType.BOTH,
        )
        for point in located
    ]
    try:
        legs = context.router.route(
            router_stops, context.composition, context.tracks, "fullRouting"
        )
        return RoutingResult(legs, "routed")
    except Exception as e:
        message = str(e)
        if "Connection between" in message:
            status = "no_connection"
        elif "gauge" in message.lower():
            # No single gauge serves the pair (GaugeMismatchError) — a
            # real answer about the two networks, not a snapping failure.
            status = "gauge_mismatch"
        else:
            status = "snap_failed"
        return RoutingResult([], status, message)


def route_all(
    context: ReferenceContext,
    jobs: Iterable[tuple[Any, Sequence[tuple[str, float, float]]]],
    workers: int = DEFAULT_WORKERS,
    progress_every: int = 25,
) -> dict:
    """Route every (key, points) job concurrently → {key: RoutingResult}.

    Routing up front and in parallel, writing sequentially afterwards,
    keeps the database work single-threaded on one connection while
    removing the part that actually costs time. Nothing shared is
    mutated: the router's session is pooled, composition, tracks and the
    country index are read-only lookups.
    """
    jobs = list(jobs)
    results: dict = {}
    if not jobs:
        return results

    logger.info("Routing %d pairs, %d at a time", len(jobs), workers)
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(route_stops, context, points): key for key, points in jobs
        }
        for future in as_completed(futures):
            key = futures[future]
            done += 1
            try:
                results[key] = future.result()
            except Exception as e:
                # A crash on one job must not lose the others.
                results[key] = RoutingResult(
                    [], "snap_failed", f"{type(e).__name__}: {e}"
                )
            if done % progress_every == 0 or done == len(jobs):
                logger.info("[%d/%d] routed", done, len(jobs))
    return results
