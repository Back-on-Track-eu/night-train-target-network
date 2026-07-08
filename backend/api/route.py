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
save/versioning flow, just no longer reachable from this endpoint).

Boarding/alighting classification and departure time are now automatic
(see timetable_mode) — the caller supplies a plain list of stop IDs, not
per-stop stop_type/time. Seasonal frequency is likewise automatic (see
schedule_mode).

NO monetary values in the response — use POST /api/evaluation/calc for that.
"""

import logging
import random

from flask import Blueprint, jsonify, request

from api.helpers.dependencies import get_loader, get_country_index
from api.helpers.route_serialize import route_to_dict
from models.route.route_factory import plan_route, TripPairInput
from models.route.timetable import VALID_TIMETABLE_MODES, VALID_SCHEDULE_MODES
from models.route.routing.rail_router import RailRouter
from models.route.version import ROUTE_BUILDER_VERSION

logger = logging.getLogger(__name__)
bp = Blueprint("route", __name__)

_VALID_ROUTING_MODES = {"simpleRouting", "fullRouting"}

_DRAFT_PROPOSAL_ID_MIN = 1_000_000_000
_DRAFT_PROPOSAL_ID_MAX = 2_147_483_647  # postgres int4 max — proposals.proposals.proposal_id is SERIAL (int4)


def _draft_proposal_id() -> int:
    """
    Placeholder proposal_id for a route that hasn't been saved as a proposal
    yet. proposals.proposals.proposal_id is a SERIAL starting at 1, so a
    random value above one billion won't realistically collide with a real
    one. This is a stand-in for a future scenarios/proposals module that
    will properly own draft-vs-saved handling (and hand back whatever id it
    thinks is appropriate) — api/route.py is just the simplest place to put
    this until that module exists.
    """
    return random.randint(_DRAFT_PROPOSAL_ID_MIN, _DRAFT_PROPOSAL_ID_MAX)


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

    timetable_mode = body.get("timetable_mode", "simpleAutomatic")
    if timetable_mode not in VALID_TIMETABLE_MODES:
        errors.append(
            f"'timetable_mode' = '{timetable_mode}' is invalid. Must be one of: {sorted(VALID_TIMETABLE_MODES)}."
        )

    schedule_mode = body.get("schedule_mode", "alwaysDaily")
    if schedule_mode not in VALID_SCHEDULE_MODES:
        errors.append(
            f"'schedule_mode' = '{schedule_mode}' is invalid. Must be one of: {sorted(VALID_SCHEDULE_MODES)}."
        )

    routing_mode = body.get("routing_mode", "fullRouting")
    if routing_mode not in _VALID_ROUTING_MODES:
        errors.append(
            f"'routing_mode' = '{routing_mode}' is invalid. Must be one of: {sorted(_VALID_ROUTING_MODES)}."
        )

    if body.get("auto_stop_addition") is not None and not isinstance(
        body["auto_stop_addition"], bool
    ):
        errors.append("'auto_stop_addition' must be a boolean if provided.")

    return errors


@bp.post("/plan")
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
      timetable_mode    : "simpleAutomatic"  (optional, default "simpleAutomatic" — only
                                  supported value for now. Departure time and per-stop
                                  boarding/alighting are derived by mirroring the trip
                                  duration around a fixed 02:30 constant: everything
                                  before 02:30 is a boarding stop, everything after is
                                  alighting. First/last stop are always boarding/alighting
                                  regardless of clock time.)
      schedule_mode     : "alwaysDaily"  (optional, default "alwaysDaily" — only supported
                                  value for now. Daily frequency in both seasons regardless
                                  of demand; a future demand-aware strategy can be added
                                  without changing this request shape.)
      routing_mode      : "simpleRouting" | "fullRouting"  (optional, default "fullRouting".
                                  "fullRouting" derives HSR avoidance/speed cap automatically
                                  from composition + track flags. "simpleRouting" skips all
                                  of that for a cheap single-pass route — not representative
                                  of real physics.)
      auto_stop_addition : bool (optional, default false — accepted but currently a no-op;
                                  reserved for automatically proposing extra stops along
                                  the route in a future iteration.)
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
    timetable_mode = body.get("timetable_mode", "simpleAutomatic")
    schedule_mode = body.get("schedule_mode", "alwaysDaily")
    routing_mode = body.get("routing_mode", "fullRouting")
    auto_stop_addition = body.get("auto_stop_addition", False)

    try:
        # Inside the try block: resolve_scenario_id() raises ValueError if
        # the DB has no is_current_base scenario seeded, which should map
        # to the same 422 domain_error response as any other domain failure.
        scenario_id = loader.resolve_scenario_id(body.get("scenario_id"))

        logger.info(
            "plan: proposal_id=%s version=%s stops=%d",
            proposal_id,
            proposal_version,
            len(body["stops"]),
        )
        route, provenance = plan_route(
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
                )
            ],
            loader=loader,
            router=router,
            scenario_id=scenario_id,
        )

    except ValueError as e:
        logger.warning("plan failed (domain error): %s", e)
        return jsonify({"error": "domain_error", "message": str(e)}), 422
    except Exception as e:
        logger.exception("plan failed (unexpected): %s", e)
        return jsonify({"error": "route_error", "message": str(e)}), 500

    return (
        jsonify(
            {
                "route_builder_version": ROUTE_BUILDER_VERSION,
                "request": body,
                "route": route_to_dict(
                    route, provenance.scenario_id, provenance.tracks
                ),
            }
        ),
        200,
    )
