"""
route.py
========
Route planning endpoint.

  POST /api/route/planOrUpdate

Accepts a stop list, composition ID, departure time, and proposal context.
Returns a fully built Route with both trips (outbound + return),
including geometry, timetable, and physics stats.

The backend automatically derives whether to plan or adjust:
  - No 'route' in body                          → plan  (new route)
  - 'route' in body, stops/composition unchanged → adjust (departure time / stop type change only)
  - 'route' in body, stops or composition changed → plan  (full reroute)

NO monetary values in the response — use POST /api/evaluation/calc for that.
"""

import logging

from flask import Blueprint, jsonify, request

from api.dependencies import get_loader
from models.route.route import Route
from models.route.route_factory import plan_route, adjust_route
from models.route.routing.rail_router import RailRouter
from models.route.version import ROUTE_BUILDER_VERSION
from models.utils import hhmm_to_min

logger = logging.getLogger(__name__)
bp = Blueprint("route", __name__)

_VALID_STOP_TYPES = {"boarding", "alighting", "both"}


def _validate(body: dict) -> list[str]:
    errors = []

    if not isinstance(body.get("proposal_id"), int):
        errors.append("'proposal_id' must be an integer.")
    if not isinstance(body.get("proposal_version"), int):
        errors.append("'proposal_version' must be an integer.")

    # stops required unless an existing route is provided
    stops = body.get("stops")
    if stops is not None:
        if not isinstance(stops, list):
            errors.append("'stops' must be a list.")
        elif len(stops) < 2:
            errors.append("'stops' must contain at least 2 entries.")
        else:
            for i, s in enumerate(stops):
                if not isinstance(s, dict):
                    errors.append(f"stops[{i}] must be an object.")
                    continue
                if not isinstance(s.get("stop_id"), str):
                    errors.append(f"stops[{i}].stop_id must be a string.")
                if s.get("stop_type") not in _VALID_STOP_TYPES:
                    errors.append(
                        f"stops[{i}].stop_type '{s.get('stop_type')}' is invalid. "
                        f"Must be one of: {sorted(_VALID_STOP_TYPES)}."
                    )

    if body.get("composition_id") is not None and not isinstance(body["composition_id"], str):
        errors.append("'composition_id' must be a string.")

    dep = body.get("departure_time")
    if dep is not None:
        if not isinstance(dep, str):
            errors.append("'departure_time' must be a string in HH:MM format.")
        else:
            try:
                hhmm_to_min(dep)
            except ValueError as e:
                errors.append(str(e))

    existing = body.get("route")
    if existing is not None and not isinstance(existing, dict):
        errors.append("'route' must be an object (Route.to_dict() output) if provided.")

    stop_type_changes = body.get("stop_type_changes")
    if stop_type_changes is not None:
        if not isinstance(stop_type_changes, dict):
            errors.append("'stop_type_changes' must be an object {stop_id: stop_type}.")
        else:
            for sid, stype in stop_type_changes.items():
                if stype not in _VALID_STOP_TYPES:
                    errors.append(
                        f"stop_type_changes['{sid}'] = '{stype}' is invalid. "
                        f"Must be one of: {sorted(_VALID_STOP_TYPES)}."
                    )

    # must have either stops+composition_id or an existing route
    if existing is None and (stops is None or body.get("composition_id") is None):
        errors.append(
            "Provide either 'stops' + 'composition_id' (new route) "
            "or 'route' (update existing route)."
        )

    return errors


def _is_adjust(body: dict, existing_route: Route) -> bool:
    """
    Return True if only departure_time or stop_type_changes differ from
    the existing route — i.e. no rerouting is needed.
    Returns False (full plan) if stops or composition changed.
    """
    new_stops        = body.get("stops")
    new_composition  = body.get("composition_id")

    if new_stops is None and new_composition is None:
        return True   # only departure_time / stop_type_changes provided

    existing_stop_ids   = [st.stop_id for st in existing_route.trips[0].stop_times]                           if existing_route.trips else []
    existing_comp_id    = existing_route.trips[0].composition.comp_id                           if existing_route.trips else None

    new_stop_ids = [s["stop_id"] for s in (new_stops or [])]

    stops_changed = bool(new_stops) and new_stop_ids != existing_stop_ids
    comp_changed  = bool(new_composition) and new_composition != existing_comp_id

    return not stops_changed and not comp_changed


@bp.post("/planOrUpdate")
def plan_or_update():
    """
    Plan a new route or adjust an existing one.

    The backend derives automatically whether a full reroute is needed:
      - No 'route' in body                           → plan (new route)
      - 'route' in body, stops/composition unchanged  → adjust (schedule only)
      - 'route' in body, stops or composition changed → plan (full reroute)

    Request body:
      proposal_id       : int   (required)
      proposal_version  : int   (required)
      stops             : [{stop_id, stop_type}, ...]  (required for plan)
      composition_id    : str   (required for plan)
      departure_time    : "HH:MM"  (optional — keep existing if omitted)
      route             : Route.to_dict() output  (required for adjust, optional for plan)
      stop_type_changes : {stop_id: stop_type}  (optional — adjust specific stops)
    """
    loader = get_loader()

    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "bad_request", "message": "Request body must be JSON."}), 400

    errors = _validate(body)
    if errors:
        return jsonify({"error": "validation_error", "details": errors}), 400

    existing_route = Route.from_dict(body["route"]) if body.get("route") else None
    use_adjust     = existing_route is not None and _is_adjust(body, existing_route)
    dep_min        = hhmm_to_min(body["departure_time"]) if body.get("departure_time") else None

    try:
        if use_adjust:
            logger.info(
                "planOrUpdate: adjust route %s → version %d",
                existing_route.route_id, body["proposal_version"],
            )
            route = adjust_route(
                existing_route     = existing_route,
                proposal_id        = body["proposal_id"],
                proposal_version   = body["proposal_version"],
                departure_time_min = dep_min,
                stop_type_changes  = body.get("stop_type_changes"),
                loader             = loader,
            )
        else:
            logger.info(
                "planOrUpdate: plan route proposal_id=%d version=%d",
                body["proposal_id"], body["proposal_version"],
            )
            # use stops/composition from body if provided, else fall back to existing route
            stops_input    = body.get("stops") or [
                {"stop_id": st.stop_id, "stop_type": st.stop_type}
                for st in existing_route.trips[0].stop_times
            ] if existing_route else body["stops"]
            comp_id        = body.get("composition_id") or (
                existing_route.trips[0].composition.comp_id if existing_route else None
            )
            dep_min_plan   = dep_min or (
                existing_route.trips[0].stop_times[0].departure_time_min
                if existing_route else None
            )

            router = RailRouter()
            route  = plan_route(
                proposal_id        = body["proposal_id"],
                proposal_version   = body["proposal_version"],
                stop_inputs        = [(s["stop_id"], s["stop_type"]) for s in stops_input],
                composition_id     = comp_id,
                departure_time_min = dep_min_plan,
                loader             = loader,
                router             = router,
            )

    except ValueError as e:
        logger.warning("planOrUpdate failed (domain error): %s", e)
        return jsonify({"error": "domain_error", "message": str(e)}), 422
    except Exception as e:
        logger.exception("planOrUpdate failed (unexpected): %s", e)
        return jsonify({"error": "route_error", "message": str(e)}), 500

    return jsonify({
        "route_builder_version": ROUTE_BUILDER_VERSION,
        "action_taken":          "adjust" if use_adjust else "plan",
        "route":                 route.to_dict(),
    }), 200