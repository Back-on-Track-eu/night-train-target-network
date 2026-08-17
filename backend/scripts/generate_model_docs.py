"""
generate_model_docs.py
======================
Renders the model registries into docs/MODEL.md — the single readable,
fully cross-linked documentation of the calculation model.

Sources (single source of truth, never duplicated by hand):
  - models/*/model.py     formula registries (Formula/FormulaParam incl.
                          the 'ref' source pointers), versions,
                          descriptions, standard values, emission factors
  - db/schema.py          parameter tables with descriptions and units

The generator only replaces the marked blocks in docs/MODEL.md
(<!-- BEGIN GENERATED: name --> ... <!-- END GENERATED: name -->); all
narrative prose outside the markers is hand-written and preserved.

Cross-linking: every formula and every parameter column gets a stable
HTML anchor. Upstream links come from FormulaParam.ref; downstream
"Used by" links are computed by inverting the ref graph, so they can
never drift.

Usage (from backend/):
  uv run python scripts/generate_model_docs.py           # rewrite blocks
  uv run python scripts/generate_model_docs.py --check   # CI: fail on diff
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from db.schema import INPUT_PARAMS_TABLES, SCENARIO_TABLES  # noqa: E402
from models.demand.model import (  # noqa: E402
    DEMAND_MODEL_DESCRIPTION,
    DEMAND_MODEL_VERSION,
)
from models.emissions.model import (  # noqa: E402
    EMISSION_FACTORS,
    EMISSIONS_MODEL_DESCRIPTION,
    EMISSIONS_MODEL_VERSION,
    MODE_SHIFT_SHARES,
)
from models.energy.model import (  # noqa: E402
    ENERGY_CALC_VERSION,
    ENERGY_FORMULAS,
    ENERGY_MODEL_DESCRIPTION,
)
from models.evaluation.model import (  # noqa: E402
    CALC_FORMULAS,
    CALC_MODEL_DESCRIPTION,
    CALC_VERSION,
)
from models.route.model import (  # noqa: E402
    ROUTE_BUILDER_DESCRIPTION,
    ROUTE_BUILDER_VERSION,
    ROUTE_FORMULAS,
)
from models.compositions.model import (  # noqa: E402
    COMPOSITIONS_MODEL_DESCRIPTION,
    COMPOSITIONS_MODEL_VERSION,
)
from models.infrastructure.model import (  # noqa: E402
    INFRA_MODEL_DESCRIPTION,
    INFRA_MODEL_VERSION,
)

DOC_PATH = BACKEND.parent / "docs" / "MODEL.md"

# Formula registries keyed by the model id used in "formula:<model>.<key>"
# refs, plus display metadata. MODEL.md renders them in this order.
REGISTRIES: dict[str, dict] = {
    "route": {
        "title": "Route & timetable builder",
        "formulas": ROUTE_FORMULAS,
        "model_py": "backend/models/route/model.py",
    },
    "energy": {
        "title": "Energy model",
        "formulas": ENERGY_FORMULAS,
        "model_py": "backend/models/energy/model.py",
    },
    "calc": {
        "title": "Cost & revenue evaluation",
        "formulas": CALC_FORMULAS,
        "model_py": "backend/models/evaluation/model.py",
    },
}

# Model.py files whose STANDARD VALUES sections are rendered. The "std id"
# is the prefix used in "standard:<ID>.<CONSTANT>" refs.
STANDARD_VALUE_FILES: dict[str, Path] = {
    "ROUTE": BACKEND / "models" / "route" / "model.py",
    "ENERGY": BACKEND / "models" / "energy" / "model.py",
    "DEMAND": BACKEND / "models" / "demand" / "model.py",
    "INFRASTRUCTURE": BACKEND / "models" / "infrastructure" / "model.py",
}


# ---------------------------------------------------------------------------
# Anchors and links
# ---------------------------------------------------------------------------


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "-", text.lower()).strip("-")


def formula_anchor(model: str, key: str) -> str:
    return f"f-{_slug(model)}-{_slug(key)}"


def column_anchor(qualified: str) -> str:
    return f"p-{_slug(qualified)}"


def standard_anchor(std_id: str, const: str) -> str:
    return f"s-{_slug(std_id)}-{_slug(const)}"


def ref_link(ref: str) -> str:
    """Render one FormulaParam.ref as a markdown link (or plain text)."""
    if not ref:
        return "computed upstream"
    if ref == "user":
        return "set by the tool user"
    kind, _, target = ref.partition(":")
    if kind == "formula":
        model, _, key = target.partition(".")
        return f"formula [`{key}`](#{formula_anchor(model, key)})"
    if kind == "column":
        column = target.rsplit(".", 1)[1]
        return f"parameter [`{column}`](#{column_anchor(target)})"
    if kind == "standard":
        std_id, _, const = target.partition(".")
        return f"standard value [`{const}`](#{standard_anchor(std_id, const)})"
    raise ValueError(f"unknown ref: {ref}")


# ---------------------------------------------------------------------------
# Inverse graph — downstream "used by" links, computed from the refs
# ---------------------------------------------------------------------------


def build_used_by() -> tuple[dict[str, list], dict[str, list]]:
    """Invert every FormulaParam.ref: which formulas consume a given
    formula output ({model}.{key}) resp. a given DB column (qualified)."""
    used_by_formula: dict[str, list] = {}
    used_by_column: dict[str, list] = {}
    for model, meta in REGISTRIES.items():
        for key, formula in meta["formulas"].items():
            for prm in formula.inputs:
                kind, _, target = prm.ref.partition(":")
                if kind == "formula":
                    used_by_formula.setdefault(target, []).append((model, key))
                elif kind == "column":
                    used_by_column.setdefault(target, []).append((model, key))
    return used_by_formula, used_by_column


def _used_by_line(consumers: list) -> str:
    links = ", ".join(
        f"[`{key}`](#{formula_anchor(model, key)})"
        for model, key in sorted(set(consumers))
    )
    return f"**Used by:** {links}" if consumers else ""


# ---------------------------------------------------------------------------
# Standard values — extracted from model.py source via AST, because PEP 224
# style docstrings after assignments are not available at runtime
# ---------------------------------------------------------------------------


def extract_standard_values(path: Path) -> list[tuple[str, str, str]]:
    """[(name, value_repr, doc)] for every documented module-level constant
    (UPPER_CASE assignment directly followed by a string literal)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    body = tree.body
    for i, node in enumerate(body):
        targets = []
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
        if len(targets) != 1 or not targets[0].isupper():
            continue
        name = targets[0]
        # Skip the version/description/changelog machinery — not standard values
        if name in {"GIT_SHA", "OPEN_TODOS", "CHANGELOG"} or name.endswith(
            ("_VERSION", "_DESCRIPTION", "_FORMULAS", "_NDIGITS")
        ):
            continue
        doc = ""
        if (
            i + 1 < len(body)
            and isinstance(body[i + 1], ast.Expr)
            and isinstance(body[i + 1].value, ast.Constant)
            and isinstance(body[i + 1].value.value, str)
        ):
            doc = " ".join(body[i + 1].value.value.split())
        value = ast.unparse(node.value)
        out.append((name, value, doc))
    return out


# ---------------------------------------------------------------------------
# Block renderers
# ---------------------------------------------------------------------------


def render_versions() -> str:
    rows = [
        (
            "Route & timetable builder",
            ROUTE_BUILDER_VERSION,
            ROUTE_BUILDER_DESCRIPTION,
            "backend/models/route/model.py",
            "backend/models/README.md",
        ),
        (
            "Energy model",
            ENERGY_CALC_VERSION,
            ENERGY_MODEL_DESCRIPTION,
            "backend/models/energy/model.py",
            "backend/models/energy/README.md",
        ),
        (
            "Demand model",
            DEMAND_MODEL_VERSION,
            DEMAND_MODEL_DESCRIPTION,
            "backend/models/demand/model.py",
            "backend/models/demand/README.md",
        ),
        (
            "Cost & revenue evaluation",
            CALC_VERSION,
            CALC_MODEL_DESCRIPTION,
            "backend/models/evaluation/model.py",
            "backend/models/evaluation/README.md",
        ),
        (
            "Emissions model",
            EMISSIONS_MODEL_VERSION,
            EMISSIONS_MODEL_DESCRIPTION,
            "backend/models/emissions/model.py",
            "backend/models/emissions/README.md",
        ),
        (
            "Composition cost model",
            COMPOSITIONS_MODEL_VERSION,
            COMPOSITIONS_MODEL_DESCRIPTION,
            "backend/models/compositions/model.py",
            "backend/models/compositions/calib/CALIBRATION.md",
        ),
        (
            "Infrastructure parameter model",
            INFRA_MODEL_VERSION,
            INFRA_MODEL_DESCRIPTION,
            "backend/models/infrastructure/model.py",
            "backend/models/infrastructure/STOP_CLASSIFICATION.md",
        ),
    ]
    lines = [
        "| Model | Version | What it computes | Anchor file | Documentation |",
        "|---|---|---|---|---|",
    ]
    for title, version, desc, anchor, doc in rows:
        lines.append(
            f"| {title} | `{version}` | {desc} | [`{Path(anchor).name}`](../{anchor}) "
            f"| [{Path(doc).name}](../{doc}) |"
        )
    return "\n".join(lines)


# The cost/revenue tree exactly as built in models/evaluation/views.py
# (Breakdown → cost.{operator.{variable,fixed}, infrastructure}, revenue,
# margin). Each node is (formula_key, heading, [children]); leaves have an
# empty children list. This is the ONE place that encodes the tree shape
# for docs/MODEL.md — if the Breakdown tree in views.py ever changes,
# update this alongside it.
CALC_TREE: list[tuple[str, str, list]] = [
    (
        "total_cost_eur",
        "Total cost",
        [
            (
                "operator_total_eur",
                "Operator cost",
                [
                    (
                        "operator_variable_total_eur",
                        "Variable operator cost",
                        [
                            ("driver_eur", "Driver cost", []),
                            ("crew_eur", "Cabin crew cost", []),
                            ("coach_maintenance_eur", "Coach maintenance", []),
                            ("loco_eur", "Locomotive rental", []),
                            ("svc_stockings_eur", "Onboard service", []),
                            ("var_overhead_eur", "Variable overhead", []),
                        ],
                    ),
                    (
                        "operator_fixed_total_eur",
                        "Fixed operator cost",
                        [
                            ("coach_amortisation_eur", "Coach write-off", []),
                            ("financing_eur", "Financing", []),
                            ("fix_overhead_eur", "Fixed overhead", []),
                            ("cleaning_eur", "Cleaning", []),
                            ("shunting_eur", "Shunting", []),
                        ],
                    ),
                ],
            ),
            (
                "infrastructure_total_eur",
                "Infrastructure cost",
                [
                    ("tac_eur", "Track access charge", []),
                    ("energy_eur", "Traction electricity", []),
                    ("station_charge_eur", "Station charges", []),
                    ("parking_eur", "Overnight parking", []),
                ],
            ),
        ],
    ),
    (
        "total_revenue_eur",
        "Total revenue",
        [("ticket_revenue_eur", "Ticket revenue", [])],
    ),
    ("ebit_margin_eur", "Profit requirement (margin)", []),
    ("net_eur", "Net result", []),
]


def render_formula_card(model: str, key: str, heading: str, level: int) -> list[str]:
    """One formula as a heading + LaTeX + description + I/O table +
    'Used by' line, at the given markdown heading depth (### / #### / ...)."""
    f = REGISTRIES[model]["formulas"][key]
    used_by_formula, _ = build_used_by()
    anchor = formula_anchor(model, key)
    hashes = "#" * level
    parts = [f'<a id="{anchor}"></a>']
    parts.append(f"{hashes} {heading} — `{key}`")
    parts.append("")
    parts.append(f"$$ {f.latex} $$")
    parts.append("")
    parts.append(f.description)
    parts.append("")
    parts.append("| | Symbol | Meaning | Unit | Source |")
    parts.append("|---|---|---|---|---|")
    for prm in f.inputs:
        parts.append(
            f"| Input | `{prm.symbol}` | {prm.description} | {prm.unit} "
            f"| {ref_link(prm.ref)} |"
        )
    out = f.output
    parts.append(
        f"| **Output** | `{out.symbol}` | {out.description} | {out.unit} | — |"
    )
    ub = _used_by_line(used_by_formula.get(f"{model}.{key}", []))
    if ub:
        parts.append("")
        parts.append(ub)
    parts.append("")
    return parts


def render_calc_tree() -> str:
    """Renders CALC_TREE depth-first, heading level increasing with depth
    (#### for the root subtotals, deeper for their children), so the
    document mirrors the Breakdown tree exactly — every subtotal appears
    with its own formula box directly above the leaves it sums, and every
    leaf's 'Source' column links back up to the parameter or upstream
    formula that produced it."""

    def walk(nodes: list, level: int) -> list[str]:
        out = []
        for key, heading, children in nodes:
            out.extend(render_formula_card("calc", key, heading, level))
            if children:
                out.extend(walk(children, level + 1))
        return out

    return "\n".join(walk(CALC_TREE, 4)).rstrip()


def render_formulas(model: str) -> str:
    meta = REGISTRIES[model]
    used_by_formula, _ = build_used_by()
    parts = []
    for key, f in meta["formulas"].items():
        anchor = formula_anchor(model, key)
        parts.append(f'<a id="{anchor}"></a>')
        parts.append(f"#### `{key}`")
        parts.append("")
        parts.append(f"$$ {f.latex} $$")
        parts.append("")
        parts.append(f.description)
        parts.append("")
        parts.append("| | Symbol | Meaning | Unit | Source |")
        parts.append("|---|---|---|---|---|")
        for prm in f.inputs:
            parts.append(
                f"| Input | `{prm.symbol}` | {prm.description} | {prm.unit} "
                f"| {ref_link(prm.ref)} |"
            )
        out = f.output
        parts.append(
            f"| **Output** | `{out.symbol}` | {out.description} | {out.unit} | — |"
        )
        ub = _used_by_line(used_by_formula.get(f"{model}.{key}", []))
        if ub:
            parts.append("")
            parts.append(ub)
        parts.append("")
    return "\n".join(parts).rstrip()


def render_parameters() -> str:
    _, used_by_column = build_used_by()
    parts = []
    for table in INPUT_PARAMS_TABLES + SCENARIO_TABLES:
        qualified_table = f"{table.schema}.{table.name}"
        parts.append(f"#### `{qualified_table}`")
        parts.append("")
        parts.append(table.description)
        parts.append("")
        parts.append("| Column | Meaning | Unit | Used in |")
        parts.append("|---|---|---|---|")
        for col in table.columns:
            qualified = f"{qualified_table}.{col.name}"
            consumers = used_by_column.get(qualified, [])
            used = ", ".join(
                f"[`{key}`](#{formula_anchor(model, key)})"
                for model, key in sorted(set(consumers))
            )
            desc = col.description or "—"
            parts.append(
                f'| <a id="{column_anchor(qualified)}"></a>`{col.name}` '
                f"| {desc} | {col.unit or '—'} | {used or '—'} |"
            )
        parts.append("")
    return "\n".join(parts).rstrip()


def render_standard_values() -> str:
    parts = []
    for std_id, path in STANDARD_VALUE_FILES.items():
        values = extract_standard_values(path)
        if not values:
            continue
        rel = path.relative_to(BACKEND.parent).as_posix()
        parts.append(f"#### {std_id.title()} model — [`{path.name}`](../{rel})")
        parts.append("")
        parts.append("| Constant | Value | Meaning |")
        parts.append("|---|---|---|")
        for name, value, doc in values:
            parts.append(
                f'| <a id="{standard_anchor(std_id, name)}"></a>`{name}` '
                f"| `{value}` | {doc or '—'} |"
            )
        parts.append("")
    return "\n".join(parts).rstrip()


def render_emission_factors() -> str:
    parts = [
        "| Mode | g CO2e per passenger-km | Source |",
        "|---|---|---|",
    ]
    for mode, factor in EMISSION_FACTORS.items():
        parts.append(
            f"| {mode.replace('_', ' ')} | {factor.g_per_pax_km:g} | {factor.source} |"
        )
    parts.append("")
    shares = ", ".join(f"{m} {s:.0%}" for m, s in MODE_SHIFT_SHARES.items())
    parts.append(
        "Placeholder mode-shift assumption for the CO2-savings estimate "
        f"(share of a route's passengers assumed shifted from each mode): {shares}."
    )
    return "\n".join(parts)


# calc formulas that don't sit in the Breakdown tree — an upstream step
# (splitting shared costs across accommodation classes) consumed by the
# per-class normalisations, not a cost/revenue line itself.
CALC_ALLOCATION_FORMULAS = [
    ("class_main_allocation", "Cost share by accommodation class"),
    ("per_sold_place_km_by_class", "Cost per sold place-km, by class"),
]

# Upstream derivations consumed by the cost leaves — computed per trip
# rather than read from a parameter, and not cost or revenue lines
# themselves. Distinct from CALC_ALLOCATION_FORMULAS, which is
# specifically about splitting a cost across accommodation classes.
CALC_DERIVATION_FORMULAS = [
    ("roster_efficiency_driver", "Roster efficiency (Dienstplanwirkungsgrad)"),
    ("tac_night_share", "Night share of a country run (track access)"),
    ("tac_peak_share", "Rush-hour share of a country run (track access)"),
    ("energy_night_share", "Night share of a country run (electricity)"),
]

# The generic aggregation rule (x_total = sum of a level's items), which
# the country/section/OD/stop matrix views reuse at levels the fixed
# CALC_TREE above doesn't name individually.
CALC_GENERIC_FORMULAS = [("total_eur", "Generic level total")]


def render_calc_formulas() -> str:
    def render_list(entries):
        return "\n".join(
            "\n".join(render_formula_card("calc", key, heading, 4))
            for key, heading in entries
        ).rstrip()

    tree_keys = set()

    def collect(nodes):
        for key, _, children in nodes:
            tree_keys.add(key)
            collect(children)

    collect(CALC_TREE)
    covered = (
        {k for k, _ in CALC_ALLOCATION_FORMULAS}
        | {k for k, _ in CALC_DERIVATION_FORMULAS}
        | {k for k, _ in CALC_GENERIC_FORMULAS}
        | tree_keys
    )
    missing = set(REGISTRIES["calc"]["formulas"]) - covered
    if missing:
        raise SystemExit(
            f"generate_model_docs: CALC_FORMULAS keys not placed in CALC_TREE, "
            f"CALC_ALLOCATION_FORMULAS, CALC_DERIVATION_FORMULAS, or "
            f"CALC_GENERIC_FORMULAS: {sorted(missing)}"
        )
    return (
        "**Cost allocation to accommodation classes** — an upstream step "
        "used by every per-class normalisation below, not a cost or "
        f"revenue line itself:\n\n{render_list(CALC_ALLOCATION_FORMULAS)}\n\n"
        "**Upstream derivations** — quantities the cost leaves below divide "
        "or multiply by, computed per trip rather than read from a "
        f"parameter:\n\n{render_list(CALC_DERIVATION_FORMULAS)}\n\n"
        "**The cost/revenue tree** — every subtotal shown with the exact "
        "leaves it sums, in the same structure as the tool's cost "
        f"breakdown views:\n\n{render_calc_tree()}\n\n"
        "**Generic aggregation** — the same summation rule the matrix "
        "views (by country, connection, route section, or stop) apply at "
        f"levels not named individually above:\n\n{render_list(CALC_GENERIC_FORMULAS)}"
    )


BLOCKS = {
    "versions": render_versions,
    "route_formulas": lambda: render_formulas("route"),
    "energy_formulas": lambda: render_formulas("energy"),
    "calc_formulas": render_calc_formulas,
    "standard_values": render_standard_values,
    "emission_factors": render_emission_factors,
    "parameters": render_parameters,
}


# ---------------------------------------------------------------------------
# Splice + entry point
# ---------------------------------------------------------------------------


def splice(doc: str) -> str:
    for name, renderer in BLOCKS.items():
        begin = f"<!-- BEGIN GENERATED: {name} -->"
        end = f"<!-- END GENERATED: {name} -->"
        if begin not in doc or end not in doc:
            raise SystemExit(f"docs/MODEL.md is missing the marker pair for '{name}'")
        pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end), re.DOTALL)
        block = f"{begin}\n{renderer()}\n{end}"
        # lambda repl: rendered LaTeX contains backslashes that re.sub would
        # otherwise parse as escape sequences
        doc = pattern.sub(lambda _m: block, doc, count=1)
    return doc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail (exit 1) if docs/MODEL.md is not up to date with the registries",
    )
    args = parser.parse_args()

    current = DOC_PATH.read_text(encoding="utf-8")
    updated = splice(current)
    if args.check:
        if updated != current:
            raise SystemExit(
                "docs/MODEL.md is out of date with the model registries — run "
                "`uv run python scripts/generate_model_docs.py` and commit the result."
            )
        print("docs/MODEL.md is up to date.")
        return
    DOC_PATH.write_text(updated, encoding="utf-8")
    print(f"docs/MODEL.md regenerated ({len(updated)} chars).")


if __name__ == "__main__":
    main()
