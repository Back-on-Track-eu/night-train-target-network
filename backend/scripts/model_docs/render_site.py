"""
render_site.py
==============
Renders docs-site/ — the public documentation site.

Same contract as render_model_md.py: only the marked blocks are
replaced, so hand-written prose outside them survives regeneration and
the --check gate covers both artefacts.

The difference is linking. docs/MODEL.md is one flat file, so every ref
resolves to a "#anchor" on the same page. The site is many pages, so a
ref has to resolve to "page#anchor" — see site_link(). Anchors keep the
extraction layer's scheme (f-/p-/s-), so existing links into MODEL.md
still land on the matching heading here.
"""

from __future__ import annotations

import re
from pathlib import Path

from .extract import (
    BACKEND,
    CALC_ALLOCATION_FORMULAS,
    CALC_DERIVATION_FORMULAS,
    CALC_GENERIC_FORMULAS,
    EMISSION_FACTORS,
    INPUT_PARAMS_TABLES,
    MODE_SHIFT_SHARES,
    MODEL_CHANGELOGS,
    MODEL_VERSION_ROWS,
    REGISTRIES,
    SCENARIO_TABLES,
    STANDARD_VALUE_FILES,
    build_used_by,
    column_anchor,
    extract_standard_values,
    formula_anchor,
    iter_calc_tree,
    parse_ref,
    standard_anchor,
    validate_calc_coverage,
    validate_summaries,
)

SITE = BACKEND.parent / "docs-site"

# Reference pages the emitter owns end to end.
REFERENCE_DIR = SITE / "reference"
COST_DIR = SITE / "cost"


# ---------------------------------------------------------------------------
# The deep-link contract
# ---------------------------------------------------------------------------


def cost_slug(key: str) -> str:
    """Cost-tree formula key -> its page slug. tac_eur -> tac,
    operator_variable_total_eur -> operator-variable-total.

    The frontend derives the same slug to build the info popover's
    "Read the full explanation" link, so this rule is a contract:
    strip a trailing _eur, then underscores become hyphens.
    """
    return re.sub(r"_eur$", "", key).replace("_", "-")


def _tree_keys() -> set[str]:
    return {key for key, _, _ in iter_calc_tree()}


def site_link(ref: str) -> str:
    """One FormulaParam.ref as a markdown link into the site."""
    parsed = parse_ref(ref)
    if parsed.kind == "upstream":
        return "computed upstream"
    if parsed.kind == "user":
        return "set by you"
    if parsed.kind == "formula":
        model, _, key = parsed.target.partition(".")
        if model == "calc" and key in _tree_keys():
            return f"[{key}](/cost/{cost_slug(key)})"
        return f"[{key}](/reference/formulas#{parsed.anchor})"
    if parsed.kind == "column":
        return f"[{parsed.label}](/reference/parameters#{parsed.anchor})"
    return f"[{parsed.label}](/reference/standard-values#{parsed.anchor})"


def _feeds_into(model: str, key: str) -> str:
    used_by_formula, _ = build_used_by()
    consumers = used_by_formula.get(f"{model}.{key}", [])
    if not consumers:
        return ""
    links = ", ".join(
        f"[{k}](/cost/{cost_slug(k)})"
        if m == "calc" and k in _tree_keys()
        else f"[{k}](/reference/formulas#{formula_anchor(m, k)})"
        for m, k in sorted(set(consumers))
    )
    return f"**Feeds into:** {links}"


# ---------------------------------------------------------------------------
# Shared renderers
# ---------------------------------------------------------------------------


def _legend_table(formula) -> list[str]:
    rows = [
        "| | Symbol | Meaning | Unit | Where it comes from |",
        "|---|---|---|---|---|",
    ]
    for prm in formula.inputs:
        rows.append(
            f"| Input | `{prm.symbol}` | {prm.description} | {prm.unit} "
            f"| {site_link(prm.ref)} |"
        )
    out = formula.output
    rows.append(f"| **Result** | `{out.symbol}` | {out.description} | {out.unit} | — |")
    return rows


def _formula_block(model: str, key: str) -> str:
    """Summary + formula + legend + downstream links. The reader-facing
    explanation is hand-written above this block, not here."""
    f = REGISTRIES[model]["formulas"][key]
    parts = [
        f'<a id="{formula_anchor(model, key)}"></a>',
        "",
        f.summary,
        "",
        "### The formula",
        "",
        f"$$ {f.latex} $$",
        "",
        *_legend_table(f),
    ]
    feeds = _feeds_into(model, key)
    if feeds:
        parts += ["", feeds]
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Cost pages — one per node of the breakdown tree
# ---------------------------------------------------------------------------

_COST_PAGE_TEMPLATE = """---
title: {heading}
description: {summary}
---

# {heading}

<!-- BEGIN GENERATED: formula -->
<!-- END GENERATED: formula -->

## In plain language

<!-- Hand-written. The generated block above carries the formula, the
     legend and the links; this section is where the number is explained
     to someone who will never read the code. Not yet written. -->

## Where the numbers come from

<!-- Hand-written: which calibration this draws on, what is sourced and
     what is assumed. See the methodology pages. -->
"""


def cost_pages() -> dict[Path, dict]:
    """{path: {block name: rendered}} for every cost-tree node."""
    pages = {}
    for key, heading, _depth in iter_calc_tree():
        path = COST_DIR / f"{cost_slug(key)}.md"
        pages[path] = {
            "blocks": {"formula": _formula_block("calc", key)},
            "template": _COST_PAGE_TEMPLATE.format(
                heading=heading,
                summary=REGISTRIES["calc"]["formulas"][key].summary.replace('"', "'"),
            ),
        }
    return pages


# ---------------------------------------------------------------------------
# Reference pages
# ---------------------------------------------------------------------------


def render_versions() -> str:
    lines = [
        "| Model | Version | What it computes |",
        "|---|---|---|",
    ]
    for title, version, desc, _anchor, _doc in MODEL_VERSION_ROWS:
        lines.append(f"| {title} | `{version}` | {desc} |")
    return "\n".join(lines)


# An entry that moved published numbers says so in its own words. The
# reader who needs this page most is the one who quoted a figure and wants
# to know whether it still holds, so those entries are marked rather than
# left to be found by reading all 69.
_VALUES_CHANGED = re.compile(r"VALUES CHANGE|BREAKING")


def render_changelog() -> str:
    """Every model's dated changelog, newest first, verbatim.

    Deliberately unedited: these entries were written by the engineers for
    themselves and are technical in places. Publishing the real record
    rather than a press summary is the point — a rewritten changelog is a
    claim about history, the original is evidence of it. The hand-written
    intro on the page frames that for the reader."""
    parts = []
    for model_name, changelog in MODEL_CHANGELOGS.items():
        parts += [f"## {model_name}", ""]
        for version, entry in changelog.items():
            moved = _VALUES_CHANGED.search(entry["changes"]) is not None
            flag = " — published numbers changed" if moved else ""
            parts += [
                f"### `{version}` — {entry['date']}{flag}",
                "",
                entry["changes"],
                "",
            ]
    return "\n".join(parts).rstrip()


def render_reference_formulas() -> str:
    """Every formula that does NOT have its own cost page: the route and
    energy registries, plus the calc formulas that sit outside the
    breakdown tree."""
    parts = []
    for model in ("route", "energy"):
        parts += [f"## {REGISTRIES[model]['title']}", ""]
        for key in REGISTRIES[model]["formulas"]:
            parts += [f"### `{key}`", "", _formula_block(model, key), ""]

    off_tree = (
        ("Cost allocation to accommodation classes", CALC_ALLOCATION_FORMULAS),
        ("Upstream derivations", CALC_DERIVATION_FORMULAS),
        ("Generic aggregation", CALC_GENERIC_FORMULAS),
    )
    for title, entries in off_tree:
        parts += [f"## {title}", ""]
        for key, heading in entries:
            parts += [f"### {heading} — `{key}`", "", _formula_block("calc", key), ""]
    return "\n".join(parts).rstrip()


def render_parameters() -> str:
    _, used_by_column = build_used_by()
    parts = []
    for table in INPUT_PARAMS_TABLES + SCENARIO_TABLES:
        qualified_table = f"{table.schema}.{table.name}"
        parts += [f"## `{qualified_table}`", "", table.description, ""]
        parts += ["| Parameter | Meaning | Unit | Used in |", "|---|---|---|---|"]
        for col in table.columns:
            qualified = f"{qualified_table}.{col.name}"
            consumers = used_by_column.get(qualified, [])
            used = ", ".join(
                f"[{key}](/cost/{cost_slug(key)})"
                if model == "calc" and key in _tree_keys()
                else f"[{key}](/reference/formulas#{formula_anchor(model, key)})"
                for model, key in sorted(set(consumers))
            )
            parts.append(
                f'| <a id="{column_anchor(qualified)}"></a>`{col.name}` '
                f"| {col.description or '—'} | {col.unit or '—'} | {used or '—'} |"
            )
        parts.append("")
    return "\n".join(parts).rstrip()


def render_standard_values() -> str:
    parts = []
    for std_id, path in STANDARD_VALUE_FILES.items():
        values = extract_standard_values(path)
        if not values:
            continue
        parts += [f"## {std_id.title()} model", ""]
        parts += ["| Constant | Value | Meaning |", "|---|---|---|"]
        for name, value, doc in values:
            parts.append(
                f'| <a id="{standard_anchor(std_id, name)}"></a>`{name}` '
                f"| `{value}` | {doc or '—'} |"
            )
        parts.append("")
    return "\n".join(parts).rstrip()


def render_emission_factors() -> str:
    parts = ["| Mode | g CO2e per passenger-km | Source |", "|---|---|---|"]
    for mode, factor in EMISSION_FACTORS.items():
        parts.append(
            f"| {mode.replace('_', ' ')} | {factor.g_per_pax_km:g} | {factor.source} |"
        )
    shares = ", ".join(f"{m} {s:.0%}" for m, s in MODE_SHIFT_SHARES.items())
    parts += [
        "",
        "The CO2 saving compares a night train against the trip someone "
        "would otherwise have made. Which trip that is, is an assumption, "
        f"not a measurement: {shares}.",
    ]
    return "\n".join(parts)


_REFERENCE_PAGES = {
    "versions.md": ("Model versions", {"versions": render_versions}),
    "changelog.md": ("What changed", {"changelog": render_changelog}),
    "formulas.md": ("All formulas", {"formulas": render_reference_formulas}),
    "parameters.md": ("Parameter reference", {"parameters": render_parameters}),
    "standard-values.md": (
        "Standard values",
        {"standard_values": render_standard_values},
    ),
    "emission-factors.md": (
        "Emission factors",
        {"emission_factors": render_emission_factors},
    ),
}

_REFERENCE_TEMPLATE = """---
title: {title}
---

# {title}

<!-- Generated from the model registries. Edit the model, not this page —
     anything outside the GENERATED markers survives regeneration. -->

{blocks}
"""


def reference_pages() -> dict[Path, dict]:
    pages = {}
    for filename, (title, renderers) in _REFERENCE_PAGES.items():
        blocks = {name: fn() for name, fn in renderers.items()}
        marker_block = "\n\n".join(
            f"<!-- BEGIN GENERATED: {name} -->\n<!-- END GENERATED: {name} -->"
            for name in renderers
        )
        pages[REFERENCE_DIR / filename] = {
            "blocks": blocks,
            "template": _REFERENCE_TEMPLATE.format(title=title, blocks=marker_block),
        }
    return pages


# ---------------------------------------------------------------------------
# Splice + the check/write seam
# ---------------------------------------------------------------------------


def _splice(doc: str, blocks: dict[str, str], path: Path) -> str:
    for name, rendered in blocks.items():
        begin = f"<!-- BEGIN GENERATED: {name} -->"
        end = f"<!-- END GENERATED: {name} -->"
        if begin not in doc or end not in doc:
            raise SystemExit(f"{path} is missing the marker pair for '{name}'")
        pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end), re.DOTALL)
        replacement = f"{begin}\n{rendered}\n{end}"
        # lambda repl: rendered LaTeX carries backslashes re.sub would eat
        doc = pattern.sub(lambda _m: replacement, doc, count=1)
    return doc


def _all_pages() -> dict[Path, dict]:
    validate_calc_coverage()
    validate_summaries()
    return {**reference_pages(), **cost_pages()}


def _target(page: dict, path: Path) -> str:
    current = path.read_text(encoding="utf-8") if path.exists() else page["template"]
    return _splice(current, page["blocks"], path)


def check() -> bool:
    """True when every emitted page matches the registries. A page that
    does not exist yet counts as out of date."""
    for path, page in _all_pages().items():
        if not path.exists() or path.read_text(encoding="utf-8") != _target(page, path):
            return False
    return True


def write() -> int:
    """Create or update every page; returns the total character count."""
    total = 0
    for path, page in _all_pages().items():
        path.parent.mkdir(parents=True, exist_ok=True)
        content = _target(page, path)
        path.write_text(content, encoding="utf-8")
        total += len(content)
    return total
