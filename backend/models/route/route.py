"""
route.py
========
Route, TripPair, Parking, and Schedule domain objects.

A TripPair is one outbound + return cycle, sharing a composition and a
schedule. Most routes have one pair; Y-shaped routes have several, each
independently scheduled and composed.

Schedule: days per week for each of the twelve months (0 = not running)
plus a minimum terminal turnaround. Specific days of week aren't
modelled, they don't affect cost or fleet sizing.

Coach fleet sizing (TripPair.trainsets): a night train composition takes
two operating days to complete one out-and-back cycle (depart evening,
arrive next morning, layover, return the following evening). A daily
service needs 2 coach sets; three days a week needs 1, since the gap
between operating days is enough for one set to complete its cycle. The
busiest month governs. Since ROUTE_BUILDER 0.9.40 the request usually
posts one frequency, which the API boundary expands to the same number in
every month — the grid stays so a seasonal plan can return without a
domain change.

Locomotives are not fleet-sized here — they're utilization-based
full-service leased and billed per segment in calc.py
(composition.loco_lease_total_eur_h × segment.total_time_min),
since lease cost scales directly with usage regardless of rotation.

Operator invariant: all TripPairs in a Route must share the same operator_id.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass

from models.params import ODPair, Composition
from models.route.trip import Trip

# Standard schedule assumptions live in the route model's central registry —
# see models/route/model.py (STANDARD VALUES).
from models.route.model import DEFAULT_MIN_TURNAROUND_MIN, EVALUATION_YEAR

# =============================================================================
# FLEET — the cycle-time rule, as pure functions
# =============================================================================
# Module-level so models/evaluation/summary.py can size a fleet from a route
# DICT (it never sees a TripPair) with the exact arithmetic TripPair uses.


def cycle_days_between(
    out_dep: int, out_arr: int, ret_dep: int, ret_arr: int, min_turnaround_min: int
) -> int:
    """Calendar days one rake needs from a departure at the origin until it
    is back there in time for a scheduled departure.

    Walk the rake through the timetable: arrive at the far terminal, wait at
    least min_turnaround_min, take the first return slot that fits —
    tomorrow's if today's is too close — and the same again at the origin.
    Every turnaround that misses the minimum costs a day, which is why a
    service whose return leaves too soon after the outbound arrives needs an
    extra rake.

    Times are minutes from the origin departure's midnight, so a next-day
    arrival is simply > 1440; clocks are taken mod a day.
    """
    day = 24 * 60

    def next_slot(ready_min: int, slot_clock: int) -> int:
        """First absolute minute >= ready_min at which the clock reads
        slot_clock."""
        k = max(0, -(-(ready_min - slot_clock) // day))
        return k * day + slot_clock

    ready_at_far = out_arr + min_turnaround_min
    ret_leaves = next_slot(ready_at_far, ret_dep % day)
    ret_arrives = ret_leaves + (ret_arr - ret_dep)
    ready_at_origin = ret_arrives + min_turnaround_min
    next_out = next_slot(ready_at_origin, out_dep % day)
    return max(1, (next_out - out_dep) // day)


def trainsets_for_cycle(cycle_days: int, schedule: "Schedule") -> int:
    """Physical rakes for a service with this cycle: sized to the busiest
    month, departure days assumed evenly spread through the week (stated in
    models/route/model.py OPEN_TODOS)."""
    return max(
        -(-(cycle_days * d) // 7) for d in schedule.days_per_week_by_month.values()
    )


# =============================================================================
# SCHEDULE
# =============================================================================


@dataclass
class Schedule:
    """Full-year operating plan: how many days a week the train runs in
    each month, and the shortest turnaround a rake is given at a terminal.

    days_per_week_by_month: {1..12: 0..7}; 0 means the train does not run
    that month. Which weekdays is not modelled — the operating days of a
    month are days_in_month × d/7, and everything downstream that counts
    departures assumes the days are spread evenly through the week.

    min_turnaround_min: the minimum a rake stands between arriving at a
    terminal and leaving it again, which is what decides whether one rake
    can serve consecutive departures or a second one is needed — see
    TripPair.cycle_days(). A HOW field on the request, default 180.
    """

    days_per_week_by_month: dict[int, int]
    min_turnaround_min: int = DEFAULT_MIN_TURNAROUND_MIN

    def __post_init__(self) -> None:
        self.days_per_week_by_month = {
            int(m): int(d) for m, d in self.days_per_week_by_month.items()
        }
        missing = set(range(1, 13)) - set(self.days_per_week_by_month)
        if missing:
            raise ValueError(f"Schedule is missing months {sorted(missing)}")

    def days_per_week(self, month: int) -> int:
        return self.days_per_week_by_month[month]

    def operating_days(self, month: int) -> float:
        days_in_month = calendar.monthrange(EVALUATION_YEAR, month)[1]
        return days_in_month * self.days_per_week(month) / 7

    @property
    def operating_days_per_year(self) -> float:
        return sum(self.operating_days(m) for m in range(1, 13))

    @property
    def peak_days_per_week(self) -> int:
        return max(self.days_per_week_by_month.values())

    @property
    def is_operating(self) -> bool:
        return self.peak_days_per_week > 0

    @property
    def is_daily_any_season(self) -> bool:
        """Kept for readers that only ask "is this a daily service": true
        when any month runs seven days a week."""
        return self.peak_days_per_week >= 7


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
    both outbound and return of a trip pair).

    hours is the scheduled layover: the gap between the arrival that ends one
    trip here and the departure that starts the next. Physics, like every
    other field on these objects — what it costs is
    models/infrastructure/facility/calc_facility.py's business, and it needs
    the duration because Europe prices stabling by started hour, by started
    24 h period, or by occupation, and because a free allowance longer than
    the layover zeroes the charge.

    Defaults to 0.0 so a route payload stored before ROUTE_BUILDER 0.9.23
    stays constructible — see api/helpers/route_serialize.py.
    """

    stop_id: str
    stop_name: str
    country_code: str
    trip_ids: list[str]
    hours: float = 0.0


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
    Populated either by user input or by the stopgap demand model
    (models/demand/stopgap.py's distribute_demand()).

    composition_count: {comp_id: coaches_required} — a single entry,
    since a TripPair uses exactly one composition. Keyed by comp_id
    (not the Composition object itself, which isn't hashable — it has
    dict fields).

    coaches_required is a float, not an integer count of physical coach
    sets to buy for this route alone. Availability buffer (coach_avail_per)
    is pooled across an operator's whole network, not dedicated per route
    — so this route's fair cost share is trainsets / coach_avail_per,
    e.g. 2 sets needed in rotation at 80% availability = 2.5. Rounding up
    per route would overestimate cost by assuming a dedicated spare. The
    physical count itself is trainsets(), from the cycle-time rule.
    """

    outbound: Trip
    return_trip: Trip
    composition: Composition
    od_pairs: list[ODPair]

    @property
    def trips(self) -> list[Trip]:
        return [self.outbound, self.return_trip]

    def cycle_days(self, min_turnaround_min: int) -> int:
        """Calendar days one rake needs from a departure at the origin until
        it is back there in time for a scheduled departure — cycle_days_between()
        on this pair's own terminal times."""
        return cycle_days_between(
            self.outbound.departure_time_min,
            self.outbound.arrival_time_min,
            self.return_trip.departure_time_min,
            self.return_trip.arrival_time_min,
            min_turnaround_min,
        )

    def trainsets(self, schedule: Schedule) -> int:
        """Physical rakes this pair needs: trainsets_for_cycle() over the
        busiest month."""
        if not schedule.is_operating:
            return 0
        return trainsets_for_cycle(
            self.cycle_days(schedule.min_turnaround_min), schedule
        )

    def composition_count(self, schedule: Schedule) -> dict[str, float]:
        """The cost model's fleet basis: the physical trainsets divided by
        availability, i.e. this route's fair share of a pooled spare fleet
        (see the class docstring). Physical count: trainsets()."""
        n = self.trainsets(schedule) / self.composition.coach_avail_per
        return {self.composition.comp_id: n}

    @property
    def countries(self) -> set[str]:
        """All countries this pair's two trips pass through — from segment
        distance shares and stop country codes. Unlike Route.countries,
        there's no parking locations here — parkings are a Route-level
        concept (a formation may park at a stop neither trip in this pair
        actually visits), not something a single TripPair owns.

        "UNK" (RailRouter's sentinel for a leg whose midpoint falls in open
        water — ferry crossings, straits — see
        route_factory._check_country_coverage()) is excluded: it's not a
        real country, has no track_infrastructures row, and callers that
        look up per-country data (e.g. route_serialize.py's
        TrackInfraCollection.get()) would otherwise get None back for it.
        """
        result: set[str] = set()
        for trip in self.trips:
            for segment in trip.segments:
                result.update(segment.country_distance_shares.keys())
            for stop in trip.stops:
                if stop.country_code:
                    result.add(stop.country_code)
        result.discard("UNK")
        return result

    @property
    def loco_propulsion_min(self) -> int:
        """Loco operating time for this pair's two trips, in minutes.
        Sums driving + dynamics + buffer + dwell across all segments and stops of
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
            (
                p
                for p in self._trip_pairs
                if trip_id in (p.outbound.trip_id, p.return_trip.trip_id)
            ),
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
        shares, stop country codes, and parking locations.

        "UNK" (open-water/ferry sentinel — see TripPair.countries) is
        excluded for the same reason: it's not a real country and has no
        track_infrastructures row for callers to look up."""
        result: set[str] = set()
        for trip in self.trips:
            for segment in trip.segments:
                result.update(segment.country_distance_shares.keys())
            for stop in trip.stops:
                if stop.country_code:
                    result.add(stop.country_code)
        for pl in self._parkings:
            result.add(pl.country_code)
        result.discard("UNK")
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
        hours and multiplies by composition.loco_lease_total_eur_h
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
