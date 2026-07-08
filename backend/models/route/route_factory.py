"""
route_factory.py
================
Sole entry point for constructing Trip, TripPair, and Route domain objects.

Pipeline for plan_route() per TripPair, per direction (in _build_trip())
-------------------------------------------------------------------------
1. Load composition + ParamVersions from DB.
2. Load tracks + stops + ParamVersions from DB.
3. RailRouter.route() — routes the stop list as given.
4. apply_auto_stop_addition() (models/route/timetable.py) — no-op for now.
   If it ever changes the stop list, route again with the new list before
   doing anything else with the result — a changed stop list invalidates
   the first routed_legs.
5. _check_country_coverage() — every country the (possibly re-routed) legs
   actually pass through must have a row in input_params.track_infrastructures
   (any field may be None and fall back to the EU-average default), or this
   raises ValueError. See that function's docstring.
6. schedule_and_classify() (models/route/timetable.py) — timetable_mode
   strategy: derives departure time + boarding/alighting per stop from the
   legs. Does no routing of its own.
7. calc_energy_consumption() enriches RoutedLeg.energy_kwh in-place.
8. _build_trip_stops_and_legs() (DB lookups + assembly) delegates exact
   timing to timetable.build_final_timetable(), pairs the result with
   RoutedLeg physics → list[Segment].
9. Trip._create() for outbound and return — no composition, no version fields.
10. TripPair._create() bundles both trips with their shared composition and schedule.
11. Route._create() assembles all TripPairs.

timetable_mode / schedule_mode / auto_stop_addition are pluggable strategies
living in models/route/timetable.py, not here — route_factory.py only
orchestrates, so a new strategy can be added there without touching this pipeline.

Returns (Route, RouteProvenance) — provenance is not stored on Trip/Route,
caller persists it alongside route_id when writing a proposal result.

ID convention
-------------
  route_id : P{proposal_id}_V{version}_R1
  trip_id  : P{proposal_id}_V{version}_R1_D{direction}_T{pair_index}

  TODO (David, 2026-07-06, future — not scheduled): considering swapping
  the D/T order to trip_id = P{proposal_id}_V{version}_R1_T{pair_index}_D{direction},
  and introducing a distinct trip-PAIR id (as opposed to the current
  per-trip id) of the form P{proposal_id}_V{version}_R1_T{pair_index} — i.e.
  drop the trailing _D{direction} entirely for anything that means "the
  pair", not "one direction of the pair". Motivation: api/helpers/
  evaluation_serialize.py's "views" section currently keys per_trip_pair /
  per_trip_pair_per_country / per_trip_pair_per_od by the outbound trip's
  full trip_id (e.g. "P123_V1_R1_D0_T1") standing in for the whole pair,
  which is a borrowed/overloaded key, not a real pair identifier. This is
  a real ID-format change, not a rename: trip_id is threaded through
  Segment/StopCost/SegmentCost/ODPair.trip_id, the route_to_dict()/
  route_from_dict() JSON schema, and every test fixture that hardcodes IDs
  — needs its own scoped pass across route_factory.py (_route_id/_trip_id
  below), models/route/route.py, api/helpers/route_serialize.py, and
  tests/ once actually scheduled. Not started here.

  proposal_id/version are always concrete ints by the time they reach here
  — for a brand new proposal (no DB row yet), api/route.py assigns a random
  placeholder proposal_id above one billion (Postgres SERIAL for
  proposals.proposals starts at 1 and won't realistically reach that range)
  and proposal_version=1, rather than this module having to know about or
  branch on a "not saved yet" state. That assignment is a stand-in for a
  future scenarios/proposals module that will own draft-vs-saved handling
  properly; api/route.py is just the simplest place to put it until that
  module exists. Either way, route_factory.py only ever sees real ints and
  always uses the one ID format.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from models.params import (
    ModelVersions,
    ParamVersions,
    ODPair,
    TrackInfraCollection,
    StopInfraCollection,
    Composition,
    CompositionCollection,
)
from models.route.trip import Stop, StopType, Segment, Trip
from models.route.route import Route, TripPair, Parking, Shunting, Schedule
from models.route.routing.rail_router import RailRouter, StopInput, RoutedLeg
from models.route.timetable import (
    schedule_and_classify,
    apply_auto_stop_addition,
    build_schedule,
    build_final_timetable,
)
from models.energy.calc_energy_consumption import calc_energy_consumption
from models.route.version import ROUTE_BUILDER_VERSION
from models.energy.version import ENERGY_CALC_VERSION

logger = logging.getLogger(__name__)


@dataclass
class RouteProvenance:
    """What was used to build a Route — returned alongside it, not stored on it."""

    model_versions: ModelVersions
    param_versions: ParamVersions
    scenario_id: int
    """Concrete scenario_id used to build this Route — never None here, even
    if the caller passed None (meaning "use the live base"): resolved once
    to a concrete id at the top of plan_route()/adjust_route() so a saved
    Route stays reproducible even after the base scenario moves on."""
    tracks: TrackInfraCollection
    """All countries' track infrastructure for this scenario — not just the
    ones this particular route touches. Same object regardless of which
    TripPair it was loaded for (all pairs share one scenario_id), so
    plan_route() just keeps whichever pair's copy loaded last. Exists here
    so api/route.py can pass it to route_to_dict() for the response's
    track_infrastructure block — Route itself never stores it (physics-only,
    per the project's separation-of-concerns rule)."""


@dataclass
class TripPairInput:
    """One outbound + return cycle to build. Schedule lives on Route — all
    pairs share one schedule, passed to plan_route() directly.

    No field here has a default — mode/flag defaulting is an API-boundary
    concern (see api/route.py), not something route_factory.py or its
    callers should need to know about. Every field must be explicitly
    supplied by the caller."""

    stop_ids: list[str]  # outbound order; return is reversed. Boarding/alighting
    # is derived automatically per timetable_mode, not supplied here.
    composition_id: str
    timetable_mode: str
    routing_mode: str
    auto_stop_addition: bool


# =============================================================================
# ID GENERATION
# =============================================================================

# TODO (future, not scheduled): D{direction}_T{pair_index} may become
# T{pair_index}_D{direction} with a separate trip-pair id
# (P{proposal_id}_V{version}_R1_T{pair_index}, no _D suffix) introduced
# alongside it — see the module docstring's "ID convention" section above
# for the motivation and full blast radius before starting this.


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
) -> list[Segment]:
    """
    DB lookups + object assembly only — no timing math here, that's
    timetable.build_final_timetable()'s job. Looks up each stop's physical
    data once, gets exact arrival/departure per stop from
    build_final_timetable(), then builds Stop objects and pairs consecutive
    stops into Segments — each Stop is shared by reference between the two
    segments touching it.
    """
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
            buffer_time_min=routed_legs[i].buffer_time_min,
            energy_kwh=routed_legs[i].energy_kwh,
            country_distance_shares=routed_legs[i].country_distance_shares,
            country_time_shares=routed_legs[i].country_time_shares,
        )
        for i in range(len(routed_legs))
    ]


# =============================================================================
# PARKING LOCATIONS
# =============================================================================


def _parkings(trips: list[Trip], stop_infra: StopInfraCollection) -> list[Parking]:
    """One Parking per unique terminal stop across all trips — deduplicated
    by stop_id since one formation sits there regardless of how many trips
    share that terminal. trip_ids lists all trips parking at this stop."""
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
                )
            elif trip.trip_id not in by_stop[stop.stop_id].trip_ids:
                by_stop[stop.stop_id].trip_ids.append(trip.trip_id)
    return list(by_stop.values())


def _shuntings(trips: list[Trip]) -> list[Shunting]:
    """One Shunting per trip terminal — no deduplication. Each coupling/
    uncoupling is a separate event even if trips share a stop.
    trip_id identifies which trip each shunting belongs to.
    TODO (Y/X-shape): shared terminals may need fewer events."""
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


def _to_router_stops(
    stop_ids: list[str], stop_infra: StopInfraCollection
) -> list[StopInput]:
    """Builds StopInput objects for a routing call. stop_type is always a
    placeholder (route() ignores it — see RailRouter.route() docstring);
    real StopType classification happens afterwards, in schedule_and_classify()."""
    router_stops = [
        StopInput(stop=stop_infra.get(sid), stop_type=StopType.BOTH) for sid in stop_ids
    ]
    for rs, sid in zip(router_stops, stop_ids):
        if rs.stop is None:
            raise ValueError(f"Stop '{sid}' not found in database.")
    return router_stops


def _check_country_coverage(
    routed_legs: list[RoutedLeg], tracks: TrackInfraCollection
) -> None:
    """Every country a route's legs pass through must have a row in
    input_params.track_infrastructures — no silent EU-average substitution
    for a country that was never seeded at all. Raises ValueError naming
    whatever's missing, surfaced by api/route.py as a 422 domain_error.

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
    auto_stop_addition: bool,
) -> Trip:
    tid = _trip_id(proposal_id, proposal_version, direction, pair_index)

    routed_legs = router.route(
        stops=_to_router_stops(stop_ids, stop_infra),
        composition=composition,
        tracks=tracks,
        routing_mode=routing_mode,
    )

    new_stop_ids = apply_auto_stop_addition(auto_stop_addition, stop_ids, routed_legs)
    if new_stop_ids != stop_ids:
        # Stop list changed — the old routed_legs no longer match it, route again.
        stop_ids = new_stop_ids
        routed_legs = router.route(
            stops=_to_router_stops(stop_ids, stop_infra),
            composition=composition,
            tracks=tracks,
            routing_mode=routing_mode,
        )

    _check_country_coverage(routed_legs, tracks)

    stop_inputs, departure_time_min = schedule_and_classify(
        timetable_mode=timetable_mode,
        stop_ids=stop_ids,
        composition=composition,
        routed_legs=routed_legs,
    )

    calc_energy_consumption(routed_legs, composition)

    segments = _build_trip_stops_and_legs(
        stop_inputs=stop_inputs,
        routed_legs=routed_legs,
        composition=composition,
        tracks=tracks,
        stop_infra=stop_infra,
        departure_time_min=departure_time_min,
    )

    trip = Trip._create(trip_id=tid, direction=direction, segments=segments)
    logger.info(
        "_build_trip: id=%s %dm %.0fmin", tid, trip.distance_m, trip.total_time_min
    )
    return trip


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
) -> tuple[TripPair, ParamVersions, TrackInfraCollection]:
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

    # Each direction routes (and may re-route, if auto_stop_addition changes
    # its stop list) and schedules independently — outbound and return can
    # legitimately have different durations (e.g. asymmetric HSR avoidance),
    # so their departure times are allowed to deviate rather than being
    # forced to share one value.
    outbound = _build_trip(
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
    )
    return_trip = _build_trip(
        proposal_id,
        proposal_version,
        direction=1,
        pair_index=pair_index,
        stop_ids=list(reversed(pair_input.stop_ids)),
        composition=composition,
        tracks=tracks,
        stop_infra=stop_infra,
        router=router,
        timetable_mode=pair_input.timetable_mode,
        routing_mode=pair_input.routing_mode,
        auto_stop_addition=pair_input.auto_stop_addition,
    )

    pair = TripPair(
        outbound=outbound,
        return_trip=return_trip,
        composition=composition,
        od_pairs=[],  # populated later by distribute_demand()
    )
    return pair, param_versions, tracks


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
) -> tuple[Route, RouteProvenance]:
    """
    Build a Route from scratch. One TripPair per entry in trip_pair_inputs
    (Y-shaped routes pass several, each with its own composition).
    All pairs share the route-level schedule.
    Demand is not set here — call distribute_demand() after plan_route()
    to populate od_pairs on each TripPair.

    No parameter here has a default and none is Optional — all resolution
    (draft proposal_id/version, "None scenario_id means live base") happens
    once at the API boundary before this is called. See the ID convention
    note at the top of this module.

    schedule_mode: dispatched via timetable.build_schedule() — see that
    module for the pluggable strategy (currently only "alwaysDaily").

    scenario_id: stored as-is in RouteProvenance so the Route stays
    reproducible even if the live base scenario later moves on.
    """
    schedule = build_schedule(schedule_mode)
    rid = _route_id(proposal_id, proposal_version)
    logger.info(
        "plan_route: id=%s pairs=%d scenario_id=%d",
        rid,
        len(trip_pair_inputs),
        scenario_id,
    )

    trip_pairs: list[TripPair] = []
    merged_param_versions = ParamVersions()
    tracks_used: TrackInfraCollection | None = None

    # Built once for the whole route, not once per trip pair — a Y-shaped
    # route with several compositions would otherwise reload the entire
    # catalog per pair. include_indicative=False since route building
    # never touches Composition.indicative (see build_all_compositions()).
    compositions = loader.build_all_compositions(scenario_id, include_indicative=False)

    for i, pair_input in enumerate(trip_pair_inputs, start=1):
        pair, param_versions, tracks = _build_trip_pair(
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

    logger.info("plan_route done: id=%s pairs=%d", rid, len(route.trip_pairs))
    return route, RouteProvenance(
        model_versions=model_versions,
        param_versions=merged_param_versions,
        scenario_id=scenario_id,
        tracks=tracks_used,
    )


# =============================================================================
# ADJUST ROUTE — schedule changes only, no rerouting
# =============================================================================


def adjust_route(
    existing_route: Route,
    existing_provenance: RouteProvenance,
    proposal_id: int,
    proposal_version: int,
    schedule: Schedule | None = None,
    departure_time_min: int | None = None,
    stop_type_changes: dict[str, StopType] | None = None,
    od_pairs: list[ODPair] | None = None,
    loader=None,
    tracks: TrackInfraCollection | None = None,
) -> tuple[Route, RouteProvenance]:
    """
    Create a new Route version with schedule or timetable changes — no
    rerouting, segment physics copied unchanged. Provenance carries over
    unchanged since no recalculation happens.

    schedule: new Schedule for the route, or None to keep existing.
    departure_time_min: applied to every TripPair, or None to keep existing.
    stop_type_changes: {stop_id: StopType} overrides, or None to keep existing.
    """
    rid = _route_id(proposal_id, proposal_version)
    logger.info(
        "adjust_route: id=%s from=%s scenario_id=%d",
        rid,
        existing_route.route_id,
        existing_provenance.scenario_id,
    )

    # _build_trip_stops_and_legs() below always needs tracks whenever segments are being
    # rebuilt — which happens for EITHER stop_type_changes OR a departure
    # time change (dwell times, buffer times etc. are re-derived either
    # way). The old condition here only loaded tracks for stop_type_changes,
    # leaving a departure-time-only adjust to hit _build_trip_stops_and_legs() with
    # tracks=None → AttributeError on tracks.get().
    rebuilding_segments = stop_type_changes or departure_time_min is not None
    if rebuilding_segments and tracks is None and loader is not None:
        tracks = loader.build_all_tracks(existing_provenance.scenario_id)
        stop_infra = loader.build_all_stops(existing_provenance.scenario_id)
    else:
        stop_infra = (
            loader.build_all_stops(existing_provenance.scenario_id) if loader else None
        )

    new_pairs: list[TripPair] = []

    for pair_index, pair in enumerate(existing_route.trip_pairs, start=1):
        new_trips: dict[int, Trip] = {}

        for existing_trip in pair.trips:
            new_dep = (
                departure_time_min
                if departure_time_min is not None
                else existing_trip.departure_time_min
            )
            new_tid = _trip_id(
                proposal_id, proposal_version, existing_trip.direction, pair_index
            )

            if stop_type_changes or departure_time_min is not None:
                stop_inputs = [
                    (
                        s.stop_id,
                        (
                            stop_type_changes.get(s.stop_id, s.stop_type)
                            if stop_type_changes
                            else s.stop_type
                        ),
                    )
                    for s in existing_trip.stops
                ]
                routed_legs = [
                    RoutedLeg(
                        geometry=seg.geometry,
                        distance_m=seg.distance_m,
                        driving_time_min=seg.driving_time_min,
                        buffer_time_min=seg.buffer_time_min,
                        energy_kwh=seg.energy_kwh,
                        country_distance_shares=seg.country_distance_shares,
                        country_time_shares=seg.country_time_shares,
                    )
                    for seg in existing_trip.segments
                ]
                new_segments = _build_trip_stops_and_legs(
                    stop_inputs=stop_inputs,
                    routed_legs=routed_legs,
                    composition=pair.composition,
                    tracks=tracks,
                    stop_infra=stop_infra,
                    departure_time_min=new_dep,
                )
            else:
                new_segments = existing_trip.segments

            new_trips[existing_trip.direction] = Trip._create(
                trip_id=new_tid,
                direction=existing_trip.direction,
                segments=new_segments,
            )

        new_pairs.append(
            TripPair(
                outbound=new_trips[0],
                return_trip=new_trips[1],
                composition=pair.composition,
                od_pairs=pair.od_pairs,  # carry over existing demand
            )
        )

    parking = (
        _parkings(
            [t for pair in new_pairs for t in pair.trips],
            stop_infra,
        )
        if stop_infra
        else existing_route.parkings
    )

    route = Route._create(
        route_id=rid,
        schedule=schedule if schedule is not None else existing_route.schedule,
        trip_pairs=new_pairs,
        parkings=parking,
        shuntings=_shuntings([t for pair in new_pairs for t in pair.trips]),
    )

    logger.info("adjust_route done: id=%s pairs=%d", rid, len(route.trip_pairs))
    return route, existing_provenance


# =============================================================================
# DEMAND DISTRIBUTION
# =============================================================================


def distribute_demand(
    route: Route,
    utilization_per: float,
    fare_per_km_by_class: dict[str, float],
) -> Route:
    """
    Proxy demand model: distributes uniform demand across all valid OD pairs
    for each trip pair, based on a target utilization and per-km fare.

    This is a placeholder until a proper demand model is built. Assumptions:
    - A night train place is sold at most once per night (no double-selling),
      so each place contributes to exactly one OD pair per trip.
    - Demand is spread uniformly across all valid OD pairs within each class.
    - Valid OD pair: origin.stop_type in {BOARDING, BOTH} and
      destination.stop_type in {ALIGHTING, BOTH} and origin precedes
      destination in the trip's stop sequence. Stops that are boarding-only
      (e.g. pre-midnight city stops) cannot be destinations; stops that are
      alighting-only (e.g. early-morning terminus) cannot be origins.
    - avg_price per OD pair is derived as fare_per_km_by_class[class] ×
      distance_km between origin and destination stop (sum of segment
      distances between those stop indices in the outbound trip).
    - places_sold per OD pair (annual) = floor(
          composition_places_by_class[class] × utilization_per
          / n_valid_od_pairs_for_class
      ) × operating_days_per_year
    - Demand is set on the outbound trip only. The return trip gets a
      mirrored set of OD pairs with origin/destination swapped and the
      same utilization applied to return direction capacity.

    Returns the route with each TripPair's od_pairs populated.
    Replaces any existing od_pairs on the trip pairs.

    TODO: replace with a proper demand model that accounts for asymmetric
    directional demand, price elasticity, and competition from other modes.
    """
    operating_days = route.schedule.operating_days_per_year

    for pair in route.trip_pairs:
        od_pairs: list[ODPair] = []

        for trip in pair.trips:
            stops = trip.stops

            # Build segment distance lookup: cumulative distance up to each stop index
            # so distance between stop[i] and stop[j] = cumulative[j] - cumulative[i]
            cumulative_km: list[float] = [0.0]
            for segment in trip.segments:
                cumulative_km.append(cumulative_km[-1] + segment.distance_m / 1000.0)

            # Find valid (origin_idx, destination_idx) pairs
            valid_pairs: list[tuple[int, int]] = [
                (i, j)
                for i in range(len(stops))
                for j in range(i + 1, len(stops))
                if stops[i].stop_type in (StopType.BOARDING, StopType.BOTH)
                and stops[j].stop_type in (StopType.ALIGHTING, StopType.BOTH)
            ]

            if not valid_pairs:
                continue

            # Distribute demand per class
            places_by_class = pair.composition.places_by_class
            for class_main, total_places in places_by_class.items():
                fare_per_km = fare_per_km_by_class.get(class_main, 0.0)
                n_pairs = len(valid_pairs)
                if n_pairs == 0 or fare_per_km == 0.0:
                    continue

                # Annual places sold per OD pair: distribute uniformly.
                # Floor ensures we never exceed physical capacity.
                places_per_od = int(
                    (total_places * utilization_per / n_pairs) * operating_days
                )

                for origin_idx, dest_idx in valid_pairs:
                    origin = stops[origin_idx]
                    destination = stops[dest_idx]
                    distance_km = cumulative_km[dest_idx] - cumulative_km[origin_idx]
                    avg_price = fare_per_km * distance_km

                    od_pairs.append(
                        ODPair(
                            origin_stop_id=origin.stop_id,
                            destination_stop_id=destination.stop_id,
                            class_main=class_main,
                            trip_id=trip.trip_id,
                            places_sold=places_per_od,
                            avg_price=avg_price,
                        )
                    )

        # TripPair isn't frozen — plain reassignment replaces any od_pairs
        # the pair may already have (e.g. from a prior distribute_demand() call).
        pair.od_pairs = od_pairs

    return route
