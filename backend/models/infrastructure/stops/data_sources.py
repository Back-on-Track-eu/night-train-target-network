"""
Resolves the pipeline's bulk inputs, downloading them from Drive on first use.

The data is deliberately not in git (see .gitignore): the OSM extract alone is
tens of gigabytes, and the derived CSVs are regenerated artifacts, not source.
Instead every file has a Drive id here, and ensure_local() fetches it into
data/ when it isn't already there — the same soft-fail pattern db/dev/seed.py
uses for ontd_seed_stops.csv, so behaviour is consistent across the project.

Each id is overridable by environment variable without a code change, which is
what makes a re-generated file easy to swap in: upload it as a new version of
the same Drive file (the id survives) or point the env var at a new one.

Usage from a notebook:

    from data_sources import ensure_local
    step4_csv = ensure_local("step4_MatchingONTDtoOSM.csv")

Drive folder holding all of these:
https://drive.google.com/drive/folders/1iAjxVKRn1qhgR-yhfczO91M41KIIIIVd
"""

from __future__ import annotations

import csv
import io
import os
import urllib.request
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"

DOWNLOAD_TIMEOUT_S = 300

# filename -> (env var overriding the id, default Drive file id)
#
# Fill a default in as soon as the file has a stable Drive id; until then the
# entry still works by setting the environment variable. An empty default is
# reported as a missing id rather than attempted as a download.
FILE_IDS: dict[str, tuple[str, str]] = {
    "bahnhoefe_stops_sorted.csv": ("STOPS_ONTD_EXPORT_FILE_ID", ""),
    "B-o-T_DataBase_stop_times.csv": ("STOPS_STOP_TIMES_FILE_ID", ""),
    "step2_output_eu_stations.osm.pbf": ("STOPS_STEP2_OUTPUT_FILE_ID", ""),
    "step3a_output_way_relation_centers.csv": ("STOPS_STEP3A_OUTPUT_FILE_ID", ""),
    "step3b_output_osm_stations_classified.csv": ("STOPS_STEP3B_OUTPUT_FILE_ID", ""),
    "step4_MatchingONTDtoOSM.csv": ("STOPS_STEP4_OUTPUT_FILE_ID", ""),
    "step5_JoinedNTStops.csv": ("STOPS_STEP5_OUTPUT_FILE_ID", ""),
    "step6_metropol.csv": ("STOPS_STEP6_OUTPUT_FILE_ID", ""),
}

# Expected header per CSV, checked after download. A Drive permission error
# serves an HTML page with HTTP 200, so without this the pipeline would cache
# and then parse a login page as if it were data.
EXPECTED_HEADERS: dict[str, list[str]] = {
    "bahnhoefe_stops_sorted.csv": [
        "ID",
        "Name",
        "Name (Lateinisch)",
        "Name (ASCII)",
        "Länderkürzel",
        "Zeitzone",
        "Latitude",
        "Longitude",
    ],
    "step3b_output_osm_stations_classified.csv": [
        "stop_id",
        "stop_name",
        "stop_lat",
        "stop_lon",
        "country",
        "station_mode",
        "mode_rule",
        "stop_code",
    ],
    "step6_metropol.csv": [
        "stop_id",
        "stop_name",
        "stop_lat",
        "stop_lon",
        "country",
        "stop_timezone",
    ],
    "step4_MatchingONTDtoOSM.csv": [
        "ontd_id",
        "ontd_name",
        "ontd_name_ascii",
        "ontd_country",
        "ontd_lat",
        "ontd_lon",
        "match_type",
        "name_score",
        "osm_stop_id",
        "osm_stop_name",
        "osm_lat",
        "osm_lon",
        "osm_stop_code",
        "osm_station_mode",
        "distance_km",
        "candidate_count",
    ],
}


def file_id(filename: str) -> str:
    """Drive id for a known filename, env var winning over the default."""
    try:
        env_var, default = FILE_IDS[filename]
    except KeyError:
        raise KeyError(
            f"{filename!r} is not a known pipeline input — add it to FILE_IDS"
        ) from None
    return os.environ.get(env_var, default).strip()


def ensure_local(filename: str, *, required: bool = True) -> Path | None:
    """Path to the local copy, downloading it from Drive if absent.

    Returns None instead of raising when required=False and the file can't be
    obtained, so a notebook can degrade to a partial run the way seed.py
    degrades to the curated catalog.
    """
    target = DATA_DIR / filename
    if target.is_file():
        return target

    env_var, _ = FILE_IDS.get(filename, ("", ""))
    ident = file_id(filename)
    if not ident:
        return _missing(
            filename,
            f"no Drive id configured — set {env_var} or add a default in "
            "data_sources.py",
            required,
        )

    url = (
        "https://drive.usercontent.google.com/download"
        f"?id={ident}&export=download&confirm=t"
    )
    print(f"  {filename} not found locally — downloading (id={ident})...")
    try:
        with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT_S) as response:
            payload = response.read()
    except Exception as exc:
        return _missing(
            filename, f"download failed ({type(exc).__name__}: {exc})", required
        )

    expected = EXPECTED_HEADERS.get(filename)
    if expected is not None:
        try:
            text = payload.decode("utf-8-sig")
        except UnicodeDecodeError:
            return _missing(filename, "downloaded content is not UTF-8 text", required)
        header = next(csv.reader(io.StringIO(text)), None)
        if header != expected:
            return _missing(
                filename,
                f"downloaded content is not the expected CSV (header {header!r}) "
                "— wrong file id, or the file is not shared publicly",
                required,
            )

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    print(f"  downloaded {filename} ({len(payload) / 1e6:.1f} MB).")
    return target


def _missing(filename: str, reason: str, required: bool) -> None:
    message = (
        f"Pipeline input {filename!r} unavailable — {reason}.\n"
        f"Place it manually at {DATA_DIR / filename} if the download can't work."
    )
    if required:
        raise FileNotFoundError(message)
    print(f"\n  WARNING: {message}\n")
