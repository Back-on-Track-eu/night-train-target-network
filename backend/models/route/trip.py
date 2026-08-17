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
from typing import NamedTuple, Optional


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


class CountryWindow(NamedTuple):
    """One country run of one segment, placed on the clock.

    enter_min/exit_min are minutes from midnight day 1, like every other
    clock value in the model; distance_share is that country's share of the
    segment length. Produced by Segment.country_windows() and consumed by
    every charge that depends on WHEN a train is in a country — the track
    access night and peak bands (infrastructure/tac/calc_tac.py) and the
    electricity night band (infrastructure/energy_pricing/
    calc_energy_price.py). A NamedTuple so the two can unpack it positionally
    or read it by name, and so neither owns the other's helper.
    """

    country_code: str
    enter_min: float
    exit_min: float
    distance_share: float


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

    countries is the same set as country_distance_shares' keys but IN PATH
    ORDER, which a dict of shares cannot express. Track access charges need
    it: a night rate applies to the clock time a run spends in one country,
    and placing each country on the clock requires knowing which was
    entered first.

    passages lists the separately charged crossings (Storebælt, Øresund,
    Channel Tunnel) this segment owns, matched by polygon intersection at
    routing time (routing/rail_router.py: PassageIndex). A crossing is
    attributed to exactly one segment per trip, so one split by an
    intermediate stop is not charged twice.

    Both default to empty so a route payload stored before ROUTE_BUILDER
    0.9.21 stays constructible — see api/helpers/route_serialize.py.
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
    countries: list[str] = field(default_factory=list)
    passages: list[str] = field(default_factory=list)

    @property
    def total_time_min(self) -> int:
        return (
            self.driving_time_min
            + self.dynamics_time_min
            + self.buffer_time_min
            + self.slack_time_min
        )

    def country_windows(self) -> list[CountryWindow]:
        """Place each country run of this segment on the clock, in path order.

        Each country's time share positions it between the from_stop
        departure and the to_stop arrival; its distance share gives it a
        length. "UNK" slices (open water, ferries, geometry outside every
        polygon) still advance the time cursor so they do not shift later
        countries' windows, and are yielded like any other — a caller with no
        infrastructure manager to pay skips them.

        Physics only, like everything else here: which tariff band a window
        falls into is the charge modules' business.
        """
        t0 = self.from_stop.departure_time_min
        t1 = self.to_stop.arrival_time_min
        duration = float((t1 or 0) - (t0 or 0)) if t0 is not None else 0.0

        # Payloads stored before ROUTE_BUILDER 0.9.21 carry no ordered path
        # list — fall back to the share dict's keys, which loses ordering
        # precision (and so places the windows only approximately) but keeps
        # a stale route evaluable.
        countries = self.countries or list(self.country_distance_shares.keys())

        windows: list[CountryWindow] = []
        cursor = float(t0 or 0)
        for cc in countries:
            enter = cursor
            cursor += duration * self.country_time_shares.get(cc, 0.0)
            windows.append(
                CountryWindow(
                    cc, enter, cursor, self.country_distance_shares.get(cc, 0.0)
                )
            )
        return windows


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
