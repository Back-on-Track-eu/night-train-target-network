"""
route.py
========
Mutable container for a night train service — mirrors GTFS routes.txt.

A Route holds exactly two Trip objects (outbound + return), stored as
dict[str, Trip] keyed by trip_id for O(1) lookup.

No ID on Route
--------------
Route carries no route_id — that is a persistence concern handled by
proposals.routes in the DB. The Python Route object is a computation
container; the API saves it and gets back a route_id from the DB.

No operator_id on Route
-----------------------
Operator identity is derived from Trip.composition.operator_id.
Route enforces that all trips share the same operator via add_trip()
and update_trip().

Monetary values
---------------
Route carries NO monetary values. parking_locations lists the endpoint
stops where parking costs apply — the cost model looks up parking_eur_day
per country from infra params and sums them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from models.route.trip import Trip
from models.utils import m_to_km, min_to_h

# =============================================================================
# ROUTE STATS
# =============================================================================


@dataclass
class RouteStats:
    """
    Aggregated physics stats across all trips in a Route.
    Recomputed automatically whenever a trip is added or removed.
    Physics only — no monetary values.
    """

    total_trips: int
    total_distance_m: int
    total_driving_time_min: int
    total_time_min: int
    total_energy_kwh: float

    @property
    def total_distance_km(self) -> float:
        return m_to_km(self.total_distance_m)

    @property
    def total_driving_time_h(self) -> float:
        return min_to_h(self.total_driving_time_min)

    @property
    def total_time_h(self) -> float:
        return min_to_h(self.total_time_min)

    def to_dict(self) -> dict:
        return {
            "total_trips": self.total_trips,
            "total_distance_m": self.total_distance_m,
            "total_distance_km": self.total_distance_km,
            "total_driving_time_min": self.total_driving_time_min,
            "total_driving_time_h": self.total_driving_time_h,
            "total_time_min": self.total_time_min,
            "total_time_h": self.total_time_h,
            "total_energy_kwh": self.total_energy_kwh,
        }


# =============================================================================
# PARKING LOCATION
# =============================================================================


@dataclass
class ParkingLocation:
    """
    A stop where overnight parking costs apply (origin or destination).
    The cost model multiplies infra.parking_eur_day by the number of
    unique parking locations.
    """

    stop_id: str
    stop_name: str
    country_code: str  # ISO 3166-1 alpha-2

    def to_dict(self) -> dict:
        return {
            "stop_id": self.stop_id,
            "stop_name": self.stop_name,
            "country_code": self.country_code,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ParkingLocation":
        return cls(
            stop_id=d["stop_id"],
            stop_name=d["stop_name"],
            country_code=d["country_code"],
        )


# =============================================================================
# ROUTE
# =============================================================================


class Route:
    """
    A night train service — mirrors GTFS routes.txt.

    Constructed exclusively via Route._create() — never instantiate directly.
    _create() is called only from route_factory.build_route().

    trips:             dict[str, Trip] keyed by trip_id.
    parking_locations: endpoint stops where parking costs apply.

    Invariant: all trips must share the same operator_id
               (enforced in add_trip() and update_trip()).
    """

    def __init__(
        self,
        route_id: str,
        parking_locations: list[ParkingLocation],
        trips: dict[str, Trip],
    ) -> None:
        self._route_id = route_id
        self._parking_locations = parking_locations
        self._trips: dict[str, Trip] = {}
        self._stats: RouteStats = RouteStats(0, 0, 0, 0, 0.0)
        # add trips via add_trip() to enforce operator consistency
        for trip in trips.values():
            self.add_trip(trip)

    def _recompute_stats(self) -> None:
        """Recompute RouteStats from all current trips. Called on add/remove."""
        trips = list(self._trips.values())
        self._stats = RouteStats(
            total_trips=len(trips),
            total_distance_m=sum(t.stats.total_distance_m for t in trips),
            total_driving_time_min=sum(t.stats.total_driving_time_min for t in trips),
            total_time_min=sum(t.stats.total_time_min for t in trips),
            total_energy_kwh=sum(t.stats.total_energy_kwh for t in trips),
        )

    @property
    def stats(self) -> RouteStats:
        return self._stats

    @classmethod
    def _create(
        cls,
        route_id: str,
        parking_locations: list["ParkingLocation"],
        trips: dict[str, "Trip"] | None = None,
    ) -> "Route":
        """
        Sole constructor for Route — called exclusively by route_factory.
        Never instantiate Route directly.
        """
        return cls(
            route_id=route_id,
            parking_locations=parking_locations,
            trips=trips or {},
        )

    # ------------------------------------------------------------------
    # Derived properties
    # ------------------------------------------------------------------

    @property
    def route_id(self) -> str:
        return self._route_id

    @property
    def operator_id(self) -> Optional[str]:
        """Operator derived from trips — None if no trips yet."""
        trip = next(iter(self._trips.values()), None)
        return trip.composition.operator_id if trip else None

    @property
    def parking_locations(self) -> list[ParkingLocation]:
        return list(self._parking_locations)

    # ------------------------------------------------------------------
    # Trip getters
    # ------------------------------------------------------------------

    def all_trips(self) -> list[Trip]:
        """Return all trips in insertion order."""
        return list(self._trips.values())

    def get_trip(self, trip_id: str) -> Optional[Trip]:
        """Return the Trip for a given trip_id, or None if not found."""
        return self._trips.get(trip_id)

    def get_trip_by_direction(self, direction: int) -> Optional[Trip]:
        """Return the Trip for a given direction (0/1), or None."""
        for trip in self._trips.values():
            if trip.direction == direction:
                return trip
        return None

    # ------------------------------------------------------------------
    # Setters
    # ------------------------------------------------------------------

    def set_parking_locations(self, parking_locations: list[ParkingLocation]) -> None:
        self._parking_locations = parking_locations

    # ------------------------------------------------------------------
    # Trip mutators — build Trip via route_factory before calling these
    # ------------------------------------------------------------------

    def _check_operator(self, trip: Trip) -> None:
        """Raise if trip's operator differs from the route's existing operator."""
        if self._trips and trip.composition.operator_id != self.operator_id:
            raise ValueError(
                f"Trip '{trip.trip_id}' has operator '{trip.composition.operator_id}' "
                f"but route already has operator '{self.operator_id}'. "
                f"A Route may only contain trips from the same operator."
            )

    def add_trip(self, trip: Trip) -> None:
        """Add a new Trip. Raises ValueError if trip_id already exists,
        if the operator differs from existing trips, or if the direction
        already has 99 trips."""
        if trip.trip_id in self._trips:
            raise ValueError(
                f"Trip '{trip.trip_id}' already exists in this route. "
                f"Use update_trip() to replace an existing trip."
            )
        direction_count = sum(
            1 for t in self._trips.values() if t.direction == trip.direction
        )
        if direction_count >= 99:
            raise ValueError(
                f"Route already has 99 trips for direction {trip.direction}. "
                f"Maximum 99 trips per direction."
            )
        self._check_operator(trip)
        self._trips[trip.trip_id] = trip
        self._recompute_stats()

    def update_trip(self, trip: Trip) -> None:
        """Replace an existing Trip. Raises ValueError if not found
        or if the operator differs from existing trips."""
        if trip.trip_id not in self._trips:
            raise ValueError(
                f"Trip '{trip.trip_id}' not found in this route. "
                f"Use add_trip() to add a new trip."
            )
        self._check_operator(trip)
        self._trips[trip.trip_id] = trip
        self._recompute_stats()

    def remove_trip(self, trip_id: str) -> None:
        """Remove a Trip by trip_id. Raises ValueError if not found."""
        if trip_id not in self._trips:
            raise ValueError(f"Trip '{trip_id}' not found in this route.")
        del self._trips[trip_id]
        self._recompute_stats()

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "route_id": self._route_id,
            "parking_locations": [p.to_dict() for p in self._parking_locations],
            "trips": [t.to_dict() for t in self._trips.values()],
            "stats": self._stats.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Route":
        trips = {t["trip_id"]: Trip.from_dict(t) for t in d["trips"]}
        return cls(
            route_id=d["route_id"],
            parking_locations=[
                ParkingLocation.from_dict(p) for p in d.get("parking_locations", [])
            ],
            trips=trips,
        )
