"""
proposal_compute.py
====================
Validation + serialization wrapper around models/pipeline.py's
run_compute() (adapters/proposal/README.md §2.1) — the single place that turns a
compute request body into the merged route+evaluation response dict. Used
by POST /api/proposal/calc (api/proposal_calc.py), publish
(api/helpers/publish_dispatch.py), the on-load refresh fallback
(api/proposals.py), and scripts/refresh_proposals.py (§4.2, WP8) — every
path that turns a compute_request into a stored proposal state goes
through here, so they can never drift from what a live /calc call would
have returned for the same request — and every one of them rides the
same §2.3 compute cache (WP13), wired in below: hash the resolved
request, serve a fresh-enough cached result, compute only on a miss.

validate_calc_body() lives here (not in the view module) so both entry
points import their shared validation from the helper layer — api/*.py
blueprints stay thin delegation and are never imported by helpers.

compute_proposal() does the serialization steps: route_to_dict()/
views_to_dict()/models_to_dict()/input_to_dict(), the route fingerprint,
the resolved-request echo, and stripping the neutral P0_V0_ ID prefix
down to the structural R1/T.../ form §2.1 specifies. It returns the
payload TOGETHER with the cache_hit flag rather than embedding the flag
in the payload — publish and the refresh paths persist the payload dict
verbatim, and a cache_hit key in it would leak into stored state.
Whether/where the flag appears on the wire stays the caller's concern
(/calc and compare expose it; publish never does).

Public interface:
  validate_calc_body(body: dict) -> list[str]
  canonical_request_hash(resolved_request: dict) -> str
  compute_proposal(body, loader=None, router=None, use_cache=True)
      -> tuple[dict, bool]   # (§2.1 response payload, cache_hit)
"""

from __future__ import annotations

import hashlib
import json

from adapters.proposal.id_prefix import rewrite_id_prefix
from adapters.proposal.projection import route_fingerprint
from models.evaluation.summary import build_summary_row
from api.helpers.dependencies import get_compute_cache, get_loader, get_rail_router
from api.helpers.evaluation_serialize import (
    input_to_dict,
    models_to_dict,
    views_to_dict,
)
from api.helpers.route_serialize import route_to_dict, suggested_stops_to_dicts
from models.evaluation.model import CALC_VERSION
from models.pipeline import run_compute
from models.route.timetable import (
    VALID_AUTO_STOP_ADDITION_MODES,
    VALID_SCHEDULE_MODES,
    VALID_TIMETABLE_MODES,
)
from models.route.routing.rail_router import VALID_ROUTING_MODES
from models.route.model import (
    DEFAULT_AUTO_STOP_ADDITION,
    DEFAULT_ROUTING_MODE,
    DEFAULT_SCHEDULE_MODE,
    DEFAULT_TIMETABLE_MODE,
    NEUTRAL_PROPOSAL_ID,
    NEUTRAL_PROPOSAL_VERSION,
    ROUTE_BUILDER_VERSION,
)

_NEUTRAL_PREFIX = f"P{NEUTRAL_PROPOSAL_ID}_V{NEUTRAL_PROPOSAL_VERSION}_"


def validate_calc_body(body: dict) -> list[str]:
    """Request validation for the merged compute request (§2.1) — the
    former plan request's WHAT/HOW fields, minus proposal_id/
    proposal_version (publish-only, not a compute concern). Shared by
    api/proposal_calc.py and api/helpers/publish_dispatch.py so both
    entry points reject the same malformed compute_request the same
    way."""
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


def canonical_request_hash(resolved_request: dict) -> str:
    """§2.3's request hash: SHA-256 over the canonical JSON form of the
    RESOLVED request (sorted keys, no whitespace). Hashing the resolved
    form — not the posted body — is what makes an omitted field and an
    explicitly-posted default converge on the same cache entry. All
    request values are strings/ints/lists of strings, so JSON encoding is
    trivially stable; the sha256: prefix matches the fingerprint format
    (§3.1) for at-a-glance recognizability in the DB."""
    canonical = json.dumps(resolved_request, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _resolve_request(body: dict, loader) -> dict:
    """The §2.1 resolved-request echo — defaults applied, scenario_id
    concrete — built BEFORE the compute so it can double as the cache key
    input. An omitted field and an explicitly-posted default must compare
    (and hash) equal, so this is built explicitly rather than echoing the
    posted body verbatim."""
    return {
        "stops": list(body["stops"]),
        "composition_id": body["composition_id"],
        "scenario_id": loader.resolve_scenario_id(body.get("scenario_id")),
        "timetable_mode": body.get("timetable_mode", DEFAULT_TIMETABLE_MODE),
        "fixed_night_interval": body.get("fixed_night_interval"),
        "schedule_mode": body.get("schedule_mode", DEFAULT_SCHEDULE_MODE),
        "routing_mode": body.get("routing_mode", DEFAULT_ROUTING_MODE),
        "auto_stop_addition": body.get(
            "auto_stop_addition", DEFAULT_AUTO_STOP_ADDITION
        ),
    }


# Response parts shared between every request converging on one result —
# what compute_cache_result.payload carries. Everything else (the request
# echo, suggested_stops) is request-specific and lives on the pointer row.
_SHARED_PAYLOAD_KEYS = (
    "route_builder_version",
    "calc_version",
    "summary",
    "route",
    "evaluation",
)


def _response_from_cache(entry: dict) -> dict:
    """Reassemble the §2.1 response from a cache hit: shared payload +
    this pointer's request-specific parts, in the exact key order the
    miss path produces."""
    payload = entry["payload"]
    response = {
        "route_builder_version": payload["route_builder_version"],
        "calc_version": payload["calc_version"],
        "route_fingerprint": entry["route_fingerprint"],
        "request": entry["resolved_request"],
    }
    if entry["suggested_stops"] is not None:
        response["suggested_stops"] = entry["suggested_stops"]
    for key in ("summary", "route", "evaluation"):
        response[key] = payload[key]
    return response


def compute_proposal(
    body: dict, loader=None, router=None, use_cache: bool = True
) -> tuple[dict, bool]:
    """Resolve + serve-from-cache-or-compute one request body (§2.1's
    WHAT/HOW fields — stops, composition_id, scenario_id, timetable_mode,
    fixed_night_interval, schedule_mode, routing_mode,
    auto_stop_addition). Callers validate the body first
    (validate_calc_body() above) — this function assumes it's already
    been checked and lets models/pipeline.py's ValueError (domain errors)
    propagate uncaught.

    loader/router default to the process-wide singletons (get_loader()/
    get_rail_router()) — every Flask caller (/calc, publish, compare, the
    on-load refresh fallback) relies on this default and passes neither.
    The override exists for scripts/refresh_proposals.py's concurrent
    batch mode: DBDataLoader holds one non-thread-safe connection, so
    each worker thread needs its OWN loader instance, while RailRouter (a
    pooled requests.Session, explicitly built for concurrent use — see
    api/helpers/dependencies.py's docstring) stays shared across threads
    via the ordinary singleton default. use_cache=False exists for the
    same script and the same reason (the cache repository is a singleton
    with one connection) — and costs it nothing: the script flushes the
    cache first and computes each proposal exactly once, so hits are
    impossible there anyway.

    Cache flow (§2.3, WP13): resolved request -> canonical hash ->
    pointer lookup. A hit whose stored payload matches the running
    ROUTE_BUILDER_VERSION/CALC_VERSION is served with zero routing and
    zero evaluation; a version mismatch is treated as a miss (defense in
    depth for a forgotten flush — the recompute below overwrites the
    stale rows). On a miss, the freshly computed response is split into
    the shared payload and the request-specific pointer parts and written
    back through ComputeCacheRepository.store().

    Returns (payload, cache_hit): the full §2.1 response shape
      {route_builder_version, calc_version, route_fingerprint, request,
       suggested_stops?, summary, route, evaluation}
    plus whether it came from the cache. cache_hit's placement in the
    wire response stays the caller's concern (/calc and compare expose
    it; publish and the refresh paths ignore it).
    """
    loader = loader if loader is not None else get_loader()
    router = router if router is not None else get_rail_router()

    resolved_request = _resolve_request(body, loader)
    scenario_id = resolved_request["scenario_id"]

    cache = get_compute_cache() if use_cache else None
    request_hash = canonical_request_hash(resolved_request) if cache else None
    if cache is not None:
        entry = cache.lookup(request_hash)
        if (
            entry is not None
            and entry["payload"]["route_builder_version"] == ROUTE_BUILDER_VERSION
            and entry["payload"]["calc_version"] == CALC_VERSION
        ):
            return _response_from_cache(entry), True

    result = run_compute(
        proposal_id=NEUTRAL_PROPOSAL_ID,
        proposal_version=NEUTRAL_PROPOSAL_VERSION,
        stops=body["stops"],
        composition_id=body["composition_id"],
        scenario_id=scenario_id,
        timetable_mode=resolved_request["timetable_mode"],
        fixed_night_interval=resolved_request["fixed_night_interval"],
        schedule_mode=resolved_request["schedule_mode"],
        routing_mode=resolved_request["routing_mode"],
        auto_stop_addition=resolved_request["auto_stop_addition"],
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

    # §3.1 — computed from route_dict before the prefix strip below, but
    # prefix-independent by construction: the canonical extract only ever
    # uses stop_id (never route_id/trip_id/geometry_id), so the fingerprint
    # is identical whichever side of rewrite_id_prefix() it's taken from.
    fingerprint = route_fingerprint(route_dict)

    payload = {
        "route_builder_version": ROUTE_BUILDER_VERSION,
        "calc_version": CALC_VERSION,
        "route_fingerprint": fingerprint,
        "request": resolved_request,
    }
    if resolved_request["auto_stop_addition"] == "suggest":
        payload["suggested_stops"] = suggested_stops_to_dicts(result.suggestions)
    evaluation = {
        "models": models_to_dict(),
        # include_route=False: the route already appears once in the
        # payload, as a sibling of "evaluation" — see input_to_dict()'s
        # docstring.
        "input": input_to_dict(
            route_dict,
            result.provenance.tracks,
            result.provenance.stop_infra,
            result.provenance.compositions,
            include_route=False,
        ),
        "views": views_to_dict(result.views, result.route),
    }
    # §5.4 gallery KPIs, derived from the exact route/evaluation dicts
    # this response carries — the same build_summary_row() the publish
    # projection uses, so the calc "summary" and a published gallery row
    # cannot drift. No geom_simplified here: the response already has the
    # full per-segment geometry (the gallery row needs the simplified
    # copy precisely because it has no segments).
    payload["summary"] = build_summary_row(route_dict, evaluation)
    payload["route"] = route_dict
    payload["evaluation"] = evaluation

    response = rewrite_id_prefix(payload, _NEUTRAL_PREFIX, "")

    if cache is not None:
        cache.store(
            request_hash=request_hash,
            route_fingerprint=fingerprint,
            scenario_id=scenario_id,
            composition_id=body["composition_id"],
            resolved_request=response["request"],
            suggested_stops=response.get("suggested_stops"),
            payload={key: response[key] for key in _SHARED_PAYLOAD_KEYS},
        )

    return response, False
