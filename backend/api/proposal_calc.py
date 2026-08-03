"""
proposal_calc.py
=================
POST /api/proposal/calc

The merged compute endpoint (PROPOSALS_DESIGN.md §2.1, WP2). One stateless
request -> route + evaluation, no side effects. Supersedes the two-call
POST /api/route/plan + POST /api/evaluation/calc pair for exploration; both
of those endpoints and their persist-on-calc behaviour stay in place
unchanged until WP5's cutover (see docs/PROPOSALS_DESIGN.md).

This module is an orchestration layer: it calls models/route and
models/evaluation exactly like route.py and evaluation.py already do, in
one pipeline. The one deliberate exception to "models stays untouched" is
additive: RouteProvenance (models/route/route_factory.py) now also carries
compositions/stop_infra alongside tracks, so this endpoint's evaluate step
reuses what plan_route() already built internally instead of reloading
the composition catalog and stop infrastructure a second time (2026-08-03
efficiency note — see RouteProvenance's docstring; no existing caller's
behaviour changes, api/route.py ignores the two new fields). No
persistence: no adapters/proposal_repository writes, no auth — the
request carries no proposal_id/proposal_version (those are publish
concerns, §2.2/WP5), and nothing here depends on g.user_id.

Pipeline steps — mirrors route.py + evaluation.py's steps, merged:
  1. Validate request body (route.py's plan-request fields; no
     proposal_id/proposal_version; scenario_id resolved once, shared by
     both the route build and the evaluation)
  2. Build the route (models.route.route_factory.plan_route), using a
     fixed neutral placeholder proposal_id/version purely so the existing
     P{id}_V{version}_-prefixed id builders in route_factory.py (untouched
     here) have something to build with
  3. Stopgap demand distribution (distribute_demand) — same as route.py
  4. Evaluate the just-built Route in memory (models.evaluation.calc.
     evaluate_route), reusing provenance.tracks/.stop_infra/.compositions
     — no round trip through route_to_dict/route_from_dict, and no
     redundant infrastructure/catalog reload, unlike the old two-endpoint
     flow
  5. Build evaluation views (models.evaluation.views)
  6. Serialize route + evaluation, strip the neutral P0_V0_ prefix off
     every id in the combined payload (route_id, trip_id, geometry_id, and
     the evaluation views' dict keys), and return them as sibling keys of
     one merged response, per §2.1
"""

import logging
import time

from flask import Blueprint, jsonify, request

from adapters.proposal_repository import rewrite_id_prefix
from adapters.proposal_projection import route_fingerprint
from api.helpers.dependencies import get_loader, get_country_index
from api.helpers.route_serialize import route_to_dict, suggested_stops_to_dicts
from api.helpers.evaluation_serialize import (
    views_to_dict,
    models_to_dict,
    input_to_dict,
)
from models.route.route_factory import plan_route, distribute_demand, TripPairInput
from models.route.timetable import (
    VALID_TIMETABLE_MODES,
    VALID_SCHEDULE_MODES,
    VALID_AUTO_STOP_ADDITION_MODES,
)
from models.route.routing.rail_router import RailRouter, VALID_ROUTING_MODES
from models.route.version import (
    ROUTE_BUILDER_VERSION,
    DEFAULT_TIMETABLE_MODE,
    DEFAULT_SCHEDULE_MODE,
    DEFAULT_ROUTING_MODE,
    DEFAULT_AUTO_STOP_ADDITION,
    STOPGAP_UTILIZATION_PER,
    STOPGAP_FARE_PER_KM_BY_CLASS,
    NEUTRAL_PROPOSAL_ID,
    NEUTRAL_PROPOSAL_VERSION,
)
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

logger = logging.getLogger(__name__)
bp = Blueprint("proposal_calc", __name__)

_NEUTRAL_PREFIX = f"P{NEUTRAL_PROPOSAL_ID}_V{NEUTRAL_PROPOSAL_VERSION}_"


def _validate(body: dict) -> list[str]:
    """Request validation for the merged compute request (§2.1) — the
    former plan request's WHAT/HOW fields, minus proposal_id/
    proposal_version (publish-only, not a compute concern). scenario_id
    keeps route.py's plan-request semantics (optional int; None = current
    base) — verified against /api/evaluation/calc's request shape, the
    merged request carries no separate evaluation-only override."""
    errors = []

    if body.get("scenario_id") is not None and not isinstance(body["scenario_id"], int):
        errors.append("'scenario_id' must be an integer if provided.")

    stops = body.get("stops")
    if not isinstance(stops, list):
        errors.append("'stops' must be a list of stop_id strings.")
    elif len(stops) < 2:
        errors.append("'stops' must contain at least 2 entries.")
    elif not all(isinstance(s, str) for s in stops):
        errors.append("'stops' must be a list of stop_id strings.")

    if not isinstance(body.get("composition_id"), str):
        errors.append("'composition_id' must be a string.")

    timetable_mode = body.get("timetable_mode", DEFAULT_TIMETABLE_MODE)
    if timetable_mode not in VALID_TIMETABLE_MODES:
        errors.append(
            f"'timetable_mode' = '{timetable_mode}' is invalid. Must be one of: {sorted(VALID_TIMETABLE_MODES)}."
        )

    fixed_night_interval = body.get("fixed_night_interval")
    if timetable_mode == "simpleAutomaticWithFixedNight":
        if (
            not isinstance(fixed_night_interval, list)
            or len(fixed_night_interval) != 2
            or not all(isinstance(s, str) for s in fixed_night_interval)
            or fixed_night_interval[0] == fixed_night_interval[1]
        ):
            errors.append(
                "'fixed_night_interval' must be a list of exactly 2 distinct "
                "stop_id strings when timetable_mode is "
                "'simpleAutomaticWithFixedNight'."
            )
        elif isinstance(stops, list) and all(isinstance(s, str) for s in stops):
            missing = [s for s in fixed_night_interval if s not in stops]
            if missing:
                errors.append(
                    f"'fixed_night_interval' stops {missing} are not in 'stops'."
                )
            elif stops.index(fixed_night_interval[0]) >= stops.index(
                fixed_night_interval[1]
            ):
                errors.append(
                    "'fixed_night_interval' start must come before its end in "
                    "'stops' order."
                )
    elif fixed_night_interval is not None:
        errors.append(
            "'fixed_night_interval' is only allowed with timetable_mode "
            "'simpleAutomaticWithFixedNight'."
        )

    schedule_mode = body.get("schedule_mode", DEFAULT_SCHEDULE_MODE)
    if schedule_mode not in VALID_SCHEDULE_MODES:
        errors.append(
            f"'schedule_mode' = '{schedule_mode}' is invalid. Must be one of: {sorted(VALID_SCHEDULE_MODES)}."
        )

    routing_mode = body.get("routing_mode", DEFAULT_ROUTING_MODE)
    if routing_mode not in VALID_ROUTING_MODES:
        errors.append(
            f"'routing_mode' = '{routing_mode}' is invalid. Must be one of: {sorted(VALID_ROUTING_MODES)}."
        )

    auto_stop_addition = body.get("auto_stop_addition", DEFAULT_AUTO_STOP_ADDITION)
    if auto_stop_addition not in VALID_AUTO_STOP_ADDITION_MODES:
        errors.append(
            f"'auto_stop_addition' = '{auto_stop_addition}' is invalid. Must be one "
            f"of: {sorted(VALID_AUTO_STOP_ADDITION_MODES)}."
        )

    return errors


@bp.post("/calc")
def calc():
    """
    Plan a route and evaluate it in one call — see PROPOSALS_DESIGN.md
    §2.1 for the full request/response contract. Stateless: no
    persistence, no proposal_id/proposal_version in the request, no auth.

    Request body: identical to POST /api/route/plan's WHAT/HOW fields
    (stops, composition_id, scenario_id, timetable_mode,
    fixed_night_interval, schedule_mode, routing_mode, auto_stop_addition)
    minus proposal_id/proposal_version — see _validate() and
    docs/PROPOSALS_DESIGN.md §2.1 for field semantics.

    Response:
      {
        "route_builder_version": "...",
        "calc_version": "...",
        "route_fingerprint": "sha256:...",  // §3.1, adapters/proposal_projection.py
        "cache_hit": false,            // always false until WP13 wires the real compute cache
        "request": { ... },            // resolved: defaults applied, scenario_id concrete
        "suggested_stops": [ ... ],    // only when auto_stop_addition="suggest"
        "route": { ... },              // route_to_dict() shape, neutral ids (R1, ...)
        "evaluation": {
          "models": { ... }, "input": { "parameters": { ... } }, "views": { ... }
        }
      }
    """
    t_start = time.monotonic()

    body = request.get_json(silent=True)
    if not body:
        return (
            jsonify({"error": "bad_request", "message": "Request body must be JSON."}),
            400,
        )

    errors = _validate(body)
    if errors:
        logger.warning("proposal/calc [1/3] validation failed — %s", errors)
        return jsonify({"error": "validation_error", "details": errors}), 400

    loader = get_loader()
    router = RailRouter(get_country_index())

    timetable_mode = body.get("timetable_mode", DEFAULT_TIMETABLE_MODE)
    schedule_mode = body.get("schedule_mode", DEFAULT_SCHEDULE_MODE)
    routing_mode = body.get("routing_mode", DEFAULT_ROUTING_MODE)
    auto_stop_addition = body.get("auto_stop_addition", DEFAULT_AUTO_STOP_ADDITION)
    fixed_night_interval = body.get("fixed_night_interval")

    try:
        scenario_id = loader.resolve_scenario_id(body.get("scenario_id"))

        logger.info(
            "proposal/calc [1/3]: stops=%d composition=%s scenario_id=%s auto_stop_addition=%s",
            len(body["stops"]),
            body["composition_id"],
            scenario_id,
            auto_stop_addition,
        )

        # Step 2+3 — build the route (neutral placeholder ids; the P0_V0_
        # prefix is stripped from the whole payload below) and populate
        # stopgap demand, exactly as route.py's /plan does.
        route, provenance, suggestions = plan_route(
            proposal_id=NEUTRAL_PROPOSAL_ID,
            proposal_version=NEUTRAL_PROPOSAL_VERSION,
            schedule_mode=schedule_mode,
            trip_pair_inputs=[
                TripPairInput(
                    stop_ids=body["stops"],
                    composition_id=body["composition_id"],
                    timetable_mode=timetable_mode,
                    routing_mode=routing_mode,
                    auto_stop_addition=auto_stop_addition,
                    fixed_night_interval=fixed_night_interval,
                )
            ],
            loader=loader,
            router=router,
            scenario_id=scenario_id,
        )
        distribute_demand(
            route,
            utilization_per=STOPGAP_UTILIZATION_PER,
            fare_per_km_by_class=STOPGAP_FARE_PER_KM_BY_CLASS,
        )
        logger.info(
            "proposal/calc [2/3] route %s built (%.3fs)",
            route.route_id,
            time.monotonic() - t_start,
        )

        # Step 4 — evaluate the Route object directly (no serialize/
        # deserialize round trip through route_to_dict/route_from_dict —
        # unlike the old two-endpoint flow, we already hold the domain
        # object). tracks, stop_infra, and compositions are all reused
        # from provenance — plan_route() already builds every one of them
        # internally (RouteProvenance now threads compositions/stop_infra
        # through the same way it already did for tracks, 2026-08-03 —
        # see models/route/route_factory.py), so no second DB/catalog load
        # happens here.
        result = evaluate_route(
            route=route, tracks=provenance.tracks, stop_infra=provenance.stop_infra
        )

        # Step 5 — build views (identical to evaluation.py step 4)
        bd_all = build_breakdown(route, result)
        bd_per_pair = build_breakdown_per_trip_pair(route, result)
        matrix_country = build_breakdown_per_trip_pair_per_country(route, result)
        matrix_od = build_breakdown_per_trip_pair_per_od(route, result)
        matrix_section, section_scopes = build_breakdown_per_trip_pair_per_section(
            route, result
        )
        matrix_stop = build_breakdown_per_trip_per_stop(route, result)
        logger.info(
            "proposal/calc [3/3] evaluated + views built (%.3fs)",
            time.monotonic() - t_start,
        )

    except ValueError as e:
        logger.warning("proposal/calc failed (domain error): %s", e)
        return jsonify({"error": "domain_error", "message": str(e)}), 422
    except Exception as e:
        logger.exception("proposal/calc failed (unexpected): %s", e)
        return jsonify({"error": "calc_error", "message": str(e)}), 500

    # Step 6 — serialize + merge. route_dict carries the neutral-prefixed
    # ids (P0_V0_R1...) exactly like route_to_dict() always has; the
    # evaluation views key some of their data by trip_id too
    # (per_trip_pair* matrices) — rewrite_id_prefix() below strips the
    # prefix from both in one recursive pass, values AND dict keys, so the
    # merged response is prefix-free throughout.
    route_dict = route_to_dict(route, provenance.scenario_id, provenance.tracks)
    trip_pair_by_key = {p.outbound.trip_id: p for p in route.trip_pairs}

    # §3.1 — computed from route_dict before the prefix strip below, but
    # prefix-independent by construction: the canonical extract only ever
    # uses stop_id (never route_id/trip_id/geometry_id), so the fingerprint
    # is identical whichever side of rewrite_id_prefix() it's taken from.
    fingerprint = route_fingerprint(route_dict)

    # Resolved request echo per §2.1: "defaults applied, scenario_id
    # concrete" — an omitted field and an explicitly-posted default must
    # compare equal, so build this explicitly rather than echoing the
    # posted body verbatim (which may omit any of the optional fields).
    resolved_request = {
        "stops": list(body["stops"]),
        "composition_id": body["composition_id"],
        "scenario_id": provenance.scenario_id,
        "timetable_mode": timetable_mode,
        "fixed_night_interval": fixed_night_interval,
        "schedule_mode": schedule_mode,
        "routing_mode": routing_mode,
        "auto_stop_addition": auto_stop_addition,
    }

    payload = {
        "route_builder_version": ROUTE_BUILDER_VERSION,
        "calc_version": CALC_VERSION,
        "route_fingerprint": fingerprint,
        # No compute cache yet (WP13) — every call is necessarily a fresh
        # compute, so this is always false rather than absent, keeping the
        # response shape stable ahead of WP13's logic swap.
        "cache_hit": False,
        "request": resolved_request,
    }
    if auto_stop_addition == "suggest":
        payload["suggested_stops"] = suggested_stops_to_dicts(suggestions)
    payload["route"] = route_dict
    payload["evaluation"] = {
        "models": models_to_dict(),
        # include_route=False: the route already appears once above, as a
        # sibling of "evaluation" — see input_to_dict()'s docstring.
        "input": input_to_dict(
            route_dict,
            provenance.tracks,
            provenance.stop_infra,
            provenance.compositions,
            include_route=False,
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

    payload = rewrite_id_prefix(payload, _NEUTRAL_PREFIX, "")

    return jsonify(payload), 200
