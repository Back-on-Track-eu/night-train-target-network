"""
route_serialize.py
===================
Route serialization (domain → dict) and deserialization (dict → domain).
Lives at the API boundary — domain objects (Route, TripPair, etc.) have no
to_dict/from_dict methods. This includes geometry_id resolution:
route_from_dict() reads route['geometries'] and resolves each segment's
geometry_id back into real coordinates before constructing Segment — the
domain layer never sees geometry_id, only the full coordinate list it
always expected.

Split out of the former serialize.py (2026-07-06) into two domain files —
this one for Route, and evaluation_serialize.py for Breakdown/matrix/model
output — mirroring the existing params_serialize.py split for the params
endpoints. Keeps each file scoped to one domain rather than one large file
mixing route, evaluation, and params concerns.

Public interface:
  validate_route_dict(data)                     → list[str]  (structural check before deserializing)
  route_to_dict(route, scenario_id, tracks)      → dict       (for POST /api/route response)
  route_from_dict(data, loader, scenario_id)     → (Route, CompositionCollection)  (for POST /api/evaluation/calc)
"""

from __future__ import annotations

from models.route.route import (
    Route,
    TripPair,
    Schedule,
    SeasonalSchedule,
    Season,
    Frequency,
    Parking,
    Shunting,
    ODPair,
)
from models.route.trip import Stop, StopType, Segment, Trip
from models.params import Composition, TrackInfraCollection, CompositionCollection

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
    if not isinstance(schedule, dict) or not isinstance(
        schedule.get("seasonal_schedules"), list
    ):
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
        "auto_added": stop.auto_added,
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
        # Keyed by class_main (Seat/Couchette/Sleeper/Capsule/Catering),
        # not class_id, since 2026-07-06 — see Composition's field comments.
        "places_by_class": comp.places_by_class,
        "density_by_class": comp.density_by_class,
    }


_EXPOSED_TRACK_FIELDS = (
    "hsr_allowed",
    "min_boarding_time_min",
    "min_alighting_time_min",
    "terrain_score",
    "terrain_category",
    "buffer_quota_per",
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
        # just countries a stop happens to sit in. tracks.get() always
        # returns a real (possibly EU-average-defaulted) row now, never
        # None, since DBDataLoader.build_all_tracks() builds one entry per
        # country in input_params.countries — see TrackInfraCollection.
        "track_infrastructure": [
            _track_to_dict(tracks.get(cc)) for cc in sorted(route.countries)
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
        auto_added=d.get("auto_added", False),  # older payloads predate this field
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


def route_from_dict(
    data: dict, loader, scenario_id: int | None = None
) -> tuple[Route, CompositionCollection]:
    """Deserialize a Route from route_to_dict() output.
    loader: DBDataLoader — provides Composition objects from DB.
    Cost parameters are not stored in the JSON; they are reloaded from DB.

    scenario_id: explicit override — pins reconstruction to a different
    scenario than the one the route was built under (e.g. costing the
    same route against a what-if). Compositions themselves aren't
    scenario-scoped (see CompositionCollection), so this only affects
    Composition.indicative (computed from track/stop infrastructure costs,
    which ARE scenario-versioned) — not composition_id resolution, which
    always finds the same row regardless of scenario_id. If None, uses
    data["scenario_id"] (the route's own scenario, embedded by
    route_to_dict). Raises ValueError if neither is available.

    Returns (Route, CompositionCollection) — the collection is returned
    alongside the Route (rather than just the Route, as before 2026-07-06)
    so callers like api/evaluation.py can reuse it to document the actual
    composition/operator parameters an evaluation was costed with, without
    a second DB round-trip.
    """
    resolved_scenario_id = (
        scenario_id if scenario_id is not None else data.get("scenario_id")
    )
    if resolved_scenario_id is None:
        raise ValueError(
            "route_from_dict: no scenario_id provided and none embedded in "
            "the route JSON (data['scenario_id']) — cannot resolve which "
            "track/stop infrastructure version to reconstruct the route with."
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

    # Built once, not per trip pair — build_all_compositions() loads every
    # operator/coach type/composition in a fixed number of queries
    # regardless of how many trip pairs a Y-shaped route has.
    compositions = loader.build_all_compositions(resolved_scenario_id)

    trip_pairs = []
    for tp in data["trip_pairs"]:
        composition = compositions.get(tp["composition_id"])
        if composition is None:
            raise ValueError(f"Composition '{tp['composition_id']}' not found.")
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
        trip_pairs.append(
            TripPair(
                outbound=_trip_from_dict(tp["outbound"], geometries_by_id),
                return_trip=_trip_from_dict(tp["return_trip"], geometries_by_id),
                composition=composition,
                od_pairs=od_pairs,
            )
        )

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

    route = Route._create(
        route_id=data["route_id"],
        schedule=schedule,
        trip_pairs=trip_pairs,
        parkings=parkings,
        shuntings=shuntings,
    )
    return route, compositions
