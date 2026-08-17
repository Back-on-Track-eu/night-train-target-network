"""
test_75_calc_energy_price_units.py
==================================
Pure unit tests for the traction energy price model in
models/infrastructure/energy_pricing/calc_energy_price.py — no Docker
stack, no DB. Runnable standalone:

    uv run --extra dev pytest tests/test_75_calc_energy_price_units.py -v

Rates here are round test numbers, not the calibrated ones: what is pinned
is the MECHANICS — which price applies to which share of a country run,
which unit a supply-equipment charge is levied in, and what a NULL means.
Calibrated values move whenever a network statement or a Eurostat release
is reissued; the mechanics do not.

Two mechanics matter most and are the reason this file exists. A NULL
night price or catenary term is a tariff fact ("not levied"), never a gap
to fill — so it must price at the day rate, or at zero, rather than
resolving to anything. And the electricity night band is independent of
the track access night band: a country can have one and not the other, in
either direction.

Every rate the model reads is EUR at the evaluation year; the calibration
notebook converts currency and price basis once, before seeding, so
nothing under test does unit arithmetic.
"""

import pytest

from models.infrastructure.energy_pricing.calc_energy_price import calc_segment_energy
from models.params import (
    ParamVersions,
    TrackInfraCollection,
    TrackInfrastructure,
)
from models.route.trip import Segment, Stop, StopType

H = 60  # minutes per hour, for readable clock literals

# A track access rate high enough that reading any of it would dwarf every
# energy term — the guard behind "this module prices energy only".
ABSURD_TAC = 999_999.0


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _track(country_code: str, **overrides) -> TrackInfrastructure:
    kwargs = {
        "country_code": country_code,
        "field_is_default": {},
        "has_row": True,
        # Every track access term is set absurdly high, the mirror of what
        # test_73 does with the flat energy price: track access and energy
        # are separate domains, and a term crossing the boundary should
        # blow a test rather than shift a number plausibly.
        "tac_eur_train_km": ABSURD_TAC,
        "parking_eur_day": ABSURD_TAC,
        "shunting_eur_event": ABSURD_TAC,
        "energy_price_eur_kwh": 0.20,
        "terrain_score": 1.0,
        "terrain_category": "Flat",
        "hsr_allowed": True,
        "min_boarding_time_min": 2,
        "min_alighting_time_min": 2,
        "buffer_quota_per": 0.0,
        "tac_b_day": ABSURD_TAC,
        "tac_b_night": ABSURD_TAC,
        "tac_gamma": ABSURD_TAC,
        "tac_seat_km": ABSURD_TAC,
        "tac_per_stop": ABSURD_TAC,
        "tac_revenue_share": 1.0,
        "tac_fixed_per_train_km": ABSURD_TAC,
        "tac_peak_multiplier": None,
        "tac_congestion_surcharge_eur_km": ABSURD_TAC,
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
        "energy_catenary_eur_train_km": None,
        "energy_catenary_eur_gross_tonne_km": None,
        # Service facility terms — this suite prices energy only; a 'none'
        # basis with no rates makes a facility charge impossible.
        "parking_basis": "none",
        "parking_eur_metre_day": None,
        "parking_eur_hour": None,
        "parking_eur_event": None,
        "parking_free_hours": None,
        "parking_hotel_power_eur_hour": None,
    }
    kwargs.update(overrides)
    return TrackInfrastructure(**kwargs)


def _tracks(*tracks: TrackInfrastructure) -> TrackInfraCollection:
    return TrackInfraCollection(
        {t.country_code: t for t in tracks},
        ParamVersions(),
        defaults=None,
        descriptions=None,
    )


class _Composition:
    """Minimal stand-in: calc_energy_price reads one attribute off a
    Composition — the gross weight the per-tonne catenary charge is levied
    on. Building a real one would need a coach catalog and would couple this
    file to the compositions domain for no gain."""

    def __init__(self, *, gross_weight_t: float = 600.0) -> None:
        self.total_gross_weight_t = gross_weight_t


def _stop(stop_id: str, country_code: str, arrival: int | None, departure: int | None):
    return Stop(
        stop_id=stop_id,
        stop_name=stop_id,
        country_code=country_code,
        lat=0.0,
        lon=0.0,
        stop_type=StopType.BOTH,
        arrival_time_min=arrival,
        departure_time_min=departure,
    )


def _segment(
    *,
    depart_min: int,
    arrive_min: int,
    distance_km: float = 100.0,
    energy_kwh: float = 2_800.0,
    countries: list[str] | None = None,
    distance_shares: dict[str, float] | None = None,
    time_shares: dict[str, float] | None = None,
) -> Segment:
    shares = distance_shares or {"XA": 1.0}
    return Segment(
        from_stop=_stop("FROM", "XA", None, depart_min),
        to_stop=_stop("TO", "XA", arrive_min, None),
        geometry=[],
        distance_m=int(distance_km * 1000),
        driving_time_min=arrive_min - depart_min,
        dynamics_time_min=0,
        buffer_time_min=0,
        energy_kwh=energy_kwh,
        country_distance_shares=shares,
        country_time_shares=time_shares or shares,
        countries=countries if countries is not None else list(shares),
    )


def _energy(segment, tracks, composition=None):
    return calc_segment_energy(segment, composition or _Composition(), tracks)


# ---------------------------------------------------------------------------
# the day rate, and what a missing night price means
# ---------------------------------------------------------------------------


def test_unbanded_country_prices_the_whole_run_at_the_day_rate():
    """Twenty-five of twenty-eight calibrated countries charge one rate
    around the clock. A NULL night price is that fact, and must not resolve
    to anything."""
    tracks = _tracks(_track("XA", energy_price_eur_kwh=0.25))
    result = _energy(_segment(depart_min=0, arrive_min=120), tracks)
    assert result.total_eur == pytest.approx(700.0)  # 2800 kWh x 0.25
    assert result.catenary_eur == 0.0
    assert result.country_energies[0].night_kwh == 0.0


def test_track_access_terms_are_never_read():
    """Every track access rate on the fixture is absurd. An energy bill that
    only reflects the energy price is the guard that the two domains stay
    apart — the mirror of test_73's flat-display-rate test."""
    tracks = _tracks(_track("XA", energy_price_eur_kwh=0.10))
    result = _energy(_segment(depart_min=0, arrive_min=120), tracks)
    assert result.total_eur == pytest.approx(280.0)


def test_a_night_band_without_a_night_price_changes_nothing():
    """A band with no rate behind it is incoherent data, not an invitation
    to invent a discount: the day rate still prices the whole run."""
    tracks = _tracks(
        _track(
            "XA",
            energy_price_eur_kwh=0.20,
            energy_night_band_start_min=22 * H,
            energy_night_band_end_min=6 * H,
        )
    )
    result = _energy(_segment(depart_min=23 * H, arrive_min=25 * H), tracks)
    assert result.total_eur == pytest.approx(560.0)
    assert result.country_energies[0].night_kwh == 0.0


# ---------------------------------------------------------------------------
# the night band — AT, CH and HR are the only banded tariffs
# ---------------------------------------------------------------------------


def _banded(**overrides) -> TrackInfrastructure:
    return _track(
        "XA",
        energy_price_eur_kwh=0.20,
        energy_price_night_eur_kwh=0.10,
        energy_night_band_start_min=22 * H,
        energy_night_band_end_min=6 * H,
        **overrides,
    )


def test_run_entirely_inside_the_band_is_all_night():
    tracks = _tracks(_banded())
    result = _energy(_segment(depart_min=23 * H, arrive_min=29 * H), tracks)
    assert result.country_energies[0].night_kwh == pytest.approx(2_800.0)
    assert result.total_eur == pytest.approx(280.0)  # 2800 x 0.10


def test_run_entirely_outside_the_band_is_all_day():
    tracks = _tracks(_banded())
    result = _energy(_segment(depart_min=8 * H, arrive_min=12 * H), tracks)
    assert result.country_energies[0].night_kwh == 0.0
    assert result.total_eur == pytest.approx(560.0)  # 2800 x 0.20


def test_evening_departure_splits_pro_rata_across_the_boundary():
    """21:00-01:00: three of four hours inside a 22:00-06:00 band, so three
    quarters of the energy bills at the night rate. Pro rata rather than a
    midpoint pick — this is the case a blended single rate would get wrong,
    and the reason the night price is its own column."""
    tracks = _tracks(_banded())
    result = _energy(_segment(depart_min=21 * H, arrive_min=25 * H), tracks)
    entry = result.country_energies[0]
    assert entry.night_kwh == pytest.approx(2_100.0)
    assert result.total_eur == pytest.approx(700 * 0.20 + 2_100 * 0.10)


def test_morning_arrival_splits_pro_rata_across_the_boundary():
    """04:00-08:00: two of four hours inside the band — the mirror case, and
    the one that makes a night-only working price overstate the discount."""
    tracks = _tracks(_banded())
    result = _energy(_segment(depart_min=4 * H, arrive_min=8 * H), tracks)
    assert result.country_energies[0].night_kwh == pytest.approx(1_400.0)
    assert result.total_eur == pytest.approx(1_400 * 0.20 + 1_400 * 0.10)


def test_band_wrapping_midnight_is_measured_across_the_wrap():
    """A run from 22:00 to 06:00 spans the whole band even though the band's
    start minute is numerically greater than its end — band_overlap_min is
    what makes wrap-safe arithmetic possible, and this pins that it is used
    here too."""
    tracks = _tracks(_banded())
    result = _energy(_segment(depart_min=22 * H, arrive_min=30 * H), tracks)
    assert result.country_energies[0].night_kwh == pytest.approx(2_800.0)


def test_zero_length_run_does_not_divide_by_zero():
    tracks = _tracks(_banded())
    result = _energy(_segment(depart_min=12 * H, arrive_min=12 * H), tracks)
    assert result.country_energies[0].night_kwh == 0.0


def test_energy_band_is_independent_of_the_track_access_band():
    """Germany bands track access 23:00-06:00 and does not band electricity;
    Switzerland bands electricity 22:00-06:00 and has no track access night
    rate. A run inside the TAC band only must therefore bill entirely at the
    energy day rate."""
    tracks = _tracks(
        _track(
            "XA",
            energy_price_eur_kwh=0.20,
            tac_night_mode="time_band",
            tac_night_band_start_min=23 * H,
            tac_night_band_end_min=6 * H,
        )
    )
    result = _energy(_segment(depart_min=23 * H, arrive_min=29 * H), tracks)
    assert result.country_energies[0].night_kwh == 0.0
    assert result.total_eur == pytest.approx(560.0)


# ---------------------------------------------------------------------------
# supply equipment — two units, one of them weight-dependent
# ---------------------------------------------------------------------------


def test_catenary_charge_per_train_km():
    """Nine countries levy it per kilometre (FR is the largest at 0.32
    EUR/train-km at 2032 prices)."""
    tracks = _tracks(_track("XA", energy_catenary_eur_train_km=0.30))
    result = _energy(_segment(depart_min=0, arrive_min=120, distance_km=200.0), tracks)
    assert result.catenary_eur == pytest.approx(60.0)
    assert result.price_eur == pytest.approx(560.0)
    assert result.total_eur == pytest.approx(620.0)


def test_catenary_charge_per_gross_tonne_km_scales_with_the_consist():
    """Three countries levy it on weight moved. A heavier train pays more —
    the reason the charge is kept in its published unit instead of being
    folded into a per-kWh price."""
    tracks = _tracks(_track("XA", energy_catenary_eur_gross_tonne_km=0.001))
    light = _energy(
        _segment(depart_min=0, arrive_min=120, distance_km=100.0),
        tracks,
        _Composition(gross_weight_t=400.0),
    )
    heavy = _energy(
        _segment(depart_min=0, arrive_min=120, distance_km=100.0),
        tracks,
        _Composition(gross_weight_t=800.0),
    )
    assert light.catenary_eur == pytest.approx(40.0)  # 0.001 x 400 x 100
    assert heavy.catenary_eur == pytest.approx(80.0)
    assert light.price_eur == heavy.price_eur


def test_a_null_catenary_term_is_priced_at_zero_not_defaulted():
    """Roughly half of Europe's infrastructure managers levy no
    supply-equipment charge at all, or levy it in the other unit. Either way
    the empty column must cost nothing — it is never resolved against the
    fallback row, unlike the day price."""
    tracks = _tracks(_track("XA"))
    result = _energy(_segment(depart_min=0, arrive_min=120), tracks)
    assert result.catenary_eur == 0.0


def test_catenary_charge_is_independent_of_the_night_band():
    """A supply-equipment charge is for access to the installation, not for
    the energy drawn through it, so the clock does not touch it."""
    tracks = _tracks(_banded(energy_catenary_eur_train_km=0.30))
    day = _energy(_segment(depart_min=8 * H, arrive_min=12 * H), tracks)
    night = _energy(_segment(depart_min=23 * H, arrive_min=27 * H), tracks)
    assert day.catenary_eur == night.catenary_eur == pytest.approx(30.0)
    assert night.price_eur < day.price_eur


# ---------------------------------------------------------------------------
# multi-country segments
# ---------------------------------------------------------------------------


def test_each_country_prices_its_own_share_at_its_own_rate():
    """The whole point of the per-country breakdown: a segment crossing a
    cheap and an expensive market must not be averaged."""
    tracks = _tracks(
        _track("XA", energy_price_eur_kwh=0.06),
        _track("XB", energy_price_eur_kwh=0.30, energy_catenary_eur_train_km=0.20),
    )
    segment = _segment(
        depart_min=0,
        arrive_min=120,
        distance_km=200.0,
        distance_shares={"XA": 0.5, "XB": 0.5},
    )
    result = _energy(segment, tracks)
    assert result.by_country["XA"] == pytest.approx(1_400 * 0.06)
    assert result.by_country["XB"] == pytest.approx(1_400 * 0.30 + 0.20 * 100)
    assert result.total_eur == pytest.approx(
        result.by_country["XA"] + result.by_country["XB"]
    )


def test_by_country_sums_to_the_total():
    """Nothing in this domain is billed by anyone but the country the leg ran
    in — unlike track access, where a crossing operator's charge has no
    levying country. So the per-country view is exhaustive, and views.py
    relies on that."""
    tracks = _tracks(
        _track("XA", energy_catenary_eur_train_km=0.10),
        _track("XB", energy_catenary_eur_gross_tonne_km=0.0005),
    )
    segment = _segment(
        depart_min=0,
        arrive_min=180,
        distance_shares={"XA": 0.3, "XB": 0.7},
    )
    result = _energy(segment, tracks)
    assert sum(result.by_country.values()) == pytest.approx(result.total_eur)


def test_unknown_slice_is_skipped_but_still_advances_the_clock():
    """Open water and ferry legs have no supplier to pay. They must not be
    charged, and must not shift the following country's window — a UNK slice
    that stole the band boundary would mis-split the next country's night
    share."""
    tracks = _tracks(_banded())
    shares = {"UNK": 0.5, "XA": 0.5}
    result = _energy(
        _segment(
            depart_min=20 * H,
            arrive_min=24 * H,
            distance_shares=shares,
            countries=["UNK", "XA"],
        ),
        tracks,
    )
    assert [c.country_code for c in result.country_energies] == ["XA"]
    # UNK holds 20:00-22:00, so XA runs 22:00-24:00 — entirely in the band.
    assert result.country_energies[0].night_kwh == pytest.approx(1_400.0)


def test_country_with_no_track_row_is_skipped_rather_than_crashing():
    """build_all_tracks() synthesizes a row for every known country, so this
    is the ferry/UNK path rather than a real gap — but the model must degrade
    quietly either way."""
    tracks = _tracks(_track("XA"))
    result = _energy(
        _segment(depart_min=0, arrive_min=120, distance_shares={"XZ": 1.0}), tracks
    )
    assert result.total_eur == 0.0
    assert result.country_energies == []


# ---------------------------------------------------------------------------
# stale payloads
# ---------------------------------------------------------------------------


def test_payload_without_ordered_countries_still_prices():
    """A route stored before ROUTE_BUILDER 0.9.21 carries no ordered country
    list. Segment.country_windows() falls back to the share dict's keys: the
    clock placement is then approximate, but the run stays evaluable rather
    than failing."""
    tracks = _tracks(_banded())
    segment = _segment(depart_min=23 * H, arrive_min=27 * H, countries=[])
    result = _energy(segment, tracks)
    assert result.total_eur == pytest.approx(280.0)
