"""
precompute_route_segments.py
============================
Batch-route every plausible stop pair once, offline, for ONE routing graph
— into a CSV that loads into route_cache.route_segments. Three ways in:
--load where the database is reachable, --export-upload + pgAdmin where it
is not (the overnight-on-a-laptop case), or db/dev/seed.py on a dev
reseed. The runtime cache grows on its own from every live-routed miss;
this script just front-loads it so the first user of a pair does not pay
the routing call.

Run AFTER the graph is final: a GraphHopper re-import changes /info's
import_date, and the API purges that graph's cached rows on its next
start (RouteSegmentRepository.sync_graph_import) — a batch routed against
the old graph is simply deleted. Recurring cost per graph, not one-off.
When the routing graph that produced the file and the one the server
serves differ, the generated merge SQL refuses the load rather than
seeding rows for the wrong network.

Phases (each resumable / independently runnable):
  --measure-only   Pair counts per distance cap, empirical variant count
                   (compositions × the graph's scenarios through the SAME
                   resolve_routing_params()/build_custom_model() the
                   runtime uses), a latency probe → worker-hours table.
  (default)        Snap every stop once per needed gauge profile (sidecar
                   CSV), then route pairs × variants pass-2-only through
                   RailRouter.route_pair_from_snapped() — the identical
                   payload/parse path the runtime fallback uses. Appends
                   to --out as it goes.
  --finalize       Completeness check, gzip to <out>.gz, write
                   <out>.meta.json (graph, import_date, variants, counts).
  --export-upload  pgAdmin kit next to --out: CSV part file(s) plus the
                   staging DDL and the merge SQL that loads them into
                   route_cache.route_segments on a remote server.
  --load           Load <out>.gz (or <out>) into route_cache for --graph,
                   ON CONFLICT DO NOTHING — safe on top of runtime rows.

Surviving a long run
--------------------
Resume      A rerun of the same command skips every (stop_lo, stop_hi,
            variant_key) already in --out, and reuses the snapped
            coordinates in <out>.snapped.csv. A run killed mid-write
            leaves a partial last line; both files are truncated back to
            their last complete row on the next start, so no repair by
            hand is ever needed. --resume-from takes further CSVs (an
            earlier run's .csv/.csv.gz, or an export of the server's
            table) whose keys are treated as done and are NOT rewritten
            into --out — what the server already has stays off the
            upload.
Failures    A per-pair routing error never stops the batch. Failures are
            classified transient (timeout, HTTP 5xx, connection dropped)
            or permanent (no route, point not found) and retried for
            --retry-rounds rounds after the main pass; --retry-all
            includes the permanent ones. What is still missing at the end
            is written fresh to <out>.failures.csv with the attempt count
            and the last message; --retry-failures-only reroutes exactly
            that file in a later run.
Order       Pairs are routed shortest straight-line distance first, so a
            run that stops early leaves a complete band from 0 km up to a
            reported edge, and a rerun with a wider --cap-km continues
            outward from there.
Progress    Percentage, throughput, elapsed, ETA and the wall-clock
            finish time, refreshed in place on a terminal and as one
            timestamped line every five minutes when redirected to a log.
            --stop-after-h ends a run cleanly after N hours (resume the
            next night).

Only fullRouting variants are precomputed (the compute default);
simpleRouting pairs fill in from traffic like any other miss. Each pair is
routed on the gauge profile its own two stops resolve to (routing/gauge.py);
a trip whose whole-stop-list gauge differs (dual-gauge border stops pulled
broad by their co-stops) misses on that pair and self-populates at runtime.

Predict-before-run: expected pair/variant/call counts are printed up
front and compared against actuals at the end — a mismatch is a defect
signal even when nothing raised.

Env: host-runnable as well as container-runnable. dev_env.resolve_env()
resolves the POSTGRES_* connection from backend/docker/.env with the dev
defaults behind it, rewriting the compose service name onto localhost off
container; the graph URL comes from the same registry the API uses
(OPENRAILROUTING_URL_<KEY>), rewritten the same way — so the 2032 graph
works straight off backend/docker/.env once its instance is enabled.
Nothing here overrides a value a container already injected.

Usage (typical, on the server, from backend/):
  uv run python scripts/precompute_route_segments.py --graph infra_2026 --measure-only
  uv run python scripts/precompute_route_segments.py --graph infra_2026 --cap-km 800 --workers 8
  uv run python scripts/precompute_route_segments.py --graph infra_2026 --cap-km 800 --finalize
  uv run python scripts/precompute_route_segments.py --graph infra_2026 --load

Usage (overnight on a laptop, upload by hand afterwards — full runbook in
docs/2026-09-21_route_cache_precompute_laptop_runbook.md):
  uv run python scripts/precompute_route_segments.py --graph infra_2026 --cap-km 800 --workers 4 --stop-after-h 10
  uv run python scripts/precompute_route_segments.py --graph infra_2026 --cap-km 800 --finalize
  uv run python scripts/precompute_route_segments.py --graph infra_2026 --export-upload --split-mb 250
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import random
import sys
import time
from collections import deque
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from itertools import combinations, islice
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

from dev_env import resolve_env, resolve_routing_urls  # noqa: E402

# dev_env is the single home for dev-side connection defaults: it reads
# backend/docker/.env, fills in only what is unset, and rewrites a compose
# service name (POSTGRES_HOST=postgres) onto localhost when we are not in
# a container. A value the container injected always wins, so this is the
# same call whether the batch runs through the migrate service or from a
# laptop. Called before the adapter imports so every consumer in the
# process sees one connection.
resolve_env()

from adapters.data_loader_from_db import DBDataLoader  # noqa: E402
from adapters.route_segment_repository import RouteSegmentRepository  # noqa: E402
from db.schema import ROUTE_CACHE_TABLES  # noqa: E402
from models.route.model import SUPPORTED_GAUGES_MM  # noqa: E402
from models.route.routing.gauge import (  # noqa: E402
    GaugeMismatchError,
    resolve_trip_gauge,
    stop_supports_gauge,
)
from models.route.routing.rail_router import (  # noqa: E402
    DEFAULT_ROUTING_GRAPH_KEY,
    CountryIndex,
    PassageIndex,
    RailRouter,
    RailRoutingError,
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

SUBMIT_CHUNK = 2000  # bounds the futures queue, keeps memory flat
FLUSH_EVERY = 500  # rows between fsync-able flushes of --out
PROGRESS_TTY_INTERVAL_S = 1.0
PROGRESS_LOG_INTERVAL_S = 300.0  # redirected output: one line every 5 min
RATE_WINDOW_S = 300.0  # ETA from the last five minutes, not the run average
BAR_WIDTH = 24
SNAP_HELPER_CANDIDATES = 8  # second points tried per stop before giving up
MB = 1024 * 1024
COPY_CHUNK = 16 * MB
# zlib's own default. gzip.open() defaults to 9, which is 2-3x slower on
# this data for a file barely smaller.
GZIP_LEVEL = 6
FAILURE_COLUMNS = [
    "stop_lo",
    "stop_hi",
    "profile",
    "variant_key",
    "attempts",
    "transient",
    "error_type",
    "error_message",
    "last_attempt_utc",
]

# (stop_lo, stop_hi, profile, variant_key) — the unit of work.
Task = tuple[str, str, str, str]
# (stop_lo, stop_hi, variant_key) — how a routed row is identified.
SegmentKey = tuple[str, str, str]


def _raise_csv_field_limit() -> None:
    """Geometry lines routinely exceed the csv module's 128 kB field cap,
    which would make resume and failure reading raise on long routes."""
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:  # platforms where the cap is a C long
            limit //= 2


_raise_csv_field_limit()


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


def generate_pairs(stops: dict, cap_km: float | None) -> dict[tuple[str, str], float]:
    """(stop_lo, stop_hi) → straight-line km for every unordered pair within
    the haversine cap, shortest first. Sorted-id order within the key IS the
    canonical storage orientation; the distance order is the work order, so
    a run that stops early leaves a complete band from 0 km up to where it
    stopped rather than a scatter across the whole cap."""
    cap_m = cap_km * 1000 if cap_km else None
    pairs = {}
    for (id_a, a), (id_b, b) in combinations(stops.items(), 2):
        dist_m = haversine_m(a.lon, a.lat, b.lon, b.lat)
        if cap_m is None or dist_m <= cap_m:
            pairs[(id_a, id_b)] = dist_m / 1000
    return dict(sorted(pairs.items(), key=lambda item: item[1]))


def enumerate_models(loader, router, graph_key: str, stops: dict) -> dict[str, dict]:
    """Distinct resolved custom models (fullRouting) across every seeded
    composition × every scenario pinned to this graph — model_hash →
    {custom_model, compositions, description}. The gauge profile joins
    the key per PAIR later (route_variant_key), since it depends on the
    stops, not the composition."""
    scenarios = loader.list_all_scenarios()
    scenario_ids = sorted(
        s.scenario_id for s in scenarios if s.routing_graph_key == graph_key
    )
    if not scenario_ids:
        print(
            f"  WARNING: no scenario pins graph '{graph_key}' yet — enumerating "
            "variants over ALL scenarios' track pins instead."
        )
        scenario_ids = sorted(s.scenario_id for s in scenarios)

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
    router,
    stops: dict,
    pairs: dict[tuple[str, str], float],
    models: dict,
    compositions: dict,
) -> tuple[list[Task], dict[str, dict | None]]:
    """(stop_lo, stop_hi, profile, variant_key) for every pair × model, in
    the pairs' distance order, plus variant_key → custom_model. The profile
    comes from the pair's own two stops through resolve_trip_gauge() — the
    same rule resolve_routing_params() applies at runtime, so keys match.
    Pairs with no common gauge are skipped; the runtime rejects them before
    any HTTP too."""
    tasks: list[Task] = []
    models_by_vkey: dict[str, dict | None] = {}
    n_gauge_skipped = 0
    any_comp = next(iter(compositions.values()))
    # route_variant_key() serialises and hashes the whole resolved custom
    # model (border polygons included) — milliseconds per call. It depends
    # on (profile, model) only, a handful of distinct values, so hash once
    # per combination instead of once per pair: 300k pairs took 20+ minutes
    # of single-core startup before routing began (measured 2026-09-22).
    model_list = list(models.values())
    vkey_by_profile_model: dict[tuple[str, int], str] = {}
    for lo, hi in pairs:
        try:
            gauge_mm = resolve_trip_gauge((stops[lo], stops[hi]), any_comp)
        except GaugeMismatchError:
            n_gauge_skipped += 1
            continue
        profile = router.profile_for_gauge(gauge_mm)
        for idx, entry in enumerate(model_list):
            vkey = vkey_by_profile_model.get((profile, idx))
            if vkey is None:
                vkey = route_variant_key(profile, entry["custom_model"])
                vkey_by_profile_model[(profile, idx)] = vkey
                models_by_vkey[vkey] = entry["custom_model"]
            tasks.append((lo, hi, profile, vkey))
    if n_gauge_skipped:
        print(f"  {n_gauge_skipped} pair(s) skipped: no common gauge.")
    return tasks, models_by_vkey


# ---------------------------------------------------------------------------
# Progress reporting
# ---------------------------------------------------------------------------


def fmt_duration(seconds: float | None) -> str:
    """Compact duration: 4d 03h, 7h 04m, 12m 30s, 45s."""
    if seconds is None or seconds < 0 or seconds == float("inf"):
        return "--"
    s = int(seconds)
    if s >= 86400:
        return f"{s // 86400}d {s % 86400 // 3600:02d}h"
    if s >= 3600:
        return f"{s // 3600}h {s % 3600 // 60:02d}m"
    if s >= 60:
        return f"{s // 60}m {s % 60:02d}s"
    return f"{s}s"


class ProgressReporter:
    """Live progress for a long batch: share done, throughput, elapsed,
    ETA and the wall-clock time the pass is expected to finish.

    The ETA follows the throughput of the last RATE_WINDOW_S rather than
    the run average — an overnight batch speeds up and slows down with
    the routing container, and a five-minute window tracks that instead
    of being dragged by the first hour. On a terminal the line refreshes
    in place once a second; when stdout is redirected (a log file, a
    detached container) it becomes one timestamped line every five
    minutes so the log stays readable.
    """

    def __init__(self, total: int, label: str) -> None:
        self.total = max(total, 0)
        self.label = label
        self.n_ok = 0
        self.n_fail = 0
        self._started = time.monotonic()
        self._last_draw = 0.0
        self._samples: deque[tuple[float, int]] = deque([(self._started, 0)])
        self._tty = sys.stdout.isatty()
        self._interval = (
            PROGRESS_TTY_INTERVAL_S if self._tty else PROGRESS_LOG_INTERVAL_S
        )

    @property
    def done(self) -> int:
        return self.n_ok + self.n_fail

    def record(self, ok: bool) -> None:
        if ok:
            self.n_ok += 1
        else:
            self.n_fail += 1
        self._tick()

    def advance(self, n: int) -> None:
        """Count n units of work at once — for byte-sized passes (gzip)
        rather than one call per item."""
        self.n_ok += n
        self._tick()

    def _tick(self) -> None:
        now = time.monotonic()
        self._samples.append((now, self.done))
        while len(self._samples) > 2 and now - self._samples[0][0] > RATE_WINDOW_S:
            self._samples.popleft()
        self.draw()

    def draw(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_draw < self._interval:
            return
        self._last_draw = now
        rate = self._rate(now)
        eta_s = (self.total - self.done) / rate if rate > 0 else None
        filled = round(BAR_WIDTH * self.done / self.total) if self.total else BAR_WIDTH
        line = (
            f"  {self.label} [{'#' * filled}{'.' * (BAR_WIDTH - filled)}] "
            f"{100 * self.done / self.total if self.total else 100:5.1f}%  "
            f"{self.done:,}/{self.total:,}  {rate:6.1f}/s  "
            f"elapsed {fmt_duration(now - self._started)}  "
            f"ETA {fmt_duration(eta_s)} ({self._finish_at(eta_s)})  "
            f"{self.n_fail:,} failed"
        )
        if self._tty:
            print(f"\r{line:<118}"[:118], end="", flush=True)
        else:
            print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {line.strip()}", flush=True)

    def finish(self) -> None:
        self.draw(force=True)
        if self._tty:
            print()

    def _rate(self, now: float) -> float:
        """Completions per second over the rate window, falling back to
        the run average until the window holds a real span."""
        t0, done0 = self._samples[0]
        span = now - t0
        if span >= 1.0 and self.done > done0:
            return (self.done - done0) / span
        elapsed = now - self._started
        return self.done / elapsed if elapsed > 0 else 0.0

    @staticmethod
    def _finish_at(eta_s: float | None) -> str:
        if eta_s is None:
            return "finish unknown"
        return f"finish ~{datetime.now() + timedelta(seconds=eta_s):%a %H:%M}"


# ---------------------------------------------------------------------------
# Resume: what is already routed, what failed last time
# ---------------------------------------------------------------------------


def repair_partial_tail(path: Path) -> bool:
    """Drop a half-written final line — the normal shape of a run killed
    mid-flush. Rows never contain newlines (JSON is compact-encoded), so
    the last '\\n' is exactly the end of the last complete row. Returns
    True when the file was truncated."""
    if not path.is_file() or path.stat().st_size == 0:
        return False
    with open(path, "rb") as fh:
        fh.seek(-1, os.SEEK_END)
        if fh.read(1) == b"\n":
            return False
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        window = min(size, 8 * 1024 * 1024)
        fh.seek(size - window)
        tail = fh.read(window)
    cut = tail.rfind(b"\n")
    keep = 0 if cut < 0 else size - window + cut + 1
    os.truncate(path, keep)
    print(f"  {path.name}: dropped {size - keep} byte(s) of a partial final row.")
    return True


def read_segment_keys(path: Path) -> set[SegmentKey]:
    """Every (stop_lo, stop_hi, variant_key) in a segment CSV (.csv or
    .csv.gz). Malformed rows are skipped with a count rather than raising
    — a resume must never need the file repaired by hand.

    The header must be exactly CSV_COLUMNS, otherwise the file is skipped:
    a failures report has nine columns and the same leading three, and
    reading it as segments would mark every failed pair as done."""
    if not path.is_file():
        return set()
    opener = gzip.open if path.name.endswith(".gz") else open
    keys: set[SegmentKey] = set()
    n_bad = 0
    with opener(path, "rt", newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if header is None:
            return keys
        if header != CSV_COLUMNS:
            print(f"  {path.name}: not a segment CSV (header differs) — skipped.")
            return keys
        try:
            for row in reader:
                if len(row) != len(CSV_COLUMNS):
                    n_bad += 1
                    continue
                keys.add((row[0], row[1], row[2]))
        except csv.Error as exc:
            n_bad += 1
            print(f"  {path.name}: stopped reading at a malformed row ({exc}).")
    suffix = f", {n_bad} malformed row(s) ignored" if n_bad else ""
    print(f"  {path.name}: {len(keys):,} segment(s) already routed{suffix}.")
    return keys


def read_failure_keys(path: Path) -> set[SegmentKey]:
    """The pairs listed in a <out>.failures.csv — the work set of
    --retry-failures-only."""
    if not path.is_file():
        sys.exit(f"{path} does not exist — nothing to retry.")
    with open(path, newline="", encoding="utf-8") as fh:
        keys = {
            (row["stop_lo"], row["stop_hi"], row["variant_key"])
            for row in csv.DictReader(fh)
        }
    print(f"  {path.name}: {len(keys):,} failed segment(s) to retry.")
    return keys


def collect_done_keys(out: Path, resume_from: list[Path]) -> set[SegmentKey]:
    """Keys that must not be routed again: the output file's own rows plus
    every --resume-from file's. Rows from --resume-from are NOT copied
    into --out — they are already in the target database, and re-exporting
    them would only inflate the upload."""
    done = read_segment_keys(out)
    for path in resume_from:
        done |= read_segment_keys(path)
    return done


def expand_resume_paths(raw: list[Path]) -> list[Path]:
    """--resume-from accepts files and directories. A directory contributes
    its segment files only — sidecars (.snapped, .failures) are left out,
    and where both X.csv and X.csv.gz exist only the CSV is read, which is
    the same rows without the decompression."""
    paths: list[Path] = []
    for path in raw:
        if path.is_dir():
            found = [
                p
                for p in sorted(path.glob("route_segments*.csv*"))
                if not any(tag in p.name for tag in (".snapped.", ".failures."))
                and p.name.endswith((".csv", ".csv.gz"))
            ]
            plain = {p.name for p in found if p.suffix == ".csv"}
            paths.extend(
                p for p in found if not (p.suffix == ".gz" and p.stem in plain)
            )
        elif path.is_file():
            paths.append(path)
        else:
            sys.exit(f"--resume-from: {path} does not exist.")
    return paths


# ---------------------------------------------------------------------------
# Snapping (one call per stop per profile, sidecar-cached)
# ---------------------------------------------------------------------------


def snap_helpers(stop, stops: dict, gauge_mm: int) -> list:
    """Candidate second points for snap_point(), nearest first — only stops
    the catalog says carry this profile's gauge (family-aware, strict:
    unknown gauge does not qualify). snap_point() routes stop → helper, so
    a helper on the other side of a gauge break (Hendaye's nearest stop is
    standard-gauge French, Barcelona-Sants' is Iberian) or on a cut-off
    branch fails the snap of a perfectly good stop."""
    return sorted(
        (
            o
            for o in stops.values()
            if o.stop_id != stop.stop_id and stop_supports_gauge(o, gauge_mm)
        ),
        key=lambda o: haversine_m(stop.lon, stop.lat, o.lon, o.lat),
    )[:SNAP_HELPER_CANDIDATES]


def snap_needed(
    router, stops: dict, needed: set[tuple[str, str]], sidecar: Path
) -> tuple[dict[tuple[str, str], list[float]], dict[tuple[str, str], str]]:
    """(snapped, errors): stop_id × profile → snapped [lon, lat], plus the
    reason for every combination that could not be snapped. Read from the
    sidecar where possible and appended to it as it goes, so the snapping
    pass is paid once across every rerun; failures are never stored and
    are simply re-attempted by the next run.

    Each stop tries up to SNAP_HELPER_CANDIDATES helpers. GraphHopper names
    the point it could not place: 'point 0' is the stop itself — no helper
    can fix that, so the search stops; anything else is the helper's or
    the connection's fault, and the next helper is tried. The snapped
    coordinate depends on the stop and profile only, so entries snapped
    with a different helper in an earlier run stay valid."""
    repair_partial_tail(sidecar)
    snapped: dict[tuple[str, str], list[float]] = {}
    if sidecar.is_file():
        with open(sidecar, newline="", encoding="utf-8") as fh:
            for row in csv.reader(fh):
                if len(row) == 4:
                    snapped[(row[0], row[1])] = [float(row[2]), float(row[3])]
        print(f"  snapping: {len(snapped):,} entries loaded from {sidecar.name}.")

    errors: dict[tuple[str, str], str] = {}
    todo = sorted(k for k in needed if k not in snapped)
    if not todo:
        return snapped, errors

    gauge_by_profile = {router.profile_for_gauge(g): g for g in SUPPORTED_GAUGES_MM}
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    progress = ProgressReporter(len(todo), "snapping")
    with open(sidecar, "a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        for sid, profile in todo:
            stop = stops[sid]
            helpers = snap_helpers(stop, stops, gauge_by_profile[profile])
            reason = "no catalog stop with this gauge to snap against"
            for helper in helpers:
                try:
                    coords = router.snap_point(
                        stop.lon, stop.lat, [helper.lon, helper.lat], profile
                    )
                except Exception as exc:
                    reason = f"{type(exc).__name__}: {exc}"[:300]
                    if "point 0" in str(exc).lower():
                        break
                    continue
                snapped[(sid, profile)] = coords
                writer.writerow([sid, profile, coords[0], coords[1]])
                break
            else:
                if helpers:
                    reason = f"all {len(helpers)} helpers failed, last — {reason}"
            if (sid, profile) not in snapped:
                errors[(sid, profile)] = reason
            progress.record(ok=(sid, profile) in snapped)
            if progress.done % 100 == 0:
                fh.flush()
    progress.finish()
    if errors:
        print(f"  snapping: {len(errors)} stop/profile combination(s) unsnappable:")
        for (sid, profile), reason in sorted(errors.items()):
            print(f"    {sid:<20} {profile:<18} {reason[:90]}")
    return snapped, errors


# ---------------------------------------------------------------------------
# Batch routing
# ---------------------------------------------------------------------------


@dataclass
class Failure:
    """One pair that is still missing from --out, and why."""

    task: Task
    error_type: str
    message: str
    attempts: int
    transient: bool
    at: str


def is_transient(exc: BaseException) -> bool:
    """Worth another attempt? A dropped connection, a timeout or a 5xx is
    the routing container under load; 'connection between locations not
    found' or a point off the network is the data, and reattempting it
    only burns night hours."""
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True
    if isinstance(exc, RailRoutingError):
        msg = str(exc).lower()
        return "http 5" in msg or "timed out" in msg or "timeout" in msg
    return False


class RemoteFailure(Exception):
    """A routing failure crossing the process boundary from a --processes
    worker: the original exception is classified in the child (type name +
    transient flag) because requests/RailRoutingError instances do not
    always survive pickling intact."""

    def __init__(self, error_type: str, message: str, transient: bool) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.transient = transient

    def __reduce__(self):
        return (RemoteFailure, (self.error_type, str(self), self.transient))


_CHILD: dict = {}


def _child_init(graph_key: str, snapped: dict, models_by_vkey: dict) -> None:
    """Per-process setup for --processes: each worker owns its router (HTTP
    session, CountryIndex, DB pool) — nothing routing-related is shared
    across processes, so the GIL stops being the ceiling."""
    import contextlib
    import io

    with contextlib.redirect_stdout(io.StringIO()):  # graph banner once is enough
        _, router, _ = build_context(graph_key)
    _CHILD.update(router=router, snapped=snapped, models=models_by_vkey)


def _child_route(task: Task) -> list:
    lo, hi, profile, vkey = task
    try:
        leg = _CHILD["router"].route_pair_from_snapped(
            [_CHILD["snapped"][(lo, profile)], _CHILD["snapped"][(hi, profile)]],
            _CHILD["models"][vkey],
            profile,
        )
        return segment_to_csv_row(lo, hi, vkey, segment_from_leg(leg, reverse=False))
    except Exception as exc:
        raise RemoteFailure(type(exc).__name__, str(exc), is_transient(exc)) from None


def record_failure(failures: dict[Task, Failure], task: Task, exc: Exception) -> None:
    previous = failures.get(task)
    remote = isinstance(exc, RemoteFailure)
    failures[task] = Failure(
        task=task,
        error_type=exc.error_type if remote else type(exc).__name__,
        message=str(exc).replace("\n", " ")[:500],
        attempts=(previous.attempts if previous else 0) + 1,
        transient=exc.transient if remote else is_transient(exc),
        at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def route_pass(
    router,
    tasks: list[Task],
    models_by_vkey: dict,
    snapped: dict,
    writer,
    fh,
    progress: ProgressReporter,
    failures: dict[Task, Failure],
    workers: int,
    deadline: float | None,
    processes: int = 1,
    graph_key: str | None = None,
) -> list[Task]:
    """One pass over `tasks`: route, append successes to --out, book
    failures. Returns the tasks never attempted, because --stop-after-h
    elapsed or Ctrl-C was pressed — they stay missing from --out and are
    picked up by the next run.

    Concurrency: `workers` threads in this process by default. With
    `processes` > 1 the routing moves to that many worker processes (one
    task in flight per process, this process only writes the CSV) — the
    per-segment Python work (response parsing, country attribution,
    haversine over every vertex, CSV encoding) is what saturates a single
    core at ~20 segments/s on the server, not GraphHopper."""

    def route_one(task: Task) -> list:
        lo, hi, profile, vkey = task
        leg = router.route_pair_from_snapped(
            [snapped[(lo, profile)], snapped[(hi, profile)]],
            models_by_vkey[vkey],
            profile,
        )
        return segment_to_csv_row(lo, hi, vkey, segment_from_leg(leg, reverse=False))

    not_attempted: list[Task] = []
    stopped = False
    if processes > 1:
        # spawn, not fork: the parent holds an open DB pool and an HTTP
        # session, and a forked child closing inherited sockets breaks them.
        pool = ProcessPoolExecutor(
            max_workers=processes,
            mp_context=multiprocessing.get_context("spawn"),
            initializer=_child_init,
            initargs=(graph_key, snapped, models_by_vkey),
        )
        route_fn = _child_route
    else:
        pool = ThreadPoolExecutor(max_workers=workers)
        route_fn = route_one
    try:
        for start in range(0, len(tasks), SUBMIT_CHUNK):
            if stopped:
                not_attempted.extend(tasks[start:])
                break
            if deadline is not None and time.monotonic() > deadline:
                not_attempted.extend(tasks[start:])
                break
            futures = {
                pool.submit(route_fn, t): t
                for t in tasks[start : start + SUBMIT_CHUNK]
            }
            consumed: set[Task] = set()
            try:
                for future in as_completed(futures):
                    task = futures[future]
                    consumed.add(task)
                    try:
                        writer.writerow(future.result())
                        failures.pop(task, None)
                        progress.record(ok=True)
                    except Exception as exc:
                        record_failure(failures, task, exc)
                        progress.record(ok=False)
                    if progress.done % FLUSH_EVERY == 0:
                        fh.flush()
                    if deadline is not None and time.monotonic() > deadline:
                        # Checked here as well as between chunks so a
                        # --stop-after-h run stops on time even when the
                        # whole batch fits into one chunk.
                        stopped = True
                        print("\n  --stop-after-h reached — stopping cleanly.")
                        for pending in futures:
                            pending.cancel()
                        not_attempted.extend(
                            t for t in futures.values() if t not in consumed
                        )
                        break
            except KeyboardInterrupt:
                stopped = True
                print("\n  Ctrl-C — letting in-flight calls finish, then stopping.")
                for future in futures:
                    future.cancel()
                # Everything not yet written counts as not attempted — the
                # in-flight calls finish, but their results are discarded.
                not_attempted.extend(t for t in futures.values() if t not in consumed)
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
        fh.flush()
        progress.finish()
    return not_attempted


def write_failures(
    path: Path,
    failures: dict[Task, Failure],
    unsnappable: list[Task],
    snap_errors: dict[tuple[str, str], str],
) -> None:
    """Rewrite the failures file from scratch — it reports what is missing
    NOW, so a rerun that fixes everything leaves an empty report rather
    than yesterday's errors. A NotSnapped row names the end that could not
    be snapped and why."""
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(FAILURE_COLUMNS)
        for lo, hi, profile, vkey in unsnappable:
            reason = "; ".join(
                f"{sid}: {snap_errors[(sid, profile)]}"
                for sid in (lo, hi)
                if (sid, profile) in snap_errors
            )
            writer.writerow([lo, hi, profile, vkey, 0, False, "NotSnapped", reason, ""])
        for f in sorted(failures.values(), key=lambda f: f.task):
            lo, hi, profile, vkey = f.task
            writer.writerow(
                [
                    lo,
                    hi,
                    profile,
                    vkey,
                    f.attempts,
                    f.transient,
                    f.error_type,
                    f.message,
                    f.at,
                ]
            )


def run_batch(
    router, tasks, models_by_vkey, snapped, snap_errors, pair_km, out: Path, args
) -> None:
    done = collect_done_keys(out, expand_resume_paths(args.resume_from or []))
    only = (
        read_failure_keys(out.with_suffix(".failures.csv"))
        if args.retry_failures_only
        else None
    )

    unsnappable = [
        t for t in tasks if (t[0], t[2]) not in snapped or (t[1], t[2]) not in snapped
    ]
    unsnappable_set = set(unsnappable)
    todo = [
        t
        for t in tasks
        if (t[0], t[1], t[3]) not in done
        and t not in unsnappable_set
        and (only is None or (t[0], t[1], t[3]) in only)
    ]
    print(
        f"\nPredict-before-run: {len(tasks):,} segments total; {len(done):,} already "
        f"done, {len(unsnappable):,} unsnappable, {len(todo):,} to route now."
    )
    if not todo:
        print("Nothing to do.")
        write_failures(out.with_suffix(".failures.csv"), {}, unsnappable, snap_errors)
        return

    out.parent.mkdir(parents=True, exist_ok=True)
    write_header = not out.is_file() or out.stat().st_size == 0
    deadline = (
        time.monotonic() + args.stop_after_h * 3600 if args.stop_after_h else None
    )
    failures: dict[Task, Failure] = {}
    n_before = len(todo)

    with open(out, "a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if write_header:
            writer.writerow(CSV_COLUMNS)
        progress = ProgressReporter(len(todo), "routing ")
        not_attempted = route_pass(
            router,
            todo,
            models_by_vkey,
            snapped,
            writer,
            fh,
            progress,
            failures,
            args.workers,
            deadline,
            processes=args.processes,
            graph_key=args.graph,
        )
        n_routed = progress.n_ok

        for round_no in range(1, args.retry_rounds + 1):
            retry = [f.task for f in failures.values() if args.retry_all or f.transient]
            if not retry or not_attempted:
                break
            print(
                f"\nRetry round {round_no}/{args.retry_rounds}: {len(retry):,} pair(s) "
                f"after {args.retry_delay_s}s."
            )
            time.sleep(args.retry_delay_s)
            progress = ProgressReporter(len(retry), f"retry {round_no} ")
            not_attempted = route_pass(
                router,
                retry,
                models_by_vkey,
                snapped,
                writer,
                fh,
                progress,
                failures,
                args.workers,
                deadline,
                processes=args.processes,
                graph_key=args.graph,
            )
            n_routed += progress.n_ok

    failures_path = out.with_suffix(".failures.csv")
    write_failures(failures_path, failures, unsnappable, snap_errors)
    n_transient = sum(1 for f in failures.values() if f.transient)
    settled = n_routed + len(failures) + len(not_attempted)
    if not_attempted:
        verdict = "stopped early"
    elif settled == n_before:
        verdict = "MATCH"
    else:
        verdict = "MISMATCH, investigate"
    print(
        f"\nDone: {n_routed:,} routed, {len(failures):,} failed "
        f"({n_transient:,} transient, {len(failures) - n_transient:,} permanent), "
        f"{len(not_attempted):,} not attempted (predicted {n_before:,} — {verdict})."
    )
    print(f"Failures + unsnappable pairs: {failures_path.name}.")
    if not_attempted:
        # Work runs shortest pair first, so the smallest distance left
        # undone is the edge of a complete band.
        edge_km = min(pair_km[(lo, hi)] for lo, hi, _, _ in not_attempted)
        print(
            f"Every pair under {edge_km:.0f} km straight-line is routed or listed "
            "as failed. Rerun the same command to continue from there."
        )


# ---------------------------------------------------------------------------
# Measure / finalize / export / load
# ---------------------------------------------------------------------------


def measure(router, stops, models, probe_pairs, workers) -> None:
    print(f"\nStops in catalog: {len(stops)}")
    print("\nPair counts by haversine cap (replaces the area guess):")
    for cap in (300, 500, 800, None):
        n = len(generate_pairs(stops, cap))
        label = f"{cap} km" if cap else "uncapped"
        print(f"  {label:>9}: {n:>9,} pairs → ~{n * len(models):>10,} segments")

    print(f"\nCustom-model variants (empirical, expected 3 per graph): {len(models)}")
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
    repair_partial_tail(out)
    failures_path = out.with_suffix(".failures.csv")
    n_failures = 0
    if failures_path.is_file():
        with open(failures_path, newline="", encoding="utf-8") as fh:
            n_failures = max(sum(1 for _ in fh) - 1, 0)

    # One sequential pass: count and compress together. Rows never contain
    # newlines (compact JSON), so counting '\n' is the row count without
    # parsing gigabytes of geometry through the csv module.
    gz_path = out.with_suffix(out.suffix + ".gz")
    total_mb = max(1, -(-out.stat().st_size // MB))
    progress = ProgressReporter(total_mb, "gzip MB ")
    n_lines = read = 0
    with (
        open(out, "rb") as src,
        gzip.open(gz_path, "wb", compresslevel=GZIP_LEVEL) as dst,
    ):
        while chunk := src.read(COPY_CHUNK):
            n_lines += chunk.count(b"\n")
            dst.write(chunk)
            read += len(chunk)
            progress.advance(-(-read // MB) - progress.done)
    progress.finish()
    n_rows = max(n_lines - 1, 0)  # minus the header

    meta = {
        "graph_key": graph_key,
        "import_date": import_date,
        "distance_cap_km": cap_km,
        "n_stops": n_stops,
        "n_segments": n_rows,
        "n_failures": n_failures,
        "models": {k: m["description"] for k, m in sorted(models.items())},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    meta_path = out.with_suffix(".meta.json")
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(
        f"Finalized: {gz_path.name} ({gz_path.stat().st_size / 1e6:.1f} MB, "
        f"{n_rows:,} segments, {n_failures:,} still missing) + {meta_path.name}.\n"
        f"Server: --load. Remote server without DB access: --export-upload. "
        f"Dev: copy the .gz and .meta.json into backend/db/dev/data/."
    )


def staging_ddl(table: str) -> str:
    """CREATE TABLE for the upload staging table, derived from the
    declarative schema (db/schema.py ROUTE_CACHE_TABLES) so its types
    cannot drift from route_cache.route_segments. Column constraints are
    dropped: the file carries neither the graph key nor the source, and
    staging validates nothing the merge does not."""
    segments = next(t for t in ROUTE_CACHE_TABLES if t.name == "route_segments")
    by_name = {c.name: c for c in segments.columns}
    lines = [
        f"    {name:<19} {by_name[name].sql_type.split(' NOT NULL')[0]}"
        for name in CSV_COLUMNS
    ]
    return f"CREATE UNLOGGED TABLE {table} (\n" + ",\n".join(lines) + "\n);"


def split_csv(out: Path, target: Path, split_mb: float) -> list[Path]:
    """Copy --out into <= split_mb parts, each with its own header, so a
    pgAdmin import that drops halfway costs one part and not the night."""
    limit = int(split_mb * MB)
    parts: list[Path] = []
    with open(out, "rb") as src:
        header = src.readline()
        part: Path | None = None
        fh = None
        written = 0
        for line in src:
            if fh is None or written + len(line) > limit:
                if fh is not None:
                    fh.close()
                part = target / f"{out.stem}_part{len(parts) + 1:02d}.csv"
                parts.append(part)
                fh = open(part, "wb")
                fh.write(header)
                written = len(header)
            fh.write(line)
            written += len(line)
        if fh is not None:
            fh.close()
    return parts


def export_upload(out: Path, graph_key: str, import_date: str | None, split_mb: float):
    """Write the pgAdmin kit next to --out: the CSV part file(s) (or a
    pointer to --out itself when no split was asked for) and the two SQL
    steps around the import — staging table first, guarded merge after.

    The merge goes through a staging table because route_segments carries
    two columns the file deliberately does not (the graph key and the
    source) and because a direct import would abort on the first pair the
    server has already routed live; INSERT ... ON CONFLICT DO NOTHING
    makes the load idempotent and safe to repeat part by part."""
    if not out.is_file():
        sys.exit(f"{out} does not exist — run the batch first.")
    repair_partial_tail(out)
    target = out.parent / f"upload_{graph_key}"
    target.mkdir(parents=True, exist_ok=True)

    if split_mb and split_mb > 0:
        parts = split_csv(out, target, split_mb)
        part_note = "\n".join(f"  {p.name}" for p in parts)
    else:
        parts = [out]
        part_note = f"  {out}  (not split — pass --split-mb to cut it up)"

    table = "route_cache.route_segments_staging"
    columns = ", ".join(CSV_COLUMNS)
    guard = (
        f"""
DO $$
DECLARE
    server_import TEXT;
BEGIN
    SELECT import_date INTO server_import FROM route_cache.graph_state
     WHERE routing_graph_key = '{graph_key}';
    IF server_import IS NOT NULL AND server_import <> '{import_date}' THEN
        RAISE EXCEPTION 'Graph import mismatch for {graph_key}: server has %, file was routed against {import_date} — do not load it.', server_import;
    END IF;
END $$;
"""
        if import_date
        else "-- Graph unreachable at export time: no import_date guard generated.\n"
    )

    (target / "01_create_staging.sql").write_text(
        f"""-- Step 1 — staging table for the precomputed segments of '{graph_key}'.
-- Run once in pgAdmin's Query Tool, then import the CSV part(s) into
-- {table} with the import wizard (Header: Yes, Format: csv).
CREATE SCHEMA IF NOT EXISTS route_cache;
DROP TABLE IF EXISTS {table};
{staging_ddl(table)}
""",
        encoding="utf-8",
    )

    (target / "02_merge.sql").write_text(
        f"""-- Step 3 — merge staging into the live cache for '{graph_key}'.
-- Additive and idempotent: rows the server already routed live are kept.
{guard}
INSERT INTO route_cache.route_segments (routing_graph_key, {columns}, source)
SELECT '{graph_key}', {columns}, 'precompute'
FROM {table}
ON CONFLICT (routing_graph_key, stop_lo, stop_hi, variant_key) DO NOTHING;

-- Only when the server has never recorded this graph: without a row here
-- the API cannot detect a later re-import and would keep serving rows
-- routed on the old graph.
INSERT INTO route_cache.graph_state (routing_graph_key, import_date, synced_at)
VALUES ('{graph_key}', '{import_date}', now())
ON CONFLICT (routing_graph_key) DO NOTHING;

-- Emptied, not dropped, so the next part can be imported into it — that
-- keeps the staging copy on the server small instead of a second copy of
-- the whole file. 03_drop_staging.sql removes it after the last part.
TRUNCATE {table};

SELECT routing_graph_key, source, COUNT(*)
FROM route_cache.route_segments GROUP BY 1, 2 ORDER BY 1, 2;
""",
        encoding="utf-8",
    )

    (target / "03_drop_staging.sql").write_text(
        f"""-- Step 4 — after the last part is merged.
DROP TABLE IF EXISTS {table};
""",
        encoding="utf-8",
    )

    (target / "README.md").write_text(
        f"""# Upload kit — route_cache segments for `{graph_key}`

Routed against GraphHopper import `{import_date}`.
Generated {datetime.now(timezone.utc).isoformat(timespec="seconds")}.

CSV part(s) to import:

```
{part_note}
```

1. pgAdmin → Query Tool on the target database → run `01_create_staging.sql`.
2. Browser → `route_cache` → Tables → `route_segments_staging` → right-click →
   *Import/Export Data…* → Import, Format `csv`, Header `Yes`, Delimiter `,`,
   Quote `"`, Encoding `UTF8`. Repeat once per part file, in any order.
3. Query Tool → run `02_merge.sql`. It refuses the load if the server's graph
   import differs from the one these rows were routed against, merges with
   `ON CONFLICT DO NOTHING`, empties staging and prints the row counts per
   graph and source. Run it after each part (staging stays small) or once
   after importing every part — both end at the same rows.
4. Query Tool → run `03_drop_staging.sql`.

No API restart is needed — lookups read the table live.
""",
        encoding="utf-8",
    )
    print(
        f"Upload kit in {target}:\n{part_note}\n"
        f"  01_create_staging.sql, 02_merge.sql, 03_drop_staging.sql, README.md"
    )


def load(out: Path, graph_key: str, import_date: str | None) -> None:
    path = out.with_suffix(out.suffix + ".gz")
    if not path.is_file():
        path = out
    if not path.is_file():
        sys.exit(f"Neither {path.name} nor its .gz exists — run --finalize first.")
    repo = RouteSegmentRepository()
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


# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Precompute route segments for one graph."
    )
    parser.add_argument("--graph", default=DEFAULT_ROUTING_GRAPH_KEY)
    parser.add_argument("--cap-km", type=float, default=800)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--processes",
        type=int,
        default=1,
        help="route in N worker processes instead of --workers threads; use "
        "when the script (not GraphHopper) is at 100%% of one core",
    )
    parser.add_argument("--out", type=Path)
    parser.add_argument("--limit", type=int, help="debug: route only N pairs")
    parser.add_argument("--probe", type=int, default=20)
    parser.add_argument(
        "--resume-from",
        type=Path,
        nargs="+",
        metavar="PATH",
        help="further segment CSV/CSV.GZ files (or directories of them) whose "
        "keys count as done; not copied into --out",
    )
    parser.add_argument(
        "--retry-rounds",
        type=int,
        default=2,
        help="passes over the failed pairs after the main one (default 2)",
    )
    parser.add_argument(
        "--retry-delay-s",
        type=int,
        default=60,
        help="pause before each retry round (default 60)",
    )
    parser.add_argument(
        "--retry-all",
        action="store_true",
        help="retry permanent failures (no route, point off the network) too",
    )
    parser.add_argument(
        "--retry-failures-only",
        action="store_true",
        help="route only the pairs listed in <out>.failures.csv",
    )
    parser.add_argument(
        "--stop-after-h",
        type=float,
        help="end the run cleanly after N hours; rerun to resume",
    )
    parser.add_argument("--measure-only", action="store_true")
    parser.add_argument("--finalize", action="store_true")
    parser.add_argument(
        "--export-upload",
        action="store_true",
        help="write the pgAdmin upload kit (CSV parts + staging/merge SQL)",
    )
    parser.add_argument(
        "--split-mb",
        type=float,
        default=0,
        help="with --export-upload: split the CSV into parts of this size "
        "(0 = no split; 250 is a comfortable pgAdmin import)",
    )
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
    if args.export_upload:
        export_upload(out, args.graph, import_date, args.split_mb)
        return
    if args.load:
        load(out, args.graph, import_date)
        return

    repair_partial_tail(out)
    pairs = generate_pairs(stops, args.cap_km)
    if args.limit:
        pairs = dict(islice(pairs.items(), args.limit))
    compositions = loader.build_all_compositions().all()
    tasks, models_by_vkey = build_tasks(router, stops, pairs, models, compositions)
    needed = {(lo, p) for lo, _, p, _ in tasks} | {(hi, p) for _, hi, p, _ in tasks}
    snapped, snap_errors = snap_needed(
        router, stops, needed, out.with_suffix(".snapped.csv")
    )
    run_batch(router, tasks, models_by_vkey, snapped, snap_errors, pairs, out, args)


if __name__ == "__main__":
    main()
