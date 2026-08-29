"""Stage 7 — did any route actually change?

A target that changes no route is the normal failure, and it is silent. `diff`
answers in track-kilometres, but the model cares about journey times, and a
corridor can be perfectly imported and still never chosen because the router
found something faster. So each project carries a **probe**: two well-connected
stations whose best path should move once the project opens, plus the box the
new path has to pass through.

`via_bbox` is what makes this a test rather than a stopwatch. A route can get
faster for reasons unrelated to the project; it can only pass *through* the new
corridor if the corridor is in the graph.

One caveat on the numbers: **no custom model is sent**, while the backend
builds one per request (composition speed cap, high-speed-track penalty where
the composition or country disallows it). These are the graph's own times, not
the model's. That is the right isolation for a data test — "is the corridor in
the graph" separated from "would this train be allowed on it" — but the times
will not match the app's, and a corridor that passes here can still be
penalised out of a real proposal.

Only the standard library is used: the routing servers are already up, and
talking to them should not need a dependency.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from .catalogue import Probe, Project
from .config import Target
from .geo import BBox
from .ghimport import load_registry

# Verdicts that mean the run failed. SAME is in the list on purpose: a probe
# that reports SAME is the exact silent-nothing-happened case this stage exists
# to catch, and letting it exit 0 made the whole check decorative.
FAILING = ("FAIL", "SAME", "BASELINE ERROR")

# Neither side routes at all. On a country extract that is the normal answer
# for every project outside the region — Bordeaux does not route on a Danish
# graph — so it is reported and not counted, or the gate would be useless
# exactly where it is cheapest to run. On the europe dataset the same line is
# a real finding: probe coordinates that snap to nothing.
UNTESTABLE = "NO ROUTE"


@dataclass(frozen=True)
class RouteResult:
    ok: bool
    distance_km: float = 0.0
    time_min: float = 0.0
    via: bool = False
    error: str = ""

    def describe(self) -> str:
        if not self.ok:
            return f"no route ({self.error})"
        return (
            f"{self.distance_km:8,.0f} km {self.time_min:7,.0f} min "
            f"{'via' if self.via else 'not via'}"
        )


def _post(url: str, payload: dict, timeout: float) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def route(port: int, probe: Probe, profile: str, timeout: float = 120.0) -> RouteResult:
    """One probe against one running OpenRailRouting server."""
    payload = {
        "profile": profile,
        # GraphHopper takes [lon, lat], same as the backend's RailRouter.
        "points": [
            [probe.origin.lon, probe.origin.lat],
            [probe.destination.lon, probe.destination.lat],
        ],
        "points_encoded": False,
        "instructions": False,
    }
    try:
        body = _post(f"http://localhost:{port}/route", payload, timeout)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = json.loads(exc.read()).get("message", "")
        except Exception:
            pass
        return RouteResult(ok=False, error=(detail or str(exc))[:200])
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return RouteResult(ok=False, error=str(exc)[:200])

    paths = body.get("paths") or []
    if not paths:
        return RouteResult(ok=False, error="no paths in response")
    path = paths[0]
    coords = (path.get("points") or {}).get("coordinates") or []
    return RouteResult(
        ok=True,
        distance_km=path.get("distance", 0.0) / 1000.0,
        time_min=path.get("time", 0.0) / 60000.0,
        via=_passes_through(coords, probe.via),
    )


def _passes_through(coords: list, box: BBox) -> bool:
    """Does the returned polyline enter the box?

    Vertex sampling only — a route whose segment crosses a small box between
    two consecutive vertices reads as a miss, so a via_bbox has to be drawn
    large relative to GraphHopper's point spacing.

    The slice is deliberate: with `elevation` enabled GraphHopper returns
    [lon, lat, ele], and unpacking a fixed pair would raise rather than
    degrade.
    """
    for point in coords:
        if len(point) < 2:
            continue
        lon, lat = point[0], point[1]
        if box.contains(lat, lon):
            return True
    return False


def _verdict(baseline: RouteResult, scenario: RouteResult) -> str:
    # Checked first: a baseline server that is down, still loading its graph,
    # or serving a different dataset reports ok=False and therefore via=False,
    # which would otherwise read as "the baseline does not go this way" and
    # turn an outage into a PASS.
    if not baseline.ok and scenario.ok:
        return "BASELINE ERROR"
    if not scenario.ok:
        return "FAIL" if baseline.ok else "NO ROUTE"
    if scenario.via and not baseline.via:
        return "PASS"
    if scenario.via and baseline.via:
        # The baseline already goes this way — an already-open project, or a
        # via_bbox drawn wide enough to catch the old alignment too.
        return "ALREADY"
    return "SAME"


def _port_for(slug: str) -> int:
    registry = load_registry()
    entry = registry.get(slug)
    if entry is None:
        running = ", ".join(sorted(registry)) or "(none)"
        raise RuntimeError(
            f"no routing server for {slug!r}. Running: {running}\n"
            f"Start one with:  osm-pipe serve ..."
        )
    return int(entry["port"])


def verify(
    target: Target,
    baseline: Target,
    projects: tuple[Project, ...],
    *,
    profile: str = "night_train",
    project_id: str = "",
    timeout: float = 120.0,
    allow_same: bool = False,
) -> int:
    """Route every probe against both servers. Returns the failure count."""
    baseline_port = _port_for(baseline.slug)
    target_port = _port_for(target.slug)

    print(f"[verify] baseline {baseline.slug} @ {baseline.as_of} :{baseline_port}")
    print(f"[verify] target   {target.slug} @ {target.as_of} :{target_port}")
    print()

    failures = 0
    tested = 0
    untestable: list[str] = []
    for project in projects:
        if project_id and project.id != project_id:
            continue
        if project.probe is None:
            continue
        tested += 1
        probe = project.probe
        base = route(baseline_port, probe, profile, timeout)
        scen = route(target_port, probe, profile, timeout)
        verdict = _verdict(base, scen)

        print(f"{verdict:<14} {project.id}")
        print(f"{'':14} {probe.origin.name} -> {probe.destination.name}")
        print(f"{'':14} baseline  {base.describe()}")
        print(f"{'':14} target    {scen.describe()}")
        if base.ok and scen.ok:
            delta = scen.time_min - base.time_min
            print(f"{'':14} delta    {delta:+8,.0f} min")
        if verdict == "SAME" and probe.baseline:
            print(f"{'':14} expected the path to leave: {probe.baseline}")
        print()

        if verdict == UNTESTABLE:
            untestable.append(project.id)
        elif verdict in FAILING and not (verdict == "SAME" and allow_same):
            failures += 1

    if not tested:
        print("[verify] no probes to run — nothing was tested")
        return 1

    checked = tested - len(untestable)
    print(f"[verify] {tested} probe(s): {checked} checked, {failures} failure(s)")
    if untestable:
        print(
            f"[verify] {len(untestable)} not testable on dataset "
            f"{target.dataset.name!r} — neither side routes at all:"
        )
        print(f"[verify]     {', '.join(untestable)}")
        print(
            "[verify]   Expected off-region and not counted as failures. On "
            "-d europe the same line means probe coordinates that snap to "
            "nothing, which IS a finding."
        )
    if failures:
        print(
            "[verify] SAME means the promotion had no effect on that pair. "
            "Check `osm-survey diff` first: if the promoted track landed in "
            "`pruned` or `island` the corridor is disconnected, and "
            "`osm-survey connectors` finds the missing junctions."
        )
    return failures
