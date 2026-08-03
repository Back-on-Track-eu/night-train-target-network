"""
pipeline.py
===========
Central dispatch for the route-plan-and-evaluate pipeline (PROPOSALS_
DESIGN.md §2.1, WP5). Pure domain-level orchestration: no Flask, no dicts,
no DB writes — composes models/route, models/demand, and models/evaluation
so every caller (the /calc endpoint, publish, the future compute cache of
WP13, model-level tests, and the DB seed's example proposal) shares one
implementation instead of each re-assembling the same steps.

Serialization stays out of this module on purpose — that's api/helpers/
proposal_compute.py's job (dicts, fingerprinting, ID-prefix stripping).
This module only ever hands back domain objects.

Public interface:
  run_compute(...) -> ComputeResult                     (full pipeline:
                                                          plan → stopgap
                                                          demand → evaluate
                                                          → views)
  evaluate_and_build_views(route, tracks, stop_infra)
      -> (EvaluationResult, ViewsBundle)                (the post-routing
                                                          half, for callers
                                                          that bring their
                                                          own Route/demand:
                                                          db/dev/seed.py's
                                                          hand-crafted
                                                          example, tests/
                                                          helpers.py's
                                                          controlled-demand
                                                          evaluations)
"""

from __future__ import annotations

from dataclasses import dataclass

from models.demand.stopgap import distribute_demand
from models.demand.version import (
    STOPGAP_FARE_PER_KM_BY_CLASS,
    STOPGAP_UTILIZATION_PER,
)
from models.evaluation.calc import EvaluationResult, evaluate_route
from models.evaluation.views import ViewsBundle, build_all_views
from models.params import StopInfraCollection, TrackInfraCollection
from models.route.route import Route
from models.route.route_factory import (
    AutoStopSuggestion,
    RouteProvenance,
    TripPairInput,
    plan_route,
)
from models.route.routing.rail_router import RailRouter


@dataclass
class ComputeResult:
    """Everything one compute pass produces — route, provenance, and the
    full evaluation, all still domain objects. Callers serialize whatever
    subset they need (api/helpers/proposal_compute.py serializes all of
    it; a model-level test typically only reads views.bd_all/bd_per_pair).
    """

    route: Route
    provenance: RouteProvenance
    suggestions: list[AutoStopSuggestion]
    evaluation_result: EvaluationResult
    views: ViewsBundle


def evaluate_and_build_views(
    route: Route,
    tracks: TrackInfraCollection,
    stop_infra: StopInfraCollection,
) -> tuple[EvaluationResult, ViewsBundle]:
    """Evaluate an already-built, already-demand-populated Route and build
    every breakdown view — the post-routing half of run_compute(), exposed
    for callers that construct their Route another way (the seed's
    hand-crafted example route, tests applying controlled demand)."""
    result = evaluate_route(route=route, tracks=tracks, stop_infra=stop_infra)
    return result, build_all_views(route, result)


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
    """Build a route and evaluate it in one call — the steps every compute
    path (POST /api/proposal/calc, publish, future cache misses) needs:
    plan → stopgap demand → evaluate → views.

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
    # models/demand/version.py. Mutates route in place.
    distribute_demand(
        route,
        utilization_per=STOPGAP_UTILIZATION_PER,
        fare_per_km_by_class=STOPGAP_FARE_PER_KM_BY_CLASS,
    )

    evaluation_result, views = evaluate_and_build_views(
        route, provenance.tracks, provenance.stop_infra
    )

    return ComputeResult(
        route=route,
        provenance=provenance,
        suggestions=suggestions,
        evaluation_result=evaluation_result,
        views=views,
    )
