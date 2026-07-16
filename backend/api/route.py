"""
route.py
========
Route planning endpoint.

  POST /api/route/plan

Accepts a stop list, composition ID, and proposal context (optional).
Returns a fully built Route with both trips (outbound + return),
including geometry, timetable, and physics stats.

Stateless: always a full plan/reroute, never an in-place adjust — that
mode was dropped (route_factory.adjust_route() still exists for a future
save/versioning flow, just no longer reachable from this endpoint — see
OPEN_TODOS["adjust_route_unreachable"] in models/route/version.py).

Boarding/alighting classification and departure time are now automatic
(see timetable_mode) — the caller supplies a plain list of stop IDs, not
per-stop stop_type/time. Seasonal frequency is likewise automatic (see
schedule_mode).

NO monetary values in the response — use POST /api/evaluation/calc for that.

Request defaults and standard values (draft proposal id range, stopgap
demand parameters) live in models/route/version.py — the single registry
of every fixed assumption the route model makes.
"""

import logging
import random

from flask import Blueprint, g, jsonify, request

from adapters.proposal_repository import rewrite_id_prefix
from api.auth_middleware import optional_auth
from api.helpers.dependencies import (
    get_loader,
    get_country_index,
    get_proposal_repository,
)
from api.helpers.route_serialize import route_to_dict, suggested_stops_to_dicts
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
    DRAFT_PROPOSAL_ID_MIN,
    DRAFT_PROPOSAL_ID_MAX,
)

logger = logging.getLogger(__name__)
bp = Blueprint("route", __name__)


def _draft_proposal_id() -> int:
    """
    Placeholder proposal_id for a route that hasn't been saved as a proposal
    yet — random within [DRAFT_PROPOSAL_ID_MIN, DRAFT_PROPOSAL_ID_MAX] so it
    won't realistically collide with a real SERIAL id. A stand-in for a
    future scenarios/proposals module that will properly own draft-vs-saved
    handling — see OPEN_TODOS["draft_proposal_module"] in
    models/route/version.py; api/route.py is just the simplest place to put
    this until that module exists.
    """
    return random.randint(DRAFT_PROPOSAL_ID_MIN, DRAFT_PROPOSAL_ID_MAX)


def _validate(body: dict) -> list[str]:
    errors = []

    if body.get("proposal_id") is not None and not isinstance(body["proposal_id"], int):
        errors.append("'proposal_id' must be an integer if provided.")
    if body.get("proposal_version") is not None and not isinstance(
        body["proposal_version"], int
    ):
        errors.append("'proposal_version' must be an integer if provided.")
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

    # fixed_night_interval is strictly coupled to its mode: required (and
    # shape-checked against the stops list) for simpleAutomaticWithFixedNight,
    # rejected outright alongside any other mode rather than silently
    # ignored — same strictness pattern as the auto_stop_addition enum.
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

    # Deliberately no bool acceptance: auto_stop_addition was a bool until
    # route builder 0.9.4 — true/false now fail here (isinstance(True, str)
    # is False) with an error message naming the enum values, rather than
    # being silently mapped to "add"/"off".
    auto_stop_addition = body.get("auto_stop_addition", DEFAULT_AUTO_STOP_ADDITION)
    if auto_stop_addition not in VALID_AUTO_STOP_ADDITION_MODES:
        errors.append(
            f"'auto_stop_addition' = '{auto_stop_addition}' is invalid. Must be one "
            f"of: {sorted(VALID_AUTO_STOP_ADDITION_MODES)} (booleans are no longer "
            f"accepted since route builder 0.9.5)."
        )

    return errors


def _resolved_setup(request_dict: dict, scenario_id: int) -> tuple:
    """Everything about a plan request that can change the built route —
    defaults applied, so an omitted field and an explicitly-posted default
    compare equal. Used for the persist dedupe: a replan with identical
    setup produces an identical route (stopgap demand included — it is
    derived from the route), so no new version is written."""
    return (
        list(request_dict["stops"]),
        request_dict["composition_id"],
        request_dict.get("timetable_mode", DEFAULT_TIMETABLE_MODE),
        request_dict.get("fixed_night_interval"),
        request_dict.get("schedule_mode", DEFAULT_SCHEDULE_MODE),
        request_dict.get("routing_mode", DEFAULT_ROUTING_MODE),
        request_dict.get("auto_stop_addition", DEFAULT_AUTO_STOP_ADDITION),
        scenario_id,
    )


def _persist_plan(
    payload: dict, body: dict, proposal_id: int, proposal_version: int, scenario_id: int
) -> tuple[dict, dict]:
    """Auto-persist a successful plan response (persist-on-calc, 2026-07-16).

    Tokenless requests compute only — persistence is a feature of identity
    (guest or registered; the frontend always holds at least a guest token,
    scripts/tests authenticate as the seeded test_script user).

    Dedupe: when the request targets an existing proposal and its resolved
    setup matches the current version's (and the builder version is
    unchanged), no row is written — the payload's draft IDs are rewritten to
    the matched current version instead, so the response references exactly
    the stored state.

    Returns (payload, proposal_block); never raises — a persistence failure
    must not discard a successfully built route.
    """
    if g.get("user_id") is None:
        return payload, {"persisted": False, "action": "unauthenticated"}

    try:
        repo = get_proposal_repository()

        posted_pid = body.get("proposal_id")
        current = repo.get_current(posted_pid) if posted_pid is not None else None
        if current is not None:
            stored_body = current["route_body"]
            same_setup = stored_body[
                "route_builder_version"
            ] == ROUTE_BUILDER_VERSION and _resolved_setup(
                stored_body["request"], stored_body["route"]["scenario_id"]
            ) == _resolved_setup(body, scenario_id)
            if same_setup:
                old_prefix = f"P{proposal_id}_V{proposal_version}_"
                new_prefix = (
                    f"P{current['proposal_id']}_V{current['proposal_version']}_"
                )
                payload = rewrite_id_prefix(payload, old_prefix, new_prefix)
                payload["request"] = {
                    **payload["request"],
                    "proposal_id": current["proposal_id"],
                    "proposal_version": current["proposal_version"],
                }
                return payload, {
                    "persisted": False,
                    "action": "unchanged",
                    "proposal_id": current["proposal_id"],
                    "proposal_version": current["proposal_version"],
                    "user_id": current["user_id"],
                }

        record = repo.save(route_body=payload, user_id=g.user_id, change_log=None)
        return record["route_body"], {
            "persisted": True,
            "action": record["action"],
            "proposal_id": record["proposal_id"],
            "proposal_version": record["proposal_version"],
            "user_id": record["user_id"],
        }
    except Exception:
        logger.exception("plan persisted nothing (unexpected persistence error)")
        return payload, {"persisted": False, "action": "error"}


@bp.post("/plan")
@optional_auth
def plan():
    """
    Plan a new route (always a full build — no in-place adjust here).

    Request body:
      proposal_id       : int   (optional — only set when replanning stops/
                                  composition of an already-saved proposal;
                                  omit for a brand new proposal. If omitted,
                                  a random placeholder id above one billion
                                  is assigned and proposal_version is forced
                                  to 1 — this is a stand-in until proposals
                                  are actually saved, not a real DB id.)
      proposal_version  : int   (optional — see proposal_id; ignored if
                                  proposal_id is omitted)
      scenario_id       : int   (optional — pins parameter versions; None = live base scenario)
      stops             : [stop_id, ...]  (required, min 2 — plain stop IDs,
                                  no stop_type; boarding/alighting is derived
                                  automatically, see timetable_mode)
      composition_id    : str   (required)
      timetable_mode    : "simpleAutomatic" | "simpleAutomaticWithFixedNight"
                                  (optional, default "simpleAutomatic".
                                  Departure time and per-stop classification are
                                  derived automatically. Classification is the same
                                  for both modes: a stop departing strictly before
                                  00:00 is boarding, one arriving at/after 05:00 is
                                  alighting, anything between is a night stop
                                  (thresholds NIGHT_START_MIN / NIGHT_END_MIN in
                                  models/route/version.py). First/last stop are
                                  always boarding/alighting regardless of clock time.
                                  "simpleAutomatic": the whole trip's duration is
                                  mirrored around a fixed 02:30 constant.
                                  "simpleAutomaticWithFixedNight": the
                                  fixed_night_interval section is centered on 02:30
                                  instead — demand-strong feeder sections outside it
                                  keep sensible evening/morning times. The interval
                                  must depart by 23:59 and arrive at 05:00 or later;
                                  a naturally shorter interval is stretched by
                                  adding slack_time_min across its segments, and if
                                  that makes it slower than
                                  FIXED_NIGHT_MIN_SPEED_RATIO of routing speed the
                                  trip carries a fixed_night_stretch_slow entry in
                                  general_parameters.timetable_warnings.)
      fixed_night_interval : [stop_id, stop_id]  (required for, and only allowed
                                  with, timetable_mode="simpleAutomaticWithFixedNight" —
                                  two distinct stop IDs from 'stops', start before end
                                  in outbound travel order; may span several legs. The
                                  return trip applies the interval reversed
                                  automatically.)
      schedule_mode     : "alwaysDaily"  (optional, default "alwaysDaily" — only supported
                                  value for now. Daily frequency in both seasons regardless
                                  of demand; a future demand-aware strategy can be added
                                  without changing this request shape.)
      routing_mode      : "simpleRouting" | "fullRouting"  (optional, default "fullRouting".
                                  "fullRouting" derives HSR avoidance/speed cap automatically
                                  from composition + track flags. "simpleRouting" skips all
                                  of that for a cheap single-pass route — not representative
                                  of real physics.)
      auto_stop_addition : "off" | "add" | "suggest"  (optional, default "add" —
                                  string enum since route builder 0.9.5, booleans
                                  are rejected.
                                  "off": exactly the caller's own stop list back,
                                  unmodified, no candidate search.
                                  "add": looks for stops from the full stop catalog
                                  that sit close to the routed path and greedily
                                  adds any that fit within the detour time budget
                                  (cheapest detour first). Added stops are marked
                                  auto_added=true on their Stop in the response so
                                  the frontend can render them differently.
                                  "suggest": routes exactly like "off", but runs the
                                  same candidate search + costing as "add" and
                                  returns every costed candidate in a top-level
                                  suggested_stops list (between request and route
                                  in the response), each with the added_time_min it
                                  would cost if implemented — no budget filtering,
                                  selection is the caller's.
                                  Threshold values AUTO_STOP_BUFFER_M /
                                  AUTO_STOP_MAX_DETOUR_PER are fixed constants in
                                  models/route/version.py, not request fields.)
    """
    body = request.get_json(silent=True)
    if not body:
        return (
            jsonify({"error": "bad_request", "message": "Request body must be JSON."}),
            400,
        )

    errors = _validate(body)
    if errors:
        return jsonify({"error": "validation_error", "details": errors}), 400

    loader = get_loader()
    router = RailRouter(get_country_index())

    # All defaulting/resolution happens here, once, at the API boundary —
    # everything below this point (TripPairInput, plan_route, and everything
    # they call) receives fully-resolved values and has no defaults or
    # None-handling of its own to fall back on.
    proposal_id = body.get("proposal_id")
    proposal_version = body.get("proposal_version")
    if proposal_id is None:
        # Brand new proposal — no DB row, no real id yet. Mint a placeholder
        # so route_factory.py never has to know "not saved yet" is even a
        # possible state. Any proposal_version supplied alongside a missing
        # proposal_id is meaningless (there's nothing to version) and is
        # ignored in favour of 1.
        proposal_id = _draft_proposal_id()
        proposal_version = 1
    elif proposal_version is None:
        # proposal_id without a version: since persist-on-calc the posted
        # version is only the draft-prefix seed anyway (the persist layer
        # assigns the real one), so default it instead of building
        # unparseable P{id}_VNone_ IDs.
        proposal_version = 1
    timetable_mode = body.get("timetable_mode", DEFAULT_TIMETABLE_MODE)
    schedule_mode = body.get("schedule_mode", DEFAULT_SCHEDULE_MODE)
    routing_mode = body.get("routing_mode", DEFAULT_ROUTING_MODE)
    auto_stop_addition = body.get("auto_stop_addition", DEFAULT_AUTO_STOP_ADDITION)
    fixed_night_interval = body.get("fixed_night_interval")  # None except for
    # timetable_mode="simpleAutomaticWithFixedNight" — enforced in _validate()

    try:
        # Inside the try block: resolve_scenario_id() raises ValueError if
        # the DB has no is_current_base scenario seeded, which should map
        # to the same 422 domain_error response as any other domain failure.
        scenario_id = loader.resolve_scenario_id(body.get("scenario_id"))

        logger.info(
            "plan: proposal_id=%s version=%s stops=%d auto_stop_addition=%s",
            proposal_id,
            proposal_version,
            len(body["stops"]),
            auto_stop_addition,
        )
        route, provenance, suggestions = plan_route(
            proposal_id=proposal_id,
            proposal_version=proposal_version,
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

        # Stopgap: populate demand so the route carries od_pairs and evaluation
        # returns non-zero revenue. Mutates the route in place. See
        # OPEN_TODOS["demand_model"] in models/route/version.py.
        distribute_demand(
            route,
            utilization_per=STOPGAP_UTILIZATION_PER,
            fare_per_km_by_class=STOPGAP_FARE_PER_KM_BY_CLASS,
        )

    except ValueError as e:
        logger.warning("plan failed (domain error): %s", e)
        return jsonify({"error": "domain_error", "message": str(e)}), 422
    except Exception as e:
        logger.exception("plan failed (unexpected): %s", e)
        return jsonify({"error": "route_error", "message": str(e)}), 500

    # suggested_stops sits between request and route, and ONLY for mode
    # "suggest" (present even when empty there — an empty list is a real
    # "searched, found nothing" answer). "off"/"add" responses keep the
    # pre-0.9.5 three-key envelope unchanged.
    payload = {
        "route_builder_version": ROUTE_BUILDER_VERSION,
        "request": body,
    }
    if auto_stop_addition == "suggest":
        payload["suggested_stops"] = suggested_stops_to_dicts(suggestions)
    payload["route"] = route_to_dict(route, provenance.scenario_id, provenance.tracks)

    # Persist-on-calc: the stored route_body is exactly the three/four-key
    # envelope above; the proposal block is response metadata only and is
    # appended after (never inside) the persisted body.
    payload, proposal_block = _persist_plan(
        payload, body, proposal_id, proposal_version, scenario_id
    )
    payload["proposal"] = proposal_block

    return jsonify(payload), 200