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
member_compute.py's job (dicts, fingerprinting, ID-prefix stripping).
This module only ever hands back domain objects.

Public interface:
  run_compute(...) -> ComputeResult                     (full pipeline:
                                                          plan → demand →
                                                          evaluate → views)
  evaluate_and_build_views(route, tracks, stop_infra, passages)
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

from models.route.model import DEFAULT_MIN_TURNAROUND_MIN
from dataclasses import dataclass

from models.demand.distribute import DemandInputs, DemandResult, distribute_demand
from models.demand.model import (
    resolve_catering,
    resolve_fares,
    resolve_fares_per_pax,
    resolve_services,
)
from models.evaluation.calc import EvaluationResult, evaluate_route
from models.evaluation.views import ViewsBundle, build_all_views
from models.params import (
    MeasureSet,
    NO_MEASURES,
    PassageChargeCollection,
    StopInfraCollection,
    TrackInfraCollection,
)
from models.route.route import Route
from models.route.route_factory import (
    AutoStopSuggestion,
    RouteProvenance,
    TripPairInput,
    plan_route,
)
from models.route.routing.rail_router import RailRouter
from models.route.timetable import ExpertTimetable


@dataclass
class ComputeResult:
    """Everything one compute pass produces — route, provenance, and the
    full evaluation, all still domain objects. Callers serialize whatever
    subset they need (api/helpers/member_compute.py serializes all of
    it; a model-level test typically only reads views.bd_all/bd_per_pair).
    """

    route: Route
    provenance: RouteProvenance
    suggestions: list[AutoStopSuggestion]
    evaluation_result: EvaluationResult
    views: ViewsBundle
    # DEMAND 0.1.0: the allocation and OD spread behind the route's
    # od_pairs — the figures the Details card shows, serialised by
    # api/helpers/evaluation_serialize.py::demand_to_dict.
    demand: DemandResult


def evaluate_and_build_views(
    route: Route,
    tracks: TrackInfraCollection,
    stop_infra: StopInfraCollection,
    passages: PassageChargeCollection,
    measures: MeasureSet = NO_MEASURES,
    catering_eur_per_pax: dict | None = None,
    services_eur_per_pax: dict | None = None,
) -> tuple[EvaluationResult, ViewsBundle]:
    """Evaluate an already-built, already-demand-populated Route and build
    every breakdown view — the post-routing half of run_compute(), exposed
    for callers that construct their Route another way (the seed's
    hand-crafted example route, tests applying controlled demand).

    measures: the measure set to price under (models/params.py). Defaults
    to NO_MEASURES, which is what every caller before WP18 asked for
    implicitly — and what a family member gets for every scenario variant
    until WP17 seeds a second set. The one thing measure sets multiply is
    this half of the pipeline: a variant re-evaluates a route it does not
    rebuild.

    catering_eur_per_pax / services_eur_per_pax: the two per-class tariff
    parts that ride on passengers rather than on distance
    (models/demand/model.py). None takes the demand model's own standard
    values, for the same reason measures defaults to NO_MEASURES.
    """
    result = evaluate_route(
        route=route,
        tracks=tracks,
        stop_infra=stop_infra,
        passages=passages,
        measures=measures,
        catering_eur_per_pax=resolve_catering(catering_eur_per_pax),
        services_eur_per_pax=resolve_services(services_eur_per_pax),
    )
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
    schedule: dict,
    min_turnaround_min: int = DEFAULT_MIN_TURNAROUND_MIN,
    demand: DemandInputs,
    fares_eur_per_km: dict | None = None,
    fares_eur_per_pax: dict | None = None,
    catering_eur_per_pax: dict | None = None,
    services_eur_per_pax: dict | None = None,
    routing_mode: str,
    auto_stop_addition: str,
    loader,
    router: RailRouter,
    expert_timetable: ExpertTimetable | None = None,
    measures: MeasureSet = NO_MEASURES,
) -> ComputeResult:
    """Build a route and evaluate it in one call — the steps every compute
    path (the family's members, publish, member-cache misses) needs:
    plan → demand → evaluate → views.

    proposal_id/proposal_version: purely ID-building placeholders for
    plan_route()'s P{id}_V{version}_-prefixed ID convention (see
    route_factory.py) — never resolved/defaulted here, callers decide
    (NEUTRAL_PROPOSAL_ID/VERSION for ephemeral compute, real ids at
    publish time). Every other field must already be resolved (defaults
    applied) — that resolution is an API-boundary concern, not this
    module's. schedule is the twelve-month map api/helpers/member_compute.py
    resolves from one posted frequency (or a posted map, or nothing);
    demand is the request's demand block as values, defaults filled in
    there too (models/demand/distribute.py::DemandInputs).

    expert_timetable: the request's manual timetable overrides, already
    turned into domain objects at the API boundary (api/helpers/
    route_serialize.py::expert_timetable_from_dict). None — the default,
    and what every request without the key produces — means a fully
    automatic timetable, byte-identical to what this pipeline returned
    before the option existed. Defaulted here (unlike the mode strings,
    which callers must pass) because it is genuinely optional input, not
    a mode whose default belongs at the API boundary.

    measures: the scenario variant's measure set, defaulted here for the
    same reason as expert_timetable — genuinely optional input, not a mode
    string. Only the evaluate half reads it; routing, timetable and demand
    are measure-independent, which is why a family builds one route per
    (scenario, composition) and evaluates it once per measure set.
    """
    route, provenance, suggestions = plan_route(
        proposal_id=proposal_id,
        proposal_version=proposal_version,
        schedule=schedule,
        min_turnaround_min=min_turnaround_min,
        trip_pair_inputs=[
            TripPairInput(
                stop_ids=stops,
                composition_id=composition_id,
                timetable_mode=timetable_mode,
                routing_mode=routing_mode,
                auto_stop_addition=auto_stop_addition,
                fixed_night_interval=fixed_night_interval,
                expert_timetable=expert_timetable,
            )
        ],
        loader=loader,
        router=router,
        scenario_id=scenario_id,
    )

    # The manual demand model (DEMAND 0.1.0) — mutates route in place and
    # hands back the allocation the API reports.
    demand_result = distribute_demand(
        route,
        demand,
        fare_per_km_by_class=resolve_fares(fares_eur_per_km),
        fare_per_pax_by_class=resolve_fares_per_pax(fares_eur_per_pax),
    )

    evaluation_result, views = evaluate_and_build_views(
        route,
        provenance.tracks,
        provenance.stop_infra,
        provenance.passages,
        measures,
        catering_eur_per_pax,
        services_eur_per_pax,
    )

    return ComputeResult(
        route=route,
        provenance=provenance,
        suggestions=suggestions,
        evaluation_result=evaluation_result,
        views=views,
        demand=demand_result,
    )
