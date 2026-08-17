"""
test_76_calc_facility_units.py
==============================
Pure unit tests for the service-facility charge model in
models/infrastructure/facility/calc_facility.py — no Docker stack, no DB.
Runnable standalone:

    uv run --extra dev pytest tests/test_76_calc_facility_units.py -v

Rates here are round test numbers, not the calibrated ones: what is pinned is
the MECHANICS — which arithmetic a stabling basis selects, how a free
allowance interacts with a layover, and what hotel power is charged on.

Three mechanics carry most of the weight and are the reason this file exists.
Europe prices a stabling occupation four different ways and picking the wrong
one silently misprices a country by an order of magnitude. A free allowance
longer than the layover zeroes the siding charge but **not** the power drawn
while standing. And a started period is a whole period: eleven and a half
hours on a per-hour tariff is twelve hours billed, not eleven and a half.

Every rate the model reads is EUR at the evaluation year; the calibration
notebook converts currency and price basis once, before seeding.
"""

import pytest

from models.infrastructure.facility.calc_facility import (
    calc_parking_event,
    shunting_event_eur,
)
from models.params import TrackInfrastructure

REF_LENGTH_M = 300.0  # the reference train, 1 locomotive + 10 coaches

# Track access and energy rates set absurdly high — the mirror of what test_73
# and test_75 do. A facility charge that reflects only facility columns is the
# guard that the three infrastructure domains stay apart.
ABSURD = 999_999.0


def _track(**overrides) -> TrackInfrastructure:
    kwargs = {
        "country_code": "XX",
        "field_is_default": {},
        "has_row": True,
        "tac_eur_train_km": ABSURD,
        "parking_eur_day": ABSURD,  # the display column — never read
        "shunting_eur_event": 250.0,
        "energy_price_eur_kwh": ABSURD,
        "terrain_score": 1.0,
        "terrain_category": "Flat",
        "hsr_allowed": True,
        "min_boarding_time_min": 2,
        "min_alighting_time_min": 2,
        "buffer_quota_per": 0.0,
        "tac_b_day": ABSURD,
        "tac_b_night": ABSURD,
        "tac_gamma": ABSURD,
        "tac_seat_km": ABSURD,
        "tac_per_stop": ABSURD,
        "tac_revenue_share": 1.0,
        "tac_fixed_per_train_km": ABSURD,
        "tac_peak_multiplier": None,
        "tac_congestion_surcharge_eur_km": ABSURD,
        "tac_night_mode": "none",
        "tac_night_band_start_min": None,
        "tac_night_band_end_min": None,
        "tac_night_full_if_accommodation": False,
        "tac_peak_band1_start_min": None,
        "tac_peak_band1_end_min": None,
        "tac_peak_band2_start_min": None,
        "tac_peak_band2_end_min": None,
        "tac_peak_weekdays_only": False,
        "energy_price_night_eur_kwh": None,
        "energy_night_band_start_min": None,
        "energy_night_band_end_min": None,
        "energy_catenary_eur_train_km": ABSURD,
        "energy_catenary_eur_gross_tonne_km": None,
        "parking_basis": None,
        "parking_eur_metre_day": None,
        "parking_eur_hour": None,
        "parking_eur_event": None,
        "parking_free_hours": None,
        "parking_hotel_power_eur_hour": None,
    }
    kwargs.update(overrides)
    return TrackInfrastructure(**kwargs)


def _park(track, hours: float, length_m: float = REF_LENGTH_M):
    return calc_parking_event(track, length_m=length_m, hours=hours)


# ---------------------------------------------------------------------------
# shunting
# ---------------------------------------------------------------------------


def test_shunting_is_the_all_in_per_event_figure():
    """One number per country, read straight through. What makes it defensible
    is the calibration, not arithmetic here: roughly nine tenths of it is the
    market cost of a locomotive and crew the infrastructure manager does not
    supply."""
    assert shunting_event_eur(_track(shunting_eur_event=180.0)) == 180.0


# ---------------------------------------------------------------------------
# per_metre_day — the majority basis
# ---------------------------------------------------------------------------


def _metre_day(**overrides):
    return _track(
        parking_basis="per_metre_day", parking_eur_metre_day=0.20, **overrides
    )


def test_per_metre_day_charges_one_started_day_for_a_layover():
    charge = _park(_metre_day(), 12.0)
    assert charge.facility_eur == pytest.approx(0.20 * 300 * 1)
    assert charge.basis == "per_metre_day"


def test_per_metre_day_counts_started_days_not_fractions():
    """Every sourced length-based tariff charges per *started* 24 h. A 30 h
    stay is two days, not 1.25 — and a 25 h stay is already two."""
    assert _park(_metre_day(), 30.0).facility_eur == pytest.approx(0.20 * 300 * 2)
    assert _park(_metre_day(), 25.0).facility_eur == pytest.approx(0.20 * 300 * 2)
    assert _park(_metre_day(), 24.0).facility_eur == pytest.approx(0.20 * 300 * 1)


def test_per_metre_day_scales_with_train_length():
    """A longer train occupies more siding. This is the basis that makes the
    length matter, and the reason Parking pricing needs the composition."""
    short = _park(_metre_day(), 12.0, length_m=150.0)
    long_ = _park(_metre_day(), 12.0, length_m=400.0)
    assert long_.facility_eur == pytest.approx(short.facility_eur * 400 / 150)


# ---------------------------------------------------------------------------
# per_hour — Germany, length-independent by design
# ---------------------------------------------------------------------------


def _per_hour(**overrides):
    return _track(parking_basis="per_hour", parking_eur_hour=6.00, **overrides)


def test_per_hour_charges_started_hours():
    assert _park(_per_hour(), 12.0).facility_eur == pytest.approx(72.0)
    assert _park(_per_hour(), 11.5).facility_eur == pytest.approx(72.0)


def test_per_hour_ignores_train_length():
    """DB InfraGO's Anlagenpreissystem calls the charge expressly
    zuglängenunabhängig, so a per-metre model must not leak into it."""
    short = _park(_per_hour(), 12.0, length_m=150.0)
    long_ = _park(_per_hour(), 12.0, length_m=400.0)
    assert short.facility_eur == long_.facility_eur == pytest.approx(72.0)


# ---------------------------------------------------------------------------
# per_event and none
# ---------------------------------------------------------------------------


def test_per_event_has_no_time_term():
    """Greece defines stabling as exactly two manoeuvres and Italy as one
    operation: a train that stands at all pays the flat charge, and standing
    longer costs nothing more."""
    track = _track(parking_basis="per_event", parking_eur_event=45.0)
    assert _park(track, 2.0).facility_eur == pytest.approx(45.0)
    assert _park(track, 36.0).facility_eur == pytest.approx(45.0)


def test_per_event_still_needs_the_train_to_stand():
    track = _track(parking_basis="per_event", parking_eur_event=45.0)
    assert _park(track, 0.0).facility_eur == 0.0


def test_basis_none_is_a_documented_zero():
    """Denmark and Slovenia levy nothing on sidings. That is a tariff fact, and
    it must not pick up a European default — which is the difference between
    the basis 'none' and a NULL basis."""
    assert _park(_track(parking_basis="none"), 12.0).facility_eur == 0.0


def test_unknown_basis_prices_zero_and_warns(caplog):
    """A basis the model does not know is a data error. Pricing it as zero and
    saying so beats guessing an arithmetic."""
    track = _track(parking_basis="per_fortnight", parking_eur_hour=6.0)
    with caplog.at_level("WARNING"):
        assert _park(track, 12.0).facility_eur == 0.0
    assert "unknown parking basis" in caplog.text


# ---------------------------------------------------------------------------
# free allowances
# ---------------------------------------------------------------------------


def test_free_allowance_longer_than_the_layover_zeroes_the_siding():
    """Norway's first 48 h and Croatia's first 24 h are free, which is why both
    cost nothing on a twelve-hour turnaround. Getting this wrong invents a
    charge two countries do not levy."""
    track = _metre_day(parking_free_hours=48.0)
    charge = _park(track, 12.0)
    assert charge.billable_hours == 0.0
    assert charge.facility_eur == 0.0


def test_free_allowance_is_subtracted_before_the_started_period_rounds():
    """30 h with 24 h free is six billable hours — one started day, not two.
    Rounding first and subtracting after would double the charge."""
    track = _metre_day(parking_free_hours=24.0)
    assert _park(track, 30.0).facility_eur == pytest.approx(0.20 * 300 * 1)


def test_free_allowance_applies_to_the_hourly_basis_too():
    """Portugal charges beyond the first hour only."""
    track = _per_hour(parking_free_hours=1.0)
    assert _park(track, 12.0).facility_eur == pytest.approx(6.00 * 11)


# ---------------------------------------------------------------------------
# hotel power
# ---------------------------------------------------------------------------


def test_hotel_power_is_charged_on_actual_stabled_hours():
    track = _metre_day(parking_hotel_power_eur_hour=15.0)
    charge = _park(track, 12.0)
    assert charge.hotel_power_eur == pytest.approx(180.0)
    assert charge.total_eur == pytest.approx(charge.facility_eur + 180.0)


def test_hotel_power_ignores_the_free_track_allowance():
    """The single most easily broken rule here: the electricity flows whether
    or not the siding is free. Norway's 48 free hours zero the siding and
    nothing else."""
    track = _metre_day(parking_free_hours=48.0, parking_hotel_power_eur_hour=15.0)
    charge = _park(track, 12.0)
    assert charge.facility_eur == 0.0
    assert charge.hotel_power_eur == pytest.approx(180.0)


def test_hotel_power_is_not_rounded_to_started_hours():
    """The siding is sold in started periods; energy is metered. A flat hourly
    proxy stands in for a metered rate, so it stays proportional."""
    track = _metre_day(parking_hotel_power_eur_hour=15.0)
    assert _park(track, 11.5).hotel_power_eur == pytest.approx(172.5)


def test_a_country_with_no_hotel_power_rate_pays_none():
    track = _metre_day()
    assert _park(track, 12.0).hotel_power_eur == 0.0


# ---------------------------------------------------------------------------
# degenerate inputs
# ---------------------------------------------------------------------------


def test_no_layover_prices_nothing():
    """A one-way route stables nothing: Parking.hours is 0.0 and pricing a
    layover of unknown length would be an invention."""
    charge = _park(_metre_day(parking_hotel_power_eur_hour=15.0), 0.0)
    assert charge.total_eur == 0.0


def test_a_negative_layover_never_produces_a_credit():
    """Defensive: the route builder wraps a negative gap forward a day, so this
    should be unreachable — but a schedule bug must not pay the operator."""
    charge = _park(_metre_day(parking_hotel_power_eur_hour=15.0), -6.0)
    assert charge.facility_eur == 0.0
    assert charge.hotel_power_eur == 0.0


def test_uncalibrated_country_prices_nothing_here():
    """A NULL basis means the calibration has no figures for this country. The
    loader substitutes the European default group before the model ever sees
    it, so reaching calc_facility with a NULL basis means that resolution was
    skipped — and pricing zero is the visible failure mode."""
    charge = _park(_track(), 12.0)
    assert charge.basis == "none"
    assert charge.total_eur == 0.0


def test_track_access_and_energy_columns_are_never_read():
    """Every rate from the other two infrastructure domains is absurd on this
    fixture. A facility charge built only from facility columns is the guard."""
    track = _metre_day(parking_hotel_power_eur_hour=15.0)
    charge = _park(track, 12.0)
    assert charge.total_eur == pytest.approx(0.20 * 300 + 15.0 * 12)
