"""
calc_tac.py
===========
Track access charge (TAC) for one segment — minimum access package only.

Scope: the charge for using the track itself, per routed leg. Explicitly
excluded (own modules / deferred): station stop charges (not even a column
read — the CH Haltezuschlag is NOT a station charge, see below), traction
energy, shunting and parking.

Component model (per country, each optional — None means "not levied",
never missing data; unknown countries were already resolved from the
EU-median default by DBDataLoader before reaching this module):
  b_day / b_night        €/train-km, day/night rate
  gamma                  €/gross-tonne-km (coaches + locomotives)
  seat_km                €/seat-km (ES corridor surcharge)
  fixed_per_train_km     €/train-km flat add-on (LU path administration)
  per_stop               €/stop — CH Haltezuschlag: a CAPACITY element of
                         the path price (accel/stop/decelerate consumes
                         path capacity), not a station-usage fee
  revenue_share          fraction of attributable traffic revenue (CH
                         Deckungsbeitrag — currently NULL everywhere, the
                         authority-set percentage is not published)
  peak_multiplier /      two IMs price the same phenomenon (approach legs
  congestion_surcharge   landing in a congested node during commuter peak)
                         two ways: CH MULTIPLIES the day rate (×2), AT
                         ADDS a flat €/train-km — kept separate so views
                         can show a congestion charge as such
All values EUR — conversion happened once, in calibration
(models/infrastructure/calib/06_seed_export.ipynb).

Night-rate mechanisms (tac_night_mode)
--------------------------------------
'none'       everything at b_day (gamma-only countries price fine — their
             b_day is None → 0).
'time_band'  pro-rata split of each country run's clock time against the
             country's night band → night_km/day_km blend, NOT a midpoint
             pick (Belgium's peak rate is several times its off-peak; a
             midpoint rule would badly mismodel a run straddling the
             boundary). Germany additionally sets
             tac_night_full_if_accommodation: the DB InfraGO SPFV rule
             widens the night rate to the ENTIRE German run when the
             composition carries night accommodation (couchette/sleeper/
             capsule) — a pure composition property, no timetable needed.
             Worked examples (all in the German 23:00–06:00 band, verified
             in tests/test_72_calc_tac_units.py):
               23:30–05:00, any composition → 100% night (inside band)
               00:00–08:00, no accommodation → 75% night (6/8 h in band)
               00:00–08:00, WITH accommodation → 100% night (widened)
               20:00–08:00, no accommodation → 58.33% night (7/12 h)
               20:00–08:00, WITH accommodation → 100% night (widened)
Switzerland has NO night/day TAC split at all (its 22:00–06:00 band
belongs to electricity pricing, not TAC) — CH is 'none' plus the peak
multiplier and the Haltezuschlag.

Peak/congestion surcharges (AT + CH)
------------------------------------
Both share the peak band columns (Mon–Fri 06:00–09:00 and 16:00–19:00 on
declared high-load/overloaded sections). _peak_fraction() computes the
exact time-window overlap, then scales by 5/7 for the weekday blend —
Segment carries clock minutes only, not a service date, so "Mon–Fri" is
priced as an expected value. Deliberately ACTIVE conservative defaults
(decided 2026-07): a night train's approach into Zürich HB or Wien Hbf
during the morning peak plausibly touches a congested section whether or
not that can be confirmed per section — silently treating every
unconfirmed approach as free would systematically understate cost in
exactly the pattern night trains run.

Stop attribution
----------------
A segment owns its to_stop; the trip's origin is nobody's to_stop, so the
FIRST segment of a trip charges BOTH ends (is_first_segment). Each stop is
charged at its own country's per_stop rate.

Passages (Storebælt, Øresund, Channel Tunnel)
---------------------------------------------
Resolved at ROUTING time (polygon intersection, rail_router.PassageIndex)
— this module just reads segment.passages and looks each id up in the
PassageChargeCollection. A passage is attributed to exactly one segment
per trip, so a crossing split by an intermediate stop doesn't pay twice.
The Channel Tunnel has a per-passenger component — hence
segment_passengers (passengers aboard per train run, from the
passenger-load pre-pass in models/evaluation/calc.py).

The flat TrackInfrastructure.tac_eur_train_km display value is NEVER read
here — asserted in the test suite.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from models.params import (
    Composition,
    PassageChargeCollection,
    TrackInfraCollection,
    TrackInfrastructure,
)
from models.route.trip import Segment
from models.utils import band_overlap_min

logger = logging.getLogger(__name__)

WEEKDAY_BLEND = 5.0 / 7.0
"""Expected-value share of weekday departures — the model has clock
minutes, not service dates, so weekday-only tariff windows are priced as
5/7 of their full overlap."""


# =============================================================================
# RESULT OBJECTS
# =============================================================================


@dataclass
class CountryTac:
    """TAC breakdown for one country run within a segment. All fields €/trip
    (one train run over this segment)."""

    country_code: str
    km: float  # this country's share of the segment length
    night_km: float  # km priced at the night rate (0 for mode 'none')
    base_eur: float  # train-km terms: day_km × b_day + night_km × b_night
    tonnage_eur: float  # gamma × gross tonnes × km
    seat_eur: float  # seat_km × places × km
    fixed_eur: float  # fixed_per_train_km × km
    stop_eur: float  # per_stop × stops charged in this country
    revenue_share_eur: float  # revenue_share × segment revenue × dist share
    congestion_eur: float  # AT-style flat surcharge (peak-scaled) — the CH
    # multiplier is folded into base_eur instead (it scales the day rate)

    @property
    def total_eur(self) -> float:
        return (
            self.base_eur
            + self.tonnage_eur
            + self.seat_eur
            + self.fixed_eur
            + self.stop_eur
            + self.revenue_share_eur
            + self.congestion_eur
        )


@dataclass
class PassageTac:
    """Charge for one passage traverse attributed to this segment. €/trip."""

    passage_id: str
    fixed_eur: float
    per_passenger_eur: float  # rate × segment_passengers, already multiplied

    @property
    def total_eur(self) -> float:
        return self.fixed_eur + self.per_passenger_eur


@dataclass
class SegmentTac:
    """Full TAC result for one segment of one trip. €/trip."""

    country_tacs: list[CountryTac] = field(default_factory=list)
    passage_tacs: list[PassageTac] = field(default_factory=list)

    @property
    def total_eur(self) -> float:
        return sum(c.total_eur for c in self.country_tacs) + sum(
            p.total_eur for p in self.passage_tacs
        )


# =============================================================================
# TIME-BAND WALK
# =============================================================================


def _country_windows(
    segment: Segment,
) -> list[tuple[str, float, float, float]]:
    """
    Place each country run of the segment on the clock:
    (country_code, enter_min, exit_min, dist_share), in path order.

    Walks Segment.countries (ordered by routing); each country's time
    share positions it between from_stop departure and to_stop arrival,
    its distance share gives it a length. UNK slices (ferries, unplaced
    geometry) still advance the time cursor — so they don't shift later
    countries' windows — but are yielded too; the caller skips their
    tariff (there is no IM to pay).
    """
    t0 = segment.from_stop.departure_time_min
    t1 = segment.to_stop.arrival_time_min
    duration = float((t1 or 0) - (t0 or 0)) if t0 is not None else 0.0

    # Ordered path list; pre-0.9.13 payloads lack it — fall back to the
    # share dict's keys (loses ordering precision, keeps them evaluable).
    countries = segment.countries or list(segment.country_distance_shares.keys())

    windows: list[tuple[str, float, float, float]] = []
    cursor = float(t0 or 0)
    for cc in countries:
        time_share = segment.country_time_shares.get(cc, 0.0)
        dist_share = segment.country_distance_shares.get(cc, 0.0)
        enter = cursor
        exit_ = cursor + duration * time_share
        cursor = exit_
        windows.append((cc, enter, exit_, dist_share))
    return windows


def _night_fraction(
    track: TrackInfrastructure, composition: Composition, enter: float, exit_: float
) -> float:
    """Share of a country run priced at the night rate — 0 for mode 'none',
    band pro-rata for 'time_band', widened to 1.0 by the DE accommodation
    rule (see module docstring)."""
    if track.tac_night_mode != "time_band":
        return 0.0
    if track.tac_night_full_if_accommodation and composition.has_night_accommodation:
        return 1.0
    if (
        track.tac_night_band_start_min is None
        or track.tac_night_band_end_min is None
        or exit_ <= enter
    ):
        return 0.0
    return band_overlap_min(
        int(enter),
        int(exit_),
        track.tac_night_band_start_min,
        track.tac_night_band_end_min,
    ) / (exit_ - enter)


def _peak_fraction(track: TrackInfrastructure, enter: float, exit_: float) -> float:
    """Share of a country run falling inside the country's declared peak
    bands, scaled by the 5/7 weekday blend when the bands are Mon–Fri
    only. 0.0 when the country declares no peak bands."""
    if exit_ <= enter:
        return 0.0
    overlap = 0.0
    for start, end in (
        (track.tac_peak_band1_start_min, track.tac_peak_band1_end_min),
        (track.tac_peak_band2_start_min, track.tac_peak_band2_end_min),
    ):
        if start is not None and end is not None:
            overlap += band_overlap_min(int(enter), int(exit_), start, end)
    fraction = overlap / (exit_ - enter)
    if track.tac_peak_weekdays_only:
        fraction *= WEEKDAY_BLEND
    return fraction


# =============================================================================
# SEGMENT TAC
# =============================================================================


def calc_segment_tac(
    segment: Segment,
    composition: Composition,
    tracks: TrackInfraCollection,
    passages: PassageChargeCollection,
    *,
    is_first_segment: bool,
    segment_revenue_eur: float = 0.0,
    segment_passengers: float = 0.0,
) -> SegmentTac:
    """
    Compute the track access charge for one segment of one trip (€/trip).

    segment_revenue_eur / segment_passengers: this segment's ticket
    revenue and passengers aboard PER TRAIN RUN — from the traffic
    pre-pass in models/evaluation/calc.py. Revenue feeds the CH
    Deckungsbeitrag term (currently NULL everywhere → 0, but real
    plumbing); passengers feed the Channel Tunnel per-passenger fee.

    is_first_segment: the trip's origin stop is nobody's to_stop, so the
    first segment charges per-stop terms for BOTH its ends.
    """
    result = SegmentTac()
    distance_km = segment.distance_m / 1000.0
    gross_t = composition.total_gross_weight_t
    seats = composition.total_places

    # --- per-country runs, in path order ---
    for cc, enter, exit_, dist_share in _country_windows(segment):
        track = tracks.get(cc)
        if track is None:
            continue  # "UNK" (open water/ferry) — no IM, no charge
        km = distance_km * dist_share
        if km <= 0.0:
            continue

        night_f = _night_fraction(track, composition, enter, exit_)
        night_km = km * night_f
        day_km = km - night_km

        b_day = track.tac_b_day or 0.0
        # A time_band country missing b_night falls back to b_day; the
        # reverse (b_day missing, night-only tariff sourced — DE, BE) keeps
        # the day fringe at 0: sourced-values-only discipline, documented
        # as a known understatement in calib/TAC_MODEL.md.
        b_night = track.tac_b_night if track.tac_b_night is not None else b_day
        base_eur = day_km * b_day + night_km * b_night

        # CH-style peak multiplier — scales the DAY-rate term only, on the
        # peak-overlapping share of the run (night bands never overlap the
        # commuter peak, so applying it to the day term is exact).
        if track.tac_peak_multiplier is not None and track.tac_peak_multiplier != 1.0:
            base_eur += (
                (track.tac_peak_multiplier - 1.0)
                * b_day
                * km
                * _peak_fraction(track, enter, exit_)
            )

        # AT-style flat congestion surcharge — own field so views can show
        # it was a congestion charge, not a higher base rate.
        congestion_eur = 0.0
        if track.tac_congestion_surcharge_eur_km is not None:
            congestion_eur = (
                track.tac_congestion_surcharge_eur_km
                * km
                * _peak_fraction(track, enter, exit_)
            )

        tonnage_eur = (track.tac_gamma or 0.0) * gross_t * km
        seat_eur = (track.tac_seat_km or 0.0) * seats * km
        fixed_eur = (track.tac_fixed_per_train_km or 0.0) * km
        revenue_share_eur = (
            (track.tac_revenue_share or 0.0) * segment_revenue_eur * dist_share
        )

        result.country_tacs.append(
            CountryTac(
                country_code=cc,
                km=km,
                night_km=night_km,
                base_eur=base_eur,
                tonnage_eur=tonnage_eur,
                seat_eur=seat_eur,
                fixed_eur=fixed_eur,
                stop_eur=0.0,  # filled below — stops belong to a stop's
                # own country, not to the run windows
                revenue_share_eur=revenue_share_eur,
                congestion_eur=congestion_eur,
            )
        )

    # --- per-stop capacity terms (CH Haltezuschlag), at each stop's own
    # country rate. The first segment charges both ends (see docstring).
    stops = [segment.to_stop]
    if is_first_segment:
        stops.append(segment.from_stop)
    for stop in stops:
        track = tracks.get(stop.country_code)
        if track is None or track.tac_per_stop is None:
            continue
        entry = next(
            (c for c in result.country_tacs if c.country_code == stop.country_code),
            None,
        )
        if entry is None:
            # Stop country not among the run windows (border-station edge
            # case) — carry the charge on its own zero-km entry.
            entry = CountryTac(
                country_code=stop.country_code,
                km=0.0,
                night_km=0.0,
                base_eur=0.0,
                tonnage_eur=0.0,
                seat_eur=0.0,
                fixed_eur=0.0,
                stop_eur=0.0,
                revenue_share_eur=0.0,
                congestion_eur=0.0,
            )
            result.country_tacs.append(entry)
        entry.stop_eur += track.tac_per_stop

    # --- passages owned by this segment (attributed at routing time) ---
    for passage_id in segment.passages:
        charge = passages.get(passage_id)
        if charge is None:
            logger.warning(
                "Segment %s→%s carries passage '%s' but no passage_charges "
                "row exists at this scenario's pinned version — charge skipped.",
                segment.from_stop.stop_id,
                segment.to_stop.stop_id,
                passage_id,
            )
            continue
        result.passage_tacs.append(
            PassageTac(
                passage_id=passage_id,
                fixed_eur=charge.fixed_eur,
                per_passenger_eur=charge.per_passenger_eur * segment_passengers,
            )
        )

    return result
