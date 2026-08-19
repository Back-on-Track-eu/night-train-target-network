"""
model.py
========
Version constant, description, changelog, and formula registry of the
Night Train Energy Model.

Bump ENERGY_CALC_VERSION when any change affects energy_kwh output:
  - Formula structure or regression coefficients change
  - New variables added to the energy model
  - Any change to calc_energy_consumption.py

ENERGY_FORMULAS documents the energy model for tool users: LaTeX,
plain-language descriptions, and input/output legends with units
(models/formula.py).

NOTE: The current implementation is a dummy flat factor — see
calc_energy_consumption.py. The regression formulas below describe the
target model the energy model team is calibrating.

TODO: GIT_SHA injected at build time by CI — see .github/workflows/backend-tests.yml
"""

from __future__ import annotations

from models.formula import Formula, FormulaParam

# =============================================================================
# VERSION
# =============================================================================

ENERGY_CALC_VERSION: str = "0.9.1"

GIT_SHA: str = "unknown"  # injected by CI

# =============================================================================
# STANDARD VALUES
# =============================================================================

ENERGY_FLAT_FACTOR_KWH_KM: float = 28.0
"""Flat placeholder energy factor used by calc_energy_consumption.py until
the weight/speed/terrain regression is calibrated. Every train is assumed
to use this much electricity per kilometre, regardless of weight, speed,
or terrain."""

# Short, plain-language summary of what this model computes — embedded as-is
# in the "models" section of POST /api/proposal/calc's response, alongside
# ENERGY_CALC_VERSION and ENERGY_FORMULAS.
ENERGY_MODEL_DESCRIPTION: str = (
    "Traction energy model: estimates the electricity a train uses on "
    "each part of the route. Currently a flat 28 kWh per kilometre "
    "placeholder, until the weight/speed/terrain model is calibrated "
    "against Deutsche Bahn Trassenfinder data."
)

CHANGELOG: dict = {
    "0.9.1": {
        "date": "2026-08-10",
        "author": "david",
        "changes": "version.py renamed to model.py (every model now anchors "
        "version, description, changelog, and formulas in a model.py). "
        "ENERGY_FORMULAS rebuilt on the shared Formula/FormulaParam "
        "dataclasses (models/formula.py): every formula carries a full "
        "input/output legend with units, descriptions rewritten in plain "
        "language for tool users. ADDITIVE response change once "
        "serialized: each models.energy.formulas entry gains 'inputs' and "
        "'output', and input params carry an optional 'ref' source "
        "pointer (models/formula.py). The flat placeholder factor moved "
        "into STANDARD VALUES as ENERGY_FLAT_FACTOR_KWH_KM (value "
        "unchanged, 28.0). Bjarne coordination batch. No computed number "
        "changes.",
    },
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
# ENERGY FORMULA REGISTRY — LaTeX + plain-language description + input/output
# legend per formula (models/formula.py). Descriptions are written for tool
# users; developer detail lives in the comments next to each entry.
# =============================================================================

ENERGY_FORMULAS: dict[str, Formula] = {
    # ------------------------------------------------------------------
    # TARGET REGRESSION MODEL (to be calibrated — see README.md)
    # ------------------------------------------------------------------
    # Coefficients f_weight, f_speed, f_terrain are calibrated via
    # regression against Deutsche Bahn Trassenfinder data; they live on
    # the composition (composition_type_energy_factor_*).
    "energy_per_leg": Formula(
        latex=r"E_{kWh,l} = m_t \times d_{km,l} \times "
        r"\left( f_{weight} + f_{speed} \cdot \bar{v}^2_{kmh,l} "
        r"+ f_{terrain} \cdot s_{terrain,l} \right)",
        description="Electricity used on one country leg: the train's "
        "weight times the distance, scaled by three factors — a base "
        "factor, one growing with the square of speed (air resistance), "
        "and one for the terrain (hills and mountains cost energy).",
        inputs=(
            FormulaParam(
                symbol="m_t",
                ref="formula:energy.train_weight",
                description="Train gross weight",
                unit="t",
            ),
            FormulaParam(
                symbol="d_km,l",
                description="Distance of the country leg",
                unit="km",
            ),
            FormulaParam(
                symbol="f_weight",
                ref="column:input_params.composition_types.composition_type_energy_factor_weight",
                description="Base energy factor per tonne-kilometre",
                unit="kWh/(t·km)",
            ),
            FormulaParam(
                symbol="f_speed",
                ref="column:input_params.composition_types.composition_type_energy_factor_speed",
                description="Air resistance factor, applied to speed squared",
                unit="kWh/(t·km·(km/h)²)",
            ),
            FormulaParam(
                symbol="f_terrain",
                ref="column:input_params.composition_types.composition_type_energy_factor_terrain",
                description="Terrain factor, applied to the terrain score",
                unit="kWh/(t·km) per terrain point",
            ),
            FormulaParam(
                symbol="v̄_kmh,l",
                ref="formula:energy.avg_speed",
                description="Average speed on the leg",
                unit="km/h",
            ),
            FormulaParam(
                symbol="s_terrain,l",
                ref="column:input_params.track_infrastructures.track_terrain_score",
                description="Terrain difficulty score of the leg's country",
                unit="1–100",
            ),
        ),
        output=FormulaParam(
            symbol="E_kWh,l",
            description="Electricity used on the country leg",
            unit="kWh",
        ),
    ),
    "energy_per_km": Formula(
        latex=r"e_{kWh/km,l} = \frac{E_{kWh,l}}{d_{km,l}}",
        description="Energy use per kilometre on a country leg: total "
        "energy divided by distance. Used for display and for comparing "
        "countries.",
        inputs=(
            FormulaParam(
                symbol="E_kWh,l",
                ref="formula:energy.energy_per_leg",
                description="Electricity used on the country leg",
                unit="kWh",
            ),
            FormulaParam(
                symbol="d_km,l",
                description="Distance of the country leg",
                unit="km",
            ),
        ),
        output=FormulaParam(
            symbol="e_kWh/km,l",
            description="Energy use per kilometre",
            unit="kWh/km",
        ),
    ),
    "total_energy": Formula(
        latex=r"E_{total} = \sum_{seg} \sum_{l \in seg} E_{kWh,l}",
        description="Total electricity used on the trip: the energy of "
        "all country legs added up.",
        inputs=(
            FormulaParam(
                symbol="E_kWh,l",
                ref="formula:energy.energy_per_leg",
                description="Electricity used on each country leg",
                unit="kWh",
            ),
        ),
        output=FormulaParam(
            symbol="E_total",
            description="Total trip energy use",
            unit="kWh",
        ),
    ),
    # ------------------------------------------------------------------
    # INPUTS
    # ------------------------------------------------------------------
    "avg_speed": Formula(
        latex=r"\bar{v}_{kmh,l} = \frac{d_{km,l}}{t_{drive,h,l}}",
        description="Average speed per country leg: distance divided by "
        "driving time. Feeds the air resistance term of the energy "
        "model.",
        inputs=(
            FormulaParam(
                symbol="d_km,l",
                description="Distance of the country leg",
                unit="km",
            ),
            FormulaParam(
                symbol="t_drive,h,l",
                description="Driving time on the leg",
                unit="h",
            ),
        ),
        output=FormulaParam(
            symbol="v̄_kmh,l",
            description="Average speed on the leg",
            unit="km/h",
        ),
    ),
    "train_weight": Formula(
        latex=r"m_t = \sum_{coach} m_{coach,t} + m_{loco,t}",
        description="Total train weight: all coach weights added up, plus "
        "the locomotive.",
        inputs=(
            FormulaParam(
                symbol="m_coach,t",
                ref="column:input_params.coach_types.coach_type_weight_gross_t",
                description="Weight of each coach",
                unit="t",
            ),
            FormulaParam(
                symbol="m_loco,t",
                ref="column:input_params.loco_types.loco_type_weight_t",
                description="Locomotive weight",
                unit="t",
            ),
        ),
        output=FormulaParam(
            symbol="m_t",
            description="Train gross weight",
            unit="t",
        ),
    ),
    # ------------------------------------------------------------------
    # CURRENT DUMMY (placeholder until calibration complete)
    # ------------------------------------------------------------------
    "energy_dummy": Formula(
        latex=r"E_{kWh,l} = c_{dummy} \times d_{km,l}",
        description="Placeholder currently in use: a flat 28 kWh per "
        "kilometre, regardless of weight, speed, or terrain — until the "
        "model above is calibrated.",
        inputs=(
            FormulaParam(
                symbol="c_dummy",
                ref="standard:ENERGY.ENERGY_FLAT_FACTOR_KWH_KM",
                description="Flat energy factor",
                unit="kWh/km",
            ),
            FormulaParam(
                symbol="d_km,l",
                description="Distance of the country leg",
                unit="km",
            ),
        ),
        output=FormulaParam(
            symbol="E_kWh,l",
            description="Electricity used on the country leg",
            unit="kWh",
        ),
    ),
}
