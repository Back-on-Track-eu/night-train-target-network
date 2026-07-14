"""
trip.py
=======
Trip domain objects — physics only. No monetary values, no provenance,
no composition (shared at TripPair level), no serialisation.

Units: metres (_m), minutes (_min), kWh (_kwh).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class StopType(Enum):
    BOARDING = "boarding"
    ALIGHTING = "alighting"
    NIGHT = "night"  # within [NIGHT_START_MIN, NIGHT_END_MIN) — see version.py
    BOTH = "both"


@dataclass
class Stop:
    """
    One stop on a trip. Clock times in minutes from midnight day 1.
    Terminal stops: origin has arrival_time_min=None, destination has
    departure_time_min=None.

    dwell_time_min is derived (departure - arrival) — None at terminals.

    auto_added: True if this stop was not in the caller's original stops
    list and was inserted by auto_stop_addition (see models/route/timetable.py) —
    lets the frontend render it differently from a stop the caller chose
    directly. Always False when auto_stop_addition was disabled or found
    nothing worth adding.
    """

    stop_id: str
    stop_name: str
    country_code: str  # ISO 3166-1 alpha-2
    lat: float
    lon: float
    stop_type: StopType
    arrival_time_min: Optional[int]
    departure_time_min: Optional[int]
    auto_added: bool = False

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

    slack_time_min is deliberate schedule padding beyond routing physics —
    0 everywhere except on legs inside a stretched fixed-night interval
    (timetable_mode="simpleAutomaticWithFixedNight", see
    models/route/timetable.py). Declared last (dataclass default), listed
    with the other time components in spirit: total = driving + dynamics
    + buffer + slack.
    """

    from_stop: Stop
    to_stop: Stop
    geometry: list[list[float]]  # [[lon, lat], ...]
    distance_m: int
    driving_time_min: int  # raw router time (constant-cruise-speed passage)
    dynamics_time_min: int  # per-stop accel/brake loss — see routing/dynamics.py
    buffer_time_min: int  # schedule buffer: country quota on driving + on dynamics
    energy_kwh: float
    country_distance_shares: dict[str, float]
    country_time_shares: dict[str, float]
    slack_time_min: int = 0  # fixed-night stretch padding — see class docstring

    @property
    def total_time_min(self) -> int:
        return (
            self.driving_time_min
            + self.dynamics_time_min
            + self.buffer_time_min
            + self.slack_time_min
        )


@dataclass(frozen=True)
class TimetableWarning:
    """One derived quality warning about a trip's timetable — informational
    only, never blocks the route. Produced by timetable-mode-specific checks
    in models/route/timetable.py (currently only fixed_night_speed_warning),
    serialized into the trip's general_parameters.timetable_warnings by
    api/helpers/route_serialize.py.

    ratio = timetable_speed_kmh / routing_speed_kmh over the interval —
    below FIXED_NIGHT_MIN_SPEED_RATIO (models/route/version.py) for code
    "fixed_night_stretch_slow"."""

    code: str
    interval: tuple[str, str]  # (start stop_id, end stop_id)
    timetable_speed_kmh: float
    routing_speed_kmh: float
    ratio: float


@dataclass
class Trip:
    """
    One directional run of a TripPair.

    trip_id   — format: P{proposal_id}_V{version}_R1_D{direction}_T{index}
    direction — 0 = outbound, 1 = return

    Constructed exclusively via Trip._create() in route_factory.
    Invariant: segments[i].to_stop.stop_id == segments[i+1].from_stop.stop_id

    timetable_warnings: derived timetable-quality annotations (see
    TimetableWarning) — [] for every mode/route that raised none.
    """

    trip_id: str
    direction: int
    segments: list[Segment]
    timetable_warnings: list[TimetableWarning] = field(default_factory=list)

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
    def dynamics_time_min(self) -> int:
        return sum(s.dynamics_time_min for s in self.segments)

    @property
    def buffer_time_min(self) -> int:
        return sum(s.buffer_time_min for s in self.segments)

    @property
    def total_driving_and_buffer_min(self) -> int:
        """driving + dynamics + buffer — every physics-derived in-motion and
        margin minute (kept under its historical name; the dynamics component
        was split out of driving in route builder 0.9.8). Deliberately
        excludes fixed-night slack (deliberate stretch padding, not physics)
        and dwell — total_time_min adds both on top."""
        return self.driving_time_min + self.dynamics_time_min + self.buffer_time_min

    @property
    def total_dwell_min(self) -> int:
        return sum(
            s.from_stop.dwell_time_min
            for s in self.segments[1:]
            if s.from_stop.dwell_time_min is not None
        )

    @property
    def slack_time_min(self) -> int:
        return sum(s.slack_time_min for s in self.segments)

    @property
    def total_time_min(self) -> int:
        return (
            self.total_driving_and_buffer_min
            + self.slack_time_min
            + self.total_dwell_min
        )

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
    def _create(
        cls,
        trip_id: str,
        direction: int,
        segments: list[Segment],
        timetable_warnings: list[TimetableWarning] | None = None,
    ) -> "Trip":
        """Sole constructor — called exclusively by route_factory."""
        return cls(
            trip_id=trip_id,
            direction=direction,
            segments=segments,
            timetable_warnings=timetable_warnings or [],
        )