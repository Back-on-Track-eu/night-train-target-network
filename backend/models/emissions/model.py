"""
model.py
========
Version anchor and factor set of the emissions model: flat per-mode GHG
intensity factors (adapters/proposal/README.md decision 24) — the single
source for the night-train, air, and car g CO2e/pax-km values used
across the platform: `proposals.proposal_summaries.co2_g_per_pax_km`,
the "summary" block of POST /api/proposal/calc, the
`evaluation.models.emissions` documentation entry
(api/helpers/evaluation_serialize.py: models_to_dict()), and the
placeholder CO2-savings derivation in models/evaluation/summary.py.

The night-train value is a flat European average until an energy-based,
country-resolved model replaces it (energy_kwh per segment x country
grid intensity / sold places). The factors migrate into a
scenario-versioned params table with the WP16 schema split — until
then, these constants are the single source. The ONTD side is NOT a
consumer: existing routes carry their own per-route value from
`ontd.trips.co2_per_km` (decision 27 — every existing-route KPI comes
from ONTD itself).
"""

from __future__ import annotations

from dataclasses import dataclass

EMISSIONS_MODEL_VERSION: str = "0.1.1"

EMISSIONS_MODEL_DESCRIPTION: str = (
    "Climate impact factors: how many grams of CO2-equivalent one "
    "passenger-kilometre causes by night train, plane, and car — used for "
    "the mode comparison and the CO2-savings estimate. The night-train "
    "value is a European average until a country-resolved, energy-based "
    "model replaces it."
)

CHANGELOG: dict = {
    "0.1.1": {
        "date": "2026-08-10",
        "author": "david",
        "changes": "factors.py renamed to model.py (every model now anchors "
        "version, description, and changelog in a model.py); CHANGELOG "
        "added; description rewritten in plain language for tool users. "
        "Factor values unchanged.",
    },
    "0.1.0": {
        "date": "2026-08-05",
        "author": "david",
        "changes": "Initial factor set (WP10 step 5, decision 24): EEA TERM "
        "2020 EU-average 2018 values — night train 33 (passenger-rail "
        "proxy), air 160, car 143 g CO2e/pax-km — plus the placeholder "
        "mode-shift shares (air 0.35, car 0.20) consumed by the "
        "CO2-savings estimate in models/evaluation/summary.py.",
    },
}


@dataclass(frozen=True)
class EmissionFactor:
    """One transport mode's GHG intensity plus its source, so every
    surfaced number stays traceable to where it came from."""

    g_per_pax_km: float
    source: str


# EEA TERM 2020 ("Motorised transport: train, plane, road or boat —
# which is greenest?"), EU-average 2018 figures per passenger-km.
EMISSION_FACTORS: dict[str, EmissionFactor] = {
    "night_train": EmissionFactor(
        g_per_pax_km=33.0,
        source="EEA TERM 2020: EU-average passenger rail, 2018 "
        "(33 g CO2e/pkm) — flat proxy for night trains until the "
        "energy-based, country-resolved model lands",
    ),
    "air": EmissionFactor(
        g_per_pax_km=160.0,
        source="EEA TERM 2020: intra-EU aviation, 2018 (160 g CO2/pkm, "
        "CO2 only — excludes non-CO2 radiative forcing such as contrails "
        "and NOx, which would push the effective value substantially higher)",
    ),
    "car": EmissionFactor(
        g_per_pax_km=143.0,
        source="EEA TERM 2020: passenger car at average occupancy, 2018 "
        "(143 g CO2e/pkm)",
    ),
}

# Placeholder mode-shift assumptions (design doc §8.1): the share of a
# proposal's demand assumed shifted away from each competing mode when
# estimating CO2 savings. Demand-model territory hosted here only
# because their sole consumer is the emissions-savings placeholder in
# models/evaluation/summary.py — they move to models/demand/ when the
# real demand model lands.
MODE_SHIFT_SHARES: dict[str, float] = {
    "air": 0.35,
    "car": 0.20,
}
