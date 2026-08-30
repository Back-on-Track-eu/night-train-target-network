"""
calc_energy_consumption.py
==========================
Energy consumption for night train trips - calibrated model.

Replaces the flat 28 kWh/km dummy (ENERGY_CALC_VERSION < 1.1.0). Fitted
against DB Trassenfinder technical runs: 1,192 route samples across all
eight standard compositions plus a 1,440-request booked-speed sweep over
a mass/length factorial. Fleet-weighted intensity of the calibration
sample is 9.19 kWh/km, so the dummy overstated traction energy roughly
threefold. Full derivation: models/energy/calib/ (02_energy_calibration
.ipynb regenerates calibrated_coefficients.py).

    E_leg = A*m                              start/stop, per leg
          + d * (B + C*m)                    rolling + constant, per km
          + d * (K_m*m + K_L*L) * v_avg^2    drag, avg leg speed squared
          + (P_loco + P_hotel*n) * t_h       auxiliaries + hotel, per hour

m = coach mass (t, 80% load, loco excluded), L = coach rake length (m),
n = number of coaches, d = leg km, v_avg = d / driving time, t_h = leg
driving time in hours. The drag term rises unclamped with average speed
- a 230 km/h leg gets 230^2 - which is deliberate: the coefficient is
identified up to DRAG_IDENTIFIED_UP_TO_KMH and the quadratic form was
verified on the sweep, so beyond that range the model extrapolates on
physics rather than on a fitted curve shape. The hotel term is an
assumption (Trassenfinder had coach load switched off); see
calibrated_coefficients.P_HOTEL_PER_COACH_KW.

Called from route_factory.py between RailRouter.route() and
_build_trip_stops_and_legs(). Mutates RoutedLeg.energy_kwh in-place.
"""

from __future__ import annotations

import logging

from models.energy import calibrated_coefficients as coef
from models.params import Composition
from models.route.routing.rail_router import RoutedLeg

logger = logging.getLogger(__name__)


def calc_energy_consumption(
    routed_legs: list[RoutedLeg],
    composition: Composition,
) -> None:
    """Enrich each RoutedLeg.energy_kwh in-place from the calibrated model."""
    mass_t = composition.total_weight_t  # coaches only - calibration basis
    length_m = composition.total_length_m
    n_coaches = len(composition.coaches)

    aux_kw = coef.P_LOCO_AUX_KW + coef.P_HOTEL_PER_COACH_KW * n_coaches
    drag_per_km = coef.K_MASS_DRAG * mass_t + coef.K_LENGTH_DRAG * length_m

    for leg in routed_legs:
        distance_km = leg.distance_m / 1000.0
        # Driving plus traction dynamics is the analogue of Trassenfinder's
        # technical running time, which the model was fitted on. Buffer is
        # schedule padding, not movement, and stays out of the speed.
        moving_min = leg.driving_time_min + leg.dynamics_time_min
        if distance_km <= 0 or moving_min <= 0:
            leg.energy_kwh = 0.0
            continue

        hours = moving_min / 60.0
        avg_speed_kmh = distance_km / hours

        if avg_speed_kmh > coef.DRAG_IDENTIFIED_UP_TO_KMH:
            logger.info(
                "energy model extrapolating: leg avg %.0f km/h exceeds the "
                "calibrated range (%.0f km/h); v^2 physics assumed to hold.",
                avg_speed_kmh,
                coef.DRAG_IDENTIFIED_UP_TO_KMH,
            )

        traction = (
            coef.A_PER_LEG_KWH_PER_T * mass_t
            + distance_km
            * (
                coef.B_PER_KM_KWH
                + coef.C_PER_TKM_KWH * mass_t
                + drag_per_km * avg_speed_kmh**2
            )
        )
        leg.energy_kwh = traction + aux_kw * hours
