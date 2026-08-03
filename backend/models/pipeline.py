"""
pipeline.py
===========
Central dispatch for the route-plan-and-evaluate pipeline (PROPOSALS_
DESIGN.md §2.1, WP5). Pure domain-level orchestration: no Flask, no dicts,
no DB writes — composes models/route and models/evaluation exactly the way
api/proposal_calc.py used to do inline, moved down a layer so every caller
(the /calc endpoint, publish, the future compute cache of WP13, and
model-level tests that need a fully evaluated Route without going through
HTTP) shares one implementation instead of each re-assembling the same six
steps.

Serialization stays out of this module on purpose — that's api/helpers/
proposal_compute.py's job (dicts, fingerprinting, ID-prefix stripping).
This module only ever hands back domain objects.

Public interface:
  run_compute(...) -> ComputeResult
"""

from __future__ import annotations

from dataclasses import dataclass

from models.evaluation.calc import EvaluationResult, evaluate_route
from models.evaluation.views import (
    Breakdown,
    NormalisationScope,
    build_breakdown,
    build_breakdown_per_trip_pair,
    build_breakdown_per_trip_pair_per_country,
    build_breakdown_per_trip_pair_per_od,
    build_breakdown_per_trip_pair_per_section,
    build_breakdown_per_trip_per_stop,
)
from models.route.route import Route
from models.route.route_factory import (
    AutoStopSuggestion,
    RouteProvenance,
    TripPairInput,
    distribute_demand,
    plan_route,
)
from models.route.routing.rail_router import RailRouter
from models.route.version import (
    STOPGAP_FARE_PER_KM_BY_CLASS,
    STOPGAP_UTILIZATION_PER,
)


@dataclass
class ComputeResult:
    """Everything one compute pass produces — route, provenance, and every
    evaluation view, all still domain objects. Callers serialize whatever
    subset they need (api/helpers/proposal_compute.py serializes all of
    it; a model-level test typically only reads bd_all/bd_per_pair)."""

    route: Route
    provenance: RouteProvenance
    suggestions: list[AutoStopSuggestion]
    evaluation_result: EvaluationResult
    bd_all: Breakdown
    bd_per_pair: dict[str, Breakdown]
    matrix_country: dict[tuple[str, str], Breakdown]
    matrix_od: dict[tuple[str, str], Breakdown]
    matrix_section: dict[tuple[str, str], Breakdown]
    section_scopes: dict[tuple[str, str], NormalisationScope]
    matrix_stop: dict[tuple[str, str], Breakdown]


def run_compute(
    *,
    proposal_id: int,
    proposal_version: int,
    stops: list[str],
    composition_id: str,
    scenario_id: int,
    timetable_mode: str,
    fixed_night_interval: list[str] | None,
    schedule_mode: str,
    routing_mode: str,
    auto_stop_addition: str,
    loader,
    router: RailRouter,
) -> ComputeResult:
    """Build a route and evaluate it in one call — the six steps every
    compute path (POST /api/proposal/calc, publish, future cache misses)
    needs: plan → stopgap demand → evaluate → the six breakdown views.

    proposal_id/proposal_version: purely ID-building placeholders for
    plan_route()'s P{id}_V{version}_-prefixed ID convention (see
    route_factory.py) — never resolved/defaulted here, callers decide
    (NEUTRAL_PROPOSAL_ID/VERSION for ephemeral compute, real ids at
    publish time). Every other field must already be resolved (defaults
    applied) — that resolution is an API-boundary concern, not this
    module's.
    """
    route, provenance, suggestions = plan_route(
        proposal_id=proposal_id,
        proposal_version=proposal_version,
        schedule_mode=schedule_mode,
        trip_pair_inputs=[
            TripPairInput(
                stop_ids=stops,
                composition_id=composition_id,
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

    # Stopgap demand distribution — see OPEN_TODOS["demand_model"] in
    # models/route/version.py. Mutates route in place.
    distribute_demand(
        route,
        utilization_per=STOPGAP_UTILIZATION_PER,
        fare_per_km_by_class=STOPGAP_FARE_PER_KM_BY_CLASS,
    )

    evaluation_result = evaluate_route(
        route=route, tracks=provenance.tracks, stop_infra=provenance.stop_infra
    )

    bd_all = build_breakdown(route, evaluation_result)
    bd_per_pair = build_breakdown_per_trip_pair(route, evaluation_result)
    matrix_country = build_breakdown_per_trip_pair_per_country(route, evaluation_result)
    matrix_od = build_breakdown_per_trip_pair_per_od(route, evaluation_result)
    matrix_section, section_scopes = build_breakdown_per_trip_pair_per_section(
        route, evaluation_result
    )
    matrix_stop = build_breakdown_per_trip_per_stop(route, evaluation_result)

    return ComputeResult(
        route=route,
        provenance=provenance,
        suggestions=suggestions,
        evaluation_result=evaluation_result,
        bd_all=bd_all,
        bd_per_pair=bd_per_pair,
        matrix_country=matrix_country,
        matrix_od=matrix_od,
        matrix_section=matrix_section,
        section_scopes=section_scopes,
        matrix_stop=matrix_stop,
    )
