"""
summary.py
==========
Gallery-summary KPI derivation (adapters/proposal/README.md §5.4) — pure
functions over the same dicts POST /api/proposal/calc returns
(route_to_dict() shape + the evaluation "views" block). No DB access, no
domain-object construction, and no geometry: the simplified gallery-map
geometry is deliberately NOT part of this row — the calc response
already carries full per-segment geometry, so only the DB-shaped
assembly in adapters/proposal/projection.py (build_summary_db_row())
adds a `geom_simplified` for `proposals.proposal_summaries`.

Moved out of adapters/proposal/projection.py with WP10 step 5: the same
derivation now feeds the calc response's "summary" block
(api/helpers/proposal_compute.py), the compare sides
(api/helpers/proposal_compare.py, via that block), and the publish-time
proposal_summaries write (adapters/proposal/repository.py via
projection.py) — and api/helpers must never import calculation code from
adapters/ (layering, AGENTS.md), so the shared home is models/. One
function, every consumer: the calc response and the gallery projection
cannot drift when a formula changes.

Public interface:
  build_summary_row(route, evaluation) → dict  (every §5.4 KPI column:
      route metrics, financial KPIs, placeholder demand KPIs, the served
      country_relations, and the flat night-train co2_g_per_pax_km.
      Identity columns and geom_simplified are the callers' concern.)
  country_relations(route)             → list  (the served "AA__BB"
      relation keys, derived from od_pairs — §7.7's stats dimension)
  ordered_stops(trip)                  → list  (a trip's stops in travel
      order — shared with the route fingerprint's canonical extract in
      adapters/proposal/projection.py)
"""

from __future__ import annotations

from models.emissions.model import EMISSION_FACTORS, MODE_SHIFT_SHARES

# Placeholder demand-KPI assumption (§8.1: "deterministic fakes derived
# from route metrics ... plausible orders of magnitude for UI
# development") — replaced wholesale once models/demand/ exists. Never
# treat this as a real modelling assumption. The mode-shift shares and
# CO2 factors it combines with live in models/emissions/model.py.
_PLACEHOLDER_AVG_FARE_EUR = 120.0


def ordered_stops(trip: dict) -> list[dict]:
    """A trip's stops in travel order — the first segment's origin, then
    every segment's destination. Shared by the route-metrics stop
    count/list below and the fingerprint's canonical extract
    (adapters/proposal/projection.py)."""
    segments = trip["segments"]
    return [segments[0]["from_stop"]] + [seg["to_stop"] for seg in segments]


def build_summary_row(route: dict, evaluation: dict) -> dict:
    """The §5.4 gallery-KPI columns for one (route, evaluation) pair —
    exactly the shape POST /api/proposal/calc returns as "summary" and
    the publish repository merges with its identity columns
    (proposal_id, user_id, composition_id, scenario_id, name, versions)
    and geom_simplified."""
    metrics = _route_metrics(route)
    financials = _financial_kpis(evaluation)
    annual_revenue_eur = evaluation["views"]["route"]["data"]["per_year"]["all"][
        "total_revenue_eur"
    ]
    demand = _placeholder_demand_kpis(
        metrics["total_distance_km"],
        annual_revenue_eur,
        financials["subsidy_eur_per_year"],
    )
    return {
        **metrics,
        **financials,
        **demand,
        "country_relations": country_relations(route),
        # Flat factor (decision 24) until the energy-based,
        # country-resolved model enriches it per route.
        "co2_g_per_pax_km": EMISSION_FACTORS["night_train"].g_per_pax_km,
    }


def country_relations(route: dict) -> list[str]:
    """Every country-to-country relation the route actually SERVES, as
    sorted "AA__BB" keys (§7.7 — the ranking dimension behind
    GET /api/proposals/stats).

    Read off the route's own od_pairs rather than its countries list: an
    OD pair exists only where a boarding-capable stop precedes an
    alighting-capable one (models/demand/stopgap.py), so a country merely
    transited, or reachable only boarding-to-boarding, contributes no
    relation. Same-country pairs are dropped — a relation is between two
    countries; domestic demand is a different question.
    """
    country_by_stop = {
        stop["stop_id"]: stop.get("country_code")
        for pair in route["trip_pairs"]
        for trip in (pair["outbound"], pair["return_trip"])
        for stop in ordered_stops(trip)
    }
    relations = {
        "__".join(sorted((origin, destination)))
        for pair in route["trip_pairs"]
        for od in pair.get("od_pairs", [])
        if (origin := country_by_stop.get(od["origin_stop_id"]))
        and (destination := country_by_stop.get(od["destination_stop_id"]))
        and origin != destination
    }
    return sorted(relations)


def _route_metrics(route: dict) -> dict:
    """total_distance_km/total_time_h/avg_speed_kmh/n_stops/countries/
    stop_ids, summed across both outbound and return trips. total_time_h
    is read from each trip's already-correct
    general_parameters.route_duration_min rather than re-summed from
    segments, which would silently omit slack_time_min."""
    total_distance_m = 0
    total_duration_min = 0
    countries: set[str] = set()
    stop_ids: list[str] = []
    seen_stop_ids: set[str] = set()

    for pair in route["trip_pairs"]:
        for stop in ordered_stops(pair["outbound"]):
            if stop["stop_id"] not in seen_stop_ids:
                seen_stop_ids.add(stop["stop_id"])
                stop_ids.append(stop["stop_id"])
        for trip in (pair["outbound"], pair["return_trip"]):
            total_duration_min += trip["general_parameters"]["route_duration_min"]
            for seg in trip["segments"]:
                total_distance_m += seg["distance_m"]
                countries.update(seg["country_distance_shares"])

    total_distance_km = round(total_distance_m / 1000.0, 1)
    total_time_h = round(total_duration_min / 60.0, 2)
    avg_speed_kmh = round(total_distance_km / total_time_h, 1) if total_time_h else 0.0

    return {
        "total_distance_km": total_distance_km,
        "total_time_h": total_time_h,
        "avg_speed_kmh": avg_speed_kmh,
        "n_stops": len(stop_ids),
        "countries": sorted(countries),
        "stop_ids": stop_ids,
    }


def _financial_kpis(evaluation: dict) -> dict:
    """cost/revenue/margin per train-km from views.route.data.per_train_km,
    and subsidy_eur_per_year (§9 locked decision 12: gap to target margin,
    max(0, -net_eur)) from views.route.data.per_year — both already
    rounded by the evaluation pipeline at a finer precision (4dp/2dp, see
    evaluation_serialize.py) than the schema's NUMERIC(10,2)/(14,2)
    columns, hence the explicit round() here rather than passing values
    through as-is."""
    route_data = evaluation["views"]["route"]["data"]
    per_train_km = route_data["per_train_km"]["all"]
    per_year = route_data["per_year"]["all"]
    return {
        "cost_eur_per_train_km": round(per_train_km["total_cost_eur"], 2),
        "revenue_eur_per_train_km": round(per_train_km["total_revenue_eur"], 2),
        "margin_eur_per_train_km": round(per_train_km["net_eur"], 2),
        "subsidy_eur_per_year": round(max(0.0, -per_year["net_eur"]), 2),
    }


def _placeholder_demand_kpis(
    total_distance_km: float, annual_revenue_eur: float, subsidy_eur_per_year: float
) -> dict:
    """Deterministic, route-metric-derived stand-ins for the demand-model
    KPIs (§8.1 placeholder policy) — stable across recomputes of the same
    route, plausible orders of magnitude, nothing more. Every value here
    is replaced once models/demand/ lands; demand_kpis_placeholder stays
    True until then. CO2 savings are each shifted mode's factor MINUS the
    night train's own emissions over the shifted km (a shifted passenger
    still emits on the train), in tonnes (/1e6 from g)."""
    night_train_g = EMISSION_FACTORS["night_train"].g_per_pax_km
    trips_per_year = (
        round(annual_revenue_eur / _PLACEHOLDER_AVG_FARE_EUR)
        if annual_revenue_eur
        else 0
    )
    trip_km_per_year = round(trips_per_year * total_distance_km)
    air_trips = round(trips_per_year * MODE_SHIFT_SHARES["air"])
    air_trip_km = round(air_trips * total_distance_km)
    car_trips = round(trips_per_year * MODE_SHIFT_SHARES["car"])
    car_trip_km = round(car_trips * total_distance_km)
    co2_savings_t = round(
        (
            air_trip_km * (EMISSION_FACTORS["air"].g_per_pax_km - night_train_g)
            + car_trip_km * (EMISSION_FACTORS["car"].g_per_pax_km - night_train_g)
        )
        / 1e6,
        1,
    )
    return {
        "demand_trips_per_year": trips_per_year,
        "demand_trip_km_per_year": trip_km_per_year,
        "shift_air_trips_per_year": air_trips,
        "shift_air_trip_km_per_year": air_trip_km,
        "shift_car_trips_per_year": car_trips,
        "shift_car_trip_km_per_year": car_trip_km,
        "co2_savings_t_per_year": co2_savings_t,
        "subsidy_eur_per_t_co2": (
            round(subsidy_eur_per_year / co2_savings_t, 2) if co2_savings_t else None
        ),
        "demand_kpis_placeholder": True,
    }
