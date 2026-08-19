"""
test_proposals_gallery.py
==========================
Manual test script for the WP6 gallery/map contract:

  POST /api/proposals  — the full §7.1 filter/sort/include contract

Two phases:

  seed   Publishes 10 diverse example proposals (varied corridors,
         compositions, countries, distances) so the gallery/map demos
         below have something interesting to filter/sort/group. Each
         seeded proposal is named "MANUAL_TEST_GALLERY <label>" —
         idempotent by name: a rerun checks the gallery for each name
         first and skips any that already exist, so repeated runs don't
         pile up duplicates. Pass --force to republish everything anyway.
  demo   Runs one representative POST /api/proposals call per filter/
         sort/include kind (range, list, substring, array-overlap,
         trip_windows, bbox, sort, each map_* section, the sources=
         validation error) and prints a compact summary of each. Full
         raw responses are written to scripts/data/proposals_gallery_
         <label>.json; every geospatial section (map_lines, map_stop_
         counts, map_country_counts) also gets its own companion
         scripts/data/proposals_gallery_<label>_<section>.geojson,
         ready to drag into QGIS — map_lines/map_country_counts are
         already GeoJSON on the wire and written as-is, map_stop_counts
         (a flat [{stop_id, lat, lon, n}] list on the wire, §7.1) is
         converted to a Point FeatureCollection here. Assumes `seed` has
         already run at least once.

Usage:
    python scripts/test_proposals_gallery.py [command] [--force]

    command : seed | demo | all (default: all)
    --force : (seed only) republish every seed proposal even if a
              same-named one already exists in the gallery

Pre-flight:
  1. Checks Flask API is reachable
  2. Loads data if not already loaded
  3. Checks OpenRailRouting is running; starts it if not (seed only)

Note: seeding actually publishes proposals.proposals rows under a fresh
guest user each run that seeds anything — not test-isolated the way
tests/test_52_proposals_gallery_api.py is. Rows are named/tagged so
they're easy to find and purge manually afterwards if needed
(DELETE FROM proposals.proposals WHERE name LIKE 'MANUAL_TEST_GALLERY%').
"""

import argparse
import json
import os
import subprocess
import sys
import time

from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dev_env import api_base_url, routing_base_url  # noqa: E402

API_BASE = api_base_url()
ROUTING_URL = routing_base_url()
CONTAINER_NAME = "openrailrouting"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "data")

NAME_PREFIX = "MANUAL_TEST_GALLERY "

# Real, known-good corridors reused from the existing test/script fixtures
# (tests/conftest.py's STOPS_* / scripts/test_scenario_comparison_paris_berlin.py
# / scripts/test_timetable_comparison_hamburg_copenhagen.py) — every stop_id
# here is already exercised elsewhere, so routing is expected to succeed.
_BERLIN_WIEN = ["osm:n3856100103", "osm:w423692233"]
_BERLIN_DRESDEN_WIEN = ["osm:n3856100103", "osm:n25397500", "osm:w423692233"]
_BERLIN_ZUERICH_WIEN = ["osm:n3856100103", "osm:n1236383343", "osm:w423692233"]
_PARIS_BERLIN = [
    "osm:n2506241285",
    "osm:n17401552",
    "osm:n2459919677",
    "osm:n3856100103",
]
_MUENCHEN_COPENHAGEN = [
    "osm:n2470201868",
    "osm:n3856100103",
    "osm:n2459919677",
    "osm:n3739700410",
]

# 10 combinations spanning 6 countries (DE, AT, CH, FR, BE, DK), a wide
# distance range (~680km Berlin-Wien to ~1700km Paris-Berlin-detour), and
# 5 composition types — enough spread for every filter/sort/map demo below
# to return a meaningfully different result each time.
SEED_PROPOSALS = [
    {
        "label": "Berlin – Wien (Balkan Standard)",
        "stops": _BERLIN_WIEN,
        "composition_id": "NEW-BAL-7",
    },
    {
        "label": "Berlin – Wien (Balkan Refurb)",
        "stops": _BERLIN_WIEN,
        "composition_id": "REF-BAL-9",
    },
    {
        "label": "Berlin – Wien (Budget Refurb)",
        "stops": _BERLIN_WIEN,
        "composition_id": "REF-BUD-6",
    },
    {
        "label": "Berlin – Wien via Dresden (Balkan Standard)",
        "stops": _BERLIN_DRESDEN_WIEN,
        "composition_id": "NEW-BAL-7",
    },
    {
        "label": "Berlin – Wien via Zürich (Balkan Standard)",
        "stops": _BERLIN_ZUERICH_WIEN,
        "composition_id": "NEW-BAL-7",
    },
    {
        "label": "Berlin – Wien via Zürich (Premium Refurb)",
        "stops": _BERLIN_ZUERICH_WIEN,
        "composition_id": "REF-PREM-12",
    },
    {
        "label": "Paris – Berlin via Brussels/Hamburg (Balkan Standard)",
        "stops": _PARIS_BERLIN,
        "composition_id": "NEW-BAL-7",
    },
    {
        "label": "Paris – Berlin via Brussels/Hamburg (Budget Refurb)",
        "stops": _PARIS_BERLIN,
        "composition_id": "REF-BUD-6",
    },
    {
        "label": "München – Copenhagen via Berlin/Hamburg (Balkan Standard)",
        "stops": _MUENCHEN_COPENHAGEN,
        "composition_id": "NEW-BAL-7",
    },
    {
        "label": "München – Copenhagen via Berlin/Hamburg (Balkan Large)",
        "stops": _MUENCHEN_COPENHAGEN,
        "composition_id": "NEW-BAL-14",
    },
]


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


def ensure_data_loaded():
    print("[ ] Checking data status...")
    r = requests.get(f"{API_BASE}/api/data/status")
    status = r.json()

    if status.get("loaded"):
        print(f"[✓] Data already loaded at {status.get('loaded_at')}.")
        return True

    print("[ ] Data not loaded — loading now...")
    r = requests.post(f"{API_BASE}/api/data/load")
    result = r.json()

    if r.status_code == 200:
        print(f"[✓] Data loaded at {result.get('loaded_at')}.")
        return True
    else:
        print(f"[✗] Data load failed: {result.get('message')}")
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
    """One guest session for the whole seeding run — every seeded
    proposal is published under this single guest user. Retries on 429
    (POST /api/auth/guest is rate-limited)."""
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


def _name_already_seeded(name: str) -> bool:
    """Exact-name check against the gallery — POST /api/proposals'
    `name` filter is a substring match, so this narrows client-side to an
    exact match rather than trusting the substring alone (a shorter seed
    name could otherwise substring-match a longer one)."""
    resp = requests.post(
        f"{API_BASE}/api/proposals",
        json={"filter": {"name": name}, "include": ["summaries"]},
        timeout=15,
    )
    resp.raise_for_status()
    return any(p["name"] == name for p in resp.json()["summaries"]["proposals"])


def seed(force: bool = False):
    print("\n" + "=" * 60)
    print("  SEED — publishing example proposals")
    print("=" * 60)

    to_seed = (
        SEED_PROPOSALS
        if force
        else [
            spec
            for spec in SEED_PROPOSALS
            if not _name_already_seeded(NAME_PREFIX + spec["label"])
        ]
    )
    skipped = len(SEED_PROPOSALS) - len(to_seed)
    if skipped:
        print(f"[ ] {skipped} already seeded — skipping (use --force to republish).")
    if not to_seed:
        print("[✓] Nothing to seed.")
        return

    headers = _guest_session()["headers"]

    published, failed = [], []
    for i, spec in enumerate(to_seed, start=1):
        name = NAME_PREFIX + spec["label"]
        print(f"\n[{i}/{len(to_seed)}] {name}")
        print(f"    stops={spec['stops']}  composition={spec['composition_id']}")
        try:
            calc = requests.post(
                f"{API_BASE}/api/proposal/calc",
                json={"stops": spec["stops"], "composition_id": spec["composition_id"]},
                timeout=120,
            )
            calc.raise_for_status()
            resp = requests.post(
                f"{API_BASE}/api/proposal/publish",
                json={
                    "compute_request": calc.json()["request"],
                    "name": name,
                    "mode": "new",
                },
                headers=headers,
                timeout=60,
            )
            resp.raise_for_status()
            body = resp.json()
            print(f"    [✓] proposal_id={body['proposal_id']}")
            published.append(body["proposal_id"])
        except requests.HTTPError as e:
            print(f"    [✗] failed: {e.response.status_code} {e.response.text[:200]}")
            failed.append(name)

    print(f"\n[✓] Published {len(published)}/{len(to_seed)}.")
    if failed:
        print(f"[✗] Failed: {failed}")


# =============================================================================
# DEMO — one representative call per filter/sort/include kind
# =============================================================================


def _run(label: str, **body):
    """POST /api/proposals, print a compact summary, write the full
    response to scripts/data/proposals_gallery_<label>.json."""
    print(f"\n--- {label} ---")
    print(f"    body: {json.dumps(body)}")
    resp = requests.post(f"{API_BASE}/api/proposals", json=body, timeout=15)
    print(f"    status: {resp.status_code}")

    result = resp.json()
    if resp.status_code != 200:
        print(f"    {result}")
        return

    if "summaries" in result:
        s = result["summaries"]
        print(f"    summaries: total={s['total']}, page={len(s['proposals'])}")
        for p in s["proposals"]:
            print(
                f"      #{p['proposal_id']:<4} {p['name']:<55} "
                f"{p['total_distance_km']:>7.1f} km  likes={p['likes_count']}  {p['countries']}"
            )
    if "map_lines" in result:
        features = result["map_lines"]["features"]
        print(f"    map_lines: {len(features)} corridor(s)")
        for f in sorted(features, key=lambda ft: -ft["properties"]["proposal_count"])[
            :5
        ]:
            props = f["properties"]
            print(
                f"      {props['stop_a']:<20} <-> {props['stop_b']:<20} "
                f"proposal_count={props['proposal_count']} "
                f"proposal_ids={props['proposal_ids']} "
                f"avg_margin={props['avg_margin_eur_per_train_km']}"
            )
    if "map_stop_counts" in result:
        print(f"    map_stop_counts: {len(result['map_stop_counts'])} stop(s)")
        for row in sorted(result["map_stop_counts"], key=lambda r: -r["n"])[:5]:
            print(f"      {row['stop_id']:<20} n={row['n']}")
    if "map_country_counts" in result:
        features = result["map_country_counts"]["features"]
        print(f"    map_country_counts: {len(features)} countr(y/ies)")
        for f in sorted(features, key=lambda ft: -ft["properties"]["n"]):
            has_geom = f["geometry"] is not None
            print(
                f"      {f['properties']['country']:<4} n={f['properties']['n']:<3} "
                f"geometry={'yes' if has_geom else 'MISSING'}"
            )

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, f"proposals_gallery_{label}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    written = [path]
    written += _write_geojson_sections(label, result)
    if len(written) > 1:
        print(f"    wrote {len(written)} file(s): {', '.join(written)}")


def _write_geojson_sections(label: str, result: dict) -> list[str]:
    """Alongside the raw .json, drop a ready-to-drag-into-QGIS .geojson
    for every geospatial section present — same convention as
    test_proposal_calc.py's lines/stops .geojson outputs, so everything
    from this project loads into one QGIS project consistently.
    map_lines/map_country_counts are already GeoJSON FeatureCollections
    (written as-is); map_stop_counts is a plain [{stop_id, lat, lon, n}]
    list, converted to a Point FeatureCollection here since it isn't one
    on the wire (§7.1 keeps it a flat list — cheaper for a frontend that
    just wants to plot markers without parsing GeoJSON geometry)."""
    written = []

    for section in ("map_lines", "map_country_counts"):
        if section not in result:
            continue
        path = os.path.join(OUTPUT_DIR, f"proposals_gallery_{label}_{section}.geojson")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result[section], f, indent=2, ensure_ascii=False)
        written.append(path)

    if "map_stop_counts" in result:
        path = os.path.join(
            OUTPUT_DIR, f"proposals_gallery_{label}_map_stop_counts.geojson"
        )
        feature_collection = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [row["lon"], row["lat"]],
                    },
                    "properties": {"stop_id": row["stop_id"], "n": row["n"]},
                }
                for row in result["map_stop_counts"]
                if row["lat"] is not None and row["lon"] is not None
            ],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(feature_collection, f, indent=2, ensure_ascii=False)
        written.append(path)

    return written


def _seed_some_likes(n: int = 3):
    """Likes the first `n` seeded MANUAL_TEST_GALLERY proposals (liking
    is idempotent per-caller, so a rerun just no-ops) so the likes_count
    demos below have something to show. Needs its own guest session —
    liking requires auth, same TRUST_GUEST floor as publish."""
    resp = requests.post(
        f"{API_BASE}/api/proposals",
        json={"filter": {"name": NAME_PREFIX.strip()}, "limit": n},
        timeout=15,
    )
    resp.raise_for_status()
    proposals = resp.json()["summaries"]["proposals"]
    if not proposals:
        print("[ ] No seeded proposals found to like — run `seed` first.")
        return

    headers = _guest_session()["headers"]
    for p in proposals:
        r = requests.post(
            f"{API_BASE}/api/proposal/{p['proposal_id']}/likes",
            headers=headers,
            timeout=10,
        )
        if r.status_code == 200:
            print(
                f"[✓] Liked proposal_id={p['proposal_id']} ({r.json()['count']} like(s))"
            )
        else:
            print(f"[✗] Could not like proposal_id={p['proposal_id']}: {r.status_code}")


def demo():
    print("\n" + "=" * 60)
    print("  DEMO — POST /api/proposals, one call per filter/sort/include kind")
    print("=" * 60)

    _seed_some_likes()

    _run("baseline_all")

    # --- range filter ---
    _run("range_short_corridors", filter={"total_distance_km": {"max": 900}})
    _run("range_long_corridors", filter={"total_distance_km": {"min": 1200}})

    # --- list filter ---
    _run("list_composition_ids", filter={"composition_ids": ["NEW-BAL-7"]})

    # --- substring filter ---
    _run("substring_name", filter={"name": "wien"})

    # --- array-overlap filters (mode "any"/OR — the default) ---
    _run("array_overlap_countries", filter={"countries": ["DK"]})
    _run("array_overlap_stop_ids", filter={"stop_ids": ["osm:n3856100103"]})

    # --- array filter mode "all"/AND — every listed country must be
    # touched; München-Copenhagen crosses DE and DK, so "all" over
    # [DE, DK] should still match it, but [DE, FR] should not ---
    _run(
        "array_all_mode_de_dk",
        filter={"countries": {"values": ["DE", "DK"], "mode": "all"}},
    )
    _run(
        "array_all_mode_de_fr_no_match",
        filter={"countries": {"values": ["DE", "FR"], "mode": "all"}},
    )

    # --- proposal_ids filter ---
    _run("list_proposal_ids", filter={"proposal_ids": [1]})

    # --- created_at / updated_at range filters ---
    _run(
        "created_at_since_epoch",
        filter={"created_at": {"min": "2020-01-01T00:00:00+00:00"}},
    )
    _run(
        "updated_at_future_empty",
        filter={"updated_at": {"min": "2099-01-01T00:00:00+00:00"}},
    )

    # --- likes_count (live-joined from proposals.likes, see _seed_some_likes) ---
    _run("likes_count_at_least_one", filter={"likes_count": {"min": 1}})
    _run("sort_by_likes_count_desc", sort=[{"by": "likes_count", "dir": "desc"}])

    # --- trip_windows: a deliberately wide window (any Berlin departure
    # in the evening) so it matches something regardless of the exact
    # timetable a given seed run produced ---
    _run(
        "trip_windows_evening_berlin_departure",
        filter={
            "trip_windows": [
                {
                    "stop_id": "osm:n3856100103",
                    "departure": {"from": "18:00", "to": "23:59"},
                }
            ]
        },
    )
    _run(
        "trip_windows_no_match",
        filter={
            "trip_windows": [
                {
                    "stop_id": "osm:n3856100103",
                    "departure": {"from": "03:00", "to": "03:01"},
                }
            ]
        },
    )

    # --- bbox ---
    _run("bbox_dach_region", filter={"bbox": [8.0, 45.0, 20.0, 55.0]})
    _run("bbox_south_atlantic_empty", filter={"bbox": [-40.0, -40.0, -30.0, -30.0]})

    # --- sort ---
    _run("sort_margin_desc", sort=[{"by": "margin_eur_per_train_km", "dir": "desc"}])
    _run("sort_distance_asc", sort=[{"by": "total_distance_km", "dir": "asc"}])

    # --- pagination / windowed total ---
    _run("pagination_page_1", limit=3, offset=0)
    _run("pagination_page_2", limit=3, offset=3)

    # --- map sections ---
    _run("include_map_lines", include=["map_lines"])
    _run("include_map_stop_counts", include=["map_stop_counts"])
    _run("include_map_country_counts", include=["map_country_counts"])
    _run(
        "include_everything",
        include=["summaries", "map_lines", "map_stop_counts", "map_country_counts"],
    )

    # --- validation: sources=["existing"] is WP10, not implemented yet ---
    _run("sources_existing_rejected", filter={"sources": ["existing"]})

    # --- validation: version/scenario filters were removed in WP6.1 ---
    _run("scenario_id_filter_rejected", filter={"scenario_ids": [1]})

    print(f"\n[✓] Full responses written to {OUTPUT_DIR}/proposals_gallery_*.json")


# =============================================================================
# MAIN
# =============================================================================


def parse_args():
    parser = argparse.ArgumentParser(
        description="Manual test script for the WP6 gallery/map API."
    )
    parser.add_argument(
        "command", nargs="?", default="all", choices=["seed", "demo", "all"]
    )
    parser.add_argument(
        "--force", action="store_true", help="(seed only) republish everything"
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    print("=" * 60)
    print("  Night Train — proposals gallery/map API test")
    print("=" * 60)

    if not check_flask():
        sys.exit(1)
    if not ensure_data_loaded():
        sys.exit(1)

    if args.command in ("seed", "all"):
        if not ensure_routing_running():
            sys.exit(1)
        seed(force=args.force)

    if args.command in ("demo", "all"):
        demo()
