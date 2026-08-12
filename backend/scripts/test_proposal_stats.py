"""
test_proposal_stats.py
=======================
Manual test script for the proposal statistics endpoint:

  GET /api/proposals/stats  — §7.7 counts, KPI aggregates, top/flop
                              countries and country-to-country relations

Prints a readable report rather than asserting: this is the script you
run after a fresh `docker compose up` to see whether the numbers look
like the database you think you have. The pytest suite
(tests/test_55_proposal_stats_api.py) owns the assertions.

What it checks, in order:

  relations  Is input_params.country_relations populated for the current
             base stop snapshot? Prints the reference stations, the size
             of the candidate set, and how many pairs were dropped as
             too far or unroutable. An empty universe here is the single
             most likely reason the relation rankings look wrong, and it
             almost always means scripts/build_country_relations.py has
             not run against a live router.
  counts     Row counts and network reach per source, cross-checked
             against POST /api/proposals' own total for the same filter
             — the two must agree, since both read the same gallery.
  kpis       The aggregate block per scope, with a reminder printed
             against every rate column that `avg` is the mean across
             proposals, not a network rate.
  countries  Top and flop, with the zero-count tail called out.
  by_user    The same report narrowed to one user_id, to confirm the
             narrowing actually narrows (and that existing trains drop
             out, since they have no owner).

Usage:
    python scripts/test_proposal_stats.py [command] [--user-id N]

    command   : relations | counts | kpis | countries | by_user | all
                (default: all)
    --user-id : which user the by_user section reports on; defaults to
                the user owning the most proposals in the gallery

The full response is written to scripts/data/proposal_stats_output.json
(and proposal_stats_user_<id>_output.json for the narrowed one) so it can
be diffed between runs.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dev_env import api_base_url  # noqa: E402

API_BASE = api_base_url()
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "data")

STATS_URL = f"{API_BASE}/api/proposals/stats"
PROPOSALS_URL = f"{API_BASE}/api/proposals"

# Rate columns: a mean over these is a mean of ratios, which is not the
# same thing as the ratio over the whole set. Flagged in the printout so
# the number is never read as a network figure — that question belongs
# to the parked analyze endpoint.
_RATE_COLUMNS = {
    "avg_speed_kmh",
    "cost_eur_per_train_km",
    "revenue_eur_per_train_km",
    "margin_eur_per_train_km",
    "subsidy_eur_per_t_co2",
    "co2_g_per_pax_km",
}


def _header(title: str) -> None:
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


def _check_api() -> None:
    try:
        response = requests.get(f"{API_BASE}/api/health", timeout=3)
        response.raise_for_status()
    except Exception as e:
        sys.exit(f"API not reachable at {API_BASE} ({e}). Is the stack up?")


def fetch_stats(user_id: int | None = None) -> dict:
    params = {"user_id": user_id} if user_id is not None else {}
    response = requests.get(STATS_URL, params=params, timeout=30)
    if response.status_code != 200:
        sys.exit(
            f"GET /api/proposals/stats → {response.status_code}: {response.text[:400]}"
        )
    return response.json()


def _write(payload: dict, filename: str) -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    print(f"\n  full response → {path}")


# =============================================================================
# Sections
# =============================================================================


def show_relations(stats: dict) -> None:
    _header("RELATION UNIVERSE  (input_params.country_relations)")
    block = stats["country_relations"]
    universe, basis = block["universe"], block["basis"]

    print(f"  reference          {basis['reference']}")
    print(
        f"  distance           {basis['distance']}, ceiling {basis['max_relation_km']:.0f} km"
    )
    print(f"  built at           {basis['built_at']}")
    print(
        f"  candidate set      {universe['n_pairs']} pairs "
        f"over {universe['n_countries']} countries"
    )
    print(f"  dropped, too far   {universe['excluded_over_threshold']}")
    print(f"  dropped, no rail   {universe['excluded_unroutable']}")
    if universe["unresolved_countries"]:
        print(
            "  no ref. station    "
            + ", ".join(universe["unresolved_countries"])
            + "  (touched by rows, but not in the stop catalog yet)"
        )

    if not universe["n_pairs"]:
        print(
            "\n  !! The candidate set is EMPTY. Run, with the router up:\n"
            "     docker exec night-train-api python /app/scripts/build_country_relations.py"
        )
        return

    print("\n  reference stations:")
    for country, station in sorted(block["reference_stations"].items()):
        print(f"    {country}  {station['stop_name']}  ({station['stop_id']})")

    print("\n  TOP relations (most served):")
    _print_relations(block["top"])
    print("\n  FLOP relations (nearest unserved first):")
    _print_relations(block["flop"])


def _print_relations(rows: list[dict]) -> None:
    if not rows:
        print("    (none)")
        return
    for row in rows:
        print(
            f"    {row['country_a']}-{row['country_b']}  "
            f"{row['rail_km']:7.0f} km / {row['rail_time_h']:5.1f} h   "
            f"proposals={row['n_proposals']:3d}  existing={row['n_existing']:3d}  "
            f"total={row['n']:3d}"
        )


def show_counts(stats: dict, user_id: int | None = None) -> None:
    _header("COUNTS")
    for scope, counts in stats["counts"].items():
        print(
            f"  {scope:9s}  rows={counts['n']:4d}  "
            f"stops={counts['n_distinct_stops']:4d}  "
            f"countries={counts['n_distinct_countries']:3d}"
        )

    # Cross-check against the gallery: both read the same union, so a
    # disagreement means the two are filtering differently — worth
    # catching here rather than in a dashboard.
    body = {"include": ["summaries"], "limit": 1}
    if user_id is not None:
        body["filter"] = {"user_ids": [user_id], "sources": ["proposal"]}
    gallery_total = requests.post(PROPOSALS_URL, json=body, timeout=30).json()[
        "summaries"
    ]["total"]
    combined = stats["counts"]["all"]["n"]
    verdict = "OK" if gallery_total == combined else "MISMATCH"
    print(f"\n  gallery total={gallery_total}, stats all={combined}  → {verdict}")


def show_kpis(stats: dict) -> None:
    _header("KPI AGGREGATES")
    for scope, block in stats["kpis"].items():
        print(f"\n  --- {scope} ({len(block)} columns) ---")
        if not block:
            print("    (no rows in this scope)")
            continue
        for column, entry in block.items():
            note = (
                "   [mean of per-route rates, not a network rate]"
                if column in _RATE_COLUMNS
                else ""
            )
            total = f"  sum={entry['sum']:,.1f}" if "sum" in entry else ""
            print(
                f"    {column:28s} n={entry['n']:4d}  avg={entry['avg']:12,.2f}  "
                f"min={entry['min']:12,.2f}  max={entry['max']:12,.2f}{total}{note}"
            )


def show_countries(stats: dict) -> None:
    _header("COUNTRIES")
    block = stats["countries"]
    print("  TOP:")
    _print_countries(block["top"])
    print("\n  FLOP (least served; zeros are catalog countries nobody proposed):")
    _print_countries(block["flop"])


def _print_countries(rows: list[dict]) -> None:
    if not rows:
        print("    (none)")
        return
    for row in rows:
        print(
            f"    {row['country']}  proposals={row['n_proposals']:3d}  "
            f"existing={row['n_existing']:3d}  total={row['n']:3d}"
        )


def busiest_user() -> int | None:
    """The user_id owning the most proposals — a sensible default subject
    for the narrowed report, and it makes the section meaningful on any
    database without hardcoding an id."""
    response = requests.post(
        PROPOSALS_URL,
        json={
            "filter": {"sources": ["proposal"]},
            "include": ["summaries"],
            "limit": 200,
        },
        timeout=30,
    )
    counts: dict[int, int] = {}
    for row in response.json()["summaries"]["proposals"]:
        if row.get("user_id") is not None:
            counts[row["user_id"]] = counts.get(row["user_id"], 0) + 1
    return max(counts, key=counts.get) if counts else None


def show_by_user(user_id: int | None) -> None:
    _header("NARROWED TO ONE USER")
    if user_id is None:
        print("  No proposals with an owner in the gallery — nothing to narrow to.")
        return

    stats = fetch_stats(user_id)
    print(f"  user_id={user_id}, scope sources={stats['scope']['sources']}")
    show_counts(stats, user_id)
    existing = stats["counts"]["existing"]["n"]
    print(
        f"  existing rows in this scope: {existing}  "
        f"→ {'OK (owners are proposals only)' if existing == 0 else 'UNEXPECTED'}"
    )
    show_countries(stats)
    _write(stats, f"proposal_stats_user_{user_id}_output.json")


# =============================================================================
# Entry point
# =============================================================================


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[2])
    parser.add_argument(
        "command",
        nargs="?",
        default="all",
        choices=["relations", "counts", "kpis", "countries", "by_user", "all"],
    )
    parser.add_argument("--user-id", type=int, default=None)
    args = parser.parse_args()

    _check_api()
    stats = fetch_stats()

    if args.command in ("relations", "all"):
        show_relations(stats)
    if args.command in ("counts", "all"):
        show_counts(stats)
    if args.command in ("kpis", "all"):
        show_kpis(stats)
    if args.command in ("countries", "all"):
        show_countries(stats)
    if args.command in ("by_user", "all"):
        show_by_user(args.user_id if args.user_id is not None else busiest_user())

    _write(stats, "proposal_stats_output.json")


if __name__ == "__main__":
    main()
