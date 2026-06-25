"""
version.py
==========
Version constant and full calculation model definition for the
Night Train Cost/Revenue Evaluation model.

This file is the authoritative source for:
  - CALC_VERSION: bump when any EvaluationResult output changes
  - CALC_FORMULAS: LaTeX + description for every calculation step
  - CHANGELOG: what changed in each version

Bump CALC_VERSION when:
  - Revenue or cost calculation logic changes
  - New cost/revenue line items are added or removed
  - Normalisation logic changes
  - Any change to EvaluationResult or its nested dataclasses

CALC_FORMULAS is imported by calc.py and embedded in every
EvaluationResult so the frontend can render the full calculation
tree with LaTeX formulas and descriptions.

TODO: Injected at build time by CI — see .github/workflows/backend-tests.yml
"""

from __future__ import annotations
from dataclasses import dataclass


# =============================================================================
# VERSION
# =============================================================================

CALC_VERSION: str = "1.0.0"

GIT_SHA: str = "unknown"  # injected by CI

CHANGELOG: dict = {
    "1.0.0": {
        "date":    "2026-06-25",
        "author":  "david",
        "changes": "Initial implementation. Normalised matrix output (raw, per_trip, "
                   "per_trip_km, per_place_km_avg, per_place_of_class, "
                   "per_place_km_of_class) at route / trip / country level. "
                   "CalcStep and CalcFormula for full calculation transparency. "
                   "Revenue and allocation generic over service_class_main. "
                   "Country breakdown infrastructure-only, clearly scoped.",
    },
}


# =============================================================================
# CALC FORMULA REGISTRY
# =============================================================================

@dataclass(frozen=True)
class CalcFormula:
    """
    One entry in the calculation model — LaTeX formula + plain-English description.
    Keyed by a short snake_case identifier in CALC_FORMULAS.

    latex       — KaTeX/MathJax-compatible LaTeX string
    description — plain English explanation of what this step calculates
    """
    latex:       str
    description: str


CALC_FORMULAS: dict[str, CalcFormula] = {

    # ------------------------------------------------------------------
    # REVENUE
    # ------------------------------------------------------------------
    "passengers_per_class": CalcFormula(
        latex       = r"n_{pax,c} = \text{places}_c \times u_c",
        description = "Passengers per class: capacity multiplied by utilisation rate.",
    ),
    "revenue_per_class": CalcFormula(
        latex       = r"R_c = n_{pax,c} \times \bar{f}_c",
        description = "Revenue per class: passengers multiplied by average fare.",
    ),
    "total_revenue": CalcFormula(
        latex       = r"R = \sum_c R_c",
        description = "Total revenue: sum of revenue across all accommodation classes.",
    ),

    # ------------------------------------------------------------------
    # COST — FIXED / DAY
    # ------------------------------------------------------------------
    "loco_amortisation": CalcFormula(
        latex       = r"C_{loco,amort} = \frac{C_{loco,purchase}}{d_{loco,avail} \times T_{loco,amort}}",
        description = "Daily locomotive amortisation: purchase cost divided by available days over amortisation period.",
    ),
    "coach_amortisation": CalcFormula(
        latex       = r"C_{coach,amort} = \frac{C_{coach,purchase}}{d_{coach,avail} \times T_{coach,amort}}",
        description = "Daily coach amortisation: purchase cost divided by available days over amortisation period.",
    ),
    "financing": CalcFormula(
        latex       = r"C_{fin} = \frac{(C_{loco,purchase} + C_{coach,purchase}) \times q_{fin}}{365}",
        description = "Daily financing cost: total capital multiplied by annual financing quota, spread over 365 days.",
    ),
    "fix_overhead": CalcFormula(
        latex       = r"C_{fix,oh} = C_{op,base} \times q_{fix,oh}",
        description = "Fixed overhead: applied as a share of the operating cost base (maintenance + staff).",
    ),
    "cleaning": CalcFormula(
        latex       = r"C_{clean} = c_{clean/day}",
        description = "Daily cleaning and service preparation cost — fixed per operating day.",
    ),
    "shunting": CalcFormula(
        latex       = r"C_{shunt} = c_{shunt/event}",
        description = "Shunting cost per trip event at origin and destination.",
    ),
    "parking": CalcFormula(
        latex       = r"C_{park} = \sum_{l \in \text{endpoints}} p_{park,country(l)}",
        description = "Overnight stabling cost: sum of parking_eur_day for each unique endpoint country.",
    ),

    # ------------------------------------------------------------------
    # COST — VARIABLE / KM
    # ------------------------------------------------------------------
    "loco_maintenance": CalcFormula(
        latex       = r"C_{loco,maint} = c_{loco,maint/km} \times d_{km}",
        description = "Variable locomotive maintenance: per-km rate multiplied by trip distance.",
    ),
    "coach_maintenance": CalcFormula(
        latex       = r"C_{coach,maint} = c_{coach,maint/km} \times d_{km}",
        description = "Variable coach maintenance: per-km rate multiplied by trip distance.",
    ),

    # ------------------------------------------------------------------
    # COST — VARIABLE / HOUR
    # ------------------------------------------------------------------
    "driver_cost": CalcFormula(
        latex       = r"C_{driver} = c_{driver/h} \times (t_{drive,h} + t_{driver,oh,h})",
        description = "Driver staff cost: hourly rate multiplied by driving time plus fixed overhead hours.",
    ),
    "crew_cost": CalcFormula(
        latex       = r"C_{crew} = c_{crew/h} \times (t_{drive,h} + t_{crew,oh,h})",
        description = "Cabin crew cost: hourly rate multiplied by driving time plus fixed overhead hours.",
    ),

    # ------------------------------------------------------------------
    # COST — VARIABLE / TICKET
    # ------------------------------------------------------------------
    "svc_stockings_per_class": CalcFormula(
        latex       = r"C_{svc,c} = c_{svc,c/place} \times \text{places}_c",
        description = "Service and stockings per class: cost per available place multiplied by capacity.",
    ),
    "var_overhead": CalcFormula(
        latex       = r"C_{var,oh} = R \times q_{var,oh}",
        description = "Variable overhead: applied as a share of total revenue (covers customer service, payments).",
    ),

    # ------------------------------------------------------------------
    # COST — INFRASTRUCTURE
    # ------------------------------------------------------------------
    "track_access_charge": CalcFormula(
        latex       = r"C_{TAC} = \sum_{l \in \text{legs}} d_{km,l} \times p_{TAC,country(l)}",
        description = "Track access charge: sum over all country legs of distance multiplied by country TAC rate.",
    ),
    "energy_cost": CalcFormula(
        latex       = r"C_{energy} = \sum_{l \in \text{legs}} E_{kWh,l} \times p_{energy,country(l)}",
        description = "Traction energy cost: sum over all country legs of energy consumed multiplied by country electricity price.",
    ),
    "station_charges": CalcFormula(
        latex       = r"C_{station} = \sum_{s \in \text{stops}} c_{stop,s}",
        description = "Station access charges: sum of stop_charge_eur for all stops on the trip.",
    ),

    # ------------------------------------------------------------------
    # COST — EBIT
    # ------------------------------------------------------------------
    "ebit_margin": CalcFormula(
        latex       = r"C_{EBIT} = R \times q_{EBIT}",
        description = "EBIT margin target: deducted as a cost — required return on revenue.",
    ),

    # ------------------------------------------------------------------
    # ALLOCATION
    # ------------------------------------------------------------------
    "space_units_per_class": CalcFormula(
        latex       = r"S_c = \text{places}_c \times \rho_c",
        description = "Space units per class: capacity multiplied by density factor (1/berths-per-compartment).",
    ),
    "cost_allocated_per_class": CalcFormula(
        latex       = r"C_{alloc,c} = C_{total} \times \frac{S_c}{\sum_c S_c}",
        description = "Cost allocated to class: total cost weighted by that class's share of total space units.",
    ),
    "cost_per_place": CalcFormula(
        latex       = r"c_{place,c} = \frac{C_{alloc,c}}{\text{places}_c}",
        description = "Cost per available place in class: allocated cost divided by number of places.",
    ),

    # ------------------------------------------------------------------
    # NORMALISED VIEWS
    # ------------------------------------------------------------------
    "per_trip": CalcFormula(
        latex       = r"x_{/trip} = \frac{x}{N_{trips}}",
        description = "Per-trip average: divide by total number of trips in the route.",
    ),
    "per_trip_km": CalcFormula(
        latex       = r"x_{/trip\text{-}km} = \frac{x}{d_{km,total}}",
        description = "Per trip-km: divide by total route distance across all trips.",
    ),
    "per_place_km_avg": CalcFormula(
        latex       = r"x_{/place\text{-}km} = \frac{x}{\sum_c \text{places}_c \times \rho_c \times d_{km}}",
        description = "Per density-weighted place-km average: divide by total space-units × distance.",
    ),
    "per_place_of_class": CalcFormula(
        latex       = r"x_{/place,c} = \frac{x}{\text{places}_c}",
        description = "Per place of class: divide by number of available places in that accommodation class.",
    ),
    "per_place_km_of_class": CalcFormula(
        latex       = r"x_{/place\text{-}km,c} = \frac{x}{\text{places}_c \times d_{km}}",
        description = "Per place-km of class: divide by places in class multiplied by trip distance.",
    ),
}



# TODO: Add GitHub Actions version bump check to .github/workflows/backend-tests.yml
# Rule: if any file under backend/models/energy/ changes (except version.py itself),
# ENERGY_CALC_VERSION must differ from the value on main branch.
# Suggested step:
#
#   - name: Check energy model version bump
#     run: |
#       CHANGED=$(git diff origin/main --name-only \
#         | grep "^backend/models/energy/" \
#         | grep -v "version.py")
#       if [ -n "$CHANGED" ]; then
#         MAIN_VER=$(git show origin/main:backend/models/energy/version.py \
#           | grep ENERGY_CALC_VERSION | cut -d'"' -f2)
#         CUR_VER=$(grep ENERGY_CALC_VERSION backend/models/energy/version.py \
#           | cut -d'"' -f2)
#         if [ "$MAIN_VER" = "$CUR_VER" ]; then
#           echo "ERROR: models/energy/ changed but ENERGY_CALC_VERSION not bumped ($CUR_VER)"
#           exit 1
#         fi
#       fi