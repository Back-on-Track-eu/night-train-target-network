"""
params.py
=========
Read-only parameter endpoints.

  GET /api/params/StopInfrastructures  — all stops
  GET /api/params/compositions         — all composition types
  GET /api/params/TrackInfrastructures — all country track infrastructure
"""

import logging

from flask import Blueprint, jsonify

from api.dependencies import get_loader
from models.utils import min_to_h

logger = logging.getLogger(__name__)
bp = Blueprint("params", __name__)


@bp.get("/StopInfrastructures")
def get_stop_infrastructures():
    """
    Return all available stops with routing-relevant fields and parameter provenance.
    Fields resolved from a default row are marked with is_default=True.
    """
    loader = get_loader()
    stop_infra, param_versions = loader.build_all_stops()

    def _field(stop_id, field_name, value):
        entry = param_versions.get(f"stop_infra:{stop_id}:{field_name}")
        return {
            "value": value,
            "is_default": entry.is_default if entry else False,
            "version": entry.version if entry else None,
            "source": (
                {
                    "source_id": entry.source.source_id,
                    "source_description": entry.source.source_description,
                    "source_url": entry.source.source_url,
                }
                if entry and entry.source
                else None
            ),
            "description": entry.description if entry else None,
        }

    stops = [
        {
            "stop_id": s.stop_id,
            "name": s.stop_name or s.stop_id,
            "country_code": s.stop_country_code,
            "lat": float(s.lat),  # location — always present, no default
            "lon": float(s.lon),  # location — always present, no default
            "stop_charge_eur": _field(
                s.stop_id, "stop_charge_eur", float(s.stop_charge_eur)
            ),
        }
        for s in stop_infra.all().values()
    ]

    stops.sort(key=lambda x: x["name"])
    return jsonify({"stops": stops}), 200


@bp.get("/compositions")
def get_compositions():
    """
    Return all available composition types with full parameters.
    Capacity and density expressed per service class.
    Staff overhead converted to hours for display.
    """
    loader = get_loader()
    compositions, _ = loader.build_all_compositions()

    result = []
    for comp_id, c in compositions.items():
        result.append(
            {
                # --- identity ---
                "comp_id": c.comp_id,
                "description": c.comp_description,
                "operator_id": c.operator_id,
                # --- routing ---
                "routing": {
                    "total_weight_t": c.total_weight_t,
                    "max_speed_kmh": c.max_speed_kmh,
                    "hsr_allowed": c.hsr_allowed,
                    "min_boarding_time_min": c.min_boarding_time_min,
                    "min_alighting_time_min": c.min_alighting_time_min,
                    "driver_factor": c.driver_factor,
                },
                # --- energy model ---
                "energy": {
                    "factor_weight": c.energy_factor_weight,
                    "factor_speed": c.energy_factor_speed,
                    "factor_terrain": c.energy_factor_terrain,
                },
                # --- capacity and density per service class ---
                "capacity": {
                    cls: {
                        "places": places,
                        "density": c.density_by_class.get(cls, 0.0),
                    }
                    for cls, places in c.places_by_class.items()
                    if places > 0
                },
                # --- ebit target ---
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
                    "driver_overhead_h": min_to_h(c.driver_overhead_min),
                    "crew_overhead_h": min_to_h(c.crew_overhead_min),
                },
                # --- variable costs per ticket sold ---
                "variable_ticket": {
                    "svc_stockings_eur_place": c.svc_stockings_eur_place,
                    "var_overhead_per": c.var_overhead_per,
                },
                # --- indicative KPIs (computed at load time from composition_references) ---
                "indicative": (
                    {
                        "cost_eur_per_seat_km": c.indicative.cost_eur_per_seat_km,
                        "cost_eur_per_place_km": c.indicative.cost_eur_per_place_km,
                        "subsidy_eur_per_pax_km": c.indicative.subsidy_eur_per_pax_km,
                        "breakeven_load_factor": c.indicative.breakeven_load_factor,
                    }
                    if c.indicative
                    else None
                ),
            }
        )

    result.sort(key=lambda x: x["comp_id"])
    return jsonify({"compositions": result}), 200


@bp.get("/TrackInfrastructures")
def get_track_infrastructures():
    """
    Return all country track infrastructure parameters with per-field provenance.
    Fields resolved from the EU-average default row are marked with is_default=True,
    and the default row's source/version is shown instead of the country row's.
    """
    loader = get_loader()
    tracks, param_versions = loader.build_all_tracks()

    def _field(cc, field_name, value):
        entry = param_versions.get(f"track_infra:{cc}:{field_name}")
        return {
            "value": value,
            "is_default": entry.is_default if entry else False,
            "version": entry.version if entry else None,
            "source": (
                {
                    "source_id": entry.source.source_id,
                    "source_description": entry.source.source_description,
                    "source_url": entry.source.source_url,
                }
                if entry and entry.source
                else None
            ),
            "description": entry.description if entry else None,
        }

    result = []
    for t in tracks.all().values():
        cc = t.country_code
        result.append(
            {
                "country_code": cc,
                "tac_eur_train_km": _field(
                    cc, "tac_eur_train_km", float(t.tac_eur_train_km)
                ),
                "energy_price_eur_kwh": _field(
                    cc, "energy_price_eur_kwh", float(t.energy_price_eur_kwh)
                ),
                "parking_eur_day": _field(
                    cc, "parking_eur_day", float(t.parking_eur_day)
                ),
                "terrain_category": _field(cc, "terrain_category", t.terrain_category),
                "terrain_score": _field(cc, "terrain_score", float(t.terrain_score)),
                "hsr_allowed": _field(cc, "hsr_allowed", t.hsr_allowed),
                "min_boarding_time_min": _field(
                    cc, "min_boarding_time_min", t.min_boarding_time_min
                ),
                "min_alighting_time_min": _field(
                    cc, "min_alighting_time_min", t.min_alighting_time_min
                ),
                "buffer_quota_per": _field(
                    cc, "buffer_quota_per", float(t.buffer_quota_per)
                ),
            }
        )

    result.sort(key=lambda x: x["country_code"])
    return jsonify({"track_infrastructures": result}), 200
