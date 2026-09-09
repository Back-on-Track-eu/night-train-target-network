"""
bench_member.py
===============
The numbers behind the proposal-family design (docs/2026-09-09_wp18_
proposal_family_plan.md): what one family MEMBER costs once its legs are
cached, attributed to the layers the design separates, and what a whole
family costs and weighs when route legs and catalogs are shared across
members. Kept as the family's regression bench — rerun after every phase.

    A  the /calc path            compute_proposal(): the number a user sees today
    B  run_compute() domain      plain, catalogs memoised, legs memoised, both —
                                 "both" is the family's per-member cost
    C  outside the domain        per-catalog load, per-step serialisation —
                                 what the plain member spends that the family
                                 document never pays
    D  family                    every (scenario, composition) on one shared
                                 context, serial and threaded, plus the §2.5
                                 document size estimate

MemoLoader / MemoRouter below are throwaway stand-ins for
models/family/context.py (Phase B2): the same memo boundary
(loader catalog builders; RailRouter.route(), copies handed out) without the
package. Section D's compactor is likewise an estimate of
route_compact_to_dict() and is replaced by it in B2.

Run inside the api container against the live stack:

    docker exec night-train-api python -m scripts.bench_member
    docker exec night-train-api python -m scripts.bench_member --repeat 10 --workers 4
    docker exec night-train-api python -m scripts.bench_member --no-family
    docker exec night-train-api python -m scripts.bench_member --stops osm:n3856100103 osm:n25397500 osm:w423692233
"""

from __future__ import annotations

import argparse
import dataclasses
import gzip
import json
import logging
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import dev_env  # noqa: E402

dev_env.resolve_env()

from adapters.proposal.id_prefix import rewrite_id_prefix  # noqa: E402
from adapters.proposal.projection import route_fingerprint  # noqa: E402
from api.config import CALC_MATRIX_WORKERS  # noqa: E402
from api.helpers import dependencies  # noqa: E402
from api.helpers.evaluation_serialize import (  # noqa: E402
    input_to_dict,
    models_to_dict,
    views_to_dict,
)
from api.helpers.proposal_compute import (  # noqa: E402
    canonical_sha256,
    classify_compute_error,
    compute_proposal,
)
from api.helpers.proposal_matrix import resolve_matrix_axes  # noqa: E402
from api.helpers.route_serialize import route_to_dict  # noqa: E402
from models.evaluation.summary import build_summary_row, ordered_stops  # noqa: E402
from models.pipeline import evaluate_and_build_views, run_compute  # noqa: E402
from models.route.model import (  # noqa: E402
    DEFAULT_COMPOSITION_ID,
    DEFAULT_ROUTING_MODE,
    DEFAULT_SCHEDULE_MODE,
    DEFAULT_TIMETABLE_MODE,
    NEUTRAL_PROPOSAL_ID,
    NEUTRAL_PROPOSAL_VERSION,
    ROUTE_BUILDER_VERSION,
)
from models.evaluation.model import CALC_VERSION  # noqa: E402

BERLIN_WIEN = ["osm:n3856100103", "osm:w423692233"]
SECOND_COMPOSITION = "REF-POD-14"
_NEUTRAL_PREFIX = f"P{NEUTRAL_PROPOSAL_ID}_V{NEUTRAL_PROPOSAL_VERSION}_"

# Response parts route_compact_to_dict() (§2.5) leaves out: catalog data,
# evaluation input, provenance, and the geometries that move to the pool.
_COMPACT_DROPS_ROUTE = ("track_infrastructure", "geometries")
_COMPACT_DROPS_PAIR = ("composition", "od_pairs")
_COMPACT_DROPS_SEGMENT = ("from_stop", "to_stop")


# =============================================================================
# Throwaway memo layer — the boundary models/family/context.py will own
# =============================================================================


class MemoLoader:
    """Build-scoped memo over DBDataLoader's per-scenario catalog builders
    and the two scenario-row resolutions compute_proposal() makes. One
    instance per family build: catalogs are read-only collections, so
    every member can share one object per (builder, scenario).
    Everything else delegates to the wrapped loader untouched."""

    _MEMOISED = frozenset(
        {
            "build_all_compositions",
            "build_all_tracks",
            "build_all_stops",
            "build_all_passages",
            "resolve_scenario_id",
            "resolve_routing_graph_key",
        }
    )

    def __init__(self, loader) -> None:
        self._loader = loader
        self._memo: dict = {}
        self._lock = threading.Lock()
        self.calls = 0
        self.hits = 0

    def __getattr__(self, name):
        target = getattr(self._loader, name)
        if name not in self._MEMOISED:
            return target

        def memoised(*args, **kwargs):
            key = (name, args, tuple(sorted(kwargs.items())))
            with self._lock:
                self.calls += 1
                if key in self._memo:
                    self.hits += 1
                    return self._memo[key]
            value = target(*args, **kwargs)
            with self._lock:
                return self._memo.setdefault(key, value)

        return memoised


class MemoRouter:
    """Build-scoped memo over RailRouter.route() — the L1 boundary: raw
    legs are a pure function of (stops, speed cap, HSR vector, gauge,
    mode) on one graph. route_trip() and calc_energy_consumption() fill
    buffer/dynamics/energy IN PLACE on the legs they get, so the memo
    hands out copies (dataclasses.replace — a shallow copy suffices, only
    scalar fields are mutated downstream)."""

    def __init__(self, router) -> None:
        self._router = router
        self._memo: dict = {}
        self._lock = threading.Lock()
        self.calls = 0
        self.hits = 0

    def __getattr__(self, name):
        return getattr(self._router, name)

    def route(self, stops, max_speed_kmh, avoid_hsr, gauge_mm, routing_mode):
        key = (
            tuple(s.stop.stop_id for s in stops),
            max_speed_kmh,
            None if avoid_hsr is None else tuple(sorted(avoid_hsr.items())),
            gauge_mm,
            routing_mode,
        )
        with self._lock:
            self.calls += 1
            legs = self._memo.get(key)
            if legs is not None:
                self.hits += 1
        if legs is None:
            legs = self._router.route(
                stops, max_speed_kmh, avoid_hsr, gauge_mm, routing_mode
            )
            with self._lock:
                legs = self._memo.setdefault(key, legs)
        return [dataclasses.replace(leg) for leg in legs]


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


def compact_route(route_dict: dict, pool: dict[str, list]) -> dict:
    """§2.5 estimate: stops once per trip, segments by stop index,
    geometries content-addressed into the shared pool, catalog/demand/
    provenance blocks dropped. Replaced by route_compact_to_dict() in B2."""
    geometries = {g["id"]: g["coords"] for g in route_dict["geometries"]}

    def trip(t: dict) -> dict:
        segments = []
        for i, seg in enumerate(t["segments"]):
            coords = geometries[seg["geometry_id"]]
            gid = "g:" + canonical_sha256(coords)[7:23]
            pool.setdefault(gid, coords)
            compact = {k: v for k, v in seg.items() if k not in _COMPACT_DROPS_SEGMENT}
            compact.update({"from": i, "to": i + 1, "geometry_id": gid})
            segments.append(compact)
        return {
            "trip_id": t["trip_id"],
            "direction": t["direction"],
            "general_parameters": t["general_parameters"],
            "stops": ordered_stops(t),
            "segments": segments,
        }

    out = {k: v for k, v in route_dict.items() if k not in _COMPACT_DROPS_ROUTE}
    out["trip_pairs"] = [
        {
            **{k: v for k, v in pair.items() if k not in _COMPACT_DROPS_PAIR},
            "outbound": trip(pair["outbound"]),
            "return_trip": trip(pair["return_trip"]),
        }
        for pair in route_dict["trip_pairs"]
    ]
    return out


# =============================================================================
# Sections
# =============================================================================


def section_calc_path(args, body: dict) -> tuple[list[float], list[float]]:
    print("A. the /calc path — compute_proposal(), request cache bypassed")
    cold = timed(lambda: compute_proposal(body, use_cache=False), 1)
    row("member, first time (legs may route live)", cold)
    warm = timed(lambda: compute_proposal(body, use_cache=False), args.repeat)
    row("member, legs cached", warm)
    other = {**body, "composition_id": args.second_composition}
    row(
        "member, other composition, legs cached",
        timed(lambda: compute_proposal(other, use_cache=False), args.repeat),
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
    and each serialisation step compute_proposal() performs, none of which
    the family document pays per member."""
    print("\nC. outside the domain — what the plain /calc member also spends")
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

    print("  serialisation per member (compute_proposal's payload)")
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
    evaluation = {
        "models": models_to_dict(),
        "input": input_to_dict(
            route_dict, prov.tracks, prov.stop_infra, prov.compositions, False
        ),
        "views": views,
    }
    payload = {"route": route_dict, "evaluation": evaluation}
    steps = {
        "route_to_dict": lambda: route_to_dict(result.route, scenario_id, prov.tracks),
        "route_fingerprint": lambda: route_fingerprint(route_dict),
        "input_to_dict (full catalogs → input.parameters)": lambda: input_to_dict(
            route_dict, prov.tracks, prov.stop_infra, prov.compositions, False
        ),
        "models_to_dict": models_to_dict,
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

    print("  wire weight of the /calc payload parts")
    print(f"    route (full)                   {kb(json_bytes(route_dict))}")
    print(f"    evaluation.input.parameters    {kb(json_bytes(evaluation['input']))}")
    print(f"    evaluation.models              {kb(json_bytes(evaluation['models']))}")
    print(f"    evaluation.views               {kb(json_bytes(views))}")
    print(
        f"\n  sum check: catalog loads {total_loads:.0f} ms + serialisation "
        f"{total_ser:.0f} ms = {total_loads + total_ser:.0f} ms of the "
        f"{warm_ms:.0f} ms /calc member"
    )


def dependencies_router(loader, scenario_id: int):
    return dependencies.get_rail_router(loader.resolve_routing_graph_key(scenario_id))


class FamilyRun:
    """One family build on shared memos: a MemoLoader per scenario, a
    MemoRouter per routing graph, members = run_compute() per
    (scenario, composition), errors classified like the API would."""

    def __init__(self, args, loader, axes) -> None:
        self.args = args
        self.axes = axes
        self.loaders = {s.scenario_id: MemoLoader(loader) for s in axes.scenarios}
        self.routers: dict[str, MemoRouter] = {}
        self._lock = threading.Lock()
        self.members: dict[tuple[int, str], dict] = {}
        self.domain_s: list[float] = []

    def router_for(self, scenario) -> MemoRouter:
        key = scenario.routing_graph_key
        with self._lock:
            if key not in self.routers:
                self.routers[key] = MemoRouter(dependencies.get_rail_router(key))
            return self.routers[key]

    def build(self, scenario, composition) -> None:
        sid = scenario.scenario_id
        cid = composition.comp_id
        t = time.perf_counter()
        try:
            result = member(
                self.args, sid, self.loaders[sid], self.router_for(scenario), cid
            )
        except Exception as exc:  # noqa: BLE001 — every failure becomes an error member
            classified = classify_compute_error(exc)
            code = classified[0] if classified else "calc_error"
            with self._lock:
                self.members[(sid, cid)] = {"status": "error", "error": code}
            return
        elapsed = time.perf_counter() - t
        prov = result.provenance
        route_dict = route_to_dict(result.route, sid, prov.tracks)
        views = views_to_dict(result.views, result.route)
        with self._lock:
            self.members[(sid, cid)] = {
                "status": "ok",
                "route_dict": route_dict,
                "fingerprint": route_fingerprint(route_dict),
                "summary": build_summary_row(route_dict, {"views": views}),
            }
            self.domain_s.append(elapsed)

    def run(self, workers: int) -> float:
        cells = [(s, c) for s in self.axes.scenarios for c in self.axes.compositions]
        t = time.perf_counter()
        if workers <= 1:
            for s, c in cells:
                self.build(s, c)
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                list(pool.map(lambda sc: self.build(*sc), cells))
        return time.perf_counter() - t

    def report(self, label: str, wall_s: float) -> None:
        ok = sum(1 for m in self.members.values() if m["status"] == "ok")
        errors: dict[str, int] = {}
        for m in self.members.values():
            if m["status"] == "error":
                errors[m["error"]] = errors.get(m["error"], 0) + 1
        per_member = median_ms(self.domain_s) if self.domain_s else 0.0
        print(
            f"  {label:<28}{wall_s:6.2f} s   ok={ok} err={sum(errors.values())}"
            f"   member median {per_member:.0f} ms"
        )
        if errors:
            print(f"    errors: {errors}")
        route_calls = sum(r.calls for r in self.routers.values())
        route_hits = sum(r.hits for r in self.routers.values())
        loader_calls = sum(ld.calls for ld in self.loaders.values())
        loader_hits = sum(ld.hits for ld in self.loaders.values())
        print(
            f"    route(): {route_calls} calls, {route_hits} memo hits, "
            f"{route_calls - route_hits} distinct (stops, variant) routed; "
            f"loader: {loader_calls} calls, {loader_hits} memo hits"
        )

    def document_estimate(self) -> None:
        """Assemble the §2.5 document from the ok members and weigh its
        parts — the number that decides whether the family goes over the
        wire as one JSON document."""
        pool: dict[str, list] = {}
        routes: dict[str, dict] = {}
        members = []
        for (sid, cid), m in self.members.items():
            if m["status"] != "ok":
                members.append(
                    {
                        "scenario_variant_id": sid,
                        "composition_id": cid,
                        "status": "error",
                        "error": m["error"],
                    }
                )
                continue
            ref = f"r:{sid}:{cid}"
            routes[ref] = compact_route(m["route_dict"], pool)
            members.append(
                {
                    "scenario_variant_id": sid,
                    "composition_id": cid,
                    "status": "ok",
                    "route_ref": ref,
                    "route_fingerprint": m["fingerprint"],
                    "summary": m["summary"],
                }
            )
        document = {
            "family_key": "sha256:" + "0" * 64,
            "route_builder_version": ROUTE_BUILDER_VERSION,
            "calc_version": CALC_VERSION,
            "request": {"stops": self.args.stops},
            # Phase A's variant axis is scenario × measure set; with the
            # single "none" set the variant ids coincide with scenario ids.
            "axes": {
                "scenario_variants": [
                    {
                        "scenario_variant_id": s.scenario_id,
                        "scenario_id": s.scenario_id,
                        "measure_set_id": 1,
                        "scenario_key": s.scenario_key,
                        "scenario_name": s.scenario_name,
                        "is_current_base": s.is_current_base,
                        "routing_graph_key": s.routing_graph_key,
                    }
                    for s in self.axes.scenarios
                ],
                "compositions": [c.comp_id for c in self.axes.compositions],
            },
            "geometries": pool,
            "routes": routes,
            "members": members,
        }
        n_ok = sum(1 for m in members if m["status"] == "ok")
        summaries = [m["summary"] for m in members if m["status"] == "ok"]
        print("  document estimate (§2.5)")
        print(f"    members                {n_ok:4d} ok of {len(members)}")
        print(f"    summaries              {kb(json_bytes(summaries))}")
        print(f"    compact routes         {kb(json_bytes(routes))}  ({len(routes)})")
        print(
            f"    geometries (pool)      {kb(json_bytes(pool))}  ({len(pool)} distinct)"
        )
        print(f"    document, raw          {kb(json_bytes(document))}")
        print(f"    document, gzip -6      {kb(gzip_bytes(document))}")
        if n_ok:
            print(
                f"    per ok member: summary {json_bytes(summaries) / n_ok:.0f} B, "
                f"compact route {json_bytes(routes) / n_ok:.0f} B"
            )


def section_family(args, loader) -> None:
    axes = resolve_matrix_axes({}, loader)
    print(
        f"\nD. family — {len(axes.scenarios)} scenarios × "
        f"{len(axes.compositions)} compositions = {axes.n_cells} members, legs cached"
    )
    serial = FamilyRun(args, loader, axes)
    serial.report("serial, fresh memos", serial.run(1))
    threaded = FamilyRun(args, loader, axes)
    threaded.report(f"{args.workers} workers, fresh memos", threaded.run(args.workers))
    threaded.document_estimate()


# =============================================================================
# Main
# =============================================================================


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--stops", nargs="+", default=BERLIN_WIEN)
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--composition", default=DEFAULT_COMPOSITION_ID)
    parser.add_argument("--second-composition", default=SECOND_COMPOSITION)
    parser.add_argument("--workers", type=int, default=CALC_MATRIX_WORKERS)
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
        f"  /calc member − plain run_compute        "
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
