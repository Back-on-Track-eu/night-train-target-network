"""
run_model.py
============
Night train model pipeline — route, calculate, assemble.

Single entry point: run() executes the full pipeline and returns a ModelResult.
A DBDataLoader (or compatible loader) must be passed in from the API layer.

Pipeline
--------
  LOAD   — receive pre-loaded loader from caller
  ROUTE  — build Stop objects, call router, get RouteResult
  EXTRACT— pull scalar values from RouteResult and collections
  CALC   — revenue → cost → class allocation
  ASSEMBLE — build and return ModelResult
"""

from __future__ import annotations

import logging
import os

from models.params import (
    CompositionParams,
    InfraCollection,
    StopCollection,
)
from models.route_evaluation_model.routing.rail_router import (
    RailRouter,
    Stop,
    RouteResult,
)
from models.route_evaluation_model.model import (
    RevenueBreakdown,
    CostBreakdown,
    ClassCostAllocation,
    ModelResult,
)

logger = logging.getLogger(__name__)


def run(
    # --- route definition ---
    stop_inputs: list[tuple[str, str]],  # (stop_id, stop_type) pairs
    composition_id: str,
    departure_time_h: float,  # e.g. 21.0 for 21:00
    # --- runtime inputs ---
    utilization_seat: float,
    utilization_couchette: float,
    utilization_sleeper: float,
    avg_fare_seat: float,
    avg_fare_couchette: float,
    avg_fare_sleeper: float,
    operating_days_year: int,
    # --- data loading ---
    loader: Optional[SheetDataLoader] = None,  # pass cached loader from API
    config_path: Optional[str] = None,  # only needed if loader is None
) -> ModelResult:
    """
    Run the full night train model pipeline.

    Parameters
    ----------
    stop_inputs : list[tuple[str, str]]
        Ordered stop list as (stop_id, stop_type) pairs.
        stop_type: "boarding" | "alighting" | "both"
    composition_id : str
        Key into the compositions table (e.g. "NJ-3.1").
    departure_time_h : float
        Departure time from first stop in decimal hours (e.g. 21.067 for 21:04).
    utilization_seat : float
        Fraction of seat capacity filled per trip (0.0–1.0).
    utilization_couchette : float
        Fraction of couchette capacity filled per trip (0.0–1.0).
    utilization_sleeper : float
        Fraction of sleeper capacity filled per trip (0.0–1.0).
    avg_fare_seat : float
        Average ticket price for seat class in EUR.
    avg_fare_couchette : float
        Average ticket price for couchette class in EUR.
    avg_fare_sleeper : float
        Average ticket price for sleeper class in EUR.
    operating_days_year : int
        Number of operating days per year for annual margin calculation.
    loader : DBDataLoader
        Pre-initialised data loader from dependencies.get_loader().
        Must implement build_composition(), build_all_infra(),
        and build_all_stop_params().
    """

    # =========================================================================
    # LOAD — use the pre-initialised loader, no Google Sheets call
    # =========================================================================
    if loader is not None:
        logger.info("Using pre-loaded data loader.")
    else:
        if config_path is None:
            raise ValueError("Either 'loader' or 'config_path' must be provided.")
        logger.info("Loading parameters from Google Sheets...")
        loader = SheetDataLoader(config_path)
        loader.load_all()

    composition = loader.build_composition(composition_id)
    infra = loader.build_all_infra()
    stop_ids = [stop_id for stop_id, _ in stop_inputs]
    stop_params = loader.build_all_stop_params(stop_ids)

    logger.info(
        "Loaded: composition=%s, infra=%d countries, stops=%d",
        composition_id,
        len(infra),
        len(stop_params),
    )

    # =========================================================================
    # ROUTE
    # =========================================================================
    logger.info("Building routing stops and running router...")

    stops = [
        Stop.from_params(stop_params.get(stop_id), stop_type)
        for stop_id, stop_type in stop_inputs
        if stop_params.get(stop_id) is not None
    ]

    if len(stops) != len(stop_inputs):
        missing = [s for s, _ in stop_inputs if stop_params.get(s) is None]
        raise ValueError(f"Stops not found in database: {missing}")

    router = RailRouter(
        base_url=os.environ.get("OPENRAILROUTING_URL", "http://localhost:8989")
    )

    route_result = router.route(
        stops=stops,
        composition=composition,
        infra=infra.all(),
        departure_time_h=departure_time_h,
    )

    logger.info(
        "Route: %.1f km, %.2f h driving, %.2f h total",
        route_result.total_distance_km,
        route_result.total_driving_time_h,
        route_result.total_time_h,
    )

    # =========================================================================
    # EXTRACT scalar values from RouteResult and collections
    # =========================================================================

    # --- energy cost: sum(kwh × price) per country leg ---
    total_energy_eur = 0.0
    for leg in route_result.legs:
        for cl in leg.country_legs:
            ip = infra.get_or_default(cl.country_code)
            if ip:
                total_energy_eur += cl.energy_kwh * ip.energy_price_eur_kwh

    # --- station charges: intermediate stops only (not first, not last) ---
    station_charges_eur = 0.0
    intermediate_stops = route_result.schedule[1:-1]
    for sched_stop in intermediate_stops:
        charge = stop_params.get_charge(sched_stop.stop_id)
        if charge > 0:
            station_charges_eur += charge
        else:
            logger.warning(
                "No stop charge for intermediate stop '%s' — set to 0.",
                sched_stop.stop_id,
            )

    # --- parking: origin and destination country ---
    parking_eur = 0.0
    countries_with_parking: set[str] = set()
    if route_result.legs:
        first_leg = route_result.legs[0]
        last_leg = route_result.legs[-1]
        if first_leg.country_legs:
            countries_with_parking.add(first_leg.country_legs[0].country_code)
        if last_leg.country_legs:
            countries_with_parking.add(last_leg.country_legs[-1].country_code)
    for cc in countries_with_parking:
        ip = infra.get_or_default(cc)
        if ip:
            parking_eur += ip.parking_eur_day

    logger.info(
        "Extracted: TAC=%.0f €, energy=%.0f €, stations=%.0f €, parking=%.0f €",
        route_result.total_tac_eur,
        total_energy_eur,
        station_charges_eur,
        parking_eur,
    )

    # =========================================================================
    # CALCULATE
    # =========================================================================

    # step 1 — revenue (needed first: cost steps use revenue figures)
    revenue = RevenueBreakdown.calculate(
        seats_total=composition.seats_total,
        couchettes_total=composition.couchettes_total,
        sleepers_total=composition.sleepers_total,
        utilization_seat=utilization_seat,
        utilization_couchette=utilization_couchette,
        utilization_sleeper=utilization_sleeper,
        avg_fare_seat=avg_fare_seat,
        avg_fare_couchette=avg_fare_couchette,
        avg_fare_sleeper=avg_fare_sleeper,
    )
    logger.info("Revenue: %.0f €", revenue.total)

    # step 2 — costs
    cost = CostBreakdown.calculate(
        purchase_loco_eur=composition.purchase_loco_eur,
        purchase_coach_eur=composition.purchase_coach_eur,
        loco_avail_per=composition.loco_avail_per,
        coach_avail_per=composition.coach_avail_per,
        loco_amort_years=composition.loco_amort_years,
        coach_amort_years=composition.coach_amort_years,
        financing_quota_per=composition.financing_quota_per,
        fix_overhead_quota_per=composition.fix_overhead_quota_per,
        cleaning_services_eur_day=composition.cleaning_services_eur_day,
        shunting_eur_day=composition.shunting_eur_day,
        parking_eur=parking_eur,
        loco_maint_eur_km=composition.loco_maint_eur_km,
        coach_maint_eur_km=composition.coach_maint_eur_km,
        total_distance_km=route_result.total_distance_km,
        driver_costs_eur_h=composition.driver_costs_eur_h,
        crew_costs_eur_h=composition.crew_costs_eur_h,
        driver_overhead_h=composition.driver_overhead_h,
        crew_overhead_h=composition.crew_overhead_h,
        total_driving_time_h=route_result.total_driving_time_h,
        total_tac_eur=route_result.total_tac_eur,
        total_energy_eur=total_energy_eur,
        station_charges_eur=station_charges_eur,
        svc_stockings_seat_per=composition.svc_stockings_seat_per,
        svc_stockings_couchette_per=composition.svc_stockings_couchette_per,
        svc_stockings_sleeper_per=composition.svc_stockings_sleeper_per,
        var_overhead_per=composition.var_overhead_per,
        revenue_seat=revenue.revenue_seat,
        revenue_couchette=revenue.revenue_couchette,
        revenue_sleeper=revenue.revenue_sleeper,
        total_revenue=revenue.total,
        ebit_margin_per=composition.ebit_margin_per,
    )
    logger.info("Cost: %.0f €", cost.total)

    # step 3 — class cost allocation
    allocation = ClassCostAllocation.calculate(
        total_cost=cost.total,
        seats_total=composition.seats_total,
        couchettes_total=composition.couchettes_total,
        sleepers_total=composition.sleepers_total,
        seat_density=composition.seat_density,
        couchette_density=composition.couchette_density,
        sleeper_density=composition.sleeper_density,
        comp_id=composition.comp_id,
    )

    # =========================================================================
    # ASSEMBLE
    # =========================================================================
    result = ModelResult(
        composition_id=composition.comp_id,
        total_distance_km=route_result.total_distance_km,
        total_driving_time_h=route_result.total_driving_time_h,
        total_time_h=route_result.total_time_h,
        operating_days_year=operating_days_year,
        revenue=revenue,
        cost=cost,
        allocation=allocation,
        capacity_seats=composition.seats_total,
        capacity_couchettes=composition.couchettes_total,
        capacity_sleepers=composition.sleepers_total,
    )

    logger.info(
        "Result: margin %.0f € (%.1f%%), cost/seat-km %.4f €",
        result.margin,
        result.margin_pct * 100,
        result.cost_per_seat_km,
    )

    return result
