"""
sources.py
==========
Where a night train's passengers come from, by journey length — the
attribution the climate figures need (docs/2026-09-18_manual_demand_
guide.md phase B, decided 2026-09-19).

Every passenger of an OD pair is either a shift from the plane, a shift
from the car, or an induced trip that would not have been made. The air
share follows the journey length: nobody flies under AIR_SHIFT_FLOOR_KM
(0), a quarter at exactly the floor, then linear to everybody at
AIR_SHIFT_FULL_KM. What is not air is "other", of which OTHER_CAR_SHARE
would have driven and the rest is induced. The constants live in
model.py; this module is the arithmetic, applied per pair so the split
follows the OD matrix rather than the route's length.

The CO2 saving of a passenger-km (models/evaluation/summary.py) is then
air × (plane − train) + car × (car − train) − induced × train: a shifted
passenger still emits on the train, an induced one only does.

Public interface:
  air_share(distance_km) -> float
  SourceSplit(...) and split_sources(loads) -> SourceSplit, where loads is
      an iterable of (distance_km, passengers)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from models.demand.model import (
    AIR_SHIFT_AT_FLOOR,
    AIR_SHIFT_FLOOR_KM,
    AIR_SHIFT_FULL_KM,
    OTHER_CAR_SHARE,
)


def air_share(distance_km: float) -> float:
    """Share of an OD pair's passengers who would otherwise have flown."""
    if distance_km < AIR_SHIFT_FLOOR_KM:
        return 0.0
    if distance_km >= AIR_SHIFT_FULL_KM:
        return 1.0
    f = (distance_km - AIR_SHIFT_FLOOR_KM) / (AIR_SHIFT_FULL_KM - AIR_SHIFT_FLOOR_KM)
    return AIR_SHIFT_AT_FLOOR + (1.0 - AIR_SHIFT_AT_FLOOR) * f


@dataclass(frozen=True)
class SourceSplit:
    """Passengers and passenger-km per source over a set of OD loads.
    `other` is car + induced — the figure the summary reports beside air;
    car and induced are its two halves the CO2 arithmetic needs."""

    air_trips: float
    air_trip_km: float
    car_trips: float
    car_trip_km: float
    induced_trips: float
    induced_trip_km: float

    @property
    def other_trips(self) -> float:
        return self.car_trips + self.induced_trips

    @property
    def other_trip_km(self) -> float:
        return self.car_trip_km + self.induced_trip_km


def split_sources(loads: Iterable[tuple[float, float]]) -> SourceSplit:
    """Sum the split over (distance_km, passengers) loads — one per OD
    pair and class, whatever the caller iterates."""
    air_t = air_km = car_t = car_km = ind_t = ind_km = 0.0
    for distance_km, passengers in loads:
        a = air_share(distance_km)
        other = 1.0 - a
        air_t += passengers * a
        air_km += passengers * a * distance_km
        car_t += passengers * other * OTHER_CAR_SHARE
        car_km += passengers * other * OTHER_CAR_SHARE * distance_km
        ind_t += passengers * other * (1.0 - OTHER_CAR_SHARE)
        ind_km += passengers * other * (1.0 - OTHER_CAR_SHARE) * distance_km
    return SourceSplit(air_t, air_km, car_t, car_km, ind_t, ind_km)
