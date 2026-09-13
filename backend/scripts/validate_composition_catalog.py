"""
Check the composition catalog (models/compositions/calib/catalog/*.csv)
without running the calibration notebook.

    uv run python scripts/validate_composition_catalog.py

Runs the same loader the notebook and db/dev/seed.py use, so whatever
passes here passes the seed. Errors exit 1; warnings are review notes.
Source references are checked against calib/data/sources_register.csv when
01_source_extraction.ipynb has written it, otherwise only their shape.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models.compositions.catalog import (  # noqa: E402
    CATALOG_DIR,
    SOURCES_REGISTER,
    load_catalog,
    summary_lines,
)


def main() -> int:
    catalog = load_catalog()
    register = "register" if SOURCES_REGISTER.is_file() else "shape only"
    print(
        f"catalog: {CATALOG_DIR} — {len(catalog.loco_types)} loco types, "
        f"{len(catalog.coach_types)} coach types, "
        f"{len(catalog.compositions)} compositions (source ids: {register})\n"
    )
    if not catalog.errors:
        print("\n".join(summary_lines(catalog)), "\n")
    for msg in catalog.warnings:
        print(f"WARNING: {msg}")
    for msg in catalog.errors:
        print(f"ERROR:   {msg}")
    print(f"\n{len(catalog.errors)} error(s), {len(catalog.warnings)} warning(s).")
    return 1 if catalog.errors else 0


if __name__ == "__main__":
    sys.exit(main())
