"""
factors.py
==========
Flat per-mode GHG intensity factors (docs/PROPOSALS_DESIGN.md decision
24) — the single source for the night-train, air, and car
g CO2e/pax-km values used across the platform:
`proposals.proposal_summaries.co2_g_per_pax_km`, the "summary" block of
POST /api/proposal/calc, the `evaluation.models.emissions` documentation
entry (api/helpers/evaluation_serialize.py: models_to_dict()), and the
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

EMISSIONS_MODEL_VERSION: str = "0.1.0"

EMISSIONS_MODEL_DESCRIPTION: str = (
    "Flat per-mode GHG intensity factors (g CO2e per passenger-km) — "
    "reference values for the gallery's mode comparison and inputs to the "
    "placeholder CO2-savings estimate. The night-train value is a flat "
    "European average pending an energy-based, country-resolved model."
)


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
