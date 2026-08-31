"""
verify_routing_graph.py
=======================
Acceptance check for a freshly imported routing graph, run straight after
the import and before the graph is zipped, uploaded, or registered in
backend/docker/.env.

Talks HTTP to the OpenRailRouting instances only — no API, no database, no
seeded scenario. That is deliberate: a graph has to be proven before a
scenario is allowed to pin it, and at that point the backend knows nothing
about it yet.

Four checks, in the order failures are cheapest to act on:

  1. /info on both graphs — the profile lists must be IDENTICAL (every
     instance shares config.yml, so a difference means the image or the
     cache is out of step with the source tree), and both bounding boxes
     are printed side by side as the coverage comparison.
  2. Gauge matrix on the target graph — the should-route pairs prove
     coverage, the should-fail pairs prove the gauge TAGS survived into
     the graph. The second half is the one that matters on a pre-filtered
     OSM extract: untagged track (gauge == 0) is permitted by every
     profile by design, so a graph that lost its gauge tags routes
     everything on every profile and looks perfectly healthy until a
     Spanish trip is planned on standard gauge.
  3. Corridor delta — one relation routed on both graphs, reported as a
     distance and time difference. For infra_2032 against infra_2026 the
     default pair crosses the Fehmarn Belt: near-identical numbers mean
     the OSM file is not the upgraded network.
  4. Graph cache size on disk for both graphs, as a bulk sanity number.

Out of scope: the Belarus/Russia exclusion. Since 0.9.27 it is applied per
request as an area rule in the backend's custom model, never baked into
the graph, so a bare /route call like the ones here is not blocked and
cannot test it (models/route/routing/README.md).

Usage:
    uv run python scripts/verify_routing_graph.py --graph infra_2032
    uv run python scripts/verify_routing_graph.py --graph infra_2032 --against infra_2026
    uv run python scripts/verify_routing_graph.py --graph infra_2032 --url http://localhost:8991

Exits non-zero if any check fails, so it can gate the upload step.
"""

import argparse
import os
import sys

from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dev_env import load_env_files, resolve_service_url  # noqa: E402

# Repo-relative, like the compose bind mounts: one graph-cache-<key>/ per
# graph, hyphenated where the graph key is underscored.
_DOCKER_DIR = Path(__file__).resolve().parents[1] / "models/route/routing/docker"

_ROUTE_TIMEOUT_S = 120

# Station coordinates, lat/lon. The pairs below are the verification table
# in models/route/routing/README.md — keep the two in step.
_STATIONS = {
    "Berlin Hbf": (52.5251, 13.3694),
    "Wien Hbf": (48.1852, 16.3775),
    "Helsinki": (60.1719, 24.9414),
    "Tampere": (61.4986, 23.7735),
    "Stockholm C": (59.3300, 18.0585),
    "Kyiv-Pas": (50.4400, 30.4890),
    "Lviv": (49.8397, 24.0050),
    "Warszawa Centralna": (52.2288, 21.0033),
    "Dublin Heuston": (53.3465, -6.2947),
    "Cork Kent": (51.9018, -8.4610),
    "London Euston": (51.5282, -0.1337),
    "Madrid Chamartín": (40.4720, -3.6825),
    "Sevilla Santa Justa": (37.3919, -5.9750),
    "Perpignan": (42.6970, 2.8800),
    "Hamburg Hbf": (53.5528, 10.0067),
    "København H": (55.6727, 12.5641),
}

# (profile, origin, destination, must_route). The must_route=False rows are
# the gauge-tag test — see the module docstring.
_GAUGE_MATRIX = [
    ("night_train", "Berlin Hbf", "Wien Hbf", True),
    ("night_train", "Helsinki", "Tampere", False),
    ("night_train_1520", "Kyiv-Pas", "Lviv", True),
    ("night_train_1520", "Kyiv-Pas", "Warszawa Centralna", False),
    ("night_train_1520", "Helsinki", "Tampere", True),
    ("night_train_1520", "Helsinki", "Stockholm C", False),
    ("night_train_1600", "Dublin Heuston", "Cork Kent", True),
    ("night_train_1600", "Dublin Heuston", "London Euston", False),
    ("night_train_1668", "Madrid Chamartín", "Sevilla Santa Justa", True),
    ("night_train_1668", "Madrid Chamartín", "Perpignan", False),
]

_DEFAULT_CORRIDOR = ("Hamburg Hbf", "København H")


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


def graph_url(graph_key: str, override: str | None = None) -> str | None:
    """Where this host reaches one graph's routing engine.

    OPENRAILROUTING_URL_<KEY> wins, rewritten to localhost by dev_env when
    it names a compose service. A graph being verified usually has no URL
    yet — it is not registered until it passes — so the published port
    variable is the fallback that makes this script work pre-registration.
    """
    if override:
        return override.rstrip("/")
    load_env_files()
    key = graph_key.upper()
    port_var = f"OPENRAILROUTING_HOST_PORT_{key}"
    url = resolve_service_url(f"OPENRAILROUTING_URL_{key}", port_var)
    if url:
        return url.rstrip("/")
    port = os.environ.get(port_var)
    return f"http://localhost:{port}" if port else None


def cache_size_mb(graph_key: str) -> float | None:
    """Size of one graph's cache directory on disk, or None if absent."""
    directory = _DOCKER_DIR / f"graph-cache-{graph_key.replace('_', '-')}"
    if not directory.is_dir():
        return None
    total = sum(f.stat().st_size for f in directory.rglob("*") if f.is_file())
    return total / 1024 / 1024


# ---------------------------------------------------------------------------
# Routing engine calls
# ---------------------------------------------------------------------------


def fetch_info(url: str) -> dict:
    resp = requests.get(f"{url}/info", timeout=30)
    resp.raise_for_status()
    return resp.json()


def route(url: str, origin: str, destination: str, profile: str) -> dict | None:
    """One bare /route call. Returns the first path, or None when the
    engine reports no connection — which is a 400 here, not an exception."""
    params = [
        ("point", "{},{}".format(*_STATIONS[origin])),
        ("point", "{},{}".format(*_STATIONS[destination])),
        ("profile", profile),
        ("calc_points", "false"),
        ("instructions", "false"),
    ]
    resp = requests.get(f"{url}/route", params=params, timeout=_ROUTE_TIMEOUT_S)
    if resp.status_code != 200:
        return None
    paths = resp.json().get("paths") or []
    return paths[0] if paths else None


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_info(graph_key: str, url: str, against: tuple[str, str] | None) -> bool:
    """Profile lists identical across instances, bounding boxes reported."""
    print("\n[1] /info")
    info = fetch_info(url)
    profiles = sorted(p["name"] for p in info.get("profiles", []))
    print(f"  {graph_key:<12} bbox={info.get('bbox')}")
    print(f"  {'':<12} profiles={', '.join(profiles)}")

    if against is None:
        return True

    other_key, other_url = against
    other = fetch_info(other_url)
    other_profiles = sorted(p["name"] for p in other.get("profiles", []))
    print(f"  {other_key:<12} bbox={other.get('bbox')}")
    print(f"  {'':<12} profiles={', '.join(other_profiles)}")

    if profiles != other_profiles:
        print(
            "  FAIL  profile lists differ — every instance shares config.yml, "
            "so one of the two images or caches is out of step."
        )
        return False
    print("  ok    profile lists identical")
    return True


def check_gauge_matrix(url: str) -> bool:
    """Coverage (should route) and gauge-tag retention (should not)."""
    print("\n[2] gauge matrix")
    failures = 0
    for profile, origin, destination, must_route in _GAUGE_MATRIX:
        path = route(url, origin, destination, profile)
        routed = path is not None
        ok = routed is must_route
        failures += not ok
        detail = f"{path['distance'] / 1000:8.1f} km" if routed else "  no route"
        # "route" and "block" are both five characters, so the columns line
        # up without padding either.
        expectation = "route" if must_route else "block"
        pair = f"{origin} -> {destination}"
        print(
            f"  {'ok  ' if ok else 'FAIL'}  {profile:<17} {pair:<44} "
            f"expect {expectation}  {detail}"
        )
    if failures:
        print(
            f"  {failures} row(s) failed. A should-block row that routed means "
            "the gauge tags did not survive into this graph."
        )
    return failures == 0


def check_corridor(
    url: str, against: tuple[str, str] | None, corridor: tuple[str, str]
) -> bool:
    """One relation on both graphs — the upgrade either shows or it does not."""
    origin, destination = corridor
    print(f"\n[3] corridor  {origin} -> {destination}  (profile night_train)")
    path = route(url, origin, destination, "night_train")
    if path is None:
        print("  FAIL  no route on the graph under test")
        return False
    print(
        f"  target   {path['distance'] / 1000:8.1f} km  {path['time'] / 60000:6.0f} min"
    )

    if against is None:
        return True

    other_key, other_url = against
    other = route(other_url, origin, destination, "night_train")
    if other is None:
        print(f"  note     no route on {other_key} — nothing to compare")
        return True
    print(
        f"  {other_key:<9}{other['distance'] / 1000:8.1f} km  "
        f"{other['time'] / 60000:6.0f} min"
    )
    delta_km = (path["distance"] - other["distance"]) / 1000
    delta_min = (path["time"] - other["time"]) / 60000
    print(f"  delta    {delta_km:+8.1f} km  {delta_min:+6.0f} min")
    if abs(delta_km) < 1.0:
        print(
            "  note     the two graphs route this corridor identically — expected "
            "only if the upgrade does not touch it."
        )
    return True


def check_cache_size(graph_key: str, against_key: str | None) -> bool:
    """Reported, never asserted: the acceptable range is a judgement call
    that depends on what the upgrade added."""
    print("\n[4] graph cache on disk")
    for key in [graph_key] + ([against_key] if against_key else []):
        size = cache_size_mb(key)
        print(f"  {key:<12} " + (f"{size:8.0f} MB" if size else "     absent"))
    return True


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[3])
    parser.add_argument(
        "--graph", required=True, help="graph key under test, e.g. infra_2032"
    )
    parser.add_argument("--against", help="graph key to compare with, e.g. infra_2026")
    parser.add_argument("--url", help="override the URL of the graph under test")
    parser.add_argument(
        "--against-url", help="override the URL of the comparison graph"
    )
    parser.add_argument(
        "--corridor",
        nargs=2,
        metavar=("ORIGIN", "DESTINATION"),
        default=_DEFAULT_CORRIDOR,
        help=f"station names for check 3 (default: {' -> '.join(_DEFAULT_CORRIDOR)})",
    )
    args = parser.parse_args()

    unknown = [s for s in args.corridor if s not in _STATIONS]
    if unknown:
        print(f"Unknown station(s): {', '.join(unknown)}")
        print(f"Known: {', '.join(sorted(_STATIONS))}")
        return 2

    url = graph_url(args.graph, args.url)
    if url is None:
        print(
            f"No URL for graph '{args.graph}'. Set OPENRAILROUTING_URL_{args.graph.upper()} "
            f"or OPENRAILROUTING_HOST_PORT_{args.graph.upper()} in backend/docker/.env, "
            "or pass --url."
        )
        return 2

    against = None
    if args.against:
        against_url = graph_url(args.against, args.against_url)
        if against_url is None:
            print(f"No URL for comparison graph '{args.against}'.")
            return 2
        against = (args.against, against_url)

    print(f"Verifying {args.graph} at {url}")
    if against:
        print(f"  against {against[0]} at {against[1]}")

    try:
        results = [
            check_info(args.graph, url, against),
            check_gauge_matrix(url),
            check_corridor(url, against, tuple(args.corridor)),
            check_cache_size(args.graph, args.against),
        ]
    except requests.RequestException as exc:
        print(f"\nRouting engine unreachable: {exc}")
        return 2

    passed = all(results)
    print(
        "\nPASS — graph accepted."
        if passed
        else "\nFAIL — do not upload this graph yet."
    )
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
