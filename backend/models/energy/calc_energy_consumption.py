"""
calc_energy_consumption.py
==========================
Energy consumption calculation for night train trips.

!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
!! DUMMY IMPLEMENTATION — REQUIRES REPLACEMENT                             !!
!!                                                                         !!
!! This module uses a flat kWh/km factor as a placeholder.                !!
!! It does NOT account for:                                                !!
!!   - Composition weight (heavier trains use more energy)                !!
!!   - Speed (energy scales with v²)                                      !!
!!   - Topography / terrain score (mountains use more energy)             !!
!!   - Regenerative braking on downhill segments                          !!
!!   - Traction system efficiency differences by country                  !!
!!                                                                         !!
!! A proper regression-based energy model should be developed in a        !!
!! separate workstream using the formula:                                  !!
!!   energy_kwh = weight_t × km × (f_weight                              !!
!!                + f_speed × avg_speed_kmh²                             !!
!!                + f_terrain × terrain_score)                            !!
!!                                                                         !!
!! Calibration data: Deutsche Bahn Trassenfinder OpenAPI                  !!
!! Calibration scripts: trassenfinder_collector.py, calibrate_energy.py  !!
!! Assigned to: energy model team                                         !!
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

Called exclusively from route_factory.py during Trip construction.
Enriches each CountryLeg in the TripPath with energy_kwh and
energy_kwh_per_km by mutating in-place.

Unit conventions
----------------
  Distance: metres (_m) — converted to km internally for kWh/km calculation
  Energy  : kWh   (_kwh)
"""

from __future__ import annotations

import logging
from models.params import Composition
from models.route.trip import TripPath

logger = logging.getLogger(__name__)

# =============================================================================
# DUMMY CONSTANT
# =============================================================================

# !! DUMMY VALUE — replace with calibrated regression coefficients !!
# Approximate average energy consumption for a loaded night train composition.
# Based on rough ÖBB Nightjet reference figures (~25-30 kWh/km for a full
# 10-12 coach formation including locomotive).
# Does NOT vary by weight, speed, or terrain.
_DUMMY_KWH_PER_KM: float = 28.0


# =============================================================================
# PUBLIC FUNCTION
# =============================================================================

def calc_energy_consumption(
        trip_path:   TripPath,
        composition: Composition,
) -> None:
    """
    Enrich each CountryLeg in trip_path.segments with energy_kwh
    and energy_kwh_per_km. Mutates in-place.

    !! DUMMY IMPLEMENTATION — see module docstring !!

    Applies a flat factor of {_DUMMY_KWH_PER_KM} kWh/km regardless of
    composition weight, speed, or terrain. The composition parameter is
    accepted for API compatibility with the future real implementation
    but is not used.

    Parameters
    ----------
    trip_path : TripPath
        TripPath returned by RailRouter.route(). CountryLeg.energy_kwh
        is 0.0 on entry. distance_m in metres — converted to km internally.
    composition : Composition
        Vehicle composition. Currently unused — reserved for the real
        implementation which will use total_weight_t and energy factors.

    Called exclusively from route_factory.py.
    """
    logger.warning(
        "calc_energy_consumption: using DUMMY flat factor %.1f kWh/km — "
        "not suitable for production use. "
        "See models/energy/calc_energy_consumption.py.",
        _DUMMY_KWH_PER_KM,
    )

    for segment in trip_path.segments:
        for cl in segment.country_legs:
            distance_km       = cl.distance_m / 1000.0
            energy_kwh        = _DUMMY_KWH_PER_KM * distance_km
            energy_kwh_per_km = _DUMMY_KWH_PER_KM if distance_km > 0 else 0.0

            cl.energy_kwh        = energy_kwh
            cl.energy_kwh_per_km = energy_kwh_per_km