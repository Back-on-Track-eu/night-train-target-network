"""
bench_member.py
===============
The numbers behind the proposal-family design (docs/PARKED_WORK.md, WP18):
how long one family MEMBER costs once the route is cached, split into the
layers the design separates.

    L1  routing         cold: legs routed live; warm: legs from route_cache
    L2  timetable       part of "reassembly" below (route built from cached
                        legs + timetable + stopgap demand)
    L3  evaluation      evaluate_route + build_all_views — the cost every
                        one of the 648 members pays
    --  serialisation   views_to_dict, what the wire carries per member

Run inside the api container against the live stack:

    docker exec night-train-api python -m scripts.bench_member
    docker exec night-train-api python -m scripts.bench_member --stops osm:n3856100103 osm:n25397500 osm:w423692233
    docker exec night-train-api python -m scripts.bench_member --repeat 10

Prints the medians and the projections that decide sync-vs-job for
POST /api/proposal/family and whether members need a cache at all.
"""

from __future__ import annotations

import argparse
import logging
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import dev_env  # noqa: E402

dev_env.resolve_env()

from api.config import CALC_MATRIX_WORKERS  # noqa: E402
from api.helpers import dependencies  # noqa: E402
from api.helpers.evaluation_serialize import views_to_dict  # noqa: E402
from api.helpers.proposal_compute import compute_proposal  # noqa: E402
from models.pipeline import evaluate_and_build_views, run_compute  # noqa: E402
from models.route.model import (  # noqa: E402
    DEFAULT_COMPOSITION_ID,
    DEFAULT_ROUTING_MODE,
    DEFAULT_SCHEDULE_MODE,
    DEFAULT_TIMETABLE_MODE,
    NEUTRAL_PROPOSAL_ID,
    NEUTRAL_PROPOSAL_VERSION,
)

BERLIN_WIEN = ["osm:n3856100103", "osm:w423692233"]
SECOND_COMPOSITION = "REF-POD-14"

N_MEMBERS = 648  # 54 scenario variants × 12 compositions
N_BASE_EVALUATIONS = 81  # 648 / 8 measure sets — the post-pass design
N_ROUTE_VARIANTS = 8


def timed(fn, repeat: int) -> list[float]:
    out = []
    for _ in range(repeat):
        t = time.perf_counter()
        fn()
        out.append(time.perf_counter() - t)
    return out


def ms(values: list[float]) -> str:
    return f"{statistics.median(values) * 1000:8.0f} ms  (n={len(values)})"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--stops", nargs="+", default=BERLIN_WIEN)
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--composition", default=DEFAULT_COMPOSITION_ID)
    parser.add_argument("--second-composition", default=SECOND_COMPOSITION)
    args = parser.parse_args()

    # The loader's "no row for BY/RU, using defaults" warnings fire on every
    # catalog build and would print 2 × repeat lines here; they are a known
    # seed property, not a measurement.
    logging.getLogger("adapters.data_loader_from_db").setLevel(logging.ERROR)
    dependencies.init()
    loader = dependencies.get_loader()
    scenario_id = loader.resolve_scenario_id(None)
    body = {
        "stops": args.stops,
        "composition_id": args.composition,
        "auto_stop_addition": "off",
    }

    print(
        f"stops: {args.stops}   composition: {args.composition}   scenario: {scenario_id}"
    )
    print(f"workers assumed for projections: {CALC_MATRIX_WORKERS}\n")

    # L1 cold — whatever the segment cache does not hold gets routed live.
    cold = timed(lambda: compute_proposal(body, use_cache=False), 1)
    print(f"member, first time   (legs may route live)   {ms(cold)}")

    # Same member again: every leg hot, request cache bypassed →
    # reassembly + timetable + demand + L3 + serialisation.
    warm = timed(lambda: compute_proposal(body, use_cache=False), args.repeat)
    print(f"member, legs cached  (full request path)     {ms(warm)}")

    # Other composition, same route variant group or the other one — the
    # cost of a NEW member on cached legs.
    other = {**body, "composition_id": args.second_composition}
    warm_other = timed(lambda: compute_proposal(other, use_cache=False), args.repeat)
    print(f"member, other composition, legs cached       {ms(warm_other)}")

    # L3 alone: evaluate + views on an already-built, demand-populated route.
    result = run_compute(
        proposal_id=NEUTRAL_PROPOSAL_ID,
        proposal_version=NEUTRAL_PROPOSAL_VERSION,
        stops=args.stops,
        composition_id=args.composition,
        scenario_id=scenario_id,
        timetable_mode=DEFAULT_TIMETABLE_MODE,
        fixed_night_interval=None,
        schedule_mode=DEFAULT_SCHEDULE_MODE,
        routing_mode=DEFAULT_ROUTING_MODE,
        auto_stop_addition="off",
        loader=loader,
        router=dependencies.get_rail_router(
            loader.resolve_routing_graph_key(scenario_id)
        ),
    )
    prov = result.provenance
    evaluation = timed(
        lambda: evaluate_and_build_views(
            result.route, prov.tracks, prov.stop_infra, prov.passages
        ),
        args.repeat,
    )
    print(f"L3 evaluate + views only                     {ms(evaluation)}")

    serialisation = timed(
        lambda: views_to_dict(result.views, result.route), args.repeat
    )
    print(f"views_to_dict (wire shape of one member)     {ms(serialisation)}")

    t_eval = statistics.median(evaluation)
    t_member = statistics.median(warm)
    t_reassembly = max(0.0, t_member - t_eval - statistics.median(serialisation))
    print("\nderived")
    print(
        f"  reassembly + timetable + demand per member  {t_reassembly * 1000:8.0f} ms"
    )
    workers = max(1, CALC_MATRIX_WORKERS)
    print("\nprojections (routes cached)")
    print(
        f"  {N_MEMBERS} members, full evaluation each       "
        f"{N_MEMBERS * t_eval / workers:6.1f} s on {workers} workers"
    )
    print(
        f"  {N_BASE_EVALUATIONS} evaluations + measures post-pass    "
        f"{N_BASE_EVALUATIONS * t_eval / workers:6.1f} s on {workers} workers"
    )
    print(
        f"  {N_ROUTE_VARIANTS} route variants, legs cached          "
        f"{N_ROUTE_VARIANTS * t_reassembly / workers:6.1f} s on {workers} workers"
    )
    print(
        f"  first-open worst case (routes live)          "
        f"~{statistics.median(cold) * N_ROUTE_VARIANTS / workers:6.1f} s + members"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
