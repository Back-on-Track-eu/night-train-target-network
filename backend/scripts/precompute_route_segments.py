"""
precompute_route_segments.py
============================
Batch-route every plausible stop pair once, offline, for ONE routing graph
— into a CSV that loads into route_cache.route_segments (--load here on a
server, or db/dev/seed.py on a dev reseed). The runtime cache grows on its
own from every live-routed miss; this script just front-loads it so the
first user of a pair does not pay the routing call.

Run AFTER the graph is final: a GraphHopper re-import changes /info's
import_date, and the API purges that graph's cached rows on its next
start (RouteSegmentRepository.sync_graph_import) — a batch routed against
the old graph is simply deleted. Recurring cost per graph, not one-off.

Phases (each resumable / independently runnable):
  --measure-only   Pair counts per distance cap, empirical variant count
                   (compositions × the graph's scenarios through the SAME
                   resolve_routing_params()/build_custom_model() the
                   runtime uses), a latency probe → worker-hours table.
  (default)        Snap every stop once per needed gauge profile (sidecar
                   CSV), then route pairs × variants pass-2-only through
                   RailRouter.route_pair_from_snapped() — the identical
                   payload/parse path the runtime fallback uses. Appends
                   to --out as it goes; a rerun skips keys already present,
                   so an interrupted job resumes by rerunning the same
                   command. Per-pair failures go to <out>.failures.csv
                   and never stop the batch.
  --finalize       Completeness check, gzip to <out>.gz, write
                   <out>.meta.json (graph, import_date, variants, counts).
  --load           Load <out>.gz (or <out>) into route_cache for --graph,
                   ON CONFLICT DO NOTHING — safe on top of runtime rows.

Only fullRouting variants are precomputed (the compute default);
simpleRouting pairs fill in from traffic like any other miss. Each pair is
routed on the gauge profile its own two stops resolve to (routing/gauge.py);
a trip whose whole-stop-list gauge differs (dual-gauge border stops pulled
broad by their co-stops) misses on that pair and self-populates at runtime.

Predict-before-run: expected pair/variant/call counts are printed up
front and compared against actuals at the end — a mismatch is a defect
signal even when nothing raised.

Env: host-runnable like scripts/refresh_proposals.py — POSTGRES_* default
to localhost (setdefault, never overriding container-injected values);
the graph URL comes from the same registry the API uses
(OPENRAILROUTING_URL_<KEY>), rewritten onto localhost by
dev_env.resolve_routing_urls() when run from the host — so the 2032 graph
works straight off backend/docker/.env once its instance is enabled.

Usage (typical, on the server, from backend/):
  uv run python scripts/precompute_route_segments.py --graph infra_2026 --measure-only
  uv run python scripts/precompute_route_segments.py --graph infra_2026 --cap-km 800 --workers 8
  uv run python scripts/precompute_route_segments.py --graph infra_2026 --cap-km 800 --finalize
  uv run python scripts/precompute_route_segments.py --graph infra_2026 --load
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import random
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("POSTGRES_DB", "nighttrain")
os.environ.setdefault("POSTGRES_USER", "nighttrain")
os.environ.setdefault("POSTGRES_PASSWORD", "nighttrain")

from dev_env import resolve_routing_urls  # noqa: E402

from adapters.data_loader_from_db import DBDataLoader  # noqa: E402
from adapters.route_segment_repository import RouteSegmentRepository  # noqa: E402
from models.route.routing.gauge import GaugeMismatchError, resolve_trip_gauge  # noqa: E402
from models.route.routing.rail_router import (  # noqa: E402
    DEFAULT_ROUTING_GRAPH_KEY,
    CountryIndex,
    PassageIndex,
    RailRouter,
    StopInput,
    default_base_url,
    resolve_routing_params,
    route_variant_key,
)
from models.route.routing.segment_cache import (  # noqa: E402
    CSV_COLUMNS,
    segment_from_leg,
    segment_to_csv_row,
)
from models.route.trip import StopType  # noqa: E402
from models.utils import haversine_m  # noqa: E402

PROGRESS_EVERY = 500
SUBMIT_CHUNK = 2000  # bounds the futures queue, keeps memory flat


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


def default_out(graph_key: str) -> Path:
    return Path(__file__).resolve().parent / "data" / f"route_segments_{graph_key}.csv"


def build_context(graph_key: str):
    # The same registry the API builds (OPENRAILROUTING_URL_<KEY>),
    # rewritten onto localhost + published port when run from the host.
    urls = resolve_routing_urls()
    urls.setdefault(DEFAULT_ROUTING_GRAPH_KEY, default_base_url())
    if graph_key not in urls:
        sys.exit(
            f"No URL configured for graph '{graph_key}' — set "
            f"OPENRAILROUTING_URL_{graph_key.upper()}. Configured: {sorted(urls)}."
        )
    loader = DBDataLoader()
    router = RailRouter(
        CountryIndex(loader.get_country_geometries()),
        PassageIndex(loader.get_passage_geometries()),
        base_url=urls[graph_key],
        graph_key=graph_key,
    )
    info = router.check_server()
    import_date = info.get("import_date")
    print(f"Graph '{graph_key}' at {router.base_url} — import_date {import_date}")
    return loader, router, import_date


def load_stops(loader) -> dict:
    """stop_id → StopInfrastructure for the current base scenario's
    catalog (lat/lon and gauges_mm are what routing needs)."""
    return dict(sorted(loader.build_all_stops().all().items()))


def generate_pairs(stops: dict, cap_km: float | None) -> list[tuple[str, str]]:
    """All unordered (stop_lo, stop_hi) pairs within the haversine cap.
    Sorted-id order IS the canonical storage orientation."""
    cap_m = cap_km * 1000 if cap_km else None
    items = list(stops.items())
    return [
        (id_a, id_b)
        for (id_a, a), (id_b, b) in combinations(items, 2)
        if cap_m is None or haversine_m(a.lon, a.lat, b.lon, b.lat) <= cap_m
    ]


def enumerate_models(loader, router, graph_key: str, stops: dict) -> dict[str, dict]:
    """Distinct resolved custom models (fullRouting) across every seeded
    composition × every scenario pinned to this graph — model_hash →
    {custom_model, compositions, description}. The gauge profile joins
    the key per PAIR later (route_variant_key), since it depends on the
    stops, not the composition."""
    with loader._conn.cursor() as cur:  # read-only; the loader has no list API
        cur.execute(
            "SELECT scenario_id FROM scenario.scenarios "
            "WHERE routing_graph_key = %s ORDER BY scenario_id",
            (graph_key,),
        )
        scenario_ids = [row[0] for row in cur.fetchall()]
        if not scenario_ids:
            print(
                f"  WARNING: no scenario pins graph '{graph_key}' yet — enumerating "
                "variants over ALL scenarios' track pins instead."
            )
            cur.execute("SELECT scenario_id FROM scenario.scenarios ORDER BY 1")
            scenario_ids = [row[0] for row in cur.fetchall()]

    compositions = loader.build_all_compositions().all()
    any_stop = next(iter(stops.values()))
    models: dict[str, dict] = {}
    for scenario_id in scenario_ids:
        tracks = loader.build_all_tracks(scenario_id)
        for comp_id, comp in sorted(compositions.items()):
            # The runtime's own derivation; stops only feed the gauge,
            # which is irrelevant for the model — any catalog stop does.
            max_speed, avoid_hsr, _ = resolve_routing_params(
                comp, tracks, [StopInput(any_stop, StopType.BOTH)] * 2
            )
            model = router.build_custom_model(max_speed, avoid_hsr)
            key = route_variant_key("", model)  # profile-less: model identity only
            entry = models.setdefault(
                key,
                {
                    "custom_model": model,
                    "compositions": set(),
                    "description": (
                        f"{max_speed} km/h cap, HSR avoided in "
                        f"{sum(avoid_hsr.values())}/{len(avoid_hsr)} countries"
                    ),
                },
            )
            entry["compositions"].add(comp_id)
    return models


def build_tasks(
    router, stops: dict, pairs: list[tuple[str, str]], models: dict, compositions: dict
) -> tuple[list[tuple[str, str, str, str]], dict[str, dict | None]]:
    """(stop_lo, stop_hi, profile, variant_key) for every pair × model,
    plus variant_key → custom_model. The profile comes from the pair's
    own two stops through resolve_trip_gauge() — the same rule
    resolve_routing_params() applies at runtime, so keys match. Pairs
    with no common gauge are skipped; the runtime rejects them before
    any HTTP too."""
    tasks: list[tuple[str, str, str, str]] = []
    models_by_vkey: dict[str, dict | None] = {}
    n_gauge_skipped = 0
    any_comp = next(iter(compositions.values()))
    for lo, hi in pairs:
        try:
            gauge_mm = resolve_trip_gauge((stops[lo], stops[hi]), any_comp)
        except GaugeMismatchError:
            n_gauge_skipped += 1
            continue
        profile = router.profile_for_gauge(gauge_mm)
        for entry in models.values():
            vkey = route_variant_key(profile, entry["custom_model"])
            models_by_vkey[vkey] = entry["custom_model"]
            tasks.append((lo, hi, profile, vkey))
    if n_gauge_skipped:
        print(f"  {n_gauge_skipped} pair(s) skipped: no common gauge.")
    return tasks, models_by_vkey


# ---------------------------------------------------------------------------
# Snapping (one call per stop per profile, sidecar-cached)
# ---------------------------------------------------------------------------


def snap_needed(
    router, stops: dict, needed: set[tuple[str, str]], sidecar: Path
) -> dict[tuple[str, str], list[float]]:
    snapped: dict[tuple[str, str], list[float]] = {}
    if sidecar.is_file():
        with open(sidecar, newline="", encoding="utf-8") as fh:
            for row in csv.reader(fh):
                snapped[(row[0], row[1])] = [float(row[2]), float(row[3])]
        print(f"  snapping: {len(snapped)} entries loaded from {sidecar.name}.")

    todo = sorted(k for k in needed if k not in snapped)
    if not todo:
        return snapped

    sidecar.parent.mkdir(parents=True, exist_ok=True)
    failures = 0
    with open(sidecar, "a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        for i, (sid, profile) in enumerate(todo, 1):
            stop = stops[sid]
            # Helper = nearest other stop: a short, routable probe
            # (snap_point needs any second reachable point).
            helper = min(
                (o for o in stops.values() if o.stop_id != sid),
                key=lambda o: haversine_m(stop.lon, stop.lat, o.lon, o.lat),
            )
            try:
                coords = router.snap_point(
                    stop.lon, stop.lat, [helper.lon, helper.lat], profile
                )
            except Exception as e:
                failures += 1
                print(f"  snap failed for {sid} on {profile}: {type(e).__name__}: {e}")
                continue
            snapped[(sid, profile)] = coords
            writer.writerow([sid, profile, coords[0], coords[1]])
            if i % 100 == 0:
                fh.flush()
                print(f"  snapping: {i}/{len(todo)}")
    print(f"  snapping done: {len(snapped)} snapped, {failures} failed.")
    return snapped


# ---------------------------------------------------------------------------
# Batch routing
# ---------------------------------------------------------------------------


def existing_keys(out: Path) -> set[tuple[str, str, str]]:
    if not out.is_file():
        return set()
    with open(out, newline="", encoding="utf-8") as fh:
        return {
            (r["stop_lo"], r["stop_hi"], r["variant_key"]) for r in csv.DictReader(fh)
        }


def run_batch(router, tasks, models_by_vkey, snapped, out: Path, workers: int) -> None:
    done = existing_keys(out)
    todo = [
        t
        for t in tasks
        if (t[0], t[1], t[3]) not in done
        and (t[0], t[2]) in snapped
        and (t[1], t[2]) in snapped
    ]
    n_unsnappable = sum(
        1 for t in tasks if (t[0], t[2]) not in snapped or (t[1], t[2]) not in snapped
    )
    print(
        f"\nPredict-before-run: {len(tasks)} segments total; {len(done)} already "
        f"done, {n_unsnappable} unsnappable, {len(todo)} to route now."
    )
    if not todo:
        print("Nothing to do.")
        return

    out.parent.mkdir(parents=True, exist_ok=True)
    write_header = not out.is_file()
    failures_path = out.with_suffix(".failures.csv")
    n_ok = n_fail = 0
    started = time.monotonic()

    def route_one(task):
        lo, hi, profile, vkey = task
        leg = router.route_pair_from_snapped(
            [snapped[(lo, profile)], snapped[(hi, profile)]],
            models_by_vkey[vkey],
            profile,
        )
        return segment_to_csv_row(lo, hi, vkey, segment_from_leg(leg, reverse=False))

    with (
        open(out, "a", newline="", encoding="utf-8") as fh,
        open(failures_path, "a", newline="", encoding="utf-8") as ffh,
    ):
        writer = csv.writer(fh)
        fail_writer = csv.writer(ffh)
        if write_header:
            writer.writerow(CSV_COLUMNS)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for chunk_start in range(0, len(todo), SUBMIT_CHUNK):
                chunk = todo[chunk_start : chunk_start + SUBMIT_CHUNK]
                futures = {pool.submit(route_one, t): t for t in chunk}
                for future in as_completed(futures):
                    lo, hi, profile, vkey = futures[future]
                    try:
                        writer.writerow(future.result())
                        n_ok += 1
                    except Exception as e:
                        fail_writer.writerow([lo, hi, vkey, type(e).__name__, str(e)])
                        n_fail += 1
                    if (n_ok + n_fail) % PROGRESS_EVERY == 0:
                        fh.flush()
                        rate = (n_ok + n_fail) / (time.monotonic() - started)
                        eta_h = (len(todo) - n_ok - n_fail) / rate / 3600
                        print(
                            f"  {n_ok + n_fail}/{len(todo)} "
                            f"({rate:.1f}/s, ETA {eta_h:.1f} h, {n_fail} failed)"
                        )

    verdict = "MATCH" if n_ok + n_fail == len(todo) else "MISMATCH, investigate"
    print(
        f"\nDone: {n_ok} routed, {n_fail} failed (predicted {len(todo)} — {verdict}). "
        f"Failures: {failures_path.name}."
    )


# ---------------------------------------------------------------------------
# Measure / finalize / load
# ---------------------------------------------------------------------------


def measure(router, stops, models, probe_pairs, workers) -> None:
    print(f"\nStops in catalog: {len(stops)}")
    print("\nPair counts by haversine cap (replaces the area guess):")
    for cap in (300, 500, 800, None):
        n = len(generate_pairs(stops, cap))
        label = f"{cap} km" if cap else "uncapped"
        print(f"  {label:>9}: {n:>9,} pairs → ~{n * len(models):>10,} segments")

    print(
        f"\nCustom-model variants (empirical, summary expected 2 per graph): {len(models)}"
    )
    for key, m in sorted(models.items()):
        print(f"  {key}: {m['description']} — {sorted(m['compositions'])}")
    print(
        "  (× gauge profiles per pair: standard-gauge pairs add nothing, broad-gauge pairs one each)"
    )

    print(f"\nLatency probe ({probe_pairs} random pairs, pass-2-only)...")
    sample = random.sample(list(stops.values()), min(len(stops), probe_pairs * 2))
    model = next(iter(models.values()))["custom_model"]
    timings = []
    for a, b in zip(sample[0::2], sample[1::2]):
        t0 = time.monotonic()
        try:
            router.route_pair_from_snapped(
                [[a.lon, a.lat], [b.lon, b.lat]], model, router.profile
            )
            timings.append(time.monotonic() - t0)
        except Exception:
            pass
    if timings:
        avg = sum(timings) / len(timings)
        print(f"  {len(timings)} ok, avg {avg * 1000:.0f} ms/call (single-threaded)")
        print(f"\nWorker-hours per cap at that rate, {workers} workers:")
        for cap in (300, 500, 800, None):
            n = len(generate_pairs(stops, cap)) * len(models)
            label = f"{cap} km" if cap else "uncapped"
            print(f"  {label:>9}: ~{n * avg / workers / 3600:.1f} h")
        print(
            "  NOTE: confirm with a small --limit batch at the real --workers "
            "before trusting the extrapolation — concurrency scaling on one "
            "container is the open measurement."
        )


def finalize(out: Path, models, graph_key, import_date, cap_km, n_stops) -> None:
    if not out.is_file():
        sys.exit(f"{out} does not exist — run the batch first.")
    with open(out, newline="", encoding="utf-8") as fh:
        n_rows = sum(1 for _ in csv.DictReader(fh))

    gz_path = out.with_suffix(out.suffix + ".gz")
    with open(out, "rb") as src, gzip.open(gz_path, "wb") as dst:
        shutil.copyfileobj(src, dst)

    meta = {
        "graph_key": graph_key,
        "import_date": import_date,
        "distance_cap_km": cap_km,
        "n_stops": n_stops,
        "n_segments": n_rows,
        "models": {k: m["description"] for k, m in sorted(models.items())},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    meta_path = out.with_suffix(".meta.json")
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(
        f"Finalized: {gz_path.name} ({gz_path.stat().st_size / 1e6:.1f} MB, "
        f"{n_rows} segments) + {meta_path.name}.\n"
        f"Server: --load. Dev: copy both into backend/db/dev/data/ for the next reseed."
    )


def load(out: Path, graph_key: str, import_date: str | None) -> None:
    path = out.with_suffix(out.suffix + ".gz")
    if not path.is_file():
        path = out
    if not path.is_file():
        sys.exit(f"Neither {path.name} nor its .gz exists — run --finalize first.")
    repo = RouteSegmentRepository()
    try:
        # Same reconciliation the API does at startup: if the served graph
        # moved on since the file was routed, the file is stale too.
        if repo.sync_graph_import(graph_key, import_date):
            print("  graph import changed — existing rows purged before load.")
        before = repo.count(graph_key)
        inserted = repo.load_csv(path, graph_key)
        print(
            f"Loaded {inserted} new segment(s) into route_cache for '{graph_key}' "
            f"({before} → {repo.count(graph_key)} rows). Restart the API to warm up."
        )
    finally:
        repo.close()


# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Precompute route segments for one graph."
    )
    parser.add_argument("--graph", default=DEFAULT_ROUTING_GRAPH_KEY)
    parser.add_argument("--cap-km", type=float, default=800)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--limit", type=int, help="debug: route only N pairs")
    parser.add_argument("--probe", type=int, default=20)
    parser.add_argument("--measure-only", action="store_true")
    parser.add_argument("--finalize", action="store_true")
    parser.add_argument("--load", action="store_true")
    args = parser.parse_args()
    out = args.out or default_out(args.graph)

    loader, router, import_date = build_context(args.graph)
    stops = load_stops(loader)
    models = enumerate_models(loader, router, args.graph, stops)

    if args.measure_only:
        measure(router, stops, models, args.probe, args.workers)
        return
    if args.finalize:
        finalize(out, models, args.graph, import_date, args.cap_km, len(stops))
        return
    if args.load:
        load(out, args.graph, import_date)
        return

    pairs = generate_pairs(stops, args.cap_km)
    if args.limit:
        pairs = pairs[: args.limit]
    compositions = loader.build_all_compositions().all()
    tasks, models_by_vkey = build_tasks(router, stops, pairs, models, compositions)
    needed = {(lo, p) for lo, _, p, _ in tasks} | {(hi, p) for _, hi, p, _ in tasks}
    snapped = snap_needed(router, stops, needed, out.with_suffix(".snapped.csv"))
    run_batch(router, tasks, models_by_vkey, snapped, out, args.workers)


if __name__ == "__main__":
    main()
