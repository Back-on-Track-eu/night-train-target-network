"""
route_factory.py
================
Sole entry point for constructing Trip, TripPair, and Route domain objects.

Pipeline for plan_route() per TripPair (_build_trip_pair()), per direction (_build_trip())
-------------------------------------------------------------------------------------------
1. Load composition + ParamVersions from DB.
2. Load tracks + stops + ParamVersions from DB.
3. RailRouter.route() — routes the stop list as given.
4. auto_stop_addition switch (this module, _build_trip()) — three modes
   (VALID_AUTO_STOP_ADDITION_MODES in models/route/timetable.py):
     "off"     — step skipped entirely, caller's stop list unmodified.
     "add"     — apply_auto_stop_addition() looks for catalog stops close
                 to the routed path and greedily adds any that fit within
                 the detour time budget, re-routing internally as needed.
     "suggest" — routes like "off" (nothing added, nothing rerouted), but
                 suggest_auto_stops() runs the same candidate search +
                 costing and its AutoStopSuggestions are bubbled up
                 through plan_route()'s return value for the API to
                 attach to the response.
   Either way the routed_legs used from here on match the (possibly
   extended) stop list, so no separate re-route call is ever needed here.
   The full search-and-cost pass only ever runs for the OUTBOUND direction —
   _build_trip_pair() reuses its result (reversed) for return via
   _build_trip()'s known_auto_added_stop_ids, rather than re-running the
   whole candidate search for what is, physically, the same corridor
   reversed. See _build_trip_pair()'s comment for the accepted trade-off
   (return no longer gets an independent detour-budget check) and why
   (measured: this search-and-cost pass, not routing itself, is the
   dominant cost of planning a route through a dense catalog).
5. _check_country_coverage() — every country the (possibly re-routed) legs
   actually pass through must have a row in input_params.track_infrastructures
   (any field may be None and fall back to the EU-average default), or this
   raises ValueError. See that function's docstring.
6. timetable_mode switch (this module, _build_trip()) — picks which named
   timetable_mode function (models/route/timetable.py) to call for this
   direction's departure time + boarding/alighting classification. Does no
   routing of its own.
7. calc_energy_consumption() enriches RoutedLeg.energy_kwh in-place.
8. _build_trip_stops_and_legs() (DB lookups + assembly) delegates exact
   timing to timetable.build_final_timetable(), pairs the result with
   RoutedLeg physics → list[Segment].
9. Trip._create() for outbound and return — no composition, no version fields.
10. TripPair._create() bundles both trips with their shared composition and schedule.
11. Route._create() assembles all TripPairs.

timetable_mode / schedule_mode / auto_stop_addition each have their switch
(which named behaviour runs, based on the request field) here in
route_factory.py — at whichever level owns the relevant context: per-trip
in _build_trip() for timetable_mode, per-TripPair in _build_trip_pair()
for auto_stop_addition (decided once from outbound, reused for return —
see above), per-route in plan_route() for schedule_mode (shared across
every TripPair, decided once). routing_mode's switch lives with its
implementation, in rail_router.py's route(). models/route/timetable.py
holds one function per named behaviour and never branches on the
mode/flag itself — see that module's docstring.

plan_route() returns (Route, RouteProvenance, list[AutoStopSuggestion]) —
provenance is not stored on Trip/Route, caller persists it alongside
route_id when writing a proposal result; suggestions is non-empty only for
auto_stop_addition="suggest" and is the API's to serialize, never stored
on the Route (nothing was added to any trip).

ID convention
-------------
  route_id : P{proposal_id}_V{version}_R1
  trip_id  : P{proposal_id}_V{version}_R1_D{direction}_T{pair_index}

  TODO: a distinct trip-pair id (and D/T reorder) is under consideration —
  full motivation and blast radius in OPEN_TODOS["trip_pair_id"],
  models/route/version.py. Not started here.

  proposal_id/version are always concrete ints by the time they reach here
  — ephemeral compute (POST /api/proposal/calc) passes the fixed neutral
  placeholders NEUTRAL_PROPOSAL_ID/VERSION (models/route/version.py, both
  0) and publish later rewrites the resulting bare structural ids up to
  the real P{proposal_id}_V{version}_ prefix (adapters/proposal/
  repository.py). Either way, route_factory.py only ever sees real ints
  and always uses the one ID format.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from models.params import (
    ModelVersions,
    ParamVersions,
    TrackInfraCollection,
    StopInfraCollection,
    PassageChargeCollection,
    Composition,
    CompositionCollection,
)
from models.route.trip import Stop, StopType, Segment, Trip, TimetableWarning
from models.route.route import Route, TripPair, Parking, Shunting
from models.route.routing.gauge import resolve_trip_gauge
from models.route.routing.rail_router import RailRouter, RoutedLeg, build_router_stops
from models.route.timetable import (
    simple_automatic_timetable,
    simple_automatic_fixed_night_timetable,
    fixed_night_speed_warning,
    always_daily_schedule,
    apply_auto_stop_addition,
    suggest_auto_stops,
    build_final_timetable,
    AutoStopSuggestion,
    VALID_TIMETABLE_MODES,
    VALID_SCHEDULE_MODES,
    VALID_AUTO_STOP_ADDITION_MODES,
)
from models.energy.calc_energy_consumption import calc_energy_consumption
from models.route.model import ROUTE_BUILDER_VERSION
from models.energy.model import ENERGY_CALC_VERSION

logger = logging.getLogger(__name__)


@dataclass
class RouteProvenance:
    """What was used to build a Route — returned alongside it, not stored on it."""

    model_versions: ModelVersions
    param_versions: ParamVersions
    scenario_id: int
    """Concrete scenario_id used to build this Route — never None here, even
    if the caller passed None (meaning "use the live base"): resolved once
    to a concrete id at the top of plan_route() so a saved
    Route stays reproducible even after the base scenario moves on."""
    tracks: TrackInfraCollection
    """All countries' track infrastructure for this scenario — not just the
    ones this particular route touches. Same object regardless of which
    TripPair it was loaded for (all pairs share one scenario_id), so
    plan_route() just keeps whichever pair's copy loaded last. Exists here
    so the API layer can pass it to route_to_dict() for the response's
    track_infrastructure block — Route itself never stores it (physics-only,
    per the project's separation-of-concerns rule)."""
    compositions: CompositionCollection
    """The full composition catalog for this scenario, built once in
    plan_route() (below) and otherwise discarded after use. Threaded
    through here (2026-08-03, adapters/proposal/README.md efficiency note) so
    api/proposal_calc.py's merged evaluate step doesn't have to reload it a
    second time via loader.build_all_compositions() — the same efficiency
    rationale as tracks above, not a new one."""
    stop_infra: StopInfraCollection
    """All stop infrastructure for this scenario, built once in
    plan_route() (for parkings) and otherwise discarded after use.
    Threaded through for the same reason as compositions above — avoids
    api/proposal_calc.py's evaluate step reloading it via
    loader.build_all_stops() a second time."""
    passages: PassageChargeCollection
    """The scenario's separately charged crossings. Routing already
    attributed each crossing to a segment by polygon (Segment.passages);
    this carries the CHARGES for the evaluate step, threaded through for
    the same reason as tracks and stop_infra above."""


@dataclass
class TripPairInput:
    """One outbound + return cycle to build. Schedule lives on Route — all
    pairs share one schedule, passed to plan_route() directly.

    No field here has a default — mode/flag defaulting is an API-boundary
    concern (see api/helpers/proposal_compute.py), not something route_factory.py or its
    callers should need to know about. Every field must be explicitly
    supplied by the caller."""

    stop_ids: list[str]  # outbound order; return is reversed. Boarding/alighting
    # is derived automatically per timetable_mode, not supplied here.
    composition_id: str
    timetable_mode: str
    routing_mode: str
    auto_stop_addition: str  # "off" | "add" | "suggest" — see timetable.py
    fixed_night_interval: list[str] | None  # [start, end] stop IDs in outbound
    # order — required for timetable_mode="simpleAutomaticWithFixedNight",
    # None for every other mode (enforced at the API boundary); reversed
    # automatically for the return trip by _build_trip_pair()


# =============================================================================
# ID GENERATION
# =============================================================================

# TODO: possible D/T reorder + distinct trip-pair id — see
# OPEN_TODOS["trip_pair_id"] in models/route/version.py before starting.


def _route_id(proposal_id: int, version: int) -> str:
    return f"P{proposal_id}_V{version}_R1"


def _trip_id(proposal_id: int, version: int, direction: int, pair_index: int) -> str:
    return f"P{proposal_id}_V{version}_R1_D{direction}_T{pair_index}"


# =============================================================================
# TRIP STOPS & LEGS
# =============================================================================


def _build_trip_stops_and_legs(
    stop_inputs: list[tuple[str, StopType]],
    routed_legs: list[RoutedLeg],
    composition: Composition,
    tracks: TrackInfraCollection,
    stop_infra: StopInfraCollection,
    departure_time_min: int,
    auto_added_stop_ids: frozenset[str] = frozenset(),
    slack_per_leg: list[int] | None = None,
) -> list[Segment]:
    """
    DB lookups + object assembly only — no timing math here, that's
    timetable.build_final_timetable()'s job. Looks up each stop's physical
    data once, gets exact arrival/departure per stop from
    build_final_timetable(), then builds Stop objects and pairs consecutive
    stops into Segments — each Stop is shared by reference between the two
    segments touching it.

    auto_added_stop_ids: stop_ids that auto_stop_addition inserted beyond
    what the caller originally supplied — stamped onto the matching Stop's
    auto_added field. Empty by default.

    slack_per_leg: fixed-night stretch minutes per leg (see
    simple_automatic_fixed_night_timetable) — stamped onto each Segment's
    slack_time_min and fed into build_final_timetable() so stop times and
    segment components stay consistent with each other. None (every other
    timetable_mode) means 0 everywhere.
    """
    if slack_per_leg is None:
        slack_per_leg = [0] * len(routed_legs)
    stop_physicals = []
    for stop_id, _ in stop_inputs:
        sp = stop_infra.get(stop_id)
        if sp is None:
            raise ValueError(f"Stop '{stop_id}' not found in database.")
        stop_physicals.append(sp)

    stop_types = [stop_type for _, stop_type in stop_inputs]
    timetable = build_final_timetable(
        stop_types=stop_types,
        country_codes=[sp.stop_country_code for sp in stop_physicals],
        routed_legs=routed_legs,
        composition=composition,
        tracks=tracks,
        departure_time_min=departure_time_min,
        slack_per_leg=slack_per_leg,
    )

    stops = [
        Stop(
            stop_id=sp.stop_id,
            stop_name=sp.stop_name,
            country_code=sp.stop_country_code,
            lat=sp.lat,
            lon=sp.lon,
            stop_type=stop_type,
            arrival_time_min=arrival_min,
            departure_time_min=departure_min,
            auto_added=sp.stop_id in auto_added_stop_ids,
        )
        for sp, stop_type, (arrival_min, departure_min) in zip(
            stop_physicals, stop_types, timetable
        )
    ]

    return [
        Segment(
            from_stop=stops[i],
            to_stop=stops[i + 1],
            geometry=routed_legs[i].geometry,
            distance_m=routed_legs[i].distance_m,
            driving_time_min=routed_legs[i].driving_time_min,
            dynamics_time_min=routed_legs[i].dynamics_time_min,
            buffer_time_min=routed_legs[i].buffer_time_min,
            energy_kwh=routed_legs[i].energy_kwh,
            country_distance_shares=routed_legs[i].country_distance_shares,
            country_time_shares=routed_legs[i].country_time_shares,
            slack_time_min=slack_per_leg[i],
            countries=routed_legs[i].countries,
            passages=routed_legs[i].passages,
        )
        for i in range(len(routed_legs))
    ]


# =============================================================================
# PARKING LOCATIONS
# =============================================================================


# A full cycle is one operating day: a formation that arrives in the morning
# leaves the same evening, and one that arrives in the evening leaves the next.
# So a layover that computes negative has wrapped past midnight and gains a day.
_DAY_MIN = 24 * 60


def _layover_hours(trips: list[Trip], stop_id: str) -> float:
    """Scheduled hours a formation stands at one terminal.

    The gap between the last arrival at this stop and the next departure from
    it, across all trips of the route — which for a trip pair is the inbound
    arrival and the outbound departure of the following cycle. Terminal times
    are minutes from midnight day 1 and a return trip may depart before the
    inbound arrived in clock terms, so a negative gap wraps forward one day
    rather than being clamped: an 06:00 arrival and a 20:00 departure is a
    14 h layover, and a 20:00 arrival with an 06:00 departure is 10 h, not
    minus fourteen.

    Returns 0.0 where the route has no second trip to depart again — a
    one-way route stables nothing, and pricing a layover of unknown length
    would be an invention.
    """
    arrivals = [
        t.segments[-1].to_stop.arrival_time_min
        for t in trips
        if t.segments and t.segments[-1].to_stop.stop_id == stop_id
    ]
    departures = [
        t.segments[0].from_stop.departure_time_min
        for t in trips
        if t.segments and t.segments[0].from_stop.stop_id == stop_id
    ]
    arrivals = [a for a in arrivals if a is not None]
    departures = [d for d in departures if d is not None]
    if not arrivals or not departures:
        return 0.0
    gap = min(departures) - max(arrivals)
    while gap < 0:
        gap += _DAY_MIN
    return gap / 60.0


def _parkings(trips: list[Trip], stop_infra: StopInfraCollection) -> list[Parking]:
    """One Parking per unique terminal stop across all trips — deduplicated
    by stop_id since one formation sits there regardless of how many trips
    share that terminal. trip_ids lists all trips parking at this stop, and
    hours is the scheduled layover (see _layover_hours)."""
    by_stop: dict[str, Parking] = {}
    for trip in trips:
        if not trip.stops:
            continue
        for stop in (trip.stops[0], trip.stops[-1]):
            if stop.stop_id not in by_stop:
                sp = stop_infra.get(stop.stop_id)
                if sp is None:
                    logger.warning(
                        "Stop '%s' not found — parking skipped.", stop.stop_id
                    )
                    continue
                by_stop[stop.stop_id] = Parking(
                    stop_id=sp.stop_id,
                    stop_name=sp.stop_name,
                    country_code=sp.stop_country_code,
                    trip_ids=[trip.trip_id],
                    hours=_layover_hours(trips, stop.stop_id),
                )
            elif trip.trip_id not in by_stop[stop.stop_id].trip_ids:
                by_stop[stop.stop_id].trip_ids.append(trip.trip_id)
    return list(by_stop.values())


def _shuntings(trips: list[Trip]) -> list[Shunting]:
    """One Shunting per trip terminal — no deduplication. Each coupling/
    uncoupling is a separate event even if trips share a stop.
    trip_id identifies which trip each shunting belongs to.
    TODO: see OPEN_TODOS["shunting_y_shape"] in models/route/version.py."""
    result = []
    for trip in trips:
        if trip.stops:
            for stop in (trip.stops[0], trip.stops[-1]):
                result.append(
                    Shunting(
                        stop_id=stop.stop_id,
                        stop_name=stop.stop_name,
                        country_code=stop.country_code,
                        trip_id=trip.trip_id,
                    )
                )
    return result


# =============================================================================
# TRIP BUILDER
# =============================================================================


def _check_country_coverage(
    routed_legs: list[RoutedLeg], tracks: TrackInfraCollection
) -> None:
    """Every country a route's legs pass through must have a row in
    input_params.track_infrastructures — no silent EU-average substitution
    for a country that was never seeded at all. Raises ValueError naming
    whatever's missing, surfaced by api/proposal_calc.py as a 422 domain_error.

    Individual fields on that row being None (and therefore resolved from
    track_infrastructure_defaults) is fine and expected — that's exactly
    what the defaults table is for. Only a country with no row whatsoever
    fails this check.

    "UNK" is exempt — it's RailRouter's sentinel for a leg segment whose
    midpoint doesn't fall inside any known country polygon at all (open
    water: straits, ferry sections, bridges — e.g. the Öresund crossing
    between Denmark and Sweden), not a country with missing data. There's
    no DB row that could ever exist for it, so it's not something seeding
    can fix, and it's not what this check exists to catch.

    DBDataLoader.build_all_tracks() synthesizes a full EU-average row for
    any country in input_params.countries with no track_infrastructures
    row at all, so tracks.get(cc) is never None here for a legitimate
    country — a country with no real row is instead recognized via
    TrackInfrastructure.has_row=False."""
    missing = {
        cc
        for leg in routed_legs
        for cc in leg.country_distance_shares
        if cc != "UNK" and ((track := tracks.get(cc)) is None or not track.has_row)
    }
    if missing:
        countries = ", ".join(sorted(missing))
        raise ValueError(
            f"Route passes through {countries} — no row in "
            f"input_params.track_infrastructures for {'this country' if len(missing) == 1 else 'these countries'}. "
            f"Add a row (country_code alone is enough — other fields fall back "
            f"to the EU-average default) before a route through it can be evaluated."
        )


def _build_trip(
    proposal_id: int,
    proposal_version: int,
    direction: int,
    pair_index: int,
    stop_ids: list[str],
    composition: Composition,
    tracks: TrackInfraCollection,
    stop_infra: StopInfraCollection,
    router: RailRouter,
    timetable_mode: str,
    routing_mode: str,
    auto_stop_addition: str,
    fixed_night_interval: list[str] | None,
    known_auto_added_stop_ids: frozenset[str] | None = None,
) -> tuple[Trip, list[AutoStopSuggestion]]:
    """
    Returns (Trip, suggestions). suggestions is non-empty only for
    auto_stop_addition="suggest" on the direction that actually runs the
    candidate search (see known_auto_added_stop_ids below) — [] otherwise.

    fixed_night_interval: [start, end] stop IDs in THIS direction's travel
    order (the caller reverses the pair input's interval for the return
    trip) — consumed only by timetable_mode="simpleAutomaticWithFixedNight",
    None for every other mode.

    known_auto_added_stop_ids: when given, skips the candidate search
    entirely regardless of auto_stop_addition — stop_ids is trusted as
    already final (the search decision was already made elsewhere, e.g. by
    the outbound direction of this same TripPair; see _build_trip_pair()),
    and this set is used as-is to mark which of those stops get
    Stop.auto_added=True. The routing call below still always happens for
    whichever direction this is — reusing a decision about WHICH stops to
    add never skips getting THIS direction's own real physics for its own
    (possibly asymmetric) path, only the expensive candidate-search-and-
    cost pass that decided the stop list in the first place.
    """
    tid = _trip_id(proposal_id, proposal_version, direction, pair_index)

    # The trip's track gauge — resolved from the USER'S stops before any
    # router call so an impossible pairing (Kyiv 1520 + Warszawa 1435)
    # fails as 422 gauge_mismatch, not a snap error. route() resolves
    # again internally from whatever list it is given (auto-stop
    # mini-reroutes included); this value is the one the Trip carries, and
    # auto-added stops cannot change it — the candidate filter only admits
    # stops that support it (timetable._find_nearby_candidates).
    router_stops = build_router_stops(stop_ids, stop_infra)
    gauge_mm = resolve_trip_gauge((rs.stop for rs in router_stops), composition)

    routed_legs = router.route(
        stops=router_stops,
        composition=composition,
        tracks=tracks,
        routing_mode=routing_mode,
    )

    # auto_stop_addition SWITCH — which (if any) auto-stop behaviour runs.
    # The timetable.py functions themselves have no mode gate; "add" always
    # returns routed_legs matching whatever stop_ids it hands back
    # (unchanged for "off"/"suggest"), so no separate re-route is ever
    # needed after this block regardless of which branch ran.
    # VALID_AUTO_STOP_ADDITION_MODES is the same set the compute request
    # validation checks against, so an unknown mode can only reach here if
    # that validation was bypassed.
    suggestions: list[AutoStopSuggestion] = []
    if known_auto_added_stop_ids is not None:
        auto_added_stop_ids = known_auto_added_stop_ids
    elif auto_stop_addition == "off":
        auto_added_stop_ids = frozenset()
    elif auto_stop_addition == "add":
        original_stop_ids = stop_ids
        stop_ids, routed_legs = apply_auto_stop_addition(
            stop_ids,
            routed_legs,
            composition=composition,
            tracks=tracks,
            stop_infra=stop_infra,
            router=router,
            routing_mode=routing_mode,
        )
        auto_added_stop_ids = frozenset(stop_ids) - frozenset(original_stop_ids)
    elif auto_stop_addition == "suggest":
        suggestions = suggest_auto_stops(
            stop_ids,
            routed_legs,
            composition=composition,
            tracks=tracks,
            stop_infra=stop_infra,
            router=router,
            routing_mode=routing_mode,
        )
        auto_added_stop_ids = frozenset()  # nothing added — suggestion only
    else:
        raise ValueError(
            f"Unknown auto_stop_addition '{auto_stop_addition}'. "
            f"Supported: {sorted(VALID_AUTO_STOP_ADDITION_MODES)}."
        )

    _check_country_coverage(routed_legs, tracks)

    # timetable_mode SWITCH — which named strategy computes departure time
    # + stop classification for this direction. VALID_TIMETABLE_MODES is the
    # same set the compute request validation (api/helpers/proposal_compute.py) checks against, so an unknown
    # mode can only reach here if that validation was bypassed. Only the
    # fixed-night strategy produces slack; every other mode gets zeros.
    if timetable_mode == "simpleAutomatic":
        stop_inputs, departure_time_min = simple_automatic_timetable(
            stop_ids=stop_ids,
            composition=composition,
            routed_legs=routed_legs,
        )
        slack_per_leg = [0] * len(routed_legs)
    elif timetable_mode == "simpleAutomaticWithFixedNight":
        stop_inputs, departure_time_min, slack_per_leg = (
            simple_automatic_fixed_night_timetable(
                stop_ids=stop_ids,
                composition=composition,
                routed_legs=routed_legs,
                fixed_night_interval=fixed_night_interval,
            )
        )
    else:
        raise ValueError(
            f"Unknown timetable_mode '{timetable_mode}'. Supported: {sorted(VALID_TIMETABLE_MODES)}."
        )

    calc_energy_consumption(routed_legs, composition)

    segments = _build_trip_stops_and_legs(
        stop_inputs=stop_inputs,
        routed_legs=routed_legs,
        composition=composition,
        tracks=tracks,
        stop_infra=stop_infra,
        departure_time_min=departure_time_min,
        auto_added_stop_ids=auto_added_stop_ids,
        slack_per_leg=slack_per_leg,
    )

    # Post-build timetable quality check — fixed-night only: did covering
    # the night window stretch the interval unreasonably slow? Runs on the
    # final segments (real dwell + slack), informational, never blocks.
    timetable_warnings: list[TimetableWarning] = []
    if timetable_mode == "simpleAutomaticWithFixedNight":
        warning = fixed_night_speed_warning(segments, fixed_night_interval)
        if warning is not None:
            timetable_warnings.append(warning)

    trip = Trip._create(
        trip_id=tid,
        direction=direction,
        segments=segments,
        timetable_warnings=timetable_warnings,
        gauge_mm=gauge_mm,
    )
    logger.info(
        "_build_trip: id=%s %dm %.0fmin", tid, trip.distance_m, trip.total_time_min
    )
    return trip, suggestions


# =============================================================================
# TRIP PAIR BUILDER
# =============================================================================


def _composition_param_versions(
    composition: Composition, compositions: CompositionCollection
) -> ParamVersions:
    """
    Filter compositions.param_versions (which covers the WHOLE eagerly-
    loaded catalog) down to just the entries relevant to one composition —
    its own fields, its operator's, and its coach types' — so a route's
    provenance doesn't carry every other composition in the catalog along
    with it.
    """
    prefixes = [
        f"composition_type:{composition.comp_id}:",
        f"composition_reference:{composition.comp_id}:",
        f"operator:{composition.operator_id}:",
        f"operator_class_cost:{composition.operator_id}:",
    ] + [f"coach_type:{coach.coachtype_id}:" for coach in composition.coaches.values()]
    filtered = ParamVersions()
    filtered.entries = {
        key: entry
        for key, entry in compositions.param_versions.entries.items()
        if any(key.startswith(p) for p in prefixes)
    }
    return filtered


def _build_trip_pair(
    proposal_id: int,
    proposal_version: int,
    pair_index: int,
    pair_input: TripPairInput,
    loader,
    router: RailRouter,
    scenario_id: int,
    compositions: CompositionCollection,
) -> tuple[TripPair, list[AutoStopSuggestion], ParamVersions, TrackInfraCollection]:
    composition = compositions.get(pair_input.composition_id)
    if composition is None:
        raise ValueError(f"Composition '{pair_input.composition_id}' not found.")
    tracks = loader.build_all_tracks(scenario_id)
    stop_infra = loader.build_all_stops(scenario_id)

    param_versions = ParamVersions()
    param_versions.entries.update(
        _composition_param_versions(composition, compositions).entries
    )
    param_versions.entries.update(tracks.param_versions.entries)
    param_versions.entries.update(stop_infra.param_versions.entries)

    # Each direction still gets its own real routing call and schedule —
    # outbound and return can legitimately have different durations (e.g.
    # asymmetric HSR avoidance), so their departure times are allowed to
    # deviate rather than being forced to share one value.
    #
    # auto_stop_addition is the one exception: its candidate search + per-
    # candidate costing (modes "add"/"suggest") is decided ONCE, from
    # outbound, not re-run independently for return. The costing means one
    # real RailRouter.route() call per nearby candidate — for a long
    # corridor with many candidates nearby, that's the dominant cost of
    # planning a route (measured: ~14s per direction on a Stockholm-Roma
    # request with 9 candidates found, against <1s for routing itself),
    # and outbound/return cover the same physical corridor reversed, so
    # running that full search twice is mostly redundant work for the same
    # answer. Accepted trade-off: return no longer gets its own independent
    # detour-budget check against its own baseline trip time, only
    # outbound's — see OPEN_TODOS["return_detour_budget"] in version.py and
    # _build_trip()'s known_auto_added_stop_ids docstring. Return still
    # gets a real routing call for its own (possibly asymmetric) physical
    # path over the shared final stop list; only the search-and-cost pass
    # that decided which stops to add (or which to suggest) is shared, not
    # the routing itself.
    outbound, suggestions = _build_trip(
        proposal_id,
        proposal_version,
        direction=0,
        pair_index=pair_index,
        stop_ids=pair_input.stop_ids,
        composition=composition,
        tracks=tracks,
        stop_infra=stop_infra,
        router=router,
        timetable_mode=pair_input.timetable_mode,
        routing_mode=pair_input.routing_mode,
        auto_stop_addition=pair_input.auto_stop_addition,
        fixed_night_interval=pair_input.fixed_night_interval,
    )

    final_outbound_stop_ids = [s.stop_id for s in outbound.stops]
    auto_added_stop_ids = frozenset(s.stop_id for s in outbound.stops if s.auto_added)

    # The fixed night interval is expressed in each direction's own travel
    # order — reversed here so the return trip fixes its night window on
    # the same physical corridor section (structurally mirrored times;
    # not minute-exact, since each direction routes its own physics).
    return_fixed_night_interval = (
        list(reversed(pair_input.fixed_night_interval))
        if pair_input.fixed_night_interval is not None
        else None
    )
    return_trip, _ = _build_trip(
        proposal_id,
        proposal_version,
        direction=1,
        pair_index=pair_index,
        stop_ids=list(reversed(final_outbound_stop_ids)),
        composition=composition,
        tracks=tracks,
        stop_infra=stop_infra,
        router=router,
        timetable_mode=pair_input.timetable_mode,
        routing_mode=pair_input.routing_mode,
        auto_stop_addition=pair_input.auto_stop_addition,
        fixed_night_interval=return_fixed_night_interval,
        known_auto_added_stop_ids=auto_added_stop_ids,
    )

    pair = TripPair(
        outbound=outbound,
        return_trip=return_trip,
        composition=composition,
        od_pairs=[],  # populated later by models/demand (stopgap.distribute_demand())
    )
    return pair, suggestions, param_versions, tracks


# =============================================================================
# PLAN ROUTE — full routing pipeline
# =============================================================================


def plan_route(
    trip_pair_inputs: list[TripPairInput],
    loader,
    router: RailRouter,
    schedule_mode: str,
    proposal_id: int,
    proposal_version: int,
    scenario_id: int,
) -> tuple[Route, RouteProvenance, list[AutoStopSuggestion]]:
    """
    Build a Route from scratch. One TripPair per entry in trip_pair_inputs
    (Y-shaped routes pass several, each with its own composition).
    All pairs share the route-level schedule.
    Demand is not set here — call models/demand's
    stopgap.distribute_demand() after plan_route() to populate od_pairs on
    each TripPair.

    Returns (Route, RouteProvenance, suggestions). suggestions is only
    non-empty for auto_stop_addition="suggest" — the costed candidate
    stops the search found near each pair's outbound corridor, concatenated
    across pairs (a Y-shaped route contributes each branch's suggestions in
    pair order), for the API layer to serialize into the response. Not part
    of the Route itself — nothing was added to any trip.

    No parameter here has a default and none is Optional — all resolution
    (draft proposal_id/version, "None scenario_id means live base") happens
    once at the API boundary before this is called. See the ID convention
    note at the top of this module.

    schedule_mode: this function's switch — which named schedule_mode
    function (models/route/timetable.py) to call. Decided once here, at
    route level, since Schedule is shared across every TripPair rather
    than being a per-trip concern (currently only "alwaysDaily").

    scenario_id: stored as-is in RouteProvenance so the Route stays
    reproducible even if the live base scenario later moves on.
    """
    # schedule_mode SWITCH — which named strategy builds this route's
    # Schedule. VALID_SCHEDULE_MODES is the same set the compute request
    # validation checks against, so an unknown mode can only reach here if
    # that validation was bypassed.
    if schedule_mode == "alwaysDaily":
        schedule = always_daily_schedule()
    else:
        raise ValueError(
            f"Unknown schedule_mode '{schedule_mode}'. Supported: {sorted(VALID_SCHEDULE_MODES)}."
        )
    rid = _route_id(proposal_id, proposal_version)
    logger.info(
        "plan_route: id=%s pairs=%d scenario_id=%d",
        rid,
        len(trip_pair_inputs),
        scenario_id,
    )

    trip_pairs: list[TripPair] = []
    suggestions: list[AutoStopSuggestion] = []
    merged_param_versions = ParamVersions()
    tracks_used: TrackInfraCollection | None = None

    # Built once for the whole route, not once per trip pair — a Y-shaped
    # route with several compositions would otherwise reload the entire
    # catalog per pair. include_indicative=False since route building
    # never touches Composition.indicative (see build_all_compositions()).
    compositions = loader.build_all_compositions(scenario_id, include_indicative=False)

    for i, pair_input in enumerate(trip_pair_inputs, start=1):
        pair, pair_suggestions, param_versions, tracks = _build_trip_pair(
            proposal_id,
            proposal_version,
            pair_index=i,
            pair_input=pair_input,
            loader=loader,
            router=router,
            scenario_id=scenario_id,
            compositions=compositions,
        )
        trip_pairs.append(pair)
        suggestions.extend(pair_suggestions)
        merged_param_versions.entries.update(param_versions.entries)
        tracks_used = (
            tracks  # identical across pairs (same scenario_id) — last write wins
        )

    model_versions = ModelVersions(
        versions={
            "route_builder": ROUTE_BUILDER_VERSION,
            "energy_calc": ENERGY_CALC_VERSION,
        }
    )

    stop_infra = loader.build_all_stops(scenario_id)
    passages = loader.build_all_passages(scenario_id)
    parking = _parkings(
        [t for pair in trip_pairs for t in pair.trips],
        stop_infra,
    )

    route = Route._create(
        route_id=rid,
        schedule=schedule,
        trip_pairs=trip_pairs,
        parkings=parking,
        shuntings=_shuntings([t for pair in trip_pairs for t in pair.trips]),
    )

    logger.info(
        "plan_route done: id=%s pairs=%d suggestions=%d",
        rid,
        len(route.trip_pairs),
        len(suggestions),
    )
    return (
        route,
        RouteProvenance(
            model_versions=model_versions,
            param_versions=merged_param_versions,
            scenario_id=scenario_id,
            tracks=tracks_used,
            compositions=compositions,
            stop_infra=stop_infra,
            passages=passages,
        ),
        suggestions,
    )
