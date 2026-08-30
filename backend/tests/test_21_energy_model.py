"""
test_21_energy_model.py
=======================
Unit tests for the calibrated energy model (v1.1.0). These test the model
math directly on stub legs - no API, no DB - so they hold regardless of
which exact coefficients calib/02 last regenerated.

The two dummy-era tests in test_20_route_content.py
(test_energy_is_flat_factor_times_distance,
test_energy_independent_of_composition) assert dummy behaviour and MUST
be deleted with this change: energy now depends on the composition, which
is the point of the calibration.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from models.energy import calibrated_coefficients as coef
from models.energy.calc_energy_consumption import calc_energy_consumption


@dataclass
class _Leg:
    distance_m: int
    driving_time_min: float
    dynamics_time_min: float = 0.0
    energy_kwh: float = 0.0


class _Coach:
    pass


@dataclass
class _Comp:
    """Mirrors the fields calc reads off models.params.Composition:
    total_weight_t and total_length_m are plain floats there (coaches
    only, derived at build time), coaches a position-keyed dict."""

    total_weight_t: float
    total_length_m: float
    n: int
    coaches: dict = field(default_factory=dict)

    def __post_init__(self):
        self.coaches = {i + 1: _Coach() for i in range(self.n)}


# The fleet's corner points, from the calibration compositions.
LIGHT_SHORT = _Comp(313.0, 158.4, 6)   # REF-COUCH-6
LIGHT_LONG = _Comp(313.8, 185.7, 7)    # NEW-BAL-7 - same mass, +17% length
HEAVY = _Comp(636.0, 316.8, 12)        # REF-BUD-12


def _energy(comp, distance_km=500.0, avg_kmh=120.0):
    leg = _Leg(int(distance_km * 1000), distance_km / avg_kmh * 60.0)
    calc_energy_consumption([leg], comp)
    return leg.energy_kwh


class TestEnergyModel:
    def test_energy_rises_with_mass(self):
        assert _energy(HEAVY) > _energy(LIGHT_SHORT)
        ratio = _energy(HEAVY) / _energy(LIGHT_SHORT)
        # calibration observed 11.13 vs 6.77 kWh/km = 1.64x at fleet speeds
        assert 1.3 < ratio < 2.2

    def test_energy_rises_with_length_at_equal_mass(self):
        """The mass-matched pair property the sweep established: +17%
        length at equal mass costs energy (drag +6-8%, plus one more
        coach of hotel load)."""
        assert _energy(LIGHT_LONG) > _energy(LIGHT_SHORT)

    def test_energy_rises_with_speed_and_keeps_rising_past_the_range(self):
        """v^2 must keep climbing through 230 km/h average - the model
        extrapolates above the calibrated range instead of clamping."""
        speeds = [80, 120, 160, 200, 230]
        energies = [_energy(HEAVY, avg_kmh=v) for v in speeds]
        assert energies == sorted(energies)
        assert energies[-1] > energies[-2] * 1.05

    def test_intensity_in_plausible_range(self):
        """4-18 kWh/km covers the calibrated fleet (6.8-11.5 observed)
        plus hotel load, across normal speeds."""
        for comp in (LIGHT_SHORT, LIGHT_LONG, HEAVY):
            for v in (80, 120, 160):
                intensity = _energy(comp, avg_kmh=v) / 500.0
                assert 4.0 < intensity < 18.0, (comp.total_weight_t, v, intensity)

    def test_hotel_load_scales_with_coaches_and_time(self):
        """Two identical-physics comps differing only in coach count must
        differ by exactly P_hotel * delta_n * hours."""
        a = _Comp(500.0, 250.0, 9)
        b = _Comp(500.0, 250.0, 10)
        hours = 500.0 / 120.0
        expected = coef.P_HOTEL_PER_COACH_KW * hours
        assert _energy(b) - _energy(a) == pytest.approx(expected, rel=1e-9)

    def test_zero_guard(self):
        leg = _Leg(0, 0.0)
        calc_energy_consumption([leg], HEAVY)
        assert leg.energy_kwh == 0.0

    def test_dynamics_time_counts_as_moving_time(self):
        """Same leg, dynamics surcharge added: lower average speed, less
        drag - but more auxiliary hours. Both effects must flow through."""
        plain = _Leg(500_000, 250.0)
        with_dyn = _Leg(500_000, 250.0, dynamics_time_min=20.0)
        calc_energy_consumption([plain, with_dyn], HEAVY)
        assert plain.energy_kwh != with_dyn.energy_kwh
