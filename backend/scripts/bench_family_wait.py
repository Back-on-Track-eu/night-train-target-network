"""
bench_family_wait.py
====================
What a user waits for when the proposal builder calculates: end-to-end wall
time of POST /api/proposal/family over HTTP, next to the server's own
stats (elapsed_s, members, leg variants, cache_hit). The numbers calibrate
the builder's expected-duration model (FAMILY_WAIT_MODEL in
frontend/src/lib/calcExpectation.ts) — when "taking longer than usual"
appears — so they are measured the way the browser sees them, not in-process
like bench_member.py. The last lines print the constants to copy over.

Four runs per route:

    first    new family key, full axes. Routes live only for stop pairs this
             graph has never routed; on a rerun of the script its legs are
             already in route_cache.route_segments and it equals "cold".
    cold     new family key, full axes, legs cached — what most calculations
             and every Details recalculation cost.
    hit      the "cold" request again — served from the document cache.
    narrow   new family key, one scenario variant x two compositions — the
             same route with few members, which separates per-leg from
             per-member cost.

A new key comes from a random passengers_per_year: demand is part of the
family key but costs nothing in routing, so the work stays the same.

Without scenario_variant_ids the backend's default axes are used, which may
hold more members than the builder posts (it sends only offered scenarios);
the fit reads n_members from the response, so that does not bias it.

Run host-side against the dev stack:

    uv run python -m scripts.bench_family_wait
    uv run python -m scripts.bench_family_wait --route "ber-wien=osm:n...,osm:w..."
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dev_env import api_base_url  # noqa: E402

API_BASE = api_base_url()
TIMEOUT_S = 180

# Known-good ids from the corridor scripts beside this one.
WIEN_HBF = "osm:w423692233"
PARIS_EST = "osm:n2506241285"
DEFAULT_ROUTES = {
    "wien-paris-2": [WIEN_HBF, PARIS_EST],
    "paris-berlin-4": [
        PARIS_EST,
        "osm:n17401552",
        "osm:n2459919677",
        "osm:n3856100103",
    ],
    "hamburg-kbh-4": [
        "osm:n2470201868",
        "osm:n3856100103",
        "osm:n2459919677",
        "osm:n3739700410",
    ],
    "wien-paris-7": [
        WIEN_HBF,
        "osm:w19800696",  # Linz Hbf
        "osm:n302097253",  # Salzburg Hbf
        "osm:n2465304880",  # München Ost
        "osm:n2574283615",  # Karlsruhe Hbf
        "osm:n3069229440",  # Strasbourg
        PARIS_EST,
    ],
    "wien-paris-11": [
        WIEN_HBF,
        "osm:n66432827",  # Wien Meidling
        "osm:n2465563392",  # St. Pölten Hbf
        "osm:w19800696",
        "osm:n302097253",
        "osm:n2578699502",  # Rosenheim
        "osm:n2465304880",
        "osm:n1058668074",  # Augsburg Hbf
        "osm:n2574283615",
        "osm:n3069229440",
        PARIS_EST,
    ],
}


def fresh_body(stops: list[str], **axes) -> dict:
    return {
        "stops": stops,
        "auto_stop_addition": "off",
        "demand": {"passengers_per_year": random.randint(100_000, 999_999)},
        **axes,
    }


def post(body: dict) -> tuple[float, dict, int]:
    """Wall seconds, the document, and the bytes on the wire (compressed)."""
    started = time.perf_counter()
    resp = requests.post(
        f"{API_BASE}/api/proposal/family", json=body, timeout=TIMEOUT_S
    )
    wall = time.perf_counter() - started
    resp.raise_for_status()
    return wall, resp.json(), int(resp.headers.get("Content-Length", len(resp.content)))


def measure(label: str, stops: list[str]) -> list[dict]:
    rows = []

    def record(run: str, body: dict) -> dict:
        wall, doc, size = post(body)
        stats = doc["stats"]
        rows.append(
            {
                "route": label,
                "run": run,
                "legs": len(stops) - 1,
                "members": stats["n_members"],
                "leg_variants": stats.get("context", {}).get("n_leg_variants", 0),
                "server_s": stats["elapsed_s"],
                "wall_s": round(wall, 2),
                "kb": round(size / 1024),
                "hit": stats["cache_hit"],
            }
        )
        return doc

    doc = record("first", fresh_body(stops))
    cold = fresh_body(stops)
    record("cold", cold)
    record("hit", cold)
    # The presented member must stay on the narrowed axes, or the backend
    # answers 400 — so the pair is the presented composition plus one other.
    presented = doc["presented"]
    others = [
        c for c in doc["axes"]["compositions"] if c != presented["composition_id"]
    ]
    record(
        "narrow",
        fresh_body(
            stops,
            scenario_variant_ids=[presented["scenario_variant_id"]],
            composition_ids=[presented["composition_id"], *others[:1]],
            presented=presented,
        ),
    )
    return rows


def print_table(rows: list[dict]) -> None:
    cols = list(rows[0])
    widths = {c: max(len(c), *(len(str(r[c])) for r in rows)) for c in cols}
    print("  ".join(c.ljust(widths[c]) for c in cols))
    for r in rows:
        print("  ".join(str(r[c]).ljust(widths[c]) for c in cols))


def print_fit(rows: list[dict]) -> None:
    """wall = base + per_member * m + per_member_leg * m * legs, least squares
    over the doc-cold runs with cached legs. Every member evaluates every leg,
    so legs cost per member — an additive legs term fits the narrow runs
    badly. Printed in the units of FAMILY_WAIT_MODEL in
    frontend/src/lib/calcExpectation.ts, which these numbers calibrate."""
    sample = [r for r in rows if r["run"] in ("cold", "narrow")]
    if len({(r["legs"], r["members"]) for r in sample}) < 3:
        print("\nToo few distinct (legs, members) points to fit.")
        return
    x = np.array([[1.0, r["members"], r["members"] * r["legs"]] for r in sample])
    y = np.array([r["wall_s"] for r in sample])
    coef, *_ = np.linalg.lstsq(x, y, rcond=None)
    worst = max(abs(y - x @ coef))
    base, per_member, per_member_leg = coef * 1000
    print(
        f"\nFAMILY_WAIT_MODEL: baseMs {base:.0f}, perMemberMs {per_member:.1f},"
        f" perMemberLegMs {per_member_leg:.2f}   (worst residual {worst:.2f} s)"
    )
    firsts = {r["route"]: r["wall_s"] for r in rows if r["run"] == "first"}
    colds = {r["route"]: r["wall_s"] for r in rows if r["run"] == "cold"}
    premiums = {route: first - colds[route] for route, first in firsts.items()}
    for route, premium in premiums.items():
        print(f"Live-routing premium {route}: {premium:+.2f} s")
    print(
        f"newRouteMs candidate (median premium): "
        f"{1000 * float(np.median(list(premiums.values()))):.0f}"
        " — only meaningful on a stack that has not routed these legs yet"
    )
    hits = [r["wall_s"] for r in rows if r["run"] == "hit"]
    print(f"Cache hit: median {np.median(hits):.2f} s")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--route",
        action="append",
        metavar="LABEL=ID,ID,...",
        help="replace the default routes; repeatable",
    )
    args = parser.parse_args()
    routes = (
        {k: v.split(",") for k, v in (r.split("=", 1) for r in args.route)}
        if args.route
        else DEFAULT_ROUTES
    )

    try:
        requests.get(f"{API_BASE}/api/health", timeout=5).raise_for_status()
    except requests.RequestException as exc:
        print(f"API not reachable at {API_BASE}: {exc}")
        return 1

    rows = []
    for label, stops in routes.items():
        print(f"{label} ({len(stops)} stops) ...", flush=True)
        try:
            rows.extend(measure(label, stops))
        except requests.HTTPError as exc:
            print(f"  skipped: {exc} {exc.response.text[:200]}")
    if not rows:
        return 1
    print()
    print_table(rows)
    print_fit(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
