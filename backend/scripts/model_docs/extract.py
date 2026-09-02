"""
extract.py
==========
Reads the calculation model's source of truth and exposes it as plain
data. No output formatting lives here — that is each renderer's job.

Sources (never duplicated by hand):
  - models/*/model.py     formula registries (Formula/FormulaParam incl.
                          the 'ref' source pointers), versions,
                          descriptions, standard values, emission factors
  - db/schema.py          parameter tables with descriptions and units

The anchor helpers live here rather than in a renderer because both
artefacts share one anchor scheme: existing links into docs/MODEL.md
keep working when the same id is emitted by the site.
"""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

from db.schema import INPUT_PARAMS_TABLES, SCENARIO_TABLES  # noqa: E402
from models.compositions.model import (  # noqa: E402
    COMPOSITIONS_MODEL_DESCRIPTION,
    COMPOSITIONS_MODEL_VERSION,
)
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
from models.infrastructure.model import (  # noqa: E402
    INFRA_MODEL_DESCRIPTION,
    INFRA_MODEL_VERSION,
)
from models.route.model import (  # noqa: E402
    ROUTE_BUILDER_DESCRIPTION,
    ROUTE_BUILDER_VERSION,
    ROUTE_FORMULAS,
)

__all__ = [
    "BACKEND",
    "CALC_ALLOCATION_FORMULAS",
    "CALC_DERIVATION_FORMULAS",
    "CALC_GENERIC_FORMULAS",
    "CALC_TREE",
    "EMISSION_FACTORS",
    "INPUT_PARAMS_TABLES",
    "MODE_SHIFT_SHARES",
    "MODEL_VERSION_ROWS",
    "REGISTRIES",
    "SCENARIO_TABLES",
    "STANDARD_VALUE_FILES",
    "Ref",
    "build_used_by",
    "column_anchor",
    "extract_standard_values",
    "formula_anchor",
    "iter_calc_tree",
    "parse_ref",
    "standard_anchor",
    "validate_calc_coverage",
    "validate_summaries",
]

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

# One row per versioned model: (title, version, description, anchor file,
# documentation file). Both artefacts render a versions table from this.
MODEL_VERSION_ROWS: list[tuple[str, str, str, str, str]] = [
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


# Longest summary that still fits the cost-breakdown info popover on one
# or two lines. Raising it means re-checking that overlay.
_SUMMARY_MAX_LEN = 110


# ---------------------------------------------------------------------------
# Anchors — one scheme, shared by every artefact
# ---------------------------------------------------------------------------


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "-", text.lower()).strip("-")


def formula_anchor(model: str, key: str) -> str:
    return f"f-{_slug(model)}-{_slug(key)}"


def column_anchor(qualified: str) -> str:
    return f"p-{_slug(qualified)}"


def standard_anchor(std_id: str, const: str) -> str:
    return f"s-{_slug(std_id)}-{_slug(const)}"


# ---------------------------------------------------------------------------
# Refs — FormulaParam.ref parsed into structured form
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Ref:
    """One parsed FormulaParam.ref.

    kind   — "formula" | "column" | "standard" | "user" | "upstream"
    target — the raw pointer body ("calc.tac_night_share",
             "input_params.track_infrastructures.track_tac_b_day",
             "INFRASTRUCTURE.WEEKDAY_BLEND"); empty for user/upstream
    """

    kind: str
    target: str = ""

    @property
    def anchor(self) -> str:
        """The stable html id this ref points at ("" when it points at no
        documented artefact)."""
        if self.kind == "formula":
            model, _, key = self.target.partition(".")
            return formula_anchor(model, key)
        if self.kind == "column":
            return column_anchor(self.target)
        if self.kind == "standard":
            std_id, _, const = self.target.partition(".")
            return standard_anchor(std_id, const)
        return ""

    @property
    def label(self) -> str:
        """The bare name of the thing pointed at, for link text."""
        if self.kind == "formula":
            return self.target.partition(".")[2]
        if self.kind == "column":
            return self.target.rsplit(".", 1)[1]
        if self.kind == "standard":
            return self.target.partition(".")[2]
        return ""


def parse_ref(ref: str) -> Ref:
    """Parse one FormulaParam.ref. Raises on an unknown pointer kind, so a
    typo in a model.py fails the build rather than rendering as prose."""
    if not ref:
        return Ref("upstream")
    if ref == "user":
        return Ref("user")
    kind, _, target = ref.partition(":")
    if kind not in {"formula", "column", "standard"}:
        raise ValueError(f"unknown ref: {ref}")
    return Ref(kind, target)


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
# The cost/revenue tree
# ---------------------------------------------------------------------------

# The cost/revenue tree exactly as built in models/evaluation/views.py
# (Breakdown → cost.{operator.{variable,fixed}, infrastructure}, revenue,
# margin). Each node is (formula_key, heading, [children]); leaves have an
# empty children list. This is the ONE place that encodes the tree shape
# for every documentation artefact — if the Breakdown tree in views.py ever
# changes, update this alongside it.
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


def iter_calc_tree(
    nodes: list | None = None, depth: int = 0
) -> list[tuple[str, str, int]]:
    """Flatten CALC_TREE depth-first into [(key, heading, depth)]."""
    out = []
    for key, heading, children in CALC_TREE if nodes is None else nodes:
        out.append((key, heading, depth))
        out.extend(iter_calc_tree(children, depth + 1))
    return out


def validate_calc_coverage() -> None:
    """Every CALC_FORMULAS key must be placed in exactly one documented
    group, so a new formula cannot ship undocumented."""
    tree_keys = {key for key, _, _ in iter_calc_tree()}
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


def validate_summaries() -> None:
    """Formula.summary is what the reader sees where there is no room for
    the full description — the cost-breakdown popover, a docs page
    description, a search snippet. The dataclass makes it required; this
    checks it is actually usable there."""
    problems = []
    for model, meta in REGISTRIES.items():
        for key, formula in meta["formulas"].items():
            summary = formula.summary.strip()
            if not summary:
                problems.append(f"{model}.{key}: empty summary")
            elif not summary.endswith((".", "?")):
                problems.append(f"{model}.{key}: summary needs a terminal period")
            elif len(summary) > _SUMMARY_MAX_LEN:
                problems.append(
                    f"{model}.{key}: summary is {len(summary)} chars, "
                    f"max {_SUMMARY_MAX_LEN} — it has to fit an info popover"
                )
    if problems:
        raise SystemExit(
            "generate_model_docs: unusable Formula.summary values:\n  "
            + "\n  ".join(problems)
        )
