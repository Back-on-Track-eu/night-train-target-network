"""
model.py
========
Version anchor and factor set of the emissions model: flat per-mode GHG
intensity factors (adapters/proposal/README.md decision 24) — the single
source for the night-train, air, and car g CO2e/pax-km values used
across the platform: `proposals.proposal_summaries.co2_g_per_pax_km`,
the "summary" block of a member (and of every family member), the
`evaluation.models.emissions` documentation entry
(api/helpers/evaluation_serialize.py: models_to_dict()), and the
CO2-savings derivation in models/evaluation/summary.py, which combines
them with the demand model's source split (models/demand/sources.py).

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

EMISSIONS_MODEL_VERSION: str = "0.2.0"

EMISSIONS_MODEL_DESCRIPTION: str = (
    "Climate impact factors: how many grams of CO2-equivalent one "
    "passenger-kilometre causes by night train, plane, and car, including "
    "the non-CO2 warming of aviation — used for the mode comparison and "
    "the CO2-savings estimate. The night-train value is a European average "
    "until a country-resolved, energy-based model replaces it."
)

CHANGELOG: dict = {
    "0.2.0": {
        "date": "2026-09-19",
        "author": "david + claude",
        "changes": "FACTORS RE-BASED on Back-on-Track's 2022 report 'The Global "
        "Warming Reduction Potential of Night-Trains' (Figure 3): plane 389, "
        "car 132, night train 14 g CO2e per passenger-km — well-to-wheel, "
        "EU energy mix, reference year 2019, INCLUDING the non-CO2 radiative "
        "forcing of aviation on the GWP* basis, which the EEA TERM 2020 "
        "figures used until now (160 / 143 / 33) left out. The train-to-plane "
        "ratio moves from 1:5 to 1:28. MODE_SHIFT_SHARES is gone: the share of "
        "a route's passengers that would otherwise have flown is no longer a "
        "flat 35 %, it is the demand model's distance-dependent source split "
        "(models/demand/sources.py, DEMAND 0.1.0), applied per OD pair. Every "
        "co2_savings_t_per_year changes.",
    },
    "0.1.2": {
        "date": "2026-09-13",
        "author": "david",
        "changes": "DOCUMENTATION ONLY - no value changes. The module docstring "
        "now names the family as the consumer of the factor set, following the "
        "WP18 move to POST /api/proposal/family as the single compute path. "
        "Factors, sources and mode-shift shares are untouched. Bumped only "
        "because the version-check gate self-gates this file: any diff requires "
        "the constant to move. Side effect: the bump marks every stored proposal "
        "outdated, so each recomputes lazily on its next load and gets an "
        "update_log entry naming this trigger - the recompute reproduces "
        "identical numbers.",
    },
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


# Back-on-Track (2022), "The Global Warming Reduction Potential of
# Night-Trains", Figure 3 — g CO2e per passenger-km, well-to-wheel, EU
# energy mix, reference year 2019, including the non-CO2 radiative forcing
# of aviation (contrails, NOx, water vapour) on the GWP* basis. The report
# builds on the EEA emissions data and adds the non-CO2 term, which is what
# separates its 389 for a plane from the EEA's CO2-only 160.
_BOT_2022 = (
    "Back-on-Track 2022, The Global Warming Reduction Potential of "
    "Night-Trains, Figure 3 (g CO2e/pkm, GWP*, well-to-wheel, EU mix 2019) — "
    "https://back-on-track.eu/the-global-warming-reduction-potential-of-night-trains/"
)

EMISSION_FACTORS: dict[str, EmissionFactor] = {
    "night_train": EmissionFactor(
        g_per_pax_km=14.0,
        source=_BOT_2022 + ": an average EU night train at a high load "
        "factor — flat proxy until the energy-based, country-resolved "
        "model lands",
    ),
    "air": EmissionFactor(
        g_per_pax_km=389.0,
        source=_BOT_2022 + ": intra-EU flight incl. non-CO2 radiative "
        "forcing; 1:28 against the night train",
    ),
    "car": EmissionFactor(
        g_per_pax_km=132.0,
        source=_BOT_2022 + ": passenger car at average occupancy",
    ),
}
