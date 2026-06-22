"""
route_factory.py
================
Factory functions for constructing Trip and Route domain objects.

Unit conventions (internal)
----------------------------
  Distance : metres  (_m)
  Duration : minutes (_min)
  Clock time: minutes from midnight day 1 (_min)
  Energy   : kWh     (_kwh)

Pipeline for build_trip()
--------------------------
1.  Load params from DB (composition, infra, stops).
2.  Build param snapshot.
3.  Call RailRouter.route() → _RouterResult (physics, no energy, no costs).
4.  Call calc_energy_consumption() → enriches _CountryLeg.energy_kwh in-place.
5.  Compute stop_times schedule (times only, no costs).
6.  Convert _CountryLeg → CountryLeg (physics only — NO cost enrichment).
7.  Build TripSegments and CountrySegments.
8.  Compute TripStats (physics only).
9.  Assemble and return Trip.

Note: schedule (step 5) is computed BEFORE segment conversion (step 6)
as it uses raw router times directly.

NO cost calculations in this module — all monetary values computed
exclusively in models/cost_rev_eval/calc.py.

DB loader interface
-------------------
loader must implement:
  build_composition(comp_id: str) -> CompositionParams
  build_all_infra() -> InfraCollection
  build_all_stop_params(stop_ids: list[str]) -> StopCollection

TODO: add to DBDataLoader for param snapshots:
  get_composition_version(comp_id: str) -> int
  get_table_generation(table_name: str) -> int  (post table_versions)
  get_max_infra_row_id() -> int                 (stand-in)
  get_max_stop_row_id() -> int                  (stand-in)
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from models.params import CompositionParams, InfraCollection, StopCollection
from models.route.trip import (
    CountryLeg,
    CountrySegment,
    ParamsSnapshot,
    StopTime,
    TripPath,
    TripSegment,
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

# TODO Think of route_id and trip_id handling... probably the best would be to have arbitrary route and trip ids before saving a scenario and then somehow a clean up method before saving
def _new_trip_id() -> str:
    return str(uuid.uuid4())


def _new_route_id() -> str:
    return str(uuid.uuid4())


# =============================================================================
# PARAM SNAPSHOT HELPERS
# =============================================================================

def _get_composition_version(loader, comp_id: str) -> int:
    """TODO: implement get_composition_version() on DBDataLoader."""
    try:
        return loader.get_composition_version(comp_id)
    except AttributeError:
        logger.warning(
            "DBDataLoader.get_composition_version() not implemented — "
            "using 1 as stand-in for '%s'.", comp_id
        )
        return 1


def _get_infra_generation(loader) -> int:
    """TODO: implement get_table_generation() on DBDataLoader."""
    try:
        return loader.get_table_generation("infrastructure")
    except AttributeError:
        pass
    try:
        return loader.get_max_infra_row_id()
    except AttributeError:
        logger.warning("DBDataLoader infra generation lookup not implemented — using 0.")
        return 0


def _get_stops_generation(loader) -> int:
    """TODO: implement get_table_generation() on DBDataLoader."""
    try:
        return loader.get_table_generation("stops")
    except AttributeError:
        pass
    try:
        return loader.get_max_stop_row_id()
    except AttributeError:
        logger.warning("DBDataLoader stops generation lookup not implemented — using 0.")
        return 0


# =============================================================================
# SCHEDULE COMPUTATION
# =============================================================================

def _compute_stop_times(
        snapped_stops:      list,
        segments:           list,
        composition:        CompositionParams,
        infra:              InfraCollection,
        departure_time_min: int,
) -> list[StopTime]:
    """
    Compute timetable from snapped stops and router segments.
    Uses only driving/buffer times and dwell constraints — no costs.

    TODO: remove × 60 conversions once params.py uses _min units.
    """
    stop_times: list[StopTime] = []
    current_min = departure_time_min

    for i, ss in enumerate(snapped_stops):
        stop      = ss.stop
        stop_type = stop.stop_type
        is_first  = (i == 0)
        is_last   = (i == len(snapped_stops) - 1)

        arrival_min: int | None = None if is_first else current_min

        dwell_min: int | None = None
        # ToDo: Understand that next part ... seems to be a bit off ... e.g. if not is_last is there twice
        if not is_first and not is_last:
            ip         = infra.get_or_default(stop.country_code)
            candidates: list[float] = []
            if stop_type in ("boarding", "both"):
                candidates.append(composition.min_boarding_time_h * 60)  # TODO: _min
                if ip:
                    candidates.append(ip.min_boarding_time_h * 60)       # TODO: _min
            if stop_type in ("alighting", "both"):
                candidates.append(composition.min_alighting_time_h * 60) # TODO: _min
                if ip:
                    candidates.append(ip.min_alighting_time_h * 60)      # TODO: _min
            dwell_min = round(max(candidates)) if candidates else 0

        departure_min: int | None = None
        if not is_last:
            departure_min = current_min if is_first else (arrival_min + dwell_min)
            current_min   = departure_min

        if not is_last:
            seg         = segments[i]
            current_min = departure_min + seg.total_time_min

        stop_times.append(StopTime(
            stop_id            = stop.stop_id,
            stop_name          = stop.name,
            lat                = ss.snapped_lat,
            lon                = ss.snapped_lon,
            stop_type          = stop_type,
            arrival_time_min   = arrival_min,
            departure_time_min = departure_min,
            dwell_time_min     = dwell_min,
        ))

    return stop_times


# =============================================================================
# SEGMENT CONVERSION — physics only, no cost enrichment
# =============================================================================

def _router_leg_to_country_leg(router_leg: Any) -> CountryLeg:
    """
    Convert a physics+energy _CountryLeg to a CountryLeg domain object.
    Physics only — no TAC, no energy cost, no station charges.
    energy_kwh must already be populated by calc_energy_consumption().
    """
    return CountryLeg(
        from_stop_id      = router_leg.from_stop_id,
        to_stop_id        = router_leg.to_stop_id,
        country_code      = router_leg.country_code,
        distance_m        = router_leg.distance_m,
        driving_time_min  = router_leg.driving_time_min,
        buffer_time_min   = router_leg.buffer_time_min,
        energy_kwh        = router_leg.energy_kwh,
        energy_kwh_per_km = router_leg.energy_kwh_per_km,
    )


def _router_segment_to_trip_segment(
        router_segment: Any,
        country_legs:   list[CountryLeg],
) -> TripSegment:
    return TripSegment(
        from_stop_id = router_segment.from_stop_id,
        to_stop_id   = router_segment.to_stop_id,
        geometry     = router_segment.geometry,
        country_legs = country_legs,
    )


def _convert_segments(router_segments: list) -> list[TripSegment]:
    result = []
    for seg in router_segments:
        legs = [_router_leg_to_country_leg(cl) for cl in seg.country_legs]
        result.append(_router_segment_to_trip_segment(seg, legs))
    return result


def _build_country_segments(segments: list[TripSegment]) -> list[CountrySegment]:
    country_legs: dict[str, list[CountryLeg]] = {}
    for seg in segments:
        for cl in seg.country_legs:
            if cl.country_code not in country_legs:
                country_legs[cl.country_code] = []
            country_legs[cl.country_code].append(cl)
    return [
        CountrySegment(country_code=cc, country_legs=legs)
        for cc, legs in country_legs.items()
    ]


# =============================================================================
# PARKING LOCATIONS
# =============================================================================

def _compute_parking_locations(
        stop_inputs: list[tuple[str, str]],
        stop_params: StopCollection,
) -> list[ParkingLocation]:
    """
    Identify unique endpoint countries where parking costs apply.
    The cost model looks up parking_eur_day per country from infra params.
    """
    seen_countries: set[str] = set()
    locations: list[ParkingLocation] = []

    for stop_id in (stop_inputs[0][0], stop_inputs[-1][0]):
        sp = stop_params.get(stop_id)
        if sp is None:
            logger.warning("Stop '%s' not found — parking location skipped.", stop_id)
            continue
        cc = sp.stop_country_code
        if cc not in seen_countries:
            seen_countries.add(cc)
            locations.append(ParkingLocation(
                stop_id      = sp.stop_id,
                stop_name    = sp.stop_name,
                country_code = cc,
            ))

    return locations


# =============================================================================
# TRIP FACTORY
# =============================================================================

def build_trip(
        stop_inputs:        list[tuple[str, str]],
        composition_id:     str,
        departure_time_min: int,
        direction:          int,
        loader,
        router:             RailRouter,
) -> Trip:
    """
    Build a fully constructed Trip from scratch.

    Parameters
    ----------
    stop_inputs : list[tuple[str, str]]
        Ordered stop list as (stop_id, stop_type) pairs.
    composition_id : str
        Key into input_params.compositions.
    departure_time_min : int
        Departure time in minutes from midnight day 1 (e.g. 21:00 → 1260).
    direction : int
        0 = outbound, 1 = return.
    loader : DBDataLoader
        Pre-initialised data loader.
    router : RailRouter
        Pre-initialised routing engine client.

    Returns
    -------
    Trip
        Fully constructed immutable Trip — physics only, no monetary values.
    """
    trip_id  = _new_trip_id()
    stop_ids = [stop_id for stop_id, _ in stop_inputs]

    # 1. load params
    composition = loader.build_composition(composition_id)
    infra       = loader.build_all_infra()
    stop_params = loader.build_all_stop_params(stop_ids)

    logger.info(
        "build_trip: id=%s direction=%d composition=%s stops=%d",
        trip_id, direction, composition_id, len(stop_ids),
    )

    # validate stops
    stops = []
    for stop_id, stop_type in stop_inputs:
        sp = stop_params.get(stop_id)
        if sp is None:
            raise ValueError(f"Stop '{stop_id}' not found in database.")
        stops.append(Stop.from_params(sp, stop_type))

    # 2. param snapshot
    snapshot = ParamsSnapshot(
        composition_id        = composition_id,
        composition_version   = _get_composition_version(loader, composition_id),
        infra_generation      = _get_infra_generation(loader),
        stops_generation      = _get_stops_generation(loader),
        route_builder_version = ROUTE_BUILDER_VERSION,
        energy_calc_version   = ENERGY_CALC_VERSION,
    )

    # 3. route (physics only — energy_kwh = 0.0)
    router_result = router.route(
        stops              = stops,
        composition        = composition,
        infra              = infra.all(),
        departure_time_min = departure_time_min,
    )

    # 4. energy consumption (enriches _CountryLeg.energy_kwh in-place)
    calc_energy_consumption(router_result, composition)

    # 5. schedule — before segment conversion
    stop_times = _compute_stop_times(
        snapped_stops      = router_result.snapped_stops,
        segments           = router_result.segments,
        composition        = composition,
        infra              = infra,
        departure_time_min = departure_time_min,
    )

    # 6+7. convert router segments → domain objects (physics only)
    segments  = _convert_segments(router_result.segments)
    countries = _build_country_segments(segments)

    # 8. stats (physics only)
    stats = TripStats(
        total_distance_m        = router_result.total_distance_m,
        total_driving_time_min  = router_result.total_driving_time_min,
        total_time_min          = router_result.total_time_min,
        total_energy_kwh        = sum(
            cl.energy_kwh
            for seg in segments
            for cl in seg.country_legs
        ),
    )

# TODO: check whether segments and countries should be part of TripPath object
    path = TripPath(
        shape     = router_result.shape,
        segments  = segments,
        countries = countries,
    )

    logger.info(
        "build_trip done: id=%s %dm %.0fmin %.1fkWh",
        trip_id, stats.total_distance_m,
        stats.total_time_min, stats.total_energy_kwh,
    )

    return Trip(
        trip_id            = trip_id,
        direction          = direction,
        departure_time_min = departure_time_min,
        params_snapshot    = snapshot,
        composition        = composition,
        stop_times         = stop_times,
        path               = path,
        stats              = stats,
    )


# =============================================================================
# ROUTE FACTORY
# =============================================================================

def build_route(
        stop_inputs:        list[tuple[str, str]],
        composition_id:     str,
        departure_time_min: int,
        loader,
        router:             RailRouter,
) -> Route:
    """
    Build a Route with outbound (direction=0) and return (direction=1) trips.

    operator_id derived from composition's comp_operator_id via DB.
    parking_locations derived from endpoint stop country codes.
    No monetary values computed here.

    Parameters
    ----------
    stop_inputs : list[tuple[str, str]]
        Ordered outbound stop list. Return direction is automatically reversed.
    composition_id : str
        Composition key — same for both directions for now.
    departure_time_min : int
        Departure time in minutes — same for both directions for now.
    loader : DBDataLoader
        Pre-initialised data loader.
    router : RailRouter
        Pre-initialised routing engine client.
    """
    route_id = _new_route_id()

    logger.info(
        "build_route: id=%s composition=%s stops=%d",
        route_id, composition_id, len(stop_inputs),
    )

    # outbound trip
    outbound = build_trip(
        stop_inputs        = stop_inputs,
        composition_id     = composition_id,
        departure_time_min = departure_time_min,
        direction          = 0,
        loader             = loader,
        router             = router,
    )

    # return trip (reversed stops)
    return_trip = build_trip(
        stop_inputs        = list(reversed(stop_inputs)),
        composition_id     = composition_id,
        departure_time_min = departure_time_min,
        direction          = 1,
        loader             = loader,
        router             = router,
    )

    # parking locations (endpoint stops, outbound direction)
    stop_ids    = [stop_id for stop_id, _ in stop_inputs]
    stop_params = loader.build_all_stop_params(stop_ids)
    parking_locations = _compute_parking_locations(stop_inputs, stop_params)

    # operator_id from composition
    operator_id = outbound.composition.company

    trips = {
        outbound.trip_id:    outbound,
        return_trip.trip_id: return_trip,
    }

    logger.info(
        "build_route done: id=%s operator=%s parking_locations=%d",
        route_id, operator_id, len(parking_locations),
    )

    return Route(
        route_id          = route_id,
        operator_id       = operator_id,
        parking_locations = parking_locations,
        trips             = trips,
    )