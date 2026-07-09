"""
version.py
==========
Version constant and model description for the Night Train Energy Model.

Bump ENERGY_CALC_VERSION when any change affects energy_kwh output:
  - Formula structure or regression coefficients change
  - New variables added to the energy model
  - Any change to calc_energy_consumption.py

ENERGY_FORMULAS documents the energy model calculations with LaTeX
and plain-English descriptions.

NOTE: The current implementation is a dummy flat factor — see
calc_energy_consumption.py. ENERGY_FORMULAS describes the target
regression model that the energy model team is calibrating.

TODO: GIT_SHA injected at build time by CI — see .github/workflows/backend-tests.yml
"""

from __future__ import annotations
from dataclasses import dataclass

# =============================================================================
# VERSION
# =============================================================================

ENERGY_CALC_VERSION: str = "0.9.0"

GIT_SHA: str = "unknown"  # injected by CI

# Short, plain-English summary of what this model computes — embedded as-is
# in the "models" section of POST /api/evaluation/calc's response, alongside
# ENERGY_CALC_VERSION and ENERGY_FORMULAS.
ENERGY_MODEL_DESCRIPTION: str = (
    "Traction energy consumption model: estimates kWh consumed per route "
    "segment. Currently a flat 28.0 kWh/km placeholder factor (see "
    "ENERGY_FORMULAS['energy_dummy']), pending calibration of the target "
    "weight/speed/terrain regression model against Deutsche Bahn "
    "Trassenfinder data."
)

CHANGELOG: dict = {
    "1.0.0": {
        "date": "2026-06-25",
        "author": "david",
        "changes": "Dummy implementation: flat 28.0 kWh/km factor. "
        "Does not account for weight, speed, or terrain. "
        "Requires calibration by energy model team — "
        "see models/energy/README.md and ONBOARDING.md.",
    },
}


# =============================================================================
# ENERGY FORMULA REGISTRY
# =============================================================================


@dataclass(frozen=True)
class EnergyFormula:
    """One entry in the energy model calculation description."""

    latex: str
    description: str


ENERGY_FORMULAS: dict[str, EnergyFormula] = {
    # ------------------------------------------------------------------
    # TARGET REGRESSION MODEL (to be calibrated — see README.md)
    # ------------------------------------------------------------------
    "energy_per_leg": EnergyFormula(
        latex=r"E_{kWh,l} = m_t \times d_{km,l} \times "
        r"\left( f_{weight} + f_{speed} \cdot \bar{v}^2_{kmh,l} "
        r"+ f_{terrain} \cdot s_{terrain,l} \right)",
        description="Energy consumed on a country leg: train gross weight × distance × "
        "a sum of three terms — a base weight-distance factor, a speed-squared "
        "term capturing aerodynamic drag, and a terrain score term. "
        "Coefficients f_weight, f_speed, f_terrain are calibrated via "
        "regression against Deutsche Bahn Trassenfinder data.",
    ),
    "energy_per_km": EnergyFormula(
        latex=r"e_{kWh/km,l} = \frac{E_{kWh,l}}{d_{km,l}}",
        description="Energy intensity per km on a country leg: total energy divided "
        "by distance. Used for display and cross-country comparison.",
    ),
    "total_energy": EnergyFormula(
        latex=r"E_{total} = \sum_{seg} \sum_{l \in seg} E_{kWh,l}",
        description="Total trip energy: sum of energy across all country legs.",
    ),
    # ------------------------------------------------------------------
    # INPUTS
    # ------------------------------------------------------------------
    "avg_speed": EnergyFormula(
        latex=r"\bar{v}_{kmh,l} = \frac{d_{km,l}}{t_{drive,h,l}}",
        description="Average speed per country leg: distance divided by driving time. "
        "Used as the speed input to the energy regression.",
    ),
    "train_weight": EnergyFormula(
        latex=r"m_t = \sum_{coach} m_{coach,t} + m_{loco,t}",
        description="Total train gross weight: sum of all coach weights plus "
        "locomotive weight. Sourced from CoachType.weight_gross_t "
        "and composition structure.",
    ),
    # ------------------------------------------------------------------
    # CURRENT DUMMY (placeholder until calibration complete)
    # ------------------------------------------------------------------
    "energy_dummy": EnergyFormula(
        latex=r"E_{kWh,l} = c_{dummy} \times d_{km,l}",
        description="DUMMY: flat energy factor applied regardless of weight, speed, "
        "or terrain. c_dummy = 28.0 kWh/km. Replace with calibrated "
        "regression model — see models/energy/README.md.",
    ),
}
