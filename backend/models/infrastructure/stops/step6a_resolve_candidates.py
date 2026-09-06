"""
Step 6a — resolve named stop candidates to OSM ids for step 6.

Step 6 keys its additions on an OSM object id, and looking that id up is the
only laborious part of adding a stop. This script does the lookup for a whole
list at once: it takes a CSV of candidates — a name, a coordinate, the reason,
which infrastructure versions the stop belongs to — matches each one against
the step 3b station extract the same way step 5 matches the schedule
(coordinate first, name second), applies step 6's own guards, and prints
paste-ready dict lines grouped by region.

It never writes into the notebook. The notebook is the record of the
selection; this is a tool for filling it. Every candidate the script cannot
resolve *unambiguously* is reported with its nearest objects, not guessed.

    uv run python step6a_resolve_candidates.py step6_gap_closure_2026-09.csv
    uv run python step6a_resolve_candidates.py my_candidates.csv --radius-km 2

Input columns (see step6_gap_closure_2026-09.csv for a complete example):

    name            display name, comment only
    search_name     what to look for in OSM names ("Spandau", "Коростень");
                    empty means use `name`
    osm_stop_id     optional. An id you already know (from git history, an
                    old charge file, a test fixture). Verified against step
                    3b, its mode and its distance from lat/lon — not trusted
                    blindly — and used instead of the name search if it holds
    lat, lon        where the station is. WGS84, "." decimal
    coord_source    "schedule" for a coordinate you trust (radius 1.5 km),
                    "corrected" for one typed from memory (radius 2.5 km)
    region          which ADDITIONS_* dict of the notebook the line belongs in
    country         ISO-2, comment only (the notebook resolves country itself)
    reason          step 6 reason — fua:<city>, tourism:<region>, ferry:<port>,
                    border, network, night_train_stop
    infra_versions  "infra-2026;infra-2032" (default), "infra-2032" or
                    "infra-2026"
    note            free text, printed as a trailing comment
    decision        only "add" rows are resolved; "skip" and "review" are
                    listed at the end so the record stays complete

Output: data/step6_candidates_resolved.csv (one row per candidate with the
outcome) and the paste-ready blocks on stdout.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import math
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

from data_sources import DATA_DIR, ensure_local, local_input

INFRA_BOTH = "infra-2026;infra-2032"
INFRA_VALID = {"infra-2026", "infra-2032"}

RADIUS_KM = {"schedule": 1.5, "corrected": 2.5}
MIN_NAME_SCORE = 60  # below this a geo candidate does not count as a name hit
AMBIGUITY_GAP = 9  # two hits within this many points, >300 m apart → ambiguous
# (an exact name, 100, beats a name that merely contains the search term, 90;
# "Aarau" is not ambiguous with "Aarau Torfeld")

# Same expansions step 5 and charges/02 use, plus the Nordic "C"/"H".
ABBREVIATIONS = {
    "hbf": "hauptbahnhof",
    "hb": "hauptbahnhof",
    "bf": "bahnhof",
    "bhf": "bahnhof",
    "centraal": "central",
    "centrale": "central",
    "centralen": "central",
    "centralstation": "central",
    "c": "central",
    "h": "hovedbanegard",
    "gl": "glowny",
    "st": "sankt",
    "hl": "hlavni",
    "n": "nadrazi",
}


def normalize(name: str) -> str:
    """Lowercase, strip diacritics, keep non-Latin scripts (Cyrillic, Greek)
    intact so a Ukrainian search name can meet a Ukrainian OSM name."""
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.lower()
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"[^\w]+", " ", text).strip()
    return " ".join(ABBREVIATIONS.get(word, word) for word in text.split())


def name_score(search: str, candidate: str) -> int:
    a, b = normalize(search), normalize(candidate)
    if not a or not b:
        return 0
    if a == b:
        return 100
    if a in b or b in a:
        return 90
    tokens_a, tokens_b = set(a.split()), set(b.split())
    if tokens_a and tokens_a <= tokens_b:
        return 85
    return int(difflib.SequenceMatcher(None, a, b).ratio() * 100)


def distance_km(lat1, lon1, lat2, lon2):
    mean_lat = math.radians((lat1 + lat2) / 2)
    dx = math.radians(lon2 - lon1) * math.cos(mean_lat)
    dy = math.radians(lat2 - lat1)
    return math.hypot(dx, dy) * 6371.0


def load_stations() -> list[dict]:
    rows = []
    with open(
        ensure_local("step3b_output_osm_stations_classified.csv"),
        encoding="utf-8-sig",
        newline="",
    ) as fh:
        for row in csv.DictReader(fh):
            try:
                row["_lat"] = float(row["stop_lat"])
                row["_lon"] = float(row["stop_lon"])
            except (TypeError, ValueError):
                continue
            rows.append(row)
    return rows


def load_step5_ids() -> tuple[set[str], list[tuple[float, float, str]]]:
    ids, located = set(), []
    with open(
        local_input("step5_JoinedNTStops.csv", "step5_JoinNTStopsWithOSM.ipynb"),
        encoding="utf-8-sig",
        newline="",
    ) as fh:
        for row in csv.DictReader(fh):
            ids.add(row["osm_stop_id"])
            if row["osm_lat"] and row["osm_lon"]:
                located.append(
                    (float(row["osm_lat"]), float(row["osm_lon"]), row["osm_stop_name"])
                )
    return ids, located


def load_step6_ids() -> set[str]:
    path = DATA_DIR / "step6_manual_additions.csv"
    if not path.is_file():
        return set()
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return {row["stop_id"] for row in csv.DictReader(fh)}


def resolve(
    candidate: dict, stations: list[dict], step5_ids: set[str], step5_located
) -> dict:
    lat, lon = float(candidate["lat"]), float(candidate["lon"])
    radius = RADIUS_KM.get(candidate["coord_source"].strip(), 1.5)
    search = candidate["search_name"].strip() or candidate["name"].strip()
    ferry = candidate["reason"].startswith("ferry")

    # Cheap bounding-box prefilter, then the real distance.
    dlat = radius / 111.32
    dlon = radius / (111.32 * max(math.cos(math.radians(lat)), 0.2))
    nearby = []
    for s in stations:
        if abs(s["_lat"] - lat) > dlat or abs(s["_lon"] - lon) > dlon:
            continue
        d = distance_km(lat, lon, s["_lat"], s["_lon"])
        if d > radius:
            continue
        mode = s["station_mode"]
        if mode == "urban_transit":
            continue
        if mode == "other" and not (ferry and s["mode_rule"] == "ferry_terminal"):
            continue
        # Score against the search name and the display name — a Cyrillic
        # search name meets a Cyrillic OSM name, a Latin display name meets
        # the odd Latin-tagged object; the better of the two counts.
        score = max(
            name_score(search, s["stop_name"]),
            name_score(candidate["name"], s["stop_name"]),
        )
        nearby.append((score, d, s))

    outcome = {
        **candidate,
        "stop_id": "",
        "osm_name": "",
        "station_mode": "",
        "distance_km": "",
        "name_score": "",
        "status": "",
        "alternatives": "",
    }

    # A prefilled id short-circuits the name search, but only after the same
    # checks a found object gets: it must exist, be a railway station, and sit
    # where the row says it does.
    given = (candidate.get("osm_stop_id") or "").strip()
    if given:
        match = next((s for s in stations if s["stop_id"] == given), None)
        if match is None:
            outcome["status"] = "given_id_not_in_step3b"
            return outcome
        d = distance_km(lat, lon, match["_lat"], match["_lon"])
        mode = match["station_mode"]
        outcome.update(
            stop_id=given,
            osm_name=match["stop_name"],
            station_mode=mode,
            distance_km=f"{d:.2f}",
            name_score=name_score(search, match["stop_name"]),
        )
        if mode == "urban_transit" or (mode == "other" and not ferry):
            outcome["status"] = f"given_id_is_{mode}"
        elif d > radius:
            outcome["status"] = f"given_id_{d:.1f}km_from_row_coordinate"
        elif given in step5_ids:
            outcome["status"] = "already_qualified_step5"
        else:
            outcome["status"] = "resolved"
        return outcome

    if not nearby:
        outcome["status"] = "no_station_within_radius"
        return outcome

    nearby.sort(key=lambda t: (-t[0], t[1]))
    best_score, best_d, best = nearby[0]
    alternatives = "; ".join(
        f"{s['stop_id']} {s['stop_name']} ({sc}, {d * 1000:.0f} m, {s['station_mode']})"
        for sc, d, s in nearby[1:4]
    )
    outcome["alternatives"] = alternatives

    if best_score < MIN_NAME_SCORE:
        outcome["status"] = "no_name_match"
        outcome["alternatives"] = "; ".join(
            f"{s['stop_id']} {s['stop_name']} ({sc}, {d * 1000:.0f} m, {s['station_mode']})"
            for sc, d, s in nearby[:4]
        )
        return outcome

    for score, d, s in nearby[1:]:
        if best_score - score <= AMBIGUITY_GAP and (
            distance_km(best["_lat"], best["_lon"], s["_lat"], s["_lon"]) > 0.3
        ):
            outcome["status"] = "ambiguous"
            break

    outcome.update(
        stop_id=best["stop_id"],
        osm_name=best["stop_name"],
        station_mode=best["station_mode"],
        distance_km=f"{best_d:.2f}",
        name_score=best_score,
    )
    if outcome["status"]:
        return outcome

    if best["stop_id"] in step5_ids:
        outcome["status"] = "already_qualified_step5"
        return outcome
    for s_lat, s_lon, s_name in step5_located:
        if distance_km(best["_lat"], best["_lon"], s_lat, s_lon) <= 0.3:
            outcome["status"] = f"within_300m_of_step5:{s_name}"
            return outcome

    outcome["status"] = "resolved"
    return outcome


def python_line(row: dict) -> str:
    name = row["osm_name"].replace('"', '\\"')
    reason = row["reason"].strip().replace('"', '\\"')
    infra = (row["infra_versions"].strip() or INFRA_BOTH).replace(",", ";")
    comment = f"  # {row['note'].strip()}" if row["note"].strip() else ""
    if infra == INFRA_BOTH:
        return f'    "{row["stop_id"]}": ("{name}", "{reason}"),{comment}'
    return f'    "{row["stop_id"]}": ("{name}", "{reason}", "{infra}"),{comment}'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("candidates", type=Path)
    parser.add_argument(
        "--radius-km",
        type=float,
        default=None,
        help="override the radius for every row",
    )
    args = parser.parse_args()

    if args.radius_km:
        for key in RADIUS_KM:
            RADIUS_KM[key] = args.radius_km

    with open(args.candidates, encoding="utf-8-sig", newline="") as fh:
        candidates = list(csv.DictReader(fh))
    for row in candidates:
        infra = (row.get("infra_versions") or "").strip()
        bad = {p for p in infra.replace(",", ";").split(";") if p} - INFRA_VALID
        if bad:
            sys.exit(f"{row['name']}: invalid infra_versions {sorted(bad)}")

    stations = load_stations()
    step5_ids, step5_located = load_step5_ids()
    step6_ids = load_step6_ids()
    print(
        f"{len(stations)} step 3b stations, {len(step5_ids)} step 5 stops, "
        f"{len(step6_ids)} existing step 6 additions"
    )

    outcomes = []
    for row in candidates:
        if row["decision"].strip() != "add":
            outcomes.append(
                {
                    **row,
                    "stop_id": "",
                    "osm_name": "",
                    "station_mode": "",
                    "distance_km": "",
                    "name_score": "",
                    "status": row["decision"],
                    "alternatives": "",
                }
            )
            continue
        outcome = resolve(row, stations, step5_ids, step5_located)
        if outcome["status"] == "resolved" and outcome["stop_id"] in step6_ids:
            outcome["status"] = "already_in_step6"
        outcomes.append(outcome)

    out_path = DATA_DIR / "step6_candidates_resolved.csv"
    with open(out_path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(outcomes[0].keys()))
        writer.writeheader()
        writer.writerows(outcomes)

    # --- paste-ready blocks --------------------------------------------------
    by_region: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for o in outcomes:
        if o["status"] == "resolved":
            by_region[o["region"].strip()][o["country"].strip()].append(o)

    print(
        "\n# ==== paste into step6_manual_additions.ipynb, one block per "
        "ADDITIONS_<REGION> dict ===="
    )
    for region in sorted(by_region):
        print(f"\n# ---- ADDITIONS_{region} ----")
        for cc in sorted(by_region[region]):
            print(f"    # --- {cc} --- (step 6a, {args.candidates.name})")
            for o in by_region[region][cc]:
                print(python_line(o))

    # --- everything that needs a human --------------------------------------
    problems = [
        o for o in outcomes if o["status"] not in ("resolved", "skip", "review")
    ]
    reviews = [o for o in outcomes if o["status"] == "review"]
    print(
        f"\n{sum(1 for o in outcomes if o['status'] == 'resolved')} resolved, "
        f"{len(problems)} need attention, {len(reviews)} marked review, "
        f"{sum(1 for o in outcomes if o['status'] == 'skip')} skipped"
    )
    for o in problems:
        print(
            f"  {o['name'][:38]:40} {o['status']:32} "
            f"{o['stop_id'] or '-':18} {o['alternatives'][:120]}"
        )
    for o in reviews:
        print(f"  REVIEW {o['name'][:32]:34} {o['note'][:140]}")
    print(f"\nfull outcome per candidate: {out_path}")


if __name__ == "__main__":
    main()
