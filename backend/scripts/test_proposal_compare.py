"""
test_proposal_compare.py
=========================
Manual test script for the WP9 compare contract:

  POST /api/proposals/compare  — two proposal-anchored sides, optional
                                  scenario_id/composition_id overrides,
                                  diff = side B minus side A (§7.3)

Two phases:

  seed   Publishes the two anchor proposals the demos compare (same
         corridor, two compositions), named "MANUAL_TEST_COMPARE <label>"
         — idempotent by name, same convention as
         test_proposals_gallery.py: a rerun finds each name in the
         gallery and reuses it. Pass --force to republish anyway.
  demo   Runs one representative compare per side kind — stored vs
         stored (cross-proposal), scenario override (against the first
         historical scenario the API lists), composition override — and
         prints a compact summary of each: published flags, route
         context, and the headline summary-KPI deltas. Full raw
         responses are written to scripts/data/proposal_compare_
         <label>.json. Assumes `seed` has already run at least once.

Usage:
    python scripts/test_proposal_compare.py [command] [--force]

    command : seed | demo | all (default: all)
    --force : (seed only) republish the anchors even if same-named ones
              already exist in the gallery

Pre-flight:
  1. Checks Flask API is reachable
  2. Checks OpenRailRouting is running; starts it if not (seed publishes
     and the override demos compute live, so both phases route)

Note: seeding publishes proposals.proposals rows under a fresh guest
user — not test-isolated the way tests/test_54_proposal_compare_api.py
is. Rows are named so they're easy to purge manually
(DELETE FROM proposals.proposals WHERE name LIKE 'MANUAL_TEST_COMPARE%').
"""

import argparse
import json
import os
import subprocess
import sys
import time

import requests

API_BASE = os.environ.get("API_BASE_URL", "http://localhost:5050")
ROUTING_URL = "http://localhost:8989"
CONTAINER_NAME = "openrailrouting"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "data")

NAME_PREFIX = "MANUAL_TEST_COMPARE "

_STOPS = ["DE_BERLIN_HBF", "AT_WIEN_HBF"]

SEED_ANCHORS = [
    {"label": "Berlin – Wien (Balkan Standard)", "composition_id": "NEW-BAL-7"},
    {"label": "Berlin – Wien (Balkan Refurb)", "composition_id": "REF-BAL-9"},
]

# The headline KPIs the demo prints per compare — a readable subset of
# the full diff.summary the endpoint returns.
_HEADLINE_KPIS = (
    "cost_eur_per_train_km",
    "revenue_eur_per_train_km",
    "margin_eur_per_train_km",
    "subsidy_eur_per_year",
)


# =============================================================================
# PRE-FLIGHT CHECKS
# =============================================================================


def check_flask():
    print("[ ] Checking Flask API...")
    try:
        r = requests.get(f"{API_BASE}/api/health", timeout=3)
        if r.status_code == 200:
            print("[✓] Flask API is running.")
            return True
    except requests.ConnectionError:
        pass
    print(
        f"[✗] Flask API not reachable at {API_BASE}. Start it with: uv run python main.py"
    )
    return False


def ensure_routing_running():
    print("[ ] Checking OpenRailRouting...")
    try:
        r = requests.get(f"{ROUTING_URL}/health", timeout=3)
        if r.status_code == 200:
            print("[✓] OpenRailRouting is running.")
            return True
    except requests.ConnectionError:
        pass

    print(f"[ ] OpenRailRouting not running — starting container '{CONTAINER_NAME}'...")
    result = subprocess.run(
        ["docker", "start", CONTAINER_NAME], capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"[✗] Failed to start container: {result.stderr.strip()}")
        return False

    print("[ ] Waiting for OpenRailRouting to be ready...")
    for i in range(30):
        time.sleep(2)
        try:
            r = requests.get(f"{ROUTING_URL}/health", timeout=2)
            if r.status_code == 200:
                print("[✓] OpenRailRouting is ready.")
                return True
        except requests.ConnectionError:
            pass
        print(f"    ...waiting ({(i + 1) * 2}s)")

    print("[✗] OpenRailRouting did not become ready in time.")
    return False


# =============================================================================
# SEED
# =============================================================================


def _guest_session(max_attempts: int = 3) -> dict:
    """One guest session for the seeding run — retries on 429 (POST
    /api/auth/guest is rate-limited)."""
    for attempt in range(1, max_attempts + 1):
        r = requests.post(f"{API_BASE}/api/auth/guest", timeout=10)
        if r.status_code == 200:
            body = r.json()
            print(
                f"[✓] Guest session: user_id={body['user_id']} ({body['display_name']})"
            )
            return {"headers": {"Authorization": f"Bearer {body['token']}"}}
        if r.status_code == 429 and attempt < max_attempts:
            print("[ ] Guest endpoint rate-limited — retrying in 5s...")
            time.sleep(5)
            continue
        r.raise_for_status()
    raise RuntimeError("Could not obtain a guest session.")


def _find_seeded(name: str) -> int | None:
    """proposal_id of an exact-named gallery row, or None — same
    exact-match-narrowing as test_proposals_gallery.py (the `name`
    filter is a substring match)."""
    resp = requests.post(
        f"{API_BASE}/api/proposals",
        json={"filter": {"name": name}, "include": ["summaries"]},
        timeout=15,
    )
    resp.raise_for_status()
    for p in resp.json()["summaries"]["proposals"]:
        if p["name"] == name:
            return p["proposal_id"]
    return None


def seed(force: bool = False) -> list[int]:
    print("\n" + "=" * 60)
    print("  SEED — publishing the two compare anchors")
    print("=" * 60)

    session = None
    proposal_ids = []
    for anchor in SEED_ANCHORS:
        name = NAME_PREFIX + anchor["label"]
        existing = None if force else _find_seeded(name)
        if existing is not None:
            print(f"[=] Already seeded: {name} (proposal_id={existing})")
            proposal_ids.append(existing)
            continue

        if session is None:
            session = _guest_session()

        print(f"[ ] Computing + publishing: {name} ...")
        calc = requests.post(
            f"{API_BASE}/api/proposal/calc",
            json={"stops": _STOPS, "composition_id": anchor["composition_id"]},
            timeout=180,
        )
        calc.raise_for_status()
        pub = requests.post(
            f"{API_BASE}/api/proposal/publish",
            json={
                "compute_request": calc.json()["request"],
                "name": name,
                "mode": "new",
            },
            headers=session["headers"],
            timeout=120,
        )
        pub.raise_for_status()
        proposal_id = pub.json()["proposal_id"]
        print(f"[✓] Published proposal_id={proposal_id}")
        proposal_ids.append(proposal_id)
    return proposal_ids


# =============================================================================
# DEMO
# =============================================================================


def _historical_scenario_id() -> int | None:
    resp = requests.get(f"{API_BASE}/api/scenarios", timeout=15)
    resp.raise_for_status()
    historical = resp.json()["historical_scenarios"]["scenarios"]
    return historical[0]["scenario_id"] if historical else None


def _run_compare(label: str, sides: list[dict]) -> None:
    print(f"\n--- {label} ---")
    print(f"    sides: {json.dumps(sides)}")
    resp = requests.post(
        f"{API_BASE}/api/proposals/compare", json={"sides": sides}, timeout=300
    )
    if resp.status_code != 200:
        print(f"[✗] {resp.status_code}: {resp.text[:300]}")
        return
    body = resp.json()

    for i, side in enumerate(body["sides"]):
        tag = "stored" if side["published"] else f"computed {side['overrides']}"
        print(
            f"    side {i}: proposal_id={side['proposal_id']} ({tag}), "
            f"composition={side['summary']['composition_id']}, "
            f"scenario={side['summary']['scenario_id']}"
        )
    context = body["route_context"]
    print(
        f"    route_identical={context['route_identical']}, "
        f"differing_request_fields={context['differing_request_fields']}"
    )
    for kpi in _HEADLINE_KPIS:
        leaf = body["diff"]["summary"].get(kpi)
        if leaf is None:
            continue
        rel = f"{leaf['rel'] * 100:+.1f}%" if leaf["rel"] is not None else "n/a"
        print(f"    Δ {kpi}: {leaf['abs']:+.2f} ({rel})  [{leaf['a']} → {leaf['b']}]")
    unmatched = body["diff"]["views_unmatched"]
    if unmatched["a_only"] or unmatched["b_only"]:
        print(
            f"    views_unmatched: a_only={len(unmatched['a_only'])}, "
            f"b_only={len(unmatched['b_only'])} paths"
        )

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filename = os.path.join(
        OUTPUT_DIR, f"proposal_compare_{label.lower().replace(' ', '_')}.json"
    )
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(body, f, indent=2, ensure_ascii=False)
    print(f"    full response -> {filename}")


def demo():
    print("\n" + "=" * 60)
    print("  DEMO — POST /api/proposals/compare")
    print("=" * 60)

    anchor_ids = [
        _find_seeded(NAME_PREFIX + anchor["label"]) for anchor in SEED_ANCHORS
    ]
    if any(pid is None for pid in anchor_ids):
        print("[✗] Seed anchors missing — run the seed phase first.")
        return
    anchor_a, anchor_b = anchor_ids

    _run_compare(
        "stored vs stored",
        [{"proposal_id": anchor_a}, {"proposal_id": anchor_b}],
    )

    historical_id = _historical_scenario_id()
    if historical_id is not None:
        _run_compare(
            "scenario override",
            [
                {"proposal_id": anchor_a},
                {"proposal_id": anchor_a, "scenario_id": historical_id},
            ],
        )
    else:
        print("\n--- scenario override --- skipped (no historical scenario seeded)")

    _run_compare(
        "composition override",
        [
            {"proposal_id": anchor_a},
            {
                "proposal_id": anchor_a,
                "composition_id": SEED_ANCHORS[1]["composition_id"],
            },
        ],
    )


# =============================================================================
# MAIN
# =============================================================================


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", nargs="?", default="all", choices=["seed", "demo", "all"]
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if not check_flask():
        sys.exit(1)
    if args.command in ("seed", "all", "demo") and not ensure_routing_running():
        sys.exit(1)

    if args.command in ("seed", "all"):
        seed(force=args.force)
    if args.command in ("demo", "all"):
        demo()


if __name__ == "__main__":
    main()
