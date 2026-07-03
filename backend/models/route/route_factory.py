"""
route_factory.py
================
Sole entry point for constructing Trip, TripPair, and Route domain objects.

Pipeline for plan_route() per TripPair
----------------------------------------
1. Load composition + ParamVersions from DB.
2. Load tracks + stops + ParamVersions from DB.
3. Build StopInput objects (StopInfrastructure + StopType) for the router.
4. RailRouter.route() → list[RoutedLeg] (energy_kwh=0.0).
5. calc_energy_consumption() enriches RoutedLeg.energy_kwh in-place.
6. _build_stops() pairs RoutedLeg physics with Stop timetable data → list[Segment].
7. Trip._create() for outbound and return — no composition, no version fields.
8. TripPair._create() bundles both trips with their shared composition and schedule.
9. Route._create() assembles all TripPairs.

Returns (Route, RouteProvenance) — provenance is not stored on Trip/Route,
caller persists it alongside route_id when writing a proposal result.

ID convention
-------------
  route_id : P{proposal_id}_V{version}_R1
  trip_id  : P{proposal_id}_V{version}_R1_D{direction}_T{pair_index}
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from models.params import ModelVersions, ParamVersions, ODPair, TrackInfraCollection, StopInfraCollection, Composition
from models.route.trip import Stop, StopType, Segment, Trip
from models.route.route import Route, TripPair, Parking, Shunting, Schedule
from models.route.routing.rail_router import RailRouter, StopInput, RoutedLeg
from models.energy.calc_energy_consumption import calc_energy_consumption
from models.route.version import ROUTE_BUILDER_VERSION
from models.energy.version import ENERGY_CALC_VERSION

logger = logging.getLogger(__name__)

@dataclass
class RouteProvenance:
    """What was used to build a Route — returned alongside it, not stored on it."""
    model_versions: ModelVersions
    param_versions: ParamVersions

@dataclass
class TripPairInput:
    """One outbound + return cycle to build. Schedule lives on Route — all
    pairs share one schedule, passed to plan_route() directly."""
    stop_inputs: list[tuple[str, StopType]]  # outbound order; return is reversed
    composition_id: str
    departure_time_min: int

# =============================================================================
# ID GENERATION
# =============================================================================

def _route_id(proposal_id: int, version: int) -> str:
    return f"P{proposal_id}_V{version}_R1"

def _trip_id(proposal_id: int, version: int, direction: int, pair_index: int) -> str:
    return f"P{proposal_id}_V{version}_R1_D{direction}_T{pair_index}"

# =============================================================================
# STOP TIMETABLE
# =============================================================================

def _build_stops(
    stop_inputs: list[tuple[str, StopType]],
    routed_legs: list[RoutedLeg],
    composition: Composition,
    tracks: TrackInfraCollection,
    stop_infra: StopInfraCollection,
    departure_time_min: int,
) -> list[Segment]:
    """
    Pairs RoutedLeg physics with Stop timetable data into list[Segment].
    Builds one Stop per physical stop in a single forward pass, then pairs
    consecutive stops into segments — each Stop is shared by reference
    between the two segments touching it.

    Dwell at intermediate stops is the max of composition/track minimums
    for whichever of boarding/alighting/both applies.
    """
    n = len(stop_inputs)
    stops: list[Stop] = []
    current_min = departure_time_min

    for i, (stop_id, stop_type) in enumerate(stop_inputs):
        sp = stop_infra.get(stop_id)
        if sp is None:
            raise ValueError(f"Stop '{stop_id}' not found in database.")

        is_first = (i == 0)
        is_last = (i == n - 1)

        arrival_min: int | None = None if is_first else current_min

        dwell_min = 0
        if not is_first and not is_last:
            track = tracks.get_or_default(sp.stop_country_code)
            candidates: list[int] = []
            if stop_type in (StopType.BOARDING, StopType.BOTH):
                candidates += [composition.min_boarding_time_min, track.min_boarding_time_min]
            if stop_type in (StopType.ALIGHTING, StopType.BOTH):
                candidates += [composition.min_alighting_time_min, track.min_alighting_time_min]
            dwell_min = max(candidates) if candidates else 0

        departure_min: int | None = None
        if not is_last:
            departure_min = current_min if is_first else (arrival_min + dwell_min)
            current_min = departure_min + routed_legs[i].total_time_min

        stops.append(Stop(
            stop_id=sp.stop_id, stop_name=sp.stop_name, country_code=sp.stop_country_code, lat=sp.lat, lon=sp.lon,
            stop_type=stop_type, arrival_time_min=arrival_min, departure_time_min=departure_min,
        ))

    return [
        Segment(
            from_stop=stops[i], to_stop=stops[i + 1],
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
                    logger.warning("Stop '%s' not found — parking skipped.", stop.stop_id)
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
                result.append(Shunting(
                    stop_id=stop.stop_id,
                    stop_name=stop.stop_name,
                    country_code=stop.country_code,
                    trip_id=trip.trip_id,
                ))
    return result

# =============================================================================
# TRIP BUILDER
# =============================================================================

def _build_trip(
    proposal_id: int, proposal_version: int, direction: int, pair_index: int,
    stop_inputs: list[tuple[str, StopType]], composition: Composition,
    tracks: TrackInfraCollection, stop_infra: StopInfraCollection,
    departure_time_min: int, router: RailRouter,
) -> Trip:
    tid = _trip_id(proposal_id, proposal_version, direction, pair_index)

    router_stops = [
        StopInput(stop=stop_infra.get(stop_id), stop_type=stop_type)
        for stop_id, stop_type in stop_inputs
    ]
    for ri, (stop_id, _) in zip(router_stops, stop_inputs):
        if ri.stop is None:
            raise ValueError(f"Stop '{stop_id}' not found in database.")

    routed_legs = router.route(stops=router_stops, composition=composition, tracks=tracks)
    calc_energy_consumption(routed_legs, composition)

    segments = _build_stops(
        stop_inputs=stop_inputs, routed_legs=routed_legs, composition=composition,
        tracks=tracks, stop_infra=stop_infra, departure_time_min=departure_time_min,
    )

    trip = Trip._create(trip_id=tid, direction=direction, segments=segments)
    logger.info("_build_trip: id=%s %dm %.0fmin", tid, trip.distance_m, trip.total_time_min)
    return trip

# =============================================================================
# TRIP PAIR BUILDER
# =============================================================================

def _build_trip_pair(
    proposal_id: int, proposal_version: int, pair_index: int,
    pair_input: TripPairInput, loader, router: RailRouter,
) -> tuple[TripPair, ParamVersions]:
    composition, comp_versions = loader.build_composition(pair_input.composition_id)
    tracks, track_versions = loader.build_all_tracks()
    stop_infra, stop_versions = loader.build_all_stops()

    param_versions = ParamVersions()
    param_versions.entries.update(comp_versions.entries)
    param_versions.entries.update(track_versions.entries)
    param_versions.entries.update(stop_versions.entries)

    outbound = _build_trip(
        proposal_id, proposal_version, direction=0, pair_index=pair_index,
        stop_inputs=pair_input.stop_inputs, composition=composition,
        tracks=tracks, stop_infra=stop_infra,
        departure_time_min=pair_input.departure_time_min, router=router,
    )
    return_trip = _build_trip(
        proposal_id, proposal_version, direction=1, pair_index=pair_index,
        stop_inputs=list(reversed(pair_input.stop_inputs)), composition=composition,
        tracks=tracks, stop_infra=stop_infra,
        departure_time_min=pair_input.departure_time_min, router=router,
    )

    pair = TripPair(
        outbound=outbound, return_trip=return_trip,
        composition=composition,
        od_pairs=[],   # populated later by distribute_demand()
    )
    return pair, param_versions

# =============================================================================
# PLAN ROUTE — full routing pipeline
# =============================================================================

def plan_route(
    proposal_id: int, proposal_version: int,
    schedule: Schedule,
    trip_pair_inputs: list[TripPairInput],
    loader, router: RailRouter,
) -> tuple[Route, RouteProvenance]:
    """
    Build a Route from scratch. One TripPair per entry in trip_pair_inputs
    (Y-shaped routes pass several, each with its own composition).
    All pairs share the route-level schedule.
    Demand is not set here — call distribute_demand() after plan_route()
    to populate od_pairs on each TripPair.
    For schedule-only changes use adjust_route() instead.
    """
    rid = _route_id(proposal_id, proposal_version)
    logger.info("plan_route: id=%s pairs=%d", rid, len(trip_pair_inputs))

    trip_pairs: list[TripPair] = []
    merged_param_versions = ParamVersions()

    for i, pair_input in enumerate(trip_pair_inputs, start=1):
        pair, param_versions = _build_trip_pair(
            proposal_id, proposal_version, pair_index=i,
            pair_input=pair_input, loader=loader, router=router,
        )
        trip_pairs.append(pair)
        merged_param_versions.entries.update(param_versions.entries)

    model_versions = ModelVersions(versions={
        "route_builder": ROUTE_BUILDER_VERSION,
        "energy_calc": ENERGY_CALC_VERSION,
    })

    stop_infra, _ = loader.build_all_stops()
    parking = _parkings(
        [t for pair in trip_pairs for t in pair.trips], stop_infra,
    )

    route = Route._create(
        route_id=rid, schedule=schedule, trip_pairs=trip_pairs,
        parkings=parking,
        shuntings=_shuntings([t for pair in trip_pairs for t in pair.trips]),
    )

    logger.info("plan_route done: id=%s pairs=%d", rid, len(route.trip_pairs))
    return route, RouteProvenance(model_versions=model_versions, param_versions=merged_param_versions)

# =============================================================================
# ADJUST ROUTE — schedule changes only, no rerouting
# =============================================================================

def adjust_route(
    existing_route: Route, existing_provenance: RouteProvenance,
    proposal_id: int, proposal_version: int,
    schedule: Schedule | None = None,
    departure_time_min: int | None = None,
    stop_type_changes: dict[str, StopType] | None = None,
    od_pairs: list[ODPair] | None = None,
    loader=None, tracks: TrackInfraCollection | None = None,
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
    logger.info("adjust_route: id=%s from=%s", rid, existing_route.route_id)

    if stop_type_changes and tracks is None and loader is not None:
        tracks, _ = loader.build_all_tracks()
        stop_infra, _ = loader.build_all_stops()
    else:
        stop_infra = loader.build_all_stops()[0] if loader else None

    new_pairs: list[TripPair] = []

    for pair_index, pair in enumerate(existing_route.trip_pairs, start=1):
        new_trips: dict[int, Trip] = {}

        for existing_trip in pair.trips:
            new_dep = departure_time_min if departure_time_min is not None \
                else existing_trip.departure_time_min
            new_tid = _trip_id(proposal_id, proposal_version, existing_trip.direction, pair_index)

            if stop_type_changes or departure_time_min is not None:
                stop_inputs = [
                    (s.stop_id, stop_type_changes.get(s.stop_id, s.stop_type) if stop_type_changes else s.stop_type)
                    for s in existing_trip.stops
                ]
                routed_legs = [
                    RoutedLeg(
                        geometry=seg.geometry, distance_m=seg.distance_m,
                        driving_time_min=seg.driving_time_min, buffer_time_min=seg.buffer_time_min,
                        energy_kwh=seg.energy_kwh,
                        country_distance_shares=seg.country_distance_shares,
                        country_time_shares=seg.country_time_shares,
                    )
                    for seg in existing_trip.segments
                ]
                new_segments = _build_stops(
                    stop_inputs=stop_inputs, routed_legs=routed_legs,
                    composition=pair.composition, tracks=tracks,
                    stop_infra=stop_infra, departure_time_min=new_dep,
                )
            else:
                new_segments = existing_trip.segments

            new_trips[existing_trip.direction] = Trip._create(
                trip_id=new_tid, direction=existing_trip.direction, segments=new_segments,
            )

        new_pairs.append(TripPair(
            outbound=new_trips[0], return_trip=new_trips[1],
            composition=pair.composition,
            od_pairs=pair.od_pairs,   # carry over existing demand
        ))

    parking = _parkings(
        [t for pair in new_pairs for t in pair.trips], stop_infra,
    ) if stop_infra else existing_route.parkings

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

    TODO: replace with a proper demand model that accounts for asymmetric directional demand, price elasticity, and competition from other modes.
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

                    od_pairs.append(ODPair(
                        origin_stop_id=origin.stop_id,
                        destination_stop_id=destination.stop_id,
                        class_main=class_main,
                        trip_id=trip.trip_id,
                        places_sold=places_per_od,
                        avg_price=avg_price,
                    ))

        # Replace od_pairs on the pair (dataclass field reassignment)
        object.__setattr__(pair, 'od_pairs', od_pairs)

    return route