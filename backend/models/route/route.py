"""
route.py
========
Route, TripPair, Parking, and Schedule domain objects.

A TripPair is one outbound + return cycle, sharing a composition and a
schedule. Most routes have one pair; Y-shaped routes have several, each
independently scheduled and composed.

Schedule: SUMMER (April–Sep) and WINTER (Oct–Mar), each 26 weeks, fixed.
Frequency is DAILY or THREE_PER_WEEK — specific days of week aren't
modelled, they don't affect cost or fleet sizing.

Coach fleet sizing (TripPair.coaches_required): a night train composition
takes two operating days to complete one out-and-back cycle (depart
evening, arrive next morning, layover, return the following evening).
DAILY service needs 2 coach sets; THREE_PER_WEEK needs 1, since the gap
between operating days is enough for one set to complete its cycle. Peak
season governs.

Locomotives are not fleet-sized here — they're utilization-based
full-service leased and billed per segment in calc.py
(composition.loco_full_service_lease_eur_h × segment.total_time_min),
since lease cost scales directly with usage regardless of rotation.

Operator invariant: all TripPairs in a Route must share the same operator_id.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from models.params import ODPair, Composition
from models.route.trip import Trip

WEEKS_PER_SEASON = 26
DAYS_PER_OPERATING_WEEK = {"DAILY": 7, "THREE_PER_WEEK": 3}

# =============================================================================
# SCHEDULE
# =============================================================================

class Season(Enum):
    SUMMER = "summer"
    WINTER = "winter"

class Frequency(Enum):
    DAILY = "daily"
    THREE_PER_WEEK = "three_per_week"

    @property
    def days_per_week(self) -> int:
        return DAYS_PER_OPERATING_WEEK[self.name]

@dataclass
class SeasonalSchedule:
    """Operating frequency for one season."""
    season: Season
    frequency: Frequency

@dataclass
class Schedule:
    """Full-year schedule. A season with no entry is treated as not operating."""

    seasonal_schedules: list[SeasonalSchedule]

    def get(self, season: Season) -> SeasonalSchedule | None:
        return next((s for s in self.seasonal_schedules if s.season == season), None)

    @property
    def is_daily_any_season(self) -> bool:
        return any(s.frequency == Frequency.DAILY for s in self.seasonal_schedules)

    @property
    def operating_days_per_year(self) -> int:
        return sum(s.frequency.days_per_week * WEEKS_PER_SEASON for s in self.seasonal_schedules)

# =============================================================================
# PARKING
# =============================================================================

@dataclass
class Shunting:
    """One shunting event at a trip terminal. One per trip end/start,
    so a round trip produces 4 shuntings (2 per trip, no deduplication).
    trip_id identifies which trip this shunting belongs to."""
    stop_id: str
    stop_name: str
    country_code: str
    trip_id: str

@dataclass
class Parking:
    """One overnight parking location — deduplicated by stop_id.
    trip_ids lists all trips whose formation parks here (typically
    both outbound and return of a trip pair)."""
    stop_id: str
    stop_name: str
    country_code: str
    trip_ids: list[str]

# =============================================================================
# TRIP PAIR
# =============================================================================

@dataclass
class TripPair:
    """
    One outbound + return cycle, sharing one composition.
    Schedule lives on Route — all pairs in a route share one schedule.

    od_pairs: demand for this trip pair — list of ODPair objects, one per
    valid origin→destination×class combination. Lives here (not on Route)
    because demand is bounded by this pair's composition capacity: you
    cannot sell more places than the composition provides for that class.
    Populated either by user input or by distribute_demand() in
    route_factory.py.

    composition_count: {comp_id: coaches_required} — a single entry,
    since a TripPair uses exactly one composition. Keyed by comp_id
    (not the Composition object itself, which isn't hashable — it has
    dict fields).

    coaches_required is a float, not an integer count of physical coach
    sets to buy for this route alone. Availability buffer (coach_avail_per)
    is pooled across an operator's whole network, not dedicated per route
    — so this route's fair cost share is schedule_min / coach_avail_per,
    e.g. 2 sets needed in rotation at 80% availability = 2.5. Rounding up
    per route would overestimate cost by assuming a dedicated spare.
    """

    outbound: Trip
    return_trip: Trip
    composition: Composition
    od_pairs: list[ODPair]

    @property
    def trips(self) -> list[Trip]:
        return [self.outbound, self.return_trip]

    def composition_count(self, schedule: Schedule) -> dict[str, float]:
        schedule_min = 2 if schedule.is_daily_any_season else 1
        n = schedule_min / self.composition.coach_avail_per
        return {self.composition.comp_id: n}

    @property
    def countries(self) -> set[str]:
        """All countries this pair's two trips pass through — from segment
        distance shares and stop country codes. Unlike Route.countries,
        there's no parking locations here — parkings are a Route-level
        concept (a formation may park at a stop neither trip in this pair
        actually visits), not something a single TripPair owns."""
        result: set[str] = set()
        for trip in self.trips:
            for segment in trip.segments:
                result.update(segment.country_distance_shares.keys())
            for stop in trip.stops:
                if stop.country_code:
                    result.add(stop.country_code)
        return result

    @property
    def loco_propulsion_min(self) -> int:
        """Loco operating time for this pair's two trips, in minutes.
        Sums driving + buffer + dwell across all segments and stops of
        both trips. No cross-pair deduplication — each pair's loco time
        is independent.

        # TODO (Y/X-shape): if two pairs share a trunk segment with one
        # physical loco, this will double-count that loco's time. Needs
        # a route-level deduplication pass once X/Y-shape routes are live."""
        total_min = 0
        for trip in self.trips:
            for segment in trip.segments:
                total_min += segment.total_time_min
            for stop in trip.stops:
                if stop.dwell_time_min is not None:
                    total_min += stop.dwell_time_min
        return total_min

    @property
    def shunting_count(self) -> int:
        """2 per trip (one at each terminal). Placeholder — see Route.shuntings.
        TODO (Y/X-shape): shared terminals may need fewer events."""
        return len(self.trips) * 2

# =============================================================================
# ROUTE
# =============================================================================

class Route:
    """
    A night train service — container for trip pairs, parking, and schedule.
    All trip pairs share one schedule. Demand (ODPairs) lives on each
    TripPair, since demand is bounded by that pair's composition capacity.
    Constructed exclusively via Route._create() in route_factory.
    """

    def __init__(
        self,
        route_id: str,
        schedule: Schedule,
        trip_pairs: list[TripPair],
        parkings: list[Parking],
        shuntings: list[Shunting],
    ) -> None:
        self._route_id = route_id
        self._schedule = schedule
        self._trip_pairs: list[TripPair] = []
        self._parkings = parkings
        self._shuntings = shuntings
        for pair in trip_pairs:
            self._add_trip_pair(pair)

    @property
    def route_id(self) -> str:
        return self._route_id

    @property
    def schedule(self) -> Schedule:
        return self._schedule

    @property
    def trip_pairs(self) -> list[TripPair]:
        return list(self._trip_pairs)

    @property
    def trips(self) -> list[Trip]:
        """Flattened trips across all trip pairs."""
        return [t for pair in self._trip_pairs for t in pair.trips]

    @property
    def od_pairs(self) -> list[ODPair]:
        """All OD pairs flattened across all trip pairs."""
        return [od for pair in self._trip_pairs for od in pair.od_pairs]

    @property
    def parkings(self) -> list[Parking]:
        return list(self._parkings)

    @property
    def shuntings(self) -> list[Shunting]:
        return list(self._shuntings)

    @property
    def operator_id(self) -> str | None:
        return self._trip_pairs[0].composition.operator_id if self._trip_pairs else None

    @property
    def composition_counts(self) -> dict[str, float]:
        """coaches_required per comp_id, summed across all TripPairs,
        using the route's shared schedule."""
        totals: dict[str, float] = {}
        for pair in self._trip_pairs:
            for comp_id, n in pair.composition_count(self._schedule).items():
                totals[comp_id] = totals.get(comp_id, 0.0) + n
        return totals

    def get_trip(self, trip_id: str) -> Trip | None:
        return next((t for t in self.trips if t.trip_id == trip_id), None)

    def get_trip_pair(self, trip_id: str) -> TripPair | None:
        """Find the TripPair containing the given trip_id (either direction)."""
        return next(
            (p for p in self._trip_pairs if trip_id in (p.outbound.trip_id, p.return_trip.trip_id)),
            None,
        )

    def _add_trip_pair(self, pair: TripPair) -> None:
        if self._trip_pairs and pair.composition.operator_id != self.operator_id:
            raise ValueError(
                f"TripPair '{pair.outbound.trip_id}' operator "
                f"'{pair.composition.operator_id}' != route operator '{self.operator_id}'."
            )
        self._trip_pairs.append(pair)

    @property
    def countries(self) -> set[str]:
        """All countries this route passes through — from segment distance
        shares, stop country codes, and parking locations."""
        result: set[str] = set()
        for trip in self.trips:
            for segment in trip.segments:
                result.update(segment.country_distance_shares.keys())
            for stop in trip.stops:
                if stop.country_code:
                    result.add(stop.country_code)
        for pl in self._parkings:
            result.add(pl.country_code)
        return result

    @property
    def loco_propulsion_min(self) -> int:
        """
        Total loco operating time across the route, in minutes: driving +
        buffer time on every distinct segment, plus dwell time at every
        distinct intermediate stop. The loco stays coupled while passengers
        board/alight, so dwell time counts as operating time too.

        Deduplicated: a segment is identified by (from_stop_id, to_stop_id),
        a stop by stop_id. On a Y-shaped route, a shared trunk segment or
        stop appears once per TripPair that uses it — but physically it's
        the same track and the same loco, so it must only be counted once.
        Without deduplication, a shared segment would be billed twice for
        one loco's actual usage.

        Physics only — no cost, minutes not hours. calc.py converts to
        hours and multiplies by composition.loco_full_service_lease_eur_h
        for route-level lease cost.
        """
        seen_segments: set[tuple[str, str]] = set()
        seen_stops: set[str] = set()
        total_min = 0

        for pair in self._trip_pairs:
            for trip in pair.trips:
                for segment in trip.segments:
                    key = (segment.from_stop.stop_id, segment.to_stop.stop_id)
                    if key in seen_segments:
                        continue
                    seen_segments.add(key)
                    total_min += segment.total_time_min

                for stop in trip.stops:
                    if stop.dwell_time_min is None:
                        continue
                    if stop.stop_id in seen_stops:
                        continue
                    seen_stops.add(stop.stop_id)
                    total_min += stop.dwell_time_min

        return total_min

    @property
    def shunting_count(self) -> int:
        """Total shunting movements — one per Shunting."""
        return len(self._shuntings)

    @classmethod
    def _create(
        cls,
        route_id: str,
        schedule: Schedule,
        trip_pairs: list[TripPair],
        parkings: list[Parking],
        shuntings: list[Shunting],
    ) -> "Route":
        """Sole constructor — called exclusively by route_factory."""
        return cls(
            route_id=route_id,
            schedule=schedule,
            trip_pairs=trip_pairs,
            parkings=parkings,
            shuntings=shuntings,
        )