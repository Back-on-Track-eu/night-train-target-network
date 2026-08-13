"""
test_73_calc_tac_units.py
=========================
Pure unit tests for the component track access charge model in
models/infrastructure/calc_tac.py — no Docker stack, no DB. Runnable
standalone:

    uv run --extra dev pytest tests/test_73_calc_tac_units.py -v

Rates here are round test numbers, not the calibrated ones: what is
pinned is the MECHANICS (which term applies to which share of a run),
since the calibrated values move whenever a network statement is
reissued. The five German night-band cases and the weekday blend are the
exception — those come verbatim from calc_tac.py's docstring and
TAC_CALIBRATION.md, and are the reason this file exists.

Every rate the model reads is EUR at the evaluation year; the notebook
converts currency and price basis once, before seeding, so nothing under
test does unit arithmetic.
"""

import pytest

from models.infrastructure.calc_tac import WEEKDAY_BLEND, calc_segment_tac
from models.params import (
    PassageCharge,
    PassageChargeCollection,
    ParamVersions,
    TrackInfraCollection,
    TrackInfrastructure,
)
from models.route.trip import Segment, Stop, StopType

# A flat display value high enough that reading it once would dwarf every
# component term — the guard behind "calc_tac.py never reads it".
ABSURD_FLAT_TAC = 999_999.0

H = 60  # minutes per hour, for readable clock literals


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _track(country_code: str, **overrides) -> TrackInfrastructure:
    kwargs = dict(
        country_code=country_code,
        field_is_default={},
        has_row=True,
        tac_eur_train_km=ABSURD_FLAT_TAC,
        parking_eur_day=0.0,
        shunting_eur_event=0.0,
        energy_price_eur_kwh=0.0,
        terrain_score=1.0,
        terrain_category="Flat",
        hsr_allowed=True,
        min_boarding_time_min=2,
        min_alighting_time_min=2,
        buffer_quota_per=0.0,
        tac_b_day=None,
        tac_b_night=None,
        tac_gamma=None,
        tac_seat_km=None,
        tac_per_stop=None,
        tac_revenue_share=None,
        tac_fixed_per_train_km=None,
        tac_peak_multiplier=None,
        tac_congestion_surcharge_eur_km=None,
        tac_night_mode="none",
        tac_night_band_start_min=None,
        tac_night_band_end_min=None,
        tac_night_full_if_accommodation=False,
        tac_peak_band1_start_min=None,
        tac_peak_band1_end_min=None,
        tac_peak_band2_start_min=None,
        tac_peak_band2_end_min=None,
        tac_peak_weekdays_only=False,
    )
    kwargs.update(overrides)
    return TrackInfrastructure(**kwargs)


def _tracks(*tracks: TrackInfrastructure) -> TrackInfraCollection:
    return TrackInfraCollection(
        {t.country_code: t for t in tracks},
        ParamVersions(),
        defaults=None,
        descriptions=None,
    )


def _passages(*charges: PassageCharge) -> PassageChargeCollection:
    return PassageChargeCollection({c.passage_id: c for c in charges}, ParamVersions())


class _Composition:
    """Minimal stand-in: calc_tac reads four attributes off a Composition
    and nothing else. Building a real one would need a coach catalog and
    would couple this file to the compositions domain for no gain."""

    def __init__(
        self,
        *,
        night_accommodation: bool = False,
        gross_weight_t: float = 500.0,
        places: int = 200,
    ) -> None:
        self.has_night_accommodation = night_accommodation
        self.total_gross_weight_t = gross_weight_t
        self.places_by_class = {"Seat": places}


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
    countries: list[str] | None = None,
    distance_shares: dict[str, float] | None = None,
    time_shares: dict[str, float] | None = None,
    from_country: str = "XA",
    to_country: str = "XA",
    passages: list[str] | None = None,
) -> Segment:
    shares = distance_shares or {from_country: 1.0}
    return Segment(
        from_stop=_stop("FROM", from_country, None, depart_min),
        to_stop=_stop("TO", to_country, arrive_min, None),
        geometry=[],
        distance_m=int(distance_km * 1000),
        driving_time_min=arrive_min - depart_min,
        dynamics_time_min=0,
        buffer_time_min=0,
        energy_kwh=0.0,
        country_distance_shares=shares,
        country_time_shares=time_shares or shares,
        countries=countries if countries is not None else list(shares),
        passages=passages or [],
    )


def _tac(segment, tracks, composition=None, **kwargs):
    return calc_segment_tac(
        segment,
        composition or _Composition(),
        tracks,
        kwargs.pop("passages", _passages()),
        is_first_segment=kwargs.pop("is_first_segment", False),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# the flat display column is never read
# ---------------------------------------------------------------------------


def test_flat_display_rate_is_never_read():
    """Every track fixture carries an absurd flat rate. A country levying
    nothing must therefore cost nothing — if the flat column were read
    anywhere, this is the test that would notice."""
    tracks = _tracks(_track("XA"))
    result = _tac(_segment(depart_min=0, arrive_min=120), tracks)
    assert result.total_eur == 0.0


# ---------------------------------------------------------------------------
# per-kilometre terms
# ---------------------------------------------------------------------------


def test_day_rate_charges_the_whole_run_without_a_night_tariff():
    tracks = _tracks(_track("XA", tac_b_day=2.0))
    result = _tac(_segment(depart_min=0, arrive_min=120, distance_km=100.0), tracks)
    assert result.total_eur == pytest.approx(200.0)


def test_gamma_only_country_prices_on_weight_alone():
    """Finland levies a gross-tonne-km rate and no train-km rate. An absent
    b_day must fall out as zero rather than as missing data."""
    tracks = _tracks(_track("FI", tac_gamma=0.002))
    composition = _Composition(gross_weight_t=500.0)
    result = _tac(
        _segment(depart_min=0, arrive_min=120, distance_km=100.0, from_country="FI"),
        tracks,
        composition,
    )
    # 0.002 x 500 t x 100 km
    assert result.total_eur == pytest.approx(100.0)
    assert result.country_tacs[0].base_eur == 0.0


def test_seat_and_fixed_terms_scale_with_places_and_distance():
    tracks = _tracks(_track("XA", tac_seat_km=0.01, tac_fixed_per_train_km=0.5))
    composition = _Composition(places=200)
    result = _tac(
        _segment(depart_min=0, arrive_min=120, distance_km=100.0),
        tracks,
        composition,
    )
    entry = result.country_tacs[0]
    assert entry.seat_eur == pytest.approx(0.01 * 200 * 100)
    assert entry.fixed_eur == pytest.approx(0.5 * 100)


def test_revenue_share_takes_a_cut_of_the_segments_traffic():
    """The Swiss Deckungsbeitrag prices traffic, not distance — which is
    why the passenger pre-pass has to run before segment costs."""
    tracks = _tracks(_track("CH", tac_revenue_share=0.05))
    result = _tac(
        _segment(depart_min=0, arrive_min=120, from_country="CH"),
        tracks,
        segment_revenue_eur=4000.0,
    )
    assert result.total_eur == pytest.approx(200.0)


# ---------------------------------------------------------------------------
# night bands — the German worked examples
# ---------------------------------------------------------------------------


def _de_tracks():
    """Germany: night rate only, 23:00-06:00, whole-run widening."""
    return _tracks(
        _track(
            "DE",
            tac_b_day=1.0,
            tac_b_night=3.0,
            tac_night_mode="time_band",
            tac_night_band_start_min=23 * H,
            tac_night_band_end_min=6 * H,
            tac_night_full_if_accommodation=True,
        )
    )


@pytest.mark.parametrize(
    "depart,arrive,accommodation,expected_night_share",
    [
        # calc_tac.py docstring, verbatim
        (23 * H + 30, 24 * H + 5 * H, False, 1.0),  # 23:30-05:00, inside
        (23 * H + 30, 24 * H + 5 * H, True, 1.0),
        (24 * H, 24 * H + 8 * H, False, 0.75),  # 00:00-08:00, 6 of 8 h
        (24 * H, 24 * H + 8 * H, True, 1.0),  # widened
        (20 * H, 24 * H + 8 * H, False, 7.0 / 12.0),  # 20:00-08:00, 7 of 12 h
        (20 * H, 24 * H + 8 * H, True, 1.0),  # widened
    ],
)
def test_german_night_band_worked_examples(
    depart, arrive, accommodation, expected_night_share
):
    tracks = _de_tracks()
    composition = _Composition(night_accommodation=accommodation)
    segment = _segment(
        depart_min=depart, arrive_min=arrive, distance_km=100.0, from_country="DE"
    )
    entry = _tac(segment, tracks, composition).country_tacs[0]
    assert entry.night_km == pytest.approx(100.0 * expected_night_share)
    day_km = 100.0 - entry.night_km
    assert entry.base_eur == pytest.approx(day_km * 1.0 + entry.night_km * 3.0)


def test_daytime_run_in_a_banded_country_pays_no_night_rate():
    segment = _segment(
        depart_min=8 * H, arrive_min=14 * H, distance_km=100.0, from_country="DE"
    )
    entry = _tac(segment, _de_tracks()).country_tacs[0]
    assert entry.night_km == 0.0
    assert entry.base_eur == pytest.approx(100.0)


def test_widening_needs_the_country_to_declare_it():
    """A banded country without the German rule splits pro rata even for a
    sleeper train — the widening is a national tariff rule, not a property
    of night trains generally."""
    tracks = _tracks(
        _track(
            "IT",
            tac_b_day=1.0,
            tac_b_night=3.0,
            tac_night_mode="time_band",
            tac_night_band_start_min=22 * H,
            tac_night_band_end_min=6 * H,
        )
    )
    segment = _segment(
        depart_min=24 * H,
        arrive_min=24 * H + 8 * H,
        distance_km=100.0,
        from_country="IT",
    )
    entry = _tac(segment, tracks, _Composition(night_accommodation=True)).country_tacs[
        0
    ]
    assert entry.night_km == pytest.approx(75.0)


def test_night_rate_falls_back_to_the_day_rate_when_not_separately_set():
    tracks = _tracks(
        _track(
            "XA",
            tac_b_day=2.0,
            tac_night_mode="time_band",
            tac_night_band_start_min=23 * H,
            tac_night_band_end_min=6 * H,
        )
    )
    segment = _segment(depart_min=24 * H, arrive_min=24 * H + 2 * H, distance_km=100.0)
    assert _tac(segment, tracks).total_eur == pytest.approx(200.0)


# ---------------------------------------------------------------------------
# peak and congestion
# ---------------------------------------------------------------------------


def _peak_bands(**overrides):
    kwargs = dict(
        tac_peak_band1_start_min=6 * H,
        tac_peak_band1_end_min=9 * H,
        tac_peak_band2_start_min=16 * H,
        tac_peak_band2_end_min=19 * H,
        tac_peak_weekdays_only=True,
    )
    kwargs.update(overrides)
    return kwargs


def test_congestion_surcharge_is_blended_over_the_week():
    """Austria: a run entirely inside the morning peak still pays only
    5/7 of the surcharge, because the model knows the clock time but not
    the weekday."""
    tracks = _tracks(_track("AT", tac_congestion_surcharge_eur_km=2.0, **_peak_bands()))
    segment = _segment(
        depart_min=7 * H, arrive_min=8 * H, distance_km=100.0, from_country="AT"
    )
    entry = _tac(segment, tracks).country_tacs[0]
    assert entry.congestion_eur == pytest.approx(2.0 * 100.0 * WEEKDAY_BLEND)


def test_peak_multiplier_scales_only_the_overlapping_share():
    """Switzerland doubles the day rate. Half this run is in the peak, so
    the surcharge is half the base — before the weekday blend."""
    tracks = _tracks(
        _track("CH", tac_b_day=2.0, tac_peak_multiplier=2.0, **_peak_bands())
    )
    segment = _segment(
        depart_min=8 * H, arrive_min=10 * H, distance_km=100.0, from_country="CH"
    )
    entry = _tac(segment, tracks).country_tacs[0]
    base = 2.0 * 100.0
    assert entry.base_eur == pytest.approx(base + base * 0.5 * WEEKDAY_BLEND)


def test_a_run_outside_every_peak_band_pays_no_surcharge():
    tracks = _tracks(
        _track(
            "AT", tac_b_day=2.0, tac_congestion_surcharge_eur_km=2.0, **_peak_bands()
        )
    )
    segment = _segment(
        depart_min=23 * H,
        arrive_min=24 * H + 4 * H,
        distance_km=100.0,
        from_country="AT",
    )
    entry = _tac(segment, tracks).country_tacs[0]
    assert entry.congestion_eur == 0.0


def test_all_day_peak_bands_are_not_blended():
    tracks = _tracks(
        _track(
            "XA",
            tac_congestion_surcharge_eur_km=2.0,
            **_peak_bands(tac_peak_weekdays_only=False),
        )
    )
    segment = _segment(depart_min=7 * H, arrive_min=8 * H, distance_km=100.0)
    entry = _tac(segment, tracks).country_tacs[0]
    assert entry.congestion_eur == pytest.approx(200.0)


# ---------------------------------------------------------------------------
# per-stop terms
# ---------------------------------------------------------------------------


def test_first_segment_charges_both_of_its_ends():
    """A trip's origin is nobody's to_stop, so without this the very first
    station of every trip would be free."""
    tracks = _tracks(_track("CH", tac_per_stop=5.0))
    segment = _segment(depart_min=0, arrive_min=120, from_country="CH", to_country="CH")
    assert _tac(segment, tracks, is_first_segment=True).total_eur == pytest.approx(10.0)
    assert _tac(segment, tracks, is_first_segment=False).total_eur == pytest.approx(5.0)


def test_each_stop_is_charged_at_its_own_countrys_rate():
    tracks = _tracks(_track("CH", tac_per_stop=5.0), _track("DE", tac_per_stop=1.0))
    segment = _segment(
        depart_min=0,
        arrive_min=120,
        from_country="CH",
        to_country="DE",
        distance_shares={"CH": 0.5, "DE": 0.5},
    )
    by_country = _tac(segment, tracks, is_first_segment=True).by_country
    assert by_country["CH"] == pytest.approx(5.0)
    assert by_country["DE"] == pytest.approx(1.0)


def test_a_stop_outside_the_run_still_gets_its_charge():
    """A border station reached over the neighbour's track: the stop's
    country never appears in the run windows, and must not be dropped."""
    tracks = _tracks(_track("XA"), _track("XB", tac_per_stop=7.0))
    segment = _segment(depart_min=0, arrive_min=120, from_country="XA", to_country="XB")
    result = _tac(segment, tracks)
    assert result.by_country["XB"] == pytest.approx(7.0)
    assert next(c for c in result.country_tacs if c.country_code == "XB").km == 0.0


# ---------------------------------------------------------------------------
# passages
# ---------------------------------------------------------------------------


def test_passage_charges_fixed_and_per_passenger_components():
    passages = _passages(
        PassageCharge("CHANNEL_TUNNEL", "Channel Tunnel", 5000.0, 20.0)
    )
    segment = _segment(depart_min=0, arrive_min=120, passages=["CHANNEL_TUNNEL"])
    result = _tac(
        segment, _tracks(_track("XA")), passages=passages, segment_passengers=100.0
    )
    assert result.passage_eur == pytest.approx(5000.0 + 20.0 * 100.0)


def test_passage_charges_stay_out_of_the_per_country_split():
    """A crossing is billed by its operator, not by the country whose
    waters it sits in — views.py spreads it separately, so by_country must
    not double it in."""
    passages = _passages(PassageCharge("STOREBAELT", "Storebælt", 800.0, 0.0))
    segment = _segment(
        depart_min=0, arrive_min=120, from_country="DK", passages=["STOREBAELT"]
    )
    result = _tac(segment, _tracks(_track("DK", tac_b_day=1.0)), passages=passages)
    assert result.by_country["DK"] == pytest.approx(100.0)
    assert result.total_eur == pytest.approx(900.0)


def test_an_unpinned_passage_is_skipped_rather_than_fatal():
    """A geometry match against a charge row dropped in a later version is
    a data inconsistency worth logging, not worth failing an evaluation
    over."""
    segment = _segment(depart_min=0, arrive_min=120, passages=["FEHMARNBELT"])
    result = _tac(segment, _tracks(_track("XA")), passages=_passages())
    assert result.passage_tacs == []


# ---------------------------------------------------------------------------
# multi-country runs and ordering
# ---------------------------------------------------------------------------


def test_countries_are_placed_on_the_clock_in_path_order():
    """The whole reason Segment carries an ordered country list: reversing
    the order moves which country's kilometres fall inside the night band.
    A 20:00-04:00 run half in each country puts the FIRST country's share
    largely in the evening and the SECOND's inside the band."""
    tracks = _tracks(
        _track(
            "XA",
            tac_b_day=1.0,
            tac_b_night=3.0,
            tac_night_mode="time_band",
            tac_night_band_start_min=23 * H,
            tac_night_band_end_min=6 * H,
        ),
        _track(
            "XB",
            tac_b_day=1.0,
            tac_b_night=3.0,
            tac_night_mode="time_band",
            tac_night_band_start_min=23 * H,
            tac_night_band_end_min=6 * H,
        ),
    )
    shares = {"XA": 0.5, "XB": 0.5}
    forward = _segment(
        depart_min=20 * H,
        arrive_min=24 * H + 4 * H,
        distance_km=100.0,
        distance_shares=shares,
        countries=["XA", "XB"],
    )
    reverse = _segment(
        depart_min=20 * H,
        arrive_min=24 * H + 4 * H,
        distance_km=100.0,
        distance_shares=shares,
        countries=["XB", "XA"],
    )
    forward_xa = _tac(forward, tracks).by_country["XA"]
    reverse_xa = _tac(reverse, tracks).by_country["XA"]
    # XA runs 20:00-00:00 forward (1 of 4 h banded) and 00:00-04:00
    # reversed (fully banded), so it must cost strictly more reversed.
    assert reverse_xa > forward_xa


def test_unknown_country_slices_are_not_charged_but_still_advance_the_clock():
    """UNK is open water — no infrastructure manager to pay — but its time
    share must still push the following country's window forward, or every
    country after a ferry would be priced at the wrong clock time."""
    tracks = _tracks(_track("XA", tac_b_day=1.0))
    segment = _segment(
        depart_min=0,
        arrive_min=240,
        distance_km=100.0,
        distance_shares={"UNK": 0.5, "XA": 0.5},
        countries=["UNK", "XA"],
    )
    result = _tac(segment, tracks)
    assert [c.country_code for c in result.country_tacs] == ["XA"]
    assert result.total_eur == pytest.approx(50.0)


def test_missing_country_order_falls_back_to_the_share_keys():
    """Route payloads stored before ROUTE_BUILDER 0.9.21 carry no ordered
    country list — they must stay evaluable."""
    tracks = _tracks(_track("XA", tac_b_day=1.0))
    segment = _segment(depart_min=0, arrive_min=120, distance_km=100.0)
    segment.countries = []
    assert _tac(segment, tracks).total_eur == pytest.approx(100.0)
