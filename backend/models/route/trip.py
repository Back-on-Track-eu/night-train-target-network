"""
trip.py
=======
Immutable domain model for one directional run of a night train route.

Unit conventions
----------------
  Distance : metres  (_m)
  Duration : minutes (_min)
  Clock time: minutes from midnight of day 1 (_min)
              e.g. 21:00 = 1260, next-day 08:00 = 1920
  Energy   : kWh     (_kwh)
  Cost     : EUR     (_eur)  — cost fields live in cost_rev_eval, NOT here
  Speed    : km/h    (_kmh)  — display/derived only, not stored

Hierarchy
---------
  Trip
  ├── trip_id: str                      (UUID, assigned by route_factory)
  ├── direction: int                    (0 = outbound, 1 = return)
  ├── departure_time_min: int
  ├── params_snapshot: ParamsSnapshot
  ├── composition: CompositionParams    (display fields only)
  ├── stop_times: list[StopTime]
  ├── path: TripPath
  │   ├── shape: dict                   (GeoJSON LineString)
  │   ├── segments: list[TripSegment]
  │   │   └── country_legs: list[CountryLeg]
  │   └── countries: list[CountrySegment]
  └── stats: TripStats

Separation of concerns
-----------------------
Trip carries PHYSICS only — distances, times, energy in kWh.
NO monetary values (TAC, energy cost, station charges, parking).
All cost calculations live exclusively in models/cost_rev_eval/calc.py.

Immutability contract
---------------------
Trip is immutable after construction. The only permitted in-place mutation
is set_departure_time(), which shifts all stop_times clock values by a delta
with no external dependencies. All other changes require building a new Trip
via route_factory and calling route.update_trip().

Consistency invariant (enforced in __post_init__):
  len(path.segments) == len(stop_times) - 1
  path.segments[i].from_stop_id == stop_times[i].stop_id   for all i
  path.segments[i].to_stop_id   == stop_times[i+1].stop_id for all i

Serialisation
-------------
to_dict() converts internal units to display-friendly formats:
  _min clock times → "HH:MM (+Nd)" strings  (arrival_time_fmt etc.)
  _min durations   → decimal hours           (for API consumers)
  _m distances     → km
from_dict() expects the raw internal values (minutes, metres).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from models.params import CompositionParams


# =============================================================================
# UNIT CONVERSION HELPERS
# =============================================================================

def _min_to_hhmm(minutes: Optional[int]) -> Optional[str]:
    """
    Convert minutes-from-midnight to HH:MM string, handling overnight.
    e.g. 1260 → "21:00", 1920 → "08:00 (+1d)"
    """
    if minutes is None:
        return None
    days  = minutes // 1440
    h     = (minutes % 1440) // 60
    m     = minutes % 60
    day_s = f" (+{days}d)" if days > 0 else ""
    return f"{h:02d}:{m:02d}{day_s}"


def _min_to_h(minutes: Optional[int]) -> Optional[float]:
    """Convert minutes to decimal hours. Returns None if input is None."""
    if minutes is None:
        return None
    return minutes / 60.0


def _m_to_km(metres: int) -> float:
    """Convert metres to kilometres."""
    return metres / 1000.0


# =============================================================================
# PARAMS SNAPSHOT
# =============================================================================

@dataclass
class ParamsSnapshot:
    """
    Records the exact parameter versions and model versions used to build
    this trip. Enables full reproducibility.

    composition_version:   comp_version of the DB row used.
    infra_generation:      table-generation counter at build time.
                           Stand-in: MAX(infra_row_id) WHERE is_current.
    stops_generation:      table-generation counter at build time.
                           Stand-in: MAX(stop_row_id) WHERE is_current.
    route_builder_version: ROUTE_BUILDER_VERSION at build time.
    energy_calc_version:   ENERGY_CALC_VERSION at build time.
    """

    composition_id:         str
    composition_version:    int
    infra_generation:       int
    stops_generation:       int
    route_builder_version:  str
    energy_calc_version:    str

    def to_dict(self) -> dict:
        return {
            "composition_id":         self.composition_id,
            "composition_version":    self.composition_version,
            "infra_generation":       self.infra_generation,
            "stops_generation":       self.stops_generation,
            "route_builder_version":  self.route_builder_version,
            "energy_calc_version":    self.energy_calc_version,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ParamsSnapshot":
        return cls(
            composition_id        = d["composition_id"],
            composition_version   = d["composition_version"],
            infra_generation      = d["infra_generation"],
            stops_generation      = d["stops_generation"],
            route_builder_version = d["route_builder_version"],
            energy_calc_version   = d["energy_calc_version"],
        )


# =============================================================================
# STOP TIME
# =============================================================================

@dataclass
class StopTime:
    """
    One row in a trip's timetable — mirrors GTFS stop_times.txt.

    All times in minutes from midnight of day 1.
    dwell_time_min is a duration, not a clock time — unaffected by
    set_departure_time().
    """

    stop_id:            str
    stop_name:          str
    lat:                float
    lon:                float
    stop_type:          str                 # "boarding" | "alighting" | "both"
    arrival_time_min:   Optional[int]       # None for origin
    departure_time_min: Optional[int]       # None for destination
    dwell_time_min:     Optional[int]       # None for terminal stops

    def shift_time(self, delta_min: int) -> "StopTime":
        """Return a new StopTime with clock times shifted by delta_min."""
        return StopTime(
            stop_id            = self.stop_id,
            stop_name          = self.stop_name,
            lat                = self.lat,
            lon                = self.lon,
            stop_type          = self.stop_type,
            arrival_time_min   = (self.arrival_time_min + delta_min
                                  if self.arrival_time_min is not None else None),
            departure_time_min = (self.departure_time_min + delta_min
                                  if self.departure_time_min is not None else None),
            dwell_time_min     = self.dwell_time_min,
        )

    def to_dict(self) -> dict:
        return {
            "stop_id":            self.stop_id,
            "stop_name":          self.stop_name,
            "lat":                self.lat,
            "lon":                self.lon,
            "stop_type":          self.stop_type,
            "arrival_time_min":   self.arrival_time_min,
            "departure_time_min": self.departure_time_min,
            "dwell_time_min":     self.dwell_time_min,
            "arrival_time_fmt":   _min_to_hhmm(self.arrival_time_min),
            "departure_time_fmt": _min_to_hhmm(self.departure_time_min),
            "dwell_time_h":       _min_to_h(self.dwell_time_min),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "StopTime":
        return cls(
            stop_id            = d["stop_id"],
            stop_name          = d["stop_name"],
            lat                = d["lat"],
            lon                = d["lon"],
            stop_type          = d["stop_type"],
            arrival_time_min   = d.get("arrival_time_min"),
            departure_time_min = d.get("departure_time_min"),
            dwell_time_min     = d.get("dwell_time_min"),
        )


# =============================================================================
# COUNTRY LEG  — physics only, no monetary values
# =============================================================================

@dataclass
class CountryLeg:
    """
    One sub-segment of a TripSegment within a single country.

    Physics only — distance, time, speed, buffer, energy in kWh.
    NO cost fields. TAC, energy costs, station charges are computed
    exclusively in models/cost_rev_eval/calc.py using these physics
    values × infra cost params.

    Constructed exclusively via _router_leg_to_country_leg() in route_factory.
    """

    from_stop_id:      str
    to_stop_id:        str
    country_code:      str      # ISO 3166-1 alpha-2
    distance_m:        int
    driving_time_min:  int      # pure engine time, no buffer
    buffer_time_min:   int      # infra_buffer_quota_per × driving_time_min
    energy_kwh:        float
    energy_kwh_per_km: float

    @property
    def total_time_min(self) -> int:
        return self.driving_time_min + self.buffer_time_min

    @property
    def distance_km(self) -> float:
        return _m_to_km(self.distance_m)

    @property
    def avg_speed_kmh(self) -> float:
        if self.driving_time_min <= 0:
            return 0.0
        return self.distance_km / (self.driving_time_min / 60.0)

    def to_dict(self) -> dict:
        return {
            "from_stop_id":      self.from_stop_id,
            "to_stop_id":        self.to_stop_id,
            "country_code":      self.country_code,
            "distance_m":        self.distance_m,
            "distance_km":       self.distance_km,
            "driving_time_min":  self.driving_time_min,
            "buffer_time_min":   self.buffer_time_min,
            "total_time_min":    self.total_time_min,
            "avg_speed_kmh":     self.avg_speed_kmh,
            "energy_kwh":        self.energy_kwh,
            "energy_kwh_per_km": self.energy_kwh_per_km,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CountryLeg":
        return cls(
            from_stop_id      = d["from_stop_id"],
            to_stop_id        = d["to_stop_id"],
            country_code      = d["country_code"],
            distance_m        = d["distance_m"],
            driving_time_min  = d["driving_time_min"],
            buffer_time_min   = d["buffer_time_min"],
            energy_kwh        = d["energy_kwh"],
            energy_kwh_per_km = d["energy_kwh_per_km"],
        )


# =============================================================================
# TRIP SEGMENT
# =============================================================================

@dataclass
class TripSegment:
    """
    One segment between two consecutive stops, potentially spanning
    multiple countries. All aggregates derived from country_legs.
    Physics only — no cost values.
    """

    from_stop_id:  str
    to_stop_id:    str
    geometry:      list[list[float]]    # [[lon, lat], ...]
    country_legs:  list[CountryLeg]

    @property
    def distance_m(self) -> int:
        return sum(cl.distance_m for cl in self.country_legs)

    @property
    def distance_km(self) -> float:
        return _m_to_km(self.distance_m)

    @property
    def driving_time_min(self) -> int:
        return sum(cl.driving_time_min for cl in self.country_legs)

    @property
    def buffer_time_min(self) -> int:
        return sum(cl.buffer_time_min for cl in self.country_legs)

    @property
    def total_time_min(self) -> int:
        return self.driving_time_min + self.buffer_time_min

    @property
    def avg_speed_kmh(self) -> float:
        if self.driving_time_min <= 0:
            return 0.0
        return self.distance_km / (self.driving_time_min / 60.0)

    @property
    def energy_kwh(self) -> float:
        return sum(cl.energy_kwh for cl in self.country_legs)

    def to_dict(self) -> dict:
        return {
            "from_stop_id":    self.from_stop_id,
            "to_stop_id":      self.to_stop_id,
            "distance_m":      self.distance_m,
            "distance_km":     self.distance_km,
            "driving_time_min": self.driving_time_min,
            "buffer_time_min": self.buffer_time_min,
            "total_time_min":  self.total_time_min,
            "avg_speed_kmh":   self.avg_speed_kmh,
            "energy_kwh":      self.energy_kwh,
            "geometry":        self.geometry,
            "country_legs":    [cl.to_dict() for cl in self.country_legs],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TripSegment":
        return cls(
            from_stop_id = d["from_stop_id"],
            to_stop_id   = d["to_stop_id"],
            geometry     = d["geometry"],
            country_legs = [CountryLeg.from_dict(cl) for cl in d["country_legs"]],
        )


# =============================================================================
# COUNTRY SEGMENT
# =============================================================================

@dataclass
class CountrySegment:
    """
    Aggregated summary of all CountryLegs within one country across the
    full trip. Physics only — no cost values.
    """

    country_code: str
    country_legs: list[CountryLeg]

    @property
    def distance_m(self) -> int:
        return sum(cl.distance_m for cl in self.country_legs)

    @property
    def distance_km(self) -> float:
        return _m_to_km(self.distance_m)

    @property
    def driving_time_min(self) -> int:
        return sum(cl.driving_time_min for cl in self.country_legs)

    @property
    def buffer_time_min(self) -> int:
        return sum(cl.buffer_time_min for cl in self.country_legs)

    @property
    def total_time_min(self) -> int:
        return self.driving_time_min + self.buffer_time_min

    @property
    def avg_speed_kmh(self) -> float:
        if self.driving_time_min <= 0:
            return 0.0
        return self.distance_km / (self.driving_time_min / 60.0)

    @property
    def energy_kwh(self) -> float:
        return sum(cl.energy_kwh for cl in self.country_legs)

    def to_dict(self) -> dict:
        return {
            "country_code":     self.country_code,
            "distance_m":       self.distance_m,
            "distance_km":      self.distance_km,
            "driving_time_min": self.driving_time_min,
            "buffer_time_min":  self.buffer_time_min,
            "total_time_min":   self.total_time_min,
            "avg_speed_kmh":    self.avg_speed_kmh,
            "energy_kwh":       self.energy_kwh,
            "country_legs":     [cl.to_dict() for cl in self.country_legs],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CountrySegment":
        return cls(
            country_code = d["country_code"],
            country_legs = [CountryLeg.from_dict(cl) for cl in d["country_legs"]],
        )


# =============================================================================
# TRIP PATH
# =============================================================================

@dataclass
class TripPath:
    """
    Full geographical representation of a trip — mirrors GTFS shapes.txt.

    shape     — GeoJSON LineString of the complete trip geometry.
    segments  — one TripSegment per consecutive stop pair.
    countries — one CountrySegment per country traversed.
    """

    shape:     dict
    segments:  list[TripSegment]
    countries: list[CountrySegment]

    def to_dict(self) -> dict:
        return {
            "shape":     self.shape,
            "segments":  [s.to_dict() for s in self.segments],
            "countries": [c.to_dict() for c in self.countries],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TripPath":
        return cls(
            shape     = d["shape"],
            segments  = [TripSegment.from_dict(s) for s in d["segments"]],
            countries = [CountrySegment.from_dict(c) for c in d["countries"]],
        )


# =============================================================================
# TRIP STATS  — physics only, no monetary values
# =============================================================================

@dataclass
class TripStats:
    """
    Aggregated physics scalars for one trip.
    Physics only — NO monetary values.

    The cost model (calc.py) uses these values × infra/composition cost
    params to compute TAC, energy costs, station charges etc.

    total_time_min = total_driving_time_min + total buffer across all segments.
    total_energy_kwh = sum of energy_kwh across all country legs.
    """

    total_distance_m:       int
    total_driving_time_min: int
    total_time_min:         int     # driving + buffer
    total_energy_kwh:       float   # total energy consumed, no price applied

    def to_dict(self) -> dict:
        return {
            "total_distance_m":       self.total_distance_m,
            "total_driving_time_min": self.total_driving_time_min,
            "total_time_min":         self.total_time_min,
            "total_energy_kwh":       self.total_energy_kwh,
            "total_distance_km":      _m_to_km(self.total_distance_m),
            "total_driving_time_h":   _min_to_h(self.total_driving_time_min),
            "total_time_h":           _min_to_h(self.total_time_min),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TripStats":
        return cls(
            total_distance_m        = d["total_distance_m"],
            total_driving_time_min  = d["total_driving_time_min"],
            total_time_min          = d["total_time_min"],
            total_energy_kwh        = d["total_energy_kwh"],
        )


# =============================================================================
# TRIP
# =============================================================================

@dataclass
class Trip:
    """
    Immutable domain model for one directional run of a Route.
    Mirrors GTFS trips.txt.

    trip_id            — UUID assigned by route_factory.
    direction          — 0 = outbound, 1 = return (GTFS direction_id).
    departure_time_min — minutes from midnight day 1 (e.g. 21:00 → 1260).

    Physics only — no monetary values anywhere in this object.

    Consistency invariant (checked in __post_init__):
      len(path.segments) == len(stop_times) - 1
      path.segments[i].from_stop_id == stop_times[i].stop_id
      path.segments[i].to_stop_id   == stop_times[i+1].stop_id
    """

    trip_id:            str
    direction:          int                 # 0 = outbound, 1 = return
    departure_time_min: int
    params_snapshot:    ParamsSnapshot
    composition:        CompositionParams
    stop_times:         list[StopTime]
    path:               TripPath
    stats:              TripStats

    def __post_init__(self) -> None:
        if self.direction not in (0, 1):
            raise ValueError(
                f"Trip '{self.trip_id}': direction must be 0 or 1, "
                f"got {self.direction}."
            )
        n_stops    = len(self.stop_times)
        n_segments = len(self.path.segments)
        if n_stops < 2:
            raise ValueError(
                f"Trip '{self.trip_id}': at least 2 stop_times required, "
                f"got {n_stops}."
            )
        if n_segments != n_stops - 1:
            raise ValueError(
                f"Trip '{self.trip_id}': expected {n_stops - 1} segments "
                f"for {n_stops} stops, got {n_segments}."
            )
        for i, seg in enumerate(self.path.segments):
            expected_from = self.stop_times[i].stop_id
            expected_to   = self.stop_times[i + 1].stop_id
            if seg.from_stop_id != expected_from:
                raise ValueError(
                    f"Trip '{self.trip_id}': segment {i} from_stop_id "
                    f"'{seg.from_stop_id}' != stop_times[{i}].stop_id "
                    f"'{expected_from}'."
                )
            if seg.to_stop_id != expected_to:
                raise ValueError(
                    f"Trip '{self.trip_id}': segment {i} to_stop_id "
                    f"'{seg.to_stop_id}' != stop_times[{i + 1}].stop_id "
                    f"'{expected_to}'."
                )

    def set_departure_time(self, departure_time_min: int) -> None:
        """
        Shift all stop clock times by delta. dwell_time_min unchanged.
        path and stats unaffected — no re-routing needed.
        """
        delta                   = departure_time_min - self.departure_time_min
        self.departure_time_min = departure_time_min
        self.stop_times         = [st.shift_time(delta) for st in self.stop_times]

    def to_dict(self) -> dict:
        return {
            "trip_id":            self.trip_id,
            "direction_id":       self.direction,
            "departure_time":     _min_to_hhmm(self.departure_time_min),
            "departure_time_min": self.departure_time_min,
            "params_snapshot":    self.params_snapshot.to_dict(),
            "composition": {
                "comp_id":          self.composition.comp_id,
                "comp_description": self.composition.comp_description,
                "operator_id":      self.composition.company,
                "seats_total":      self.composition.seats_total,
                "couchettes_total": self.composition.couchettes_total,
                "sleepers_total":   self.composition.sleepers_total,
            },
            "stop_times": [st.to_dict() for st in self.stop_times],
            "shape":      self.path.shape,
            "path":       self.path.to_dict(),
            "stats":      self.stats.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Trip":
        composition = CompositionParams.from_display_dict(d["composition"])
        return cls(
            trip_id            = d["trip_id"],
            direction          = d["direction_id"],
            departure_time_min = d["departure_time_min"],
            params_snapshot    = ParamsSnapshot.from_dict(d["params_snapshot"]),
            composition        = composition,
            stop_times         = [StopTime.from_dict(st) for st in d["stop_times"]],
            path               = TripPath.from_dict(d["path"]),
            stats              = TripStats.from_dict(d["stats"]),
        )