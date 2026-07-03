"""
serialize.py
============
All serialization (domain → dict) and deserialization (dict → domain)
for the evaluation pipeline. Lives at the API boundary — domain objects
(Route, Breakdown, etc.) have no to_dict/from_dict methods.

Public interface:
  route_to_dict(route)            → dict  (for POST /api/route response)
  route_from_dict(data, loader)   → Route (for POST /api/evaluation/calc)
  breakdown_to_dict(breakdown)    → dict  (for evaluation response)
  matrix_to_dict(matrix)          → dict  (for matrix views in response)
"""

from __future__ import annotations

from models.route.route import (
    Route, TripPair, Schedule, SeasonalSchedule, Season, Frequency,
    Parking, Shunting, ODPair,
)
from models.route.trip import Stop, StopType, Segment, Trip
from models.evaluation.views import (
    Breakdown,
    normalise_per_operating_day, normalise_per_trip_km,
    normalise_per_available_place_km, normalise_per_sold_place_km,
)

# =============================================================================
# ROUTE — validate
# =============================================================================

def validate_route_dict(data: dict) -> list[str]:
    """Structural validation of a route_to_dict() payload before deserialization.
    Returns a list of error messages, empty if valid."""
    errors = []
    if not isinstance(data.get("route_id"), str):
        errors.append("route.route_id must be a string.")
    schedule = data.get("schedule")
    if not isinstance(schedule, dict) or not isinstance(schedule.get("seasonal_schedules"), list):
        errors.append("route.schedule.seasonal_schedules must be a list.")
    trip_pairs = data.get("trip_pairs")
    if not isinstance(trip_pairs, list) or len(trip_pairs) == 0:
        errors.append("route.trip_pairs must be a non-empty list.")
    else:
        for i, tp in enumerate(trip_pairs):
            prefix = f"route.trip_pairs[{i}]"
            if not isinstance(tp.get("composition_id"), str):
                errors.append(f"{prefix}.composition_id must be a string.")
            for direction in ("outbound", "return_trip"):
                trip = tp.get(direction)
                if not isinstance(trip, dict):
                    errors.append(f"{prefix}.{direction} must be an object.")
                elif not isinstance(trip.get("segments"), list):
                    errors.append(f"{prefix}.{direction}.segments must be a list.")
    return errors

# =============================================================================
# ROUTE — serialize
# =============================================================================

def _stop_to_dict(stop: Stop) -> dict:
    return {
        "stop_id": stop.stop_id,
        "stop_name": stop.stop_name,
        "country_code": stop.country_code,
        "lat": stop.lat,
        "lon": stop.lon,
        "stop_type": stop.stop_type.value,
        "arrival_time_min": stop.arrival_time_min,
        "departure_time_min": stop.departure_time_min,
    }

def _segment_to_dict(seg: Segment) -> dict:
    return {
        "from_stop": _stop_to_dict(seg.from_stop),
        "to_stop": _stop_to_dict(seg.to_stop),
        "geometry": seg.geometry,
        "distance_m": seg.distance_m,
        "driving_time_min": seg.driving_time_min,
        "buffer_time_min": seg.buffer_time_min,
        "energy_kwh": seg.energy_kwh,
        "country_distance_shares": seg.country_distance_shares,
        "country_time_shares": seg.country_time_shares,
    }

def _trip_to_dict(trip: Trip) -> dict:
    return {
        "trip_id": trip.trip_id,
        "direction": trip.direction,
        "segments": [_segment_to_dict(s) for s in trip.segments],
    }

def route_to_dict(route: Route) -> dict:
    """Serialize a Route to a JSON-compatible dict.
    Round-trips via route_from_dict(data, loader)."""
    return {
        "route_id": route.route_id,
        "schedule": {
            "seasonal_schedules": [
                {"season": ss.season.value, "frequency": ss.frequency.value}
                for ss in route.schedule.seasonal_schedules
            ]
        },
        "trip_pairs": [
            {
                "composition_id": pair.composition.comp_id,
                "od_pairs": [
                    {
                        "origin_stop_id": od.origin_stop_id,
                        "destination_stop_id": od.destination_stop_id,
                        "class_main": od.class_main,
                        "trip_id": od.trip_id,
                        "places_sold": od.places_sold,
                        "avg_price": od.avg_price,
                    }
                    for od in pair.od_pairs
                ],
                "outbound": _trip_to_dict(pair.outbound),
                "return_trip": _trip_to_dict(pair.return_trip),
            }
            for pair in route.trip_pairs
        ],
        "parkings": [
            {
                "stop_id": p.stop_id,
                "stop_name": p.stop_name,
                "country_code": p.country_code,
                "trip_ids": p.trip_ids,
            }
            for p in route.parkings
        ],
        "shuntings": [
            {
                "stop_id": s.stop_id,
                "stop_name": s.stop_name,
                "country_code": s.country_code,
                "trip_id": s.trip_id,
            }
            for s in route.shuntings
        ],
    }

# =============================================================================
# ROUTE — deserialize
# =============================================================================

def _stop_from_dict(d: dict) -> Stop:
    return Stop(
        stop_id=d["stop_id"],
        stop_name=d["stop_name"],
        country_code=d["country_code"],
        lat=float(d["lat"]),
        lon=float(d["lon"]),
        stop_type=StopType(d["stop_type"]),
        arrival_time_min=d.get("arrival_time_min"),
        departure_time_min=d.get("departure_time_min"),
    )

def _segment_from_dict(d: dict) -> Segment:
    return Segment(
        from_stop=_stop_from_dict(d["from_stop"]),
        to_stop=_stop_from_dict(d["to_stop"]),
        geometry=d["geometry"],
        distance_m=int(d["distance_m"]),
        driving_time_min=int(d["driving_time_min"]),
        buffer_time_min=int(d["buffer_time_min"]),
        energy_kwh=float(d["energy_kwh"]),
        country_distance_shares=d["country_distance_shares"],
        country_time_shares=d["country_time_shares"],
    )

def _trip_from_dict(d: dict) -> Trip:
    return Trip(
        trip_id=d["trip_id"],
        direction=int(d["direction"]),
        segments=[_segment_from_dict(s) for s in d["segments"]],
    )

def route_from_dict(data: dict, loader) -> Route:
    """Deserialize a Route from route_to_dict() output.
    loader: DBDataLoader — provides Composition objects from DB.
    Cost parameters are not stored in the JSON; they are reloaded from DB."""
    schedule = Schedule(
        seasonal_schedules=[
            SeasonalSchedule(
                season=Season(ss["season"]),
                frequency=Frequency(ss["frequency"]),
            )
            for ss in data["schedule"]["seasonal_schedules"]
        ]
    )

    trip_pairs = []
    for tp in data["trip_pairs"]:
        composition, _ = loader.build_composition(tp["composition_id"])
        od_pairs = [
            ODPair(
                origin_stop_id=od["origin_stop_id"],
                destination_stop_id=od["destination_stop_id"],
                class_main=od["class_main"],
                trip_id=od["trip_id"],
                places_sold=int(od["places_sold"]),
                avg_price=float(od["avg_price"]),
            )
            for od in tp.get("od_pairs", [])
        ]
        trip_pairs.append(TripPair(
            outbound=_trip_from_dict(tp["outbound"]),
            return_trip=_trip_from_dict(tp["return_trip"]),
            composition=composition,
            od_pairs=od_pairs,
        ))

    parkings = [
        Parking(
            stop_id=p["stop_id"],
            stop_name=p["stop_name"],
            country_code=p["country_code"],
            trip_ids=p["trip_ids"],
        )
        for p in data.get("parkings", [])
    ]

    shuntings = [
        Shunting(
            stop_id=s["stop_id"],
            stop_name=s["stop_name"],
            country_code=s["country_code"],
            trip_id=s["trip_id"],
        )
        for s in data.get("shuntings", [])
    ]

    return Route._create(
        route_id=data["route_id"],
        schedule=schedule,
        trip_pairs=trip_pairs,
        parkings=parkings,
        shuntings=shuntings,
    )

# =============================================================================
# BREAKDOWN — serialize
# =============================================================================

def breakdown_to_dict(b: Breakdown) -> dict:
    """Serialize a Breakdown tree to a nested JSON-compatible dict.
    Includes computed summary fields (total_cost_eur, net_eur) at the top."""
    return {
        "cost": {
            "operator": {
                "variable": {
                    "driver_eur": b.cost.operator.variable.driver_eur,
                    "crew_eur": b.cost.operator.variable.crew_eur,
                    "coach_maintenance_eur": b.cost.operator.variable.coach_maintenance_eur,
                    "loco_eur": b.cost.operator.variable.loco_eur,
                    "svc_stockings_eur": b.cost.operator.variable.svc_stockings_eur,
                    "var_overhead_eur": b.cost.operator.variable.var_overhead_eur,
                    "total_eur": b.cost.operator.variable.total_eur,
                },
                "fixed": {
                    "coach_amortisation_eur": b.cost.operator.fixed.coach_amortisation_eur,
                    "financing_eur": b.cost.operator.fixed.financing_eur,
                    "fix_overhead_eur": b.cost.operator.fixed.fix_overhead_eur,
                    "cleaning_eur": b.cost.operator.fixed.cleaning_eur,
                    "shunting_eur": b.cost.operator.fixed.shunting_eur,
                    "total_eur": b.cost.operator.fixed.total_eur,
                },
                "total_eur": b.cost.operator.total_eur,
            },
            "infrastructure": {
                "tac_eur": b.cost.infrastructure.tac_eur,
                "energy_eur": b.cost.infrastructure.energy_eur,
                "station_charge_eur": b.cost.infrastructure.station_charge_eur,
                "parking_eur": b.cost.infrastructure.parking_eur,
                "total_eur": b.cost.infrastructure.total_eur,
            },
            "total_eur": b.cost.total_eur,
        },
        "revenue": {
            "ticket_revenue_eur": b.revenue.ticket_revenue_eur,
            "total_eur": b.revenue.total_eur,
        },
        "margin": {
            "ebit_margin_eur": b.margin.ebit_margin_eur,
            "total_eur": b.margin.total_eur,
        },
        "total_cost_eur": b.total_cost_eur,
        "total_revenue_eur": b.total_revenue_eur,
        "net_eur": b.net_eur,
    }

def matrix_to_dict(
    matrix: dict[tuple[str, str], Breakdown],
    route: Route,
    trip_pair_by_key: dict[str, TripPair] | None = None,
) -> dict:
    """Convert a (pair_key, dimension_key) → Breakdown matrix to a nested dict
    with all normalisations per cell. trip_pair_by_key maps outbound trip_id
    → TripPair for per-pair normalisation denominators."""
    out: dict[str, dict[str, dict]] = {}
    for (pair_key, dim_key), b in matrix.items():
        trip_pair = (trip_pair_by_key or {}).get(pair_key) if pair_key != "all" else None
        out.setdefault(pair_key, {})[dim_key] = normalise_all_to_dict(b, route, trip_pair)
    return out

def normalise_all_to_dict(
    breakdown: Breakdown,
    route: Route,
    trip_pair: TripPair | None = None,
) -> dict:
    """All normalisations of a Breakdown as a serialized dict.
    Combines computation (normalisers) and serialization in one step
    since the result is always destined for JSON output."""
    return {
        "per_year": breakdown_to_dict(breakdown),
        "per_operating_day": breakdown_to_dict(normalise_per_operating_day(breakdown, route)),
        "per_trip_km": breakdown_to_dict(normalise_per_trip_km(breakdown, route, trip_pair)),
        "per_available_place_km": breakdown_to_dict(normalise_per_available_place_km(breakdown, route, trip_pair)),
        "per_sold_place_km": breakdown_to_dict(normalise_per_sold_place_km(breakdown, route, trip_pair)),
    }