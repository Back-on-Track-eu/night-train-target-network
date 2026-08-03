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

PROPOSAL_URL = "/api/proposal"
PROPOSAL_CALC_URL = "/api/proposal/calc"
PROPOSAL_PUBLISH_URL = "/api/proposal/publish"
PROPOSALS_URL = "/api/proposals"
FEEDBACK_URL = "/api/feedback"
FEEDBACK_CATEGORIES_URL = "/api/feedback/categories"
SCENARIOS_URL = "/api/scenarios"


def likes_url(proposal_id: int) -> str:
    return f"{PROPOSAL_URL}/{proposal_id}/likes"


def comments_url(proposal_id: int, comment_id: int | None = None) -> str:
    base = f"{PROPOSAL_URL}/{proposal_id}/comments"
    return base if comment_id is None else f"{base}/{comment_id}"


# Mirrors models/route/version.py: DAYS_PER_OPERATING_WEEK / WEEKS_PER_SEASON.
_DAYS_PER_WEEK = {"daily": 7, "three_per_week": 3}
_WEEKS_PER_SEASON = 26


# =============================================================================
# HTTP wrappers
# =============================================================================


def build_route(
    api_base: str,
    stops: list[str],
    composition_id: str = "NEW-BAL-7",
    timeout: int = 90,
    **extra,
) -> dict:
    """POST /api/proposal/calc with the given stops/composition (plus any
    extra request fields, e.g. scenario_id or routing_mode) and return the
    route dict. Asserts 200 — callers testing error paths post directly
    instead.

    WP5: repointed from the removed POST /api/route/plan to
    POST /api/proposal/calc (same route-building content, evaluation
    always included alongside it now — callers that only want the route
    just ignore the rest of the response, as they always could). Always
    stateless — no headers/persistence concept exists here any more."""
    body = {"stops": stops, "composition_id": composition_id, **extra}
    resp = requests.post(f"{api_base}{PROPOSAL_CALC_URL}", json=body, timeout=timeout)
    assert resp.status_code == 200, f"proposal/calc failed: {resp.text[:300]}"
    return resp.json()["route"]


def publish(
    api_base: str,
    compute_request: dict,
    name: str,
    mode: str = "new",
    proposal_id: int | None = None,
    based_on_proposal_id: int | None = None,
    headers: dict | None = None,
    timeout: int = 60,
) -> dict:
    """POST /api/proposal/publish (WP5's only user write path) and return
    the full response body. Asserts 200 — callers testing error paths
    (403/404/422/etc.) post directly instead.

    headers: an Authorization header is required (publish is
    @require_auth) — callers always pass one; there's no tokenless case
    to default to, unlike build_route()/compute()."""
    body = {"compute_request": compute_request, "name": name, "mode": mode}
    if proposal_id is not None:
        body["proposal_id"] = proposal_id
    if based_on_proposal_id is not None:
        body["based_on_proposal_id"] = based_on_proposal_id
    resp = requests.post(
        f"{api_base}{PROPOSAL_PUBLISH_URL}", json=body, timeout=timeout, headers=headers
    )
    assert resp.status_code == 200, f"proposal/publish failed: {resp.text[:300]}"
    return resp.json()


def compute(
    api_base: str,
    stops: list[str],
    composition_id: str = "NEW-BAL-7",
    timeout: int = 90,
    **extra,
) -> dict:
    """POST /api/proposal/calc (WP2's merged endpoint) with the given
    stops/composition (plus any extra request fields, e.g. scenario_id,
    routing_mode, auto_stop_addition) and return the full response body
    (route_builder_version, calc_version, request, route, evaluation —
    and suggested_stops when auto_stop_addition="suggest"). Asserts 200 —
    callers testing error paths post directly instead.

    Always stateless: proposal/calc never persists, so unlike build_route()/
    evaluate() there is no headers param — an Authorization header would
    have no effect here."""
    body = {"stops": stops, "composition_id": composition_id, **extra}
    resp = requests.post(f"{api_base}{PROPOSAL_CALC_URL}", json=body, timeout=timeout)
    assert resp.status_code == 200, f"proposal/calc failed: {resp.text[:300]}"
    return resp.json()


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
    contribute 0 sold place-km (see views.py:build_class_keyed_normalisations)."""
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
# Model-layer evaluation (WP5 replacement for evaluate(inject_demand(...)))
# =============================================================================
#
# POST /api/evaluation/calc accepted an arbitrary pre-built route JSON,
# which is how the old test suite drove controlled demand scenarios
# (inject_demand() + evaluate()) for formula-correctness testing.
# POST /api/proposal/calc has no equivalent — it only takes stops/
# composition_id and always runs the stopgap distribute_demand()
# internally, no override. Formula-correctness tests that need custom
# demand now call the model layer directly instead (route_from_dict ->
# add_directional_domain_demand -> evaluate_route -> views), skipping
# HTTP entirely — see docs/PROPOSALS_DESIGN.md's WP5 entry for the
# decision.


def add_directional_domain_demand(
    route, class_main: str, places_sold: int, avg_price: float
):
    """Domain-object equivalent of directional_od() + inject_demand():
    appends one full-route ODPair per trip (outbound + return of every
    pair), oriented in that trip's own travel direction (first stop ->
    last stop) — the same well-defined, non-zero sold place-km guarantee
    directional_od() gives. Appends (doesn't replace) so callers can
    build up multi-class demand with repeated calls, same as the old
    `ods += directional_od(...)` loop over STANDARD_DEMAND. Mutates route
    in place; returns it for chaining."""
    from models.params import ODPair

    for pair in route.trip_pairs:
        for trip in (pair.outbound, pair.return_trip):
            stops = [trip.segments[0].from_stop] + [
                seg.to_stop for seg in trip.segments
            ]
            pair.od_pairs = pair.od_pairs + [
                ODPair(
                    origin_stop_id=stops[0].stop_id,
                    destination_stop_id=stops[-1].stop_id,
                    class_main=class_main,
                    trip_id=trip.trip_id,
                    places_sold=places_sold,
                    avg_price=avg_price,
                )
            ]
    return route


def compute_evaluation_domain(
    route_dict: dict,
    loader,
    demand: list[tuple[str, int, float]],
    scenario_id: int | None = None,
) -> tuple[dict, dict]:
    """Reconstruct route_dict (a POST /api/proposal/calc route section,
    e.g. from a session route fixture) as a domain Route via
    route_from_dict(), apply `demand` (a list of (class_main, places_sold,
    avg_price) — see add_directional_domain_demand()), evaluate, and
    serialize back into exactly the old POST /api/evaluation/calc response
    shape ({calc_version, route_id, scenario_id, models, input, views}).

    scenario_id: optional override, same semantics as route_from_dict()'s
    own parameter — costs the route under a different scenario than it
    was planned with (e.g. a historical/what-if pin). Defaults to the
    route's own embedded scenario_id.

    Returns (costed_route_dict, result) — costed_route_dict is the
    od_pairs-populated route (route_to_dict() shape, input.route equals
    it verbatim), result is the full evaluation response. Same contract
    the old evaluate(inject_demand(route, ods)) round trip provided, so
    every test written against that shape needs no changes beyond calling
    this instead of the HTTP helper."""
    from api.helpers.evaluation_serialize import (
        input_to_dict,
        models_to_dict,
        views_to_dict,
    )
    from api.helpers.route_serialize import route_from_dict, route_to_dict
    from models.evaluation.calc import evaluate_route
    from models.evaluation.version import CALC_VERSION
    from models.evaluation.views import (
        build_breakdown,
        build_breakdown_per_trip_pair,
        build_breakdown_per_trip_pair_per_country,
        build_breakdown_per_trip_pair_per_od,
        build_breakdown_per_trip_pair_per_section,
        build_breakdown_per_trip_per_stop,
    )

    resolved_scenario_id = (
        scenario_id if scenario_id is not None else route_dict["scenario_id"]
    )
    route, compositions = route_from_dict(
        route_dict, loader, scenario_id=resolved_scenario_id
    )
    # route_dict came from POST /api/proposal/calc, which always runs the
    # stopgap distribute_demand() internally — its od_pairs are already
    # populated. Clear that baseline before applying `demand`, so an empty
    # demand list genuinely means zero demand and a non-empty one replaces
    # rather than adds to the stopgap figures — the same wholesale-replace
    # semantics the old inject_demand() had.
    for pair in route.trip_pairs:
        pair.od_pairs = []
    for class_main, places_sold, avg_price in demand:
        add_directional_domain_demand(route, class_main, places_sold, avg_price)

    tracks = loader.build_all_tracks(resolved_scenario_id)
    stop_infra = loader.build_all_stops(resolved_scenario_id)
    result_obj = evaluate_route(route=route, tracks=tracks, stop_infra=stop_infra)

    bd_all = build_breakdown(route, result_obj)
    bd_per_pair = build_breakdown_per_trip_pair(route, result_obj)
    matrix_country = build_breakdown_per_trip_pair_per_country(route, result_obj)
    matrix_od = build_breakdown_per_trip_pair_per_od(route, result_obj)
    matrix_section, section_scopes = build_breakdown_per_trip_pair_per_section(
        route, result_obj
    )
    matrix_stop = build_breakdown_per_trip_per_stop(route, result_obj)

    costed = route_to_dict(route, resolved_scenario_id, tracks)
    trip_pair_by_key = {p.outbound.trip_id: p for p in route.trip_pairs}

    result = {
        "calc_version": CALC_VERSION,
        "route_id": route.route_id,
        "scenario_id": resolved_scenario_id,
        "models": models_to_dict(),
        "input": input_to_dict(
            costed, tracks, stop_infra, compositions, include_route=True
        ),
        "views": views_to_dict(
            bd_all,
            bd_per_pair,
            matrix_country,
            matrix_od,
            matrix_section,
            section_scopes,
            matrix_stop,
            route,
            trip_pair_by_key,
        ),
    }
    return costed, result


# =============================================================================
# Evaluation JSON navigation
# =============================================================================


def route_bd(
    result: dict, normalisation: str = "per_year", class_main: str = "all"
) -> dict:
    """Route-level breakdown of an evaluation result at one normalisation.
    CALC 0.9.9: every normalisation is a dict keyed by class_main plus
    'all' — default returns the 'all' cell (the whole route, matching the
    pre-0.9.9 scalar payloads). Pass class_main=None for the raw
    class-keyed dict."""
    cells = result["views"]["route"]["data"][normalisation]
    return cells if class_main is None else cells[class_main]


def purge_saved_proposals(conn, keep_route_id: str = "P1_V1_R1") -> None:
    """Delete everything the persist-on-calc pipelines wrote, except the one
    real example proposal seeded at DB init time (keep_route_id — see
    db/dev/seed.py: seed_example_proposal). Persisted GTFS IDs all start
    with 'P' (P{id}_V{version}_...), the seeded GTFS demo rows don't
    (NJ-...) — the prefix cleanly separates persisted data from unrelated
    seed data. '!~ ^P1_V1_R1' is a regex anchor, not a numeric comparison —
    it excludes exactly the seed's own IDs without also excluding
    P100_.../P1000_...-prefixed rows, which share the "P1" substring but
    not the "P1_" boundary. Deleting routes cascades trips and stop_times;
    deleting services cascades calendar and calendar_dates.

    proposals.likes/proposals.comments are cleared unconditionally (not
    keyed off keep_route_id) — db/dev/seed.py seeds no engagement rows on
    any proposal, including the permanent example, so there is nothing to
    preserve there. This lets engagement tests exercise the permanent seed
    proposal directly without ever leaving state behind. Commits.
    """
    keep_pid = int(keep_route_id.split("_")[0][1:])
    cur = conn.cursor()
    cur.execute("DELETE FROM proposals.likes")
    cur.execute("DELETE FROM proposals.comments")
    cur.execute(
        f"DELETE FROM proposals.routes WHERE route_id ~ '^P' "
        f"AND route_id !~ '^{keep_route_id}'"
    )
    cur.execute(
        f"DELETE FROM proposals.shapes WHERE shape_id ~ '^P' "
        f"AND shape_id !~ '^{keep_route_id}'"
    )
    cur.execute(
        f"DELETE FROM proposals.services WHERE service_id ~ '^P' "
        f"AND service_id !~ '^{keep_route_id}'"
    )
    cur.execute(
        "DELETE FROM proposals.proposals WHERE proposal_id != %s",
        (keep_pid,),
    )
    conn.commit()
    cur.close()
