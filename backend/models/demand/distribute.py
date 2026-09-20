"""
distribute.py
=============
DEMAND 0.1.0 on a Route: the manual demand of the request, allocated onto
every trip pair's composition (groups.py), spread over each trip's
sellable OD pairs (od_matrix.py) and written into TripPair.od_pairs as
annual places sold per pair and class — the shape models/evaluation reads.
Replaces the uniform stopgap that populated the same od_pairs since
ROUTE_BUILDER 0.9.13.

Per trip = per year ÷ departures (D10): every departure of the route, both
directions, carries the same demand, so halving the frequency doubles the
load on each train and turns what it cannot seat into "not served". The
outbound trip's sellable pairs are the matrix the request weights and pins
describe; the return trip gets the mirror image (origin and destination
swapped), renormalised over its own sellable pairs so an asymmetric stop
classification never sells a share to a pair that does not exist.

Assumptions carried over from the stopgap:
  - a night train place is sold at most once per night, so every place
    sold belongs to exactly one OD pair per trip;
  - avg_price per OD pair is the two-part base fare, fare_per_pax +
    fare_per_km × distance_km (services and catering ride on passengers
    in models/evaluation/calc.py).

Public interface:
  DemandInputs(...)                 the resolved request block as values
  DemandResult / PairDemand         what the API serialises (evaluation_
                                    serialize.demand_to_dict)
  distribute_demand(route, inputs, fare_per_km_by_class,
                    fare_per_pax_by_class) -> DemandResult   (mutates route)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from models.demand.groups import Allocation, allocate, split_by_group
from models.demand.model import CLASS_ORDER
from models.demand.od_matrix import (
    PairKey,
    SellablePair,
    alighting_stop_ids,
    average_distance_km,
    boarding_stop_ids,
    drop_stale_pins,
    od_shares,
    resolve_weights,
    sellable_pairs,
)
from models.demand.sources import SourceSplit, split_sources
from models.params import ODPair
from models.route.route import Route, TripPair


@dataclass(frozen=True)
class DemandInputs:
    """The request's demand block, resolved (api/helpers/member_compute.py
    fills the defaults). Weights keyed by stop id, pins by (origin,
    destination) stop id, in percent."""

    passengers_per_year: float
    group_shares_pct: dict[str, float]
    board_weights: dict[str, float] = field(default_factory=dict)
    alight_weights: dict[str, float] = field(default_factory=dict)
    pins_pct: dict[PairKey, float] = field(default_factory=dict)


@dataclass(frozen=True)
class PairDemand:
    """One trip pair's demand: the allocation of one departure onto its
    composition and the OD spread of the outbound trip (the matrix the
    request describes; the return trip is its mirror)."""

    composition_id: str
    allocation: Allocation
    pairs: list[SellablePair]
    shares: dict[PairKey, float]
    boarding_stop_ids: list[str]
    alighting_stop_ids: list[str]
    board_weights: dict[str, float]
    alight_weights: dict[str, float]
    pins_pct: dict[PairKey, float]
    dropped_pins: list[PairKey]
    average_distance_km: float
    sources: SourceSplit


@dataclass(frozen=True)
class DemandResult:
    passengers_per_year: float
    departures_per_year: float
    operating_days_per_year: float
    trip_pairs: list[PairDemand]

    @property
    def per_trip_demand(self) -> float:
        return (
            self.passengers_per_year / self.departures_per_year
            if self.departures_per_year
            else 0.0
        )


def _mirror_shares(
    outbound_shares: dict[PairKey, float], return_pairs: list[SellablePair]
) -> dict[PairKey, float]:
    """The return trip sells the outbound matrix mirrored; renormalised
    over the pairs the return trip actually has."""
    raw = {
        p.key: outbound_shares.get((p.destination_stop_id, p.origin_stop_id), 0.0)
        for p in return_pairs
    }
    total = sum(raw.values())
    return {k: (v / total if total else 0.0) for k, v in raw.items()}


def _write_od_pairs(
    trip_id: str,
    pairs: list[SellablePair],
    shares: dict[PairKey, float],
    allocation: Allocation,
    operating_days: float,
    fare_per_km_by_class: dict[str, float],
    fare_per_pax_by_class: dict[str, float],
) -> tuple[list[ODPair], list[tuple[float, float]]]:
    """Annual places sold per (pair, class) on one trip: the class's served
    places per departure × the pair's share × this trip's departures a
    year (one per operating day). Also returns the (distance_km,
    passengers) loads the source split sums over."""
    out: list[ODPair] = []
    loads: list[tuple[float, float]] = []
    for class_main in CLASS_ORDER:
        served = allocation.by_class.get(class_main, 0.0)
        if served <= 0.0:
            continue
        for pair in pairs:
            share = shares.get(pair.key, 0.0)
            if share <= 0.0:
                continue
            places_sold = served * share * operating_days
            out.append(
                ODPair(
                    origin_stop_id=pair.origin_stop_id,
                    destination_stop_id=pair.destination_stop_id,
                    class_main=class_main,
                    trip_id=trip_id,
                    places_sold=places_sold,
                    avg_price=fare_per_pax_by_class.get(class_main, 0.0)
                    + fare_per_km_by_class.get(class_main, 0.0) * pair.distance_km,
                )
            )
            loads.append((pair.distance_km, places_sold))
    return out, loads


def _pair_demand(
    pair: TripPair,
    inputs: DemandInputs,
    per_trip_demand_by_group: dict[str, float],
    operating_days: float,
    fare_per_km_by_class: dict[str, float],
    fare_per_pax_by_class: dict[str, float],
) -> PairDemand:
    allocation = allocate(pair.composition.places_by_class, per_trip_demand_by_group)

    outbound_pairs = sellable_pairs(pair.outbound)
    board_ids = boarding_stop_ids(pair.outbound)
    alight_ids = alighting_stop_ids(pair.outbound)
    board = resolve_weights(board_ids, inputs.board_weights)
    alight = resolve_weights(alight_ids, inputs.alight_weights)
    pins, dropped = drop_stale_pins(inputs.pins_pct, outbound_pairs)
    shares = od_shares(outbound_pairs, board, alight, pins)

    return_pairs = sellable_pairs(pair.return_trip)
    return_shares = _mirror_shares(shares, return_pairs)

    out_rows, out_loads = _write_od_pairs(
        pair.outbound.trip_id,
        outbound_pairs,
        shares,
        allocation,
        operating_days,
        fare_per_km_by_class,
        fare_per_pax_by_class,
    )
    ret_rows, ret_loads = _write_od_pairs(
        pair.return_trip.trip_id,
        return_pairs,
        return_shares,
        allocation,
        operating_days,
        fare_per_km_by_class,
        fare_per_pax_by_class,
    )
    # TripPair is not frozen — plain reassignment replaces whatever the
    # pair carried, exactly as the stopgap did.
    pair.od_pairs = out_rows + ret_rows

    return PairDemand(
        composition_id=pair.composition.comp_id,
        allocation=allocation,
        pairs=outbound_pairs,
        shares=shares,
        boarding_stop_ids=board_ids,
        alighting_stop_ids=alight_ids,
        board_weights=board,
        alight_weights=alight,
        pins_pct=pins,
        dropped_pins=dropped,
        average_distance_km=average_distance_km(outbound_pairs, shares),
        # Sources over both trips: the split follows each pair's own length.
        sources=split_sources(out_loads + ret_loads),
    )


def distribute_demand(
    route: Route,
    inputs: DemandInputs,
    fare_per_km_by_class: dict[str, float],
    fare_per_pax_by_class: dict[str, float],
) -> DemandResult:
    """Run the manual demand model on a planned route. Replaces every trip
    pair's od_pairs (TripPair is not frozen) and returns what the API
    serialises. Every departure of the route carries the same demand:
    per trip = passengers per year ÷ (operating days × 2 × trip pairs)."""
    operating_days = route.schedule.operating_days_per_year
    departures = operating_days * 2 * len(route.trip_pairs)
    per_trip_total = inputs.passengers_per_year / departures if departures else 0.0
    per_trip_by_group = split_by_group(per_trip_total, inputs.group_shares_pct)

    pairs = [
        _pair_demand(
            pair,
            inputs,
            per_trip_by_group,
            operating_days,
            fare_per_km_by_class,
            fare_per_pax_by_class,
        )
        for pair in route.trip_pairs
    ]
    return DemandResult(
        passengers_per_year=inputs.passengers_per_year,
        departures_per_year=departures,
        operating_days_per_year=operating_days,
        trip_pairs=pairs,
    )
