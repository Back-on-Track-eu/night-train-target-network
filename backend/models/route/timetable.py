"""
timetable.py
============
Per-direction scheduling/stop-list logic for route planning — the
implementations, not the switch. Which implementation runs for a given
request is decided by route_factory.py (at whichever level owns the
relevant context — per-trip in _build_trip(), per-route in plan_route());
this module holds one function per named strategy and never branches on
timetable_mode/schedule_mode/auto_stop_addition itself.

Three request-level concerns have their logic here, each with its switch
living in route_factory.py:

  timetable_mode      — departure time + stop classification (boarding/
                         night/alighting) for one direction's stop list.
                         One function per mode; route_factory._build_trip()
                         picks which to call:
                           simple_automatic_timetable() — "simpleAutomatic":
                             trip duration mirrored around MIRROR_MIN.
                           simple_automatic_fixed_night_timetable() —
                             "simpleAutomaticWithFixedNight": the caller's
                             fixed_night_interval [A, B] is what gets
                             centered on MIRROR_MIN instead, stretched with
                             per-leg slack if naturally shorter than the
                             night window (dep(A) by 23:59, arr(B) from
                             05:00) — see the function for the full rules.
                         Both classify intermediate stops with the shared
                         NIGHT_START_MIN/NIGHT_END_MIN rule (boarding if
                         departing strictly before 00:00, alighting if
                         arriving at/after 05:00, night otherwise);
                         fixed_night_speed_warning() is the fixed-night
                         mode's post-build quality check.

  schedule_mode       — seasonal frequency for the route as a whole. One
                         function per mode (currently always_daily_schedule()
                         for "alwaysDaily"); route_factory.plan_route()
                         picks which to call — a route-level decision made
                         once, not per trip, since schedule is shared
                         across every TripPair.

  auto_stop_addition  — additional stops along a route beyond what the
                         caller supplied. Split into a shared search+cost
                         phase and two mode-specific consumers:
                           find_and_cost_auto_stop_candidates() — every
                             catalog stop close to the already-routed
                             geometry, each costed CONCURRENTLY with one
                             3-point mini-reroute of its own leg (a
                             sequential whole-trip reroute per candidate
                             doesn't scale to the ~50 stops a busy corridor
                             can add). Shared by both modes below.
                           apply_auto_stop_addition() — mode "add": greedy
                             cheapest-first acceptance within the
                             AUTO_STOP_MAX_DETOUR_PER budget, then one real
                             reroute of the final stop list; always returns
                             routed_legs matching the returned stop_ids so
                             route_factory never re-routes itself.
                           suggest_auto_stops() — mode "suggest": no
                             selection, no budget, no reroute — just every
                             costed candidate as an AutoStopSuggestion
                             (with added_time_min), in geographic order
                             along the route, for the caller to decide.
                         Whether either is called at all (and mode "off"
                         skipping both) is route_factory._build_trip()'s
                         switch.

VALID_TIMETABLE_MODES / VALID_SCHEDULE_MODES / VALID_AUTO_STOP_ADDITION_MODES
stay here as the single source of truth for the allowed strings —
api/route.py's request validation and route_factory.py's dispatch both read
from them, so a new mode is added in exactly one place (plus the function
implementing it and the route_factory branch that calls it).

Standard values (MIRROR_MIN, AUTO_STOP_BUFFER_M, AUTO_STOP_MAX_DETOUR_PER)
live in models/route/version.py — the single registry of every fixed
assumption the route model makes.

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
from models.route.trip import Segment, StopType, TimetableWarning
from models.route.route import Schedule, SeasonalSchedule, Season, Frequency
from models.route.routing.rail_router import RailRouter, RoutedLeg, build_router_stops
from models.route.version import (
    MIRROR_MIN,
    NIGHT_START_MIN,
    NIGHT_END_MIN,
    FIXED_NIGHT_MIN_SPEED_RATIO,
    AUTO_STOP_BUFFER_M,
    AUTO_STOP_MAX_DETOUR_PER,
)
from models.utils import haversine_m

logger = logging.getLogger(__name__)

# =============================================================================
# timetable_mode IMPLEMENTATIONS — route_factory._build_trip() picks which
# of these to call based on the request's timetable_mode; nothing here
# branches on the mode string itself.
# =============================================================================


def _classify_stop_type(arrival_min: int, departure_min: int) -> StopType:
    """Shared three-way classification for INTERMEDIATE stops, used by every
    timetable_mode (termini are always boarding/alighting by position, the
    caller's concern). Boarding is judged on DEPARTURE time, alighting on
    ARRIVAL time:
      departure strictly before NIGHT_START_MIN (00:00+1) → boarding
      arrival at/after NIGHT_END_MIN (05:00+1)            → alighting
      otherwise                                            → night
    The two conditions can't both hold (that would need arrival >= Y and
    departure < X with Y > X), so precedence never matters.
    """
    if departure_min < NIGHT_START_MIN:
        return StopType.BOARDING
    if arrival_min >= NIGHT_END_MIN:
        return StopType.ALIGHTING
    return StopType.NIGHT


def _provisional_offsets(
    pure_leg_times: list[int], slack_per_leg: list[int], min_dwell: int
) -> tuple[list[int], list[int]]:
    """Cumulative provisional (arrival, departure) offsets from trip
    departure per stop — pure leg times plus slack per leg, min-dwell
    approximation at intermediate stops, no dwell at termini. The common
    positioning/classification arithmetic behind both timetable modes."""
    n = len(pure_leg_times) + 1
    arr_offset = [0] * n
    dep_offset = [0] * n
    for i in range(1, n):
        arr_offset[i] = dep_offset[i - 1] + pure_leg_times[i - 1] + slack_per_leg[i - 1]
        dep_offset[i] = arr_offset[i] + (min_dwell if i < n - 1 else 0)
    return arr_offset, dep_offset


def _classify_stops(
    departure_time_min: int, arr_offset: list[int], dep_offset: list[int]
) -> list[StopType]:
    """Stop types for a whole direction given its departure time and
    provisional offsets: first always boarding, last always alighting
    (termini by position), everything between via _classify_stop_type()
    on its provisional arrival/departure clock times."""
    n = len(arr_offset)
    stop_types: list[StopType] = [StopType.BOARDING]
    for i in range(1, n - 1):
        stop_types.append(
            _classify_stop_type(
                departure_time_min + arr_offset[i], departure_time_min + dep_offset[i]
            )
        )
    if n > 1:
        stop_types.append(StopType.ALIGHTING)
    return stop_types


def simple_automatic_timetable(
    stop_ids: list[str],
    composition: Composition,
    routed_legs: list[RoutedLeg],
) -> tuple[list[tuple[str, StopType]], int]:
    """
    Implements timetable_mode="simpleAutomatic". Derive departure time and
    per-stop classification from already-routed leg physics — no
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
      2. Walk forward from that departure time to a provisional arrival
         AND departure clock time per intermediate stop (same min-dwell
         approximation) and classify via _classify_stop_type(): boarding
         if it departs strictly before 00:00, alighting if it arrives
         at/after 05:00, night otherwise. First stop is always boarding,
         last always alighting, regardless of clock time — they're
         termini by position, not by the threshold rule.

    The real dwell-inclusive timetable is built afterwards via
    build_final_timetable() (below), using the stop types and departure
    time returned here — that final pass can land a few minutes off the
    provisional classification pass (real dwell vs the min-dwell
    approximation), an accepted approximation for this mode (a stop
    within a couple of minutes of a threshold could in theory land on the
    other side of the boundary once real dwell is added; not worth
    iterating to convergence here).

    Returns (stop_inputs with classified StopType, departure_time_min).
    """
    pure_leg_times = [leg.total_time_min for leg in routed_legs]
    min_dwell = min(
        composition.min_boarding_time_min, composition.min_alighting_time_min
    )
    arr_offset, dep_offset = _provisional_offsets(
        pure_leg_times, [0] * len(routed_legs), min_dwell
    )

    total_duration = arr_offset[-1]  # legs + min-dwell at every intermediate stop
    departure_time_min = round(MIRROR_MIN - total_duration / 2)

    stop_types = _classify_stops(departure_time_min, arr_offset, dep_offset)
    stop_inputs = list(zip(stop_ids, stop_types))
    return stop_inputs, departure_time_min


def simple_automatic_fixed_night_timetable(
    stop_ids: list[str],
    composition: Composition,
    routed_legs: list[RoutedLeg],
    fixed_night_interval: list[str],
) -> tuple[list[tuple[str, StopType]], int, list[int]]:
    """
    Implements timetable_mode="simpleAutomaticWithFixedNight". Same
    provisional-physics technique as simple_automatic_timetable(), but the
    schedule is positioned so the MIDPOINT of [departure at interval start
    A, arrival at interval end B] lands on MIRROR_MIN — instead of the
    midpoint of the whole trip. Lets a demand-strong feeder section keep
    evening departures while the night window sits on a chosen corridor
    section; plain simpleAutomatic is the special case A=first, B=last.

    fixed_night_interval: [A, B] stop IDs in THIS direction's travel order
    (the caller reverses it for the return trip); both must be in stop_ids
    with A before B. The interval may span any number of legs — everything
    below works on cumulative offsets, not per-leg positions.

    Night-window guarantee + stretching: the schedule must satisfy
    dep(A) < NIGHT_START_MIN (departs 23:59 at the latest — boarding is
    judged on departure time, strictly before the window) and
    arr(B) >= NIGHT_END_MIN (arrives 05:00 at the earliest — alighting is
    judged on arrival time). By construction that also guarantees every
    stop before A classifies boarding and every stop after B alighting.
    The minimum interval span is therefore
    NIGHT_END_MIN - NIGHT_START_MIN + 1 (301 min): a naturally shorter
    interval is stretched to exactly that minimum by distributing slack
    minutes across the interval's legs, proportionally to each leg's pure
    time (largest-remainder rounding so the total is exact). The ideal
    MIRROR_MIN midpoint is then clamped into the window's constraints —
    for a minimally-stretched interval that pins dep(A)=23:59 /
    arr(B)=05:00 exactly (midpoint 02:29.5; minimal stretch deliberately
    wins over exact midpoint symmetry). The slack ends up on
    Segment.slack_time_min via the returned slack_per_leg — route_factory
    threads it through build_final_timetable() and segment assembly.
    Whether the stretch made the interval unreasonably slow is checked
    separately, after the final timetable exists — see
    fixed_night_speed_warning().

    Provisional offsets use the same min-dwell approximation and the same
    accepted final-pass deviation as simple_automatic_timetable().

    Returns (stop_inputs with classified StopType, departure_time_min,
    slack_per_leg aligned with routed_legs — zeros outside the interval).
    """
    a_idx = _interval_index(stop_ids, fixed_night_interval[0], "start")
    b_idx = _interval_index(stop_ids, fixed_night_interval[1], "end")
    if a_idx >= b_idx:
        raise ValueError(
            f"fixed_night_interval start '{fixed_night_interval[0]}' must come "
            f"before end '{fixed_night_interval[1]}' in travel order."
        )

    pure_leg_times = [leg.total_time_min for leg in routed_legs]
    min_dwell = min(
        composition.min_boarding_time_min, composition.min_alighting_time_min
    )

    no_slack = [0] * len(routed_legs)
    arr_natural, dep_natural = _provisional_offsets(pure_leg_times, no_slack, min_dwell)
    natural_span = arr_natural[b_idx] - dep_natural[a_idx]

    # dep(A) <= NIGHT_START_MIN - 1 and arr(B) >= NIGHT_END_MIN together
    # need at least this much span between the two.
    required_span = NIGHT_END_MIN - (NIGHT_START_MIN - 1)
    slack_total = max(0, required_span - natural_span)

    slack_per_leg = no_slack
    if slack_total > 0:
        slack_per_leg = _distribute_slack(
            slack_total, pure_leg_times, first_leg=a_idx, last_leg=b_idx - 1
        )
        logger.info(
            "simple_automatic_fixed_night_timetable: interval [%s, %s] spans "
            "%dmin naturally, %dmin required — stretched by %dmin.",
            fixed_night_interval[0],
            fixed_night_interval[1],
            natural_span,
            required_span,
            slack_total,
        )

    arr_offset, dep_offset = _provisional_offsets(
        pure_leg_times, slack_per_leg, min_dwell
    )
    span = arr_offset[b_idx] - dep_offset[a_idx]  # natural_span + slack_total

    # Ideal: interval midpoint on MIRROR_MIN — then clamped into the hard
    # window constraints, which always admit a value since span >=
    # required_span. Minimal-stretch intervals land on the clamp bounds
    # (dep(A)=23:59, arr(B)=05:00) rather than the exact midpoint.
    dep_a = round(MIRROR_MIN - span / 2)
    dep_a = min(dep_a, NIGHT_START_MIN - 1)
    dep_a = max(dep_a, NIGHT_END_MIN - span)
    departure_time_min = dep_a - dep_offset[a_idx]

    stop_types = _classify_stops(departure_time_min, arr_offset, dep_offset)
    stop_inputs = list(zip(stop_ids, stop_types))
    return stop_inputs, departure_time_min, slack_per_leg


def _interval_index(stop_ids: list[str], stop_id: str, role: str) -> int:
    """Index of a fixed_night_interval endpoint in stop_ids, with a domain
    error naming the missing endpoint — api/route.py validates against the
    caller's own stops, this re-checks against the possibly auto-extended
    final list (auto_stop_addition only ever inserts, so a miss here means
    the request validation was bypassed)."""
    try:
        return stop_ids.index(stop_id)
    except ValueError:
        raise ValueError(
            f"fixed_night_interval {role} stop '{stop_id}' is not in the "
            f"trip's stop list."
        ) from None


def _distribute_slack(
    slack_total: int, pure_leg_times: list[int], first_leg: int, last_leg: int
) -> list[int]:
    """slack_total minutes spread over legs first_leg..last_leg (inclusive),
    proportionally to each leg's pure time, as whole minutes summing exactly
    to slack_total (largest-remainder rounding). Legs outside the interval
    get 0. Falls back to an even split if the interval's pure times sum to 0
    (degenerate, but must not divide by zero)."""
    slack_per_leg = [0] * len(pure_leg_times)
    interval = list(range(first_leg, last_leg + 1))
    interval_time = sum(pure_leg_times[i] for i in interval)

    if interval_time <= 0:
        base, remainder = divmod(slack_total, len(interval))
        for k, i in enumerate(interval):
            slack_per_leg[i] = base + (1 if k < remainder else 0)
        return slack_per_leg

    exact = [slack_total * pure_leg_times[i] / interval_time for i in interval]
    floored = [int(x) for x in exact]
    remainder = slack_total - sum(floored)
    by_fraction = sorted(
        range(len(interval)), key=lambda k: exact[k] - floored[k], reverse=True
    )
    for k in by_fraction[:remainder]:
        floored[k] += 1
    for k, i in enumerate(interval):
        slack_per_leg[i] = floored[k]
    return slack_per_leg


def fixed_night_speed_warning(
    segments: list[Segment], fixed_night_interval: list[str]
) -> TimetableWarning | None:
    """
    Post-build quality check for timetable_mode="simpleAutomaticWithFixedNight":
    compares the fixed interval's timetable speed (elapsed dep(A)→arr(B),
    slack and intermediate dwell included) against its pure routing speed
    (driving + dynamics + buffer only). Stretching a naturally short
    interval to cover the night window can make it arbitrarily slow — below
    FIXED_NIGHT_MIN_SPEED_RATIO this returns a "fixed_night_stretch_slow"
    TimetableWarning for the trip's general_parameters.timetable_warnings;
    None otherwise. A warning, never an error — the route still returns.

    Runs on the final assembled segments (real dwell, real slack), not the
    provisional physics the timetable strategy positioned with.
    """
    stop_ids = [segments[0].from_stop.stop_id] + [s.to_stop.stop_id for s in segments]
    a_idx = _interval_index(stop_ids, fixed_night_interval[0], "start")
    b_idx = _interval_index(stop_ids, fixed_night_interval[1], "end")

    interval_segments = segments[a_idx:b_idx]
    interval_km = sum(s.distance_m for s in interval_segments) / 1000
    physics_min = sum(
        s.driving_time_min + s.dynamics_time_min + s.buffer_time_min
        for s in interval_segments
    )
    dep_a = segments[a_idx].from_stop.departure_time_min
    arr_b = segments[b_idx - 1].to_stop.arrival_time_min
    timetable_min = arr_b - dep_a

    if physics_min <= 0 or timetable_min <= 0:
        return None  # degenerate interval — nothing meaningful to compare

    routing_speed_kmh = interval_km / (physics_min / 60)
    timetable_speed_kmh = interval_km / (timetable_min / 60)
    ratio = timetable_speed_kmh / routing_speed_kmh
    if ratio >= FIXED_NIGHT_MIN_SPEED_RATIO:
        return None

    logger.info(
        "fixed_night_speed_warning: interval [%s, %s] timetable speed "
        "%.1fkm/h vs routing speed %.1fkm/h (ratio %.2f < %.2f).",
        fixed_night_interval[0],
        fixed_night_interval[1],
        timetable_speed_kmh,
        routing_speed_kmh,
        ratio,
        FIXED_NIGHT_MIN_SPEED_RATIO,
    )
    return TimetableWarning(
        code="fixed_night_stretch_slow",
        interval=(fixed_night_interval[0], fixed_night_interval[1]),
        timetable_speed_kmh=round(timetable_speed_kmh, 1),
        routing_speed_kmh=round(routing_speed_kmh, 1),
        ratio=round(ratio, 2),
    )


VALID_TIMETABLE_MODES = frozenset({"simpleAutomatic", "simpleAutomaticWithFixedNight"})
"""Single source of truth for allowed timetable_mode strings — read by both
api/route.py's request validation and route_factory._build_trip()'s switch.
Adding a mode means: add its function above, add it to this set, add a
branch in _build_trip(). "simpleAutomaticWithFixedNight" additionally
requires the request's fixed_night_interval, validated in api/route.py and
threaded through TripPairInput."""


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
# auto_stop_addition IMPLEMENTATION — search + costing shared by modes "add"
# (apply_auto_stop_addition) and "suggest" (suggest_auto_stops); route_
# factory._build_trip() decides which of them to call, if any ("off").
# =============================================================================

VALID_AUTO_STOP_ADDITION_MODES = frozenset({"off", "add", "suggest"})
"""Single source of truth for allowed auto_stop_addition strings — read by
both api/route.py's request validation and route_factory._build_trip()'s
switch. "off": caller's stop list returned unmodified, no search. "add":
search + cost + greedy addition within the detour budget. "suggest":
search + cost like "add", but nothing is added — every costed candidate is
returned as an AutoStopSuggestion instead, budget deliberately not applied."""

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


@dataclass(frozen=True)
class AutoStopSuggestion:
    """One suggested additional stop for mode "suggest" — public output
    type, serialized by api/helpers/route_serialize.py into the response's
    suggested_stops list. added_time_min is the full trip-time increase
    (detour + dwell) the stop would cost if implemented — same figure the
    greedy selection in mode "add" budgets against."""

    stop_id: str
    stop_name: str
    country_code: str
    lat: float
    lon: float
    added_time_min: float


def _nearest_point_on_line(lon: float, lat: float, line) -> tuple[float, float]:
    """(distance_m, fraction_along) of the point on a prebuilt shapely
    LineString nearest to (lon, lat). The nearest-point search itself runs
    in raw lon/lat degree space (fine for locating the nearest point —
    regional leg lengths are far too short for degree-space distortion to
    matter); the returned distance is then computed with haversine_m for an
    accurate metres value, matching the buffer/detour math everywhere else.

    The caller builds the LineString once per leg and reuses it across all
    stops checked against that leg — constructing an ~8000-point LineString
    per (stop, leg) pair was the search step's dominant Python-side cost.

    NOTE (benchmarked, 2026-07-12): a segment-level shapely STRtree was
    tried on the theory that a single very long leg (e.g. an ~8000-point
    Stockholm-Roma polyline) would make this whole-line scan the bottleneck
    behind a slow auto_stop_addition request. Measured head-to-head against
    a realistic 58-stop catalog and an 8000-point leg, post-warmup: this
    whole-line approach ~29ms, the STRtree version ~67ms — GEOS's native
    LineString.project() is already a tight C loop over the whole geometry,
    and building thousands of individual segment objects for an index costs
    more than the linear scan it replaces at this scale. Kept simple;
    revisit only if measured to matter at a much larger catalog scale."""
    from shapely.geometry import Point

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
    is decided by the caller.

    Two cheap pre-filters run before any shapely work, in order:
      1. Touched-country filter: the catalog is cut down to stops in
         countries the routed legs actually pass through — read straight
         off each leg's country_distance_shares, which RailRouter already
         attributed via point-in-polygon during routing, so this is
         effectively a free spatial join between route and country
         geometries (no new query, no new geometry math). With a
         continental catalog and a route touching a handful of countries
         this removes the large majority of stops before any per-leg work.
         Known edge + planned NUTS-1 refinement: see OPEN_TODOS
         ["auto_stop_nuts1_prefilter"] in models/route/version.py.
      2. Per-leg bounding box (with a generous margin over
         AUTO_STOP_BUFFER_M): skips the shapely nearest-point call for
         stops that can't possibly be within the buffer of this leg.
    """
    start = time.monotonic()
    existing = set(stop_ids)
    touched_countries = {
        cc
        for leg in routed_legs
        for cc in leg.country_distance_shares
        if cc != "UNK"  # open water/ferry sentinel — no stop can be "in" it
    }
    pool = {
        stop_id: stop
        for stop_id, stop in stop_infra.all().items()
        if stop_id not in existing and stop.stop_country_code in touched_countries
    }

    margin_deg = AUTO_STOP_BUFFER_M * _DEG_PER_M * 1.5  # generous safety factor
    best_by_stop: dict[str, _AutoStopCandidate] = {}
    from shapely.geometry import LineString

    for leg_index, leg in enumerate(routed_legs):
        geometry = leg.geometry
        if len(geometry) < 2:
            continue
        min_lon = min(c[0] for c in geometry) - margin_deg
        max_lon = max(c[0] for c in geometry) + margin_deg
        min_lat = min(c[1] for c in geometry) - margin_deg
        max_lat = max(c[1] for c in geometry) + margin_deg

        line = None  # built lazily, once per leg, only if any stop passes the bbox
        for stop_id, stop in pool.items():
            if not (min_lon <= stop.lon <= max_lon and min_lat <= stop.lat <= max_lat):
                continue
            if line is None:
                line = LineString(geometry)

            distance_m, fraction = _nearest_point_on_line(stop.lon, stop.lat, line)
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
        "_find_nearby_candidates: %d candidate(s) from %d catalog stops "
        "(%d after touched-country prefilter) in %.2fs.",
        len(candidates),
        len(stop_infra),
        len(pool),
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
    Rough driving + dynamics + buffer + dwell trip time (total_time_min per
    leg), used only to compare against
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
    candidate: _AutoStopCandidate,
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
    find_and_cost_auto_stop_candidates() safe to run concurrently:
    candidates on different legs can never affect each other's routing,
    and even two candidates sharing a leg are each scored against the
    leg's ORIGINAL two endpoints here (an accepted approximation — the
    leg's actual combined cost is verified for real by mode "add"'s single
    final reroute after selection, whether or not it matches this estimate
    exactly).

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
            "auto_stop_addition: mini-reroute for '%s' failed — excluding it.",
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


def find_and_cost_auto_stop_candidates(
    stop_ids: list[str],
    routed_legs: list[RoutedLeg],
    composition: Composition,
    tracks: TrackInfraCollection,
    stop_infra: StopInfraCollection,
    router: RailRouter,
    routing_mode: str,
) -> list[tuple[_AutoStopCandidate, float]]:
    """
    Shared search + costing phase for modes "add" and "suggest":
      1. Find every catalog stop within AUTO_STOP_BUFFER_M of routed_legs'
         geometry (_find_nearby_candidates — prefiltered to route-touched
         countries, see that function).
      2. Cost every candidate CONCURRENTLY: a 3-point mini-reroute of just
         its own leg (_candidate_added_time_min) rather than a sequential
         whole-trip reroute per candidate — with up to ~50 candidates in
         practice, sequential whole-trip reroutes would be far too slow
         for an interactive request. One thread per candidate; RailRouter's
         underlying requests.Session/connection pool is sized for this
         (see rail_router.py's _CONNECTION_POOL_SIZE).

    Returns (candidate, added_time_min) pairs, unsorted — candidates whose
    mini-reroute failed are excluded. Selection order (cheapest-first for
    "add", geographic for "suggest") is each consumer's own concern.
    """
    candidates = _find_nearby_candidates(stop_ids, routed_legs, stop_infra)
    if not candidates:
        return []

    costing_start = time.monotonic()
    with ThreadPoolExecutor(max_workers=len(candidates)) as pool:
        added_times = list(
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
            )
        )
    logger.info(
        "find_and_cost_auto_stop_candidates: costed %d candidate(s) "
        "concurrently in %.2fs.",
        len(candidates),
        time.monotonic() - costing_start,
    )
    return [
        (candidate, added_time_min)
        for candidate, added_time_min in zip(candidates, added_times)
        if added_time_min is not None
    ]


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
    Implements auto_stop_addition="add": adds worthwhile stops along the
    already-routed path, beyond what the caller supplied. Always runs the
    full algorithm — route_factory._build_trip() only calls this for mode
    "add"; this function itself has no mode gate.

    Algorithm:
      1./2. Shared search + concurrent costing —
         find_and_cost_auto_stop_candidates() above.
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
    costed_candidates = find_and_cost_auto_stop_candidates(
        stop_ids, routed_legs, composition, tracks, stop_infra, router, routing_mode
    )
    if not costed_candidates:
        return stop_ids, routed_legs
    costed_candidates.sort(key=lambda pair: pair[1])

    baseline_time_min = _estimate_full_trip_time_min(
        stop_ids, routed_legs, composition, tracks, stop_infra
    )
    max_extra_min = baseline_time_min * AUTO_STOP_MAX_DETOUR_PER

    committed = [(sid, (i, -1.0)) for i, sid in enumerate(stop_ids)]
    running_extra_min = 0.0
    added_stop_ids: list[str] = []

    for candidate, candidate_time_min in costed_candidates:
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


def suggest_auto_stops(
    stop_ids: list[str],
    routed_legs: list[RoutedLeg],
    composition: Composition,
    tracks: TrackInfraCollection,
    stop_infra: StopInfraCollection,
    router: RailRouter,
    routing_mode: str,
) -> list[AutoStopSuggestion]:
    """
    Implements auto_stop_addition="suggest": same search + costing as mode
    "add" (find_and_cost_auto_stop_candidates), but nothing is added and
    nothing is rerouted — the route stays exactly the caller's own stop
    list ("off" behaviour) and every costed candidate is returned as an
    AutoStopSuggestion instead, in geographic order along the route
    (leg_index, then fraction along that leg).

    The AUTO_STOP_MAX_DETOUR_PER budget is deliberately NOT applied here:
    "suggest" is informational — the full costed candidate list with each
    stop's added_time_min lets the caller make their own selection, budget
    or no budget. Candidates whose mini-reroute failed are excluded, as in
    mode "add".
    """
    costed_candidates = find_and_cost_auto_stop_candidates(
        stop_ids, routed_legs, composition, tracks, stop_infra, router, routing_mode
    )
    costed_candidates.sort(
        key=lambda pair: (pair[0].leg_index, pair[0].along_leg_fraction)
    )
    suggestions = []
    for candidate, added_time_min in costed_candidates:
        stop = stop_infra.get(candidate.stop_id)
        suggestions.append(
            AutoStopSuggestion(
                stop_id=stop.stop_id,
                stop_name=stop.stop_name,
                country_code=stop.stop_country_code,
                lat=stop.lat,
                lon=stop.lon,
                added_time_min=round(added_time_min, 1),
            )
        )
    logger.info("suggest_auto_stops: %d suggestion(s).", len(suggestions))
    return suggestions


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
    for whichever of boarding/alighting/both applies. NIGHT stops are
    treated exactly like BOTH — both activities remain operationally
    possible at a night stop, only demand treats it differently (see
    distribute_demand in route_factory.py). 0 for a stop type that's
    none of these (shouldn't occur for an intermediate stop, but falls
    back safely rather than raising)."""
    track = tracks.get(country_code)
    candidates: list[int] = []
    if stop_type in (StopType.BOARDING, StopType.BOTH, StopType.NIGHT):
        candidates += [composition.min_boarding_time_min, track.min_boarding_time_min]
    if stop_type in (StopType.ALIGHTING, StopType.BOTH, StopType.NIGHT):
        candidates += [composition.min_alighting_time_min, track.min_alighting_time_min]
    return max(candidates) if candidates else 0


def build_final_timetable(
    stop_types: list[StopType],
    country_codes: list[str],
    routed_legs: list[RoutedLeg],
    composition: Composition,
    tracks: TrackInfraCollection,
    departure_time_min: int,
    slack_per_leg: list[int] | None = None,
) -> list[tuple[int | None, int | None]]:
    """
    Exact, dwell-inclusive (arrival_min, departure_min) per stop, given a
    departure time and stop types that are already fixed (typically the
    output of a timetable_mode strategy above). Not itself a strategy —
    there's only one correct way to turn "departure time + stop types"
    into real clock times, so this is a plain function, not dispatched.

    slack_per_leg: fixed-night stretch minutes per leg, aligned with
    routed_legs (see simple_automatic_fixed_night_timetable) — None means
    no slack anywhere, the case for every other timetable_mode.

    First stop: arrival=None (it's the origin, nothing to arrive at).
    Last stop: departure=None (journey's over). Every stop in between
    departs at arrival + dwell_min().
    """
    n = len(stop_types)
    if slack_per_leg is None:
        slack_per_leg = [0] * len(routed_legs)
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
            clock_min = departure_min + routed_legs[i].total_time_min + slack_per_leg[i]

        times.append((arrival_min, departure_min))

    return times
