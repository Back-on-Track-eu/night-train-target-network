"""
Seeds the Back-on-Track night train database.

Only schema DDL lives in sql/*.sql, loaded via sql_loader.
All seed data is plain Python dicts inserted via insert_rows(), sourced
from this file plus two derived CSV inputs: the calib seed CSVs
(regenerated from the calibration notebook, not committed) and
data/stop_seed_catalog.csv (the whole stop catalog, Drive-hosted and
downloaded here when absent — produced by the stop classification
pipeline, models/infrastructure/stops/step10_export_seed_stops.py).
Idempotent — each schema starts with DROP SCHEMA ... CASCADE.

Run order:
  1. admin
  2. input_params: sources → countries → service_classes → operators →
     operator_class_costs → coach_types → coach_type_classes →
     track_infrastructure_defaults → track_infrastructures →
     stop_infrastructure_defaults → stop_infrastructures →
  3. scenario: scenarios (base scenario pinning the version numbers seeded
     for the four infrastructure tables, plus one illustrative what-if
     scenario)
  4. proposals

Versioning note
---------------
Only the four infrastructure input_params tables (track_infrastructures,
track_infrastructure_defaults, stop_infrastructures,
stop_infrastructure_defaults) are versioned — "current" is entirely a
scenario.scenarios concept for these (see db/schema.py and db/README.md). A
version bump is a FULL-TABLE SNAPSHOT: editing one row duplicates every
other row of that table forward into the new version number.

Each seeded scenario (see the "scenario" section near the bottom of this
file, and models/scenarios/README.md for what they mean) pins its own
version number, in lockstep, across all four tables. The routing graph is
pinned the same way, via scenario.scenarios.routing_graph_key. Versions
run as a grid — three operating conditions on each of two networks:

  - versions 1, 2, 3 — Infra 2026 (today's network, routing graph
    infra_2026). Version 1 is the live default (is_current_base=TRUE) with
    track_hsr_allowed=False everywhere; version 2 flips that flag to True;
    version 3 additionally converges track_buffer_quota_per toward a
    best-practice benchmark (_with_optimized_timetable).
  - version 4 — the superseded infra-2026 revision, outside the grid.
  - versions 5, 6, 7 — Infra 2032 (the upgraded network, routing graph
    infra_2032), carrying the same three operating conditions in the same
    order.

Only track_infrastructures/track_infrastructure_defaults carry different
figures across the operating conditions; stop_infrastructures,
stop_infrastructure_defaults and passage_charges are duplicated
unchanged, since neither the HSR policy nor the timetable moves a stop or
crossing charge. The 2032 half of the grid is a copy of the 2026 half in
all five tables — an upgraded network is new track, and track lives in
the routing graph, not here.

Because each scenario owns a full, independent snapshot of all four
tables, comparing data across scenarios must go through resolved values,
not version-number equality — see test_04_versioning.py /
test_31_evaluation_content.py for the pattern.

NOT versioned — they're a catalog you add to, not history you edit. Each
row's natural id (operator_id, coach_type_id, composition_type_id) is
permanent; changing a value means seeding a new id, never editing a row
in place. See db/schema.py for the rationale.
"""

import gzip
import os
import sys
from pathlib import Path
from datetime import timedelta
from decimal import Decimal
import json

import psycopg2
from dotenv import load_dotenv

load_dotenv()

from sql_loader import load_sql

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from db.schema import STOP_NAME_LANGS, build_ddl

DB_HOST = os.environ["POSTGRES_HOST"]
DB_PORT = os.environ["POSTGRES_PORT"]
DB_NAME = os.environ["POSTGRES_DB"]
DB_USER = os.environ["POSTGRES_USER"]
DB_PASSWORD = os.environ["POSTGRES_PASSWORD"]


class _PgEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, timedelta):
            total = int(obj.total_seconds())
            h, rem = divmod(total, 3600)
            m, s = divmod(rem, 60)
            return f"{h:02d}:{m:02d}:{s:02d}"
        return super().default(obj)


def _dumps(obj) -> str:
    return json.dumps(obj, cls=_PgEncoder)


def insert_rows(cur, table: str, rows: list[dict]) -> None:
    if not rows:
        return
    columns = list(rows[0].keys())
    sql = (
        f"INSERT INTO {table} ({', '.join(columns)}) "
        f"VALUES ({', '.join(['%s'] * len(columns))})"
    )
    for row in rows:
        values = [
            _dumps(row[c]) if isinstance(row[c], (dict, list)) else row[c]
            for c in columns
        ]
        cur.execute(sql, values)


# ============================================================
# admin
# ============================================================

USERS = [
    {"display_name": "David", "email": "david@backontrack.eu", "is_verified": True},
    {"display_name": "Bjarne", "email": "bjarne@backontrack.eu", "is_verified": True},
    # Identity the integration test suite and manual scripts authenticate as,
    # so auto-persisted proposals from test runs are identifiable (and
    # cleanable) by owner — see tests/conftest.py: script_token.
    {
        "display_name": "test_script",
        "email": "test_script@dev.local",
        "is_verified": True,
    },
]

# ============================================================
# calibration seed CSVs
# ============================================================
# Operational parameters are exported by
# models/compositions/calib/02_calibration.ipynb (final cell) into
# calib/seed/*.csv and read here — update values by re-running the
# notebook, never by editing this file. Derivations:
# models/compositions/calib/CALIBRATION.md.

import csv
from collections import Counter
from pathlib import Path

CALIB_SEED_DIR = (
    Path(__file__).resolve().parents[2] / "models" / "compositions" / "calib" / "seed"
)


_CALIB_SEED_CSVS = (
    "operators.csv",
    "operator_class_costs.csv",
    "coach_types.csv",
    "coach_type_classes.csv",
    "composition_types.csv",
    "composition_type_coaches.csv",
    "class_cost_allocation.csv",
    "loco_types.csv",
    "operator_loco_costs.csv",
    "composition_type_locos.csv",
)


def _run_notebook_for_seed_csvs(
    nb_path: Path, workdir: Path, targets: Path, names: tuple[str, ...]
) -> None:
    """Execute a calibration notebook far enough to produce its seed CSVs.

    Calibration notebooks are the single source of truth: the seed CSVs are
    derived artifacts, not committed, and regenerating them here means a
    fresh container never runs against a stale number.

    Two filters keep this working inside the API container, which has no
    dev extras:

    - Cells importing pandas or matplotlib, or using pd./plt., are skipped.
      Detection is by code token rather than prose, so a comment mentioning
      pandas does not trip it.
    - Execution stops as soon as every target CSV exists. The compute and
      export cells always precede the document generator, so this skips
      regenerating a committed calibration document on every boot without
      needing the notebook to mark its own cells.
    """
    import json as _json
    import os as _os
    import re as _re

    print(f"  seed CSVs missing — regenerating from {nb_path.name}...")
    with open(nb_path, encoding="utf-8") as fh:
        nb = _json.load(fh)

    namespace: dict = {}
    cwd = _os.getcwd()
    _os.chdir(workdir)  # the export cells write relative paths
    try:
        for cell in nb["cells"]:
            if cell["cell_type"] != "code":
                continue
            src = "".join(cell["source"])
            if _re.search(
                r"^\s*(?:import|from)\s+(?:pandas|matplotlib)", src, _re.M
            ) or _re.search(r"\bpd\.|\bplt\.", src):
                continue
            try:
                exec(compile(src, f"<{nb_path.name}>", "exec"), namespace)
            except Exception as e:
                first_line = src.strip().splitlines()[0][:60]
                raise AssertionError(
                    f"{nb_path.name} cell starting {first_line!r} raised "
                    f"{type(e).__name__}: {e} — the compute/export cells "
                    "must stay stdlib-only AND self-contained (merging "
                    "their imports into a pandas cell makes the filter "
                    "skip them; see the notebook's stdlib-imports cell)"
                ) from e
            # Empty names means "run the whole notebook" — used for a
            # notebook that only produces inputs for the next one.
            if names and all((targets / name).is_file() for name in names):
                break
    finally:
        _os.chdir(cwd)

    missing = [name for name in names if not (targets / name).is_file()]
    assert not missing, (
        f"{nb_path.name} did not produce {missing} — its compute/export "
        "cells may have gained a pandas dependency; keep them stdlib-only "
        "(see the export cell's header comment)"
    )
    print(f"  seed CSVs regenerated from {nb_path.name}.")


def _ensure_seed_csvs(
    seed_dir: Path, names: tuple[str, ...], notebooks: tuple[Path, ...]
) -> None:
    """Regenerate a domain's seed CSVs from its notebooks when absent.

    notebooks run in order; only the last one writes the seed CSVs, but an
    earlier one may write files it reads (the TAC calibration reads the
    source register that 01 produces).
    """
    if all((seed_dir / name).is_file() for name in names):
        return
    for nb_path in notebooks:
        assert nb_path.is_file(), (
            f"seed CSVs missing and {nb_path} not found — cannot "
            "regenerate; restore the notebook"
        )
    for i, nb_path in enumerate(notebooks):
        _run_notebook_for_seed_csvs(
            nb_path,
            workdir=nb_path.parent,
            targets=seed_dir,
            # Only the last notebook is expected to produce the targets;
            # the earlier ones run to completion for their side effects.
            names=names if i == len(notebooks) - 1 else (),
        )


_ensure_seed_csvs(
    CALIB_SEED_DIR,
    _CALIB_SEED_CSVS,
    (CALIB_SEED_DIR.parent / "02_calibration.ipynb",),
)


def _read_seed_csv(seed_dir: Path, name: str, notebook: str) -> list[dict]:
    path = seed_dir / name
    assert path.is_file(), (
        f"missing {path} — run {notebook} top to bottom first (its export "
        "cell writes the seed CSVs)"
    )
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _read_calib_csv(name: str) -> list[dict]:
    return _read_seed_csv(
        CALIB_SEED_DIR, name, "models/compositions/calib/02_calibration.ipynb"
    )


# ============================================================
# TAC calibration seed CSVs
# ============================================================
# Track access charges per country, exported by
# models/infrastructure/tac/calib/02_tac_calibration.ipynb (seed export
# cell) after 01 has written the source register. Every value arrives as
# plain EUR at the 2032 evaluation year — the notebook converts currency
# and price basis exactly once, so nothing below does unit arithmetic.
# Derivations: models/infrastructure/tac/calib/TAC_CALIBRATION.md.

TAC_SEED_DIR = (
    Path(__file__).resolve().parents[2]
    / "models"
    / "infrastructure"
    / "tac"
    / "calib"
    / "seed"
)

_TAC_SEED_CSVS = (
    "track_tac.csv",
    "track_tac_default.csv",
    "passage_charges.csv",
    "sources.csv",
)

_ensure_seed_csvs(
    TAC_SEED_DIR,
    _TAC_SEED_CSVS,
    (
        TAC_SEED_DIR.parent / "01_source_extraction.ipynb",
        TAC_SEED_DIR.parent / "02_tac_calibration.ipynb",
    ),
)


def _read_tac_csv(name: str) -> list[dict]:
    return _read_seed_csv(
        TAC_SEED_DIR,
        name,
        "models/infrastructure/tac/calib/01_source_extraction.ipynb then 02_tac_calibration.ipynb",
    )


# Columns whose empty string is a real NULL — "this country does not levy
# this term" — and must never become 0.0. The loader's group substitution
# is what turns a wholly uncalibrated country into the EU median, and that
# has to stay a load-time decision (see DBDataLoader._row_to_track).
_TAC_NUMERIC_COLUMNS = (
    "track_tac_b_day",
    "track_tac_b_night",
    "track_tac_gamma",
    "track_tac_seat_km",
    "track_tac_per_stop",
    "track_tac_revenue_share",
    "track_tac_fixed_per_train_km",
    "track_tac_peak_multiplier",
    "track_tac_congestion_surcharge_eur_km",
)

_TAC_TIME_COLUMNS = (
    "track_tac_night_band_start",
    "track_tac_night_band_end",
    "track_tac_peak_band1_start",
    "track_tac_peak_band1_end",
    "track_tac_peak_band2_start",
    "track_tac_peak_band2_end",
)

_TAC_BOOL_COLUMNS = (
    "track_tac_night_full_if_accommodation",
    "track_tac_peak_weekdays_only",
)


def _tac_columns(row: dict) -> dict:
    """One calibration row as track-table column values, empty cells kept
    as NULL. source_id/change_log are dropped here — the FK is resolved
    against input_params.sources by seed_sources(), see _TAC_SOURCE_KEYS."""
    out: dict = {}
    for column in _TAC_NUMERIC_COLUMNS:
        out[column] = float(row[column]) if row[column] else None
    for column in _TAC_TIME_COLUMNS:
        out[column] = row[column] or None
    for column in _TAC_BOOL_COLUMNS:
        out[column] = row[column] == "True"
    out["track_tac_night_mode"] = row["track_tac_night_mode"] or "none"
    return out


_TAC_ROWS = {row["country_code"]: row for row in _read_tac_csv("track_tac.csv")}

TAC_BY_COUNTRY = {cc: _tac_columns(row) for cc, row in _TAC_ROWS.items()}

TAC_DEFAULT = _tac_columns(_read_tac_csv("track_tac_default.csv")[0])

# {country_code: register source_id} — resolved to a real FK after the
# sources table is inserted, since the FK is a SERIAL the CSV cannot know.
_TAC_SOURCE_KEYS = {
    cc: row["source_id"] for cc, row in _TAC_ROWS.items() if row["source_id"]
}

_TAC_CHANGE_LOGS = {
    cc: row["change_log"] for cc, row in _TAC_ROWS.items() if row["change_log"]
}

PASSAGE_CHARGES_RAW = _read_tac_csv("passage_charges.csv")

TAC_SOURCES = _read_tac_csv("sources.csv")


# ============================================================
# energy pricing calibration seed CSVs
# ============================================================
# Traction energy prices per country, exported by
# models/infrastructure/energy_pricing/calib/02_energy_pricing_calibration
# .ipynb (seed export cell) after 01 has written the source register. Same
# contract as the TAC block above: plain EUR at the 2032 evaluation year,
# currency and price basis converted exactly once in the notebook.
# Derivations:
# models/infrastructure/energy_pricing/calib/ENERGY_PRICING_CALIBRATION.md.

ENERGY_SEED_DIR = (
    Path(__file__).resolve().parents[2]
    / "models"
    / "infrastructure"
    / "energy_pricing"
    / "calib"
    / "seed"
)

_ENERGY_SEED_CSVS = (
    "track_energy.csv",
    "track_energy_default.csv",
    "sources.csv",
)

_ensure_seed_csvs(
    ENERGY_SEED_DIR,
    _ENERGY_SEED_CSVS,
    (
        ENERGY_SEED_DIR.parent / "01_source_extraction.ipynb",
        ENERGY_SEED_DIR.parent / "02_energy_pricing_calibration.ipynb",
    ),
)


def _read_energy_csv(name: str) -> list[dict]:
    return _read_seed_csv(
        ENERGY_SEED_DIR,
        name,
        "models/infrastructure/energy_pricing/calib/01_source_extraction.ipynb "
        "then 02_energy_pricing_calibration.ipynb",
    )


# Columns whose empty string is a real NULL. Unlike the TAC group these are
# never substituted from the defaults row: an empty night price means the
# country charges one rate around the clock, an empty catenary term means it
# levies no supply-equipment charge (see DBDataLoader._energy_components).
_ENERGY_NUMERIC_COLUMNS = (
    "track_energy_price_eur_kwh",
    "track_energy_price_night_eur_kwh",
    "track_energy_catenary_eur_train_km",
    "track_energy_catenary_eur_gross_tonne_km",
)

_ENERGY_TIME_COLUMNS = (
    "track_energy_night_band_start",
    "track_energy_night_band_end",
)


def _energy_columns(row: dict) -> dict:
    """One calibration row as track-table column values, empty cells kept as
    NULL. source_id/change_log are dropped here — the FK is resolved against
    input_params.sources by seed_sources(), see _ENERGY_SOURCE_KEYS."""
    out: dict = {c: float(row[c]) if row[c] else None for c in _ENERGY_NUMERIC_COLUMNS}
    out.update({c: row[c] or None for c in _ENERGY_TIME_COLUMNS})
    return out


_ENERGY_ROWS = {
    row["country_code"]: row for row in _read_energy_csv("track_energy.csv")
}

ENERGY_BY_COUNTRY = {cc: _energy_columns(row) for cc, row in _ENERGY_ROWS.items()}

# The fallback row carries the median day price and nothing else — a night
# band and a catenary charge are national particularities, so an
# uncalibrated country is priced without either rather than given an
# invented median (see the calibration document, Part IV).
ENERGY_DEFAULT = _energy_columns(_read_energy_csv("track_energy_default.csv")[0])

_ENERGY_SOURCE_KEYS = {
    cc: row["source_id"] for cc, row in _ENERGY_ROWS.items() if row["source_id"]
}

_ENERGY_CHANGE_LOGS = {
    cc: row["change_log"] for cc, row in _ENERGY_ROWS.items() if row["change_log"]
}

ENERGY_SOURCES = _read_energy_csv("sources.csv")


# ============================================================
# facility calibration seed CSVs
# ============================================================
# Shunting, stabling and hotel power per country, exported by
# models/infrastructure/facility/calib/02_facility_calibration.ipynb after 01
# has written the source register. Same contract as the TAC and energy blocks
# above: plain EUR at the 2032 evaluation year, both conversions done once in
# the notebook. Derivations:
# models/infrastructure/facility/calib/FACILITY_CALIBRATION.md.

FACILITY_SEED_DIR = (
    Path(__file__).resolve().parents[2]
    / "models"
    / "infrastructure"
    / "facility"
    / "calib"
    / "seed"
)

_FACILITY_SEED_CSVS = (
    "track_facility.csv",
    "track_facility_default.csv",
    "sources.csv",
)

_ensure_seed_csvs(
    FACILITY_SEED_DIR,
    _FACILITY_SEED_CSVS,
    (
        FACILITY_SEED_DIR.parent / "01_source_extraction.ipynb",
        FACILITY_SEED_DIR.parent / "02_facility_calibration.ipynb",
    ),
)


def _read_facility_csv(name: str) -> list[dict]:
    return _read_seed_csv(
        FACILITY_SEED_DIR,
        name,
        "models/infrastructure/facility/calib/01_source_extraction.ipynb "
        "then 02_facility_calibration.ipynb",
    )


_FACILITY_NUMERIC_COLUMNS = (
    "track_shunting_eur_event",
    "track_parking_eur_metre_day",
    "track_parking_eur_hour",
    "track_parking_eur_event",
    "track_parking_free_hours",
    "track_parking_hotel_power_eur_hour",
    "track_parking_eur_day",
)


def _facility_columns(row: dict) -> dict:
    """One calibration row as track-table column values. Only the rate column
    matching the basis carries a number; the others are NULL because the
    country does not price in that unit."""
    out: dict = {
        c: float(row[c]) if row[c] else None for c in _FACILITY_NUMERIC_COLUMNS
    }
    out["track_parking_basis"] = row["track_parking_basis"] or None
    return out


_FACILITY_ROWS = {
    row["country_code"]: row for row in _read_facility_csv("track_facility.csv")
}

FACILITY_BY_COUNTRY = {cc: _facility_columns(row) for cc, row in _FACILITY_ROWS.items()}

FACILITY_DEFAULT = _facility_columns(
    _read_facility_csv("track_facility_default.csv")[0]
)

_FACILITY_SOURCE_KEYS = {
    cc: row["source_id"] for cc, row in _FACILITY_ROWS.items() if row["source_id"]
}

_FACILITY_CHANGE_LOGS = {
    cc: row["change_log"] for cc, row in _FACILITY_ROWS.items() if row["change_log"]
}

FACILITY_SOURCES = _read_facility_csv("sources.csv")


# ============================================================
# route context calibration seed CSVs
# ============================================================
# Terrain, schedule supplement, dwell floor and high-speed access per country,
# exported by models/infrastructure/route_context/calib/
# 02_route_context_calibration.ipynb after 01 has written the source register
# and, where a database with a loaded ONTD snapshot was reachable, the
# observation set under sources/. Derivations:
# models/infrastructure/route_context/calib/ROUTE_CONTEXT_CALIBRATION.md.
#
# The only one of the four infrastructure domains with no money in it, so
# nothing here is converted or escalated — what travels is a terrain score, a
# fraction, two dwell floors and a flag.

ROUTE_CONTEXT_SEED_DIR = (
    Path(__file__).resolve().parents[2]
    / "models"
    / "infrastructure"
    / "route_context"
    / "calib"
    / "seed"
)

_ROUTE_CONTEXT_SEED_CSVS = (
    "track_route_context.csv",
    "track_route_context_default.csv",
    "sources.csv",
)

_ensure_seed_csvs(
    ROUTE_CONTEXT_SEED_DIR,
    _ROUTE_CONTEXT_SEED_CSVS,
    (
        ROUTE_CONTEXT_SEED_DIR.parent / "01_source_extraction.ipynb",
        ROUTE_CONTEXT_SEED_DIR.parent / "02_route_context_calibration.ipynb",
    ),
)


def _read_route_context_csv(name: str) -> list[dict]:
    return _read_seed_csv(
        ROUTE_CONTEXT_SEED_DIR,
        name,
        "models/infrastructure/route_context/calib/01_source_extraction.ipynb "
        "then 02_route_context_calibration.ipynb",
    )


def _minutes_to_interval(value: str) -> str | None:
    """The calibration carries a dwell floor in minutes; the column is an
    INTERVAL. Converted here rather than in the notebook so the calibration
    stays in the unit it reasons about."""
    if not value:
        return None
    total = int(round(float(value) * 60))
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def _route_context_columns(row: dict) -> dict:
    """One calibration row as track-table column values."""
    return {
        "track_terrain_category": row["track_terrain_category"] or None,
        "track_terrain_score": (
            float(row["track_terrain_score"]) if row["track_terrain_score"] else None
        ),
        "track_buffer_quota_per": (
            float(row["track_buffer_quota_per"])
            if row["track_buffer_quota_per"]
            else None
        ),
        "track_min_boarding_time": _minutes_to_interval(row["track_min_boarding_time"]),
        "track_min_alighting_time": _minutes_to_interval(
            row["track_min_alighting_time"]
        ),
        "track_hsr_allowed": (
            None
            if not row["track_hsr_allowed"]
            else row["track_hsr_allowed"].strip().lower() == "true"
        ),
    }


_ROUTE_CONTEXT_ROWS = {
    row["country_code"]: row
    for row in _read_route_context_csv("track_route_context.csv")
}

ROUTE_CONTEXT_BY_COUNTRY = {
    cc: _route_context_columns(row) for cc, row in _ROUTE_CONTEXT_ROWS.items()
}

ROUTE_CONTEXT_DEFAULT = _route_context_columns(
    _read_route_context_csv("track_route_context_default.csv")[0]
)

_ROUTE_CONTEXT_SOURCE_KEYS = {
    cc: row["source_id"] for cc, row in _ROUTE_CONTEXT_ROWS.items() if row["source_id"]
}

_ROUTE_CONTEXT_CHANGE_LOGS = {
    cc: row["change_log"]
    for cc, row in _ROUTE_CONTEXT_ROWS.items()
    if row["change_log"]
}

ROUTE_CONTEXT_SOURCES = _read_route_context_csv("sources.csv")


def _num(row: dict, *keys: str) -> dict:
    """Return a copy of row with the given keys coerced to float."""
    out = dict(row)
    for k in keys:
        out[k] = float(out[k])
    return out


# ============================================================
# sources
# ============================================================

SOURCES = [
    {
        "source_description": "B-o-T_targetnetwork_DB_v2.xlsx — illustrative placeholder values",
        "source_url": None,
        "source_date": "2025-06-01",
    },
    {
        "source_description": "Illustrative / internal estimate",
        "source_url": None,
        "source_date": None,
    },
]

SOURCES.append(
    {
        "source_description": (
            "Back-on-Track (2026) and various other sources — composition "
            "cost calibration; for further details see "
            "backend/models/compositions/calib/CALIBRATION.md"
        ),
        "source_url": "backend/models/compositions/calib/CALIBRATION.md",
        "source_date": "2026-07-21",
    }
)

# The infrastructure source registers — one row per document actually cited
# by a calibrated value, from the TAC and energy pricing calibrations. Seeded
# so every track access and energy number in the database points at the
# document it was read from.
#
# The three registers overlap heavily: a network statement typically prices a
# track access term, an energy term and a facility tariff, and each register
# describes the document in its own words. Deduplicated by the register's source_id, which is the
# document's identity — inserting two rows for one network statement would
# make provenance look richer than it is, and seed_sources() resolves the FK
# through the description text, which must therefore be unique. First
# register wins on wording; the section a value was actually read at lives in
# the per-value locator in each calibration's data/, not here.
_INFRA_SOURCE_ROWS: dict[str, dict] = {}
for _row in TAC_SOURCES + ENERGY_SOURCES + FACILITY_SOURCES + ROUTE_CONTEXT_SOURCES:
    _INFRA_SOURCE_ROWS.setdefault(_row["source_id"], _row)

SOURCES += [
    {
        "source_description": row["source_description"],
        "source_url": row["source_url"] or None,
        "source_date": row["source_date"] or None,
    }
    for row in _INFRA_SOURCE_ROWS.values()
]

# {register source_id: source_description} — the join key between the
# calibrations' own ids (AT-SNNB-2027) and the SERIAL source_id the database
# assigns. One map for both domains, since one document is one row.
INFRA_SOURCE_DESCRIPTIONS = {
    sid: row["source_description"] for sid, row in _INFRA_SOURCE_ROWS.items()
}

SRC_EXCEL = "B-o-T_targetnetwork_DB_v2.xlsx — illustrative placeholder values"
SRC_ILLUSTRATIVE = "Illustrative / internal estimate"
SRC_CALIBRATION = SOURCES[-1]["source_description"]


def fetch_source_ids(cur) -> dict[str, int]:
    cur.execute("SELECT source_id, source_description FROM input_params.sources")
    return {desc: sid for sid, desc in cur.fetchall()}


# ============================================================
# countries
# ============================================================

COUNTRIES = [
    {"country_code": "DE", "country_name": "Germany"},
    {"country_code": "AT", "country_name": "Austria"},
    {
        "country_code": "CH",
        "country_name": "Switzerland",
    },  # not an EU member — kept for existing CH routes
    {"country_code": "FR", "country_name": "France"},
    {"country_code": "BE", "country_name": "Belgium"},
    {"country_code": "DK", "country_name": "Denmark"},
    {"country_code": "SE", "country_name": "Sweden"},
    # Remaining EU27 members — added so _check_country_coverage() in
    # route_factory.py doesn't reject a route for merely transiting one of
    # these, even though none has real track_infrastructures figures yet
    # (see _TRACK_INFRA_PLACEHOLDER_COUNTRIES below: every field but
    # country_code is None, so TrackInfraCollection resolves every one of
    # them from the EU-average default — is_default stays False since a real
    # row exists, but expect a "using EU default" warning logged per field
    # per country).
    {"country_code": "BG", "country_name": "Bulgaria"},
    {"country_code": "HR", "country_name": "Croatia"},
    {"country_code": "CY", "country_name": "Cyprus"},
    {"country_code": "CZ", "country_name": "Czechia"},
    {"country_code": "EE", "country_name": "Estonia"},
    {"country_code": "FI", "country_name": "Finland"},
    {"country_code": "GR", "country_name": "Greece"},
    {"country_code": "HU", "country_name": "Hungary"},
    {"country_code": "IE", "country_name": "Ireland"},
    {"country_code": "IT", "country_name": "Italy"},
    {"country_code": "LV", "country_name": "Latvia"},
    {"country_code": "LT", "country_name": "Lithuania"},
    {"country_code": "LU", "country_name": "Luxembourg"},
    {"country_code": "MT", "country_name": "Malta"},
    {"country_code": "NL", "country_name": "Netherlands"},
    {"country_code": "PL", "country_name": "Poland"},
    {"country_code": "PT", "country_name": "Portugal"},
    {"country_code": "RO", "country_name": "Romania"},
    {"country_code": "SK", "country_name": "Slovakia"},
    {"country_code": "SI", "country_name": "Slovenia"},
    {"country_code": "ES", "country_name": "Spain"},
    # Non-EU countries the network reaches. NO/GB are Tier 2 routing scope
    # (deferred), the Western Balkans are transit countries on southeastern
    # corridors — all six get a border polygon and a placeholder track row,
    # so a route through them is attributed rather than rejected.
    {"country_code": "NO", "country_name": "Norway"},
    {"country_code": "GB", "country_name": "United Kingdom"},
    {"country_code": "BA", "country_name": "Bosnia and Herzegovina"},
    {"country_code": "RS", "country_name": "Serbia"},
    {"country_code": "ME", "country_name": "Montenegro"},
    {"country_code": "AL", "country_name": "Albania"},
    # Eastern and southeastern networks the ONTD catalogue reaches. Same
    # placeholder treatment as the blocks above. Present so their stops seed
    # at all (_build_stop_infrastructures() drops any catalog row whose
    # country is not here) and so their track kilometres are attributed
    # rather than falling to RailRouter's "UNK" sentinel, which
    # _check_country_coverage() exempts — an unmodelled country is silently
    # free of charges, which is worse than an approximate figure.
    {"country_code": "UA", "country_name": "Ukraine"},
    {"country_code": "TR", "country_name": "Türkiye"},
    {"country_code": "MD", "country_name": "Moldova"},
    {"country_code": "MK", "country_name": "North Macedonia"},
    # Liechtenstein has no stop of ours and never will — it is 10 km of the
    # Feldkirch–Buchs line through Schaan-Vaduz, i.e. the Arlberg corridor
    # every Zürich–Wien night train runs. Without a row those kilometres
    # carry no buffer quota and no track access charge, and nothing warns.
    {"country_code": "LI", "country_name": "Liechtenstein"},
    # Belarus and Russia are NOT modelled — no route may pass through
    # either, under any routing mode (project decision; BLOCKED_COUNTRIES
    # in models/route/model.py). These rows exist SOLELY to hold the
    # border polygons that rail_router's request-time exclusion rules are
    # built from (the graph-side `country` encoded value is not registered
    # by this OpenRailRouting fork, so the block cannot be baked into the
    # graph — see models/route/routing/docker/config.yml). Deliberately
    # absent from _TRACK_INFRA_PLACEHOLDER_COUNTRIES below: their
    # synthesized track rows keep has_row=False, so if the routing block
    # ever failed, _check_country_coverage() would still 422 the route
    # rather than silently pricing Belarusian kilometres. Do not "fix"
    # either omission.
    {"country_code": "BY", "country_name": "Belarus"},
    {"country_code": "RU", "country_name": "Russia"},
]


# Country border polygons — Marine Regions "Union of the ESRI Country
# shapefile and the Exclusive Economic Zones" v4 (Flanders Marine
# Institute, 2024, https://doi.org/10.14284/698, CC-BY 4.0), filtered to
# the rail-network countries above and reduced to one MultiPolygon each by
# scripts/export_country_geoms.py, which downloads the source from Drive
# and runs before this seed in both container entrypoints. Nothing is
# fetched here: seed.py stays stdlib-only, and the geo dependencies live
# with the script that needs them.
#
# The polygons cover land AND maritime zones. That is the point: with the
# retired land-only borders (Natural Earth admin-0, 1:110m) every belt,
# strait and tunnel crossing fell outside all polygons — Rødbyhavn and
# Puttgarden both sat 30-50km from the nearest one — so the "UNK" sentinel
# swallowed real track on both approaches, drawing no TAC, no buffer quota
# and no electricity price. Countries with no railway (MT, CY) are
# deliberately absent from the artifact and keep a NULL geometry: no
# polygon, no attribution, and no route can transit them.
COUNTRY_GEOMS_FILE = Path(
    os.environ.get(
        "COUNTRY_GEOMS_PATH",
        Path(__file__).resolve().parent / "data" / "country_geoms.geojson.gz",
    )
)

# Contract with scripts/export_country_geoms.py's _PROPERTY.
_COUNTRY_GEOMS_PROPERTY = "country_code"


def _country_geoms_warning(reason: str) -> None:
    print(
        "\n  ############################################################\n"
        f"  #  WARNING: country geometry artifact unavailable — {reason}.\n"
        "  #  Seeding all countries with NULL geometry: routing cannot\n"
        "  #  attribute distance to any country, so every segment falls\n"
        "  #  back to the UNK sentinel and no route can be evaluated.\n"
        "  #  It is normally built before this seed runs — check the\n"
        "  #  export_country_geoms.py output above for a failed Drive\n"
        "  #  download (EEZ_LAND_UNION_FILE_ID), or build it by hand:\n"
        "  #  uv run python scripts/export_country_geoms.py\n"
        "  ############################################################\n"
    )


def _read_country_geoms() -> dict[str, dict]:
    """{country_code: GeoJSON geometry}, or {} with a warning banner.

    Soft-failing by design, like the ONTD stop seed: seed.py runs in the
    container entrypoint under set -e, and a Drive outage upstream must not
    keep the API down. The banner plus test_02's geometry assertions make
    the gap loud instead.
    """
    if not COUNTRY_GEOMS_FILE.is_file():
        _country_geoms_warning(f"{COUNTRY_GEOMS_FILE} not found")
        return {}
    try:
        with gzip.open(COUNTRY_GEOMS_FILE, "rt", encoding="utf-8") as fh:
            collection = json.load(fh)
        features = {
            f["properties"][_COUNTRY_GEOMS_PROPERTY]: f["geometry"]
            for f in collection["features"]
        }
    except Exception as e:
        _country_geoms_warning(
            f"{COUNTRY_GEOMS_FILE.name} is unreadable ({type(e).__name__}: {e})"
        )
        return {}
    if not features:
        _country_geoms_warning(f"{COUNTRY_GEOMS_FILE.name} carries no features")
    return features


def seed_country_geometries(cur) -> None:
    """
    Populate input_params.countries.country_geom for every seeded country
    the artifact covers. Runs as UPDATEs after COUNTRIES has been inserted,
    since ST_GeomFromGeoJSON() isn't something insert_rows()'s plain-value
    INSERT can express.
    """
    features = _read_country_geoms()
    if not features:
        return
    seeded = {row["country_code"] for row in COUNTRIES}
    matched = 0
    for country_code, geometry in features.items():
        if country_code not in seeded:
            print(
                f"  WARNING: artifact carries '{country_code}', which is not "
                "in COUNTRIES — skipping."
            )
            continue
        cur.execute(
            """
            UPDATE input_params.countries
            SET country_geom = ST_SetSRID(ST_Multi(ST_GeomFromGeoJSON(%s)), 4326)
            WHERE country_code = %s
            """,
            (_dumps(geometry), country_code),
        )
        matched += 1
    print(f"  Matched {matched}/{len(seeded)} country geometries.")
    # Railless countries have no polygon by design — named, not warned about.
    ungeocoded = sorted(seeded - set(features))
    if ungeocoded:
        print(f"  No geometry (no rail network): {', '.join(ungeocoded)}.")


# ============================================================
# service_classes  (density = space consumption per place, Sleeper > Couchette > Seat)
# seat=1/64, couchette=1/20, sleeper=1/12
# ============================================================

# One service class per coach section (class_id = "<coach> - <section
# label>", workbook 2026-07-22); density retired — densities are derived
# per composition from section geometry.
# Class categories that do NOT make a train count as carrying night
# accommodation for tariff purposes. Everything a passenger can lie down in
# does; a dining car alone does not make a night train. The distinction
# drives the German whole-run night pricing — see
# models/infrastructure/tac/calib/TAC_CALIBRATION.md (DE section) and
# models/infrastructure/tac/calc_tac.py.
_DAY_CLASS_MAINS = frozenset({"Seat", "Catering"})

SERVICE_CLASSES = sorted(
    {
        (row["class_id"], row["class_main"].capitalize())
        for row in _read_calib_csv("coach_type_classes.csv")
    }
)
SERVICE_CLASSES = [
    {
        "service_class_id": cid,
        "service_class_main": cm,
        "service_class_is_night_accommodation": cm not in _DAY_CLASS_MAINS,
    }
    for cid, cm in SERVICE_CLASSES
]

# A catalog with no night accommodation at all would silently disable the
# German night widening — the failure this assert exists to catch, since
# nothing else about the evaluation would look wrong.
assert any(r["service_class_is_night_accommodation"] for r in SERVICE_CLASSES), (
    "no service class counts as night accommodation — check that "
    "coach_type_classes.csv still spells class_main as expected"
)


# ============================================================
# operators
# ============================================================

OPERATORS = [
    _num(
        row,
        "operator_driver_costs_eur_h",
        "operator_crew_costs_eur_h",
        "operator_driver_max_duty_h",
        "operator_crew_max_duty_h",
        "operator_driver_roster_eff_ref",
        "operator_crew_roster_eff_ref",
        "operator_relief_allowance_h",
        "operator_ebit_margin_per",
        "operator_financing_quota_per",
        "operator_var_overhead_per",
        "operator_fix_overhead_quota_per",
    )
    for row in _read_calib_csv("operators.csv")
]

# Calibrated per class_main (seat/couchette/sleeper/capsule); fanned out
# over every service_class_id of that main class. Catering classes carry
# no stockings entry (dropped in the calibration).
_CLASS_COST_BY_MAIN = {
    (row["operator_id"], row["class_main"].lower()): float(
        row["svc_stockings_eur_place"]
    )
    for row in _read_calib_csv("operator_class_costs.csv")
}

OPERATOR_CLASS_COSTS_RAW = [
    (op, sc["service_class_id"], rate)
    for (op, main), rate in _CLASS_COST_BY_MAIN.items()
    for sc in SERVICE_CLASSES
    if sc["service_class_main"].lower() == main
]

# ============================================================
# coach_types
# ============================================================

# Synthetic interim coach types from the calibration aggregates — one
# virtual coach per (composition, class present). Places and crew factors
# match the calibrated composition exactly (crew factors sum to
# attendants + 1.19 manager-equivalents); weights are allocated by places
# share. Replaced by the real per-coach workbook split later.
_COACHES = _read_calib_csv("coach_types.csv")

COACH_TYPES = [
    {
        "coach_type_id": row["coach_type_id"],
        "coach_type_operator_id": row["coach_type_operator_id"],
        "coach_type_weight_gross_t": float(row["coach_type_weight_gross_t"]),
        "coach_type_length_m": float(row["coach_type_length_m"]),
        "coach_type_weight_wo_service_t": float(row["coach_type_weight_wo_service_t"]),
        "coach_type_length_wo_service_m": float(row["coach_type_length_wo_service_m"]),
        "coach_type_has_wifi": row["coach_type_has_wifi"] == "True",
        "coach_type_bikes": 1 if row["coach_type_bikes"] == "True" else 0,
        "coach_type_climatization": row["coach_type_climatization"] == "True",
        "coach_type_plugs": row["coach_type_plugs"] == "True",
        "coach_type_crew_factor": float(row["coach_type_crew_factor"]),
        "coach_type_remarks": row["coach_type_remarks"],
    }
    for row in _COACHES
]

COACH_TYPE_CLASSES_RAW = [
    (
        row["coach_type_id"],
        row["class_id"],
        int(row["places"]),
        float(row["section_length_m"]),
        float(row["section_weight_t"]),
        float(row["section_crew_factor"]),
    )
    for row in _read_calib_csv("coach_type_classes.csv")
]

# ============================================================
# track infrastructure
# ============================================================
#
# Three full-table snapshots, one per scenario (see the "scenario" section
# near the bottom of this file, and models/scenarios/README.md for what
# each one means and why):
#   version 1 — Infra 2026: today's network, track_hsr_allowed=False
#     everywhere (night trains may not use high-speed lines).
#   version 2 — Infra 2026 + NT on HSR: identical to version 1 except
#     track_hsr_allowed=True everywhere.
#   version 3 — Infra 2026 + NT on HSR + optimised timetables: version 2
#     plus a reduced track_buffer_quota_per (see _with_optimized_timetable).
# A scenario pins one version NUMBER for the whole table, never a
# per-country flag — see db/schema.py (scenario.scenarios).
#
# "2026" names the physical NETWORK, not the price year: every monetary
# parameter here stays at the calibrated 2032 evaluation-year basis in all
# three. The 2032 NETWORK scenarios carry the same figures and differ only
# in the routing graph they pin (see the version grid below).


# ------------------------------------------------------------------
# Scenario version numbering
# ------------------------------------------------------------------
# One version number per scenario, shared across all five versioned
# tables, and every table snapshots itself once per version — never a
# partial diff (db/README.md). The same three OPERATING CONDITIONS are
# snapshotted once per NETWORK, which makes the numbering a grid rather
# than a sequence:
#
#                 baseline   + NT on HSR   + NT on HSR + opt. timetables
#   infra_2026       1            2                   3
#   infra_2032       5            6                   7
#
# Version 4 sits outside the grid: it is the SUPERSEDED revision of the
# infra-2026 baseline (Germany's pre-correction track access rates), not
# a fourth operating condition — see _TRACK_INFRA_V4_OVERRIDES.
#
# The two rows of the grid are byte-identical in these tables. What makes
# a 2032 scenario different is the routing graph it pins, which is where
# an upgraded network lives — see models/scenarios/README.md, including
# the passage-charge gap that follows from copying the table forward
# unchanged.
INFRA_VERSIONS = (1, 2, 3, 4, 5, 6, 7)

# The operating conditions each version carries. Version 4 mirrors
# version 1 here; its own difference is applied separately.
_HSR_ALLOWED_BY_VERSION = {
    1: False,
    2: True,
    3: True,
    4: False,
    5: False,
    6: True,
    7: True,
}
_OPT_TIMETABLE_VERSIONS = frozenset({3, 7})
_SUPERSEDED_VERSION = 4

# 2032 default row. track_hsr_allowed is set per-version below (see
# _build_track_infra_defaults) rather than baked in here.
_TRACK_INFRA_DEFAULT_2032 = {
    "track_infra_default_key": "_default",
    "track_tac_eur_train_km": 4.50,
    # Qualified assumption: schedule buffer quotas across European networks
    # realistically sit at 30-50% of pure driving time (construction sites,
    # mixed-traffic congestion, temporary speed restrictions, node dwell
    # creep); 0.40 is the band's midpoint, used for every country without
    # an explicit row. The per-country rows below differentiate within the
    # band — see the comment on each.
    # TODO: differentiate buffer_quota_per by TIME OF DAY — congestion is
    # daypart-dependent (after ~05:00 the morning rush builds, while the
    # night hours most night-train legs actually run in are far emptier),
    # so a flat per-country quota over-pads genuine night legs and
    # under-pads early-morning arrival legs. Needs a schema change
    # (per-country time bands) plus route-model work to apply the quota
    # per leg by clock time — see OPEN_TODOS["buffer_quota_time_of_day"]
    # in models/route/version.py before starting.
}

# --- Scenario shaping helpers ------------------------------------------
#
# Defined here, above the first caller: _build_track_infra_defaults()
# runs at import time and the default row is built before the
# per-country rows below.
#
# Optimised-timetable scenario (version 3)
#
# PROVISIONAL — the two constants below are an assumption, not yet a
# calibration. models/scenarios/README.md states the derivation, the
# weakness, and the re-calibration that settles them; nothing else in the
# repository reads them.
#
# track_buffer_quota_per is not a pure timetable buffer. It is the whole
# schedule supplement measured against the router's passage time, and it
# contains four things: pathing and construction allowance, margin because
# a night train does not hold priority, speed the train cannot sustain,
# and dynamics the model misses (route_context/calib's
# ROUTE_CONTEXT_CALIBRATION.md §3). Better timetabling acts on the first
# two only, so this scenario must NOT scale the quota as a whole — doing
# that would also optimise away the router's own error and produce
# fictionally fast trains.
#
# What it does instead: converge each country toward a best-practice
# benchmark. Austria's 0.346 (56 ONTD legs, the strongest-evidence low
# value) is a network where night trains are already well-pathed AND the
# router models the line speeds well, so nothing below it is reachable by
# timetabling alone. A quarter of each country's excess above that floor
# is removed — a median cut of 3.9 pp, and a country already at or below
# the benchmark is left untouched.
OPT_TT_BENCHMARK_QUOTA = 0.35
OPT_TT_EXCESS_REDUCTION = 0.25


def _with_hsr_allowed(row: dict, hsr_allowed: bool) -> dict:
    """Override track_hsr_allowed on a row, unless it's None (the 21
    EU27-placeholder countries deliberately resolve every field from the
    default row — see _TRACK_INFRA_CANONICAL_ROWS below)."""
    if row["track_hsr_allowed"] is None:
        return row
    return {**row, "track_hsr_allowed": hsr_allowed}


def _with_optimized_timetable(row: dict) -> dict:
    """Reduce track_buffer_quota_per toward OPT_TT_BENCHMARK_QUOTA.

    None is passed through for the same reason _with_hsr_allowed() passes
    it through: a placeholder country resolves the field from the defaults
    row, which this function has already been applied to.
    """
    quota = row["track_buffer_quota_per"]
    if quota is None or quota <= OPT_TT_BENCHMARK_QUOTA:
        return row
    reduced = OPT_TT_BENCHMARK_QUOTA + (quota - OPT_TT_BENCHMARK_QUOTA) * (
        1 - OPT_TT_EXCESS_REDUCTION
    )
    return {**row, "track_buffer_quota_per": round(reduced, 3)}


def _build_track_infra_defaults() -> list[dict]:
    """The EU-average fallback row, once per scenario version.

    The TAC component group is the calibrated European median (see
    TAC_DEFAULT) and is identical in all three: the 2026 deprecated
    snapshot predates the TAC calibration entirely, and inventing a
    historical median for it would be worse than reusing the current one.
    The energy group (ENERGY_DEFAULT) is the same story and carries the
    median day price only — no night band, no catenary charge, since
    neither is a gap to fill. The facility group (FACILITY_DEFAULT) carries
    the European default directly rather than a median of the calibrated
    countries: for seventeen of the twenty-eight that default IS the
    calibration, so a median over them would re-derive it with extra steps.
    The route context group (ROUTE_CONTEXT_DEFAULT) carries the European
    ONTD-weighted schedule supplement and the median terrain band — the
    fallback every placeholder country resolves to, since those rows are left
    NULL on purpose.

    The versions differ exactly as the per-country rows do: HSR permission
    and the optimised-timetable buffer, per the version grid above.
    Everything else is byte-identical across all seven — including v4,
    the superseded infra-2026 revision, which differs from v1 only in
    Germany's own row and so takes a plain copy of the fallback.
    """
    base = {
        **_TRACK_INFRA_DEFAULT_2032,
        **TAC_DEFAULT,
        **ENERGY_DEFAULT,
        **FACILITY_DEFAULT,
        **ROUTE_CONTEXT_DEFAULT,
    }
    rows = []
    for version in INFRA_VERSIONS:
        # Set directly rather than through _with_hsr_allowed(): the
        # fallback row starts without a track_hsr_allowed to flip (see
        # _TRACK_INFRA_DEFAULT_2032), and its value is never NULL — it IS
        # what a country row's NULL resolves to.
        row = {**base, "track_hsr_allowed": _HSR_ALLOWED_BY_VERSION[version]}
        if version in _OPT_TIMETABLE_VERSIONS:
            row = _with_optimized_timetable(row)
        rows.append({**row, "track_infra_default_version": version})
    return rows


TRACK_INFRA_DEFAULTS = _build_track_infra_defaults()

# Canonical per-country dataset (all 28 countries) — hsr_allowed here is
# irrelevant, it's overridden per-version below (True for the 2026 and
# 2032+HSR snapshots, False for the 2032 no-HSR snapshot).
_TRACK_INFRA_CANONICAL_ROWS = [
    {
        "country_code": "DE",
        "track_infra_version": 2,
        "track_tac_eur_train_km": 5.40,
        # worst long-distance punctuality of the major networks, Generalsanierung
        # construction backlog, dense mixed traffic
    },
    {
        "country_code": "AT",
        "track_infra_version": 2,
        "track_tac_eur_train_km": 4.20,
        # high ÖBB punctuality, well-maintained network; Alpine corridors and the Wien
        # node keep it above the floor
    },
    {
        "country_code": "CH",
        "track_infra_version": 2,
        "track_tac_eur_train_km": 6.80,
        # best punctuality in Europe — dense but rigorously timetabled; band floor
    },
    {
        "country_code": "FR",
        "track_infra_version": 2,
        "track_tac_eur_train_km": 4.60,
        # moderate punctuality; maintenance backlog on the conventional (non-LGV)
        # network night trains use
    },
    {
        "country_code": "BE",
        "track_infra_version": 2,
        "track_tac_eur_train_km": 5.10,
        # dense, congested network around the Brussels node, frequent engineering
        # works
    },
    {
        "country_code": "DK",
        "track_infra_version": 2,
        "track_tac_eur_train_km": 4.80,
        # ERTMS/signalling programme disruptions, Storebælt corridor bottleneck
    },
    # SE keeps a NULL flat TAC as the is_default test fixture. Its parking and
    # shunting NULLs below are overwritten by _apply_facility_calibration() —
    # Sweden is calibrated, and a fixture is not a reason to unprice a country.
    # The TAC fixture survives because the flat column is display-only.
    {
        "country_code": "SE",
        "track_infra_version": 2,
        "track_tac_eur_train_km": None,
        "track_parking_eur_day": None,
        "track_shunting_eur_event": None,
        # long single-track stretches, freight mixing, winter operations
    },
]

# Countries with no calibrated figures yet: every field None, resolved
# entirely from the EU-average default (track_infrastructure_defaults).
# The row exists so _check_country_coverage() in route_factory.py doesn't
# reject a route for merely transiting one of these (is_default stays
# False — a row exists — but every field logs a "using EU default" warning
# the first time it's resolved). Listed as codes rather than 27 identical
# dicts: adding a country is a one-token edit, and there is no per-country
# value here to get out of step.
_TRACK_INFRA_PLACEHOLDER_COUNTRIES = (
    # Remaining EU27 members
    "BG",
    "HR",
    "CY",
    "CZ",
    "EE",
    "FI",
    "GR",
    "HU",
    "IE",
    "IT",
    "LV",
    "LT",
    "LU",
    "MT",
    "NL",
    "PL",
    "PT",
    "RO",
    "SK",
    "SI",
    "ES",
    # Non-EU: Tier 2 routing scope (NO, GB) and southeastern transit
    "NO",
    "GB",
    "BA",
    "RS",
    "ME",
    "AL",
    # Eastern/southeastern networks and the Arlberg transit country — see
    # the matching block in COUNTRIES above.
    "UA",
    "TR",
    "MD",
    "MK",
    "LI",
)

_TRACK_INFRA_PLACEHOLDER_FIELDS = dict.fromkeys(
    (
        "track_tac_eur_train_km",
        "track_parking_eur_day",
        "track_shunting_eur_event",
        "track_energy_price_eur_kwh",
        "track_terrain_category",
        "track_terrain_score",
        "track_hsr_allowed",
        "track_min_boarding_time",
        "track_min_alighting_time",
        "track_buffer_quota_per",
    )
)

_TRACK_INFRA_CANONICAL_ROWS += [
    {
        "country_code": country_code,
        "track_infra_version": 2,
        **_TRACK_INFRA_PLACEHOLDER_FIELDS,
    }
    for country_code in _TRACK_INFRA_PLACEHOLDER_COUNTRIES
]

# The calibration names the United Kingdom "UK"; the database uses the
# ISO 3166-1 alpha-2 code everywhere. One alias, declared once.
_TAC_COUNTRY_ALIASES = {"UK": "GB"}


def _apply_tac_calibration(rows: list[dict]) -> None:
    """Merge the calibrated TAC components onto the canonical country rows,
    in place.

    A country the calibration does not cover keeps every component NULL,
    which the loader reads as "no rate term at all" and resolves to the
    EU-median group — the same treatment as a country with no row.
    """
    calibrated = {
        _TAC_COUNTRY_ALIASES.get(cc, cc): values
        for cc, values in TAC_BY_COUNTRY.items()
    }
    change_logs = {
        _TAC_COUNTRY_ALIASES.get(cc, cc): note for cc, note in _TAC_CHANGE_LOGS.items()
    }
    for row in rows:
        cc = row["country_code"]
        row.update(calibrated.get(cc, TAC_UNCALIBRATED))
        if cc in change_logs:
            row["change_log"] = change_logs[cc]


# Every component NULL — what an uncalibrated country carries, so the
# column set stays uniform across the table rather than some rows silently
# lacking keys.
TAC_UNCALIBRATED = {
    **dict.fromkeys(_TAC_NUMERIC_COLUMNS),
    **dict.fromkeys(_TAC_TIME_COLUMNS),
    **dict.fromkeys(_TAC_BOOL_COLUMNS, False),
    "track_tac_night_mode": "none",
}

# Every energy column NULL — what a country the calibration does not cover
# carries, so the column set stays uniform across the table rather than some
# rows silently lacking keys (insert_rows() takes its column list from the
# first row).
ENERGY_UNCALIBRATED = {
    **dict.fromkeys(_ENERGY_NUMERIC_COLUMNS),
    **dict.fromkeys(_ENERGY_TIME_COLUMNS),
}


def _apply_energy_calibration(rows: list[dict]) -> None:
    """Merge the calibrated energy prices onto the canonical country rows,
    in place.

    A country the calibration does not cover keeps every energy column NULL.
    For the day price the loader then substitutes the EU median, as it does
    for any missing legacy parameter; the night and catenary columns stay
    empty, which the cost model reads as "not levied" rather than as missing
    data — see DBDataLoader._energy_components().
    """
    calibrated = {
        _TAC_COUNTRY_ALIASES.get(cc, cc): values
        for cc, values in ENERGY_BY_COUNTRY.items()
    }
    change_logs = {
        _TAC_COUNTRY_ALIASES.get(cc, cc): note
        for cc, note in _ENERGY_CHANGE_LOGS.items()
    }
    for row in rows:
        cc = row["country_code"]
        row.update(calibrated.get(cc, ENERGY_UNCALIBRATED))
        if cc in change_logs:
            # A country calibrated by both domains keeps both notes: the TAC
            # merge below may already have written one.
            existing = row.get("change_log")
            row["change_log"] = (
                f"{existing} {change_logs[cc]}" if existing else change_logs[cc]
            )


_apply_tac_calibration(_TRACK_INFRA_CANONICAL_ROWS)
_apply_energy_calibration(_TRACK_INFRA_CANONICAL_ROWS)


# Every facility column NULL — what a country the calibration does not cover
# carries. The loader then resolves the whole group from the defaults row,
# since a NULL basis means "no facility figures for this country" rather than
# "no charge levied" (that is the documented basis 'none').
FACILITY_UNCALIBRATED = {
    **dict.fromkeys(_FACILITY_NUMERIC_COLUMNS),
    "track_parking_basis": None,
}


def _apply_facility_calibration(rows: list[dict]) -> None:
    """Merge the calibrated shunting and stabling figures onto the canonical
    country rows, in place."""
    calibrated = {
        _TAC_COUNTRY_ALIASES.get(cc, cc): values
        for cc, values in FACILITY_BY_COUNTRY.items()
    }
    change_logs = {
        _TAC_COUNTRY_ALIASES.get(cc, cc): note
        for cc, note in _FACILITY_CHANGE_LOGS.items()
    }
    for row in rows:
        cc = row["country_code"]
        row.update(calibrated.get(cc, FACILITY_UNCALIBRATED))
        if cc in change_logs:
            existing = row.get("change_log")
            row["change_log"] = (
                f"{existing} {change_logs[cc]}" if existing else change_logs[cc]
            )


_apply_facility_calibration(_TRACK_INFRA_CANONICAL_ROWS)


def _apply_route_context_calibration(rows: list[dict]) -> None:
    """Merge the calibrated route-context values onto the canonical country
    rows, in place.

    The placeholder countries are skipped on purpose. Their rows carry None in
    every one of these fields as a deliberate fixture — they exist to prove
    that field-by-field resolution from the defaults row works, and
    _with_hsr_allowed() reads a None track_hsr_allowed as the marker for
    "leave this row alone" when building the v1 and v3 snapshots. Filling them
    would both destroy the fixture and silently flip those countries onto
    scenario-specific HSR permissions they were never meant to have. They
    resolve to the defaults row, which is itself calibrated.
    """
    calibrated = {
        _TAC_COUNTRY_ALIASES.get(cc, cc): values
        for cc, values in ROUTE_CONTEXT_BY_COUNTRY.items()
    }
    change_logs = {
        _TAC_COUNTRY_ALIASES.get(cc, cc): note
        for cc, note in _ROUTE_CONTEXT_CHANGE_LOGS.items()
    }
    for row in rows:
        cc = row["country_code"]
        if cc in _TRACK_INFRA_PLACEHOLDER_COUNTRIES or cc not in calibrated:
            continue
        row.update(calibrated[cc])
        if cc in change_logs:
            existing = row.get("change_log")
            row["change_log"] = (
                f"{existing} {change_logs[cc]}" if existing else change_logs[cc]
            )


_apply_route_context_calibration(_TRACK_INFRA_CANONICAL_ROWS)

# Level the change_log key across every row. insert_rows() takes its column
# list from the FIRST row, so a key present on some rows and not others either
# vanishes from the INSERT or raises KeyError, depending purely on which
# country happens to be first — and both merges above write change_log only
# where their calibration carries a note.
for _row in _TRACK_INFRA_CANONICAL_ROWS:
    _row.setdefault("change_log", None)


# Version 4 — the SUPERSEDED revision of the infra-2026 lineage: identical
# to v1 except Germany still carries its pre-correction track access rates.
# Not a fourth scenario a user can pick (is_current_scenario=FALSE, so it
# lands in the API's historical_scenarios group); it is the lineage's own
# history, and the only snapshot in the seed whose TARIFFS differ from the
# base. That makes it what the scenario-override tests pin to — the HSR
# and optimised-timetable scenarios differ in routing and timetabling, not
# in charges, so neither can prove that pinning a scenario_id actually
# swaps a cost parameter.
#
# track_tac_eur_train_km is display only — the cost model prices from the
# components, so this snapshot has to move a COMPONENT to differ in cost at
# all, which is what track_tac_b_night does (Germany levies no day rate).
# Scaled by the same 3.10/5.40 ratio the flat figure carries, so the two
# tell one story rather than drifting apart.
_V4_DE_TAC_RATIO = 3.10 / 5.40

_TRACK_INFRA_V4_OVERRIDES = {
    "DE": {
        "track_tac_eur_train_km": 3.10,
        "track_tac_b_night": round(
            TAC_BY_COUNTRY["DE"]["track_tac_b_night"] * _V4_DE_TAC_RATIO, 8
        ),
    },
}


def _build_track_infrastructures() -> list[dict]:
    """Every country's row at every version — one complete snapshot per
    scenario, per the version grid at the top of this section.

    Versions 1-3 and 5-7 are the same three operating conditions applied
    to the same canonical rows, so the 2026 and 2032 halves of the grid
    come out identical here: a 2032 scenario differs by the routing graph
    it pins, not by a value in this table. Version 4 is the superseded
    infra-2026 revision — version 1 plus Germany's pre-correction rates.
    """
    rows = []
    for version in INFRA_VERSIONS:
        for row in _TRACK_INFRA_CANONICAL_ROWS:
            built = _with_hsr_allowed(row, _HSR_ALLOWED_BY_VERSION[version])
            if version in _OPT_TIMETABLE_VERSIONS:
                built = _with_optimized_timetable(built)
            built = {**built, "track_infra_version": version}
            if version == _SUPERSEDED_VERSION:
                built.update(_TRACK_INFRA_V4_OVERRIDES.get(row["country_code"], {}))
            rows.append(built)
    return rows


TRACK_INFRASTRUCTURES = _build_track_infrastructures()

# ============================================================
# stop infrastructure
# ============================================================
#
# Three full-table snapshots, one per scenario — same lockstep numbering
# as track infrastructure above (1 = Infra 2026, 2 = + NT on HSR,
# 3 = + optimised timetables). Stop charges depend on neither the HSR
# policy nor the timetable, so all three versions carry byte-identical
# values; only the version number differs, satisfying "each scenario holds
# its own infrastructure rows" without inventing an artificial value
# difference.

_STOP_INFRA_DEFAULT_CANONICAL = [
    # global default (country_code NULL)
    {"country_code": None, "stop_charge_eur": 11.28},
]


# The whole stop catalog: every stop the app can plan through. A derived
# artifact, Drive-hosted (not in the repo — no large data in git):
# regenerated by models/infrastructure/stops/step10_export_seed_stops.py,
# which unions the current night train stops (step 5) with the manual
# metropolitan/tourism/ferry additions (step 6), then uploaded to Drive as
# a new version of the same file. The seed downloads it once into
# db/dev/data/ when the local copy is absent; STOP_SEED_FILE_ID (env)
# overrides the file id without a code change, same pattern as
# ONTD_WORKBOOK_ID.
# Seeding the full catalog up front is what keeps the snapshot versions
# immutable at runtime: the retired alternative (db/ontd/stop_mapping.py
# minting missing stops during the bootstrap) mutated pinned versions,
# breaking the compute cache's scenario-pin invariant — and never
# survived a reseed anyway.
STOP_SEED_CSV = Path(__file__).resolve().parent / "data" / "stop_seed_catalog.csv"
STOP_SEED_FILE_ID = os.environ.get(
    "STOP_SEED_FILE_ID", "1QfkYrX5Fc5N0JqFLx5FWEaaZ6z0YCM6c"
)

# Contract with step10_export_seed_stops.py's output columns — also the
# validation gate for downloads (a Drive permission error returns an HTML
# page, which must not be seeded or cached as if it were the CSV). Exact
# match, full width: catalog and seed move in lockstep, and every column
# is consumed (the interim prefix check from the schema transition is
# retired).
_STOP_SEED_CSV_COLUMNS = [
    "stop_id",
    "stop_name",
    "country_code",
    "stop_timezone",
    "stop_lat",
    "stop_lon",
    "stop_charge_eur",
    "stop_charge_vat_rate_per",
    "stop_charge_incl_vat_eur",
    "stop_charge_basis",
    "stop_charge_price_basis_year",
    "stop_charge_class",
    "stop_charge_source",
    "provenance",
    # Which routing-graph infrastructure version(s) the stop belongs to
    # ("infra-2026;infra-2032", "infra-2032", "infra-2026"), tagged in step 6
    # of the stop pipeline. Read for the header contract only: every stop
    # still seeds into every snapshot version below. Consuming it — a stop
    # that exists only in the 2032 graph must not be selectable against the
    # 2026 one — is a separate work package.
    "infra_versions",
    "name_latin",
    "name_ascii",
    "uic_ref",
    *(f"country_{lang}" for lang in STOP_NAME_LANGS),
    "city",
    "city_osm_id",
    *(f"city_{lang}" for lang in STOP_NAME_LANGS),
    "gauges",
    "gauge_source",
]

_STOP_SEED_CHANGE_LOG = (
    "seeded from the stop classification pipeline "
    "(models/infrastructure/stops, step 10) — charge resolves via country/"
    "global default until real station charge data lands"
)


def _stop_seed_warning(reason: str) -> None:
    print(
        "\n  ############################################################\n"
        f"  #  WARNING: stop seed CSV unavailable — {reason}.\n"
        "  #  Seeding NO stops: every route will report unmatched stops\n"
        "  #  and most planning tests will fail. Regenerate with\n"
        "  #  models/infrastructure/stops/step10_export_seed_stops.py\n"
        "  #  (upload to Drive) or place the file at\n"
        "  #  db/dev/data/stop_seed_catalog.csv.\n"
        "  ############################################################\n"
    )


# ---------------------------------------------------------------------------
# route_cache — precomputed route segments (optional, one file per graph)
# ---------------------------------------------------------------------------
# Produced by scripts/precompute_route_segments.py (--finalize) as
# route_segments_<graph_key>.csv.gz; local under db/dev/data/, or Drive-
# hosted with ROUTE_SEGMENTS_FILE_ID_<KEY> (the graph naming contract in
# models/route/routing/rail_router.py). Optional by design: no file ->
# empty cache -> every pair live-routes once and stores itself. Dev only:
# servers load via the script's --load; a dev reseed drops route_cache and
# starts from these files again.
ROUTE_SEGMENTS_DIR = Path(__file__).resolve().parent / "data"
ROUTE_SEGMENTS_GLOB = "route_segments_*.csv.gz"
_ROUTE_SEGMENTS_ID_PREFIX = "ROUTE_SEGMENTS_FILE_ID_"


def _download_route_segments(graph_key: str) -> Path | None:
    """Fetch the Drive-hosted file for one graph if an id is configured —
    soft-failing like _download_stop_seed()."""
    import urllib.request

    file_id = os.environ.get(f"{_ROUTE_SEGMENTS_ID_PREFIX}{graph_key.upper()}", "")
    if not file_id:
        return None
    target = ROUTE_SEGMENTS_DIR / f"route_segments_{graph_key}.csv.gz"
    url = (
        "https://drive.usercontent.google.com/download"
        f"?id={file_id}&export=download&confirm=t"
    )
    print(f"  route segments for '{graph_key}' — downloading (id={file_id})...")
    try:
        with urllib.request.urlopen(url, timeout=600) as resp:
            data = resp.read()
    except Exception as e:
        print(f"  download failed ({type(e).__name__}: {e}).")
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def seed_route_segments() -> None:
    """Bulk-load every route_segments_<graph_key>.csv.gz present (plus any
    Drive-configured graph) through RouteSegmentRepository.load_csv() —
    its own connection, so this runs after the main commit like
    seed_example_proposal()."""
    from adapters.route_segment_repository import RouteSegmentRepository

    configured = {
        var[len(_ROUTE_SEGMENTS_ID_PREFIX) :].lower()
        for var, value in os.environ.items()
        if var.startswith(_ROUTE_SEGMENTS_ID_PREFIX) and value.strip()
    }
    for graph_key in configured:
        if not (ROUTE_SEGMENTS_DIR / f"route_segments_{graph_key}.csv.gz").is_file():
            _download_route_segments(graph_key)

    files = sorted(ROUTE_SEGMENTS_DIR.glob(ROUTE_SEGMENTS_GLOB))
    if not files:
        print("  route_cache: no route_segments_*.csv.gz — cache fills from traffic.")
        return
    repo = RouteSegmentRepository()
    try:
        for path in files:
            graph_key = path.name[len("route_segments_") : -len(".csv.gz")]
            meta_path = path.with_name(f"route_segments_{graph_key}.meta.json")
            if meta_path.is_file():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                repo.sync_graph_import(graph_key, meta.get("import_date"))
            inserted = repo.load_csv(path, graph_key)
            print(f"  route_cache [{graph_key}]: {inserted} segment(s) loaded.")
    finally:
        repo.close()


def _download_stop_seed() -> bool:
    """Fetch the Drive-hosted CSV into db/dev/data/ — returns success.
    Soft-failing by design: seed.py runs in the container entrypoint
    under set -e, and a Drive outage must not keep the API down (the
    warning banner plus test_02's catalog assertions make the gap loud
    instead)."""
    import io
    import urllib.request

    url = (
        "https://drive.usercontent.google.com/download"
        f"?id={STOP_SEED_FILE_ID}&export=download&confirm=t"
    )
    print(
        "  ONTD stop seed CSV not found locally — downloading "
        f"(id={STOP_SEED_FILE_ID})..."
    )
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            text = resp.read().decode("utf-8-sig")
    except Exception as e:
        _stop_seed_warning(f"download failed ({type(e).__name__}: {e})")
        return False

    header = csv.DictReader(io.StringIO(text)).fieldnames
    if header != _STOP_SEED_CSV_COLUMNS:
        _stop_seed_warning(
            f"downloaded content is not the expected CSV (header {header!r} — "
            "wrong file id, or the Drive file is not shared publicly)"
        )
        return False

    STOP_SEED_CSV.parent.mkdir(parents=True, exist_ok=True)
    STOP_SEED_CSV.write_text(text, encoding="utf-8")
    n_stops = sum(1 for _ in csv.DictReader(io.StringIO(text)))
    print(f"  downloaded {STOP_SEED_CSV.name} ({n_stops} stops).")
    return True


def _parse_optional_float(value):
    text = (value or "").strip()
    return float(text) if text else None


def _parse_optional_str(value):
    text = (value or "").strip()
    return text or None


def _parse_gauges(value, stop_id):
    """';'-separated gauge list -> Postgres INTEGER[] literal ('{1435,1520}'),
    or None when the pipeline found no usable tracks. A literal string, not a
    Python list, deliberately: insert_rows() JSON-dumps every list value (the
    JSONB convention the proposal tables rely on), which would send '[1435]'
    — not valid array syntax. A str passes through untouched and Postgres
    casts it against the column type; reads come back as real lists either
    way. Non-numeric leftovers (OSM words like 'broad' that step 8 keeps
    visible rather than guessing) are dropped with a warning — a word cannot
    be compared against a composition's gauge capability."""
    text = (value or "").strip()
    if not text:
        return None
    gauges = []
    for part in text.split(";"):
        part = part.strip()
        if part.isdigit():
            gauges.append(int(part))
        elif part:
            print(f"  {stop_id}: non-numeric gauge {part!r} dropped from seed.")
    if not gauges:
        return None
    return "{" + ",".join(str(g) for g in sorted(gauges)) + "}"


def _read_stop_seed() -> list[dict]:
    if not STOP_SEED_CSV.is_file() and not _download_stop_seed():
        return []
    with open(STOP_SEED_CSV, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != _STOP_SEED_CSV_COLUMNS:
            _stop_seed_warning(
                f"local {STOP_SEED_CSV.name} has unexpected header "
                f"{reader.fieldnames!r}"
            )
            return []
        catalog = list(reader)

    # The catalog covers more of Europe than the model does. A stop in a country
    # COUNTRIES doesn't seed has no track access, energy or facility parameters
    # behind it, so it could not be costed even if the foreign key allowed it —
    # dropped here rather than at the constraint, and counted so the gap is
    # visible instead of silent. Widening coverage means adding the country to
    # COUNTRIES (it falls back to the European calibration mean), not relaxing
    # this filter.
    modelled = {row["country_code"] for row in COUNTRIES}
    skipped = Counter(
        row["country_code"] for row in catalog if row["country_code"] not in modelled
    )
    if skipped:
        total = sum(skipped.values())
        detail = ", ".join(f"{code} {n}" for code, n in sorted(skipped.items()))
        print(f"  {total} catalog stops skipped — country not modelled ({detail}).")

    rows = [
        {
            "stop_id": row["stop_id"],
            "stop_name": row["stop_name"],
            "country_code": row["country_code"],
            "stop_timezone": row["stop_timezone"],
            "stop_lat": float(row["stop_lat"]),
            "stop_lon": float(row["stop_lon"]),
            # Empty means no station charge is known: NULL resolves via the
            # country/global default. Only stops listed in the pipeline's
            # tracked station_charges.csv carry a figure.
            "stop_charge_eur": _parse_optional_float(row["stop_charge_eur"]),
            # The charge's provenance travels with it: without these a
            # published figure cannot say which document it came from.
            "stop_charge_vat_rate_per": _parse_optional_float(
                row["stop_charge_vat_rate_per"]
            ),
            "stop_charge_incl_vat_eur": _parse_optional_float(
                row["stop_charge_incl_vat_eur"]
            ),
            "stop_charge_basis": _parse_optional_str(row["stop_charge_basis"]),
            "stop_charge_price_basis_year": (
                int(row["stop_charge_price_basis_year"])
                if row["stop_charge_price_basis_year"].strip()
                else None
            ),
            "stop_charge_class": _parse_optional_str(row["stop_charge_class"]),
            "stop_charge_source": _parse_optional_str(row["stop_charge_source"]),
            "stop_provenance": row["provenance"],
            "name_latin": row["name_latin"],
            "name_ascii": row["name_ascii"],
            "uic_ref": _parse_optional_str(row["uic_ref"]),
            **{f"country_{lang}": row[f"country_{lang}"] for lang in STOP_NAME_LANGS},
            # City is empty for rural halts beyond any city/town radius; the
            # localized names are then empty with it.
            "city": _parse_optional_str(row["city"]),
            "city_osm_id": (
                int(row["city_osm_id"]) if row["city_osm_id"].strip() else None
            ),
            **{
                f"city_{lang}": _parse_optional_str(row[f"city_{lang}"])
                for lang in STOP_NAME_LANGS
            },
            # Array literal string (see _parse_gauges); None stays NULL.
            "gauges_mm": _parse_gauges(row["gauges"], row["stop_id"]),
            "gauge_evidence": _parse_optional_str(row["gauge_source"]),
            "change_log": _STOP_SEED_CHANGE_LOG,
        }
        for row in catalog
        if row["country_code"] in modelled
    ]
    return rows


def _build_stop_infra_defaults() -> list[dict]:
    return [
        {**row, "stop_infra_default_version": version}
        for version in INFRA_VERSIONS
        for row in _STOP_INFRA_DEFAULT_CANONICAL
    ]


def _build_stop_infrastructures() -> list[dict]:
    # The CSV is read once, outside the comprehension — the inner iterable
    # would otherwise be re-evaluated per version.
    all_stops = _read_stop_seed()
    return [
        {"change_log": None, **row, "stop_infra_version": version}
        for version in INFRA_VERSIONS
        for row in all_stops
    ]


STOP_INFRA_DEFAULTS = _build_stop_infra_defaults()
STOP_INFRASTRUCTURES = _build_stop_infrastructures()

# ============================================================
# composition_types
# ============================================================

# The eleven calibrated standard compositions, read from calib/seed/.
# Energy factors and boarding/alighting times are not part of the cost
# calibration — they keep the established defaults until the energy
# model calibration workstream lands.
_COMP_ENERGY_AND_TIMES = dict(
    composition_type_min_boarding_time="00:02:00",
    composition_type_min_alighting_time="00:02:00",
)

_COMP_CSV_HELPER_COLS = {"n_coaches", "length_m", "attendants"}


def build_composition_types() -> list[dict]:
    rows = []
    for raw in _read_calib_csv("composition_types.csv"):
        row = {k: v for k, v in raw.items() if k not in _COMP_CSV_HELPER_COLS}
        row = _num(
            row,
            "composition_type_zugchef_crew_factor",
            "composition_type_length_cost_prop",
            "composition_type_max_speed_kmh",
            "composition_type_purchase_coach_eur",
            "composition_type_coach_avail_per",
            "composition_type_cleaning_eur_day",
            "composition_type_coach_maint_eur_km",
            "composition_type_driver_factor",
            "composition_type_indicative_cost_eur_train_km",
            "composition_type_indicative_cost_ct_place_km",
        )
        row["composition_type_coach_amort_years"] = int(
            row["composition_type_coach_amort_years"]
        )
        row["composition_type_hsr_allowed"] = (
            row["composition_type_hsr_allowed"] == "True"
        )
        rows.append({**row, **_COMP_ENERGY_AND_TIMES})
    return rows


COMPOSITION_TYPE_IDS = [
    r["composition_type_id"] for r in _read_calib_csv("composition_types.csv")
]

COMPOSITION_TYPE_COACHES_RAW = [
    (row["composition_type_id"], int(row["position"]), row["coach_type_id"])
    for row in _read_calib_csv("composition_type_coaches.csv")
]

# ============================================================
# proposals
# ============================================================
#
# No hand-written GTFS rows here. Every backend/db/README.md-documented
# invariant says GTFS rows are always linked to a proposals.proposals row
# by the P{proposal_id}_V{version}_R1 ID convention — a hand-seeded GTFS
# demo route with its own ad-hoc IDs (as this block used to be) violated
# that silently. seed_example_proposal(), called at the end of main(),
# builds one real proposal (Berlin Hbf -> Dresden Hbf -> Wien Hbf) and
# saves it through adapters.proposal.repository.ProposalRepository — the
# exact same code path a live POST /api/proposal uses — so the seeded
# example and a real save are structurally identical by construction,
# not by two independently maintained representations.

# ============================================================
# FK-resolving seed helpers
# ============================================================


def seed_sources(cur, source_ids: dict) -> None:
    ill = source_ids[SRC_ILLUSTRATIVE]
    cal = source_ids[SRC_CALIBRATION]
    cur.execute(
        "UPDATE input_params.track_infrastructure_defaults SET track_tac_src=%s, track_parking_src=%s, track_energy_price_src=%s, track_terrain_src=%s, track_hsr_src=%s, track_min_boarding_src=%s, track_min_alighting_src=%s, track_buffer_src=%s",
        (ill,) * 8,
    )
    cur.execute(
        "UPDATE input_params.track_infrastructures         SET track_tac_src=%s, track_parking_src=%s, track_energy_price_src=%s, track_terrain_src=%s, track_hsr_src=%s, track_min_boarding_src=%s, track_min_alighting_src=%s, track_buffer_src=%s",
        (ill,) * 8,
    )
    cur.execute(
        "UPDATE input_params.stop_infrastructure_defaults  SET stop_charge_src=%s",
        (ill,),
    )
    cur.execute(
        "UPDATE input_params.stop_infrastructures          SET stop_loc_src=%s, stop_charge_src=%s",
        (ill, ill),
    )
    cur.execute(
        "UPDATE input_params.operators                     SET source_id=%s", (cal,)
    )
    cur.execute(
        "UPDATE input_params.operator_class_costs          SET source_id=%s", (cal,)
    )
    cur.execute(
        "UPDATE input_params.coach_types                   SET source_id=%s", (cal,)
    )
    cur.execute(
        "UPDATE input_params.coach_type_classes            SET source_id=%s", (cal,)
    )
    cur.execute(
        "UPDATE input_params.composition_types             SET source_id=%s", (cal,)
    )
    _seed_tac_sources(cur, source_ids)
    _seed_energy_sources(cur, source_ids)
    _seed_facility_sources(cur, source_ids)
    _seed_route_context_sources(cur, source_ids)


def _seed_tac_sources(cur, source_ids: dict) -> None:
    """Point every calibrated TAC row at the network statement it was read
    from, overwriting the blanket illustrative FK set above.

    The calibration's own source ids (AT-SNNB-2027) are resolved through
    the description text, since the database assigns the numeric source_id
    itself. One FK per country covers the whole component group — where a
    country's terms come from more than one document the extras are named
    in the row's change_log (see models/params.py).
    """
    for country_code, register_id in _TAC_SOURCE_KEYS.items():
        description = INFRA_SOURCE_DESCRIPTIONS[register_id]
        cur.execute(
            "UPDATE input_params.track_infrastructures SET track_tac_src=%s "
            "WHERE country_code=%s",
            (
                source_ids[description],
                _TAC_COUNTRY_ALIASES.get(country_code, country_code),
            ),
        )
    for passage_id, register_id in _PASSAGE_SOURCE_KEYS.items():
        cur.execute(
            "UPDATE input_params.passage_charges SET passage_src=%s "
            "WHERE passage_id=%s",
            (source_ids[INFRA_SOURCE_DESCRIPTIONS[register_id]], passage_id),
        )


def _seed_energy_sources(cur, source_ids: dict) -> None:
    """Point every calibrated energy row at the document its price was read
    from, overwriting the blanket illustrative FK set above.

    One FK per country covers the day price, the night price and the
    catenary terms together — they are one tariff picture, and where more
    than one document is involved the extras are named in the row's
    change_log (see models/params.py: _TRACK_DEFAULT_SRC_ATTRS). The
    calibration's own source ids resolve through the description text, since
    the database assigns the numeric source_id itself.
    """
    for country_code, register_id in _ENERGY_SOURCE_KEYS.items():
        cur.execute(
            "UPDATE input_params.track_infrastructures "
            "SET track_energy_price_src=%s WHERE country_code=%s",
            (
                source_ids[INFRA_SOURCE_DESCRIPTIONS[register_id]],
                _TAC_COUNTRY_ALIASES.get(country_code, country_code),
            ),
        )


def _seed_facility_sources(cur, source_ids: dict) -> None:
    """Point every calibrated facility row at the document its charges were
    read from, overwriting the blanket illustrative FK set above.

    One FK covers shunting and stabling together: they come from the same
    network statement in every country that publishes either, and where more
    than one document is involved the extras are named in the row's
    change_log. The parking and shunting _src columns are set to the same
    source for that reason.
    """
    for country_code, register_id in _FACILITY_SOURCE_KEYS.items():
        cur.execute(
            "UPDATE input_params.track_infrastructures "
            "SET track_parking_src=%s, track_shunting_src=%s WHERE country_code=%s",
            (
                source_ids[INFRA_SOURCE_DESCRIPTIONS[register_id]],
                source_ids[INFRA_SOURCE_DESCRIPTIONS[register_id]],
                _TAC_COUNTRY_ALIASES.get(country_code, country_code),
            ),
        )


def _seed_route_context_sources(cur, source_ids: dict) -> None:
    """Point every calibrated route-context row at its document.

    Four _src columns share one FK: terrain, high-speed permission, the two
    dwell floors and the buffer quota all come out of the same calibration
    run, and splitting them would claim a per-field provenance the domain
    does not have. The per-value record stays
    models/infrastructure/route_context/calib/data/route_context.csv.
    """
    for country_code, register_id in _ROUTE_CONTEXT_SOURCE_KEYS.items():
        source_id = source_ids[INFRA_SOURCE_DESCRIPTIONS[register_id]]
        cur.execute(
            "UPDATE input_params.track_infrastructures "
            "SET track_terrain_src=%s, track_hsr_src=%s, "
            "    track_min_boarding_src=%s, track_min_alighting_src=%s, "
            "    track_buffer_src=%s "
            "WHERE country_code=%s",
            (
                source_id,
                source_id,
                source_id,
                source_id,
                source_id,
                _TAC_COUNTRY_ALIASES.get(country_code, country_code),
            ),
        )


def seed_operator_class_costs(cur):
    for operator_id, service_class_id, eur_place in OPERATOR_CLASS_COSTS_RAW:
        cur.execute(
            "SELECT operator_row_id FROM input_params.operators WHERE operator_id=%s",
            (operator_id,),
        )
        operator_row_id = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO input_params.operator_class_costs
               (operator_row_id, service_class_id, operator_class_svc_stockings_eur_place)
               VALUES (%s, %s, %s)""",
            (operator_row_id, service_class_id, eur_place),
        )


def seed_coach_type_classes(cur):
    for (
        coach_type_id,
        service_class_id,
        places,
        section_length_m,
        section_weight_t,
        section_crew_factor,
    ) in COACH_TYPE_CLASSES_RAW:
        cur.execute(
            "SELECT coach_type_row_id FROM input_params.coach_types WHERE coach_type_id=%s",
            (coach_type_id,),
        )
        coach_type_row_id = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO input_params.coach_type_classes
               (coach_type_row_id, service_class_id, coach_type_class_places,
                section_length_m, section_weight_t, section_crew_factor)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (
                coach_type_row_id,
                service_class_id,
                places,
                section_length_m,
                section_weight_t,
                section_crew_factor,
            ),
        )


LOCO_TYPES = [
    {
        "loco_type_id": row["loco_type_id"],
        "loco_type_description": row["loco_type_description"],
        "loco_type_traction": row["loco_type_traction"],
        "loco_type_weight_t": float(row["loco_type_weight_t"]),
        "loco_type_max_speed_kmh": int(row["loco_type_max_speed_kmh"]),
    }
    for row in _read_calib_csv("loco_types.csv")
]

OPERATOR_LOCO_COSTS_RAW = [
    (row["operator_id"], row["loco_type_id"], float(row["operator_loco_lease_eur_h"]))
    for row in _read_calib_csv("operator_loco_costs.csv")
]

COMPOSITION_TYPE_LOCOS_RAW = [
    (row["composition_type_id"], int(row["position"]), row["loco_type_id"])
    for row in _read_calib_csv("composition_type_locos.csv")
]


def seed_operator_loco_costs(cur):
    """Rental rate per operator and machine. Sparse by design — only the
    pairings the calibration actually derived a rate for get a row, and the
    loader refuses to cost a composition whose pairing is missing."""
    for operator_id, loco_type_id, eur_h in OPERATOR_LOCO_COSTS_RAW:
        cur.execute(
            "SELECT operator_row_id FROM input_params.operators WHERE operator_id=%s",
            (operator_id,),
        )
        operator_row_id = cur.fetchone()[0]
        cur.execute(
            "SELECT loco_type_row_id FROM input_params.loco_types WHERE loco_type_id=%s",
            (loco_type_id,),
        )
        loco_type_row_id = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO input_params.operator_loco_costs
               (operator_row_id, loco_type_row_id, operator_loco_lease_eur_h)
               VALUES (%s, %s, %s)""",
            (operator_row_id, loco_type_row_id, eur_h),
        )


def seed_composition_type_locos(cur):
    for comp_id, position, loco_type_id in COMPOSITION_TYPE_LOCOS_RAW:
        cur.execute(
            "SELECT composition_type_row_id FROM input_params.composition_types WHERE composition_type_id=%s",
            (comp_id,),
        )
        composition_type_row_id = cur.fetchone()[0]
        cur.execute(
            "SELECT loco_type_row_id FROM input_params.loco_types WHERE loco_type_id=%s",
            (loco_type_id,),
        )
        loco_type_row_id = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO input_params.composition_type_locos
               (composition_type_row_id, position, loco_type_row_id)
               VALUES (%s, %s, %s)""",
            (composition_type_row_id, position, loco_type_row_id),
        )


def seed_composition_type_coaches(cur):
    for comp_id, position, coach_type_id in COMPOSITION_TYPE_COACHES_RAW:
        cur.execute(
            "SELECT composition_type_row_id FROM input_params.composition_types WHERE composition_type_id=%s",
            (comp_id,),
        )
        composition_type_row_id = cur.fetchone()[0]
        cur.execute(
            "SELECT coach_type_row_id FROM input_params.coach_types WHERE coach_type_id=%s",
            (coach_type_id,),
        )
        coach_type_row_id = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO input_params.composition_type_coaches
               (composition_type_row_id, position, coach_type_row_id)
               VALUES (%s, %s, %s)""",
            (composition_type_row_id, position, coach_type_row_id),
        )


# ============================================================
# Each scenario pins its own version number, in lockstep, across all four
# infrastructure tables — every scenario row is a complete, self-contained
# pin, no NULLs, and no table is shared/inherited between scenarios (see
# the versioning note at the top of this file). routing_graph_key pins the
# routing graph the same way — a new graph arrives as NEW scenario rows,
# never by repointing a pinned one. Compositions/coach types/operators/
# composition references aren't part of a scenario at all — see
# db/schema.py (scenario.scenarios).
#
# Six selectable scenarios, one scenario_key each (six independent
# lineages, not forks of one another): the same three operating
# conditions on each of the two networks, per the version grid above.
# models/scenarios/README.md is the reference for what each represents
# and how the descriptions below were written.
#   1. "infra-2026"             — today's network, no HSR access (the live
#      default; is_current_base=TRUE).
#   2. "infra-2026-hsr"         — + night trains allowed on high-speed lines.
#   3. "infra-2026-hsr-opt-tt"  — + optimised timetables (reduced schedule
#      supplement).
#   5. "infra-2032"             — the upgraded network, no HSR access.
#   6. "infra-2032-hsr"         — + night trains on high-speed lines.
#   7. "infra-2032-hsr-opt-tt"  — + optimised timetables.
# All but the first are current lineage heads (is_current_scenario=TRUE,
# is_current_base=FALSE).
#
# Plus one SUPERSEDED row on the "infra-2026" key (version 4,
# is_current_scenario=FALSE): the lineage's pre-correction German rates.
# Not user-selectable — see _TRACK_INFRA_V4_OVERRIDES for why it exists.
#
# DEPLOYMENT COUPLING: the three 2032 rows pin routing_graph_key
# "infra_2032", so a deployment that does not run that OpenRailRouting
# instance cannot compute them — the API answers 503
# routing_graph_not_configured rather than routing on the wrong network
# (api/helpers/dependencies.py, api/proposal_calc.py). Enabling the
# instance is three lines in backend/docker/.env; see
# models/route/routing/README.md.

# ============================================================
# passage charges
# ============================================================
#
# Three identical full-table snapshots, one per scenario version, in the
# same lockstep numbering as the track and stop tables. Identical because
# no 2026 scenario varies a crossing charge — the versioning contract
# still requires a complete snapshot per version rather than a shared row
# (see db/schema.py: scenario.scenarios).
#
# KNOWN GAP: the Infra 2032 versions (5-7) are copies of the 2026 ones,
# so the fixed links that network adds carry no charge. Routes crossing
# them are therefore priced as if the crossing were free, and 2032 costs
# are understated by exactly that amount. Closing it needs a sourced
# tariff per new crossing, not a placeholder — models/scenarios/README.md.

PASSAGE_CHARGES = [
    {
        "passage_id": row["passage_id"],
        "passage_name": row["passage_name"],
        "passage_fixed_eur": float(row["passage_fixed_eur"]),
        "passage_per_passenger_eur": float(row["passage_per_passenger_eur"]),
        "passage_geom": row["passage_geom"],
        "passage_version": version,
    }
    for version in INFRA_VERSIONS
    for row in PASSAGE_CHARGES_RAW
]

_PASSAGE_SOURCE_KEYS = {
    row["passage_id"]: row["source_id"] for row in PASSAGE_CHARGES_RAW
}


def seed_passage_charges(cur) -> None:
    """Insert the crossing rows, parsing the GeoJSON geometry server-side.
    Kept out of insert_rows() because the geometry column needs a
    ST_GeomFromGeoJSON() call around its placeholder."""
    for row in PASSAGE_CHARGES:
        cur.execute(
            """INSERT INTO input_params.passage_charges
               (passage_id, passage_name, passage_fixed_eur,
                passage_per_passenger_eur, passage_geom, passage_version)
               VALUES (%s, %s, %s, %s, ST_GeomFromGeoJSON(%s), %s)""",
            (
                row["passage_id"],
                row["passage_name"],
                row["passage_fixed_eur"],
                row["passage_per_passenger_eur"],
                row["passage_geom"],
                row["passage_version"],
            ),
        )


BASE_SCENARIO = {
    "scenario_key": "infra-2026",
    "scenario_name": "Infra 2026",
    "description": "Today's rail network, as it exists now. Night trains "
    "run on conventional lines only — they are not permitted on "
    "high-speed lines — and their timetables carry the same generous "
    "padding real night trains carry today. This is the realistic "
    "baseline: what a night train would cost and how long it would take "
    "if it started running this year.",
    "change_log": "Initial seed.",
    "editor": "david",
    "is_current_base": True,
    "is_current_scenario": True,
    "track_infrastructures_version": 1,
    "track_infrastructure_defaults_version": 1,
    "stop_infrastructures_version": 1,
    "stop_infrastructure_defaults_version": 1,
    "passage_charges_version": 1,
    "routing_graph_key": "infra_2026",
}

HSR_SCENARIO = {
    "scenario_key": "infra-2026-hsr",
    "scenario_name": "Infra 2026 + night trains on high-speed lines",
    "description": "Today's rail network, but night trains are allowed to "
    "use high-speed lines. Nothing new is built — this is a policy "
    "change, asking what happens if infrastructure managers open existing "
    "high-speed track to night trains. Journeys get shorter wherever a "
    "high-speed line runs alongside the conventional route.",
    "change_log": "Initial seed.",
    "editor": "david",
    "is_current_base": False,
    "is_current_scenario": True,
    "track_infrastructures_version": 2,
    "track_infrastructure_defaults_version": 2,
    "stop_infrastructures_version": 2,
    "stop_infrastructure_defaults_version": 2,
    "passage_charges_version": 2,
    "routing_graph_key": "infra_2026",
}

SUPERSEDED_BASE_REVISION = {
    "scenario_key": "infra-2026",
    "scenario_name": "Infra 2026 (superseded revision)",
    "description": "An earlier revision of the Infra 2026 baseline, kept "
    "so evaluations published before the German track access charges were "
    "corrected stay reproducible. Superseded — not selectable, and not "
    "the basis of any new evaluation.",
    "change_log": "Pre-correction German track access rates.",
    "editor": "david",
    "is_current_base": False,
    "is_current_scenario": False,
    "track_infrastructures_version": 4,
    "track_infrastructure_defaults_version": 4,
    "stop_infrastructures_version": 4,
    "stop_infrastructure_defaults_version": 4,
    "passage_charges_version": 4,
    "routing_graph_key": "infra_2026",
}

OPT_TT_SCENARIO = {
    "scenario_key": "infra-2026-hsr-opt-tt",
    "scenario_name": "Infra 2026 + night trains on high-speed lines "
    "+ optimised timetables",
    "description": "As above, and night trains additionally receive "
    "well-designed paths. Real night-train timetables carry large margins "
    "today because a night train rarely holds priority and is routinely "
    "planned around other traffic. This scenario asks how much time the "
    "same trains on the same tracks would save if planners scheduled them "
    "as carefully as the best-performing networks already do.",
    "change_log": "Initial seed. Schedule supplement provisional — see "
    "models/scenarios/README.md.",
    "editor": "david",
    "is_current_base": False,
    "is_current_scenario": True,
    "track_infrastructures_version": 3,
    "track_infrastructure_defaults_version": 3,
    "stop_infrastructures_version": 3,
    "stop_infrastructure_defaults_version": 3,
    "passage_charges_version": 3,
    "routing_graph_key": "infra_2026",
}

# --- Infra 2032 -------------------------------------------------------
# The same three operating conditions on the upgraded network. The
# infrastructure tables they pin (versions 5-7) are copies of 1-3: what
# separates these rows from their 2026 counterparts is routing_graph_key,
# because an upgraded network is new track, and track lives in the
# routing graph rather than in input_params.

BASE_SCENARIO_2032 = {
    "scenario_key": "infra-2032",
    "scenario_name": "Infra 2032",
    "description": "The rail network as it is expected to exist in 2032, "
    "including the fixed links and line upgrades now under construction "
    "or firmly committed. Night trains still run on conventional lines "
    "only, and their timetables still carry the generous padding real "
    "night trains carry today. What changes against Infra 2026 is the "
    "track itself: journeys that take a long detour today become direct.",
    "change_log": "Initial seed. Mirrors Infra 2026 on the infra_2032 "
    "routing graph; crossing charges copied unchanged — see "
    "models/scenarios/README.md.",
    "editor": "david",
    "is_current_base": False,
    "is_current_scenario": True,
    "track_infrastructures_version": 5,
    "track_infrastructure_defaults_version": 5,
    "stop_infrastructures_version": 5,
    "stop_infrastructure_defaults_version": 5,
    "passage_charges_version": 5,
    "routing_graph_key": "infra_2032",
}

HSR_SCENARIO_2032 = {
    "scenario_key": "infra-2032-hsr",
    "scenario_name": "Infra 2032 + night trains on high-speed lines",
    "description": "The 2032 network, with night trains additionally "
    "allowed to use high-speed lines. The same policy change as in the "
    "2026 equivalent, asked of a network that by then has more high-speed "
    "line to open up.",
    "change_log": "Initial seed. Mirrors Infra 2026 + NT on HSR on the "
    "infra_2032 routing graph.",
    "editor": "david",
    "is_current_base": False,
    "is_current_scenario": True,
    "track_infrastructures_version": 6,
    "track_infrastructure_defaults_version": 6,
    "stop_infrastructures_version": 6,
    "stop_infrastructure_defaults_version": 6,
    "passage_charges_version": 6,
    "routing_graph_key": "infra_2032",
}

OPT_TT_SCENARIO_2032 = {
    "scenario_key": "infra-2032-hsr-opt-tt",
    "scenario_name": "Infra 2032 + night trains on high-speed lines "
    "+ optimised timetables",
    "description": "The most favourable of the six scenarios: everything "
    "currently being built, night trains permitted on high-speed lines, "
    "and well-designed paths rather than the residual ones they are given "
    "today. Read it as the upper bound of what is achievable without new "
    "projects beyond those already committed.",
    "change_log": "Initial seed. Mirrors Infra 2026 + NT on HSR + "
    "optimised timetables on the infra_2032 routing graph. Schedule "
    "supplement provisional — see models/scenarios/README.md.",
    "editor": "david",
    "is_current_base": False,
    "is_current_scenario": True,
    "track_infrastructures_version": 7,
    "track_infrastructure_defaults_version": 7,
    "stop_infrastructures_version": 7,
    "stop_infrastructure_defaults_version": 7,
    "passage_charges_version": 7,
    "routing_graph_key": "infra_2032",
}

# Insert order is display order nowhere — the API groups and sorts — but
# keeping the grid's reading order here makes a missing row obvious.
SCENARIOS = [
    BASE_SCENARIO,
    HSR_SCENARIO,
    OPT_TT_SCENARIO,
    SUPERSEDED_BASE_REVISION,
    BASE_SCENARIO_2032,
    HSR_SCENARIO_2032,
    OPT_TT_SCENARIO_2032,
]


# ============================================================
# Example proposal — seeded via the real save code path
# ============================================================

# Physics-only field subsets mirroring api/helpers/route_serialize.py's
# _composition_to_dict() / _track_to_dict() — kept intentionally separate
# (rather than importing those underscore-prefixed helpers across a
# module boundary) but sourced from the SAME live domain objects
# (Composition / TrackInfrastructure), never hand-typed numbers. If the
# route_serialize.py field lists change, mirror the change here too.
_EXPOSED_TRACK_FIELDS = (
    "hsr_allowed",
    "min_boarding_time_min",
    "min_alighting_time_min",
    "terrain_score",
    "terrain_category",
    "buffer_quota_per",
)


def _composition_physics_dict(comp) -> dict:
    """Local mirror of route_serialize._composition_to_dict()'s shape,
    for the draft route dict fed to route_from_dict() below. The nested
    object is inert on that path — route_from_dict() resolves the
    composition from the OUTER trip_pairs[].composition_id via the
    loader and ignores this — but the keys are kept in step with the
    real serializer so nobody reads this as the wire contract
    (composition_id/description since 2026-08-07, was comp_id/
    comp_description)."""
    return {
        "composition_id": comp.comp_id,
        "description": comp.comp_description,
        "operator_id": comp.operator_id,
        "max_speed_kmh": comp.max_speed_kmh,
        "hsr_allowed": comp.hsr_allowed,
        "min_boarding_time_min": comp.min_boarding_time_min,
        "min_alighting_time_min": comp.min_alighting_time_min,
        "total_weight_t": comp.total_weight_t,
        "total_crew": comp.total_crew,
        "places_by_class": comp.places_by_class,
        # derived from real section geometry — replaces the retired
        # density_by_class (2026-07-22); mirrors route_serialize
        "density_by_class_main_length": comp.density_by_class_main_length,
        "density_by_class_main_weight": comp.density_by_class_main_weight,
        "total_length_m": comp.total_length_m,
    }


def _track_physics_dict(track) -> dict:
    return {
        "country_code": track.country_code,
        "defaulted_fields": [
            f for f in _EXPOSED_TRACK_FIELDS if track.field_is_default.get(f)
        ],
        "hsr_allowed": track.hsr_allowed,
        "min_boarding_time_min": track.min_boarding_time_min,
        "min_alighting_time_min": track.min_alighting_time_min,
        "terrain_score": track.terrain_score,
        "terrain_category": track.terrain_category,
        "buffer_quota_per": track.buffer_quota_per,
    }


def _example_trip(
    trip_id: str,
    direction: int,
    stops: list[tuple[str, str, str, float, float]],
    times_min: list[tuple[int | None, int | None]],
    stop_types: list[str],
    segment_physics: list[tuple[int, int, int, float, dict, dict]],
    segment_geometries: list[list[list[float]]],
    geometries_out: list[dict],
) -> dict:
    """One direction of the example trip pair. stops/times_min/stop_types
    are parallel lists over stop positions (n stops); segment_physics/
    segment_geometries are parallel lists over segments (n - 1). Segment
    distance/time/energy figures are illustrative hand-picked values —
    this script has no OpenRailRouting connection to derive them from,
    same as the demo route this replaces."""
    segments = []
    for i in range(len(stops) - 1):
        from_id, from_name, from_cc, from_lat, from_lon = stops[i]
        to_id, to_name, to_cc, to_lat, to_lon = stops[i + 1]
        distance_m, driving_min, buffer_min, energy_kwh, dist_shares, time_shares = (
            segment_physics[i]
        )
        geometry_id = f"{trip_id}_L{i}"
        geometries_out.append({"id": geometry_id, "coords": segment_geometries[i]})
        segments.append(
            {
                "from_stop": {
                    "stop_id": from_id,
                    "stop_name": from_name,
                    "country_code": from_cc,
                    "lat": from_lat,
                    "lon": from_lon,
                    "stop_type": stop_types[i],
                    "arrival_time_min": times_min[i][0],
                    "departure_time_min": times_min[i][1],
                },
                "to_stop": {
                    "stop_id": to_id,
                    "stop_name": to_name,
                    "country_code": to_cc,
                    "lat": to_lat,
                    "lon": to_lon,
                    "stop_type": stop_types[i + 1],
                    "arrival_time_min": times_min[i + 1][0],
                    "departure_time_min": times_min[i + 1][1],
                },
                "geometry_id": geometry_id,
                "distance_m": distance_m,
                "driving_time_min": driving_min,
                "dynamics_time_min": 0,
                "buffer_time_min": buffer_min,
                "slack_time_min": 0,
                "energy_kwh": energy_kwh,
                "country_distance_shares": dist_shares,
                "country_time_shares": time_shares,
            }
        )
    return {"trip_id": trip_id, "direction": direction, "segments": segments}


def _build_example_route(scenario_id: int, composition, tracks) -> dict:
    """Berlin Hbf -> Dresden Hbf -> Wien Hbf, NEW-BAL-7. Route physics are
    hand-crafted (not routed via a live OpenRailRouting call) so seeding
    has no dependency on the routing container being up yet — see
    seed_example_proposal()'s docstring for how this feeds into a real
    evaluation. route_id uses the bare "R1" structural-id convention
    (mirrors a fresh compute response, adapters/proposal/README.md §2.1) so the
    resulting dict is publish()-ready the same way a live compute's
    output is — adapters/proposal/repository.py's publish() rewrites it
    up to the real P{proposal_id}_V{version}_ prefix."""
    draft_prefix = "R1"
    composition_dict = _composition_physics_dict(composition)

    berlin = ("osm:n3856100103", "Berlin Hbf", "DE", 52.525, 13.369)
    dresden = ("osm:n25397500", "Dresden Hbf", "DE", 51.040, 13.732)
    wien = ("osm:w423692233", "Wien Hbf", "AT", 48.185, 16.376)

    # Berlin -> Dresden: fully within DE. Dresden -> Wien: illustrative
    # DE/AT split (doesn't model the real Berlin-Dresden-Wien routing
    # through Czechia — same simplification the demo route this replaces
    # made).
    outbound_physics = [
        (165300, 95, 8, 850.0, {"DE": 1.0}, {"DE": 1.0}),
        (518100, 430, 28, 2650.0, {"DE": 0.3, "AT": 0.7}, {"DE": 0.3, "AT": 0.7}),
    ]
    return_physics = [
        (518100, 430, 28, 2650.0, {"AT": 0.7, "DE": 0.3}, {"AT": 0.7, "DE": 0.3}),
        (165300, 95, 8, 850.0, {"DE": 1.0}, {"DE": 1.0}),
    ]
    outbound_geometries = [
        [[13.369, 52.525], [13.732, 51.040]],
        [[13.732, 51.040], [16.376, 48.185]],
    ]
    return_geometries = [
        [[16.376, 48.185], [13.732, 51.040]],
        [[13.732, 51.040], [13.369, 52.525]],
    ]

    geometries: list[dict] = []
    outbound = _example_trip(
        trip_id=f"{draft_prefix}_D0_T1",
        direction=0,
        stops=[berlin, dresden, wien],
        times_min=[(None, 1264), (1367, 1372), (1830, None)],
        stop_types=["boarding", "both", "alighting"],
        segment_physics=outbound_physics,
        segment_geometries=outbound_geometries,
        geometries_out=geometries,
    )
    return_trip = _example_trip(
        trip_id=f"{draft_prefix}_D1_T1",
        direction=1,
        stops=[wien, dresden, berlin],
        times_min=[(None, 1200), (1658, 1663), (1766, None)],
        stop_types=["boarding", "both", "alighting"],
        segment_physics=return_physics,
        segment_geometries=return_geometries,
        geometries_out=geometries,
    )

    return {
        "route_id": draft_prefix,
        "scenario_id": scenario_id,
        "schedule": {
            "seasonal_schedules": [
                {"season": "summer", "frequency": "daily"},
                {"season": "winter", "frequency": "daily"},
            ]
        },
        "trip_pairs": [
            {
                "composition_id": composition.comp_id,
                "composition": composition_dict,
                "od_pairs": [],
                "outbound": outbound,
                "return_trip": return_trip,
            }
        ],
        "parkings": [
            {
                "stop_id": "osm:w423692233",
                "stop_name": "Wien Hbf",
                "country_code": "AT",
                "trip_ids": [f"{draft_prefix}_D0_T1"],
            },
            {
                "stop_id": "osm:n3856100103",
                "stop_name": "Berlin Hbf",
                "country_code": "DE",
                "trip_ids": [f"{draft_prefix}_D1_T1"],
            },
        ],
        "shuntings": [
            {
                "stop_id": "osm:n3856100103",
                "stop_name": "Berlin Hbf",
                "country_code": "DE",
                "trip_id": f"{draft_prefix}_D0_T1",
            },
            {
                "stop_id": "osm:w423692233",
                "stop_name": "Wien Hbf",
                "country_code": "AT",
                "trip_id": f"{draft_prefix}_D0_T1",
            },
            {
                "stop_id": "osm:w423692233",
                "stop_name": "Wien Hbf",
                "country_code": "AT",
                "trip_id": f"{draft_prefix}_D1_T1",
            },
            {
                "stop_id": "osm:n3856100103",
                "stop_name": "Berlin Hbf",
                "country_code": "DE",
                "trip_id": f"{draft_prefix}_D1_T1",
            },
        ],
        "track_infrastructure": [
            _track_physics_dict(tracks.get(cc)) for cc in ("AT", "DE")
        ],
        "geometries": geometries,
    }


# The seeded example lands on proposal_id=1 naturally — the first-ever
# INSERT into proposals.proposals on a fresh DB, no reservation needed.
# This is collision-free because tests/conftest.py's session route
# fixtures use draft proposal_id placeholders 100+ (see the range
# convention documented there), not 1-4 as they once did. Documentation
# only below (not read anywhere in this file) — kept in sync with the
# same-named constant in tests/test_50_proposals_api.py, which does use
# it, to make the shared convention explicit in both places.
_SEED_PROPOSAL_ID = 1


def _compute_example_proposal(
    route_dict: dict, scenario_id: int, loader, tracks
) -> dict:
    """Run the hand-crafted example route dict through the real
    evaluation pipeline — distribute_demand() (models/demand) ->
    models.pipeline.evaluate_and_build_views() — and serialize the result
    into exactly the shape api/helpers/proposal_compute.compute_proposal()
    produces (§2.1), so ProposalRepository.publish() can't tell the
    difference from a live compute. Deliberately does NOT go through
    run_compute() itself (whose plan_route() step requires a live
    RailRouter/OpenRailRouting) — the whole point of hand-crafting the
    route's physics is to keep DB seeding independent of the routing
    container being up yet; only the post-routing half of the pipeline is
    reused."""
    from api.helpers.evaluation_serialize import (
        input_to_dict,
        models_to_dict,
        views_to_dict,
    )
    from api.helpers.route_serialize import route_from_dict, route_to_dict
    from adapters.proposal.projection import route_fingerprint
    from models.evaluation.summary import build_summary_row
    from models.demand.stopgap import distribute_demand
    from models.demand.model import (
        STOPGAP_FARE_PER_KM_BY_CLASS,
        STOPGAP_UTILIZATION_PER,
    )
    from models.evaluation.model import CALC_VERSION
    from models.pipeline import evaluate_and_build_views
    from models.route.model import ROUTE_BUILDER_VERSION

    route, compositions = route_from_dict(route_dict, loader, scenario_id=scenario_id)
    distribute_demand(
        route,
        utilization_per=STOPGAP_UTILIZATION_PER,
        fare_per_km_by_class=STOPGAP_FARE_PER_KM_BY_CLASS,
    )
    stop_infra = loader.build_all_stops(scenario_id)
    passages = loader.build_all_passages(scenario_id)
    _, views = evaluate_and_build_views(route, tracks, stop_infra, passages)

    serialized_route = route_to_dict(route, scenario_id, tracks)
    evaluation = {
        "models": models_to_dict(),
        "input": input_to_dict(
            serialized_route, tracks, stop_infra, compositions, include_route=False
        ),
        "views": views_to_dict(views, route),
    }

    return {
        "route_builder_version": ROUTE_BUILDER_VERSION,
        "calc_version": CALC_VERSION,
        "route_fingerprint": route_fingerprint(serialized_route),
        "request": {
            "stops": ["osm:n3856100103", "osm:n25397500", "osm:w423692233"],
            "composition_id": "NEW-BAL-7",
            "scenario_id": scenario_id,
            "timetable_mode": "simpleAutomatic",
            "fixed_night_interval": None,
            "schedule_mode": "alwaysDaily",
            "routing_mode": "fullRouting",
            "auto_stop_addition": "off",
        },
        "summary": build_summary_row(serialized_route, evaluation),
        "route": serialized_route,
        "evaluation": evaluation,
    }


def seed_example_proposal(cur, conn) -> None:
    """
    Seeds one real, published proposal (Berlin Hbf -> Dresden Hbf -> Wien
    Hbf) through the exact same write path a live POST /api/proposal/
    publish uses — ProposalRepository.publish() — so the demo GTFS rows
    and the proposals.proposals row that owns them are structurally
    identical to a real publish, not a hand-maintained parallel
    representation. Must run after conn.commit() so the users/scenario/
    composition/track rows it reads are visible to the separate
    connections the loader and ProposalRepository open.

    WP5 note: proposals no longer support half-states — every published
    proposal carries both route AND evaluation (§2.4). This seed now runs
    the hand-crafted example route through the real evaluation pipeline
    (_compute_example_proposal() — distribute_demand ->
    evaluate_and_build_views) instead of the old no-demand illustrative
    stub, so cost/revenue on the seeded example are real computed numbers,
    not absent. It still deliberately does NOT go through the full
    compute_proposal()/run_compute() pipeline (which needs a live
    RailRouter/OpenRailRouting) — see _compute_example_proposal()'s
    docstring.

    Best-effort: an illustrative example isn't load-bearing the way
    input_params/admin data is. A failure here is logged and swallowed
    rather than aborting the rest of seeding.
    """
    try:
        import sys
        from pathlib import Path

        # db/dev/seed.py -> backend/ is two levels up. Only the standalone
        # Mathesar dev stack (db/dev/docker-compose.yml) lacks this
        # entirely — its own Dockerfile copies just seed.py/sql_loader.py/
        # sql/, not the rest of the backend tree — so the import below is
        # expected to fail there and is caught below.
        backend_root = Path(__file__).resolve().parents[2]
        if str(backend_root) not in sys.path:
            sys.path.insert(0, str(backend_root))

        from adapters.proposal.repository import ProposalRepository
        from adapters.data_loader_from_db import DBDataLoader
    except ImportError:
        print(
            "Seeding example proposal... skipped (adapters/ not present in "
            "this image — expected on the standalone db/dev docker-compose "
            "stack, which only ships seed.py itself, not the rest of the "
            "backend tree)."
        )
        return

    print("Seeding example proposal...")
    try:
        cur.execute(
            "SELECT scenario_id FROM scenario.scenarios WHERE is_current_base = TRUE"
        )
        scenario_id = cur.fetchone()[0]
        cur.execute(
            "SELECT user_id FROM admin.users WHERE email = %s",
            ("david@backontrack.eu",),
        )
        user_id = cur.fetchone()[0]

        loader = DBDataLoader()
        try:
            composition = loader.build_all_compositions(scenario_id).get("NEW-BAL-7")
            tracks = loader.build_all_tracks(scenario_id)
            route_dict = _build_example_route(scenario_id, composition, tracks)
            computed = _compute_example_proposal(
                route_dict, scenario_id, loader, tracks
            )
        finally:
            loader.close()

        repo = ProposalRepository()
        try:
            repo.publish(
                mode="new",
                user_id=user_id,
                name="Berlin – Dresden – Wien (seed example)",
                computed=computed,
            )
        finally:
            repo.close()
    except Exception as e:
        print(f"  WARNING: example proposal seed failed, skipping: {e}")
        conn.rollback()


def sync_ontd_schema(cur) -> None:
    """Additive column top-ups for an ontd schema that already exists.

    The guard above deliberately never re-applies create_ontd_schema.sql
    on a database that already carries loaded ONTD data (it DROPs the
    refreshed tables). That leaves one gap: a reseed rebuilds
    input_params and proposals from the latest DDL while the ontd tables
    stay at whatever shape they were created with — so a column added to
    a refreshed table reaches a fresh database and a reloaded one, but
    never a merely reseeded one. The gallery's UNION reads both sides,
    so the halves must agree.

    Every statement here is additive and IF NOT EXISTS: this is a
    catch-up, never a migration in its own right. The server-side
    counterpart is db/dev/sql/migrations/. Entries can be dropped once
    no environment predates them.
    """
    cur.execute(
        "ALTER TABLE ontd.route_summaries "
        "ADD COLUMN IF NOT EXISTS country_relations TEXT[] NOT NULL DEFAULT '{}'"
    )


def main():
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )
    print(f"Connected to '{DB_NAME}' at {DB_HOST}:{DB_PORT}")
    cur = conn.cursor()

    print("Creating schemas...")
    cur.execute(load_sql("create_admin_schema.sql"))
    cur.execute(build_ddl())  # input_params + scenario — db/schema.py
    cur.execute(load_sql("create_proposal_schema.sql"))

    # ONTD schema bootstrap (WP10 step 6a) — created ONLY when absent, so
    # the gallery's source union (proposals ∪ ontd.route_summaries) has
    # tables to query in every environment, empty until db/ontd/loader.py
    # runs. Guarded because create_ontd_schema.sql DROPs the refreshed
    # tables: re-applying it on a database that already carries loaded
    # ONTD data would wipe that data on every reseed.
    cur.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.schemata "
        "WHERE schema_name = 'ontd')"
    )
    if not cur.fetchone()[0]:
        print("Bootstrapping empty ontd schema...")
        ontd_ddl = (
            Path(__file__).resolve().parent.parent
            / "ontd"
            / "sql"
            / "create_ontd_schema.sql"
        )
        cur.execute(ontd_ddl.read_text(encoding="utf-8"))
    else:
        print("Syncing existing ontd schema...")
        sync_ontd_schema(cur)

    print("Seeding admin.users...")
    insert_rows(cur, "admin.users", USERS)

    print("Seeding input_params.sources...")
    insert_rows(cur, "input_params.sources", SOURCES)
    source_ids = fetch_source_ids(cur)

    print("Seeding input_params.countries...")
    insert_rows(cur, "input_params.countries", COUNTRIES)
    seed_country_geometries(cur)

    print("Seeding input_params.service_classes...")
    insert_rows(cur, "input_params.service_classes", SERVICE_CLASSES)

    print("Seeding input_params.loco_types...")
    insert_rows(cur, "input_params.loco_types", LOCO_TYPES)

    print("Seeding input_params.operators...")
    insert_rows(cur, "input_params.operators", OPERATORS)
    seed_operator_class_costs(cur)
    seed_operator_loco_costs(cur)

    print("Seeding input_params.coach_types...")
    insert_rows(cur, "input_params.coach_types", COACH_TYPES)
    seed_coach_type_classes(cur)

    print("Seeding input_params.track_infrastructure_defaults...")
    insert_rows(cur, "input_params.track_infrastructure_defaults", TRACK_INFRA_DEFAULTS)

    print("Seeding input_params.track_infrastructures...")
    insert_rows(cur, "input_params.track_infrastructures", TRACK_INFRASTRUCTURES)

    print("Seeding input_params.stop_infrastructure_defaults...")
    insert_rows(cur, "input_params.stop_infrastructure_defaults", STOP_INFRA_DEFAULTS)

    print("Seeding input_params.stop_infrastructures...")
    insert_rows(cur, "input_params.stop_infrastructures", STOP_INFRASTRUCTURES)

    print("Seeding input_params.passage_charges...")
    seed_passage_charges(cur)

    print("Seeding input_params.composition_types...")
    insert_rows(cur, "input_params.composition_types", build_composition_types())
    seed_composition_type_coaches(cur)
    seed_composition_type_locos(cur)

    print("Injecting source IDs...")
    seed_sources(cur, source_ids)

    print("Seeding scenario.scenarios...")
    insert_rows(cur, "scenario.scenarios", SCENARIOS)

    conn.commit()

    # Must run after commit — it opens its own connections (via
    # ProposalRepository/DBDataLoader) and needs the users/scenario rows
    # above to already be visible to them.
    seed_example_proposal(cur, conn)

    print("Seeding route_cache (optional precomputed segments)...")
    seed_route_segments()

    print("\nDone. Row counts:")
    for schema, table in [
        ("admin", "users"),
        ("input_params", "sources"),
        ("input_params", "countries"),
        ("input_params", "service_classes"),
        ("input_params", "operators"),
        ("input_params", "operator_class_costs"),
        ("input_params", "coach_types"),
        ("input_params", "coach_type_classes"),
        ("input_params", "loco_types"),
        ("input_params", "operator_loco_costs"),
        ("input_params", "composition_type_locos"),
        ("input_params", "track_infrastructure_defaults"),
        (
            "input_params",
            "track_infrastructures",
        ),  # 84 rows: 3 full snapshots x 28 countries
        ("input_params", "passage_charges"),  # 12 rows: 3 snapshots x 4 crossings
        ("input_params", "stop_infrastructure_defaults"),
        ("input_params", "stop_infrastructures"),
        ("input_params", "composition_types"),
        ("input_params", "composition_type_coaches"),
        ("scenario", "scenarios"),
        ("route_cache", "graph_state"),
        ("route_cache", "route_segments"),
        ("proposals", "proposals"),
        ("proposals", "routes"),
        ("proposals", "trips"),
        ("proposals", "stop_times"),
        ("proposals", "shapes"),
        ("proposals", "services"),
    ]:
        cur.execute(f"SELECT COUNT(*) FROM {schema}.{table}")
        print(f"  {schema}.{table}: {cur.fetchone()[0]} rows")

    cur.execute(
        "SELECT COUNT(*) FROM input_params.countries WHERE country_geom IS NOT NULL"
    )
    print(f"  input_params.countries: {cur.fetchone()[0]} rows have country_geom")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
