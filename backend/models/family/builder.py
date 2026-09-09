"""
builder.py
==========
run_family(): every member of one stop list + HOW under the current pins,
built on one FamilyContext. Pure domain orchestration over
models/pipeline.py — no dicts, no I/O of its own; the API layer
(api/helpers/family_compute.py) resolves the request and axes before,
and serialises the result after.

Shape of a build
----------------
  1. prewarm  — the context fans out over every (scenario, composition,
                direction): catalogs once per scenario, raw legs once per
                distinct variant. The only threaded phase, because it is
                the only I/O (scripts/bench_member.py: a member is 4 ms
                once these are shared; threads on that only contend).
  2. baseline — the presented member runs first, alone, with the
                request's auto_stop_addition: this is the one member whose
                suggestions ride on the document. Every other member runs
                with "off" — suggestions are the same corridor's candidates
                either way, and the search is the one expensive step no
                memo covers.
  3. members  — serial loop over (scenario variant, composition), variants
                outer, compositions inner. One run_compute() per
                (scenario, composition); when several variants share a
                scenario (several measure sets, WP17) the route is built
                once and only evaluate_and_build_views() repeats, because
                measures never touch routing, timetable or demand.

Every failure a member can raise — a graph this deployment does not run,
a stop pair the router cannot serve, a gauge mismatch, a domain
ValueError — becomes an error member with the exception attached; the
API layer maps it to the same wire code /calc would answer
(classify_compute_error()). The family is still complete: on a
one-instance stack every infra_2032 member is an error member and the
document is still 200.

Public interface:
  FamilyAxes(variants, scenarios, measure_sets, compositions)
  run_family(request, axes, context, presented) -> FamilyResult
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from models.evaluation.calc import EvaluationResult
from models.evaluation.views import ViewsBundle
from models.params import Composition, MeasureSet, Scenario, ScenarioVariant
from models.pipeline import ComputeResult, evaluate_and_build_views, run_compute
from models.route.model import NEUTRAL_PROPOSAL_ID, NEUTRAL_PROPOSAL_VERSION
from models.route.route import Route
from models.route.route_factory import AutoStopSuggestion, RouteProvenance
from models.route.timetable import ExpertTimetable

from .context import FamilyContext


@dataclass(frozen=True)
class FamilyRequest:
    """The resolved WHAT + HOW every member shares — the request echo of
    api/helpers/proposal_compute.py as domain values. scenario and
    composition are deliberately absent: those are the axes."""

    stops: list[str]
    timetable_mode: str
    fixed_night_interval: list[str] | None
    schedule_mode: str
    routing_mode: str
    auto_stop_addition: str
    expert_timetable: ExpertTimetable | None


@dataclass(frozen=True)
class FamilyAxes:
    """The two axes, resolved to domain objects, in presentation order.
    scenarios / measure_sets are lookups for the variants' ids."""

    variants: list[ScenarioVariant]
    scenarios: dict[int, Scenario]
    measure_sets: dict[int, MeasureSet]
    compositions: list[Composition]

    @property
    def n_members(self) -> int:
        return len(self.variants) * len(self.compositions)


@dataclass
class FamilyMember:
    """One (scenario variant, composition). status is "ok" with a
    computation, or "error" with the exception that stopped it."""

    scenario_variant_id: int
    scenario_id: int
    measure_set_id: int
    composition_id: str
    status: str
    route: Route | None = None
    provenance: RouteProvenance | None = None
    evaluation_result: EvaluationResult | None = None
    views: ViewsBundle | None = None
    error: BaseException | None = None

    @property
    def route_key(self) -> tuple[int, str]:
        """(scenario_id, composition_id) — the route this member was
        evaluated on. Variants of one scenario share it."""
        return self.scenario_id, self.composition_id


@dataclass
class FamilyResult:
    request: FamilyRequest
    axes: FamilyAxes
    presented: tuple[int, str]
    suggestions: list[AutoStopSuggestion]
    members: list[FamilyMember]
    elapsed_s: float
    context_stats: dict = field(default_factory=dict)

    @property
    def n_ok(self) -> int:
        return sum(1 for m in self.members if m.status == "ok")

    @property
    def n_error(self) -> int:
        return len(self.members) - self.n_ok

    def member(self, scenario_variant_id: int, composition_id: str) -> FamilyMember:
        for m in self.members:
            if (m.scenario_variant_id, m.composition_id) == (
                scenario_variant_id,
                composition_id,
            ):
                return m
        raise KeyError((scenario_variant_id, composition_id))


def _build_route(
    request: FamilyRequest,
    scenario: Scenario,
    composition: Composition,
    measures: MeasureSet,
    context: FamilyContext,
    auto_stop_addition: str,
) -> ComputeResult:
    """One run_compute() on the shared context — the same call
    api/helpers/proposal_compute.py makes, with the memoised loader and
    router in place of the singletons."""
    return run_compute(
        proposal_id=NEUTRAL_PROPOSAL_ID,
        proposal_version=NEUTRAL_PROPOSAL_VERSION,
        stops=request.stops,
        composition_id=composition.comp_id,
        scenario_id=scenario.scenario_id,
        timetable_mode=request.timetable_mode,
        fixed_night_interval=request.fixed_night_interval,
        schedule_mode=request.schedule_mode,
        routing_mode=request.routing_mode,
        auto_stop_addition=auto_stop_addition,
        expert_timetable=request.expert_timetable,
        loader=context.loader,
        router=context.router(scenario.routing_graph_key),
        measures=measures,
    )


def run_family(
    request: FamilyRequest,
    axes: FamilyAxes,
    context: FamilyContext,
    presented: tuple[int, str],
    workers: int,
) -> FamilyResult:
    """Build every member. presented is (scenario_variant_id,
    composition_id) — the member that runs first and carries the
    request's auto_stop_addition; workers sizes the prewarm fan-out only.
    """
    started = time.perf_counter()
    context.prewarm(
        axes.scenarios.values(),
        axes.compositions,
        request.stops,
        request.routing_mode,
        workers,
    )

    members: list[FamilyMember] = []
    suggestions: list[AutoStopSuggestion] = []
    # Routes already built in this family, by (scenario_id, composition_id)
    # — the second variant of a scenario re-evaluates rather than rebuilds.
    built: dict[tuple[int, str], ComputeResult] = {}

    # Presented first, so its suggestions exist before anything else runs
    # and a client that only waits for the presented member sees it early
    # once the endpoint streams (it does not today; the order still
    # documents the intent).
    order = sorted(
        (
            (variant, composition)
            for variant in axes.variants
            for composition in axes.compositions
        ),
        key=lambda vc: (vc[0].scenario_variant_id, vc[1].comp_id) != presented,
    )

    for variant, composition in order:
        scenario = axes.scenarios[variant.scenario_id]
        measures = axes.measure_sets[variant.measure_set_id]
        is_presented = (variant.scenario_variant_id, composition.comp_id) == presented
        member = FamilyMember(
            scenario_variant_id=variant.scenario_variant_id,
            scenario_id=scenario.scenario_id,
            measure_set_id=measures.measure_set_id,
            composition_id=composition.comp_id,
            status="ok",
        )
        try:
            route_key = (scenario.scenario_id, composition.comp_id)
            computed = built.get(route_key)
            if computed is None:
                computed = _build_route(
                    request,
                    scenario,
                    composition,
                    measures,
                    context,
                    request.auto_stop_addition if is_presented else "off",
                )
                built[route_key] = computed
                if is_presented:
                    suggestions = computed.suggestions
                member.evaluation_result, member.views = (
                    computed.evaluation_result,
                    computed.views,
                )
            else:
                # Same route, different measures: the only half that
                # depends on the measure set (models/pipeline.py).
                prov = computed.provenance
                member.evaluation_result, member.views = evaluate_and_build_views(
                    computed.route,
                    prov.tracks,
                    prov.stop_infra,
                    prov.passages,
                    measures,
                )
            member.route = computed.route
            member.provenance = computed.provenance
        except Exception as exc:  # noqa: BLE001 — every failure is a member
            member.status = "error"
            member.error = exc
        members.append(member)

    # Back into presentation order: variants outer, compositions inner.
    position = {v.scenario_variant_id: i for i, v in enumerate(axes.variants)}
    column = {c.comp_id: i for i, c in enumerate(axes.compositions)}
    members.sort(
        key=lambda m: (position[m.scenario_variant_id], column[m.composition_id])
    )

    return FamilyResult(
        request=request,
        axes=axes,
        presented=presented,
        suggestions=suggestions,
        members=members,
        elapsed_s=time.perf_counter() - started,
        context_stats=context.stats,
    )
