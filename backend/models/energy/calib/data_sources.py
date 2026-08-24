"""
Resolves the calibration's collected samples, downloading them from Drive on
first use.

The samples are deliberately not in git: they are a Trassenfinder extraction,
roughly 1,560 HTTP calls over 30-50 minutes, so a machine without them cannot
rebuild them in the course of a seed run. They travel through one Drive folder
instead, following the pattern of the stop pipeline's data_sources.py.

Two kinds of file, deliberately handled differently:

  ensure_local(name)
      Comes from outside this machine - the collected Trassenfinder samples.
      Downloaded when absent so 02 can run without re-querying the API.

  local_input(name, produced_by)
      Written by an earlier step of this calibration. Never downloaded: a stale
      Drive copy could silently override what the notebook just produced.
      Missing means that step has not been run, and the error says which.

A local file always wins. The sync only fills gaps, so re-running 01 overwrites
nothing and a hand-placed file is never clobbered.

Usage from a notebook in this directory:

    from data_sources import ensure_local
    samples = ensure_local("samples_all.csv")
"""

from __future__ import annotations

import csv
import inspect
import os
import shutil
import sys
import tempfile
from pathlib import Path

CALIB_DIR = Path(__file__).resolve().parent
SOURCES_DIR = CALIB_DIR / "sources"
DATA_DIR = CALIB_DIR / "data"
SEED_DIR = CALIB_DIR / "seed"

# backend/ on the path so a notebook launched from this directory can reach
# dev_env, which loads backend/docker/.env - the same file the containers read.
_BACKEND_ROOT = CALIB_DIR.parents[2]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

try:
    from dev_env import load_env_files

    load_env_files()
except ImportError:  # pragma: no cover - notebook run outside the repo
    print("  dev_env not importable - reading the folder id from the environment.")

FOLDER_ID_VAR = "ENERGY_DRIVE_FOLDER_ID"

# Files the folder is expected to provide. Listed so a typo fails loudly here
# rather than as a confusing "not in the folder" after a multi-minute sync.
DOWNLOADABLE = {
    "samples_ontd.csv",
    "samples_synthetic.csv",
    "samples_all.csv",
    "failures_ontd.csv",
    "failures_synthetic.csv",
}

_SAMPLE_HEADER = [
    "source",
    "route_name",
    "start_stop_name",
    "start_ds100",
    "end_stop_name",
    "end_ds100",
    "composition_id",
    "n_coaches",
    "weight_t",
    "length_m",
    "v_max_kmh",
    "energy_kwh",
    "distance_km",
    "travel_time_min",
]

_FAILURE_HEADER = [
    "source",
    "route_name",
    "start_ds100",
    "end_ds100",
    "composition_id",
    "error",
]

# Expected header per CSV, checked on use. A Drive permission error serves an
# HTML page with HTTP 200, so without this the calibration would cache and then
# parse a login page as if it were data.
EXPECTED_HEADERS: dict[str, list[str]] = {
    "samples_ontd.csv": _SAMPLE_HEADER,
    "samples_synthetic.csv": _SAMPLE_HEADER,
    "samples_all.csv": _SAMPLE_HEADER,
    "failures_ontd.csv": _FAILURE_HEADER,
    "failures_synthetic.csv": _FAILURE_HEADER,
}

_synced = False


def folder_id() -> str:
    return os.environ.get(FOLDER_ID_VAR, "").strip()


def sync_folder(*, force: bool = False) -> int:
    """Copy every folder file missing from data/ into it. Returns the count.

    Runs at most once per process unless forced. Downloads into a temporary
    directory and copies only what is absent, so an existing local file - one
    01 just wrote, or one placed by hand - is never overwritten.
    """
    global _synced
    if _synced and not force:
        return 0

    ident = folder_id()
    if not ident:
        raise RuntimeError(
            f"{FOLDER_ID_VAR} is not set - put the Drive folder id in "
            "backend/docker/.env, or run 01_source_extraction.ipynb to collect "
            "the samples locally."
        )
    try:
        import gdown
    except ImportError:
        raise RuntimeError(
            "gdown is needed to sync the Drive folder. Install it with "
            "`uv sync --extra dev`, or place the files in data/ by hand."
        ) from None

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"  syncing Drive folder {ident}...")

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
    print(f"  sync complete - {copied} file(s) added.")
    return copied


def _check_header(path: Path) -> None:
    expected = EXPECTED_HEADERS.get(path.name)
    if expected is None:
        return
    with open(path, encoding="utf-8-sig", newline="") as fh:
        header = next(csv.reader(fh), None)
    if header != expected:
        raise ValueError(
            f"{path.name} has an unexpected header {header!r} - the copy in "
            "data/ is stale or is not the file it claims to be. Delete it and "
            "re-sync, or regenerate it with 01_source_extraction.ipynb."
        )


def ensure_local(filename: str, *, required: bool = True) -> Path | None:
    """Path to the local copy, syncing the Drive folder if it isn't there.

    Returns None instead of raising when required=False and the file cannot be
    obtained, so a notebook can degrade to a partial run.
    """
    if filename not in DOWNLOADABLE:
        raise KeyError(
            f"{filename!r} is not one of the calibration's downloadable inputs. "
            "If 01 produces it, use local_input() instead; otherwise add it to "
            "DOWNLOADABLE."
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
    """Path to a file an earlier step of this calibration wrote.

    Not downloadable by design: these are generated artifacts, so a Drive copy
    could silently override what the notebook just produced. Missing means the
    step that makes it has not been run.
    """
    path = DATA_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(
            f"{filename} not found in {DATA_DIR} - run {produced_by} first."
        )
    return path


def source_input(filename: str) -> Path:
    """Path to a committed input under sources/.

    These travel with the repository: route lists and the composition table are
    small, hand-curated, and needed before anything can be collected.
    """
    path = SOURCES_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(
            f"{filename} not found in {SOURCES_DIR} - it should be committed."
        )
    return path


def _missing(filename: str, reason: str, required: bool) -> None:
    """Raise or warn, depending on whether the caller can proceed without it."""
    message = (
        f"Calibration input {filename!r} unavailable - {reason}\n"
        f"Place it manually at {DATA_DIR / filename}, or run "
        "01_source_extraction.ipynb to collect it."
    )
    if required:
        raise FileNotFoundError(message)
    print(f"\n  WARNING: {message}\n")
