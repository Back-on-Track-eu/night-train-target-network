"""
bench_member.py
===============
The numbers behind the proposal-family design (docs/2026-09-09_wp18_
proposal_family_plan.md): what one family MEMBER costs once its legs are
cached, attributed to the layers the design separates, and what a whole
family costs and weighs when route legs and catalogs are shared across
members. Kept as the family's regression bench — rerun after every phase.

    A  one member                compute_member(): what publish, compare and
                                 the views endpoint each pay
    B  run_compute() domain      plain, catalogs memoised, legs memoised, both —
                                 "both" is the family's per-member cost
    C  outside the domain        per-catalog load, per-step serialisation —
                                 what the plain member spends that the family
                                 document never pays
    D  family                    run_family() on a real FamilyContext, twice
                                 (fresh context each time), the serialised
                                 document weighed, then the endpoint's own
                                 build_or_load_family() as a cache miss and
                                 a cache hit

Sections B–C run on models/family/context.py's MemoLoader / MemoRouter;
section D runs the real builder (models/family/builder.py) and weighs the
real document (api/helpers/family_serialize.py), so the numbers here are
the endpoint's, not an estimate of it.

Run inside the api container against the live stack:

    docker exec night-train-api python -m scripts.bench_member
    docker exec night-train-api python -m scripts.bench_member --repeat 10 --workers 4
    docker exec night-train-api python -m scripts.bench_member --no-family
    docker exec night-train-api python -m scripts.bench_member --stops osm:n3856100103 osm:n25397500 osm:w423692233
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import dev_env  # noqa: E402

dev_env.resolve_env()

from adapters.proposal.id_prefix import rewrite_id_prefix  # noqa: E402
from adapters.proposal.projection import route_fingerprint  # noqa: E402
from api.config import FAMILY_WORKERS  # noqa: E402
from api.helpers import dependencies  # noqa: E402
from api.helpers.evaluation_serialize import (  # noqa: E402
    input_to_dict,
    models_to_dict,
    views_to_dict,
)
from api.helpers.family_compute import (  # noqa: E402
    build_or_load_family,
    resolve_family_axes,
    resolve_family_request,
    resolve_presented,
)
from api.helpers.family_serialize import family_document  # noqa: E402
from api.helpers.member_compute import (  # noqa: E402
    classify_compute_error,
    compute_member,
)
from api.helpers.route_serialize import route_to_dict  # noqa: E402
from models.evaluation.summary import build_summary_row  # noqa: E402
from models.family.builder import FamilyRequest, run_family  # noqa: E402
from models.family.context import FamilyContext, MemoLoader, MemoRouter  # noqa: E402
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
_NEUTRAL_PREFIX = f"P{NEUTRAL_PROPOSAL_ID}_V{NEUTRAL_PROPOSAL_VERSION}_"


# =============================================================================
# Timing helpers
# =============================================================================


def timed(fn, repeat: int) -> list[float]:
    out = []
    for _ in range(repeat):
        t = time.perf_counter()
        fn()
        out.append(time.perf_counter() - t)
    return out


def median_ms(values: list[float]) -> float:
    return statistics.median(values) * 1000


def row(label: str, values: list[float]) -> None:
    print(f"  {label:<52}{median_ms(values):8.0f} ms  (n={len(values)})")


def kb(n_bytes: int) -> str:
    return f"{n_bytes / 1024:8.1f} KB"


def json_bytes(obj) -> int:
    return len(json.dumps(obj, separators=(",", ":")).encode("utf-8"))


def gzip_bytes(obj) -> int:
    # Flask-Compress' default level, so this is what the wire carries.
    return len(gzip.compress(json.dumps(obj, separators=(",", ":")).encode(), 6))


# =============================================================================
# One member, one call
# =============================================================================


def member(args, scenario_id: int, loader, router, composition_id: str):
    return run_compute(
        proposal_id=NEUTRAL_PROPOSAL_ID,
        proposal_version=NEUTRAL_PROPOSAL_VERSION,
        stops=args.stops,
        composition_id=composition_id,
        scenario_id=scenario_id,
        timetable_mode=DEFAULT_TIMETABLE_MODE,
        fixed_night_interval=None,
        schedule_mode=DEFAULT_SCHEDULE_MODE,
        routing_mode=DEFAULT_ROUTING_MODE,
        auto_stop_addition="off",
        loader=loader,
        router=router,
    )


# =============================================================================
# Sections
# =============================================================================


def section_calc_path(args, body: dict) -> tuple[list[float], list[float]]:
    print("A. one member — compute_member(), member cache bypassed")
    cold = timed(lambda: compute_member(body, use_cache=False), 1)
    row("member, first time (legs may route live)", cold)
    warm = timed(lambda: compute_member(body, use_cache=False), args.repeat)
    row("member, legs cached", warm)
    other = {**body, "composition_id": args.second_composition}
    row(
        "member, other composition, legs cached",
        timed(lambda: compute_member(other, use_cache=False), args.repeat),
    )
    return cold, warm


def section_domain(args, scenario_id: int, loader, router) -> dict[str, float]:
    """run_compute() four ways. Each memo variant is filled by one untimed
    run first — the timed runs are what a member costs once the family
    has built the shared state."""
    print("\nB. run_compute() — domain only, no serialisation")
    variants = {
        "plain": ("plain loader + router", loader, router),
        "loader": ("MemoLoader only (catalogs shared)", MemoLoader(loader), router),
        "router": ("MemoRouter only (legs shared)", loader, MemoRouter(router)),
        "family": (
            "MemoLoader + MemoRouter (family member)",
            MemoLoader(loader),
            MemoRouter(router),
        ),
    }
    out: dict[str, float] = {}
    for key, (label, ld, rt) in variants.items():
        member(args, scenario_id, ld, rt, args.composition)
        values = timed(
            lambda ld=ld, rt=rt: member(args, scenario_id, ld, rt, args.composition),
            args.repeat,
        )
        row(label, values)
        out[key] = median_ms(values)

    result = member(args, scenario_id, loader, router, args.composition)
    prov = result.provenance
    evaluation = timed(
        lambda: evaluate_and_build_views(
            result.route, prov.tracks, prov.stop_infra, prov.passages
        ),
        args.repeat,
    )
    row("evaluate + views only", evaluation)
    out["evaluate"] = median_ms(evaluation)
    return out


def section_outside_domain(args, scenario_id: int, loader, warm_ms: float) -> None:
    """The plain member's non-domain cost: each catalog load run_compute()
    makes (stops twice — _build_trip_pair() and plan_route()'s parkings)
    and each serialisation step compute_member() performs, none of which
    the family document pays per member."""
    print("\nC. outside the domain — what a plain member also spends")
    print("  catalog loads per member (× = calls per run_compute)")
    loads = {
        "build_all_compositions ×1": lambda: loader.build_all_compositions(
            scenario_id, include_indicative=False
        ),
        "build_all_tracks ×1": lambda: loader.build_all_tracks(scenario_id),
        "build_all_stops ×2": lambda: loader.build_all_stops(scenario_id),
        "build_all_passages ×1": lambda: loader.build_all_passages(scenario_id),
        "resolve_scenario_id + routing_graph_key ×1": lambda: (
            loader.resolve_scenario_id(None),
            loader.resolve_routing_graph_key(scenario_id),
        ),
    }
    total_loads = 0.0
    for label, fn in loads.items():
        values = timed(fn, args.repeat)
        row("  " + label, values)
        total_loads += median_ms(values) * (2 if "×2" in label else 1)

    print("  serialisation per member (compute_member's payload)")
    result = member(
        args,
        scenario_id,
        MemoLoader(loader),
        MemoRouter(dependencies_router(loader, scenario_id)),
        args.composition,
    )
    prov = result.provenance
    route_dict = route_to_dict(result.route, scenario_id, prov.tracks)
    views = views_to_dict(result.views, result.route)
    evaluation = {"views": views}
    payload = {"route": route_dict, "evaluation": evaluation}
    steps = {
        "route_to_dict": lambda: route_to_dict(result.route, scenario_id, prov.tracks),
        "route_fingerprint": lambda: route_fingerprint(route_dict),
        "views_to_dict": lambda: views_to_dict(result.views, result.route),
        "build_summary_row": lambda: build_summary_row(route_dict, evaluation),
        "rewrite_id_prefix (whole payload)": lambda: rewrite_id_prefix(
            payload, _NEUTRAL_PREFIX, ""
        ),
    }
    total_ser = 0.0
    for label, fn in steps.items():
        values = timed(fn, args.repeat)
        row("  " + label, values)
        total_ser += median_ms(values)

    # What a member stopped carrying in WP18 B2b — timed and weighed so
    # the saving stays visible, NOT counted in the sum below: the models
    # registry is GET /api/models and the parameters are GET /api/params/*
    # for the member's scenario.
    print("  no longer in the payload (their own endpoints since B2b)")
    parameters = input_to_dict(
        route_dict, prov.tracks, prov.stop_infra, prov.compositions, False
    )
    row(
        "  input_to_dict (full catalogs → GET /api/params/*)",
        timed(
            lambda: input_to_dict(
                route_dict, prov.tracks, prov.stop_infra, prov.compositions, False
            ),
            args.repeat,
        ),
    )
    row("  models_to_dict (→ GET /api/models)", timed(models_to_dict, args.repeat))

    print("  wire weight of the member payload")
    print(f"    route (full)                   {kb(json_bytes(route_dict))}")
    print(f"    evaluation.views               {kb(json_bytes(views))}")
    print(f"    (dropped) input.parameters     {kb(json_bytes(parameters))}")
    print(f"    (dropped) models               {kb(json_bytes(models_to_dict()))}")
    print(
        f"\n  sum check: catalog loads {total_loads:.0f} ms + serialisation "
        f"{total_ser:.0f} ms = {total_loads + total_ser:.0f} ms of the "
        f"{warm_ms:.0f} ms member"
    )


def dependencies_router(loader, scenario_id: int):
    return dependencies.get_rail_router(loader.resolve_routing_graph_key(scenario_id))


def section_family(args, loader) -> None:
    """The real thing: models/family/builder.run_family() on a fresh
    FamilyContext, then api/helpers/family_serialize.family_document()
    on the result — the two halves of POST /api/proposal/family without
    the HTTP and the cache. Run twice: fresh context each time, so the
    second run shows what route_cache alone buys."""
    body = {"stops": args.stops, "auto_stop_addition": "off"}
    request_echo = resolve_family_request(body)
    axes = resolve_family_axes(body, loader)
    presented = resolve_presented(body, axes, loader)
    request = FamilyRequest(
        stops=request_echo["stops"],
        timetable_mode=request_echo["timetable_mode"],
        fixed_night_interval=request_echo["fixed_night_interval"],
        schedule_mode=request_echo["schedule_mode"],
        routing_mode=request_echo["routing_mode"],
        auto_stop_addition=request_echo["auto_stop_addition"],
        expert_timetable=None,
    )
    print(
        f"\nD. family — {len(axes.variants)} variants × "
        f"{len(axes.compositions)} compositions = {axes.n_members} members, "
        f"{args.workers} prewarm workers"
    )

    for label in ("first run (legs may route live)", "second run (legs cached)"):
        context = FamilyContext(loader, dependencies.get_rail_router)
        t = time.perf_counter()
        result = run_family(request, axes, context, presented, args.workers)
        build_s = time.perf_counter() - t

        errors: dict[str, int] = {}
        error_records = {}
        for m in result.members:
            if m.status == "error":
                classified = classify_compute_error(m.error)
                code = classified[0] if classified else "calc_error"
                errors[code] = errors.get(code, 0) + 1
                error_records[(m.scenario_variant_id, m.composition_id)] = {
                    "scenario_variant_id": m.scenario_variant_id,
                    "composition_id": m.composition_id,
                    "status": "error",
                    "error": code,
                    "message": str(m.error),
                }
        t = time.perf_counter()
        document = family_document(
            result, "sha256:bench", request_echo, False, error_records
        )
        serialise_s = time.perf_counter() - t

        stats = result.context_stats
        print(f"  {label}")
        print(
            f"    build {build_s:6.2f} s   serialise {serialise_s:5.2f} s   "
            f"ok={result.n_ok} err={result.n_error}" + (f"  {errors}" if errors else "")
        )
        print(
            f"    route(): {stats['route_calls']} calls, {stats['route_hits']} hits, "
            f"{stats['n_leg_variants']} routed;  loader: "
            f"{stats['loader_calls']} calls, "
            f"{stats['loader_hits']} hits"
        )

    print("  document (the wire shape)")
    print(f"    routes                 {len(document['routes'])}")
    print(f"    geometries (pool)      {len(document['geometries'])}")
    print(
        f"    summaries              "
        f"{kb(json_bytes([m['summary'] for m in document['members'] if m['status'] == 'ok']))}"
    )
    print(f"    compact routes         {kb(json_bytes(document['routes']))}")
    print(f"    geometries             {kb(json_bytes(document['geometries']))}")
    print(f"    document, raw          {kb(json_bytes(document))}")
    print(f"    document, gzip -6      {kb(gzip_bytes(document))}")

    # And through the front door, cache included: the second call is the
    # document cache hit a returning client sees.
    print("  build_or_load_family() (the endpoint's path, with the caches)")
    for label in ("miss", "hit"):
        t = time.perf_counter()
        document = build_or_load_family(body)
        print(
            f"    {label:<5}{(time.perf_counter() - t) * 1000:8.0f} ms   "
            f"cache_hit={document['stats']['cache_hit']}"
        )


# =============================================================================
# Main
# =============================================================================


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--stops", nargs="+", default=BERLIN_WIEN)
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--composition", default=DEFAULT_COMPOSITION_ID)
    parser.add_argument("--second-composition", default=SECOND_COMPOSITION)
    parser.add_argument("--workers", type=int, default=FAMILY_WORKERS)
    parser.add_argument(
        "--no-family",
        dest="family",
        action="store_false",
        help="skip section D (the full family build)",
    )
    args = parser.parse_args()

    # The loader's "no row for BY/RU, using defaults" warnings fire on every
    # catalog build and would print 2 × repeat lines here; they are a known
    # seed property, not a measurement.
    logging.getLogger("adapters.data_loader_from_db").setLevel(logging.ERROR)
    dependencies.init()
    loader = dependencies.get_loader()
    scenario_id = loader.resolve_scenario_id(None)
    router = dependencies_router(loader, scenario_id)
    body = {
        "stops": args.stops,
        "composition_id": args.composition,
        "auto_stop_addition": "off",
    }
    print(
        f"stops: {args.stops}   composition: {args.composition}   "
        f"scenario: {scenario_id}   repeat: {args.repeat}\n"
    )

    _, warm = section_calc_path(args, body)
    domain = section_domain(args, scenario_id, loader, router)
    section_outside_domain(args, scenario_id, loader, median_ms(warm))

    plain = domain["plain"]
    family = domain["family"]
    print("\nderived")
    print(
        f"  member − plain run_compute              "
        f"{median_ms(warm) - plain:8.0f} ms  (serialisation + request resolution)"
    )
    print(
        f"  plain − family member                   {plain - family:8.0f} ms  "
        "(catalog loads + leg lookups shared away)"
    )
    print(
        f"  family member − evaluate                "
        f"{family - domain['evaluate']:8.0f} ms  "
        "(trip build + timetable + demand — the per-member floor)"
    )

    if args.family:
        section_family(args, loader)
    return 0


if __name__ == "__main__":
    sys.exit(main())
