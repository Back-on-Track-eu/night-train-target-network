"""
proposal_compute.py
====================
Serialization wrapper around models/pipeline.py's run_compute()
(PROPOSALS_DESIGN.md §2.1) — the single place that turns a resolved
compute request into the merged route+evaluation response dict. Used by
both POST /api/proposal/calc (api/proposal_calc.py) and publish
(api/helpers/publish_dispatch.py), so the two paths can never drift: a
publish always stores exactly what a /calc call would have returned for
the same request. Also the natural wire-in point for WP13's compute
cache (hash the resolved request, check cache, call this only on a miss).

compute_proposal() does the serialization steps proposal_calc.py used to
do inline: route_to_dict()/views_to_dict()/models_to_dict()/
input_to_dict(), the route fingerprint, the resolved-request echo, and
stripping the neutral P0_V0_ ID prefix down to the structural R1/T.../
form §2.1 specifies. It does NOT set cache_hit — that flag depends on
which caller invokes it (proposal_calc.py always False today; publish
never even exposes it), so it stays the caller's concern.

Public interface:
  compute_proposal(body: dict) -> dict
"""

from __future__ import annotations

from adapters.proposal_projection import route_fingerprint
from adapters.proposal_repository import rewrite_id_prefix
from api.helpers.dependencies import get_country_index, get_loader
from api.helpers.evaluation_serialize import (
    input_to_dict,
    models_to_dict,
    views_to_dict,
)
from api.helpers.route_serialize import route_to_dict, suggested_stops_to_dicts
from models.evaluation.version import CALC_VERSION
from models.pipeline import run_compute
from models.route.routing.rail_router import RailRouter
from models.route.version import (
    DEFAULT_AUTO_STOP_ADDITION,
    DEFAULT_ROUTING_MODE,
    DEFAULT_SCHEDULE_MODE,
    DEFAULT_TIMETABLE_MODE,
    NEUTRAL_PROPOSAL_ID,
    NEUTRAL_PROPOSAL_VERSION,
    ROUTE_BUILDER_VERSION,
)

_NEUTRAL_PREFIX = f"P{NEUTRAL_PROPOSAL_ID}_V{NEUTRAL_PROPOSAL_VERSION}_"


def compute_proposal(body: dict) -> dict:
    """Resolve + compute one request body (§2.1's WHAT/HOW fields — stops,
    composition_id, scenario_id, timetable_mode, fixed_night_interval,
    schedule_mode, routing_mode, auto_stop_addition). Callers validate the
    body first (api/proposal_calc.py::_validate(), reused by
    api/helpers/publish_dispatch.py) — this function assumes it's already
    been checked and lets models/pipeline.py's ValueError (domain errors)
    propagate uncaught.

    Returns the full §2.1 response shape minus cache_hit:
      {route_builder_version, calc_version, route_fingerprint, request,
       suggested_stops?, route, evaluation}
    """
    loader = get_loader()
    router = RailRouter(get_country_index())

    timetable_mode = body.get("timetable_mode", DEFAULT_TIMETABLE_MODE)
    schedule_mode = body.get("schedule_mode", DEFAULT_SCHEDULE_MODE)
    routing_mode = body.get("routing_mode", DEFAULT_ROUTING_MODE)
    auto_stop_addition = body.get("auto_stop_addition", DEFAULT_AUTO_STOP_ADDITION)
    fixed_night_interval = body.get("fixed_night_interval")

    scenario_id = loader.resolve_scenario_id(body.get("scenario_id"))

    result = run_compute(
        proposal_id=NEUTRAL_PROPOSAL_ID,
        proposal_version=NEUTRAL_PROPOSAL_VERSION,
        stops=body["stops"],
        composition_id=body["composition_id"],
        scenario_id=scenario_id,
        timetable_mode=timetable_mode,
        fixed_night_interval=fixed_night_interval,
        schedule_mode=schedule_mode,
        routing_mode=routing_mode,
        auto_stop_addition=auto_stop_addition,
        loader=loader,
        router=router,
    )

    # route_dict carries the neutral-prefixed ids (P0_V0_R1...) exactly
    # like route_to_dict() always has; the evaluation views key some of
    # their data by trip_id too (per_trip_pair* matrices) —
    # rewrite_id_prefix() below strips the prefix from both in one
    # recursive pass, values AND dict keys, so the merged response is
    # prefix-free throughout.
    route_dict = route_to_dict(
        result.route, result.provenance.scenario_id, result.provenance.tracks
    )
    trip_pair_by_key = {p.outbound.trip_id: p for p in result.route.trip_pairs}

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
        "scenario_id": result.provenance.scenario_id,
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
        "request": resolved_request,
    }
    if auto_stop_addition == "suggest":
        payload["suggested_stops"] = suggested_stops_to_dicts(result.suggestions)
    payload["route"] = route_dict
    payload["evaluation"] = {
        "models": models_to_dict(),
        # include_route=False: the route already appears once above, as a
        # sibling of "evaluation" — see input_to_dict()'s docstring.
        "input": input_to_dict(
            route_dict,
            result.provenance.tracks,
            result.provenance.stop_infra,
            result.provenance.compositions,
            include_route=False,
        ),
        "views": views_to_dict(
            result.bd_all,
            result.bd_per_pair,
            result.matrix_country,
            result.matrix_od,
            result.matrix_section,
            result.section_scopes,
            result.matrix_stop,
            result.route,
            trip_pair_by_key,
        ),
    }

    return rewrite_id_prefix(payload, _NEUTRAL_PREFIX, "")
