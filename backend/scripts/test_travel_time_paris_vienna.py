"""
test_travel_time_paris_vienna.py
=================================
Manual test script for the schedule supplement ("travel time add-on")
calibrated in models/infrastructure/route_context/calib.

Motivation: the tool puts Wien -> Paris at ~17.5 h where the real ÖBB
Nightjet NJ 468 ran it in 15:25 (2024/25) and 14:46 (2021/22 launch).
ROUTE_CONTEXT_CALIBRATION.md §3 already flags why that can happen — the
per-country supplement is measured against the router's pure passage time
and therefore contains BOTH real timetable padding AND router speed error,
and for France it was measured on 26 legs of which 9 of 11 trips are SNCF
Intercités de Nuit (low-priority domestic paths, several deliberately
slowed to arrive at a civilised hour). That sample gives FR 70.6 %, the
highest of any country, and France is the longest country share of this
corridor.

What this script does, in three parts:

  1. ROUTE      One POST /api/proposal/calc for the NJ 468 corridor with
                the requested composition and scenario. Nothing is written
                to the database.
  2. EXTRACT    Per-leg dump of distance_m, driving_time_min,
                dynamics_time_min, buffer_time_min, slack_time_min and
                country_time_shares -> scripts/data/tt_pv_legs.csv, plus
                the raw response as tt_pv_route.json. This is the honest
                pure passage time per country, which no aggregate in the
                API exposes.
  3. REPLAY     Offline recomputation of the trip duration under
                alternative per-country supplements. No routing, no DB —
                pure arithmetic on the extracted legs, so a scenario costs
                nothing to try. Six built-in scenarios from the ONTD leg
                distribution (min / p25 / median / current / p75 / max)
                plus any --supplement override.

Everything is compared against the real NJ 468 timetable (REFERENCE below).

The 90-minute technical stop at Mannheim (coupling) is NOT modelled by the
API — /api/proposal/calc has no per-stop dwell field, and the calibrated
dwell floor is 2 minutes per commercial stop. It is added as a flat
constant (--tech-stop-min, default 90) OUTSIDE the model, and every
printed total states whether it is included. Do not let it silently land
inside a supplement comparison: it is scheduled standing time, not running
time, and the supplement multiplies running time only.

Usage:
    python scripts/test_travel_time_paris_vienna.py
    python scripts/test_travel_time_paris_vienna.py --variant direct
    python scripts/test_travel_time_paris_vienna.py --scenario infra-2026-hsr
    python scripts/test_travel_time_paris_vienna.py --composition REF-BAL-9
    python scripts/test_travel_time_paris_vienna.py --supplement FR=35 DE=25 AT=20
    python scripts/test_travel_time_paris_vienna.py --tech-stop-min 0
    python scripts/test_travel_time_paris_vienna.py --stops osm:n... osm:n... \
        --reference-min 780 --label zrh-ams --tech-stop-min 0

Pre-flight (same as the other scripts/ comparison tools):
  1. Checks the Flask API is reachable
  2. Loads data if not already loaded
  3. Checks OpenRailRouting is running; starts the container if not
"""

import argparse
import csv
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
CONTAINER_NAME = "openrailrouting-infra-2026"

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "data")

# =============================================================================
# CORRIDOR
# =============================================================================
#
# stop_ids from models/infrastructure/stops/data/stop_seed_catalog.csv.
#
# "direct" is the real NJ 468 path: München Ost - Augsburg - (Ulm,
# Stuttgart passed without a stop) - Karlsruhe - Kehl - Strasbourg - Paris.
# The real train did NOT stop at Ulm or Stuttgart; they are omitted so the
# routed path matches without inventing dwell.
#
# "mannheim" is the modelled variant for the 13th: the portion runs
# Stuttgart - Mannheim - Karlsruhe so it can be coupled at Mannheim. That
# is a genuine detour (Stuttgart->Karlsruhe direct is ~78 km, via Mannheim
# ~170 km), so it costs distance AND time on top of the 90-minute stand.

STOPS_DIRECT = [
    "osm:w423692233",  # Wien Hauptbahnhof            AT
    "osm:n66432827",  # Wien Meidling                AT
    "osm:n2465563392",  # St. Pölten Hauptbahnhof      AT
    "osm:w19800696",  # Linz Hauptbahnhof            AT
    "osm:n302097253",  # Salzburg Hauptbahnhof        AT
    "osm:n2578699502",  # Rosenheim                    DE
    "osm:n2465304880",  # München Ost                  DE
    "osm:n1058668074",  # Augsburg Hauptbahnhof        DE
    "osm:n2574283615",  # Karlsruhe Hauptbahnhof       DE
    "osm:n3069229440",  # Strasbourg                   FR
    "osm:n2506241285",  # Paris Gare de l'Est          FR
]

STOPS_MANNHEIM = [
    "osm:w423692233",  # Wien Hauptbahnhof            AT
    "osm:n66432827",  # Wien Meidling                AT
    "osm:n2465563392",  # St. Pölten Hauptbahnhof      AT
    "osm:w19800696",  # Linz Hauptbahnhof            AT
    "osm:n302097253",  # Salzburg Hauptbahnhof        AT
    "osm:n2578699502",  # Rosenheim                    DE
    "osm:n2465304880",  # München Ost                  DE
    "osm:n1058668074",  # Augsburg Hauptbahnhof        DE
    "osm:n1635698272",  # Stuttgart Hauptbahnhof       DE
    "osm:n25439439",  # Mannheim Hauptbahnhof        DE  <- technical stop
    "osm:n2574283615",  # Karlsruhe Hauptbahnhof       DE
    "osm:n3069229440",  # Strasbourg                   FR
    "osm:n2506241285",  # Paris Gare de l'Est          FR
]

VARIANTS = {"direct": STOPS_DIRECT, "mannheim": STOPS_MANNHEIM}

TECH_STOP_STOP_ID = "osm:n25439439"  # Mannheim Hbf

# NEW-BAL-14: "Similar to OEBB nightjet next generation double formation",
# 14 coaches, 638 t, 371 m, v_max 230, hsr_allowed=true. The composition
# Juri modelled.
DEFAULT_COMPOSITION_ID = "NEW-BAL-14"
DEFAULT_SCENARIO = "infra-2026"

# =============================================================================
# REFERENCE — the real NJ 468, Wien Hbf -> Paris Est
# =============================================================================
#
# Two timetable years, because they differ by 39 minutes and the argument
# changes depending on which one is quoted:
#
#   2021/22 launch   Wien 19:38 -> Paris Est 10:24     886 min (14:46)
#   2024/25 final    Wien 18:13 -> Paris Est 09:38     925 min (15:25)
#
# 14.5 h as quoted in the ÖBB launch press release is the optimistic end of
# that range; the train never actually ran faster than 14:46 door to door.
#
# Country split of the 2024/25 timetable, from the published passing times
# (Freilassing 21:25 = AT/DE border, Kehl 04:50 = DE/FR border). Distances
# are route kilometres on the path the train actually took — note that the
# French figure is Strasbourg - Nancy - Paris CLASSIC (502 km), not the
# LGV Est (441 km); a public timetable viewer that computes distances on
# the high-speed alignment will understate this section by ~60 km.
#
#            km       min     km/h
#   AT     319.7      192    100.1     Wien 18:13 -> Freilassing 21:25
#   DE     532.0      445     71.7     Freilassing 21:25 -> Kehl 04:50
#   FR     502.0      288    104.6     Kehl 04:50 -> Paris 09:38
#   TOTAL 1353.7      925     87.8
#
# The DE figure includes a long stand short of the border and the Karlsruhe
# stop, and is not a running-speed figure: the German section of this train
# is deliberately stretched so it reaches Strasbourg at 04:54 and Paris at
# 09:38 rather than arriving in the middle of the night. That stretching is
# operator design, not infrastructure — see the note on the "observed"
# scenario below.

REFERENCE = {
    "2024/25": {
        "total_min": 925,
        "total_km": 1353.7,
        "by_country_min": {"AT": 192, "DE": 445, "FR": 288},
        "by_country_km": {"AT": 319.7, "DE": 532.0, "FR": 502.0},
    },
    "2021/22": {
        "total_min": 886,
        "total_km": 1353.7,
        "by_country_min": None,
        "by_country_km": None,
    },
}

# =============================================================================
# SUPPLEMENT SCENARIOS
# =============================================================================
#
# Per-country schedule supplement in PERCENT of pure passage time.
#
# "seed_2026_08" is what the 2026-08-17 calibration seeded: the time-weighted
# mean residual of real ONTD legs over the router's passage time. "recal" is
# what the 2026-09-05 calibration seeds: the lower quartile of the leg-level
# residual, shrunk toward the European lower-quartile prior, floored at 8 %,
# France fixed at 25 % as a documented exception. The other five replace the
# time-weighted country residual with a leg-level order statistic over the
# same included ONTD legs, shrunk toward the European leg-weighted mean of
# that same statistic with the same k=10 rule the calibration uses:
#
#     supplement = measured x n/(n+10) + European_prior x 10/(n+10)
#
# All 19 countries with ONTD legs are listed; a corridor through any other
# country takes the scenario's European prior below.
#
# NOTE the gap between "median" and "seed_2026_08": the leg distribution is
# strongly right-skewed, so the time-weighted mean sits well above the
# typical leg. For France the median leg is +52.7 %, not +78 %.

SUPPLEMENT_SCENARIOS = {
    "min": {
        "AT": 0.8,
        "BE": 12.0,
        "BG": 11.9,
        "CH": 8.3,
        "CZ": 1.6,
        "DE": 0.5,
        "DK": 15.4,
        "FR": 18.2,
        "GB": 24.1,
        "HR": 4.8,
        "HU": 7.7,
        "IT": 1.0,
        "NL": 4.3,
        "NO": 11.4,
        "PL": 1.9,
        "RO": 1.3,
        "SE": 6.2,
        "SI": 18.7,
        "SK": 7.5,
    },
    "p25": {
        "AT": 11.3,
        "BE": 29.3,
        "BG": 32.0,
        "CH": 20.6,
        "CZ": 20.3,
        "DE": 19.2,
        "DK": 33.3,
        "FR": 35.2,
        "GB": 40.7,
        "HR": 26.8,
        "HU": 23.1,
        "IT": 21.0,
        "NL": 29.5,
        "NO": 26.3,
        "PL": 22.1,
        "RO": 36.0,
        "SE": 34.3,
        "SI": 31.4,
        "SK": 24.3,
    },
    "median": {
        "AT": 24.4,
        "BE": 46.0,
        "BG": 49.7,
        "CH": 37.1,
        "CZ": 33.2,
        "DE": 38.0,
        "DK": 45.7,
        "FR": 52.7,
        "GB": 61.0,
        "HR": 39.7,
        "HU": 35.9,
        "IT": 48.0,
        "NL": 42.5,
        "NO": 39.8,
        "PL": 42.2,
        "RO": 51.1,
        "SE": 56.4,
        "SI": 47.3,
        "SK": 36.8,
    },
    "seed_2026_08": {
        "AT": 34.7,
        "BE": 51.2,
        "BG": 55.3,
        "CH": 50.7,
        "CZ": 46.6,
        "DE": 49.0,
        "DK": 54.4,
        "FR": 70.8,
        "GB": 62.2,
        "HR": 41.7,
        "HU": 42.2,
        "IT": 53.7,
        "NL": 42.3,
        "NO": 46.8,
        "PL": 57.1,
        "RO": 53.4,
        "SE": 68.1,
        "SI": 52.5,
        "SK": 47.4,
    },
    "p75": {
        "AT": 43.2,
        "BE": 61.1,
        "BG": 89.1,
        "CH": 66.4,
        "CZ": 70.6,
        "DE": 60.1,
        "DK": 61.4,
        "FR": 77.3,
        "GB": 78.3,
        "HR": 55.3,
        "HU": 55.1,
        "IT": 65.8,
        "NL": 58.3,
        "NO": 61.9,
        "PL": 75.0,
        "RO": 81.0,
        "SE": 84.8,
        "SI": 72.6,
        "SK": 59.9,
    },
    "max": {
        "AT": 138.4,
        "BE": 143.9,
        "BG": 217.3,
        "CH": 138.7,
        "CZ": 201.4,
        "DE": 188.6,
        "DK": 130.6,
        "FR": 158.9,
        "GB": 135.7,
        "HR": 126.5,
        "HU": 119.4,
        "IT": 130.2,
        "NL": 109.9,
        "NO": 143.3,
        "PL": 208.5,
        "RO": 259.2,
        "SE": 147.0,
        "SI": 148.4,
        "SK": 149.1,
    },
    # SEEDED SINCE 2026-09-05: the minimum-driving-time calibration. After a
    # reseed the buf% column in section 1 must show these; if it still shows
    # seed_2026_08 the database was not reseeded.
    "recal": {
        "AT": 11.3,
        "BE": 27.8,
        "BG": 26.5,
        "CH": 20.3,
        "CZ": 20.4,
        "DE": 18.9,
        "DK": 32.6,
        "EE": 23.9,
        "ES": 23.9,
        "FI": 23.9,
        "FR": 25.0,
        "GB": 38.5,
        "GR": 23.9,
        "HR": 27.0,
        "HU": 22.4,
        "IE": 23.9,
        "IT": 20.7,
        "LT": 23.9,
        "LU": 23.9,
        "LV": 23.9,
        "NL": 29.2,
        "NO": 25.5,
        "PL": 22.0,
        "PT": 23.9,
        "RO": 32.4,
        "SE": 34.9,
        "SI": 31.0,
        "SK": 23.9,
    },
    # CORRIDOR-FITTED, not a calibration either — the supplement each country
    # needs to reproduce the real NJ 468 elapsed time against this router's
    # pure passage. Included so a run shows what the corridor actually
    # demands next to what the model assumes. Note the shape: Germany needs
    # far MORE than the model gives it and France far less, which no country
    # average can produce, because the difference is the operator's night-path
    # design and not a property of either network.
    "observed": {"AT": 22.4, "DE": 58.5, "FR": 25.0},
}

# Countries with no ONTD legs fall back to the European prior for that
# statistic. Only relevant if the corridor is changed to touch one.
SCENARIO_PRIOR = {
    "min": 5.5,
    "p25": 24.6,
    "median": 42.0,
    "seed_2026_08": 51.2,
    "recal": 23.9,
    "p75": 66.0,
    "max": 167.2,
    "shortleg": 46.9,
    "observed": None,
}


# =============================================================================
# PRE-FLIGHT CHECKS
# =============================================================================


def check_flask() -> bool:
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


def ensure_data_loaded() -> bool:
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
    print(f"[✗] Data load failed: {result.get('message')}")
    return False


def ensure_routing_running() -> bool:
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
# SCENARIO LOOKUP
# =============================================================================


def fetch_scenario(scenario_key: str) -> dict:
    """GET /api/scenarios and return the row matching scenario_key, whichever
    of the three response groups it lands in. Exits if not found — that is a
    seed problem, not something to route around."""
    resp = requests.get(f"{API_BASE}/api/scenarios", timeout=15)
    resp.raise_for_status()
    body = resp.json()

    for group in ("current_base", "current_scenarios", "historical_scenarios"):
        for scenario in body[group]["scenarios"]:
            if scenario["scenario_key"] == scenario_key:
                return scenario

    print(f"[✗] No scenario found with scenario_key='{scenario_key}'.")
    keys = [
        s["scenario_key"]
        for group in ("current_base", "current_scenarios", "historical_scenarios")
        for s in body[group]["scenarios"]
    ]
    print("    Available keys: " + ", ".join(keys))
    sys.exit(1)


# =============================================================================
# 1. ROUTE
# =============================================================================


def compute(scenario_id: int, stops: list[str], composition_id: str) -> dict:
    """One stateless POST /api/proposal/calc.

    auto_stop_addition="off" so the leg list is exactly the corridor asked
    for — an auto-added stop would change both the dwell total and the
    per-leg dynamics, and this script compares legs against a real
    timetable's legs.
    """
    body = {
        "scenario_id": scenario_id,
        "stops": stops,
        "composition_id": composition_id,
        "routing_mode": "fullRouting",
        "schedule_mode": "alwaysDaily",
        "timetable_mode": "simpleAutomatic",
        "auto_stop_addition": "off",
    }
    resp = requests.post(f"{API_BASE}/api/proposal/calc", json=body, timeout=180)
    if resp.status_code != 200:
        print(f"[✗] proposal/calc failed: {resp.status_code} {resp.text[:400]}")
        sys.exit(1)
    return resp.json()


# =============================================================================
# 2. EXTRACT
# =============================================================================


def outbound_trip(route: dict) -> dict:
    pair = route["trip_pairs"][0]
    for trip in (pair["outbound"], pair["return_trip"]):
        if trip["direction"] == 0:
            return trip
    return pair["outbound"]


def extract_legs(trip: dict) -> list[dict]:
    """One flat row per segment — the numbers the replay needs, nothing else.

    pure_min = driving + dynamics. That is the passage time the supplement
    multiplies; buffer_time_min is what the model ALREADY added on top of
    it, and slack_time_min is timetable stretching, which is not a
    supplement and must not be scaled.
    """
    rows = []
    for i, seg in enumerate(trip["segments"], start=1):
        driving = seg["driving_time_min"]
        dynamics = seg["dynamics_time_min"]
        rows.append(
            {
                "seq": i,
                "from_stop": seg["from_stop"]["stop_name"],
                "to_stop": seg["to_stop"]["stop_name"],
                "distance_km": round(seg["distance_m"] / 1000, 1),
                "driving_min": driving,
                "dynamics_min": dynamics,
                "pure_min": driving + dynamics,
                "buffer_min": seg["buffer_time_min"],
                "slack_min": seg["slack_time_min"],
                "applied_pct": (
                    round(100 * seg["buffer_time_min"] / (driving + dynamics), 1)
                    if (driving + dynamics) > 0
                    else None
                ),
                "countries": "+".join(seg["countries"]),
                "country_time_shares": json.dumps(seg["country_time_shares"]),
                "country_distance_shares": json.dumps(seg["country_distance_shares"]),
            }
        )
    return rows


def dwell_minutes(trip: dict) -> int:
    """Scheduled standing time at intermediate stops — outside every
    supplement (§4 of the calibration: a stop is not running time)."""
    segments = trip["segments"]
    stops = [segments[0]["from_stop"]] + [s["to_stop"] for s in segments]
    total = 0
    for stop in stops[1:-1]:
        arr, dep = stop["arrival_time_min"], stop["departure_time_min"]
        if arr is not None and dep is not None:
            total += dep - arr
    return total


def pure_by_country(legs: list[dict]) -> dict[str, float]:
    """Pure passage minutes attributed to countries by country_time_shares —
    the same attribution rule the ONTD check in §3 uses, so the replay and
    the calibration are measuring the same thing."""
    out: dict[str, float] = {}
    for leg in legs:
        shares = json.loads(leg["country_time_shares"])
        for cc, share in shares.items():
            out[cc] = out.get(cc, 0.0) + leg["pure_min"] * share
    return out


def write_outputs(payload: dict, legs: list[dict], tag: str) -> tuple[str, str]:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    json_path = os.path.join(OUTPUT_DIR, f"tt_pv_route_{tag}.json")
    csv_path = os.path.join(OUTPUT_DIR, f"tt_pv_legs_{tag}.csv")

    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)

    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(legs[0]))
        writer.writeheader()
        writer.writerows(legs)

    return json_path, csv_path


# =============================================================================
# 3. REPLAY
# =============================================================================


def replay(
    legs: list[dict], supplements: dict[str, float], prior: float | None
) -> tuple[float, dict[str, float]]:
    """Total running minutes under an alternative supplement vector, plus
    the per-country running total.

    Applied per leg on the leg's country time shares, which is how
    dynamics.py already weights the quota — a cross-border leg is not
    charged one country's supplement on its whole length.
    """
    total = 0.0
    by_country: dict[str, float] = {}
    for leg in legs:
        shares = json.loads(leg["country_time_shares"])
        for cc, share in shares.items():
            pct = supplements.get(cc, prior if prior is not None else 0.0)
            minutes = leg["pure_min"] * share * (1 + pct / 100)
            total += minutes
            by_country[cc] = by_country.get(cc, 0.0) + minutes
    return total, by_country


def hhmm(minutes: float) -> str:
    m = int(round(minutes))
    return f"{m // 60}:{m % 60:02d}"


def parse_overrides(pairs: list[str]) -> dict[str, float]:
    out = {}
    for pair in pairs or []:
        if "=" not in pair:
            print(f"[✗] --supplement expects CC=pct, got '{pair}'.")
            sys.exit(1)
        cc, value = pair.split("=", 1)
        out[cc.strip().upper()] = float(value)
    return out


# =============================================================================
# REPORT
# =============================================================================


def print_legs(legs: list[dict]) -> None:
    print(
        f"\n  {'#':>2} {'from':22}{'to':22}{'km':>8}{'drive':>7}{'dyn':>5}"
        f"{'pure':>6}{'buf':>6}{'slack':>6}{'buf%':>7}  countries"
    )
    for leg in legs:
        print(
            f"  {leg['seq']:>2} {leg['from_stop'][:21]:22}{leg['to_stop'][:21]:22}"
            f"{leg['distance_km']:>8.1f}{leg['driving_min']:>7}{leg['dynamics_min']:>5}"
            f"{leg['pure_min']:>6}{leg['buffer_min']:>6}{leg['slack_min']:>6}"
            f"{(leg['applied_pct'] if leg['applied_pct'] is not None else 0):>7.1f}"
            f"  {leg['countries']}"
        )


def print_country_block(legs: list[dict]) -> dict[str, float]:
    pure = pure_by_country(legs)
    ref_km = REFERENCE["2024/25"].get("by_country_km")
    ref_min = REFERENCE["2024/25"].get("by_country_min")

    print(
        f"\n  {'country':9}{'pure min':>10}{'recal %':>10}{'ref min':>10}{'ref km':>9}"
    )
    for cc in sorted(pure):
        seeded = SUPPLEMENT_SCENARIOS["recal"].get(cc)
        print(
            f"  {cc:9}{pure[cc]:>10.1f}"
            f"{(f'{seeded:.1f}' if seeded is not None else '—'):>10}"
            f"{(str(ref_min.get(cc, '—')) if ref_min else '—'):>10}"
            f"{(f'{ref_km[cc]:.1f}' if ref_km and cc in ref_km else '—'):>9}"
        )
    print(f"  {'TOTAL':9}{sum(pure.values()):>10.1f}")
    return pure


def print_replay_table(
    legs: list[dict],
    dwell: int,
    tech_stop_min: int,
    trip_km: float,
    overrides: dict[str, float],
) -> None:
    scenarios = dict(SUPPLEMENT_SCENARIOS)
    if overrides:
        scenarios["custom"] = overrides
    countries = sorted(pure_by_country(legs))

    header = f"\n  {'scenario':13}" + "".join(f"{cc:>7}" for cc in countries)
    print(
        header + f"{'running':>10}{'+dwell':>9}{'+tech':>9}{'km/h':>8}{'vs real':>10}"
    )
    ref = REFERENCE["2024/25"]["total_min"]
    for name, vector in scenarios.items():
        prior = SCENARIO_PRIOR.get(name)
        running, _ = replay(legs, vector, prior)
        with_dwell = running + dwell
        with_tech = with_dwell + tech_stop_min
        speed = trip_km / (with_tech / 60) if with_tech else 0.0
        delta = with_tech - ref
        cells = ""
        for cc in countries:
            value = vector.get(cc, prior)
            cells += f"{value:>7.1f}" if value is not None else f"{'—':>7}"
        print(
            f"  {name:13}{cells}"
            f"{hhmm(running):>10}{hhmm(with_dwell):>9}{hhmm(with_tech):>9}"
            f"{speed:>8.1f}{('+' if delta >= 0 else '−') + hhmm(abs(delta)):>10}"
        )

    print(
        "\n  running = pure passage x (1 + supplement), summed over legs on "
        "country time shares; a country absent from a scenario takes that "
        "scenario's European prior (— = none, the leg's pure time is kept)"
    )
    print(f"  +dwell  = plus {dwell} min scheduled dwell at intermediate stops")
    print(
        f"  +tech   = plus {tech_stop_min} min technical stop "
        f"(Mannheim coupling; added outside the model)"
    )
    if REFERENCE["2021/22"] is None:
        print(f"  vs real = against the --reference-min timetable, {hhmm(ref)}")
    else:
        print(
            f"  vs real = against NJ 468 2024/25, {hhmm(ref)} "
            f"Wien 18:13 -> Paris 09:38 "
            f"(2021/22 launch: {hhmm(REFERENCE['2021/22']['total_min'])})"
        )


def solve_required_supplement(
    legs: list[dict], target_min: float, dwell: int, tech: int
) -> float:
    """The single uniform supplement that reproduces the real timetable.
    Reported as one number because a per-country solve is underdetermined
    from one observation — the same reason §3 refused to split the residual."""
    pure = sum(pure_by_country(legs).values())
    running_target = target_min - dwell - tech
    if pure <= 0:
        return 0.0
    return 100 * (running_target / pure - 1)


# =============================================================================
# MAIN
# =============================================================================


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Wien -> Paris travel time check against the schedule supplement calibration."
    )
    parser.add_argument("--variant", choices=sorted(VARIANTS), default="mannheim")
    parser.add_argument(
        "--stops",
        nargs="+",
        metavar="STOP_ID",
        help="Any corridor instead of a built-in variant (stop_ids in travel "
        "order). Use with --reference-min to compare against a real train.",
    )
    parser.add_argument(
        "--reference-min",
        type=int,
        help="Real timetable duration in minutes for --stops corridors "
        "(departure -> arrival). Replaces the NJ 468 reference.",
    )
    parser.add_argument(
        "--label", default=None, help="Tag for the output files with --stops."
    )
    parser.add_argument("--scenario", default=DEFAULT_SCENARIO)
    parser.add_argument("--composition", default=DEFAULT_COMPOSITION_ID)
    parser.add_argument(
        "--tech-stop-min",
        type=int,
        default=90,
        help="Technical stop at Mannheim, added outside the model. 0 to drop it.",
    )
    parser.add_argument(
        "--supplement",
        nargs="*",
        metavar="CC=PCT",
        help="Custom supplement vector, e.g. --supplement FR=35 DE=25 AT=20",
    )
    parser.add_argument(
        "--skip-preflight", action="store_true", help="Assume the stack is up."
    )
    args = parser.parse_args()

    if args.stops:
        stops = args.stops
        variant_label = args.label or "custom"
        if args.reference_min:
            REFERENCE["2024/25"] = {
                "total_min": args.reference_min,
                "total_km": None,
                "by_country_min": None,
                "by_country_km": None,
            }
            REFERENCE["2021/22"] = None
    else:
        stops = VARIANTS[args.variant]
        variant_label = args.variant
    tech_stop_min = args.tech_stop_min if TECH_STOP_STOP_ID in stops else 0
    overrides = parse_overrides(args.supplement)

    print("=" * 78)
    print("WIEN -> PARIS TRAVEL TIME CHECK")
    print("=" * 78)

    if not args.skip_preflight:
        if not check_flask():
            sys.exit(1)
        if not ensure_data_loaded():
            sys.exit(1)
        if not ensure_routing_running():
            sys.exit(1)

    scenario = fetch_scenario(args.scenario)
    print(
        f"\n  variant      {variant_label} ({len(stops)} stops)"
        f"\n  scenario     {scenario['scenario_key']} "
        f"({scenario['scenario_name']}) [scenario_id={scenario['scenario_id']}]"
        f"\n  composition  {args.composition}"
        f"\n  tech stop    {tech_stop_min} min"
    )

    print("\n[ ] Routing...")
    payload = compute(scenario["scenario_id"], stops, args.composition)
    trip = outbound_trip(payload["route"])
    legs = extract_legs(trip)
    dwell = dwell_minutes(trip)
    gp = trip["general_parameters"]
    print(
        f"[✓] Routed: {gp['trip_km']} km, {gp['route_duration_min']} min "
        f"({hhmm(gp['route_duration_min'])}), {gp['average_speed_kmh']} km/h"
    )

    tag = f"{variant_label}_{args.scenario}"
    json_path, csv_path = write_outputs(payload, legs, tag)

    print("\n" + "-" * 78)
    print("1. LEGS AS ROUTED")
    print("-" * 78)
    print_legs(legs)
    print(f"\n  dwell at intermediate stops: {dwell} min")

    print("\n" + "-" * 78)
    print("2. PURE PASSAGE TIME BY COUNTRY")
    print("-" * 78)
    print_country_block(legs)

    print("\n" + "-" * 78)
    print("3. SUPPLEMENT SCENARIOS")
    print("-" * 78)
    print_replay_table(legs, dwell, tech_stop_min, gp["trip_km"], overrides)

    for label, ref in (
        ("2024/25", REFERENCE["2024/25"]),
        ("2021/22", REFERENCE["2021/22"]),
    ):
        if ref is None:
            continue
        needed = solve_required_supplement(legs, ref["total_min"], dwell, tech_stop_min)
        print(
            f"\n  Uniform supplement reproducing the real {label} timetable "
            f"({hhmm(ref['total_min'])}): {needed:.1f} %"
        )
    if tech_stop_min:
        print(
            f"  (the {tech_stop_min}-minute technical stop is inside those totals; "
            f"re-run with --tech-stop-min 0 for the running-only comparison)"
        )

    print("\n" + "-" * 78)
    print(f"  legs  -> {csv_path}")
    print(f"  raw   -> {json_path}")
    print("-" * 78)


if __name__ == "__main__":
    main()
