"""
route_factory.py
================
Sole entry point for constructing Trip and Route domain objects.

All Trip and Route objects MUST be constructed via build_route() —
never instantiate Trip._create() or Route._create() directly outside
this module.

Unit conventions (internal)
----------------------------
  Distance : metres  (_m)
  Duration : minutes (_min)
  Clock time: minutes from midnight day 1 (_min)
  Energy   : kWh     (_kwh)

Pipeline for build_route()
--------------------------
1.  Load composition + ParamVersions from DB.
2.  Load tracks + ParamVersions from DB.
3.  Load stops + ParamVersions from DB.
4.  Merge all ParamVersions.
5.  Build Stop objects from StopInfrastructure (DB lat/lon — authoritative).
6.  Call RailRouter.route() → TripPath (physics, no energy, no costs).
7.  Call calc_energy_consumption() → enriches CountryLeg.energy_kwh in-place.
8.  Compute stop_times schedule (times only, no costs).
9.  Compute TripStats.
10. Construct Trip via Trip._create() with GTFS-compatible ID convention.
11. Build outbound + return trips, construct Route via Route._create().

ID convention
-------------
  route_id : f"P{proposal_id}_V{version}_R1"                           e.g. "P1_V1_R1"
  trip_id  : f"P{proposal_id}_V{version}_R1_D{direction}_T{index}"     e.g. "P1_V1_R1_D0_T1"
  trip_index starts at 1 per direction.
  version increments on every proposal change (reroute or schedule adjustment).

NO cost calculations in this module — all monetary values computed
exclusively in models/cost_rev_eval/calc.py.
"""

from __future__ import annotations

import logging

from models.params import (
    ModelVersions,
    ParamVersions,
    Composition,
    StopInfrastructure,
    TrackInfraCollection,
    StopInfraCollection,
)
from models.route.trip import (
    StopTime,
    TripPath,
    TripStats,
    Trip,
)
from models.route.route import Route, ParkingLocation
from models.route.routing.rail_router import RailRouter, Stop
from models.energy.calc_energy_consumption import calc_energy_consumption
from models.route.version import ROUTE_BUILDER_VERSION
from models.energy.version import ENERGY_CALC_VERSION

logger = logging.getLogger(__name__)


# =============================================================================
# ID GENERATION
# =============================================================================

def _route_id(proposal_id: int, version: int) -> str:
    """e.g. proposal_id=1, version=1 → 'P1_V1_R1'"""
    return f"P{proposal_id}_V{version}_R1"


def _trip_id(proposal_id: int, version: int, direction: int, trip_index: int) -> str:
    """
    GTFS-compatible string trip ID.
    e.g. proposal_id=1, version=1, direction=0, trip_index=1 → "P1_V1_R1_D0_T1"
    trip_index starts at 1 per direction.
    """
    return f"P{proposal_id}_V{version}_R1_D{direction}_T{trip_index}"


# =============================================================================
# SCHEDULE COMPUTATION
# =============================================================================

def _compute_stop_times(
        stops:              list[Stop],
        trip_path:          TripPath,
        composition:        Composition,
        tracks:             TrackInfraCollection,
        departure_time_min: int,
) -> list[StopTime]:
    """
    Compute timetable from stops and routed TripPath.

    Dwell time logic:
      boarding only  → max(composition.min_boarding_time_min,
                           track.min_boarding_time_min)
      alighting only → max(composition.min_alighting_time_min,
                           track.min_alighting_time_min)
      both           → max of all four values

    Travel time between stops = segment.total_time_min
    (driving_time_min + buffer_time_min, already computed by router).

    lat/lon taken from Stop (built from StopInfrastructure DB coordinates).
    """
    stop_times: list[StopTime] = []
    current_min = departure_time_min

    for i, stop in enumerate(stops):
        is_first = (i == 0)
        is_last  = (i == len(stops) - 1)

        arrival_min: int | None = None if is_first else current_min

        # dwell time for intermediate stops
        dwell_min: int | None = None
        if not is_first and not is_last:
            track      = tracks.get_or_default(stop.country_code)
            stop_type  = stop.stop_type
            candidates: list[int] = []

            if stop_type in ("boarding", "both"):
                candidates.append(composition.min_boarding_time_min)
                candidates.append(track.min_boarding_time_min)
            if stop_type in ("alighting", "both"):
                candidates.append(composition.min_alighting_time_min)
                candidates.append(track.min_alighting_time_min)

            dwell_min = max(candidates) if candidates else 0

        departure_min: int | None = None
        if not is_last:
            departure_min = current_min if is_first else (arrival_min + dwell_min)
            # advance clock by segment travel time
            current_min = departure_min + trip_path.segments[i].total_time_min

        stop_times.append(StopTime(
            stop_id            = stop.stop_id,
            stop_name          = stop.name,
            lat                = stop.lat,
            lon                = stop.lon,
            stop_type          = stop.stop_type,
            arrival_time_min   = arrival_min,
            departure_time_min = departure_min,
            dwell_time_min     = dwell_min,
        ))

    return stop_times


# =============================================================================
# STATS COMPUTATION
# =============================================================================

def _compute_stats(trip_path: TripPath) -> TripStats:
    """Compute TripStats from a fully energy-enriched TripPath."""
    total_distance_m        = sum(s.distance_m       for s in trip_path.segments)
    total_driving_time_min  = sum(s.driving_time_min for s in trip_path.segments)
    total_time_min          = sum(s.total_time_min   for s in trip_path.segments)
    total_energy_kwh        = sum(
        cl.energy_kwh
        for s in trip_path.segments
        for cl in s.country_legs
    )
    return TripStats(
        total_distance_m       = total_distance_m,
        total_driving_time_min = total_driving_time_min,
        total_time_min         = total_time_min,
        total_energy_kwh       = total_energy_kwh,
    )


# =============================================================================
# PARKING LOCATIONS
# =============================================================================

def _compute_parking_locations(
        stop_inputs:  list[tuple[str, str]],
        stop_infra:   StopInfraCollection,
) -> list[ParkingLocation]:
    """
    Identify unique endpoint countries where parking costs apply.
    The cost model looks up parking_eur_day per country from track params.
    """
    seen:      set[str]            = set()
    locations: list[ParkingLocation] = []

    for stop_id in (stop_inputs[0][0], stop_inputs[-1][0]):
        sp = stop_infra.get(stop_id)
        if sp is None:
            logger.warning("Stop '%s' not found — parking location skipped.", stop_id)
            continue
        cc = sp.stop_country_code
        if cc not in seen:
            seen.add(cc)
            locations.append(ParkingLocation(
                stop_id      = sp.stop_id,
                stop_name    = sp.stop_name,
                country_code = cc,
            ))

    return locations


# =============================================================================
# TRIP BUILDER  (private — called only by build_route)
# =============================================================================

def _build_trip(
        proposal_id:        int,
        proposal_version:   int,
        direction:          int,
        trip_index:         int,
        stop_inputs:        list[tuple[str, str]],
        composition:        Composition,
        tracks:             TrackInfraCollection,
        stop_infra:         StopInfraCollection,
        param_versions:     ParamVersions,
        departure_time_min: int,
        router:             RailRouter,
) -> Trip:
    """
    Build one directional Trip. Private — called only by build_route().

    Uses DB lat/lon from StopInfrastructure for stop_times coordinates.
    Router snapping is for geometry only — not used for stop coordinates.
    """
    tid = _trip_id(proposal_id, proposal_version, direction, trip_index)
    logger.info(
        "_build_trip: id=%s direction=%d composition=%s stops=%d",
        tid, direction, composition.comp_id, len(stop_inputs),
    )

    # build Stop objects from StopInfrastructure (DB coordinates — authoritative)
    stops: list[Stop] = []
    for stop_id, stop_type in stop_inputs:
        sp = stop_infra.get(stop_id)
        if sp is None:
            raise ValueError(f"Stop '{stop_id}' not found in database.")
        stops.append(Stop.from_infra(sp, stop_type))

    # route → TripPath (energy_kwh = 0.0 on all CountryLegs)
    trip_path = router.route(
        stops       = stops,
        composition = composition,
        tracks      = tracks,
    )

    # enrich energy in-place
    calc_energy_consumption(trip_path, composition)

    # schedule
    stop_times = _compute_stop_times(
        stops              = stops,
        trip_path          = trip_path,
        composition        = composition,
        tracks             = tracks,
        departure_time_min = departure_time_min,
    )

    # stats
    stats = _compute_stats(trip_path)

    # model versions
    model_versions = ModelVersions(versions={
        "route_builder": ROUTE_BUILDER_VERSION,
        "energy_calc":   ENERGY_CALC_VERSION,
    })

    logger.info(
        "_build_trip done: id=%s %dm %.0fmin %.1fkWh",
        tid, stats.total_distance_m,
        stats.total_time_min, stats.total_energy_kwh,
    )

    return Trip._create(
        trip_id            = tid,
        direction          = direction,
        departure_time_min = departure_time_min,
        model_versions     = model_versions,
        param_versions     = param_versions,
        composition        = composition,
        stop_times         = stop_times,
        path               = trip_path,
        stats              = stats,
    )


# =============================================================================
# ROUTE FACTORY  (public entry point)
# =============================================================================

def plan_route(
        proposal_id:        int,
        proposal_version:   int,
        stop_inputs:        list[tuple[str, str]],
        composition_id:     str,
        departure_time_min: int,
        loader,
        router:             RailRouter,
) -> Route:
    """
    Build a Route from scratch — full routing pipeline.
    Called when creating a new proposal or when geometry/physics changes
    (stops, composition) require a full reroute.

    For lightweight schedule changes (departure time, stop types) on an
    existing proposal, use adjust_route() instead.

    Parameters
    ----------
    proposal_id : int
        Stable DB serial ID of the proposal.
    proposal_version : int
        Version counter for this proposal — drives the GTFS ID convention.
        route_id = f"P{proposal_id}_V{proposal_version}_R1"
        trip_id  = f"P{proposal_id}_V{proposal_version}_R1_D{direction}_T{trip_index}"
    stop_inputs : list[tuple[str, str]]
        Ordered outbound stop list as (stop_id, stop_type) pairs.
        Return direction uses the reversed list automatically.
    composition_id : str
        Key into input_params.composition_types.
    departure_time_min : int
        Departure time in minutes from midnight day 1 (e.g. 21:00 → 1260).
        Same for both directions.
    loader : DBDataLoader
        Pre-initialised data loader.
    router : RailRouter
        Pre-initialised routing engine client.

    Returns
    -------
    Route
        Fully constructed Route — physics only, no monetary values.
    """
    rid = _route_id(proposal_id, proposal_version)
    logger.info(
        "plan_route: id=%s composition=%s stops=%d",
        rid, composition_id, len(stop_inputs),
    )

    # 1. load params — each returns (object, ParamVersions)
    composition,  comp_versions  = loader.build_composition(composition_id)
    tracks,       track_versions = loader.build_all_tracks()
    stop_infra,   stop_versions  = loader.build_all_stops()

    # 2. merge all ParamVersions
    param_versions = ParamVersions()
    param_versions.entries.update(comp_versions.entries)
    param_versions.entries.update(track_versions.entries)
    param_versions.entries.update(stop_versions.entries)

    # 3. parking locations
    parking_locations = _compute_parking_locations(stop_inputs, stop_infra)

    # 4. build outbound trip (direction=0)
    outbound = _build_trip(
        proposal_id        = proposal_id,
        proposal_version   = proposal_version,
        direction          = 0,
        trip_index         = 1,
        stop_inputs        = stop_inputs,
        composition        = composition,
        tracks             = tracks,
        stop_infra         = stop_infra,
        param_versions     = param_versions,
        departure_time_min = departure_time_min,
        router             = router,
    )

    # 5. build return trip (direction=1, reversed stops)
    return_trip = _build_trip(
        proposal_id        = proposal_id,
        proposal_version   = proposal_version,
        direction          = 1,
        trip_index         = 1,
        stop_inputs        = list(reversed(stop_inputs)),
        composition        = composition,
        tracks             = tracks,
        stop_infra         = stop_infra,
        param_versions     = param_versions,
        departure_time_min = departure_time_min,
        router             = router,
    )

    # 6. assemble Route
    route = Route._create(
        route_id          = rid,
        parking_locations = parking_locations,
        trips             = {},
    )
    route.add_trip(outbound)
    route.add_trip(return_trip)

    logger.info(
        "plan_route done: id=%s operator=%s trips=%d",
        rid, route.operator_id, len(route.all_trips()),
    )

    return route


# =============================================================================
# ADJUST ROUTE  (lightweight copy — no rerouting)
# =============================================================================

def adjust_route(
        existing_route:     Route,
        proposal_id:        int,
        proposal_version:   int,
        departure_time_min: int | None = None,
        stop_type_changes:  dict[str, str] | None = None,
        loader              = None,
        tracks:             "TrackInfraCollection | None" = None,
) -> Route:
    """
    Create a new proposal version by copying an existing Route with
    lightweight schedule changes — no rerouting.

    Use this when only departure time or stop types change.
    For geometry/physics changes (stops, composition), use plan_route().

    Parameters
    ----------
    existing_route : Route
        The current route to copy from.
    proposal_id : int
        Stable proposal ID (unchanged across versions).
    proposal_version : int
        New version number (incremented from existing).
    departure_time_min : int | None
        New departure time in minutes. None = keep existing.
    stop_type_changes : dict[str, str] | None
        {stop_id: new_stop_type} overrides. None = keep existing.
    loader : DBDataLoader | None
        Required if stop_type_changes is provided (for track params).
    tracks : TrackInfraCollection | None
        Pre-loaded tracks. If None and stop_type_changes provided, loads from loader.
    """
    rid = _route_id(proposal_id, proposal_version)
    logger.info(
        "adjust_route: id=%s from=%s departure=%s stop_type_changes=%s",
        rid, existing_route.route_id, departure_time_min, stop_type_changes,
    )

    # load tracks if stop type changes need dwell recalculation
    if stop_type_changes and tracks is None and loader is not None:
        tracks, _ = loader.build_all_tracks()

    new_route = Route._create(
        route_id          = rid,
        parking_locations = existing_route.parking_locations,
        trips             = {},
    )

    for existing_trip in existing_route.all_trips():
        composition = existing_trip.composition
        new_dep     = departure_time_min if departure_time_min is not None                       else existing_trip.departure_time_min
        new_tid     = _trip_id(
            proposal_id, proposal_version,
            existing_trip.direction, 1,
        )

        # rebuild stop_times with new departure / stop types
        updated_stops = []
        for st in existing_trip.stop_times:
            new_type = stop_type_changes.get(st.stop_id, st.stop_type)                        if stop_type_changes else st.stop_type
            updated_stops.append(
                Stop(
                    stop_id      = st.stop_id,
                    name         = st.stop_name,
                    lat          = st.lat,
                    lon          = st.lon,
                    stop_type    = new_type,
                )
            )

        if tracks is not None:
            new_stop_times = _compute_stop_times(
                stops              = updated_stops,
                trip_path          = existing_trip.path,
                composition        = composition,
                tracks             = tracks,
                departure_time_min = new_dep,
            )
        else:
            # no dwell recalculation — just shift times
            delta = new_dep - existing_trip.departure_time_min
            new_stop_times = [st.shift_time(delta) for st in existing_trip.stop_times]

        new_stats = _compute_stats(existing_trip.path)

        new_trip = Trip._create(
            trip_id            = new_tid,
            direction          = existing_trip.direction,
            departure_time_min = new_dep,
            model_versions     = existing_trip.model_versions,
            param_versions     = existing_trip.param_versions,
            composition        = composition,
            stop_times         = new_stop_times,
            path               = existing_trip.path,
            stats              = new_stats,
        )
        new_route.add_trip(new_trip)

    logger.info(
        "adjust_route done: id=%s trips=%d",
        rid, len(new_route.all_trips()),
    )

    return new_route