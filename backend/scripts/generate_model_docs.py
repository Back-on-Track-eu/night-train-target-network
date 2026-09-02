"""
generate_model_docs.py
======================
CLI for the model documentation generators.

Both artefacts are rendered from one extraction layer over the model
registries (scripts/model_docs/extract.py), so they can differ in prose
but never in facts:

  model-md   docs/MODEL.md — the developer reference, one flat
             cross-linked document
  site       docs-site/ — the public documentation site

Sources (single source of truth, never duplicated by hand):
  - models/*/model.py     formula registries (Formula/FormulaParam incl.
                          the 'ref' source pointers), versions,
                          descriptions, standard values, emission factors
  - db/schema.py          parameter tables with descriptions and units

Usage (from backend/):
  uv run python scripts/generate_model_docs.py                   # rewrite
  uv run python scripts/generate_model_docs.py --check           # CI: fail on diff
  uv run python scripts/generate_model_docs.py --target model-md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
BACKEND = SCRIPTS.parent
for _path in (str(BACKEND), str(SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from model_docs import render_model_md  # noqa: E402
from model_docs.extract import (  # noqa: E402
    validate_calc_coverage,
    validate_summaries,
)

# One entry per artefact: the module providing check() -> bool and
# write() -> int, plus the path named in the "out of date" message.
TARGETS = {
    "model-md": (render_model_md, "docs/MODEL.md"),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail (exit 1) if a generated artefact is not up to date "
        "with the registries",
    )
    parser.add_argument(
        "--target",
        choices=[*TARGETS, "all"],
        default="all",
        help="which artefact to render (default: all)",
    )
    args = parser.parse_args()

    # Registry-level invariants, checked once before any artefact is
    # rendered: a formula missing its place in the tree or carrying an
    # unusable summary is a source problem, not an output problem.
    validate_calc_coverage()
    validate_summaries()

    selected = list(TARGETS) if args.target == "all" else [args.target]

    for name in selected:
        module, label = TARGETS[name]
        if args.check:
            if not module.check():
                raise SystemExit(
                    f"{label} is out of date with the model registries — run "
                    f"`uv run python scripts/generate_model_docs.py "
                    f"--target {name}` and commit the result."
                )
            print(f"{label} is up to date.")
        else:
            print(f"{label} regenerated ({module.write()} chars).")


if __name__ == "__main__":
    main()
