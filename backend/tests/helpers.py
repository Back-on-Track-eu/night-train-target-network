"""
helpers.py
==========
Plain-Python helpers shared across the test suite — HTTP wrappers for
the compute/publish endpoints, navigation over route/evaluation JSON, and
model-layer evaluation with controlled demand.

Everything here derives strictly from data actually present in the API
responses (route_to_dict() / evaluation calc output). Nothing is fabricated:
stop times, per-trip stats, and per-country km are all reconstructible from
the segments a trip carries. Fields the API genuinely does not expose have
no helper here — tests for such fields don't exist in this suite.
"""

import json

import requests

from models.route.model import DEFAULT_COMPOSITION_ID

PROPOSAL_URL = "/api/proposal"
PROPOSAL_FAMILY_URL = "/api/proposal/family"
PROPOSAL_PUBLISH_URL = "/api/proposal/publish"
PROPOSALS_URL = "/api/proposals"
PROPOSALS_COMPARE_URL = "/api/proposals/compare"
FEEDBACK_URL = "/api/feedback"
FEEDBACK_CATEGORIES_URL = "/api/feedback/categories"
SCENARIOS_URL = "/api/scenarios"


def like_url(proposal_id: int) -> str:
    return f"{PROPOSAL_URL}/{proposal_id}/like"


def comment_url(proposal_id: int, comment_id: int | None = None) -> str:
    base = f"{PROPOSAL_URL}/{proposal_id}/comment"
    return base if comment_id is None else f"{base}/{comment_id}"


def engagements_url(proposal_id: int) -> str:
    return f"{PROPOSAL_URL}/{proposal_id}/engagements"


# Mirrors models/route/version.py: DAYS_PER_OPERATING_WEEK / WEEKS_PER_SEASON.
_DAYS_PER_WEEK = {"daily": 7, "three_per_week": 3}
_WEEKS_PER_SEASON = 26


# =============================================================================
# HTTP wrappers
# =============================================================================


# =============================================================================
# One member, in-process
# =============================================================================
#
# POST /api/proposal/calc is gone (WP18 B2b). What the content tests need
# from it — the FULL route dict (route_from_dict() reads geometries and
# od_pairs), the summary and the views — is exactly what compute_member()
# returns, and the wire only carries the family's compact route now
# (test_42 covers that contract). So compute() and build_route() call
# compute_member() in-process, through the same singletons the API uses,
# with the member cache bypassed so a test never reads a stale row. The
# api_base/timeout parameters stay so the ~100 call sites are untouched;
# they are not used. Error paths post a 1×1 family instead — post_member().

_dependencies_ready = False


def _member_compute():
    """compute_member with the API's singletons initialised once per
    process — the same call scripts/bench_member.py makes."""
    global _dependencies_ready
    from api.helpers import dependencies
    from api.helpers.member_compute import compute_member

    if not _dependencies_ready:
        dependencies.init()
        _dependencies_ready = True
    return compute_member


def compute_body(body: dict) -> dict:
    """One member for a raw request body, in-process: the member payload
    {route_builder_version, calc_version, route_fingerprint, request,
    suggested_stops?, summary, route, evaluation: {views}}. Domain errors
    propagate as the pipeline raises them (GaugeMismatchError,
    RailRoutingError, ValueError) — tests asserting wire codes use
    post_member() instead."""
    from api.helpers.member_compute import validate_calc_body

    errors = validate_calc_body(body)
    assert not errors, f"invalid member request: {errors}"
    payload, _ = _member_compute()(body, use_cache=False)
    # Through JSON and back, so the dict is exactly what the wire would
    # have carried (keys as strings, tuples as lists, floats as floats):
    # every comparison in the suite was written against HTTP responses.
    return json.loads(json.dumps(payload))


def build_route(
    api_base: str,
    stops: list[str],
    composition_id: str = "NEW-BAL-7",
    timeout: int = 90,
    **extra,
) -> dict:
    """The full route dict for stops/composition (plus any request fields,
    e.g. scenario_id or routing_mode). See the section comment: in-process
    since B2b; api_base and timeout are unused."""
    return compute_body({"stops": stops, "composition_id": composition_id, **extra})[
        "route"
    ]


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
    composition_id: str | None = "NEW-BAL-7",
    timeout: int = 90,
    **extra,
) -> dict:
    """One member for the given stops/composition (plus any request
    fields — scenario_id, routing_mode, auto_stop_addition, …): the member
    payload compute_body() documents. In-process since B2b; api_base and
    timeout are unused (see the section comment).

    composition_id=None posts no composition at all, so the boundary
    applies its own default — the only way to exercise that path."""
    body = {"stops": stops, **extra}
    if composition_id is not None:
        body["composition_id"] = composition_id
    return compute_body(body)


def post_member(api_base: str, body: dict, timeout: int = 300):
    """A member request on the wire: the same body /calc took (stops,
    composition_id, scenario_id, the HOW fields) posted as a 1×1 family,
    returned raw. The way to assert what a client sees — a 400 for a bad
    HOW field comes back exactly as it did from /calc; a compute failure
    is a 200 whose one member has status "error" and /calc's code
    (see member_of()).

    BOTH axes are always narrowed to one value, including when the body
    names neither: an omitted composition_id or scenario_id means "the
    boundary's default" for a member, but "every composition" / "every
    current variant" for a family, and a 6- or 72-member document is not
    what the caller asked about."""
    body = dict(body)
    composition_id = body.pop("composition_id", None) or DEFAULT_COMPOSITION_ID
    scenario_id = body.pop("scenario_id", None)
    axes = {
        "composition_ids": [composition_id],
        "scenario_variant_ids": [_variant_id_for(api_base, scenario_id)],
        "presented": {"composition_id": composition_id},
    }
    return post_family(api_base, {**body, **axes}, timeout=timeout)


def member_of(document: dict) -> dict:
    """The single member of a 1×1 family document."""
    assert len(document["members"]) == 1, document["members"]
    return document["members"][0]


_variants_cache: dict[str, dict] = {}


def _variant_id_for(api_base: str, scenario_id: int | None) -> int:
    """scenario_id → its variant under the empty measure set, from GET
    /api/scenarios, cached per api_base. None → the base scenario's
    variant, which is what a member request without a scenario_id
    resolves to."""
    if api_base not in _variants_cache:
        body = requests.get(f"{api_base}{SCENARIOS_URL}", timeout=15).json()
        none_set = next(
            m["measure_set_id"] for m in body["measure_sets"] if m["key"] == "none"
        )
        _variants_cache[api_base] = {
            "by_scenario": {
                v["scenario_id"]: v["scenario_variant_id"]
                for v in body["scenario_variants"]
                if v["measure_set_id"] == none_set
            },
            "base": next(
                v["scenario_variant_id"]
                for v in body["scenario_variants"]
                if v["measure_set_id"] == none_set and v["is_current_base"]
            ),
        }
    cached = _variants_cache[api_base]
    return cached["base"] if scenario_id is None else cached["by_scenario"][scenario_id]


def post_family(api_base: str, body: dict, timeout: int = 300):
    """POST /api/proposal/family and return the raw response — callers
    assert the status themselves, since the family's error shapes (400
    family_too_large, 404 on an expired key) are part of what the tests
    pin. The generous timeout covers a cold family whose legs are not in
    route_cache yet."""
    return requests.post(f"{api_base}{PROPOSAL_FAMILY_URL}", json=body, timeout=timeout)


def family(api_base: str, stops: list[str], timeout: int = 300, **extra) -> dict:
    """POST /api/proposal/family for the given stops (plus any request
    fields — scenario_variant_ids, composition_ids, presented, the HOW
    fields) and return the document. Asserts 200."""
    resp = post_family(api_base, {"stops": stops, **extra}, timeout=timeout)
    assert resp.status_code == 200, f"proposal/family failed: {resp.text[:300]}"
    return resp.json()


def member_views_url(key: str, scenario_variant_id: int, composition_id: str) -> str:
    return (
        f"{PROPOSAL_FAMILY_URL}/{key}/members/{scenario_variant_id}/"
        f"{composition_id}/views"
    )


def compare_sides(api_base: str, sides: list[dict], timeout: int = 120) -> dict:
    """POST /api/proposals/compare (WP9) with the given side specs and
    return the full response body (sides, diff, route_context). Asserts
    200 — callers testing error paths (400/404/422) post directly
    instead. Stateless and unauthenticated like compute(); the generous
    timeout covers override sides, which run a live compute each."""
    resp = requests.post(
        f"{api_base}{PROPOSALS_COMPARE_URL}", json={"sides": sides}, timeout=timeout
    )
    assert resp.status_code == 200, f"proposals/compare failed: {resp.text[:300]}"
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
# Model-layer evaluation — controlled demand
# =============================================================================
#
# POST /api/proposal/calc only takes stops/composition_id and always runs
# the stopgap demand model internally, no override. Formula-correctness
# tests that need custom demand therefore call the model layer directly
# (route_from_dict -> add_directional_domain_demand ->
# models.pipeline.evaluate_and_build_views -> views_to_dict), skipping
# HTTP entirely — see adapters/proposal/README.md for the
# decision.


def add_directional_domain_demand(
    route, class_main: str, places_sold: int, avg_price: float
):
    """Append one full-route ODPair per trip (outbound + return of every
    pair), oriented in that trip's own travel direction (first stop ->
    last stop), so every trip gets a well-defined, non-zero sold place-km.
    Appends (doesn't replace) so callers can build up multi-class demand
    with repeated calls over STANDARD_DEMAND. Mutates route in place;
    returns it for chaining."""
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
    serialize into the standalone evaluation-response shape the suite's
    content tests assert on ({calc_version, route_id, scenario_id, models,
    input, views}).

    scenario_id: optional override, same semantics as route_from_dict()'s
    own parameter — costs the route under a different scenario than it
    was planned with (e.g. a historical/what-if pin). Defaults to the
    route's own embedded scenario_id.

    Returns (costed_route_dict, result) — costed_route_dict is the
    od_pairs-populated route (route_to_dict() shape, input.route equals
    it verbatim), result is the full evaluation response."""
    from api.helpers.evaluation_serialize import (
        input_to_dict,
        models_to_dict,
        views_to_dict,
    )
    from api.helpers.route_serialize import route_from_dict, route_to_dict
    from models.evaluation.model import CALC_VERSION
    from models.pipeline import evaluate_and_build_views

    resolved_scenario_id = (
        scenario_id if scenario_id is not None else route_dict["scenario_id"]
    )
    route, compositions = route_from_dict(
        route_dict, loader, scenario_id=resolved_scenario_id
    )
    # route_dict came from POST /api/proposal/calc, which always runs the
    # stopgap demand model internally — its od_pairs are already populated.
    # Clear that baseline before applying `demand`, so an empty demand list
    # genuinely means zero demand and a non-empty one replaces rather than
    # adds to the stopgap figures (wholesale-replace semantics).
    for pair in route.trip_pairs:
        pair.od_pairs = []
    for class_main, places_sold, avg_price in demand:
        add_directional_domain_demand(route, class_main, places_sold, avg_price)

    tracks = loader.build_all_tracks(resolved_scenario_id)
    stop_infra = loader.build_all_stops(resolved_scenario_id)
    passages = loader.build_all_passages(resolved_scenario_id)
    _, views = evaluate_and_build_views(route, tracks, stop_infra, passages)

    costed = route_to_dict(route, resolved_scenario_id, tracks)

    result = {
        "calc_version": CALC_VERSION,
        "route_id": route.route_id,
        "scenario_id": resolved_scenario_id,
        "models": models_to_dict(),
        "input": input_to_dict(
            costed, tracks, stop_infra, compositions, include_route=True
        ),
        "views": views_to_dict(views, route),
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

    proposal_summaries has no FK to proposals.proposals (§5.4 — it's a
    derived, rebuildable projection, not authoritative data), so it needs
    its own explicit DELETE here: nothing cascades it. Skipping this
    silently orphans a row on every purge, which a later gallery/map call
    then counts and returns — a real, previously-undetected leak this
    purge left every prior test run.

    proposals.likes/comments/update_log are cleared unconditionally (not
    keyed off keep_route_id) — db/dev/seed.py seeds no engagement or
    timeline rows on any proposal, including the permanent example, so
    there is nothing to preserve there. This lets engagement tests
    exercise the permanent seed proposal directly without ever leaving
    state behind. update_log matters as much as the other two since WP11:
    it is a soft reference, so its rows outlive the proposals they
    describe, and a run that left them behind would seed the next run's
    timeline with stale events. Commits.
    """
    keep_pid = int(keep_route_id.split("_")[0][1:])
    cur = conn.cursor()
    cur.execute("DELETE FROM proposals.likes")
    cur.execute("DELETE FROM proposals.comments")
    cur.execute("DELETE FROM proposals.update_log")
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
    cur.execute(
        "DELETE FROM proposals.proposal_summaries WHERE proposal_id != %s",
        (keep_pid,),
    )
    conn.commit()
    cur.close()
