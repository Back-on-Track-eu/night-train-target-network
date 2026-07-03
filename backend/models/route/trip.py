"""
trip.py
=======
Trip domain objects — physics only. No monetary values, no provenance,
no composition (shared at TripPair level), no serialisation.

Units: metres (_m), minutes (_min), kWh (_kwh).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

class StopType(Enum):
    BOARDING  = "boarding"
    ALIGHTING = "alighting"
    BOTH      = "both"

@dataclass
class Stop:
    """
    One stop on a trip. Clock times in minutes from midnight day 1.
    Terminal stops: origin has arrival_time_min=None, destination has
    departure_time_min=None.

    dwell_time_min is derived (departure - arrival) — None at terminals.
    """

    stop_id: str
    stop_name: str
    country_code: str           # ISO 3166-1 alpha-2
    lat: float
    lon: float
    stop_type: StopType
    arrival_time_min: Optional[int]
    departure_time_min: Optional[int]

    @property
    def dwell_time_min(self) -> Optional[int]:
        if self.arrival_time_min is None or self.departure_time_min is None:
            return None
        return self.departure_time_min - self.arrival_time_min

@dataclass
class Segment:
    """
    One segment between two consecutive stops. Atomic unit of the model.

    country_distance_shares and country_time_shares sum to 1.0 each and
    can differ — e.g. a mountainous section may be slow relative to its
    length, giving it a larger time share than distance share.

    energy_kwh is 0.0 after routing, enriched in-place by
    calc_energy_consumption().
    """

    from_stop: Stop
    to_stop: Stop
    geometry: list[list[float]]                # [[lon, lat], ...]
    distance_m: int
    driving_time_min: int
    buffer_time_min: int
    energy_kwh: float
    country_distance_shares: dict[str, float]
    country_time_shares: dict[str, float]

    @property
    def total_time_min(self) -> int:
        return self.driving_time_min + self.buffer_time_min

@dataclass
class Trip:
    """
    One directional run of a TripPair.

    trip_id   — format: P{proposal_id}_V{version}_R1_D{direction}_T{index}
    direction — 0 = outbound, 1 = return

    Constructed exclusively via Trip._create() in route_factory.
    Invariant: segments[i].to_stop.stop_id == segments[i+1].from_stop.stop_id
    """

    trip_id: str
    direction: int
    segments: list[Segment]

    @property
    def departure_time_min(self) -> int:
        return self.segments[0].from_stop.departure_time_min

    @property
    def arrival_time_min(self) -> int:
        return self.segments[-1].to_stop.arrival_time_min

    @property
    def distance_m(self) -> int:
        return sum(s.distance_m for s in self.segments)

    @property
    def driving_time_min(self) -> int:
        return sum(s.driving_time_min for s in self.segments)

    @property
    def buffer_time_min(self) -> int:
        return sum(s.buffer_time_min for s in self.segments)

    @property
    def total_driving_and_buffer_min(self) -> int:
        return self.driving_time_min + self.buffer_time_min

    @property
    def total_dwell_min(self) -> int:
        return sum(
            s.from_stop.dwell_time_min
            for s in self.segments[1:]
            if s.from_stop.dwell_time_min is not None
        )

    @property
    def total_time_min(self) -> int:
        return self.total_driving_and_buffer_min + self.total_dwell_min

    @property
    def energy_kwh(self) -> float:
        return sum(s.energy_kwh for s in self.segments)

    @property
    def stops(self) -> list[Stop]:
        if not self.segments:
            return []
        result = [self.segments[0].from_stop]
        for seg in self.segments:
            result.append(seg.to_stop)
        return result

    @classmethod
    def _create(cls, trip_id: str, direction: int, segments: list[Segment]) -> "Trip":
        """Sole constructor — called exclusively by route_factory."""
        return cls(trip_id=trip_id, direction=direction, segments=segments)