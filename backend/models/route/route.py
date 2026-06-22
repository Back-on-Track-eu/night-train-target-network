"""
route.py
========
Mutable container for a named night train service — mirrors GTFS routes.txt.

A Route holds one or more Trip objects (exactly two for now: outbound +
return), stored as dict[str, Trip] keyed by trip_id for O(1) lookup.

Monetary values
---------------
Route carries NO monetary values. parking_locations lists the endpoint
stops where parking costs apply — the cost model looks up parking_eur_day
per country from infra params and sums them.

route_id    — UUID assigned by route_factory.
operator_id — links to input_params.operators; plain string for now.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from models.route.trip import Trip


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
    stop_id:      str
    stop_name:    str
    country_code: str   # ISO 3166-1 alpha-2

    def to_dict(self) -> dict:
        return {
            "stop_id":      self.stop_id,
            "stop_name":    self.stop_name,
            "country_code": self.country_code,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ParkingLocation":
        return cls(
            stop_id      = d["stop_id"],
            stop_name    = d["stop_name"],
            country_code = d["country_code"],
        )


# =============================================================================
# ROUTE
# =============================================================================

class Route:
    """
    A named night train service — mirrors GTFS routes.txt.

    trips: dict[str, Trip] keyed by trip_id.
    parking_locations: endpoint stops where parking costs apply.
    Serialised as lists in to_dict() / from_dict().
    """

    def __init__(
        self,
        route_id:          str,
        operator_id:       str,
        parking_locations: list[ParkingLocation],
        trips:             dict[str, Trip],
    ) -> None:
        self._route_id          = route_id
        self._operator_id       = operator_id
        self._parking_locations = parking_locations
        self._trips:            dict[str, Trip] = trips

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @property
    def route_id(self) -> str:
        return self._route_id

    @property
    def operator_id(self) -> str:
        return self._operator_id

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
    # Setters — caller responsible for re-evaluation after changes
    # ------------------------------------------------------------------

    def set_operator_id(self, operator_id: str) -> None:
        self._operator_id = operator_id

    def set_parking_locations(self, parking_locations: list[ParkingLocation]) -> None:
        self._parking_locations = parking_locations

    # ------------------------------------------------------------------
    # Trip mutators — build Trip via route_factory before calling these
    # ------------------------------------------------------------------

    def add_trip(self, trip: Trip) -> None:
        """Add a new Trip. Raises ValueError if trip_id already exists."""
        if trip.trip_id in self._trips:
            raise ValueError(
                f"Route '{self._route_id}': trip_id '{trip.trip_id}' already exists. "
                f"Use update_trip() to replace an existing trip."
            )
        self._trips[trip.trip_id] = trip

    def update_trip(self, trip: Trip) -> None:
        """Replace an existing Trip. Raises ValueError if not found."""
        if trip.trip_id not in self._trips:
            raise ValueError(
                f"Route '{self._route_id}': trip_id '{trip.trip_id}' not found. "
                f"Use add_trip() to add a new trip."
            )
        self._trips[trip.trip_id] = trip

    def remove_trip(self, trip_id: str) -> None:
        """Remove a Trip by trip_id. Raises ValueError if not found."""
        if trip_id not in self._trips:
            raise ValueError(
                f"Route '{self._route_id}': trip_id '{trip_id}' not found."
            )
        del self._trips[trip_id]

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "route_id":          self._route_id,
            "operator_id":       self._operator_id,
            "parking_locations": [p.to_dict() for p in self._parking_locations],
            "trips":             [t.to_dict() for t in self._trips.values()],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Route":
        trips = {t["trip_id"]: Trip.from_dict(t) for t in d["trips"]}
        return cls(
            route_id          = d["route_id"],
            operator_id       = d["operator_id"],
            parking_locations = [ParkingLocation.from_dict(p)
                                  for p in d.get("parking_locations", [])],
            trips             = trips,
        )