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
  Cost     : EUR     (_eur)  — cost fields live in evaluation, NOT here
  Speed    : km/h    (_kmh)  — display/derived only, not stored

Hierarchy
---------
  Trip
  ├── trip_id: str                      (UUID, assigned by route_factory)
  ├── direction: int                    (0 = outbound, 1 = return)
  ├── departure_time_min: int
  ├── model_versions: ModelVersions
  ├── param_versions: ParamVersions
  ├── composition: Composition
  ├── stop_times: list[StopTime]
  ├── path: TripPath
  │   ├── shape: dict                   (GeoJSON LineString)
  │   ├── segments: list[TripSegment]    (one per stop pair, physics from CountryLegs)
  │   │   └── country_legs: list[CountryLeg]
  │   └── countries: list[CountrySegment] (one per country, physics from CountryLegs)
  └── stats: TripStats

Separation of concerns
-----------------------
Trip carries PHYSICS only — distances, times, energy in kWh.
NO monetary values (TAC, energy cost, station charges, parking).
All cost calculations live exclusively in models/evaluation/calc.py.

Immutability contract
---------------------
Trip is immutable after construction. The only permitted in-place mutation
is set_departure_time(), which shifts all stop_times clock values by a delta
with no external dependencies. All other changes require building a new Trip
via route_factory.

Consistency invariant (enforced in __post_init__):
  len(path.segments) == len(stop_times) - 1
  path.segments[i].from_stop_id == stop_times[i].stop_id   for all i
  path.segments[i].to_stop_id   == stop_times[i+1].stop_id for all i
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from models.utils import min_to_hhmm, min_to_h, m_to_km
from models.params import Composition, ModelVersions, ParamVersions

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

    stop_id: str
    stop_name: str
    lat: float
    lon: float
    stop_type: str  # "boarding" | "alighting" | "both"
    arrival_time_min: Optional[int]  # None for origin
    departure_time_min: Optional[int]  # None for destination
    dwell_time_min: Optional[int]  # None for terminal stops

    def shift_time(self, delta_min: int) -> "StopTime":
        """Return a new StopTime with clock times shifted by delta_min."""
        return StopTime(
            stop_id=self.stop_id,
            stop_name=self.stop_name,
            lat=self.lat,
            lon=self.lon,
            stop_type=self.stop_type,
            arrival_time_min=(
                self.arrival_time_min + delta_min
                if self.arrival_time_min is not None
                else None
            ),
            departure_time_min=(
                self.departure_time_min + delta_min
                if self.departure_time_min is not None
                else None
            ),
            dwell_time_min=self.dwell_time_min,
        )

    def to_dict(self) -> dict:
        return {
            "stop_id": self.stop_id,
            "stop_name": self.stop_name,
            "lat": self.lat,
            "lon": self.lon,
            "stop_type": self.stop_type,
            "arrival_time_min": self.arrival_time_min,
            "departure_time_min": self.departure_time_min,
            "dwell_time_min": self.dwell_time_min,
            "arrival_time_fmt": min_to_hhmm(self.arrival_time_min),
            "departure_time_fmt": min_to_hhmm(self.departure_time_min),
            "dwell_time_h": min_to_h(self.dwell_time_min),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "StopTime":
        return cls(
            stop_id=d["stop_id"],
            stop_name=d["stop_name"],
            lat=d["lat"],
            lon=d["lon"],
            stop_type=d["stop_type"],
            arrival_time_min=d.get("arrival_time_min"),
            departure_time_min=d.get("departure_time_min"),
            dwell_time_min=d.get("dwell_time_min"),
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
    exclusively in models/evaluation/calc.py using these values
    × infra cost params.

    Constructed exclusively via route_factory.
    """

    from_stop_id: str
    to_stop_id: str
    country_code: str  # ISO 3166-1 alpha-2
    distance_m: int
    driving_time_min: int  # pure engine time, no buffer
    buffer_time_min: int  # infra_buffer_quota_per × driving_time_min
    energy_kwh: float
    energy_kwh_per_km: float

    @property
    def total_time_min(self) -> int:
        return self.driving_time_min + self.buffer_time_min

    @property
    def distance_km(self) -> float:
        return m_to_km(self.distance_m)

    @property
    def avg_speed_kmh(self) -> float:
        if self.driving_time_min <= 0:
            return 0.0
        return self.distance_km / (self.driving_time_min / 60.0)

    def to_dict(self) -> dict:
        return {
            "from_stop_id": self.from_stop_id,
            "to_stop_id": self.to_stop_id,
            "country_code": self.country_code,
            "distance_m": self.distance_m,
            "distance_km": self.distance_km,
            "driving_time_min": self.driving_time_min,
            "buffer_time_min": self.buffer_time_min,
            "total_time_min": self.total_time_min,
            "avg_speed_kmh": self.avg_speed_kmh,
            "energy_kwh": self.energy_kwh,
            "energy_kwh_per_km": self.energy_kwh_per_km,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CountryLeg":
        return cls(
            from_stop_id=d["from_stop_id"],
            to_stop_id=d["to_stop_id"],
            country_code=d["country_code"],
            distance_m=d["distance_m"],
            driving_time_min=d["driving_time_min"],
            buffer_time_min=d["buffer_time_min"],
            energy_kwh=d["energy_kwh"],
            energy_kwh_per_km=d["energy_kwh_per_km"],
        )


# =============================================================================
# TRIP SEGMENT
# =============================================================================


@dataclass
class TripSegment:
    """
    One segment between two consecutive stops, potentially spanning
    multiple countries. Physics properties derived from country_legs.
    """

    from_stop_id: str
    to_stop_id: str
    geometry: list[list[float]]  # [[lon, lat], ...]
    country_legs: list[CountryLeg]

    @property
    def distance_m(self) -> int:
        return sum(cl.distance_m for cl in self.country_legs)

    @property
    def distance_km(self) -> float:
        return m_to_km(self.distance_m)

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
            "from_stop_id": self.from_stop_id,
            "to_stop_id": self.to_stop_id,
            "geometry": self.geometry,
            "distance_m": self.distance_m,
            "distance_km": self.distance_km,
            "driving_time_min": self.driving_time_min,
            "buffer_time_min": self.buffer_time_min,
            "total_time_min": self.total_time_min,
            "avg_speed_kmh": self.avg_speed_kmh,
            "energy_kwh": self.energy_kwh,
            "country_legs": [cl.to_dict() for cl in self.country_legs],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TripSegment":
        return cls(
            from_stop_id=d["from_stop_id"],
            to_stop_id=d["to_stop_id"],
            geometry=d["geometry"],
            country_legs=[CountryLeg.from_dict(cl) for cl in d["country_legs"]],
        )


# =============================================================================
# COUNTRY SEGMENT
# =============================================================================


@dataclass
class CountrySegment:
    """
    Aggregated summary of all CountryLegs within one country across the
    full trip. Physics properties derived from country_legs.
    """

    country_code: str
    country_legs: list[CountryLeg]

    @property
    def distance_m(self) -> int:
        return sum(cl.distance_m for cl in self.country_legs)

    @property
    def distance_km(self) -> float:
        return m_to_km(self.distance_m)

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
            "country_code": self.country_code,
            "distance_m": self.distance_m,
            "distance_km": self.distance_km,
            "driving_time_min": self.driving_time_min,
            "buffer_time_min": self.buffer_time_min,
            "total_time_min": self.total_time_min,
            "avg_speed_kmh": self.avg_speed_kmh,
            "energy_kwh": self.energy_kwh,
            "country_legs": [cl.to_dict() for cl in self.country_legs],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CountrySegment":
        return cls(
            country_code=d["country_code"],
            country_legs=[CountryLeg.from_dict(cl) for cl in d["country_legs"]],
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

    shape: dict
    segments: list[TripSegment]
    countries: list[CountrySegment]

    def to_dict(self) -> dict:
        return {
            "shape": self.shape,
            "segments": [s.to_dict() for s in self.segments],
            "countries": [c.to_dict() for c in self.countries],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TripPath":
        return cls(
            shape=d["shape"],
            segments=[TripSegment.from_dict(s) for s in d["segments"]],
            countries=[CountrySegment.from_dict(c) for c in d["countries"]],
        )


# =============================================================================
# TRIP STATS  — physics only, no monetary values
# =============================================================================


@dataclass
class TripStats:
    """
    Aggregated physics scalars for one trip. Physics only — NO monetary values.

    total_time_min = total_driving_time_min + total buffer across all segments.
    total_energy_kwh = sum of energy_kwh across all country legs.
    """

    total_distance_m: int
    total_driving_time_min: int
    total_time_min: int  # driving + buffer
    total_energy_kwh: float  # total energy consumed, no price applied

    def to_dict(self) -> dict:
        return {
            "total_distance_m": self.total_distance_m,
            "total_driving_time_min": self.total_driving_time_min,
            "total_time_min": self.total_time_min,
            "total_energy_kwh": self.total_energy_kwh,
            "total_distance_km": m_to_km(self.total_distance_m),
            "total_driving_time_h": min_to_h(self.total_driving_time_min),
            "total_time_h": min_to_h(self.total_time_min),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TripStats":
        return cls(
            total_distance_m=d["total_distance_m"],
            total_driving_time_min=d["total_driving_time_min"],
            total_time_min=d["total_time_min"],
            total_energy_kwh=d["total_energy_kwh"],
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
    model_versions and param_versions capture what was used to build this trip.

    Consistency invariant (checked in __post_init__):
      len(path.segments) == len(stop_times) - 1
      path.segments[i].from_stop_id == stop_times[i].stop_id
      path.segments[i].to_stop_id   == stop_times[i+1].stop_id
    """

    trip_id: str
    direction: int  # 0 = outbound, 1 = return
    departure_time_min: int
    model_versions: ModelVersions
    param_versions: ParamVersions
    composition: Composition
    stop_times: list[StopTime]
    path: TripPath
    stats: TripStats

    def __post_init__(self) -> None:
        pass  # validation deferred to _create() — do not instantiate directly

    def _post_validate(self) -> None:
        """Structural validation — called by _create() after construction."""
        if self.direction not in (0, 1):
            raise ValueError(
                f"Trip '{self.trip_id}': direction must be 0 or 1, "
                f"got {self.direction}."
            )
        n_stops = len(self.stop_times)
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
            expected_to = self.stop_times[i + 1].stop_id
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

    @classmethod
    def _create(
        cls,
        trip_id: str,
        direction: int,
        departure_time_min: int,
        model_versions: "ModelVersions",
        param_versions: "ParamVersions",
        composition: "Composition",
        stop_times: list["StopTime"],
        path: "TripPath",
        stats: "TripStats",
    ) -> "Trip":
        """
        Sole constructor for Trip — called exclusively by route_factory.
        Never instantiate Trip directly.
        """
        trip = cls(
            trip_id=trip_id,
            direction=direction,
            departure_time_min=departure_time_min,
            model_versions=model_versions,
            param_versions=param_versions,
            composition=composition,
            stop_times=stop_times,
            path=path,
            stats=stats,
        )
        trip._post_validate()
        return trip

    def set_departure_time(self, departure_time_min: int) -> None:
        """
        Shift all stop clock times by delta. dwell_time_min unchanged.
        path and stats unaffected — no re-routing needed.
        """
        delta = departure_time_min - self.departure_time_min
        self.departure_time_min = departure_time_min
        self.stop_times = [st.shift_time(delta) for st in self.stop_times]

    def to_dict(self) -> dict:
        return {
            "trip_id": self.trip_id,
            "direction_id": self.direction,
            "departure_time": min_to_hhmm(self.departure_time_min),
            "departure_time_min": self.departure_time_min,
            "model_versions": self.model_versions.versions,
            "param_versions": {
                k: {
                    "value": v.value,
                    "version": v.version,
                    "is_default": v.is_default,
                    "source": (
                        {
                            "source_id": v.source.source_id,
                            "source_description": v.source.source_description,
                            "source_url": v.source.source_url,
                            "source_date": v.source.source_date,
                        }
                        if v.source
                        else None
                    ),
                    "description": v.description,
                }
                for k, v in self.param_versions.entries.items()
            },
            "composition": {
                "comp_id": self.composition.comp_id,
                "comp_description": self.composition.comp_description,
                "operator_id": self.composition.operator_id,
                "places_by_class": self.composition.places_by_class,
                "density_by_class": self.composition.density_by_class,
            },
            "stop_times": [st.to_dict() for st in self.stop_times],
            "shape": self.path.shape,
            "path": self.path.to_dict(),
            "stats": self.stats.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Trip":
        """
        Reconstruct a Trip from its to_dict() representation.

        composition is reconstructed with only display fields — cost fields
        are sentinel zeros since evaluate_route() always reloads the full
        Composition from the DB via loader.build_composition(comp_id).
        """
        comp_d = d["composition"]
        composition = Composition(
            comp_id=comp_d["comp_id"],
            comp_description=comp_d.get("comp_description", ""),
            operator_id=comp_d.get("operator_id", ""),
            driver_factor=0.0,
            max_speed_kmh=0.0,
            hsr_allowed=False,
            min_boarding_time_min=0,
            min_alighting_time_min=0,
            energy_factor_weight=0.0,
            energy_factor_speed=0.0,
            energy_factor_terrain=0.0,
            total_weight_t=0.0,
            total_crew=0.0,
            places_by_class=comp_d.get("places_by_class", {}),
            density_by_class=comp_d.get("density_by_class", {}),
            driver_costs_eur_h=0.0,
            crew_costs_eur_h=0.0,
            driver_overhead_min=0,
            crew_overhead_min=0,
            ebit_margin_per=0.0,
            financing_quota_per=0.0,
            shunting_eur_day=0.0,
            var_overhead_per=0.0,
            fix_overhead_quota_per=0.0,
            svc_stockings_eur_place={},
            purchase_loco_eur=0.0,
            purchase_coach_eur=0.0,
            loco_avail_per=0.0,
            coach_avail_per=0.0,
            loco_amort_years=0,
            coach_amort_years=0,
            cleaning_services_eur_day=0.0,
            loco_maint_eur_km=0.0,
            coach_maint_eur_km=0.0,
        )
        return cls(
            trip_id=d["trip_id"],
            direction=d["direction_id"],
            departure_time_min=d["departure_time_min"],
            model_versions=ModelVersions(versions=d.get("model_versions", {})),
            param_versions=ParamVersions(),  # not reconstructed from dict
            composition=composition,
            stop_times=[StopTime.from_dict(st) for st in d["stop_times"]],
            path=TripPath.from_dict(d["path"]),
            stats=TripStats.from_dict(d["stats"]),
        )
