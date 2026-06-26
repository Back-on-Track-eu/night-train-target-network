"""
calc.py
=======
Night Train Cost and Revenue Evaluation Model.

# TODO: DETAILED REVIEW NEEDED
# This file was written in one pass and has not yet been reviewed in detail.
# Before going to production, review:
#   - All cost calculation formulas for correctness
#   - per_sold vs per_available place/place-km split per class (added, needs validation)
#   - OD pair cost allocation logic (_build_od_breakdown)
#   - Normalised matrix divisors (available vs sold place-km)
#   - Revenue calculation from demand input
#   - _sum_breakdowns aggregation across trips
#   - Country breakdown scope and distance attribution
# Tag: david@backontrack.eu

Unit conventions (internal)
----------------------------
  Distance : metres  (_m)   — converted to km for cost calc
  Duration : minutes (_min) — converted to hours for cost calc
  Energy   : kWh     (_kwh)
  Cost/Rev : EUR     (_eur)

Separation of concerns
-----------------------
This module owns ALL monetary calculations.
Trip/Route objects carry physics only. calc.py multiplies those
by cost parameters from infra + composition params.

Input
-----
  route        : Route (physics + composition)
  route_demand : RouteDemand (OD pairs with places sold + avg price per trip)
  operating_days_year : int

Output — NormalisedMatrix at four levels
-----------------------------------------
  summary   : route-level aggregate
  by_trip   : one per trip
  by_country: infrastructure-only, aggregated across trips
  by_od     : per OD pair per trip (cost allocated, see below)

Normalised views (7)
---------------------
  per_day              = raw (costs already per operating day)
  per_year             = raw × operating_days_year
  per_trip             = raw ÷ n_trips
  per_trip_km          = raw ÷ total_distance_km
  per_available_place_km = raw ÷ Σ(capacity × distance_km)
  per_sold_place_km    = raw ÷ Σ(places_sold × od_distance_km)
  per_available_place_of_class    = raw ÷ available places per class_main
  per_sold_place_of_class         = raw ÷ sold places per class_main
  per_available_place_km_of_class = raw ÷ (available places × distance_km) per class_main
  per_sold_place_km_of_class      = raw ÷ (sold places × distance_km) per class_main

OD pair cost allocation
-----------------------
  Infrastructure (TAC, energy, station charges):
    exact — only legs/stops actually traversed by this OD pair
  Variable/km (maintenance):
    proportional to OD distance share of trip
  Variable/hour (driver, crew):
    proportional to OD driving-time share of trip
  Fixed/day (amortisation, financing, cleaning, overhead, shunting, parking):
    proportional to density-weighted sold-place-km share of trip
  Variable/ticket (svc_stockings):
    direct — based on OD pair places_sold
  Variable/ticket (var_overhead, ebit):
    proportional to OD revenue share of trip
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from models.evaluation.version import CALC_VERSION, CALC_FORMULAS, CalcFormula
from models.params import (
    Composition, TrackInfraCollection, StopInfraCollection,
    ModelVersions, ParamVersions,
    CompositionReference, IndicativeFigures,
)
from models.route.route import Route
from models.route.trip import Trip, TripSegment, CountryLeg, TripPath, TripStats, CountrySegment, StopTime
from models.utils import m_to_km, min_to_h

logger = logging.getLogger(__name__)


# =============================================================================
# DEMAND INPUT
# =============================================================================

@dataclass
class ODDemand:
    """
    Demand for one OD pair on one trip, for one accommodation class.
    e.g. Vienna → Hamburg, Couchette: 26 places sold at avg €89.
    """
    origin_stop_id:      str
    destination_stop_id: str
    class_main:          str    # "Seat" | "Couchette" | "Sleeper" | "Capsule" | "Catering"
    places_sold:         int
    avg_price:           float  # EUR


@dataclass
class TripDemand:
    """All OD demand for one trip."""
    trip_id:  str
    od_pairs: list[ODDemand] = field(default_factory=list)

    def total_revenue(self) -> float:
        return sum(od.places_sold * od.avg_price for od in self.od_pairs)

    def revenue_by_class(self) -> dict[str, float]:
        result: dict[str, float] = defaultdict(float)
        for od in self.od_pairs:
            result[od.class_main] += od.places_sold * od.avg_price
        return dict(result)

    def places_sold_by_class(self) -> dict[str, int]:
        result: dict[str, int] = defaultdict(int)
        for od in self.od_pairs:
            result[od.class_main] += od.places_sold
        return dict(result)


@dataclass
class RouteDemand:
    """Demand for all trips in a route."""
    trips: dict[str, TripDemand] = field(default_factory=dict)  # keyed by trip_id

    def get_trip_demand(self, trip_id: str) -> TripDemand:
        return self.trips.get(trip_id, TripDemand(trip_id=trip_id))


# =============================================================================
# CALC STEP
# =============================================================================

@dataclass
class CalcStep:
    """
    One evaluated calculation step.
    formula_key references CALC_FORMULAS in version.py.
    """
    formula_key: str
    inputs:      dict[str, float]
    result:      float

    def scale(self, factor: float) -> "CalcStep":
        """Return a new CalcStep with all values multiplied by factor."""
        if factor == 0:
            return CalcStep(self.formula_key, {k: 0.0 for k in self.inputs}, 0.0)
        return CalcStep(
            formula_key = self.formula_key,
            inputs      = {k: v * factor for k, v in self.inputs.items()},
            result      = self.result * factor,
        )

    def to_dict(self) -> dict:
        return {
            "formula_key": self.formula_key,
            "inputs":      self.inputs,
            "result":      self.result,
        }


# =============================================================================
# BREAKDOWN
# =============================================================================

@dataclass
class Breakdown:
    """
    Full cost/revenue breakdown. All values in EUR per operating day.
    scope: "full" | "infrastructure_only" | "od_pair"
    """

    scope: str = "full"

    # Revenue
    revenue_by_class:   dict[str, float] = field(default_factory=dict)
    total_revenue:      float = 0.0

    # Cost — fixed / day
    loco_amortisation:  float = 0.0
    coach_amortisation: float = 0.0
    financing:          float = 0.0
    fix_overhead:       float = 0.0
    cleaning:           float = 0.0
    shunting:           float = 0.0
    parking:            float = 0.0

    # Cost — variable / km
    loco_maintenance:   float = 0.0
    coach_maintenance:  float = 0.0

    # Cost — variable / hour
    driver:             float = 0.0
    crew:               float = 0.0

    # Cost — variable / ticket
    svc_stockings_by_class: dict[str, float] = field(default_factory=dict)
    var_overhead:           float = 0.0

    # Cost — infrastructure
    track_access:       float = 0.0
    energy:             float = 0.0
    station_charges:    float = 0.0

    # Cost — ebit
    ebit_margin:        float = 0.0

    # Calc steps
    calc_steps: list[CalcStep] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Derived totals
    # ------------------------------------------------------------------

    @property
    def fixed_day_total(self) -> float:
        return (self.loco_amortisation + self.coach_amortisation
                + self.financing + self.fix_overhead
                + self.cleaning + self.shunting + self.parking)

    @property
    def variable_km_total(self) -> float:
        return self.loco_maintenance + self.coach_maintenance

    @property
    def variable_hour_total(self) -> float:
        return self.driver + self.crew

    @property
    def variable_ticket_total(self) -> float:
        return sum(self.svc_stockings_by_class.values()) + self.var_overhead

    @property
    def infrastructure_total(self) -> float:
        return self.track_access + self.energy + self.station_charges

    @property
    def total_cost(self) -> float:
        return (self.fixed_day_total + self.variable_km_total
                + self.variable_hour_total + self.variable_ticket_total
                + self.infrastructure_total + self.ebit_margin)

    @property
    def margin(self) -> float:
        return self.total_revenue - self.total_cost

    @property
    def margin_pct(self) -> float:
        return self.margin / self.total_revenue if self.total_revenue > 0 else 0.0

    # ------------------------------------------------------------------
    # Internal scale — multiply all values by factor
    # ------------------------------------------------------------------

    def _scale(self, factor: float) -> "Breakdown":
        if factor == 0:
            return Breakdown(scope=self.scope)
        return Breakdown(
            scope                  = self.scope,
            revenue_by_class       = {k: v * factor for k, v in self.revenue_by_class.items()},
            total_revenue          = self.total_revenue          * factor,
            loco_amortisation      = self.loco_amortisation      * factor,
            coach_amortisation     = self.coach_amortisation     * factor,
            financing              = self.financing               * factor,
            fix_overhead           = self.fix_overhead            * factor,
            cleaning               = self.cleaning                * factor,
            shunting               = self.shunting                * factor,
            parking                = self.parking                 * factor,
            loco_maintenance       = self.loco_maintenance        * factor,
            coach_maintenance      = self.coach_maintenance       * factor,
            driver                 = self.driver                  * factor,
            crew                   = self.crew                    * factor,
            svc_stockings_by_class = {k: v * factor for k, v in self.svc_stockings_by_class.items()},
            var_overhead           = self.var_overhead             * factor,
            track_access           = self.track_access             * factor,
            energy                 = self.energy                   * factor,
            station_charges        = self.station_charges          * factor,
            ebit_margin            = self.ebit_margin              * factor,
            calc_steps             = [s.scale(factor) for s in self.calc_steps],
        )

    # ------------------------------------------------------------------
    # Normalise functions
    # ------------------------------------------------------------------

    def per_day(self) -> "Breakdown":
        """Raw — already per operating day."""
        return self._scale(1.0)

    def per_year(self, operating_days_year: int) -> "Breakdown":
        """Annual total: multiply by operating days per year."""
        return self._scale(float(operating_days_year))

    def per_trip(self, n_trips: int) -> "Breakdown":
        """Average per trip."""
        return self._scale(1.0 / n_trips) if n_trips > 0 else self._scale(0)

    def per_trip_km(self, total_distance_km: float) -> "Breakdown":
        """Per trip-km across all trips."""
        return self._scale(1.0 / total_distance_km) if total_distance_km > 0 else self._scale(0)

    def per_available_place_km(self, total_available_place_km: float) -> "Breakdown":
        """Per available (capacity) place-km — supply-side view."""
        return self._scale(1.0 / total_available_place_km) if total_available_place_km > 0 else self._scale(0)

    def per_sold_place_km(self, total_sold_place_km: float) -> "Breakdown":
        """Per sold place-km — demand-side view."""
        return self._scale(1.0 / total_sold_place_km) if total_sold_place_km > 0 else self._scale(0)

    def per_available_place_of_class(self, available_places: int) -> "Breakdown":
        """Per available (capacity) place in one class."""
        return self._scale(1.0 / available_places) if available_places > 0 else self._scale(0)

    def per_sold_place_of_class(self, sold_places: int) -> "Breakdown":
        """Per sold place in one class."""
        return self._scale(1.0 / sold_places) if sold_places > 0 else self._scale(0)

    def per_available_place_km_of_class(self, available_places: int, distance_km: float) -> "Breakdown":
        """Per available (capacity) place-km in one class."""
        denom = available_places * distance_km
        return self._scale(1.0 / denom) if denom > 0 else self._scale(0)

    def per_sold_place_km_of_class(self, sold_places: int, distance_km: float) -> "Breakdown":
        """Per sold place-km in one class."""
        denom = sold_places * distance_km
        return self._scale(1.0 / denom) if denom > 0 else self._scale(0)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "scope":   self.scope,
            "revenue": {
                "by_class": self.revenue_by_class,
                "total":    self.total_revenue,
            },
            "cost": {
                "fixed_day": {
                    "loco_amortisation":  self.loco_amortisation,
                    "coach_amortisation": self.coach_amortisation,
                    "financing":          self.financing,
                    "fix_overhead":       self.fix_overhead,
                    "cleaning":           self.cleaning,
                    "shunting":           self.shunting,
                    "parking":            self.parking,
                    "total":              self.fixed_day_total,
                },
                "variable_km": {
                    "loco_maintenance":  self.loco_maintenance,
                    "coach_maintenance": self.coach_maintenance,
                    "total":             self.variable_km_total,
                },
                "variable_hour": {
                    "driver": self.driver,
                    "crew":   self.crew,
                    "total":  self.variable_hour_total,
                },
                "variable_ticket": {
                    "svc_stockings": self.svc_stockings_by_class,
                    "var_overhead":  self.var_overhead,
                    "total":         self.variable_ticket_total,
                },
                "infrastructure": {
                    "track_access":   self.track_access,
                    "energy":         self.energy,
                    "station_charges":self.station_charges,
                    "total":          self.infrastructure_total,
                },
                "ebit_margin": self.ebit_margin,
                "total":       self.total_cost,
            },
            "margin":     self.margin,
            "margin_pct": self.margin_pct,
            "calc_steps": [s.to_dict() for s in self.calc_steps],
        }


# =============================================================================
# NORMALISED MATRIX
# =============================================================================

@dataclass
class NormalisedMatrix:
    """All normalised views for one level."""
    per_day:                          Breakdown
    per_year:                         Breakdown
    per_trip:                         Breakdown
    per_trip_km:                      Breakdown
    per_available_place_km:           Breakdown
    per_sold_place_km:                Breakdown
    per_available_place_of_class:     dict[str, Breakdown]   # keyed by class_main
    per_sold_place_of_class:          dict[str, Breakdown]   # keyed by class_main
    per_available_place_km_of_class:  dict[str, Breakdown]   # keyed by class_main
    per_sold_place_km_of_class:       dict[str, Breakdown]   # keyed by class_main

    def to_dict(self) -> dict:
        return {
            "per_day":                         self.per_day.to_dict(),
            "per_year":                        self.per_year.to_dict(),
            "per_trip":                        self.per_trip.to_dict(),
            "per_trip_km":                     self.per_trip_km.to_dict(),
            "per_available_place_km":          self.per_available_place_km.to_dict(),
            "per_sold_place_km":               self.per_sold_place_km.to_dict(),
            "per_available_place_of_class":    {k: v.to_dict() for k, v in self.per_available_place_of_class.items()},
            "per_sold_place_of_class":         {k: v.to_dict() for k, v in self.per_sold_place_of_class.items()},
            "per_available_place_km_of_class": {k: v.to_dict() for k, v in self.per_available_place_km_of_class.items()},
            "per_sold_place_km_of_class":      {k: v.to_dict() for k, v in self.per_sold_place_km_of_class.items()},
        }


def _build_matrix(
        breakdown:               Breakdown,
        operating_days_year:     int,
        n_trips:                 int,
        total_distance_km:       float,
        total_available_place_km: float,
        total_sold_place_km:     float,
        available_by_class_main: dict[str, int],
        sold_by_class_main:      dict[str, int],
) -> NormalisedMatrix:
    per_available_place_of_class:     dict[str, Breakdown] = {}
    per_sold_place_of_class:          dict[str, Breakdown] = {}
    per_available_place_km_of_class:  dict[str, Breakdown] = {}
    per_sold_place_km_of_class:       dict[str, Breakdown] = {}

    for cls, avail in available_by_class_main.items():
        sold = sold_by_class_main.get(cls, 0)
        per_available_place_of_class[cls]    = breakdown.per_available_place_of_class(avail)
        per_sold_place_of_class[cls]         = breakdown.per_sold_place_of_class(sold)
        per_available_place_km_of_class[cls] = breakdown.per_available_place_km_of_class(avail, total_distance_km)
        per_sold_place_km_of_class[cls]      = breakdown.per_sold_place_km_of_class(sold,  total_distance_km)

    return NormalisedMatrix(
        per_day                          = breakdown.per_day(),
        per_year                         = breakdown.per_year(operating_days_year),
        per_trip                         = breakdown.per_trip(n_trips),
        per_trip_km                      = breakdown.per_trip_km(total_distance_km),
        per_available_place_km           = breakdown.per_available_place_km(total_available_place_km),
        per_sold_place_km                = breakdown.per_sold_place_km(total_sold_place_km),
        per_available_place_of_class     = per_available_place_of_class,
        per_sold_place_of_class          = per_sold_place_of_class,
        per_available_place_km_of_class  = per_available_place_km_of_class,
        per_sold_place_km_of_class       = per_sold_place_km_of_class,
    )


# =============================================================================
# HELPERS
# =============================================================================

def _class_main_from_id(class_id: str) -> str:
    for main in ("Seat", "Couchette", "Sleeper", "Capsule", "Catering"):
        if main.lower() in class_id.lower():
            return main
    return class_id


def _places_by_class_main(composition: Composition) -> dict[str, int]:
    result: dict[str, int] = defaultdict(int)
    for cls_id, places in composition.places_by_class.items():
        result[_class_main_from_id(cls_id)] += places
    return dict(result)


def _density_by_class_main(composition: Composition) -> dict[str, float]:
    total_places:  dict[str, int]   = defaultdict(int)
    total_density: dict[str, float] = defaultdict(float)
    for cls_id, places in composition.places_by_class.items():
        main    = _class_main_from_id(cls_id)
        density = composition.density_by_class.get(cls_id, 1.0)
        total_places[main]  += places
        total_density[main] += density * places
    return {
        main: total_density[main] / total_places[main]
        for main in total_places if total_places[main] > 0
    }


def _stop_index(trip: Trip, stop_id: str) -> Optional[int]:
    """Return position of stop_id in trip.stop_times, or None."""
    for i, st in enumerate(trip.stop_times):
        if st.stop_id == stop_id:
            return i
    return None


def _legs_for_od(trip: Trip, origin_stop_id: str, dest_stop_id: str) -> list[CountryLeg]:
    """Return all CountryLegs covered by this OD pair."""
    i_from = _stop_index(trip, origin_stop_id)
    i_to   = _stop_index(trip, dest_stop_id)
    if i_from is None or i_to is None or i_from >= i_to:
        return []
    legs: list[CountryLeg] = []
    for seg in trip.path.segments[i_from:i_to]:
        legs.extend(seg.country_legs)
    return legs


def _stops_for_od(trip: Trip, origin_stop_id: str, dest_stop_id: str) -> list:
    """Return intermediate stops (excluding origin) up to and including destination."""
    i_from = _stop_index(trip, origin_stop_id)
    i_to   = _stop_index(trip, dest_stop_id)
    if i_from is None or i_to is None or i_from >= i_to:
        return []
    return trip.stop_times[i_from + 1: i_to + 1]


# =============================================================================
# TRIP BREAKDOWN BUILDER
# =============================================================================

def _build_trip_breakdown(
        trip:               Trip,
        composition:        Composition,
        tracks:             TrackInfraCollection,
        stop_infra:         StopInfraCollection,
        parking_eur:        float,
        trip_demand:        TripDemand,
        operating_days_year: int,
) -> Breakdown:
    """Build complete Breakdown (revenue + costs) for one trip."""
    steps: list[CalcStep] = []
    distance_km          = m_to_km(trip.stats.total_distance_m)
    total_driving_time_h = min_to_h(trip.stats.total_driving_time_min)
    places_main          = _places_by_class_main(composition)

    # --- Revenue from demand ---
    revenue_by_class = trip_demand.revenue_by_class()
    total_revenue    = trip_demand.total_revenue()
    places_sold      = trip_demand.places_sold_by_class()
    for od in trip_demand.od_pairs:
        steps.append(CalcStep("revenue_per_class", {
            "places_sold": float(od.places_sold),
            "avg_price":   od.avg_price,
        }, od.places_sold * od.avg_price))

    # --- Fixed / day ---
    loco_avail_days  = composition.loco_avail_per  * 365.0
    coach_avail_days = composition.coach_avail_per * 365.0

    loco_amort = (
        composition.purchase_loco_eur / (loco_avail_days * composition.loco_amort_years)
        if loco_avail_days > 0 and composition.loco_amort_years > 0 else 0.0
    )
    steps.append(CalcStep("loco_amortisation", {
        "purchase_loco_eur":  composition.purchase_loco_eur,
        "loco_avail_days":    loco_avail_days,
        "loco_amort_years":   float(composition.loco_amort_years),
    }, loco_amort))

    coach_amort = (
        composition.purchase_coach_eur / (coach_avail_days * composition.coach_amort_years)
        if coach_avail_days > 0 and composition.coach_amort_years > 0 else 0.0
    )
    steps.append(CalcStep("coach_amortisation", {
        "purchase_coach_eur": composition.purchase_coach_eur,
        "coach_avail_days":   coach_avail_days,
        "coach_amort_years":  float(composition.coach_amort_years),
    }, coach_amort))

    financing = (composition.purchase_loco_eur + composition.purchase_coach_eur) \
                 * composition.financing_quota_per / 365.0
    steps.append(CalcStep("financing", {
        "purchase_total_eur":   composition.purchase_loco_eur + composition.purchase_coach_eur,
        "financing_quota_per":  composition.financing_quota_per,
    }, financing))

    # --- Variable / km ---
    loco_maint  = composition.loco_maint_eur_km  * distance_km
    coach_maint = composition.coach_maint_eur_km * distance_km
    steps.append(CalcStep("loco_maintenance",  {"loco_maint_eur_km":  composition.loco_maint_eur_km,  "distance_km": distance_km}, loco_maint))
    steps.append(CalcStep("coach_maintenance", {"coach_maint_eur_km": composition.coach_maint_eur_km, "distance_km": distance_km}, coach_maint))

    # --- Variable / hour ---
    driver = composition.driver_costs_eur_h * (
        total_driving_time_h + min_to_h(composition.driver_overhead_min)
    )
    crew = composition.crew_costs_eur_h * (
        total_driving_time_h + min_to_h(composition.crew_overhead_min)
    )
    steps.append(CalcStep("driver_cost", {
        "driver_costs_eur_h":   composition.driver_costs_eur_h,
        "total_driving_time_h": total_driving_time_h,
        "driver_overhead_h":    min_to_h(composition.driver_overhead_min),
    }, driver))
    steps.append(CalcStep("crew_cost", {
        "crew_costs_eur_h":    composition.crew_costs_eur_h,
        "total_driving_time_h": total_driving_time_h,
        "crew_overhead_h":     min_to_h(composition.crew_overhead_min),
    }, crew))

    # --- Fixed overhead base ---
    op_cost_base = (
        composition.cleaning_services_eur_day
        + composition.shunting_eur_day
        + loco_maint + coach_maint + driver + crew
    )
    fix_overhead = op_cost_base * composition.fix_overhead_quota_per
    steps.append(CalcStep("fix_overhead", {
        "op_cost_base":           op_cost_base,
        "fix_overhead_quota_per": composition.fix_overhead_quota_per,
    }, fix_overhead))

    steps.append(CalcStep("cleaning", {"cleaning_services_eur_day": composition.cleaning_services_eur_day}, composition.cleaning_services_eur_day))
    steps.append(CalcStep("shunting",  {"shunting_eur_day": composition.shunting_eur_day}, composition.shunting_eur_day))
    steps.append(CalcStep("parking",   {"parking_eur": parking_eur}, parking_eur))

    # --- Infrastructure ---
    total_tac_eur    = 0.0
    total_energy_eur = 0.0
    for seg in trip.path.segments:
        for cl in seg.country_legs:
            track = tracks.get_or_default(cl.country_code)
            tac   = track.tac_eur_train_km * cl.distance_km
            enrg  = cl.energy_kwh * track.energy_price_eur_kwh
            total_tac_eur    += tac
            total_energy_eur += enrg
            steps.append(CalcStep("track_access_charge", {
                "distance_km":      cl.distance_km,
                "tac_eur_train_km": track.tac_eur_train_km,
            }, tac))
            steps.append(CalcStep("energy_cost", {
                "energy_kwh":           cl.energy_kwh,
                "energy_price_eur_kwh": track.energy_price_eur_kwh,
            }, enrg))

    station_charges = sum(
        (stop_infra.get(st.stop_id).stop_charge_eur
         if stop_infra.get(st.stop_id) else 0.0)
        for st in trip.stop_times
    )
    steps.append(CalcStep("station_charges", {"n_stops": float(len(trip.stop_times))}, station_charges))

    # --- Variable / ticket ---
    svc_by_class: dict[str, float] = {}
    for cls_main, sold in places_sold.items():
        svc_rate = composition.svc_stockings_eur_place.get(cls_main, 0.0)
        svc      = svc_rate * sold
        svc_by_class[cls_main] = svc
        steps.append(CalcStep("svc_stockings_per_class", {
            "svc_eur_place": svc_rate,
            "places_sold":   float(sold),
        }, svc))

    var_overhead = total_revenue * composition.var_overhead_per
    ebit_margin  = total_revenue * composition.ebit_margin_per
    steps.append(CalcStep("var_overhead", {"total_revenue": total_revenue, "var_overhead_per": composition.var_overhead_per}, var_overhead))
    steps.append(CalcStep("ebit_margin",  {"total_revenue": total_revenue, "ebit_margin_per":  composition.ebit_margin_per},  ebit_margin))

    return Breakdown(
        scope                  = "full",
        revenue_by_class       = revenue_by_class,
        total_revenue          = total_revenue,
        loco_amortisation      = loco_amort,
        coach_amortisation     = coach_amort,
        financing              = financing,
        fix_overhead           = fix_overhead,
        cleaning               = composition.cleaning_services_eur_day,
        shunting               = composition.shunting_eur_day,
        parking                = parking_eur,
        loco_maintenance       = loco_maint,
        coach_maintenance      = coach_maint,
        driver                 = driver,
        crew                   = crew,
        svc_stockings_by_class = svc_by_class,
        var_overhead           = var_overhead,
        track_access           = total_tac_eur,
        energy                 = total_energy_eur,
        station_charges        = station_charges,
        ebit_margin            = ebit_margin,
        calc_steps             = steps,
    )


# =============================================================================
# OD PAIR BREAKDOWN BUILDER
# =============================================================================

def _build_od_breakdown(
        od:          ODDemand,
        trip:        Trip,
        composition: Composition,
        tracks:      TrackInfraCollection,
        stop_infra:  StopInfraCollection,
        trip_bd:     Breakdown,
        trip_demand: TripDemand,
) -> Breakdown:
    """
    Build Breakdown for one OD pair by exact attribution and proportional allocation.

    Cost allocation rules:
      Infrastructure (TAC, energy, station charges): exact — only legs/stops traversed
      Variable/km (maintenance):   proportional to OD distance share of trip
      Variable/hour (driver, crew): proportional to OD driving-time share of trip
      Fixed/day (amort, financing, cleaning, overhead, shunting, parking):
          proportional to density-weighted sold-place-km share of trip
      Variable/ticket (svc_stockings): direct — OD places_sold
      Variable/ticket (var_overhead, ebit): proportional to OD revenue share
    """
    steps: list[CalcStep] = []
    od_legs  = _legs_for_od(trip, od.origin_stop_id, od.destination_stop_id)
    od_stops = _stops_for_od(trip, od.origin_stop_id, od.destination_stop_id)

    od_distance_km     = sum(cl.distance_km for cl in od_legs)
    od_driving_time_h  = min_to_h(sum(cl.driving_time_min for cl in od_legs))
    trip_distance_km   = m_to_km(trip.stats.total_distance_m)
    trip_driving_time_h = min_to_h(trip.stats.total_driving_time_min)

    # proportional shares
    dist_share  = od_distance_km   / trip_distance_km    if trip_distance_km    > 0 else 0.0
    time_share  = od_driving_time_h / trip_driving_time_h if trip_driving_time_h > 0 else 0.0

    # density-weighted sold-place-km share for fixed cost allocation
    density = _density_by_class_main(composition).get(od.class_main, 1.0)
    od_density_place_km = od.places_sold * density * od_distance_km
    trip_density_place_km = sum(
        trod.places_sold
        * _density_by_class_main(composition).get(trod.class_main, 1.0)
        * sum(cl.distance_km for cl in _legs_for_od(trip, trod.origin_stop_id, trod.destination_stop_id))
        for trod in trip_demand.od_pairs
    )
    fixed_share = od_density_place_km / trip_density_place_km if trip_density_place_km > 0 else 0.0

    # revenue share
    od_revenue   = od.places_sold * od.avg_price
    total_trip_rev = trip_demand.total_revenue()
    rev_share    = od_revenue / total_trip_rev if total_trip_rev > 0 else 0.0

    steps.append(CalcStep("revenue_per_class", {
        "places_sold": float(od.places_sold),
        "avg_price":   od.avg_price,
    }, od_revenue))

    # --- Infrastructure — exact ---
    od_tac_eur    = 0.0
    od_energy_eur = 0.0
    for cl in od_legs:
        track = tracks.get_or_default(cl.country_code)
        tac   = track.tac_eur_train_km * cl.distance_km
        enrg  = cl.energy_kwh * track.energy_price_eur_kwh
        od_tac_eur    += tac
        od_energy_eur += enrg
        steps.append(CalcStep("track_access_charge", {
            "distance_km":      cl.distance_km,
            "tac_eur_train_km": track.tac_eur_train_km,
        }, tac))
        steps.append(CalcStep("energy_cost", {
            "energy_kwh":           cl.energy_kwh,
            "energy_price_eur_kwh": track.energy_price_eur_kwh,
        }, enrg))

    od_station_charges = sum(
        (stop_infra.get(st.stop_id).stop_charge_eur
         if stop_infra.get(st.stop_id) else 0.0)
        for st in od_stops
    )
    steps.append(CalcStep("station_charges", {"n_stops": float(len(od_stops))}, od_station_charges))

    # --- Variable / km — by distance share ---
    od_loco_maint  = trip_bd.loco_maintenance  * dist_share
    od_coach_maint = trip_bd.coach_maintenance * dist_share
    steps.append(CalcStep("loco_maintenance",  {"trip_loco_maint":  trip_bd.loco_maintenance,  "dist_share": dist_share}, od_loco_maint))
    steps.append(CalcStep("coach_maintenance", {"trip_coach_maint": trip_bd.coach_maintenance, "dist_share": dist_share}, od_coach_maint))

    # --- Variable / hour — by driving time share ---
    od_driver = trip_bd.driver * time_share
    od_crew   = trip_bd.crew   * time_share
    steps.append(CalcStep("driver_cost", {"trip_driver": trip_bd.driver, "time_share": time_share}, od_driver))
    steps.append(CalcStep("crew_cost",   {"trip_crew":   trip_bd.crew,   "time_share": time_share}, od_crew))

    # --- Fixed / day — by density-weighted sold-place-km share ---
    od_loco_amort   = trip_bd.loco_amortisation  * fixed_share
    od_coach_amort  = trip_bd.coach_amortisation * fixed_share
    od_financing    = trip_bd.financing           * fixed_share
    od_fix_overhead = trip_bd.fix_overhead        * fixed_share
    od_cleaning     = trip_bd.cleaning            * fixed_share
    od_shunting     = trip_bd.shunting            * fixed_share
    od_parking      = trip_bd.parking             * fixed_share
    steps.append(CalcStep("loco_amortisation",  {"trip_loco_amort":  trip_bd.loco_amortisation,  "fixed_share": fixed_share}, od_loco_amort))
    steps.append(CalcStep("coach_amortisation", {"trip_coach_amort": trip_bd.coach_amortisation, "fixed_share": fixed_share}, od_coach_amort))
    steps.append(CalcStep("financing",          {"trip_financing":   trip_bd.financing,           "fixed_share": fixed_share}, od_financing))
    steps.append(CalcStep("fix_overhead",       {"trip_fix_overhead":trip_bd.fix_overhead,        "fixed_share": fixed_share}, od_fix_overhead))
    steps.append(CalcStep("cleaning",           {"trip_cleaning":    trip_bd.cleaning,            "fixed_share": fixed_share}, od_cleaning))
    steps.append(CalcStep("shunting",           {"trip_shunting":    trip_bd.shunting,            "fixed_share": fixed_share}, od_shunting))
    steps.append(CalcStep("parking",            {"trip_parking":     trip_bd.parking,             "fixed_share": fixed_share}, od_parking))

    # --- Variable / ticket — direct for svc, revenue share for overhead/ebit ---
    svc_rate  = composition.svc_stockings_eur_place.get(od.class_main, 0.0)
    od_svc    = svc_rate * od.places_sold
    od_var_oh = trip_bd.var_overhead * rev_share
    od_ebit   = trip_bd.ebit_margin  * rev_share
    steps.append(CalcStep("svc_stockings_per_class", {"svc_eur_place": svc_rate, "places_sold": float(od.places_sold)}, od_svc))
    steps.append(CalcStep("var_overhead", {"trip_var_overhead": trip_bd.var_overhead, "rev_share": rev_share}, od_var_oh))
    steps.append(CalcStep("ebit_margin",  {"trip_ebit_margin":  trip_bd.ebit_margin,  "rev_share": rev_share}, od_ebit))

    return Breakdown(
        scope                  = "od_pair",
        revenue_by_class       = {od.class_main: od_revenue},
        total_revenue          = od_revenue,
        loco_amortisation      = od_loco_amort,
        coach_amortisation     = od_coach_amort,
        financing              = od_financing,
        fix_overhead           = od_fix_overhead,
        cleaning               = od_cleaning,
        shunting               = od_shunting,
        parking                = od_parking,
        loco_maintenance       = od_loco_maint,
        coach_maintenance      = od_coach_maint,
        driver                 = od_driver,
        crew                   = od_crew,
        svc_stockings_by_class = {od.class_main: od_svc},
        var_overhead           = od_var_oh,
        track_access           = od_tac_eur,
        energy                 = od_energy_eur,
        station_charges        = od_station_charges,
        ebit_margin            = od_ebit,
        calc_steps             = steps,
    )


# =============================================================================
# COUNTRY BREAKDOWN BUILDER
# =============================================================================

def _build_country_breakdowns(
        route:  Route,
        tracks: TrackInfraCollection,
) -> dict[str, Breakdown]:
    """Infrastructure-only Breakdown per country, aggregated across all trips."""
    country_tac:    dict[str, float]            = defaultdict(float)
    country_energy: dict[str, float]            = defaultdict(float)
    country_dist:   dict[str, float]            = defaultdict(float)
    country_steps:  dict[str, list[CalcStep]]   = defaultdict(list)

    for trip in route.all_trips():
        for seg in trip.path.segments:
            for cl in seg.country_legs:
                track = tracks.get_or_default(cl.country_code)
                tac   = track.tac_eur_train_km * cl.distance_km
                enrg  = cl.energy_kwh * track.energy_price_eur_kwh
                country_tac[cl.country_code]    += tac
                country_energy[cl.country_code] += enrg
                country_dist[cl.country_code]   += cl.distance_km
                country_steps[cl.country_code].append(
                    CalcStep("track_access_charge", {
                        "distance_km":      cl.distance_km,
                        "tac_eur_train_km": track.tac_eur_train_km,
                    }, tac)
                )
                country_steps[cl.country_code].append(
                    CalcStep("energy_cost", {
                        "energy_kwh":           cl.energy_kwh,
                        "energy_price_eur_kwh": track.energy_price_eur_kwh,
                    }, enrg)
                )

    return {
        cc: Breakdown(
            scope        = "infrastructure_only",
            track_access = country_tac[cc],
            energy       = country_energy[cc],
            calc_steps   = country_steps[cc],
        )
        for cc in country_tac
    }


# =============================================================================
# SUM BREAKDOWNS
# =============================================================================

def _sum_breakdowns(bds: list[Breakdown], scope: str = "full") -> Breakdown:
    result = Breakdown(scope=scope)
    for bd in bds:
        for cls, rev in bd.revenue_by_class.items():
            result.revenue_by_class[cls] = result.revenue_by_class.get(cls, 0.0) + rev
        result.total_revenue          += bd.total_revenue
        result.loco_amortisation      += bd.loco_amortisation
        result.coach_amortisation     += bd.coach_amortisation
        result.financing              += bd.financing
        result.fix_overhead           += bd.fix_overhead
        result.cleaning               += bd.cleaning
        result.shunting               += bd.shunting
        result.parking                += bd.parking
        result.loco_maintenance       += bd.loco_maintenance
        result.coach_maintenance      += bd.coach_maintenance
        result.driver                 += bd.driver
        result.crew                   += bd.crew
        for cls, svc in bd.svc_stockings_by_class.items():
            result.svc_stockings_by_class[cls] = result.svc_stockings_by_class.get(cls, 0.0) + svc
        result.var_overhead           += bd.var_overhead
        result.track_access           += bd.track_access
        result.energy                 += bd.energy
        result.station_charges        += bd.station_charges
        result.ebit_margin            += bd.ebit_margin
        result.calc_steps             += bd.calc_steps
    return result


# =============================================================================
# OD PAIR RESULT
# =============================================================================

@dataclass
class ODPairResult:
    """Normalised matrix for one OD pair on one trip."""
    trip_id:            str
    origin_stop_id:     str
    destination_stop_id: str
    class_main:         str
    places_sold:        int
    matrix:             NormalisedMatrix

    def to_dict(self) -> dict:
        return {
            "trip_id":              self.trip_id,
            "origin_stop_id":       self.origin_stop_id,
            "destination_stop_id":  self.destination_stop_id,
            "class_main":           self.class_main,
            "places_sold":          self.places_sold,
            **self.matrix.to_dict(),
        }


# =============================================================================
# EVALUATION RESULT
# =============================================================================

@dataclass
class EvaluationResult:
    """Full route-level cost and revenue evaluation result."""

    calc_version:        str
    calc_formulas:       dict[str, CalcFormula]
    model_versions:      ModelVersions
    param_versions:      ParamVersions
    operating_days_year: int
    parking_eur:         float
    summary:             NormalisedMatrix
    by_trip:             list[NormalisedMatrix]
    by_country:          dict[str, NormalisedMatrix]
    by_od:               list[ODPairResult]

    def to_dict(self) -> dict:
        return {
            "calc_version":        self.calc_version,
            "calc_formulas":       {
                k: {"latex": v.latex, "description": v.description}
                for k, v in self.calc_formulas.items()
            },
            "model_versions":      self.model_versions.versions,
            "param_versions":      {
                k: {
                    "value":       v.value,
                    "version":     v.version,
                    "is_default":  v.is_default,
                    "source": {
                        "source_id":          v.source.source_id,
                        "source_description": v.source.source_description,
                        "source_url":         v.source.source_url,
                        "source_date":        str(v.source.source_date) if v.source.source_date else None,
                    } if v.source else None,
                    "description": v.description,
                }
                for k, v in self.param_versions.entries.items()
            },
            "operating_days_year": self.operating_days_year,
            "parking_eur":         self.parking_eur,
            "summary":             self.summary.to_dict(),
            "by_trip":             [t.to_dict() for t in self.by_trip],
            "by_country":          {cc: m.to_dict() for cc, m in self.by_country.items()},
            "by_od":               [od.to_dict() for od in self.by_od],
        }



# =============================================================================
# INDICATIVE FIGURES — composition comparison
# =============================================================================

def compute_indicative_figures(
        composition: Composition,
        ref:         CompositionReference,
        tracks:      TrackInfraCollection,
        stop_infra:  StopInfraCollection,
) -> IndicativeFigures:
    """
    Compute four indicative KPIs for a composition using a reference trip profile.
    Uses the same _build_trip_breakdown() logic as evaluate_route() — figures are
    therefore consistent with real evaluation results.

    A synthetic Trip is constructed from the reference parameters with a single
    country leg using country_code "__REF__" backed by a synthetic
    TrackInfrastructure built from the reference terrain score. TAC and energy
    price are taken from the EU-average default if available, else set to 0.

    Called only from data_loader_from_db.build_all_compositions().
    """
    from models.params import TrackInfrastructure, DefaultTrackInfra
    from dataclasses import dataclass as _dc, field as _field

    # synthetic track infrastructure for reference leg
    default_track = tracks.get_or_default("__REF__")
    ref_track = TrackInfrastructure(
        country_code           = "__REF__",
        tac_eur_train_km       = default_track.tac_eur_train_km    if default_track else 0.0,
        tac_src                = None,
        parking_eur_day        = default_track.parking_eur_day     if default_track else 0.0,
        parking_src            = None,
        energy_price_eur_kwh   = default_track.energy_price_eur_kwh if default_track else 0.18,
        energy_price_src       = None,
        terrain_score          = ref.ref_terrain_score,
        terrain_category       = "Reference",
        terrain_src            = None,
        hsr_allowed            = False,
        hsr_src                = None,
        min_boarding_time_min  = composition.min_boarding_time_min,
        min_boarding_src       = None,
        min_alighting_time_min = composition.min_alighting_time_min,
        min_alighting_src      = None,
        buffer_quota_per       = default_track.buffer_quota_per    if default_track else 0.07,
        buffer_src             = None,
    )

    # synthetic TrackInfraCollection with only the reference leg
    from models.params import TrackInfraCollection as _TIC
    ref_tracks = _TIC({"__REF__": ref_track})

    # synthetic StopInfraCollection (no station charges for reference)
    from models.params import StopInfraCollection as _SIC, StopInfrastructure as _SI
    ref_stop = _SI(
        stop_id="__REF_ORIGIN__", stop_name="Reference Origin",
        stop_country_code="__REF__", lat=0.0, lon=0.0,
        loc_src=None, stop_charge_eur=0.0, stop_charge_src=None,
    )
    ref_stop2 = _SI(
        stop_id="__REF_DEST__", stop_name="Reference Destination",
        stop_country_code="__REF__", lat=0.0, lon=0.0,
        loc_src=None, stop_charge_eur=0.0, stop_charge_src=None,
    )
    ref_stop_infra = _SIC({"__REF_ORIGIN__": ref_stop, "__REF_DEST__": ref_stop2})

    # compute energy for reference leg
    distance_m     = int(ref.ref_distance_km * 1000)
    driving_min    = int((ref.ref_distance_km / ref.ref_avg_speed_kmh) * 60)
    buffer_min     = int(driving_min * ref_track.buffer_quota_per)
    energy_kwh     = (
        composition.total_weight_t * ref.ref_distance_km * (
            composition.energy_factor_weight
            + composition.energy_factor_speed  * ref.ref_avg_speed_kmh ** 2
            + composition.energy_factor_terrain * ref.ref_terrain_score
        )
    )
    energy_per_km  = energy_kwh / ref.ref_distance_km if ref.ref_distance_km > 0 else 0.0

    ref_leg = CountryLeg(
        from_stop_id      = "__REF_ORIGIN__",
        to_stop_id        = "__REF_DEST__",
        country_code      = "__REF__",
        distance_m        = distance_m,
        driving_time_min  = driving_min,
        buffer_time_min   = buffer_min,
        energy_kwh        = energy_kwh,
        energy_kwh_per_km = energy_per_km,
    )

    ref_segment = TripSegment(
        from_stop_id = "__REF_ORIGIN__",
        to_stop_id   = "__REF_DEST__",
        geometry     = [],
        country_legs = [ref_leg],
    )

    ref_path = TripPath(
        shape     = {"type": "LineString", "coordinates": []},
        segments  = [ref_segment],
        countries = [],
    )

    ref_stats = TripStats(
        total_distance_m       = distance_m,
        total_driving_time_min = driving_min,
        total_time_min         = driving_min + buffer_min,
        total_energy_kwh       = energy_kwh,
    )

    ref_stop_times = [
        StopTime(stop_id="__REF_ORIGIN__", stop_name="Reference Origin",
                 lat=0.0, lon=0.0, stop_type="boarding",
                 arrival_time_min=None, departure_time_min=0, dwell_time_min=0),
        StopTime(stop_id="__REF_DEST__",   stop_name="Reference Destination",
                 lat=0.0, lon=0.0, stop_type="alighting",
                 arrival_time_min=driving_min + buffer_min, departure_time_min=None, dwell_time_min=0),
    ]

    # build a minimal Trip-like object (duck-typed for _build_trip_breakdown)
    @_dc
    class _RefTrip:
        stats:      TripStats
        path:       TripPath
        stop_times: list
        composition: object

        class _Comp:
            comp_id = "__REF__"
        composition = _Comp()

    ref_trip = _RefTrip(stats=ref_stats, path=ref_path, stop_times=ref_stop_times)
    ref_trip.composition = _RefTrip._Comp()

    # build demand from reference utilisation and fares
    places_main = _places_by_class_main(composition)
    od_pairs = []
    for cls_main, places in places_main.items():
        util  = ref.ref_utilization_by_class.get(cls_main, 0.0)
        fare  = ref.ref_avg_fare_by_class.get(cls_main, 0.0)
        sold  = int(places * util)
        od_pairs.append(ODDemand(
            origin_stop_id      = "__REF_ORIGIN__",
            destination_stop_id = "__REF_DEST__",
            class_main          = cls_main,
            places_sold         = sold,
            avg_price           = fare,
        ))

    ref_demand = TripDemand(trip_id="__REF__", od_pairs=od_pairs)

    # compute breakdown using the same function as evaluate_route()
    bd = _build_trip_breakdown(
        trip               = ref_trip,
        composition        = composition,
        tracks             = ref_tracks,
        stop_infra         = ref_stop_infra,
        parking_eur        = ref_track.parking_eur_day,
        trip_demand        = ref_demand,
        operating_days_year = ref.ref_operating_days,
    )

    # derive four KPIs
    density_main       = _density_by_class_main(composition)
    avail_place_km     = sum(
        places * density_main.get(cls, 1.0) * ref.ref_distance_km
        for cls, places in places_main.items()
    )
    total_places       = sum(places_main.values())
    avail_seat_km      = total_places * ref.ref_distance_km if total_places > 0 else 1.0

    sold_pax_km        = sum(
        od.places_sold * ref.ref_distance_km
        for od in od_pairs
    )

    cost_per_seat_km   = bd.total_cost / avail_seat_km    if avail_seat_km   > 0 else 0.0
    cost_per_place_km  = bd.total_cost / avail_place_km   if avail_place_km  > 0 else 0.0
    subsidy_per_pax_km = (bd.total_cost - bd.total_revenue) / sold_pax_km if sold_pax_km > 0 else 0.0

    # breakeven: revenue at current fares needed = total_cost
    # revenue = Σ(places × util × fare) × scale_factor → scale_factor = cost/revenue
    breakeven_load = (
        bd.total_cost / bd.total_revenue * sum(
            ref.ref_utilization_by_class.get(cls, 0.0)
            for cls in places_main
        ) / len(places_main)
        if bd.total_revenue > 0 and places_main else 0.0
    )
    breakeven_load = min(breakeven_load, 1.0)

    return IndicativeFigures(
        cost_eur_per_seat_km    = cost_per_seat_km,
        cost_eur_per_place_km   = cost_per_place_km,
        subsidy_eur_per_pax_km  = subsidy_per_pax_km,
        breakeven_load_factor   = breakeven_load,
    )


# =============================================================================
# EVALUATE ROUTE — entry point
# =============================================================================

def evaluate_route(
        route:               Route,
        route_demand:        RouteDemand,
        operating_days_year: int,
        loader,
) -> EvaluationResult:
    """
    Evaluate cost and revenue for all trips in a Route.

    Parameters
    ----------
    route : Route
        Fully constructed Route — physics only.
    route_demand : RouteDemand
        OD-pair demand: places sold and avg price per class per trip.
        For testing, populate with simple dummy values.
    operating_days_year : int
        Operating days per year for annual normalisation.
    loader : DBDataLoader
        Pre-initialised data loader.
    """
    tracks,     _ = loader.build_all_tracks()
    stop_infra, _ = loader.build_all_stops()

    # parking_eur — route-level
    parking_eur = 0.0
    for loc in route.parking_locations:
        track = tracks.get_or_default(loc.country_code)
        parking_eur += track.parking_eur_day

    trip_breakdowns: list[Breakdown]       = []
    trip_matrices:   list[NormalisedMatrix] = []
    compositions:    list[Composition]     = []
    od_results:      list[ODPairResult]    = []

    all_trips = route.all_trips()
    n_trips   = len(all_trips)

    for trip in all_trips:
        comp, _ = loader.build_composition(trip.composition.comp_id)
        compositions.append(comp)
        trip_demand   = route_demand.get_trip_demand(trip.trip_id)
        places_main   = _places_by_class_main(comp)
        density_main  = _density_by_class_main(comp)
        distance_km   = m_to_km(trip.stats.total_distance_m)

        # build full trip breakdown
        trip_bd = _build_trip_breakdown(
            trip, comp, tracks, stop_infra, parking_eur,
            trip_demand, operating_days_year,
        )
        trip_breakdowns.append(trip_bd)

        # available place-km for this trip
        avail_place_km = sum(
            places * density_main.get(cls, 1.0) * distance_km
            for cls, places in places_main.items()
        )

        # sold place-km for this trip
        sold_place_km = sum(
            od.places_sold
            * density_main.get(od.class_main, 1.0)
            * sum(cl.distance_km for cl in _legs_for_od(trip, od.origin_stop_id, od.destination_stop_id))
            for od in trip_demand.od_pairs
        )

        sold_main = trip_demand.places_sold_by_class()
        trip_matrix = _build_matrix(
            trip_bd, operating_days_year, 1,
            distance_km, avail_place_km, sold_place_km,
            places_main, sold_main,
        )
        trip_matrices.append(trip_matrix)

        # OD pair breakdowns
        for od in trip_demand.od_pairs:
            od_legs = _legs_for_od(trip, od.origin_stop_id, od.destination_stop_id)
            od_dist_km    = sum(cl.distance_km for cl in od_legs)
            od_avail_plkm = places_main.get(od.class_main, 0) * density_main.get(od.class_main, 1.0) * od_dist_km
            od_sold_plkm  = od.places_sold * density_main.get(od.class_main, 1.0) * od_dist_km

            od_bd = _build_od_breakdown(
                od, trip, comp, tracks, stop_infra, trip_bd, trip_demand,
            )
            od_matrix = _build_matrix(
                od_bd, operating_days_year, 1,
                od_dist_km, od_avail_plkm, od_sold_plkm,
                {od.class_main: places_main.get(od.class_main, 0)},
                {od.class_main: od.places_sold},
            )
            od_results.append(ODPairResult(
                trip_id             = trip.trip_id,
                origin_stop_id      = od.origin_stop_id,
                destination_stop_id = od.destination_stop_id,
                class_main          = od.class_main,
                places_sold         = od.places_sold,
                matrix              = od_matrix,
            ))

    # --- Route summary ---
    comp0         = compositions[0] if compositions else None
    places_main   = _places_by_class_main(comp0) if comp0 else {}
    density_main  = _density_by_class_main(comp0) if comp0 else {}
    total_dist_km = sum(m_to_km(t.stats.total_distance_m) for t in all_trips)

    total_avail_place_km = sum(
        places * density_main.get(cls, 1.0) * total_dist_km
        for cls, places in places_main.items()
    )
    total_sold_place_km = sum(
        od.places_sold
        * density_main.get(od.class_main, 1.0)
        * sum(
            cl.distance_km
            for cl in _legs_for_od(trip, od.origin_stop_id, od.destination_stop_id)
        )
        for trip, td in zip(all_trips, [route_demand.get_trip_demand(t.trip_id) for t in all_trips])
        for od in td.od_pairs
    )

    summary_bd     = _sum_breakdowns(trip_breakdowns, scope="full")
    total_sold_main: dict[str, int] = defaultdict(int)
    for td in [route_demand.get_trip_demand(t.trip_id) for t in all_trips]:
        for cls, sold in td.places_sold_by_class().items():
            total_sold_main[cls] += sold

    summary_matrix = _build_matrix(
        summary_bd, operating_days_year, n_trips,
        total_dist_km, total_avail_place_km, total_sold_place_km,
        places_main, dict(total_sold_main),
    )

    # --- Country ---
    country_raw = _build_country_breakdowns(route, tracks)
    by_country: dict[str, NormalisedMatrix] = {}
    for cc, bd in country_raw.items():
        cc_dist_km = sum(
            cl.distance_km
            for trip in all_trips
            for seg in trip.path.segments
            for cl in seg.country_legs
            if cl.country_code == cc
        )
        by_country[cc] = _build_matrix(
            bd, operating_days_year, n_trips,
            cc_dist_km, 0.0, 0.0, {}, {},
        )

    # extract model + param versions from first trip
    first_trip     = all_trips[0] if all_trips else None
    model_versions = first_trip.model_versions if first_trip else ModelVersions(versions={})
    param_versions = first_trip.param_versions  if first_trip else ParamVersions()

    logger.info(
        "evaluate_route: %d trips rev=%.0f€ cost=%.0f€ margin=%.0f€ "
        "(%d OD pairs, %d countries)",
        n_trips,
        summary_bd.total_revenue, summary_bd.total_cost, summary_bd.margin,
        len(od_results), len(by_country),
    )

    return EvaluationResult(
        calc_version        = CALC_VERSION,
        calc_formulas       = CALC_FORMULAS,
        model_versions      = model_versions,
        param_versions      = param_versions,
        operating_days_year = operating_days_year,
        parking_eur         = parking_eur,
        summary             = summary_matrix,
        by_trip             = trip_matrices,
        by_country          = by_country,
        by_od               = od_results,
    )