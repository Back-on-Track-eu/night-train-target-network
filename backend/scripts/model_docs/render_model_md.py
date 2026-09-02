"""
render_model_md.py
==================
Renders docs/MODEL.md — the developer-facing reference: one flat,
fully cross-linked document covering every formula, parameter and
standard value.

Only the marked blocks are replaced
(<!-- BEGIN GENERATED: name --> ... <!-- END GENERATED: name -->); all
narrative prose outside the markers is hand-written and preserved.

Cross-linking: every formula and every parameter column gets a stable
HTML anchor from extract.py. Upstream links come from FormulaParam.ref;
downstream "Used by" links are computed by inverting the ref graph, so
they can never drift.
"""

from __future__ import annotations

import re
from pathlib import Path

from .extract import (
    BACKEND,
    CALC_ALLOCATION_FORMULAS,
    CALC_DERIVATION_FORMULAS,
    CALC_GENERIC_FORMULAS,
    CALC_TREE,
    EMISSION_FACTORS,
    INPUT_PARAMS_TABLES,
    MODE_SHIFT_SHARES,
    MODEL_VERSION_ROWS,
    REGISTRIES,
    SCENARIO_TABLES,
    STANDARD_VALUE_FILES,
    build_used_by,
    column_anchor,
    extract_standard_values,
    formula_anchor,
    parse_ref,
    standard_anchor,
    validate_calc_coverage,
)

DOC_PATH = BACKEND.parent / "docs" / "MODEL.md"

# How each ref kind is named in a formula card's "Source" column.
_REF_PREFIX = {
    "formula": "formula",
    "column": "parameter",
    "standard": "standard value",
}


def ref_link(ref: str) -> str:
    """Render one FormulaParam.ref as a markdown link (or plain text)."""
    parsed = parse_ref(ref)
    if parsed.kind == "upstream":
        return "computed upstream"
    if parsed.kind == "user":
        return "set by the tool user"
    return f"{_REF_PREFIX[parsed.kind]} [`{parsed.label}`](#{parsed.anchor})"


def _used_by_line(consumers: list) -> str:
    links = ", ".join(
        f"[`{key}`](#{formula_anchor(model, key)})"
        for model, key in sorted(set(consumers))
    )
    return f"**Used by:** {links}" if consumers else ""


# ---------------------------------------------------------------------------
# Block renderers
# ---------------------------------------------------------------------------


def render_versions() -> str:
    lines = [
        "| Model | Version | What it computes | Anchor file | Documentation |",
        "|---|---|---|---|---|",
    ]
    for title, version, desc, anchor, doc in MODEL_VERSION_ROWS:
        lines.append(
            f"| {title} | `{version}` | {desc} | [`{Path(anchor).name}`](../{anchor}) "
            f"| [{Path(doc).name}](../{doc}) |"
        )
    return "\n".join(lines)


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


def render_calc_formulas() -> str:
    def render_list(entries):
        return "\n".join(
            "\n".join(render_formula_card("calc", key, heading, 4))
            for key, heading in entries
        ).rstrip()

    validate_calc_coverage()
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
# Splice
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


def check() -> bool:
    """True when docs/MODEL.md is up to date with the registries."""
    current = DOC_PATH.read_text(encoding="utf-8")
    return splice(current) == current


def write() -> int:
    """Rewrite the generated blocks in place; returns the doc's length."""
    current = DOC_PATH.read_text(encoding="utf-8")
    updated = splice(current)
    DOC_PATH.write_text(updated, encoding="utf-8")
    return len(updated)
