"""
routes/params.py
================
Read-only parameter endpoints — compositions, stops, and infrastructure.
These serve the UI dropdowns, stop picker, and parameter display panel.

  GET /api/compositions   — list all composition IDs + full parameters
  GET /api/stops          — list all stops with id, name, country, lat, lon
  GET /api/infrastructure — list all country infrastructure params
"""

from flask import Blueprint, jsonify
import logging

from api.dependencies import get_loader

logger = logging.getLogger(__name__)
bp = Blueprint("params", __name__)


@bp.get("/compositions")
def get_compositions():
    """
    Return all available train compositions with full parameters.
    """
    loader = get_loader()
    compositions = loader.build_all_compositions()

    result = []
    for comp_id, c in compositions.all().items():
        if comp_id == "_default":
            continue
        result.append(
            {
                # --- identity ---
                "comp_id": c.comp_id,
                "description": c.comp_description,
                "company": c.company,
                # --- routing ---
                "routing": {
                    "weight_gross_t": c.weight_gross_t,
                    "max_speed_kmh": c.max_speed_kmh,
                    "hsr_allowed": c.hsr_allowed,
                    "min_boarding_time_h": c.min_boarding_time_h,
                    "min_alighting_time_h": c.min_alighting_time_h,
                },
                # --- energy model ---
                "energy": {
                    "factor_weight": c.energy_factor_weight,
                    "factor_speed": c.energy_factor_speed,
                    "factor_terrain": c.energy_factor_terrain,
                },
                # --- capacity ---
                "capacity": {
                    "seats": c.seats_total,
                    "couchettes": c.couchettes_total,
                    "sleepers": c.sleepers_total,
                },
                # --- space density ---
                "density": {
                    "seat": c.seat_density,
                    "couchette": c.couchette_density,
                    "sleeper": c.sleeper_density,
                },
                # --- target margin ---
                "ebit_margin_per": c.ebit_margin_per,
                # --- fixed costs per operating day ---
                "fixed_costs": {
                    "purchase_loco_eur": c.purchase_loco_eur,
                    "purchase_coach_eur": c.purchase_coach_eur,
                    "loco_avail_per": c.loco_avail_per,
                    "coach_avail_per": c.coach_avail_per,
                    "loco_amort_years": c.loco_amort_years,
                    "coach_amort_years": c.coach_amort_years,
                    "financing_quota_per": c.financing_quota_per,
                    "fix_overhead_quota_per": c.fix_overhead_quota_per,
                    "cleaning_services_eur_day": c.cleaning_services_eur_day,
                    "shunting_eur_day": c.shunting_eur_day,
                },
                # --- variable costs per km ---
                "variable_km": {
                    "loco_maint_eur_km": c.loco_maint_eur_km,
                    "coach_maint_eur_km": c.coach_maint_eur_km,
                },
                # --- variable costs per hour ---
                "variable_hour": {
                    "driver_costs_eur_h": c.driver_costs_eur_h,
                    "crew_costs_eur_h": c.crew_costs_eur_h,
                    "driver_overhead_h": c.driver_overhead_h,
                    "crew_overhead_h": c.crew_overhead_h,
                },
                # --- variable costs per ticket sold ---
                "variable_ticket": {
                    "svc_stockings_seat_per": c.svc_stockings_seat_per,
                    "svc_stockings_couchette_per": c.svc_stockings_couchette_per,
                    "svc_stockings_sleeper_per": c.svc_stockings_sleeper_per,
                    "var_overhead_per": c.var_overhead_per,
                },
            }
        )

    result.sort(key=lambda x: x["comp_id"])
    return jsonify(result), 200


@bp.get("/stops")
def get_stops():
    """
    Return all available stops with routing-relevant fields.
    Each entry has: stop_id, name, country_code, lat, lon, stop_charge_eur.
    """
    loader = get_loader()
    stop_collection = loader.build_all_stops()

    stops = []
    for stop_id, row in all_rows.items():
        if stop_id == "_default":
            continue
        stops.append(
            {
                "stop_id": stop_id,
                "name": row.get("stop_name", stop_id),
                "country_code": row.get("stop_country_code", ""),
                "lat": _safe_float(row.get("stop_lat")),
                "lon": _safe_float(row.get("stop_lon")),
                "stop_charge_eur": _safe_float(row.get("stop_charge_eur")),
            }
        )

    stops.sort(key=lambda x: x["name"])
    return jsonify(stops), 200


@bp.get("/infrastructure")
def get_infrastructure():
    """
    Return all country infrastructure parameters.
    """
    loader = get_loader()
    infra = loader.build_all_infra()

    result = []
    for country_code, ip in infra.all().items():
        if country_code == "_default":
            continue
        result.append(
            {
                "country_code": ip.country_code,
                "tac_eur_train_km": ip.tac_eur_train_km,
                "energy_price_eur_kwh": ip.energy_price_eur_kwh,
                "parking_eur_day": ip.parking_eur_day,
                "terrain_category": ip.terrain_category,
                "terrain_score": ip.terrain_score,
                "hsr_allowed": ip.hsr_allowed,
                "min_boarding_time_h": ip.min_boarding_time_h,
                "min_alighting_time_h": ip.min_alighting_time_h,
                "buffer_quota_per": ip.buffer_quota_per,
            }
        )

    result.sort(key=lambda x: x["country_code"])
    return jsonify(result), 200


def _safe_float(value) -> float:
    try:
        return float(str(value).strip()) if value else 0.0
    except (ValueError, TypeError):
        return 0.0
