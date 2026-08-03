"""
projection.py
=============
Fingerprint + gallery-summary projection (PROPOSALS_DESIGN.md §3.1/§5.4,
WP4). Pure functions over the same dicts POST /api/proposal/calc already
returns (route_to_dict() shape + the evaluation "views" block) — no DB
access, no domain-object construction. Lives under adapters/proposal/
because the repository calls it during publish (WP5); adapters must never
be imported *by* the pure serializers, only the other way around (see
AGENTS.md's layering note).

Public interface:
  route_fingerprint(route)            → str   (§3.1 — SHA-256 over the
                                                 route's resolved stops/
                                                 times/geometry, prefix-
                                                 and-ID agnostic by
                                                 construction)
  build_summary_row(route, evaluation) → dict  (§5.4 — the non-identity
                                                 proposals.proposal_summaries
                                                 columns: route metrics,
                                                 financial KPIs, simplified
                                                 geometry, placeholder
                                                 demand KPIs. Identity
                                                 columns — proposal_id,
                                                 user_id, composition_id,
                                                 scenario_id, name,
                                                 versions — are the
                                                 repository's concern at
                                                 publish time, not this
                                                 module's.)

Callers: api/helpers/proposal_compute.py (fingerprint only, for the
merged compute response); repository.py from WP5 onward (both functions,
at publish/refresh time).
"""

from __future__ import annotations

import hashlib
import json

# Douglas-Peucker tolerance for proposal_summaries.geom_simplified, in
# degrees (route geometry is stored unprojected, EPSG:4326) — a first-pass
# placeholder pending real tuning against gallery-map zoom levels (§5.4's
# own wording: "tolerance tuned for gallery-map zoom levels"). ~0.0005° is
# roughly 50m at mid-European latitudes.
_GEOM_SIMPLIFY_TOLERANCE_DEG = 0.0005

# Placeholder demand-KPI assumptions (§8.1: "deterministic fakes derived
# from route metrics ... plausible orders of magnitude for UI development")
# — deliberately crude, replaced wholesale once models/demand/ exists.
# Never treat these as real modelling assumptions.
_PLACEHOLDER_AVG_FARE_EUR = 120.0
_PLACEHOLDER_AIR_SHIFT_SHARE = 0.35
_PLACEHOLDER_CAR_SHIFT_SHARE = 0.20
_PLACEHOLDER_CO2_PER_AIR_PAX_KM_T = 0.00020
_PLACEHOLDER_CO2_PER_CAR_PAX_KM_T = 0.00007


# =============================================================================
# FINGERPRINT — §3.1
# =============================================================================


def route_fingerprint(route: dict) -> str:
    """SHA-256 over a canonical extract of the built route: per trip pair
    (list order preserved), per trip (outbound then return), the ordered
    (stop_id, arrival_time_min, departure_time_min) list plus that trip's
    concatenated segment geometry, coordinates rounded to 5 decimals
    (~1m — absorbs float noise). No route_id/trip_id/geometry_id ever
    enters the hash, only stop_id (a stable, unprefixed reference) — so
    ephemeral (neutral-id) and published (P{id}_V{n}_-prefixed) forms of
    the identical route hash identically by construction, without needing
    to strip anything. Returned as 'sha256:<hex>'.
    """
    geometries_by_id = {g["id"]: g["coords"] for g in route.get("geometries", [])}
    canonical = [
        {
            "outbound": _canonical_trip(pair["outbound"], geometries_by_id),
            "return_trip": _canonical_trip(pair["return_trip"], geometries_by_id),
        }
        for pair in route["trip_pairs"]
    ]
    # Fixed key insertion order above + separators with no whitespace make
    # this dump byte-identical for byte-identical input, run to run.
    canonical_json = json.dumps(canonical, separators=(",", ":"))
    digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _canonical_trip(trip: dict, geometries_by_id: dict[str, list]) -> dict:
    stops = _ordered_stops(trip)
    coords = [
        pt
        for seg in trip["segments"]
        for pt in geometries_by_id.get(seg["geometry_id"], [])
    ]
    return {
        "stops": [
            [s["stop_id"], s["arrival_time_min"], s["departure_time_min"]]
            for s in stops
        ],
        "geometry": [[round(c, 5) for c in pt] for pt in coords],
    }


def _ordered_stops(trip: dict) -> list[dict]:
    """A trip's stops in travel order — the first segment's origin, then
    every segment's destination. Shared by the fingerprint's canonical
    extract and the route-metrics stop count/list below."""
    segments = trip["segments"]
    return [segments[0]["from_stop"]] + [seg["to_stop"] for seg in segments]


# =============================================================================
# SUMMARY ROW — §5.4
# =============================================================================


def build_summary_row(route: dict, evaluation: dict) -> dict:
    """The non-identity proposals.proposal_summaries columns for one
    (route, evaluation) pair, in the shape ready to merge with the
    identity columns the publish repository adds (proposal_id, user_id,
    composition_id, scenario_id, name, route_builder_version,
    calc_version)."""
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
    return {**metrics, **financials, **demand}


def _route_metrics(route: dict) -> dict:
    """total_distance_km/total_time_h/avg_speed_kmh/n_stops/countries/
    stop_ids/geom_simplified — computed the way today's
    proposal_summary_to_dict does (summed across both outbound and return
    trips), except total_time_h is read from each trip's already-correct
    general_parameters.route_duration_min rather than re-summed from
    segments, which today's helper does and which silently omits
    slack_time_min."""
    total_distance_m = 0
    total_duration_min = 0
    countries: set[str] = set()
    stop_ids: list[str] = []
    seen_stop_ids: set[str] = set()

    for pair in route["trip_pairs"]:
        for stop in _ordered_stops(pair["outbound"]):
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
        "geom_simplified": _geom_simplified(route),
    }


def _geom_simplified(route: dict) -> dict:
    """Per-segment shapes concatenated into one LineString per trip
    (outbound and return, every pair), collected into a MultiLineString,
    Douglas-Peucker simplified — the geom_simplified GeoJSON handed to the
    repository for ST_GeomFromGeoJSON/ST_SetSRID at insert time (WP5)."""
    from shapely.geometry import LineString, MultiLineString, mapping

    geometries_by_id = {g["id"]: g["coords"] for g in route.get("geometries", [])}
    lines = []
    for pair in route["trip_pairs"]:
        for trip in (pair["outbound"], pair["return_trip"]):
            coords = [
                pt
                for seg in trip["segments"]
                for pt in geometries_by_id.get(seg["geometry_id"], [])
            ]
            if len(coords) >= 2:
                lines.append(LineString(coords))

    simplified = MultiLineString(lines).simplify(
        _GEOM_SIMPLIFY_TOLERANCE_DEG, preserve_topology=False
    )
    # simplify() on a MultiLineString collapses to a plain LineString when
    # only one line survives — normalize back so geom_simplified always
    # matches the column's MultiLineString type.
    if simplified.geom_type == "LineString":
        simplified = MultiLineString([simplified])
    return mapping(simplified)


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
    True until then."""
    trips_per_year = (
        round(annual_revenue_eur / _PLACEHOLDER_AVG_FARE_EUR)
        if annual_revenue_eur
        else 0
    )
    trip_km_per_year = round(trips_per_year * total_distance_km)
    air_trips = round(trips_per_year * _PLACEHOLDER_AIR_SHIFT_SHARE)
    air_trip_km = round(air_trips * total_distance_km)
    car_trips = round(trips_per_year * _PLACEHOLDER_CAR_SHIFT_SHARE)
    car_trip_km = round(car_trips * total_distance_km)
    co2_savings_t = round(
        air_trip_km * _PLACEHOLDER_CO2_PER_AIR_PAX_KM_T
        + car_trip_km * _PLACEHOLDER_CO2_PER_CAR_PAX_KM_T,
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
