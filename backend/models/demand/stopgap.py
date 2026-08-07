"""
stopgap.py
==========
Stopgap demand model — the uniform-distribution proxy that populates a
Route's OD pairs until the real demand model exists (see
OPEN_TODOS["demand_model"] in version.py). Moved here from
models/route/route_factory.py so all demand-related code lives under
models/demand/ ahead of the real model landing in the same package.

Public interface:
  distribute_demand(route, utilization_per, fare_per_km_by_class) -> Route
"""

from __future__ import annotations

from models.params import ODPair
from models.route.route import Route
from models.route.trip import StopType


def distribute_demand(
    route: Route,
    utilization_per: float,
    fare_per_km_by_class: dict[str, float],
) -> Route:
    """
    Proxy demand model: distributes uniform demand across all valid OD pairs
    for each trip pair, based on a target utilization and per-km fare.

    This is a placeholder until a proper demand model is built
    (OPEN_TODOS["demand_model"] in version.py). Assumptions:
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

            # Find valid (origin_idx, destination_idx) pairs. NIGHT stops
            # are deliberately on neither side — demand-quiet by definition
            # (the whole point of the classification); they still dwell and
            # cost like BOTH, they just sell no places in this stopgap.
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
