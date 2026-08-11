"""
test_72_roster_units.py
=======================
Pure unit tests for the Dienstplanwirkungsgrad (roster efficiency) model
in models/params.py — no Docker stack, no DB. Runnable standalone:

    uv run --extra dev pytest tests/test_72_roster_units.py -v

The model turns a raw productive-hour wage into the rate actually paid,
given how many crew shifts the trip needs. Worked reference (the
calibration's reference night route, 13.5 h driving / 14.5 h on train,
CALIBRATION.md "Roster efficiency"):

    driver  ceil(13.5 / 8)  = 2 duties
            0.60 x 14.5 / (14.5 + 2.5 x 1) = 0.5118
            54.16 / 0.5118 = 105.82 EUR/h
    crew    ceil(14.5 / 10) = 2 duties
            0.70 x 14.5 / (14.5 + 2.5 x 1) = 0.5971
            48.75 / 0.5971 =  81.65 EUR/h
"""

import pytest

from models.params import Operator

# Calibrated standard operator, 2032 basis (calib/seed/operators.csv).
DRIVER_RAW = 54.16
CREW_RAW = 48.75


def _operator(**overrides) -> Operator:
    kwargs = dict(
        operator_id="TEST",
        operator_name="Test operator",
        driver_costs_eur_h=DRIVER_RAW,
        crew_costs_eur_h=CREW_RAW,
        driver_max_duty_h=8.0,
        crew_max_duty_h=10.0,
        driver_roster_eff_ref=0.60,
        crew_roster_eff_ref=0.70,
        relief_allowance_h=2.5,
        ebit_margin_per=0.10,
        financing_quota_per=0.04,
        var_overhead_per=0.08,
        fix_overhead_quota_per=0.12,
        svc_stockings_eur_place={},
        loco_full_service_lease_eur_h=161.0,
    )
    kwargs.update(overrides)
    return Operator(**kwargs)


# ---------------------------------------------------------------------------
# single duty — the reference efficiency, unchanged
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("driving_h", [1.0, 4.0, 7.9, 8.0])
def test_driver_within_one_duty_keeps_reference_efficiency(driving_h):
    op = _operator()
    assert op.roster_efficiency("driver", driving_h, driving_h + 1.0) == pytest.approx(
        0.60
    )


@pytest.mark.parametrize("on_train_h", [2.0, 9.0, 10.0])
def test_crew_within_one_duty_keeps_reference_efficiency(on_train_h):
    op = _operator()
    assert op.roster_efficiency("crew", on_train_h, on_train_h) == pytest.approx(0.70)


def test_short_trip_rate_equals_raw_over_reference_efficiency():
    op = _operator()
    assert op.driver_rate_eur_h(6.0, 7.0) == pytest.approx(DRIVER_RAW / 0.60)
    assert op.crew_rate_eur_h(7.0) == pytest.approx(CREW_RAW / 0.70)


# ---------------------------------------------------------------------------
# duty boundaries — the step down
# ---------------------------------------------------------------------------


def test_exactly_max_duty_is_still_one_duty():
    """8.0 h driving is legal in one shift; float noise in the summed
    minute fields must not tip it into a second."""
    op = _operator()
    assert op.roster_efficiency("driver", 8.0, 9.0) == pytest.approx(0.60)
    assert op.roster_efficiency("crew", 10.0, 10.0) == pytest.approx(0.70)


def test_just_over_max_duty_steps_down():
    op = _operator()
    eff = op.roster_efficiency("driver", 8.01, 9.0)
    assert eff == pytest.approx(0.60 * 9.0 / (9.0 + 2.5))
    assert eff < 0.60


@pytest.mark.parametrize(
    "driving_h,expected_duties", [(8.0, 1), (8.5, 2), (16.0, 2), (16.5, 3), (24.0, 3)]
)
def test_driver_duty_count_progression(driving_h, expected_duties):
    op = _operator()
    on_train_h = driving_h + 1.0
    eff = op.roster_efficiency("driver", driving_h, on_train_h)
    expected = 0.60 * on_train_h / (on_train_h + 2.5 * (expected_duties - 1))
    assert eff == pytest.approx(expected)


def test_reference_night_route_matches_calibration():
    """The worked example pinned in CALIBRATION.md."""
    op = _operator()
    assert op.roster_efficiency("driver", 13.5, 14.5) == pytest.approx(0.5118, abs=1e-4)
    assert op.roster_efficiency("crew", 14.5, 14.5) == pytest.approx(0.5971, abs=1e-4)
    assert op.driver_rate_eur_h(13.5, 14.5) == pytest.approx(105.82, abs=0.01)
    assert op.crew_rate_eur_h(14.5) == pytest.approx(81.65, abs=0.01)


def test_roles_cross_their_boundaries_independently():
    """A 9.5 h-driving / 10.0 h trip is two driver duties but still one
    crew duty — the driver cap (8 h) is tighter than the crew cap (10 h)."""
    op = _operator()
    assert op.roster_efficiency("driver", 9.5, 10.0) < 0.60
    assert op.roster_efficiency("crew", 10.0, 10.0) == pytest.approx(0.70)


# ---------------------------------------------------------------------------
# shape of the curve
# ---------------------------------------------------------------------------


def test_efficiency_recovers_within_a_duty_band():
    """Inside one duty count the fixed relief allowance amortises, so a
    longer trip is *more* efficient — the sawtooth's rising edge."""
    op = _operator()
    short = op.roster_efficiency("driver", 9.0, 10.0)
    long = op.roster_efficiency("driver", 15.0, 16.0)
    assert long > short


def test_crossing_a_boundary_costs_more_than_the_extra_hour_returns():
    """The falling edge: one hour more driving that tips the trip into a
    third duty must lower efficiency despite the longer amortisation."""
    op = _operator()
    assert op.roster_efficiency("driver", 16.5, 17.5) < op.roster_efficiency(
        "driver", 16.0, 17.0
    )


def test_rate_is_never_below_the_raw_wage():
    op = _operator()
    for driving_h in (1.0, 8.0, 12.0, 20.0, 30.0):
        assert op.driver_rate_eur_h(driving_h, driving_h + 1.0) >= DRIVER_RAW


# ---------------------------------------------------------------------------
# degenerate inputs
# ---------------------------------------------------------------------------


def test_zero_on_train_hours_falls_back_to_reference():
    """A zero-length trip has no productive hours to divide; the rate must
    stay finite rather than blowing up the whole evaluation."""
    op = _operator()
    assert op.roster_efficiency("driver", 0.0, 0.0) == pytest.approx(0.60)
    assert op.driver_rate_eur_h(0.0, 0.0) == pytest.approx(DRIVER_RAW / 0.60)


def test_zero_relief_allowance_disables_the_penalty():
    """Relief allowance is a seeded parameter — zero means an operator
    whose relief crews cost no unproductive time."""
    op = _operator(relief_allowance_h=0.0)
    assert op.roster_efficiency("driver", 24.0, 25.0) == pytest.approx(0.60)
