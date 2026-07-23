"""
params_serialize.py
====================
Serialization (domain → dict) for the read-only parameter endpoints in
api/params.py. Split out from serialize.py because that module explicitly
scopes itself to "the evaluation pipeline" (route + evaluation) — see its
own module docstring.

Covers all three params endpoints: StopInfrastructures,
TrackInfrastructures, and compositions.

Public interface:
  stop_infra_to_dict(stop_infra)             → dict  (full body for GET /api/params/StopInfrastructures)
  track_infra_to_dict(track_infra)           → dict  (full body for GET /api/params/TrackInfrastructures)
  composition_collection_to_dict(compositions) → dict  (full body for GET /api/params/compositions)
"""

from __future__ import annotations

from models.params import (
    ParamsSource,
    StopInfraCollection,
    TrackInfraCollection,
    TRACK_INFRA_FIELD_NAMES,
    CompositionCollection,
)
from models.utils import min_to_h
from models.evaluation.views import build_class_main_shares

# =============================================================================
# SHARED
# =============================================================================


def _register_source(
    sources_map: dict[int, dict], source: ParamsSource | None
) -> int | None:
    """
    Register a ParamsSource into a shared {source_id: dict} map (mutated in
    place) and return its source_id, or None if there's no source. Callers
    embed the returned id inline (e.g. as a field's "source_id") instead of
    the full source object — the full object is only ever written once per
    distinct source_id into sources_map, however many fields reference it.
    """
    if source is None:
        return None
    if source.source_id not in sources_map:
        sources_map[source.source_id] = {
            "source_id": source.source_id,
            "source_description": source.source_description,
            "source_url": source.source_url,
            "source_date": source.source_date,
        }
    return source.source_id


# =============================================================================
# STOP INFRASTRUCTURE — serialize
# =============================================================================


def stop_infra_to_dict(stop_infra: StopInfraCollection) -> dict:
    """
    Serialize a StopInfraCollection into the full JSON body for
    GET /api/params/StopInfrastructures.

      descriptions  : table/column documentation, once — identical for
                      every stop, so it's not repeated per stop/field
      sources       : every referenced source, keyed by source_id — fields
                      below embed a "source_id" rather than the full object
      default_stops : the raw EU-average fallback rows stops resolve
                      against when their own stop_charge_eur is NULL
                      ("global", plus "by_country" for any country with
                      its own override)
      count         : total number of stops
      stops         : the stops themselves
    """
    sources_map: dict[int, dict] = {}

    def _field(stop_id, field_name, value):
        entry = stop_infra.param_versions.get(f"stop_infra:{stop_id}:{field_name}")
        return {
            "value": value,
            "is_default": entry.is_default if entry else False,
            "version": entry.version if entry else None,
            "source_id": _register_source(sources_map, entry.source if entry else None),
        }

    global_default = stop_infra.defaults.get(None)
    default_stops = {
        "global": (
            {
                "stop_charge_eur": {
                    "value": float(global_default.stop_charge_eur),
                    "source_id": _register_source(
                        sources_map, global_default.stop_charge_src
                    ),
                }
            }
            if global_default
            else None
        ),
        "by_country": {
            cc: {
                "stop_charge_eur": {
                    "value": float(d.stop_charge_eur),
                    "source_id": _register_source(sources_map, d.stop_charge_src),
                }
            }
            for cc, d in sorted(stop_infra.defaults.items(), key=lambda kv: kv[0] or "")
            if cc is not None
        },
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

    return {
        "descriptions": {
            "table": stop_infra.descriptions.table,
            "fields": stop_infra.descriptions.fields,
        },
        "sources": sources_map,
        "default_stops": default_stops,
        "count": len(stops),
        "stops": stops,
    }


# =============================================================================
# TRACK INFRASTRUCTURE — serialize
# =============================================================================

# How to cast each TRACK_INFRA_FIELD_NAMES value for JSON. Iterating the
# canonical field tuple (rather than hand-listing each field, as the old
# inline version in api/params.py did) means a field can't silently go
# missing from the response the way shunting_eur_event previously did.
_TRACK_FIELD_CASTS: dict[str, type] = {
    "tac_eur_train_km": float,
    "parking_eur_day": float,
    "shunting_eur_event": float,
    "energy_price_eur_kwh": float,
    "terrain_score": float,
    "terrain_category": str,
    "hsr_allowed": bool,
    "min_boarding_time_min": int,
    "min_alighting_time_min": int,
    "buffer_quota_per": float,
}


def track_infra_to_dict(track_infra: TrackInfraCollection) -> dict:
    """
    Serialize a TrackInfraCollection into the full JSON body for
    GET /api/params/TrackInfrastructures.

      descriptions          : table/column documentation, once — identical
                              for every country, so it's not repeated per
                              country/field
      sources               : every referenced source, keyed by source_id —
                              fields below embed a "source_id" rather than
                              the full object
      default_track_infra   : the single EU-average fallback row every
                              field resolves against when a country's own
                              value (or entire row) is missing
      count                 : total number of countries
      track_infrastructures : one entry per country
    """
    sources_map: dict[int, dict] = {}

    def _field(cc, field_name, value):
        entry = track_infra.param_versions.get(f"track_infra:{cc}:{field_name}")
        return {
            "value": value,
            "is_default": entry.is_default if entry else False,
            "version": entry.version if entry else None,
            "source_id": _register_source(sources_map, entry.source if entry else None),
        }

    default = track_infra.defaults
    default_track_infra = {
        field_name: {
            "value": _TRACK_FIELD_CASTS[field_name](getattr(default, field_name)),
            "source_id": _register_source(sources_map, default.source_for(field_name)),
        }
        for field_name in TRACK_INFRA_FIELD_NAMES
    }

    track_infrastructures = [
        {
            "country_code": t.country_code,
            **{
                field_name: _field(
                    t.country_code,
                    field_name,
                    _TRACK_FIELD_CASTS[field_name](getattr(t, field_name)),
                )
                for field_name in TRACK_INFRA_FIELD_NAMES
            },
        }
        for t in track_infra.all().values()
    ]
    track_infrastructures.sort(key=lambda x: x["country_code"])

    return {
        "descriptions": {
            "table": track_infra.descriptions.table,
            "fields": track_infra.descriptions.fields,
        },
        "sources": sources_map,
        "default_track_infra": default_track_infra,
        "count": len(track_infrastructures),
        "track_infrastructures": track_infrastructures,
    }


# =============================================================================
# COMPOSITIONS — serialize
# =============================================================================


def _class_share_mix(c) -> dict:
    """Per class_main: its blended cost proportion (the workbook's
    per-class cost_acc columns — X·length + (1−X)·weight of the revenue
    space, plus the service-area cost per head). From the canonical
    allocation machinery (views.build_class_main_shares), so the
    compositions API and the evaluation's by_class_main split can never
    disagree. Shares sum to 1."""
    shares = build_class_main_shares(c)
    return {
        cm: round(shares.hardware.get(cm, 0.0), 5) for cm in sorted(shares.per_head)
    }


def composition_collection_to_dict(compositions: CompositionCollection) -> dict:
    """
    Serialize a CompositionCollection into the full JSON body for
    GET /api/params/compositions.

      descriptions  : documentation mirroring the actual response shape
                      below (grouped "compositions" — with "routing"/
                      "staff"/"energy"/"capacity"/"equipment"/"coaches"/
                      "fixed_costs"/"variable_km" sub-sections —,
                      "operators", "indicative"), once — see
                      CompositionCollection.descriptions
      sources       : every referenced source, keyed by source_id
      count         : total number of compositions
      compositions  : the compositions themselves — each embeds
                      "source_ids" (a list) rather than per-field source
                      objects, since Composition's own fields aren't
                      individually sourced/versioned (see Composition's
                      docstring) — only a set of sources for the whole
                      entity, same as before this refactor, just
                      id-referenced now instead of embedding full objects
      operators     : the operators they reference, same "source_ids"
                      treatment
    """
    sources_map: dict[int, dict] = {}

    def _source_ids_for_prefixes(prefixes: list[str]) -> list[int]:
        """Distinct source_ids from ParamVersions entries whose key starts
        with any of the given prefixes (e.g. "composition_type:STD-7.1:",
        "coach_type:WLABmz:"), registering each into sources_map."""
        ids = {
            _register_source(sources_map, entry.source)
            for key, entry in compositions.param_versions.entries.items()
            if entry.source is not None and any(key.startswith(p) for p in prefixes)
        }
        return sorted(ids)

    result = []
    operators_by_id: dict[str, dict] = {}

    for comp_id, c in compositions.all().items():
        result.append(
            {
                # --- identity ---
                "comp_id": c.comp_id,
                "description": c.comp_description,
                "material_strategy": c.material_strategy,
                "operator_id": c.operator_id,
                # --- routing ---
                "routing": {
                    "total_weight_t": c.total_weight_t,
                    "total_length_m": c.total_length_m,
                    # locomotives needed; scales loco lease (and the
                    # energy weight basis once the energy model is
                    # calibrated)
                    "n_locos": c.n_locos,
                    "max_speed_kmh": c.max_speed_kmh,
                    "hsr_allowed": c.hsr_allowed,
                    "min_boarding_time_min": c.min_boarding_time_min,
                    "min_alighting_time_min": c.min_alighting_time_min,
                },
                # --- staff requirements ---
                "staff": {
                    "driver_factor": c.driver_factor,
                    # total = Σ coach crew factors + the Zugchef factor
                    # (train manager in attendant-equivalents, doubled for
                    # ≥10-coach formations), all priced at the crew rate
                    "crew_factor_total": c.total_crew,
                    "zugchef_crew_factor": c.zugchef_crew_factor,
                    "crew_factor_coaches": round(
                        c.total_crew - c.zugchef_crew_factor, 4
                    ),
                },
                # --- capacity and density per top-level accommodation class
                #     (class_main — Seat/Couchette/Sleeper/Capsule/Catering),
                #     not the more granular class_id, since 2026-07-06; see
                #     Composition.places_by_class's field comment ---
                # densities derived from real section geometry (m and t per
                # place) — replace the retired service_class_density
                "capacity": {
                    "total_places": sum(c.places_by_class.values()),
                    # averages over all classes (workbook AL/AM):
                    # full-composition space per place, service included
                    "avg_density_length_m_per_place": round(
                        c.avg_density_length_m_per_place, 4
                    ),
                    "avg_density_weight_t_per_place": round(
                        c.avg_density_weight_t_per_place, 4
                    ),
                    "by_class": {
                        cls: {
                            "places": places,
                            "density_length_m_per_place": (
                                c.density_by_class_main_length.get(cls)
                            ),
                            "density_weight_t_per_place": (
                                c.density_by_class_main_weight.get(cls)
                            ),
                        }
                        for cls, places in c.places_by_class.items()
                        if places > 0
                    },
                },
                # --- onboard equipment — true if ANY coach has it ---
                "equipment": {
                    "has_wifi": c.has_wifi,
                    "has_bikes": c.has_bikes,
                    "has_climatization": c.has_climatization,
                    "has_plugs": c.has_plugs,
                    # catering concept of the composition (structured
                    # composition-level field; coach amenities above are
                    # OR-aggregations)
                    "food_and_beverages": c.food_and_beverages,
                },
                # --- individual coaches in this composition, ordered by position ---
                "coaches": {
                    "count": len(c.coaches),
                    # ordered formation — coach_type_id references the
                    # top-level "coach_types" catalog (coach types repeat
                    # across compositions, so details live there once,
                    # same pattern as "operators" and "classes")
                    "list": [
                        {"position": pos, "coach_type_id": coach.coachtype_id}
                        for pos, coach in sorted(c.coaches.items())
                    ],
                },
                # --- fixed costs per operating day (composition-level only —
                #     operator-level fixed costs are under "operators") ---
                "fixed_costs": {
                    "purchase_coach_eur": c.purchase_coach_eur,
                    "coach_avail_per": c.coach_avail_per,
                    "coach_amort_years": c.coach_amort_years,
                    "cleaning_services_eur_day": c.cleaning_services_eur_day,
                },
                # --- variable costs per km ---
                "variable_km": {
                    "coach_maint_eur_km": c.coach_maint_eur_km,
                },
                # --- class cost allocation (calib/CALIBRATION.md) ---
                # --- class cost allocation (workbook cost_acc columns;
                #     calib/CALIBRATION.md) ---
                "cost_allocation": {
                    # per class_main: its blended cost proportion
                    # (workbook cost_acc columns; X-blend + service areas
                    # per head — identical to the evaluation's
                    # by_class_main hardware basis); sums to 1
                    "by_class_main": _class_share_mix(c),
                },
                # --- indicative KPIs: seeded calibration values from the
                #     composition_types columns — see calib/CALIBRATION.md ---
                "indicative": (
                    {
                        "kpis": {
                            "cost_eur_per_train_km": c.indicative.cost_eur_per_train_km,
                            "cost_ct_per_place_km": c.indicative.cost_ct_per_place_km,
                        },
                        # basis (reference route, price basis, scope) is
                        # documented in the "descriptions" block — loaded
                        # from the composition_types column comments — and
                        # in full in calib/CALIBRATION.md (umbrella source)
                    }
                    if c.indicative
                    else None
                ),
                # --- sources for this composition's own values: composition_type + coach_types ---
                "source_ids": _source_ids_for_prefixes(
                    [f"composition_type:{comp_id}:"]
                    + [
                        f"coach_type:{coach.coachtype_id}:"
                        for coach in c.coaches.values()
                    ]
                ),
            }
        )

        if c.operator_id not in operators_by_id:
            operators_by_id[c.operator_id] = {
                "operator_id": c.operator_id,
                "operator_name": c.operator_name,
                "driver_costs_eur_h": c.driver_costs_eur_h,
                "crew_costs_eur_h": c.crew_costs_eur_h,
                "ebit_margin_per": c.ebit_margin_per,
                "financing_quota_per": c.financing_quota_per,
                "var_overhead_per": c.var_overhead_per,
                "fix_overhead_quota_per": c.fix_overhead_quota_per,
                "loco_full_service_lease_eur_h": c.loco_full_service_lease_eur_h,
                "cost_per_class": c.svc_stockings_eur_place,
                # --- sources for this operator's own values + its per-class costs ---
                "source_ids": _source_ids_for_prefixes(
                    [
                        f"operator:{c.operator_id}:",
                        f"operator_class_cost:{c.operator_id}:",
                    ]
                ),
            }

    coach_types_catalog: dict[str, dict] = {}
    for c in compositions.all().values():
        for coach in c.coaches.values():
            if coach.coachtype_id in coach_types_catalog:
                continue
            coach_types_catalog[coach.coachtype_id] = {
                "length_m": coach.length_m,
                # per-coach service-area geometry stays exposed here —
                # it is the raw schema data (a dining car has zero
                # revenue space); composition-level wo_service totals
                # are internal to the allocation and not serialized
                "length_wo_service_m": coach.length_wo_service_m,
                "weight_gross_t": coach.weight_gross_t,
                "weight_wo_service_t": coach.weight_wo_service_t,
                "crew_factor": coach.crew_factor,
                "places_total": coach.total_places(),
                "equipment": {
                    "has_wifi": coach.has_wifi,
                    "has_bikes": coach.bikes > 0,
                    "has_climatization": coach.climatization,
                    "has_plugs": coach.plugs,
                },
                "class_ids": sorted(a.class_id for a in coach.classes.values()),
                "remarks": coach.remarks,
                "source_ids": _source_ids_for_prefixes(
                    [f"coach_type:{coach.coachtype_id}:"]
                ),
            }
    coach_types_catalog = dict(sorted(coach_types_catalog.items()))

    classes_by_main: dict[str, list] = {}
    seen_class_ids: set[str] = set()
    for c in compositions.all().values():
        for coach in c.coaches.values():
            for a in coach.classes.values():
                if a.class_id in seen_class_ids:
                    continue
                seen_class_ids.add(a.class_id)
                classes_by_main.setdefault(a.class_main, []).append(
                    {
                        "class_id": a.class_id,
                        "coach_type_id": coach.coachtype_id,
                        "places": a.places,
                    }
                )
    for lst in classes_by_main.values():
        lst.sort(key=lambda x: x["class_id"])

    result.sort(key=lambda x: x["comp_id"])
    operators = sorted(operators_by_id.values(), key=lambda x: x["operator_id"])

    return {
        "descriptions": compositions.descriptions,
        "sources": sources_map,
        "count": len(result),
        "compositions": result,
        "operators": operators,
        # all service classes across the catalog, grouped by class_main —
        # one entry per class_id with its carrying coach type and places
        "classes": classes_by_main,
        # all coach types across the catalog, keyed by coach_type_id —
        # referenced from compositions' coaches.list; class_ids reference
        # the "classes" section
        "coach_types": coach_types_catalog,
    }
