"""
timetable.py
============
Per-direction scheduling/stop-list logic for route planning — the
implementations, not the switch. Which implementation runs for a given
request is decided by route_factory.py (at whichever level owns the
relevant context — per-trip in _build_trip(), per-route in plan_route());
this module holds one function per named strategy and never branches on
timetable_mode/schedule_mode itself. auto_stop_addition's enabled/disabled
gate is likewise decided by _build_trip() — apply_auto_stop_addition()
below always runs the full candidate-search algorithm when called.

Three request-level concerns have their logic here, each with its switch
living in route_factory.py:

  timetable_mode      — departure time + boarding/alighting classification
                         for one direction's stop list. One function per
                         mode (currently simple_automatic_timetable() for
                         "simpleAutomatic"); route_factory._build_trip()
                         picks which to call.

  schedule_mode       — seasonal frequency for the route as a whole. One
                         function per mode (currently always_daily_schedule()
                         for "alwaysDaily"); route_factory.plan_route()
                         picks which to call — a route-level decision made
                         once, not per trip, since schedule is shared
                         across every TripPair.

  auto_stop_addition  — whether to propose additional stops along a route
                         beyond what the caller supplied. Looks for stops
                         from the full stop catalog that sit close to the
                         already-routed geometry, costs them all CONCURRENTLY
                         (one 3-point mini-reroute per candidate — a
                         sequential whole-trip reroute per candidate doesn't
                         scale to the ~50 stops a busy corridor can add),
                         then greedily accepts cheapest-first as long as the
                         resulting full trip time (driving + buffer + dwell)
                         stays within AUTO_STOP_MAX_DETOUR_PER of the
                         original. apply_auto_stop_addition() does one more
                         real reroute of the final stop list at the end and
                         always returns routed_legs matching the returned
                         stop_ids, so route_factory never has to re-route
                         itself — but whether to call it at all is
                         route_factory._build_trip()'s call.

VALID_TIMETABLE_MODES / VALID_SCHEDULE_MODES stay here as the single source
of truth for the allowed strings — api/route.py's request validation and
route_factory.py's dispatch both read from them, so a new mode is added in
exactly one place (plus the function implementing it and the route_factory
branch that calls it).

Not pluggable, but timing math so it lives here too: build_final_timetable()
and dwell_min() compute the exact, dwell-inclusive arrival/departure at each
stop once departure time and stop types are already fixed. There's only one
correct way to do that (unlike the three concerns above), so it isn't a
strategy — it's a plain function route_factory.py calls once it has what it
needs from a timetable_mode strategy.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from models.params import Composition, TrackInfraCollection, StopInfraCollection
from models.route.trip import StopType
from models.route.route import Schedule, SeasonalSchedule, Season, Frequency
from models.route.routing.rail_router import RailRouter, RoutedLeg, build_router_stops
from models.utils import haversine_m

logger = logging.getLogger(__name__)

MIRROR_MIN = 26 * 60 + 30
"""02:30, expressed 'next day' (1590) on the continuous minutes-from-midnight
scale used throughout (see models.utils.hhmm_to_min). Fixed constant that
timetable_mode='simpleAutomatic' schedules are mirrored around."""

# =============================================================================
# timetable_mode IMPLEMENTATIONS — route_factory._build_trip() picks which
# of these to call based on the request's timetable_mode; nothing here
# branches on the mode string itself.
# =============================================================================


def simple_automatic_timetable(
    stop_ids: list[str],
    composition: Composition,
    routed_legs: list[RoutedLeg],
) -> tuple[list[tuple[str, StopType]], int]:
    """
    Implements timetable_mode="simpleAutomatic". Derive departure time and
    per-stop boarding/alighting from already-routed leg physics — no
    routing happens here, the caller routes once (possibly again, if
    auto_stop_addition changed the stop list) and hands over the resulting
    legs.

    Called once per direction (caller passes this direction's stop_ids and
    routed_legs already in the right order):
      1. Approximate total duration by adding the cheapest possible dwell
         (min of the composition's own boarding/alighting minimums) per
         intermediate stop — a light correction so the mirror point isn't
         thrown off by completely ignoring dwell. Mirror that duration
         around MIRROR_MIN (02:30) to get this direction's departure time.
      2. Walk forward from that departure time using pure leg times (still
         no dwell) to get a provisional clock time at each intermediate
         stop, and classify it boarding (before 02:30) or alighting (at/after
         02:30). First stop is always boarding, last always alighting,
         regardless of clock time — they're termini by position, not by
         the mirror rule.

    The real dwell-inclusive timetable is built afterwards via
    build_final_timetable() (below), using the stop types and departure
    time returned here — that final pass will land a few minutes later
    at each stop than the provisional classification pass, an accepted
    approximation for this mode (a stop within ~2 min of 02:30 could in
    theory land on the other side of the boundary once real dwell is
    added; not worth iterating to convergence here).

    Returns (stop_inputs with classified StopType, departure_time_min).
    """
    n = len(stop_ids)
    pure_leg_times = [leg.total_time_min for leg in routed_legs]

    min_dwell = min(
        composition.min_boarding_time_min, composition.min_alighting_time_min
    )
    approx_dwell_total = min_dwell * max(n - 2, 0)  # only intermediate stops get dwell
    total_duration = sum(pure_leg_times) + approx_dwell_total

    departure_time_min = round(MIRROR_MIN - total_duration / 2)

    stop_types: list[StopType] = [StopType.BOARDING]  # first stop: always boarding
    provisional_clock = departure_time_min
    for i in range(1, n - 1):
        provisional_clock += pure_leg_times[i - 1]
        stop_types.append(
            StopType.BOARDING if provisional_clock < MIRROR_MIN else StopType.ALIGHTING
        )
    if n > 1:
        stop_types.append(StopType.ALIGHTING)  # last stop: always alighting

    stop_inputs = list(zip(stop_ids, stop_types))
    return stop_inputs, departure_time_min


VALID_TIMETABLE_MODES = frozenset({"simpleAutomatic"})
"""Single source of truth for allowed timetable_mode strings — read by both
api/route.py's request validation and route_factory._build_trip()'s switch.
Adding a mode means: add its function above, add it to this set, add a
branch in _build_trip()."""


# =============================================================================
# schedule_mode IMPLEMENTATIONS — route_factory.plan_route() picks which of
# these to call based on the request's schedule_mode (once per route, not
# per trip — schedule is shared across every TripPair); nothing here
# branches on the mode string itself.
# =============================================================================


def always_daily_schedule() -> Schedule:
    """Implements schedule_mode='alwaysDaily': daily frequency in both
    seasons, regardless of actual demand."""
    return Schedule(
        seasonal_schedules=[
            SeasonalSchedule(season=Season.SUMMER, frequency=Frequency.DAILY),
            SeasonalSchedule(season=Season.WINTER, frequency=Frequency.DAILY),
        ]
    )


VALID_SCHEDULE_MODES = frozenset({"alwaysDaily"})
"""Single source of truth for allowed schedule_mode strings — read by both
api/route.py's request validation and route_factory.plan_route()'s switch.
Reserved: a future demand-aware mode can be added here (new function + this
set + a plan_route() branch) without changing the request shape."""


# =============================================================================
# auto_stop_addition IMPLEMENTATION — always runs the full algorithm when
# called; route_factory._build_trip() decides whether to call it at all
# based on the request's auto_stop_addition bool.
# =============================================================================

AUTO_STOP_BUFFER_M = 3_000
"""Max distance (metres) from a stop to the already-routed path for that
stop to be considered a candidate for auto_stop_addition — covers both
stops that sit right on the line and ones merely 'close by'. Fixed
constant, not exposed via the API (see api/route.py's request docstring)."""

AUTO_STOP_MAX_DETOUR_PER = 0.05
"""Max allowed increase in full (driving + buffer + dwell) trip time, as a
fraction of the original trip's time, before auto_stop_addition stops
adding further candidates. Fixed constant, not exposed via the API."""

_DEG_PER_M = 1 / 111_000
"""Rough metres-per-degree constant (~111km/degree of latitude) — only
used for a coarse, generously-margined bounding-box pre-filter below, not
for real distance math (that's haversine_m throughout)."""


@dataclass
class _AutoStopCandidate:
    """One stop from the catalog considered for auto_stop_addition.

    leg_index / along_leg_fraction locate where the candidate belongs in
    the ORIGINAL (pre-addition) stop sequence — leg_index is the index
    into the original routed_legs/stop_ids the candidate sits nearest to
    (it belongs between stop_ids[leg_index] and stop_ids[leg_index + 1]);
    along_leg_fraction (0..1) orders multiple candidates that land on the
    same leg. Both stay fixed to the ORIGINAL geometry even as candidates
    get committed one by one — see apply_auto_stop_addition()'s sort-key
    merge for why that's safe.
    """

    stop_id: str
    detour_distance_m: float
    leg_index: int
    along_leg_fraction: float


def _nearest_point_on_leg(
    lon: float, lat: float, leg_geometry: list[list[float]]
) -> tuple[float, float]:
    """(distance_m, fraction_along) of the point on leg_geometry nearest to
    (lon, lat). The nearest-point search itself runs in raw lon/lat degree
    space via shapely (fine for locating the nearest point — regional leg
    lengths are far too short for degree-space distortion to matter); the
    returned distance is then computed with haversine_m for an accurate
    metres value, matching the buffer/detour math everywhere else.

    NOTE (benchmarked, 2026-07-12): a segment-level shapely STRtree was
    tried here on the theory that a single very long leg (e.g. an
    ~8000-point Stockholm-Roma polyline) would make this whole-leg scan
    the bottleneck behind a slow auto_stop_addition request. Measured
    head-to-head against a realistic 58-stop catalog and an 8000-point
    leg, post-warmup: this whole-leg approach ~29ms, the STRtree version
    ~67ms — GEOS's native LineString.project() is already a tight C loop
    over the whole geometry, and building thousands of individual segment
    objects for an index costs more than the linear scan it replaces at
    this scale. Both are tens of milliseconds regardless — nowhere near
    what a slow request actually costs (see apply_auto_stop_addition()'s
    timing logs for where that time really goes). Kept simple; revisit
    only if the stop catalog grows to the point this is measured to
    matter, with a fresh benchmark at that scale."""
    from shapely.geometry import LineString, Point

    line = LineString(leg_geometry)
    point = Point(lon, lat)
    fraction = line.project(point, normalized=True)
    nearest = line.interpolate(fraction, normalized=True)
    distance_m = haversine_m(lon, lat, nearest.x, nearest.y)
    return distance_m, fraction


def _find_nearby_candidates(
    stop_ids: list[str],
    routed_legs: list[RoutedLeg],
    stop_infra: StopInfraCollection,
) -> list[_AutoStopCandidate]:
    """
    Every stop in the catalog within AUTO_STOP_BUFFER_M of the routed path,
    excluding stops already in stop_ids. A stop near more than one leg is
    kept only once, at its closest leg. Not sorted here — selection order
    (cheapest detour first) is decided by the caller.
    """
    start = time.monotonic()
    existing = set(stop_ids)
    margin_deg = AUTO_STOP_BUFFER_M * _DEG_PER_M * 1.5  # generous safety factor
    best_by_stop: dict[str, _AutoStopCandidate] = {}

    for leg_index, leg in enumerate(routed_legs):
        geometry = leg.geometry
        if len(geometry) < 2:
            continue
        min_lon = min(c[0] for c in geometry) - margin_deg
        max_lon = max(c[0] for c in geometry) + margin_deg
        min_lat = min(c[1] for c in geometry) - margin_deg
        max_lat = max(c[1] for c in geometry) + margin_deg

        for stop_id, stop in stop_infra.all().items():
            if stop_id in existing:
                continue
            if not (min_lon <= stop.lon <= max_lon and min_lat <= stop.lat <= max_lat):
                continue  # cheap pre-filter — skip the shapely call entirely

            distance_m, fraction = _nearest_point_on_leg(stop.lon, stop.lat, geometry)
            if distance_m > AUTO_STOP_BUFFER_M:
                continue

            existing_best = best_by_stop.get(stop_id)
            if existing_best is None or distance_m < existing_best.detour_distance_m:
                best_by_stop[stop_id] = _AutoStopCandidate(
                    stop_id=stop_id,
                    detour_distance_m=distance_m,
                    leg_index=leg_index,
                    along_leg_fraction=fraction,
                )

    candidates = list(best_by_stop.values())
    logger.info(
        "_find_nearby_candidates: %d candidate(s) from %d catalog stops in %.2fs.",
        len(candidates),
        len(stop_infra),
        time.monotonic() - start,
    )
    return candidates


def _estimate_full_trip_time_min(
    stop_ids: list[str],
    routed_legs: list[RoutedLeg],
    composition: Composition,
    tracks: TrackInfraCollection,
    stop_infra: StopInfraCollection,
) -> int:
    """
    Rough driving + buffer + dwell trip time, used only to compare against
    AUTO_STOP_MAX_DETOUR_PER — not the final published schedule. Every
    intermediate stop is conservatively treated as StopType.BOTH (the max
    of boarding/alighting dwell), since real classification only happens
    afterwards via route_factory._build_trip()'s timetable_mode switch and
    this needs to stay independent of timetable_mode.
    """
    total = sum(leg.total_time_min for leg in routed_legs)
    for stop_id in stop_ids[1:-1]:
        country_code = stop_infra.get(stop_id).stop_country_code
        total += dwell_min(StopType.BOTH, country_code, composition, tracks)
    return total


def _candidate_added_time_min(
    candidate: "_AutoStopCandidate",
    stop_ids: list[str],
    routed_legs: list[RoutedLeg],
    composition: Composition,
    tracks: TrackInfraCollection,
    stop_infra: StopInfraCollection,
    router: RailRouter,
    routing_mode: str,
) -> float | None:
    """
    One candidate's cost in isolation: reroute only the leg it sits on
    (leg_start → candidate → leg_end, three points) rather than the whole
    trip, and compare against that leg's original time. Independent of
    every other candidate — this is what makes the calls in
    apply_auto_stop_addition() safe to run concurrently: candidates on
    different legs can never affect each other's routing, and even two
    candidates sharing a leg are each scored against the leg's ORIGINAL
    two endpoints here (an accepted approximation — see that leg's actual
    combined cost is verified for real by the single final reroute after
    selection, whether or not it matches this estimate exactly).

    Returns None (candidate excluded from consideration) if the mini
    reroute itself fails — a single unroutable candidate stop shouldn't
    take down the whole auto_stop_addition pass.
    """
    leg_start_id = stop_ids[candidate.leg_index]
    leg_end_id = stop_ids[candidate.leg_index + 1]
    try:
        sub_legs = router.route(
            stops=build_router_stops(
                [leg_start_id, candidate.stop_id, leg_end_id], stop_infra
            ),
            composition=composition,
            tracks=tracks,
            routing_mode=routing_mode,
        )
    except Exception:
        logger.warning(
            "apply_auto_stop_addition: mini-reroute for '%s' failed — excluding it.",
            candidate.stop_id,
            exc_info=True,
        )
        return None

    original_leg_time_min = routed_legs[candidate.leg_index].total_time_min
    detour_time_min = (
        sum(leg.total_time_min for leg in sub_legs) - original_leg_time_min
    )

    country_code = stop_infra.get(candidate.stop_id).stop_country_code
    dwell_time_min = dwell_min(StopType.BOTH, country_code, composition, tracks)

    return detour_time_min + dwell_time_min


def apply_auto_stop_addition(
    stop_ids: list[str],
    routed_legs: list[RoutedLeg],
    composition: Composition,
    tracks: TrackInfraCollection,
    stop_infra: StopInfraCollection,
    router: RailRouter,
    routing_mode: str,
) -> tuple[list[str], list[RoutedLeg]]:
    """
    Proposes additional worthwhile stops along the already-routed path,
    beyond what the caller supplied. Always runs — route_factory._build_trip()
    only calls this when the request's auto_stop_addition is true; this
    function itself has no enabled/disabled gate.

    Algorithm:
      1. Find every catalog stop within AUTO_STOP_BUFFER_M of routed_legs'
         geometry (_find_nearby_candidates) — covers stops right on the
         line as well as ones merely close by.
      2. Cost every candidate CONCURRENTLY: a 3-point mini-reroute of just
         its own leg (_candidate_added_time_min) rather than a sequential
         whole-trip reroute per candidate — with up to ~50 candidates in
         practice, sequential whole-trip reroutes would be far too slow
         for an interactive request. One thread per candidate; RailRouter's
         underlying requests.Session/connection pool is sized for this
         (see rail_router.py's _CONNECTION_POOL_SIZE).
      3. Sort by added_time_min ascending (cheapest first) and greedily
         accumulate — pure arithmetic now, no further I/O — stopping at
         the first candidate that would push the running total over
         AUTO_STOP_MAX_DETOUR_PER of the original trip's time. Later
         (more expensive) candidates are not added even if they'd
         individually fit, matching the original "stop at first rejection"
         rule now applied to accumulated rather than per-step cost.
      4. One single full-trip reroute of the final stop list, once, for
         the authoritative routed_legs the rest of the pipeline uses — a
         deliberate simplicity trade-off over re-stitching the individual
         mini-routes from step 2 (which would save this one call but need
         special-casing legs with 2+ accepted candidates).

    Each accepted candidate is merged back into the stop sequence by
    (leg_index, along_leg_fraction), so the final stop list always follows
    the route's actual geography regardless of selection order.

    Returns (final_stop_ids, final_routed_legs) — routed_legs always
    matches final_stop_ids, whether or not anything was actually added, so
    route_factory._build_trip() never needs to re-route itself afterwards.
    """
    candidates = _find_nearby_candidates(stop_ids, routed_legs, stop_infra)
    if not candidates:
        return stop_ids, routed_legs

    costing_start = time.monotonic()
    with ThreadPoolExecutor(max_workers=len(candidates)) as pool:
        added_time_by_stop_id: dict[str, float | None] = dict(
            zip(
                (c.stop_id for c in candidates),
                pool.map(
                    lambda c: _candidate_added_time_min(
                        c,
                        stop_ids,
                        routed_legs,
                        composition,
                        tracks,
                        stop_infra,
                        router,
                        routing_mode,
                    ),
                    candidates,
                ),
            )
        )
    logger.info(
        "apply_auto_stop_addition: costed %d candidate(s) concurrently in %.2fs.",
        len(candidates),
        time.monotonic() - costing_start,
    )

    costed_candidates = sorted(
        (c for c in candidates if added_time_by_stop_id[c.stop_id] is not None),
        key=lambda c: added_time_by_stop_id[c.stop_id],
    )

    baseline_time_min = _estimate_full_trip_time_min(
        stop_ids, routed_legs, composition, tracks, stop_infra
    )
    max_extra_min = baseline_time_min * AUTO_STOP_MAX_DETOUR_PER

    committed = [(sid, (i, -1.0)) for i, sid in enumerate(stop_ids)]
    running_extra_min = 0.0
    added_stop_ids: list[str] = []

    for candidate in costed_candidates:
        candidate_time_min = added_time_by_stop_id[candidate.stop_id]
        if running_extra_min + candidate_time_min > max_extra_min:
            logger.info(
                "apply_auto_stop_addition: stopping at '%s' (+%.1fmin) — would "
                "push cumulative added time past budget %.1fmin.",
                candidate.stop_id,
                candidate_time_min,
                max_extra_min,
            )
            break

        # (stop_id, sort_key) merge — original stops carry sort_key=(index,
        # -1.0), which always sorts before any candidate assigned to that
        # same leg (candidates carry fraction in [0, 1]) and after the
        # previous leg's candidates, keeping geographic order regardless
        # of the cheapest-first order candidates were accepted in.
        committed = sorted(
            committed
            + [
                (candidate.stop_id, (candidate.leg_index, candidate.along_leg_fraction))
            ],
            key=lambda entry: entry[1],
        )
        running_extra_min += candidate_time_min
        added_stop_ids.append(candidate.stop_id)

    if not added_stop_ids:
        return stop_ids, routed_legs

    logger.info(
        "apply_auto_stop_addition: added %d stop(s): %s",
        len(added_stop_ids),
        added_stop_ids,
    )
    final_reroute_start = time.monotonic()
    final_stop_ids = [sid for sid, _ in committed]
    final_routed_legs = router.route(
        stops=build_router_stops(final_stop_ids, stop_infra),
        composition=composition,
        tracks=tracks,
        routing_mode=routing_mode,
    )
    logger.info(
        "apply_auto_stop_addition: final reroute of %d stop(s) took %.2fs.",
        len(final_stop_ids),
        time.monotonic() - final_reroute_start,
    )
    return final_stop_ids, final_routed_legs


# =============================================================================
# FINAL TIMETABLE — exact, dwell-inclusive arrival/departure per stop
# =============================================================================


def dwell_min(
    stop_type: StopType,
    country_code: str,
    composition: Composition,
    tracks: TrackInfraCollection,
) -> int:
    """Dwell at one intermediate stop: max of composition/track minimums
    for whichever of boarding/alighting/both applies. 0 for a stop type
    that's neither (shouldn't occur for an intermediate stop, but falls
    back safely rather than raising)."""
    track = tracks.get(country_code)
    candidates: list[int] = []
    if stop_type in (StopType.BOARDING, StopType.BOTH):
        candidates += [composition.min_boarding_time_min, track.min_boarding_time_min]
    if stop_type in (StopType.ALIGHTING, StopType.BOTH):
        candidates += [composition.min_alighting_time_min, track.min_alighting_time_min]
    return max(candidates) if candidates else 0


def build_final_timetable(
    stop_types: list[StopType],
    country_codes: list[str],
    routed_legs: list[RoutedLeg],
    composition: Composition,
    tracks: TrackInfraCollection,
    departure_time_min: int,
) -> list[tuple[int | None, int | None]]:
    """
    Exact, dwell-inclusive (arrival_min, departure_min) per stop, given a
    departure time and stop types that are already fixed (typically the
    output of a timetable_mode strategy above). Not itself a strategy —
    there's only one correct way to turn "departure time + stop types"
    into real clock times, so this is a plain function, not dispatched.

    First stop: arrival=None (it's the origin, nothing to arrive at).
    Last stop: departure=None (journey's over). Every stop in between
    departs at arrival + dwell_min().
    """
    n = len(stop_types)
    clock_min = departure_time_min  # time reached so far
    times: list[tuple[int | None, int | None]] = []

    for i, (stop_type, country_code) in enumerate(zip(stop_types, country_codes)):
        is_first, is_last = i == 0, i == n - 1

        arrival_min = None if is_first else clock_min
        this_dwell = (
            0
            if is_first or is_last
            else dwell_min(stop_type, country_code, composition, tracks)
        )
        departure_min = (
            None if is_last else (clock_min if is_first else arrival_min + this_dwell)
        )

        if not is_last:
            clock_min = departure_min + routed_legs[i].total_time_min

        times.append((arrival_min, departure_min))

    return times
