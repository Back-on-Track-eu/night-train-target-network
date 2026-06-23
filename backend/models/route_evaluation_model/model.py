"""
model.py
========
Night train cost and revenue model classes.

Each class owns its calculation logic via a calculate() classmethod.
All calculate() methods accept only scalar inputs — no RouteResult,
no collections. run_model.py extracts all needed values and passes
them as plain floats.

Classes:
    RevenueBreakdown      — revenue by ticket class
    CostBreakdown         — full cost breakdown by category
    ClassCostAllocation   — cost allocated per ticket class and per berth
    ModelResult           — top-level result combining all three
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# =============================================================================
# REVENUE BREAKDOWN
# =============================================================================


@dataclass
class RevenueBreakdown:
    """
    Revenue breakdown by ticket class.
    passengers = capacity × utilization
    revenue    = passengers × avg_fare
    """

    # runtime inputs
    utilization_seat: float = 0.0
    utilization_couchette: float = 0.0
    utilization_sleeper: float = 0.0
    avg_fare_seat: float = 0.0
    avg_fare_couchette: float = 0.0
    avg_fare_sleeper: float = 0.0

    # derived
    passengers_seat: float = 0.0
    passengers_couchette: float = 0.0
    passengers_sleeper: float = 0.0
    revenue_seat: float = 0.0
    revenue_couchette: float = 0.0
    revenue_sleeper: float = 0.0

    @property
    def total_passengers(self) -> float:
        return (
            self.passengers_seat + self.passengers_couchette + self.passengers_sleeper
        )

    @property
    def total(self) -> float:
        return self.revenue_seat + self.revenue_couchette + self.revenue_sleeper

    @classmethod
    def calculate(
        cls,
        seats_total: int,
        couchettes_total: int,
        sleepers_total: int,
        utilization_seat: float,
        utilization_couchette: float,
        utilization_sleeper: float,
        avg_fare_seat: float,
        avg_fare_couchette: float,
        avg_fare_sleeper: float,
    ) -> "RevenueBreakdown":
        pax_seat = seats_total * utilization_seat
        pax_couchette = couchettes_total * utilization_couchette
        pax_sleeper = sleepers_total * utilization_sleeper

        return cls(
            utilization_seat=utilization_seat,
            utilization_couchette=utilization_couchette,
            utilization_sleeper=utilization_sleeper,
            avg_fare_seat=avg_fare_seat,
            avg_fare_couchette=avg_fare_couchette,
            avg_fare_sleeper=avg_fare_sleeper,
            passengers_seat=pax_seat,
            passengers_couchette=pax_couchette,
            passengers_sleeper=pax_sleeper,
            revenue_seat=pax_seat * avg_fare_seat,
            revenue_couchette=pax_couchette * avg_fare_couchette,
            revenue_sleeper=pax_sleeper * avg_fare_sleeper,
        )


# =============================================================================
# COST BREAKDOWN
# =============================================================================


@dataclass
class CostBreakdown:
    """
    Full cost breakdown for one trip. All values in EUR.

    Fixed per operating day:
        loco_amortisation       — loco purchase / (avail_days × amort_years)
        coach_amortisation      — coach purchase / (avail_days × amort_years)
        financing               — (loco + coach) × financing_quota / 365
        fix_overhead            — % of operating costs (cleaning, shunting,
                                  maint/km, staff/h) — excludes capital costs
                                  (amortisation, financing)
        cleaning_services       — daily cleaning and service preparation
        shunting                — daily shunting operations
        parking                 — daily stabling fee at origin/destination

    Variable per ticket sold:
        svc_stockings_seat      — % of seat revenue
        svc_stockings_couchette — % of couchette revenue
        svc_stockings_sleeper   — % of sleeper revenue
        var_overhead            — % of total revenue

    Variable per km:
        loco_maintenance        — loco maint/km × total km
        coach_maintenance       — coach maint/km × total km

    Variable per hour:
        driver                  — driver cost × billable hours
        crew                    — crew cost × billable hours

    Infrastructure variable:
        track_access            — TAC sum over all country legs
        energy                  — energy cost sum over all country legs
        station_charges         — sum of stop charges at intermediate stops

    Target margin:
        ebit_margin             — required EBIT % × revenue
    """

    # fixed per day
    loco_amortisation: float = 0.0
    coach_amortisation: float = 0.0
    financing: float = 0.0
    fix_overhead: float = 0.0
    cleaning_services: float = 0.0
    shunting: float = 0.0
    parking: float = 0.0

    # variable per ticket sold
    svc_stockings_seat: float = 0.0
    svc_stockings_couchette: float = 0.0
    svc_stockings_sleeper: float = 0.0
    var_overhead: float = 0.0

    # variable per km
    loco_maintenance: float = 0.0
    coach_maintenance: float = 0.0

    # variable per hour
    driver: float = 0.0
    crew: float = 0.0

    # infrastructure
    track_access: float = 0.0
    energy: float = 0.0
    station_charges: float = 0.0

    # target margin
    ebit_margin: float = 0.0

    @property
    def fixed_day_total(self) -> float:
        return (
            self.loco_amortisation
            + self.coach_amortisation
            + self.financing
            + self.fix_overhead
            + self.cleaning_services
            + self.shunting
            + self.parking
        )

    @property
    def variable_ticket_total(self) -> float:
        return (
            self.svc_stockings_seat
            + self.svc_stockings_couchette
            + self.svc_stockings_sleeper
            + self.var_overhead
        )

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
        return (
            self.fixed_day_total
            + self.variable_ticket_total
            + self.variable_km_total
            + self.variable_hour_total
            + self.infra_total
            + self.ebit_margin
        )

    @classmethod
    def calculate(
        cls,
        # --- fixed per day ---
        purchase_loco_eur: float,
        purchase_coach_eur: float,
        loco_avail_per: float,
        coach_avail_per: float,
        loco_amort_years: float,
        coach_amort_years: float,
        financing_quota_per: float,
        fix_overhead_quota_per: float,
        cleaning_services_eur_day: float,
        shunting_eur_day: float,
        parking_eur: float,
        # --- variable per km ---
        loco_maint_eur_km: float,
        coach_maint_eur_km: float,
        total_distance_km: float,
        # --- variable per hour ---
        driver_costs_eur_h: float,
        crew_costs_eur_h: float,
        driver_overhead_h: float,
        crew_overhead_h: float,
        total_driving_time_h: float,
        # --- infrastructure ---
        total_tac_eur: float,
        total_energy_eur: float,
        station_charges_eur: float,
        # --- variable per ticket ---
        svc_stockings_seat_per: float,
        svc_stockings_couchette_per: float,
        svc_stockings_sleeper_per: float,
        var_overhead_per: float,
        revenue_seat: float,
        revenue_couchette: float,
        revenue_sleeper: float,
        total_revenue: float,
        # --- ebit ---
        ebit_margin_per: float,
    ) -> "CostBreakdown":
        """
        Calculate all cost components for one trip from scalar inputs only.
        All values extracted from RouteResult and collections by run_model.py.

        fix_overhead base = operating costs only (cleaning, shunting, maint/km,
        staff/h) — amortisation and financing are excluded as capital costs.
        """

        # --- fixed per day ---
        loco_avail_days = loco_avail_per * 365.0
        coach_avail_days = coach_avail_per * 365.0

        loco_amort = (
            purchase_loco_eur / (loco_avail_days * loco_amort_years)
            if loco_avail_days > 0 and loco_amort_years > 0
            else 0.0
        )
        coach_amort = (
            purchase_coach_eur / (coach_avail_days * coach_amort_years)
            if coach_avail_days > 0 and coach_amort_years > 0
            else 0.0
        )

        financing = (
            (purchase_loco_eur + purchase_coach_eur) * financing_quota_per / 365.0
        )

        # fix overhead base: operating costs only, excludes amortisation + financing
        op_cost_base = (
            cleaning_services_eur_day
            + shunting_eur_day
            + loco_maint_eur_km * total_distance_km
            + coach_maint_eur_km * total_distance_km
            + driver_costs_eur_h * (total_driving_time_h + driver_overhead_h)
            + crew_costs_eur_h * (total_driving_time_h + crew_overhead_h)
        )
        fix_overhead = op_cost_base * fix_overhead_quota_per

        # --- variable per km ---
        loco_maint = loco_maint_eur_km * total_distance_km
        coach_maint = coach_maint_eur_km * total_distance_km

        # --- variable per hour ---
        driver = driver_costs_eur_h * (total_driving_time_h + driver_overhead_h)
        crew = crew_costs_eur_h * (total_driving_time_h + crew_overhead_h)

        # --- variable per ticket ---
        svc_seat = revenue_seat * svc_stockings_seat_per
        svc_couchette = revenue_couchette * svc_stockings_couchette_per
        svc_sleeper = revenue_sleeper * svc_stockings_sleeper_per
        var_overhead = total_revenue * var_overhead_per

        # --- ebit margin ---
        ebit_margin = total_revenue * ebit_margin_per

        return cls(
            loco_amortisation=loco_amort,
            coach_amortisation=coach_amort,
            financing=financing,
            fix_overhead=fix_overhead,
            cleaning_services=cleaning_services_eur_day,
            shunting=shunting_eur_day,
            parking=parking_eur,
            svc_stockings_seat=svc_seat,
            svc_stockings_couchette=svc_couchette,
            svc_stockings_sleeper=svc_sleeper,
            var_overhead=var_overhead,
            loco_maintenance=loco_maint,
            coach_maintenance=coach_maint,
            driver=driver,
            crew=crew,
            track_access=total_tac_eur,
            energy=total_energy_eur,
            station_charges=station_charges_eur,
            ebit_margin=ebit_margin,
        )


# =============================================================================
# CLASS COST ALLOCATION
# =============================================================================


@dataclass
class ClassCostAllocation:
    """
    Cost allocated to each ticket class based on coach space consumption.

    space_units = berths × density (1 / berths_per_standard_coach)
    class_cost  = total_cost × (class_units / total_units)
    per_berth   = class_cost / berths_in_class
    """

    space_units_seat: float = 0.0
    space_units_couchette: float = 0.0
    space_units_sleeper: float = 0.0

    cost_seat_class: float = 0.0
    cost_couchette_class: float = 0.0
    cost_sleeper_class: float = 0.0

    cost_per_seat: float = 0.0
    cost_per_couchette: float = 0.0
    cost_per_sleeper: float = 0.0

    @property
    def total_space_units(self) -> float:
        return (
            self.space_units_seat
            + self.space_units_couchette
            + self.space_units_sleeper
        )

    @classmethod
    def calculate(
        cls,
        total_cost: float,
        seats_total: int,
        couchettes_total: int,
        sleepers_total: int,
        seat_density: float,
        couchette_density: float,
        sleeper_density: float,
        comp_id: str = "",
    ) -> "ClassCostAllocation":
        """
        Allocate total_cost across ticket classes using space units.
        All inputs are plain scalars extracted by run_model.py.
        """
        seat_units = seats_total * seat_density
        couchette_units = couchettes_total * couchette_density
        sleeper_units = sleepers_total * sleeper_density
        total_units = seat_units + couchette_units + sleeper_units

        if total_units == 0:
            logger.warning(
                "Total space units are zero for composition '%s' — "
                "cost allocation skipped.",
                comp_id,
            )
            return cls()

        cost_seat = total_cost * seat_units / total_units
        cost_couchette = total_cost * couchette_units / total_units
        cost_sleeper = total_cost * sleeper_units / total_units

        return cls(
            space_units_seat=seat_units,
            space_units_couchette=couchette_units,
            space_units_sleeper=sleeper_units,
            cost_seat_class=cost_seat,
            cost_couchette_class=cost_couchette,
            cost_sleeper_class=cost_sleeper,
            cost_per_seat=cost_seat / seats_total if seats_total > 0 else 0.0,
            cost_per_couchette=(
                cost_couchette / couchettes_total if couchettes_total > 0 else 0.0
            ),
            cost_per_sleeper=(
                cost_sleeper / sleepers_total if sleepers_total > 0 else 0.0
            ),
        )


# =============================================================================
# MODEL RESULT
# =============================================================================


@dataclass
class ModelResult:
    """Top-level result object returned by run_model.py."""

    composition_id: str
    total_distance_km: float
    total_driving_time_h: float
    total_time_h: float
    operating_days_year: int

    revenue: RevenueBreakdown
    cost: CostBreakdown
    allocation: ClassCostAllocation

    capacity_seats: int = 0
    capacity_couchettes: int = 0
    capacity_sleepers: int = 0

    @property
    def margin(self) -> float:
        return self.revenue.total - self.cost.total

    @property
    def margin_pct(self) -> float:
        return self.margin / self.revenue.total if self.revenue.total > 0 else 0.0

    @property
    def annual_margin(self) -> float:
        return self.margin * self.operating_days_year

    @property
    def cost_per_seat_km(self) -> float:
        total_capacity = (
            self.capacity_seats + self.capacity_couchettes + self.capacity_sleepers
        )
        seat_km = total_capacity * self.total_distance_km
        return self.cost.total / seat_km if seat_km > 0 else 0.0

    def summary(self) -> str:
        lines = [
            f"=== Night Train Model Result — {self.composition_id} ===",
            f"Route distance:       {self.total_distance_km:>10,.1f} km",
            f"Driving time:         {self.total_driving_time_h:>10,.2f} h",
            f"Total time:           {self.total_time_h:>10,.2f} h",
            f"Operating days/year:  {self.operating_days_year:>10d}",
            f"",
            f"--- CAPACITY ---",
            f"  Seats:              {self.capacity_seats:>10d}",
            f"  Couchettes:         {self.capacity_couchettes:>10d}",
            f"  Sleepers:           {self.capacity_sleepers:>10d}",
            f"",
            f"--- REVENUE ---",
            f"  Seats:              {self.revenue.revenue_seat:>10,.0f} €"
            f"  ({self.revenue.passengers_seat:.1f} pax, LF {self.revenue.utilization_seat:.0%})",
            f"  Couchettes:         {self.revenue.revenue_couchette:>10,.0f} €"
            f"  ({self.revenue.passengers_couchette:.1f} pax, LF {self.revenue.utilization_couchette:.0%})",
            f"  Sleepers:           {self.revenue.revenue_sleeper:>10,.0f} €"
            f"  ({self.revenue.passengers_sleeper:.1f} pax, LF {self.revenue.utilization_sleeper:.0%})",
            f"  TOTAL REVENUE:      {self.revenue.total:>10,.0f} €",
            f"",
            f"--- COSTS ---",
            f"  Fixed per day:",
            f"    Loco amort:       {self.cost.loco_amortisation:>10,.0f} €",
            f"    Coach amort:      {self.cost.coach_amortisation:>10,.0f} €",
            f"    Financing:        {self.cost.financing:>10,.0f} €",
            f"    Fix overhead:     {self.cost.fix_overhead:>10,.0f} €",
            f"    Cleaning:         {self.cost.cleaning_services:>10,.0f} €",
            f"    Shunting:         {self.cost.shunting:>10,.0f} €",
            f"    Parking:          {self.cost.parking:>10,.0f} €",
            f"    Subtotal:         {self.cost.fixed_day_total:>10,.0f} €",
            f"  Variable per km:",
            f"    Loco maint:       {self.cost.loco_maintenance:>10,.0f} €",
            f"    Coach maint:      {self.cost.coach_maintenance:>10,.0f} €",
            f"    Subtotal:         {self.cost.variable_km_total:>10,.0f} €",
            f"  Variable per hour:",
            f"    Driver:           {self.cost.driver:>10,.0f} €",
            f"    Crew:             {self.cost.crew:>10,.0f} €",
            f"    Subtotal:         {self.cost.variable_hour_total:>10,.0f} €",
            f"  Variable per ticket:",
            f"    Svc/stock seat:   {self.cost.svc_stockings_seat:>10,.0f} €",
            f"    Svc/stock couch:  {self.cost.svc_stockings_couchette:>10,.0f} €",
            f"    Svc/stock sleep:  {self.cost.svc_stockings_sleeper:>10,.0f} €",
            f"    Var overhead:     {self.cost.var_overhead:>10,.0f} €",
            f"    Subtotal:         {self.cost.variable_ticket_total:>10,.0f} €",
            f"  Infrastructure:",
            f"    Track access:     {self.cost.track_access:>10,.0f} €",
            f"    Energy:           {self.cost.energy:>10,.0f} €",
            f"    Station charges:  {self.cost.station_charges:>10,.0f} €",
            f"    Subtotal:         {self.cost.infra_total:>10,.0f} €",
            f"  EBIT margin target: {self.cost.ebit_margin:>10,.0f} €",
            f"  TOTAL COST:         {self.cost.total:>10,.0f} €",
            f"",
            f"--- CLASS COST ALLOCATION ---",
            f"  Space units:  seat={self.allocation.space_units_seat:.2f}"
            f"  couch={self.allocation.space_units_couchette:.2f}"
            f"  sleep={self.allocation.space_units_sleeper:.2f}"
            f"  total={self.allocation.total_space_units:.2f}",
            f"  Cost/seat:          {self.allocation.cost_per_seat:>10,.2f} €",
            f"  Cost/couchette:     {self.allocation.cost_per_couchette:>10,.2f} €",
            f"  Cost/sleeper:       {self.allocation.cost_per_sleeper:>10,.2f} €",
            f"",
            f"--- RESULT ---",
            f"  Margin/trip:        {self.margin:>10,.0f} €  ({self.margin_pct:.1%})",
            f"  Margin/year:        {self.annual_margin:>10,.0f} €",
            f"  Cost/seat-km:       {self.cost_per_seat_km:>10.4f} €/seat-km",
        ]
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "composition_id": self.composition_id,
            "total_distance_km": self.total_distance_km,
            "total_driving_time_h": self.total_driving_time_h,
            "total_time_h": self.total_time_h,
            "operating_days_year": self.operating_days_year,
            "capacity": {
                "seats": self.capacity_seats,
                "couchettes": self.capacity_couchettes,
                "sleepers": self.capacity_sleepers,
            },
            "revenue": {
                "utilization_seat": self.revenue.utilization_seat,
                "utilization_couchette": self.revenue.utilization_couchette,
                "utilization_sleeper": self.revenue.utilization_sleeper,
                "avg_fare_seat": self.revenue.avg_fare_seat,
                "avg_fare_couchette": self.revenue.avg_fare_couchette,
                "avg_fare_sleeper": self.revenue.avg_fare_sleeper,
                "passengers_seat": self.revenue.passengers_seat,
                "passengers_couchette": self.revenue.passengers_couchette,
                "passengers_sleeper": self.revenue.passengers_sleeper,
                "revenue_seat": self.revenue.revenue_seat,
                "revenue_couchette": self.revenue.revenue_couchette,
                "revenue_sleeper": self.revenue.revenue_sleeper,
                "total": self.revenue.total,
            },
            "cost": {
                "loco_amortisation": self.cost.loco_amortisation,
                "coach_amortisation": self.cost.coach_amortisation,
                "financing": self.cost.financing,
                "fix_overhead": self.cost.fix_overhead,
                "cleaning_services": self.cost.cleaning_services,
                "shunting": self.cost.shunting,
                "parking": self.cost.parking,
                "fixed_day_total": self.cost.fixed_day_total,
                "loco_maintenance": self.cost.loco_maintenance,
                "coach_maintenance": self.cost.coach_maintenance,
                "variable_km_total": self.cost.variable_km_total,
                "driver": self.cost.driver,
                "crew": self.cost.crew,
                "variable_hour_total": self.cost.variable_hour_total,
                "svc_stockings_seat": self.cost.svc_stockings_seat,
                "svc_stockings_couchette": self.cost.svc_stockings_couchette,
                "svc_stockings_sleeper": self.cost.svc_stockings_sleeper,
                "var_overhead": self.cost.var_overhead,
                "variable_ticket_total": self.cost.variable_ticket_total,
                "track_access": self.cost.track_access,
                "energy": self.cost.energy,
                "station_charges": self.cost.station_charges,
                "infra_total": self.cost.infra_total,
                "ebit_margin": self.cost.ebit_margin,
                "total": self.cost.total,
            },
            "allocation": {
                "space_units_seat": self.allocation.space_units_seat,
                "space_units_couchette": self.allocation.space_units_couchette,
                "space_units_sleeper": self.allocation.space_units_sleeper,
                "total_space_units": self.allocation.total_space_units,
                "cost_seat_class": self.allocation.cost_seat_class,
                "cost_couchette_class": self.allocation.cost_couchette_class,
                "cost_sleeper_class": self.allocation.cost_sleeper_class,
                "cost_per_seat": self.allocation.cost_per_seat,
                "cost_per_couchette": self.allocation.cost_per_couchette,
                "cost_per_sleeper": self.allocation.cost_per_sleeper,
            },
            "margin": self.margin,
            "margin_pct": self.margin_pct,
            "annual_margin": self.annual_margin,
            "cost_per_seat_km": self.cost_per_seat_km,
        }
