"""
calc_energy_consumption.py
==========================
Energy consumption for night train trips.

DUMMY IMPLEMENTATION: flat 28 kWh/km factor, ignores weight, speed, and
terrain. Real model: energy_kwh = weight_t × km × (f_weight + f_speed ×
avg_speed_kmh² + f_terrain × terrain_score), calibrated against DB
Trassenfinder data (see trassenfinder_collector.py, calibrate_energy.py).

Called from route_factory.py between RailRouter.route() and _build_stops().
Mutates RoutedLeg.energy_kwh in-place.
"""

from __future__ import annotations

import logging

from models.params import Composition
from models.route.routing.rail_router import RoutedLeg

logger = logging.getLogger(__name__)

_DUMMY_KWH_PER_KM: float = 28.0


def calc_energy_consumption(
    routed_legs: list[RoutedLeg],
    composition: Composition,
) -> None:
    """Enrich each RoutedLeg.energy_kwh in-place. composition is currently
    unused — reserved for the real model."""
    logger.warning(
        "calc_energy_consumption: using DUMMY flat factor %.1f kWh/km.",
        _DUMMY_KWH_PER_KM,
    )
    for leg in routed_legs:
        leg.energy_kwh = _DUMMY_KWH_PER_KM * (leg.distance_m / 1000.0)