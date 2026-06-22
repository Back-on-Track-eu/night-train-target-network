"""
calc.py
=======
Night Train Cost and Revenue Evaluation Model.

Unit conventions (internal)
----------------------------
  Distance : metres  (_m)   — converted to km for cost calc
  Duration : minutes (_min) — converted to hours for cost calc
  Energy   : kWh     (_kwh)
  Cost     : EUR     (_eur)

Separation of concerns
-----------------------
This module owns ALL monetary calculations for the route evaluation.
The Trip/Route objects carry physics only (distances, times, energy kWh).
calc.py multiplies those by cost parameters from infra + composition params.

Cost computations per trip:
  TAC           = sum(country_leg.distance_km × infra.tac_eur_train_km)
  energy_eur    = sum(country_leg.energy_kwh × infra.energy_price_eur_kwh)
  station_chg   = sum(stop.stop_charge_eur for all stops)
  parking_eur   = sum(infra.parking_eur_day for each parking location)

TODO: once params.py uses _min units, remove × 60 / 60 conversions.

CALC_VERSION returned in every POST /api/cost-rev-calc/calc response.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from models.cost_rev_eval.version import CALC_VERSION
from models.params import InfraCollection, StopCollection
from models.route.route import Route
from models.route.trip import Trip

logger = logging.getLogger(__name__)


# =============================================================================
# UNIT HELPERS
# =============================================================================

def _m_to_km(metres: int) -> float:
    return metres / 1000.0


def _min_to_h(minutes: int) -> float:
    return minutes / 60.0


# =============================================================================
# REVENUE BREAKDOWN
# =============================================================================

@dataclass
class RevenueBreakdown:
    """Revenue breakdown by ticket class for one trip."""

    utilization_seat:      float = 0.0
    utilization_couchette: float = 0.0
    utilization_sleeper:   float = 0.0
    avg_fare_seat:         float = 0.0
    avg_fare_couchette:    float = 0.0
    avg_fare_sleeper:      float = 0.0
    passengers_seat:       float = 0.0
    passengers_couchette:  float = 0.0
    passengers_sleeper:    float = 0.0
    revenue_seat:          float = 0.0
    revenue_couchette:     float = 0.0
    revenue_sleeper:       float = 0.0

    @property
    def total_passengers(self) -> float:
        return self.passengers_seat + self.passengers_couchette + self.passengers_sleeper

    @property
    def total(self) -> float:
        return self.revenue_seat + self.revenue_couchette + self.revenue_sleeper

    @classmethod
    def calculate(
            cls,
            seats_total:           int,
            couchettes_total:      int,
            sleepers_total:        int,
            utilization_seat:      float,
            utilization_couchette: float,
            utilization_sleeper:   float,
            avg_fare_seat:         float,
            avg_fare_couchette:    float,
            avg_fare_sleeper:      float,
    ) -> "RevenueBreakdown":
        pax_seat      = seats_total      * utilization_seat
        pax_couchette = couchettes_total * utilization_couchette
        pax_sleeper   = sleepers_total   * utilization_sleeper
        return cls(
            utilization_seat      = utilization_seat,
            utilization_couchette = utilization_couchette,
            utilization_sleeper   = utilization_sleeper,
            avg_fare_seat         = avg_fare_seat,
            avg_fare_couchette    = avg_fare_couchette,
            avg_fare_sleeper      = avg_fare_sleeper,
            passengers_seat       = pax_seat,
            passengers_couchette  = pax_couchette,
            passengers_sleeper    = pax_sleeper,
            revenue_seat          = pax_seat      * avg_fare_seat,
            revenue_couchette     = pax_couchette * avg_fare_couchette,
            revenue_sleeper       = pax_sleeper   * avg_fare_sleeper,
        )

    def to_dict(self) -> dict:
        return {
            "utilization_seat":      self.utilization_seat,
            "utilization_couchette": self.utilization_couchette,
            "utilization_sleeper":   self.utilization_sleeper,
            "avg_fare_seat":         self.avg_fare_seat,
            "avg_fare_couchette":    self.avg_fare_couchette,
            "avg_fare_sleeper":      self.avg_fare_sleeper,
            "passengers_seat":       self.passengers_seat,
            "passengers_couchette":  self.passengers_couchette,
            "passengers_sleeper":    self.passengers_sleeper,
            "revenue_seat":          self.revenue_seat,
            "revenue_couchette":     self.revenue_couchette,
            "revenue_sleeper":       self.revenue_sleeper,
            "total":                 self.total,
        }


# =============================================================================
# COST BREAKDOWN
# =============================================================================

@dataclass
class CostBreakdown:
    """Full cost breakdown for one trip. All values in EUR."""

    loco_amortisation:       float = 0.0
    coach_amortisation:      float = 0.0
    financing:               float = 0.0
    fix_overhead:            float = 0.0
    cleaning_services:       float = 0.0
    shunting:                float = 0.0
    parking:                 float = 0.0
    svc_stockings_seat:      float = 0.0
    svc_stockings_couchette: float = 0.0
    svc_stockings_sleeper:   float = 0.0
    var_overhead:            float = 0.0
    loco_maintenance:        float = 0.0
    coach_maintenance:       float = 0.0
    driver:                  float = 0.0
    crew:                    float = 0.0
    track_access:            float = 0.0
    energy:                  float = 0.0
    station_charges:         float = 0.0
    ebit_margin:             float = 0.0

    @property
    def fixed_day_total(self) -> float:
        return (self.loco_amortisation + self.coach_amortisation
                + self.financing + self.fix_overhead
                + self.cleaning_services + self.shunting + self.parking)

    @property
    def variable_ticket_total(self) -> float:
        return (self.svc_stockings_seat + self.svc_stockings_couchette
                + self.svc_stockings_sleeper + self.var_overhead)

    @property
    def variable_km_total(self) -> float:
        return self.loco_maintenance + self.coach_maintenance

    @property
    def variable_hour_total(self) -> float:
        return self.driver + self.crew

    @property
    def infra_total(self) -> float:
        return self.track_access + self.energy + self.station_charges

    @property
    def total(self) -> float:
        return (self.fixed_day_total + self.variable_ticket_total
                + self.variable_km_total + self.variable_hour_total
                + self.infra_total + self.ebit_margin)

    @classmethod
    def calculate(
            cls,
            purchase_loco_eur:         float,
            purchase_coach_eur:        float,
            loco_avail_per:            float,
            coach_avail_per:           float,
            loco_amort_years:          float,
            coach_amort_years:         float,
            financing_quota_per:       float,
            fix_overhead_quota_per:    float,
            cleaning_services_eur_day: float,
            shunting_eur_day:          float,
            parking_eur:               float,
            loco_maint_eur_km:         float,
            coach_maint_eur_km:        float,
            total_distance_m:          int,
            driver_costs_eur_h:        float,
            crew_costs_eur_h:          float,
            driver_overhead_h:         float,   # TODO: _min once params updated
            crew_overhead_h:           float,   # TODO: _min once params updated
            total_driving_time_min:    int,
            total_tac_eur:             float,
            total_energy_eur:          float,
            station_charges_eur:       float,
            svc_stockings_seat_per:    float,
            svc_stockings_couchette_per: float,
            svc_stockings_sleeper_per: float,
            var_overhead_per:          float,
            revenue_seat:              float,
            revenue_couchette:         float,
            revenue_sleeper:           float,
            total_revenue:             float,
            ebit_margin_per:           float,
    ) -> "CostBreakdown":
        total_distance_km    = _m_to_km(total_distance_m)
        total_driving_time_h = _min_to_h(total_driving_time_min)

        loco_avail_days  = loco_avail_per  * 365.0
        coach_avail_days = coach_avail_per * 365.0

        loco_amort = (
            purchase_loco_eur / (loco_avail_days * loco_amort_years)
            if loco_avail_days > 0 and loco_amort_years > 0 else 0.0
        )
        coach_amort = (
            purchase_coach_eur / (coach_avail_days * coach_amort_years)
            if coach_avail_days > 0 and coach_amort_years > 0 else 0.0
        )
        financing = (purchase_loco_eur + purchase_coach_eur) * financing_quota_per / 365.0

        op_cost_base = (
            cleaning_services_eur_day
            + shunting_eur_day
            + loco_maint_eur_km  * total_distance_km
            + coach_maint_eur_km * total_distance_km
            + driver_costs_eur_h * (total_driving_time_h + driver_overhead_h)
            + crew_costs_eur_h   * (total_driving_time_h + crew_overhead_h)
        )
        fix_overhead = op_cost_base * fix_overhead_quota_per

        loco_maint  = loco_maint_eur_km  * total_distance_km
        coach_maint = coach_maint_eur_km * total_distance_km
        driver      = driver_costs_eur_h * (total_driving_time_h + driver_overhead_h)
        crew        = crew_costs_eur_h   * (total_driving_time_h + crew_overhead_h)

        svc_seat      = revenue_seat      * svc_stockings_seat_per
        svc_couchette = revenue_couchette * svc_stockings_couchette_per
        svc_sleeper   = revenue_sleeper   * svc_stockings_sleeper_per
        var_overhead  = total_revenue     * var_overhead_per
        ebit_margin   = total_revenue     * ebit_margin_per

        return cls(
            loco_amortisation       = loco_amort,
            coach_amortisation      = coach_amort,
            financing               = financing,
            fix_overhead            = fix_overhead,
            cleaning_services       = cleaning_services_eur_day,
            shunting                = shunting_eur_day,
            parking                 = parking_eur,
            svc_stockings_seat      = svc_seat,
            svc_stockings_couchette = svc_couchette,
            svc_stockings_sleeper   = svc_sleeper,
            var_overhead            = var_overhead,
            loco_maintenance        = loco_maint,
            coach_maintenance       = coach_maint,
            driver                  = driver,
            crew                    = crew,
            track_access            = total_tac_eur,
            energy                  = total_energy_eur,
            station_charges         = station_charges_eur,
            ebit_margin             = ebit_margin,
        )

    def to_dict(self) -> dict:
        return {
            "loco_amortisation":       self.loco_amortisation,
            "coach_amortisation":      self.coach_amortisation,
            "financing":               self.financing,
            "fix_overhead":            self.fix_overhead,
            "cleaning_services":       self.cleaning_services,
            "shunting":                self.shunting,
            "parking":                 self.parking,
            "fixed_day_total":         self.fixed_day_total,
            "loco_maintenance":        self.loco_maintenance,
            "coach_maintenance":       self.coach_maintenance,
            "variable_km_total":       self.variable_km_total,
            "driver":                  self.driver,
            "crew":                    self.crew,
            "variable_hour_total":     self.variable_hour_total,
            "svc_stockings_seat":      self.svc_stockings_seat,
            "svc_stockings_couchette": self.svc_stockings_couchette,
            "svc_stockings_sleeper":   self.svc_stockings_sleeper,
            "var_overhead":            self.var_overhead,
            "variable_ticket_total":   self.variable_ticket_total,
            "track_access":            self.track_access,
            "energy":                  self.energy,
            "station_charges":         self.station_charges,
            "infra_total":             self.infra_total,
            "ebit_margin":             self.ebit_margin,
            "total":                   self.total,
        }


# =============================================================================
# CLASS COST ALLOCATION
# =============================================================================

@dataclass
class ClassCostAllocation:
    """Cost allocated per ticket class based on coach space consumption."""

    space_units_seat:      float = 0.0
    space_units_couchette: float = 0.0
    space_units_sleeper:   float = 0.0
    cost_seat_class:       float = 0.0
    cost_couchette_class:  float = 0.0
    cost_sleeper_class:    float = 0.0
    cost_per_seat:         float = 0.0
    cost_per_couchette:    float = 0.0
    cost_per_sleeper:      float = 0.0

    @property
    def total_space_units(self) -> float:
        return (self.space_units_seat + self.space_units_couchette
                + self.space_units_sleeper)

    @classmethod
    def calculate(
            cls,
            total_cost:        float,
            seats_total:       int,
            couchettes_total:  int,
            sleepers_total:    int,
            seat_density:      float,
            couchette_density: float,
            sleeper_density:   float,
            comp_id:           str = "",
    ) -> "ClassCostAllocation":
        seat_units      = seats_total      * seat_density
        couchette_units = couchettes_total * couchette_density
        sleeper_units   = sleepers_total   * sleeper_density
        total_units     = seat_units + couchette_units + sleeper_units

        if total_units == 0:
            logger.warning(
                "Total space units are zero for '%s' — allocation skipped.", comp_id
            )
            return cls()

        cost_seat      = total_cost * seat_units      / total_units
        cost_couchette = total_cost * couchette_units / total_units
        cost_sleeper   = total_cost * sleeper_units   / total_units

        return cls(
            space_units_seat      = seat_units,
            space_units_couchette = couchette_units,
            space_units_sleeper   = sleeper_units,
            cost_seat_class       = cost_seat,
            cost_couchette_class  = cost_couchette,
            cost_sleeper_class    = cost_sleeper,
            cost_per_seat         = cost_seat      / seats_total      if seats_total      > 0 else 0.0,
            cost_per_couchette    = cost_couchette / couchettes_total if couchettes_total > 0 else 0.0,
            cost_per_sleeper      = cost_sleeper   / sleepers_total   if sleepers_total   > 0 else 0.0,
        )

    def to_dict(self) -> dict:
        return {
            "space_units_seat":      self.space_units_seat,
            "space_units_couchette": self.space_units_couchette,
            "space_units_sleeper":   self.space_units_sleeper,
            "total_space_units":     self.total_space_units,
            "cost_seat_class":       self.cost_seat_class,
            "cost_couchette_class":  self.cost_couchette_class,
            "cost_sleeper_class":    self.cost_sleeper_class,
            "cost_per_seat":         self.cost_per_seat,
            "cost_per_couchette":    self.cost_per_couchette,
            "cost_per_sleeper":      self.cost_per_sleeper,
        }


# =============================================================================
# TRIP RESULT
# =============================================================================

@dataclass
class TripResult:
    """Cost and revenue evaluation result for one trip."""

    trip_id:             str
    direction:           int
    revenue:             RevenueBreakdown
    cost:                CostBreakdown
    allocation:          ClassCostAllocation
    capacity_seats:      int   = 0
    capacity_couchettes: int   = 0
    capacity_sleepers:   int   = 0
    total_distance_m:    int   = 0
    total_driving_time_min: int = 0

    @property
    def margin(self) -> float:
        return self.revenue.total - self.cost.total

    @property
    def margin_pct(self) -> float:
        return self.margin / self.revenue.total if self.revenue.total > 0 else 0.0

    def annual_margin(self, operating_days_year: int) -> float:
        return self.margin * operating_days_year

    @property
    def cost_per_seat_km(self) -> float:
        total_capacity = self.capacity_seats + self.capacity_couchettes + self.capacity_sleepers
        seat_km = total_capacity * _m_to_km(self.total_distance_m)
        return self.cost.total / seat_km if seat_km > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "trip_id":      self.trip_id,
            "direction_id": self.direction,
            "capacity": {
                "seats":      self.capacity_seats,
                "couchettes": self.capacity_couchettes,
                "sleepers":   self.capacity_sleepers,
            },
            "revenue":          self.revenue.to_dict(),
            "cost":             self.cost.to_dict(),
            "allocation":       self.allocation.to_dict(),
            "margin":           self.margin,
            "margin_pct":       self.margin_pct,
            "cost_per_seat_km": self.cost_per_seat_km,
        }


# =============================================================================
# EVALUATION RESULT
# =============================================================================

@dataclass
class EvaluationResult:
    """Route-level cost and revenue evaluation result."""

    calc_version:        str
    operating_days_year: int
    parking_eur:         float
    trip_results:        list[TripResult]

    @property
    def total_revenue(self) -> float:
        return sum(tr.revenue.total for tr in self.trip_results)

    @property
    def total_cost(self) -> float:
        return sum(tr.cost.total for tr in self.trip_results)

    @property
    def total_margin(self) -> float:
        return self.total_revenue - self.total_cost

    @property
    def total_margin_pct(self) -> float:
        return self.total_margin / self.total_revenue if self.total_revenue > 0 else 0.0

    @property
    def annual_margin(self) -> float:
        return self.total_margin * self.operating_days_year

    def get_trip_result(self, trip_id: str) -> Optional[TripResult]:
        for tr in self.trip_results:
            if tr.trip_id == trip_id:
                return tr
        return None

    def get_trip_result_by_direction(self, direction: int) -> Optional[TripResult]:
        for tr in self.trip_results:
            if tr.direction == direction:
                return tr
        return None

    def to_dict(self) -> dict:
        return {
            "calc_version":        self.calc_version,
            "operating_days_year": self.operating_days_year,
            "parking_eur":         self.parking_eur,
            "summary": {
                "total_revenue":    self.total_revenue,
                "total_cost":       self.total_cost,
                "total_margin":     self.total_margin,
                "total_margin_pct": self.total_margin_pct,
                "annual_margin":    self.annual_margin,
            },
            "trip_results": [tr.to_dict() for tr in self.trip_results],
        }


# =============================================================================
# EVALUATE ROUTE — entry point
# =============================================================================

# Representative constants for avg_op_cost_per_km display in compositions endpoint
# !! DISPLAY HEURISTIC ONLY — not used in cost calculation !!
_AVG_SPEED_KMH     = 90.0
_AVG_TRIP_HOURS    = 10.0
_OPERATING_DAYS    = 360


def evaluate_route(
        route:                    Route,
        utilization_seat:         float,
        utilization_couchette:    float,
        utilization_sleeper:      float,
        avg_fare_seat:            float,
        avg_fare_couchette:       float,
        avg_fare_sleeper:         float,
        operating_days_year:      int,
        loader,
) -> EvaluationResult:
    """
    Evaluate cost and revenue for all trips in a Route.

    Loads infra + stop params from DB to compute all monetary values:
      - TAC per country leg
      - Energy cost per country leg
      - Station charges for all stops
      - Parking from parking_locations × infra.parking_eur_day

    Parameters
    ----------
    route : Route
        Fully constructed Route — physics only, no monetary values.
    utilization_seat/couchette/sleeper : float
        Fraction of capacity filled (0.0–1.0).
    avg_fare_seat/couchette/sleeper : float
        Average ticket price per class in EUR.
    operating_days_year : int
        Operating days per year for annual margin.
    loader : DBDataLoader
        Pre-initialised data loader.
    """
    # load cost params
    infra = loader.build_all_infra()

    # compute parking_eur from parking_locations × infra
    parking_eur = 0.0
    for loc in route.parking_locations:
        ip = infra.get_or_default(loc.country_code)
        if ip:
            parking_eur += ip.parking_eur_day
        else:
            logger.warning(
                "No infra params for parking location '%s' (%s) — parking set to 0.",
                loc.stop_id, loc.country_code,
            )

    trip_results: list[TripResult] = []

    for trip in route.all_trips():
        # load full composition (cost fields) + stop params for this trip
        composition = loader.build_composition(trip.composition.comp_id)
        stop_ids    = [st.stop_id for st in trip.stop_times]
        stop_params = loader.build_all_stop_params(stop_ids)

        # compute infra costs from country legs × infra params
        total_tac_eur    = 0.0
        total_energy_eur = 0.0
        for seg in trip.path.segments:
            for cl in seg.country_legs:
                ip = infra.get_or_default(cl.country_code)
                if ip:
                    total_tac_eur    += ip.tac_eur_train_km * cl.distance_km
                    total_energy_eur += cl.energy_kwh * ip.energy_price_eur_kwh
                else:
                    logger.warning(
                        "No infra params for '%s' — TAC and energy cost set to 0.",
                        cl.country_code,
                    )

        # station charges for all stops
        station_charges_eur = sum(
            stop_params.get_charge(st.stop_id)
            for st in trip.stop_times
        )

        revenue = RevenueBreakdown.calculate(
            seats_total           = composition.seats_total,
            couchettes_total      = composition.couchettes_total,
            sleepers_total        = composition.sleepers_total,
            utilization_seat      = utilization_seat,
            utilization_couchette = utilization_couchette,
            utilization_sleeper   = utilization_sleeper,
            avg_fare_seat         = avg_fare_seat,
            avg_fare_couchette    = avg_fare_couchette,
            avg_fare_sleeper      = avg_fare_sleeper,
        )

        cost = CostBreakdown.calculate(
            purchase_loco_eur            = composition.purchase_loco_eur,
            purchase_coach_eur           = composition.purchase_coach_eur,
            loco_avail_per               = composition.loco_avail_per,
            coach_avail_per              = composition.coach_avail_per,
            loco_amort_years             = composition.loco_amort_years,
            coach_amort_years            = composition.coach_amort_years,
            financing_quota_per          = composition.financing_quota_per,
            fix_overhead_quota_per       = composition.fix_overhead_quota_per,
            cleaning_services_eur_day    = composition.cleaning_services_eur_day,
            shunting_eur_day             = composition.shunting_eur_day,
            parking_eur                  = parking_eur,
            loco_maint_eur_km            = composition.loco_maint_eur_km,
            coach_maint_eur_km           = composition.coach_maint_eur_km,
            total_distance_m             = trip.stats.total_distance_m,
            driver_costs_eur_h           = composition.driver_costs_eur_h,
            crew_costs_eur_h             = composition.crew_costs_eur_h,
            driver_overhead_h            = composition.driver_overhead_h,
            crew_overhead_h              = composition.crew_overhead_h,
            total_driving_time_min       = trip.stats.total_driving_time_min,
            total_tac_eur                = total_tac_eur,
            total_energy_eur             = total_energy_eur,
            station_charges_eur          = station_charges_eur,
            svc_stockings_seat_per       = composition.svc_stockings_seat_per,
            svc_stockings_couchette_per  = composition.svc_stockings_couchette_per,
            svc_stockings_sleeper_per    = composition.svc_stockings_sleeper_per,
            var_overhead_per             = composition.var_overhead_per,
            revenue_seat                 = revenue.revenue_seat,
            revenue_couchette            = revenue.revenue_couchette,
            revenue_sleeper              = revenue.revenue_sleeper,
            total_revenue                = revenue.total,
            ebit_margin_per              = composition.ebit_margin_per,
        )

        allocation = ClassCostAllocation.calculate(
            total_cost        = cost.total,
            seats_total       = composition.seats_total,
            couchettes_total  = composition.couchettes_total,
            sleepers_total    = composition.sleepers_total,
            seat_density      = composition.seat_density,
            couchette_density = composition.couchette_density,
            sleeper_density   = composition.sleeper_density,
            comp_id           = composition.comp_id,
        )

        trip_results.append(TripResult(
            trip_id               = trip.trip_id,
            direction             = trip.direction,
            revenue               = revenue,
            cost                  = cost,
            allocation            = allocation,
            capacity_seats        = composition.seats_total,
            capacity_couchettes   = composition.couchettes_total,
            capacity_sleepers     = composition.sleepers_total,
            total_distance_m      = trip.stats.total_distance_m,
            total_driving_time_min = trip.stats.total_driving_time_min,
        ))

        logger.info(
            "evaluate_route trip=%s dir=%d rev=%.0f€ cost=%.0f€ margin=%.0f€",
            trip.trip_id, trip.direction,
            revenue.total, cost.total, revenue.total - cost.total,
        )

    return EvaluationResult(
        calc_version        = CALC_VERSION,
        operating_days_year = operating_days_year,
        parking_eur         = parking_eur,
        trip_results        = trip_results,
    )