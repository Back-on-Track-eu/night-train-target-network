"""
helpers.py
==========
Plain-Python helpers shared across the test suite — HTTP wrappers for the
two POST endpoints, navigation over route/evaluation JSON, and demand
(od_pairs) construction.

Everything here derives strictly from data actually present in the API
responses (route_to_dict() / evaluation calc output). Nothing is fabricated:
stop times, per-trip stats, and per-country km are all reconstructible from
the segments a trip carries. Fields the API genuinely does not expose have
no helper here — tests for such fields don't exist in this suite.
"""

import requests

ROUTE_URL = "/api/route/plan"
EVAL_URL = "/api/evaluation/calc"
PROPOSAL_URL = "/api/proposal"
PROPOSALS_URL = "/api/proposals"
FEEDBACK_URL = "/api/feedback"
FEEDBACK_CATEGORIES_URL = "/api/feedback/categories"
SCENARIOS_URL = "/api/scenarios"

# Mirrors models/route/version.py: DAYS_PER_OPERATING_WEEK / WEEKS_PER_SEASON.
_DAYS_PER_WEEK = {"daily": 7, "three_per_week": 3}
_WEEKS_PER_SEASON = 26


# =============================================================================
# HTTP wrappers
# =============================================================================


def build_route(
    api_base: str,
    stops: list[str],
    composition_id: str = "STD-7.1",
    timeout: int = 90,
    **extra,
) -> dict:
    """POST /api/route/plan with the given stops/composition (plus any extra
    request fields, e.g. scenario_id or routing_mode) and return the route dict.
    Asserts 200 — callers testing error paths post directly instead."""
    body = {"stops": stops, "composition_id": composition_id, **extra}
    resp = requests.post(f"{api_base}{ROUTE_URL}", json=body, timeout=timeout)
    assert resp.status_code == 200, f"route/plan failed: {resp.text[:300]}"
    return resp.json()["route"]


def evaluate(
    api_base: str, route: dict, scenario_id: int | None = None, timeout: int = 60
) -> dict:
    """POST /api/evaluation/calc for a route dict (optionally overriding the
    scenario) and return the full response body. Asserts 200."""
    body: dict = {"route": route}
    if scenario_id is not None:
        body["scenario_id"] = scenario_id
    resp = requests.post(f"{api_base}{EVAL_URL}", json=body, timeout=timeout)
    assert resp.status_code == 200, f"evaluation/calc failed: {resp.text[:300]}"
    return resp.json()


def save_proposal(
    api_base: str,
    route: dict,
    user_id: int,
    timeout: int = 30,
    evaluation: dict | None = None,
    route_builder_version: str = "test",
    request: dict | None = None,
    **extra,
) -> dict:
    """POST /api/proposal for a route dict as the given user. Wraps `route`
    into a route_body envelope ({route_builder_version, request,
    route} — route_builder_version/request default to test-only placeholder
    values unless overridden) since the endpoint now requires the whole
    POST /api/route/plan response, not just its route section. `evaluation`,
    if given, is passed through as evaluation_body verbatim — build it
    via evaluate(route) first so its input.route matches `route` (the
    endpoint rejects a mismatch). Any other kwargs (e.g. change_log) go at
    the top level of the save body. Asserts 201 — callers testing error
    paths post directly instead."""
    body = {
        "user_id": user_id,
        "route_body": {
            "route_builder_version": route_builder_version,
            "request": request if request is not None else {},
            "route": route,
        },
        **extra,
    }
    if evaluation is not None:
        body["evaluation_body"] = evaluation
    resp = requests.post(f"{api_base}{PROPOSAL_URL}", json=body, timeout=timeout)
    assert resp.status_code == 201, f"proposal save failed: {resp.text[:300]}"
    return resp.json()


# =============================================================================
# Route JSON navigation
# =============================================================================


def all_trips(route: dict) -> list[dict]:
    """Every trip (outbound + return of every trip pair), each enriched with
    its pair's composition_id/composition for convenience."""
    trips = []
    for pair in route["trip_pairs"]:
        for trip in (pair["outbound"], pair["return_trip"]):
            trips.append(
                {
                    **trip,
                    "composition_id": pair["composition_id"],
                    "composition": pair["composition"],
                }
            )
    return trips


def trip_by_direction(route: dict, direction: int, pair_index: int = 0) -> dict:
    """The outbound (0) or return (1) trip of one trip pair."""
    pair = route["trip_pairs"][pair_index]
    return pair["outbound"] if direction == 0 else pair["return_trip"]


def stop_times(trip: dict) -> list[dict]:
    """Ordered stop list of a trip, reconstructed from its segments
    (first segment's from_stop, then every segment's to_stop), each stop
    enriched with dwell_time_min (departure − arrival, None at terminals)."""
    segments = trip["segments"]
    if not segments:
        return []
    stops = [segments[0]["from_stop"]] + [seg["to_stop"] for seg in segments]
    result = []
    for s in stops:
        arr, dep = s.get("arrival_time_min"), s.get("departure_time_min")
        dwell = (dep - arr) if (arr is not None and dep is not None) else None
        result.append({**s, "dwell_time_min": dwell})
    return result


def trip_distance_km(trip: dict) -> float:
    """Total trip distance in km — sum of segment distances."""
    return sum(seg["distance_m"] for seg in trip["segments"]) / 1000.0


def trip_energy_kwh(trip: dict) -> float:
    """Total trip traction energy in kWh — sum of segment energies."""
    return sum(seg["energy_kwh"] for seg in trip["segments"])


def trip_driving_time_min(trip: dict) -> int:
    """Total driving time in minutes — sum of segment driving times."""
    return sum(seg["driving_time_min"] for seg in trip["segments"])


def country_km(trip: dict) -> dict[str, float]:
    """Distance in km attributed to each country a trip crosses, from each
    segment's country_distance_shares — the same allocation the evaluation
    model uses for TAC (see models/evaluation/calc.py:_calc_segment_cost)."""
    km: dict[str, float] = {}
    for seg in trip["segments"]:
        for cc, share in seg["country_distance_shares"].items():
            km[cc] = km.get(cc, 0.0) + seg["distance_m"] / 1000.0 * share
    return km


def route_countries(route: dict) -> set[str]:
    """Every country any trip touches (including transit-only countries)."""
    return {
        cc
        for trip in all_trips(route)
        for seg in trip["segments"]
        for cc in seg["country_distance_shares"]
    }


def operating_days(route: dict) -> int:
    """Operating days per year from the route's embedded schedule — mirrors
    Schedule.operating_days_per_year (days_per_week × 26 weeks per season)."""
    return sum(
        _DAYS_PER_WEEK[ss["frequency"]] * _WEEKS_PER_SEASON
        for ss in route["schedule"]["seasonal_schedules"]
    )


# =============================================================================
# Demand construction (od_pairs)
# =============================================================================


def inject_demand(route: dict, od_pairs: list[dict]) -> dict:
    """Return a copy of the route with od_pairs set on every trip pair.
    Demand travels into evaluation/calc entirely inside the route JSON —
    od_pairs (each entry carrying an explicit trip_id) is the only mechanism."""
    route = dict(route)
    route["trip_pairs"] = [{**tp, "od_pairs": od_pairs} for tp in route["trip_pairs"]]
    return route


def replicated_od(route: dict, template: list[dict]) -> list[dict]:
    """Replicate each OD template entry once per trip (outbound + return of
    every pair), filling trip_id. Origins/destinations are used as given —
    entries against a trip's travel direction still count for revenue but
    contribute 0 sold place-km (see views.py:normalise_per_sold_place_km)."""
    ods = []
    for trip in all_trips(route):
        for od in template:
            ods.append({**od, "trip_id": trip["trip_id"]})
    return ods


def directional_od(
    route: dict, class_main: str, places_sold: int, avg_price: float
) -> list[dict]:
    """One full-route OD per trip, oriented in that trip's own travel
    direction (first stop → last stop). Gives every trip a well-defined,
    non-zero sold place-km — used where normalisation divisors are recomputed
    by hand."""
    ods = []
    for trip in all_trips(route):
        stops = stop_times(trip)
        ods.append(
            {
                "origin_stop_id": stops[0]["stop_id"],
                "destination_stop_id": stops[-1]["stop_id"],
                "class_main": class_main,
                "trip_id": trip["trip_id"],
                "places_sold": places_sold,
                "avg_price": avg_price,
            }
        )
    return ods


# =============================================================================
# Evaluation JSON navigation
# =============================================================================


def route_bd(result: dict, normalisation: str = "per_year") -> dict:
    """Route-level breakdown of an evaluation result at one normalisation."""
    return result["views"]["route"]["data"][normalisation]