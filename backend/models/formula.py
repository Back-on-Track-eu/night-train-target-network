"""
formula.py
==========
Shared formula-documentation dataclasses for every model under models/.

Each model's model.py documents its calculations in a formula registry
(ROUTE_FORMULAS, ENERGY_FORMULAS, CALC_FORMULAS) keyed by output field
name. One registry entry is a Formula: the LaTeX expression, a short
plain-language description written for tool users (not developers), and
a full input/output legend with units.

Serialization into API responses lives in
api/helpers/evaluation_serialize.py (models_to_dict()), per the
no-serialization-in-domain-objects rule.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FormulaParam:
    """One input or output of a formula.

    symbol      — identifier matching the LaTeX expression (e.g. "t_drive,l")
    description — one plain-language line on what the value means
    unit        — display unit (e.g. "min", "€/h"); "–" for dimensionless
    ref         — machine-readable pointer to where the value comes from,
                  used to render clickable upstream/downstream links
                  (docs/MODEL.md generator, API legend). One of:
                    "formula:<model>.<key>"            output of another formula
                    "column:<schema>.<table>.<column>" database parameter
                    "standard:<MODEL>.<CONSTANT>"      standard value in a model.py
                    "user"                             set by the tool user
                    ""                                 computed upstream (e.g.
                                                       routing engine), no single
                                                       linkable source
    """

    symbol: str
    description: str
    unit: str = "–"
    ref: str = ""


@dataclass(frozen=True)
class Formula:
    """One documented calculation step of a model.

    latex       — KaTeX/MathJax-compatible LaTeX string
    description — short plain-language explanation for tool users;
                  developer detail belongs in code comments or READMEs
    inputs      — legend of every symbol on the right-hand side
    output      — the left-hand side: what comes out, in which unit
    """

    latex: str
    description: str
    inputs: tuple[FormulaParam, ...]
    output: FormulaParam
