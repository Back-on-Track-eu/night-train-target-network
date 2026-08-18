"""
Resolves the pipeline's bulk inputs, downloading them from Drive on first use.

The data is deliberately not in git (see .gitignore): the OSM extract alone is
tens of gigabytes, and the derived CSVs are regenerated artifacts, not source.
Instead there is ONE Drive folder holding all of them, and ensure_local() picks
a file out of it by name, syncing the folder once per process when something is
missing.

One folder id rather than one id per file: the id lives in backend/docker/.env,
because ids are wiring and that file is the project's one home for wiring
(AGENTS.md "Parameter placement"). This module loads that .env through dev_env,
so a notebook run from the host sees the same value the containers do.

Two kinds of file, deliberately handled differently:

  ensure_local(name)
      Comes from outside this machine — the two external exports and the
      OSM-derived intermediates that need the ~60 GB Europe extract, an osmium
      pass and hours of Overpass calls to rebuild. Downloaded when absent.

  local_input(name, produced_by)
      Written by an earlier step of this pipeline. Never downloaded: a stale
      Drive copy could silently override what the notebook just produced.
      Missing means that step has not been run, and the error says which.

A local file always wins. The sync only fills gaps, so re-running a step
overwrites nothing and a hand-placed file is never clobbered.

Usage from a notebook:

    from data_sources import ensure_local
    step4_csv = ensure_local("step4_MatchingONTDtoOSM.csv")

Drive folder:
https://drive.google.com/drive/folders/1iAjxVKRn1qhgR-yhfczO91M41KIIIIVd
"""

from __future__ import annotations

import csv
import inspect
import os
import shutil
import sys
import tempfile
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"

# backend/ on the path so a notebook launched from this directory can reach
# dev_env, which loads backend/docker/.env — the same file the containers read.
_BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

try:
    from dev_env import load_env_files

    load_env_files()
except ImportError:  # pragma: no cover — notebook run outside the repo
    print("  dev_env not importable — reading the folder id from the environment.")

FOLDER_ID_VAR = "STOPS_DRIVE_FOLDER_ID"

# Files the folder is expected to provide. Listed so a typo fails loudly here
# rather than as a confusing "not in the folder" after a multi-minute sync.
DOWNLOADABLE = {
    "bahnhoefe_stops_sorted.csv",
    "B-o-T_DataBase_stop_times.csv",
    "step2_output_eu_stations.osm.pbf",
    "step3a_output_way_relation_centers.csv",
    "step3b_output_osm_stations_classified.csv",
    "step4_MatchingONTDtoOSM.csv",
    "stop_seed_catalog.csv",
}

# Expected header per CSV, checked on use. A Drive permission error serves an
# HTML page with HTTP 200, so without this the pipeline would cache and then
# parse a login page as if it were data.
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
    "stop_seed_catalog.csv": [
        "stop_id",
        "stop_name",
        "country_code",
        "stop_timezone",
        "stop_lat",
        "stop_lon",
        "stop_charge_eur",
    ],
}

_synced = False


def folder_id() -> str:
    return os.environ.get(FOLDER_ID_VAR, "").strip()


def sync_folder(*, force: bool = False) -> int:
    """Copy every folder file missing from data/ into it. Returns the count.

    Runs at most once per process unless forced. Downloads into a temporary
    directory and copies only what is absent, so an existing local file — one a
    step just wrote, or one placed by hand — is never overwritten.
    """
    global _synced
    if _synced and not force:
        return 0

    ident = folder_id()
    if not ident:
        raise RuntimeError(
            f"{FOLDER_ID_VAR} is not set — put the Drive folder id in "
            "backend/docker/.env, or place the files in data/ by hand."
        )
    try:
        import gdown
    except ImportError:
        raise RuntimeError(
            "gdown is needed to sync the Drive folder. Install it with "
            "`uv sync --extra dev`, or place the files in data/ by hand."
        ) from None

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"  syncing Drive folder {ident} — this takes a few minutes...")

    # gdown's signature has drifted between majors (5.x took remaining_ok, 6.x
    # dropped it), so only options present in the installed version are passed.
    options = {"id": ident, "output": None, "quiet": True, "use_cookies": False}
    accepted = inspect.signature(gdown.download_folder).parameters
    options = {k: v for k, v in options.items() if k in accepted}
    if "remaining_ok" in accepted:
        options["remaining_ok"] = True

    copied = 0
    with tempfile.TemporaryDirectory() as tmp:
        gdown.download_folder(**{**options, "output": tmp})
        for source in sorted(Path(tmp).rglob("*")):
            if not source.is_file() or (DATA_DIR / source.name).exists():
                continue
            shutil.copy2(source, DATA_DIR / source.name)
            print(f"    + {source.name} ({source.stat().st_size / 1e6:.1f} MB)")
            copied += 1

    _synced = True
    print(f"  sync complete — {copied} file(s) added.")
    return copied


def _check_header(path: Path) -> None:
    expected = EXPECTED_HEADERS.get(path.name)
    if expected is None:
        return
    with open(path, encoding="utf-8-sig", newline="") as fh:
        header = next(csv.reader(fh), None)
    if header != expected:
        raise ValueError(
            f"{path.name} has an unexpected header {header!r} — the copy in "
            "data/ is stale or is not the file it claims to be. Delete it and "
            "re-sync, or regenerate it."
        )


def ensure_local(filename: str, *, required: bool = True) -> Path | None:
    """Path to the local copy, syncing the Drive folder if it isn't there.

    Returns None instead of raising when required=False and the file cannot be
    obtained, so a notebook can degrade to a partial run.
    """
    if filename not in DOWNLOADABLE:
        raise KeyError(
            f"{filename!r} is not one of the pipeline's downloadable inputs. "
            "If an earlier step produces it, use local_input() instead; "
            "otherwise add it to DOWNLOADABLE."
        )

    target = DATA_DIR / filename
    if not target.is_file():
        try:
            sync_folder()
        except RuntimeError as exc:
            return _missing(filename, str(exc), required)

    if not target.is_file():
        return _missing(
            filename, "not present in the Drive folder after a sync.", required
        )

    _check_header(target)
    return target


def local_input(filename: str, produced_by: str) -> Path:
    """Path to a file an earlier step of this pipeline wrote.

    Not downloadable by design: these are generated artifacts, so a Drive copy
    could silently override what the notebook just produced. Missing means the
    step that makes it has not been run.
    """
    path = DATA_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(
            f"{filename} not found in {DATA_DIR} — run {produced_by} first."
        )
    return path


def _missing(filename: str, reason: str, required: bool) -> None:
    """Raise or warn, depending on whether the caller can proceed without it."""
    message = (
        f"Pipeline input {filename!r} unavailable — {reason}\n"
        f"Place it manually at {DATA_DIR / filename} if the download can't work."
    )
    if required:
        raise FileNotFoundError(message)
    print(f"\n  WARNING: {message}\n")
