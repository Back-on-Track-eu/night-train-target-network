"""
serialize.py
============
All serialization (domain → dict) and deserialization (dict → domain)
for the evaluation pipeline. Lives at the API boundary — domain objects
(Route, Breakdown, etc.) have no to_dict/from_dict methods. This includes
geometry_id resolution: route_from_dict() reads route['geometries'] and
resolves each segment's geometry_id back into real coordinates before
constructing Segment — the domain layer never sees geometry_id, only
the full coordinate list it always expected.

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
from models.params import Composition, TrackInfraCollection
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
    if "geometries" in data and not isinstance(data["geometries"], list):
        errors.append("route.geometries must be a list if present.")
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

def _segment_to_dict(seg: Segment, geometry_id: str) -> dict:
    """geometry_id: caller-assigned reference into route['geometries'] —
    see _trip_to_dict(). The actual coordinate list is never embedded here."""
    return {
        "from_stop": _stop_to_dict(seg.from_stop),
        "to_stop": _stop_to_dict(seg.to_stop),
        "geometry_id": geometry_id,
        "distance_m": seg.distance_m,
        "driving_time_min": seg.driving_time_min,
        "buffer_time_min": seg.buffer_time_min,
        "energy_kwh": seg.energy_kwh,
        "country_distance_shares": seg.country_distance_shares,
        "country_time_shares": seg.country_time_shares,
    }

def _trip_to_dict(trip: Trip, geometries: list[dict]) -> dict:
    """geometries: shared collector this trip's segments append {id, coords}
    entries to. Every trip in the route appends into the same list, which
    route_to_dict() attaches once, as route['geometries'], after all
    trip_pairs are built — keeps the bulky coordinate data out of segments
    entirely rather than embedding it inline per-segment."""
    segments = []
    for i, seg in enumerate(trip.segments):
        geometry_id = f"{trip.trip_id}_L{i}"
        geometries.append({"id": geometry_id, "coords": seg.geometry})
        segments.append(_segment_to_dict(seg, geometry_id))
    return {
        "trip_id": trip.trip_id,
        "direction": trip.direction,
        "segments": segments,
    }

def _composition_to_dict(comp: Composition) -> dict:
    """Physics-relevant subset of Composition — NOT the full object.
    Composition mixes routing/energy/capacity fields with cost fields
    (driver_costs_eur_h, purchase_coach_eur, etc.); this endpoint is
    physics-only (see route.py's module docstring), so every *_eur*/*_per
    cost field and driver_factor (a crew-cost input only) are deliberately
    excluded here. Full cost breakdown lives in POST /api/evaluation/calc."""
    return {
        "comp_id": comp.comp_id,
        "comp_description": comp.comp_description,
        "operator_id": comp.operator_id,
        "max_speed_kmh": comp.max_speed_kmh,
        "hsr_allowed": comp.hsr_allowed,
        "min_boarding_time_min": comp.min_boarding_time_min,
        "min_alighting_time_min": comp.min_alighting_time_min,
        "energy_factor_weight": comp.energy_factor_weight,
        "energy_factor_speed": comp.energy_factor_speed,
        "energy_factor_terrain": comp.energy_factor_terrain,
        "total_weight_t": comp.total_weight_t,
        "total_crew": comp.total_crew,
        "places_by_class": comp.places_by_class,
        "density_by_class": comp.density_by_class,
    }

_EXPOSED_TRACK_FIELDS = (
    "hsr_allowed", "min_boarding_time_min", "min_alighting_time_min",
    "terrain_score", "terrain_category", "buffer_quota_per",
)
"""Which TrackInfrastructure fields _track_to_dict() actually shows — used
to filter defaulted_fields down to fields the caller can actually see
(no point flagging tac_eur_train_km as defaulted when tac_eur_train_km
itself isn't even in the response)."""

def _track_to_dict(track) -> dict:
    """Physics-relevant subset of TrackInfrastructure — NOT the full object.
    Same reasoning as _composition_to_dict(): tac_eur_train_km, parking_eur_day,
    shunting_eur_event, energy_price_eur_kwh, and every *_src provenance field
    are deliberately excluded here.

    defaulted_fields IS included, unlike the cost fields — it's not a
    monetary value, and it's exactly the kind of thing this manual-testing
    response exists to surface: which of the fields shown below came from
    the EU-average default rather than this country's own data (e.g. a
    real row with a couple of None columns still resolves those specific
    fields from the default template — see TrackInfrastructure.field_is_default).
    There's no whole-row equivalent here: route_factory._check_country_coverage()
    already rejects a route outright if a country has no row in
    track_infrastructures at all, so every TrackInfrastructure reaching this
    function is guaranteed to be a real row."""
    return {
        "country_code": track.country_code,
        "defaulted_fields": [
            f for f in _EXPOSED_TRACK_FIELDS if track.field_is_default.get(f)
        ],
        "hsr_allowed": track.hsr_allowed,
        "min_boarding_time_min": track.min_boarding_time_min,
        "min_alighting_time_min": track.min_alighting_time_min,
        "terrain_score": track.terrain_score,
        "terrain_category": track.terrain_category,
        "buffer_quota_per": track.buffer_quota_per,
    }

def route_to_dict(route: Route, scenario_id: int, tracks: TrackInfraCollection) -> dict:
    """Serialize a Route to a JSON-compatible dict.
    Round-trips via route_from_dict(data, loader).

    scenario_id: the concrete scenario this Route was built under (from
    RouteProvenance.scenario_id — never None, already resolved). Embedded
    in the dict, not on the Route object itself (Route stays physics-only
    per the project's separation-of-concerns rule) — this is what lets
    route_from_dict() reconstruct the same Composition/parameters later
    without the caller needing to separately track and resupply it.

    tracks: the full TrackInfraCollection this Route was built under (from
    RouteProvenance.tracks) — filtered down to just the countries this
    route's stops actually touch and serialized as route['track_infrastructure'].
    Not needed for round-tripping (route_from_dict() never reads it back,
    it reloads tracks fresh from DB via scenario_id like everything else) —
    purely informational, for manually cross-checking physics against the
    exact parameter values a build used.

    Segment geometry is pulled out into route['geometries'] (a flat list of
    {id, coords}, referenced from each segment by geometry_id) rather than
    embedded inline per-segment — pure readability reorg, same total data,
    just out of the way when scanning stops/times/physics.
    """
    geometries: list[dict] = []
    trip_pairs = [
        {
            "composition_id": pair.composition.comp_id,
            "composition": _composition_to_dict(pair.composition),
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
            "outbound": _trip_to_dict(pair.outbound, geometries),
            "return_trip": _trip_to_dict(pair.return_trip, geometries),
        }
        for pair in route.trip_pairs
    ]

    return {
        "route_id": route.route_id,
        "scenario_id": scenario_id,
        "schedule": {
            "seasonal_schedules": [
                {"season": ss.season.value, "frequency": ss.frequency.value}
                for ss in route.schedule.seasonal_schedules
            ]
        },
        "trip_pairs": trip_pairs,
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
        # sorted(route.countries) — reuses the existing property rather than
        # re-deriving country codes here; it already correctly includes
        # transit-only countries (via segment.country_distance_shares), not
        # just countries a stop happens to sit in. get_or_default() always
        # returns a real (possibly EU-average-defaulted) row now, never None.
        "track_infrastructure": [
            _track_to_dict(tracks.get_or_default(cc))
            for cc in sorted(route.countries)
        ],
        "geometries": geometries,  # last — keeps the bulky coordinate data out of the way when scanning the rest of route
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

def _segment_from_dict(d: dict, geometries_by_id: dict[str, list]) -> Segment:
    """geometries_by_id: {geometry_id: coords} built once in route_from_dict()
    from route['geometries']. Resolves geometry_id back into the real
    coordinate list here — Segment itself always just wants geometry, it
    never knows the id indirection exists."""
    geometry_id = d["geometry_id"]
    coords = geometries_by_id.get(geometry_id)
    if coords is None:
        raise ValueError(
            f"route_from_dict: no entry in route['geometries'] for geometry_id '{geometry_id}'."
        )
    return Segment(
        from_stop=_stop_from_dict(d["from_stop"]),
        to_stop=_stop_from_dict(d["to_stop"]),
        geometry=coords,
        distance_m=int(d["distance_m"]),
        driving_time_min=int(d["driving_time_min"]),
        buffer_time_min=int(d["buffer_time_min"]),
        energy_kwh=float(d["energy_kwh"]),
        country_distance_shares=d["country_distance_shares"],
        country_time_shares=d["country_time_shares"],
    )

def _trip_from_dict(d: dict, geometries_by_id: dict[str, list]) -> Trip:
    return Trip(
        trip_id=d["trip_id"],
        direction=int(d["direction"]),
        segments=[_segment_from_dict(s, geometries_by_id) for s in d["segments"]],
    )

def route_from_dict(data: dict, loader, scenario_id: int | None = None) -> Route:
    """Deserialize a Route from route_to_dict() output.
    loader: DBDataLoader — provides Composition objects from DB.
    Cost parameters are not stored in the JSON; they are reloaded from DB.

    scenario_id: explicit override — pins reconstruction to a different
    scenario than the one the route was built under (e.g. costing the
    same route against a what-if). If None, uses data["scenario_id"] (the
    route's own scenario, embedded by route_to_dict) — this is the normal
    path, and is what keeps a reconstructed Route's Composition consistent
    with the parameters that produced its physics in the first place.
    Raises ValueError if neither is available.
    """
    resolved_scenario_id = scenario_id if scenario_id is not None else data.get("scenario_id")
    if resolved_scenario_id is None:
        raise ValueError(
            "route_from_dict: no scenario_id provided and none embedded in "
            "the route JSON (data['scenario_id']) — cannot resolve which "
            "parameter versions to reconstruct the route's Composition from."
        )

    schedule = Schedule(
        seasonal_schedules=[
            SeasonalSchedule(
                season=Season(ss["season"]),
                frequency=Frequency(ss["frequency"]),
            )
            for ss in data["schedule"]["seasonal_schedules"]
        ]
    )

    geometries_by_id = {g["id"]: g["coords"] for g in data.get("geometries", [])}

    trip_pairs = []
    for tp in data["trip_pairs"]:
        composition, _ = loader.build_composition(tp["composition_id"], resolved_scenario_id)
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
            outbound=_trip_from_dict(tp["outbound"], geometries_by_id),
            return_trip=_trip_from_dict(tp["return_trip"], geometries_by_id),
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