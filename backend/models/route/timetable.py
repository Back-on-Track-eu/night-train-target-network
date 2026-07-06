"""
timetable.py
============
Pluggable per-direction scheduling/stop-list logic for route planning.
Kept separate from route_factory.py's build pipeline so new strategies can
be added (or the current ones swapped out) without touching orchestration.
route_factory.py does DB lookups and object assembly only — every question
of "what time is it at this stop" is answered here, whether that's the
rough first-pass answer (timetable_mode) or the final exact one
(build_final_timetable).

Three independent concerns live here, each dispatched by a request-level
string/bool field:

  timetable_mode      — departure time + boarding/alighting classification
                         for one direction's stop list. schedule_and_classify()
                         dispatches to the named strategy.

  schedule_mode       — seasonal frequency for the route as a whole.
                         build_schedule() dispatches to the named strategy.
                         Currently only "alwaysDaily" (daily regardless of
                         demand) — a future demand-aware strategy can be
                         added here without touching route_factory.py.

  auto_stop_addition  — whether to propose additional stops along a route
                         beyond what the caller supplied. Takes the routed
                         legs as context (needed to find real stops along
                         a path), even though that context goes unused
                         today — currently always a no-op regardless of
                         value. apply_auto_stop_addition() is the single
                         call site route_factory.py uses, so a real
                         implementation can be dropped in later without
                         touching the caller.

Not pluggable, but timing math so it lives here too: build_final_timetable()
and dwell_min() compute the exact, dwell-inclusive arrival/departure at each
stop once departure time and stop types are already fixed. There's only one
correct way to do that (unlike the three concerns above), so it isn't a
strategy — it's a plain function route_factory.py calls once it has what it
needs from a timetable_mode strategy.
"""

from __future__ import annotations

import logging

from models.params import Composition, TrackInfraCollection
from models.route.trip import StopType
from models.route.route import Schedule, SeasonalSchedule, Season, Frequency
from models.route.routing.rail_router import RoutedLeg

logger = logging.getLogger(__name__)

MIRROR_MIN = 26 * 60 + 30
"""02:30, expressed 'next day' (1590) on the continuous minutes-from-midnight
scale used throughout (see models.utils.hhmm_to_min). Fixed constant that
timetable_mode='simpleAutomatic' schedules are mirrored around."""

# =============================================================================
# timetable_mode STRATEGIES
# =============================================================================

def _simple_automatic(
    stop_ids: list[str], composition: Composition, routed_legs: list[RoutedLeg],
) -> tuple[list[tuple[str, StopType]], int]:
    """
    Derive departure time and per-stop boarding/alighting from already-routed
    leg physics — no routing happens here, the caller routes once (possibly
    twice, if auto_stop_addition changes the stop list) and hands over the
    resulting legs.

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

    min_dwell = min(composition.min_boarding_time_min, composition.min_alighting_time_min)
    approx_dwell_total = min_dwell * max(n - 2, 0)  # only intermediate stops get dwell
    total_duration = sum(pure_leg_times) + approx_dwell_total

    departure_time_min = round(MIRROR_MIN - total_duration / 2)

    stop_types: list[StopType] = [StopType.BOARDING]  # first stop: always boarding
    provisional_clock = departure_time_min
    for i in range(1, n - 1):
        provisional_clock += pure_leg_times[i - 1]
        stop_types.append(StopType.BOARDING if provisional_clock < MIRROR_MIN else StopType.ALIGHTING)
    if n > 1:
        stop_types.append(StopType.ALIGHTING)  # last stop: always alighting

    stop_inputs = list(zip(stop_ids, stop_types))
    return stop_inputs, departure_time_min

_TIMETABLE_MODE_STRATEGIES = {
    "simpleAutomatic": _simple_automatic,
}

VALID_TIMETABLE_MODES = frozenset(_TIMETABLE_MODE_STRATEGIES)
"""Public — api/route.py validates against this instead of hardcoding the list."""

def schedule_and_classify(
    timetable_mode: str, stop_ids: list[str],
    composition: Composition, routed_legs: list[RoutedLeg],
) -> tuple[list[tuple[str, StopType]], int]:
    """Dispatches to the named timetable_mode strategy. Raises ValueError if unknown."""
    strategy = _TIMETABLE_MODE_STRATEGIES.get(timetable_mode)
    if strategy is None:
        raise ValueError(f"Unknown timetable_mode '{timetable_mode}'. Supported: {sorted(_TIMETABLE_MODE_STRATEGIES)}.")
    return strategy(stop_ids=stop_ids, composition=composition, routed_legs=routed_legs)

# =============================================================================
# schedule_mode STRATEGIES
# =============================================================================

def _always_daily() -> Schedule:
    """schedule_mode='alwaysDaily': daily frequency in both seasons,
    regardless of actual demand."""
    return Schedule(seasonal_schedules=[
        SeasonalSchedule(season=Season.SUMMER, frequency=Frequency.DAILY),
        SeasonalSchedule(season=Season.WINTER, frequency=Frequency.DAILY),
    ])

_SCHEDULE_MODE_STRATEGIES = {
    "alwaysDaily": _always_daily,
}

VALID_SCHEDULE_MODES = frozenset(_SCHEDULE_MODE_STRATEGIES)
"""Public — api/route.py validates against this instead of hardcoding the list."""

def build_schedule(schedule_mode: str) -> Schedule:
    """Dispatches to the named schedule_mode strategy. Raises ValueError if unknown.
    Reserved for a future demand-aware strategy that sets frequency based on
    actual demand instead of always assuming daily."""
    strategy = _SCHEDULE_MODE_STRATEGIES.get(schedule_mode)
    if strategy is None:
        raise ValueError(f"Unknown schedule_mode '{schedule_mode}'. Supported: {sorted(_SCHEDULE_MODE_STRATEGIES)}.")
    return strategy()

# =============================================================================
# auto_stop_addition STRATEGIES
# =============================================================================

def apply_auto_stop_addition(
    enabled: bool, stop_ids: list[str], routed_legs: list[RoutedLeg],
) -> list[str]:
    """
    Whether to propose additional worthwhile stops along the route beyond
    what the caller supplied. Takes the already-routed legs (geometry +
    physics) as context, since finding real stops "along the route" needs
    the actual path — not just the stop_id list — even though that context
    goes unused today.

    Currently a no-op regardless of value — always returns stop_ids
    unchanged. Reserved for a future implementation that looks along
    routed_legs' geometry for stops worth adding. If it ever does change
    the list, the caller (route_factory._build_trip()) re-routes with the
    new list before doing anything else with it — routed_legs here must
    never be reused as-is against a changed stop_ids. Logs at info level
    when enabled=True is requested, purely so it's visible during manual
    testing that nothing was actually added yet.
    """
    if enabled:
        logger.info("apply_auto_stop_addition: enabled=True requested but not yet implemented — no-op.")
    return stop_ids

# =============================================================================
# FINAL TIMETABLE — exact, dwell-inclusive arrival/departure per stop
# =============================================================================

def dwell_min(
    stop_type: StopType, country_code: str, composition: Composition, tracks: TrackInfraCollection,
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
    stop_types: list[StopType], country_codes: list[str], routed_legs: list[RoutedLeg],
    composition: Composition, tracks: TrackInfraCollection, departure_time_min: int,
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
        this_dwell = 0 if is_first or is_last else dwell_min(stop_type, country_code, composition, tracks)
        departure_min = None if is_last else (clock_min if is_first else arrival_min + this_dwell)

        if not is_last:
            clock_min = departure_min + routed_legs[i].total_time_min

        times.append((arrival_min, departure_min))

    return times