"""
calc_tac.py
===========
Track access charge for one segment — the minimum access package only.

The charge for using the track itself, per routed leg. Station charges,
traction energy, shunting and parking are separate domains and no column
of theirs is read here. The one apparent exception is the per-stop term:
the Swiss Haltezuschlag is a capacity element of the path price, not a
station-usage fee, which is why it belongs to TAC — the reasoning is set
out in models/infrastructure/tac/calib/TAC_CALIBRATION.md.

Every rate this module reads is EUR at the 2032 evaluation year. Currency
and price-basis conversion happen exactly once, in the calibration
notebook, before the values are ever seeded — no unit, currency or year
arithmetic belongs here.

The flat TrackInfrastructure.tac_eur_train_km display value is never read;
tests/test_73_calc_tac_units.py pins that by setting it absurdly high.

Component model
---------------
Per country, each term optional. A None is a documented tariff fact —
"this country does not levy this" — not missing data: countries with no
calibrated tariff at all were already resolved to the EU-median group by
DBDataLoader before reaching this module.

  b_day / b_night      EUR/train-km, day and night rate
  gamma                EUR/gross-tonne-km on the whole consist
  seat_km              EUR/seat-km (ES corridor surcharge)
  fixed_per_train_km   EUR/train-km administrative add-on (LU)
  per_stop             EUR/stop path-capacity element (CH Haltezuschlag)
  revenue_share        fraction of attributable traffic revenue (CH
                       Deckungsbeitrag)
  peak_multiplier /    two IMs price the same phenomenon — an approach leg
  congestion_surcharge landing in a congested node during the commuter
                       peak — two ways: CH multiplies the day rate, AT
                       adds a flat EUR/train-km. Kept as separate fields
                       so a congestion charge can be shown as one.

Night rates
-----------
Mode 'none' prices everything at b_day, so a gamma-only country falls out
correctly (its b_day is None, hence 0).

Mode 'time_band' splits each country run pro rata between day and night
rate by the clock time it spends inside the national band. Pro rata, not
a midpoint pick: Belgium's banded rate is several times its off-peak one,
and a midpoint rule would badly mismodel a run straddling the boundary.

Germany additionally sets night_full_if_accommodation. The DB InfraGO
SPFV rule widens the night rate to the entire German run when the train
carries night accommodation — a property of the composition, needing no
timetable. Worked examples, all against the 23:00-06:00 band and all
pinned in the test suite:

  23:30-05:00, any composition          100% night (inside the band)
  00:00-08:00, no accommodation          75% night (6 of 8 h in band)
  00:00-08:00, with accommodation       100% night (widened)
  20:00-08:00, no accommodation        58.33% night (7 of 12 h)
  20:00-08:00, with accommodation      100% night (widened)

Switzerland has no night/day TAC split at all — its 22:00-06:00 band is
an electricity tariff, not a track access one.

Peak and congestion
-------------------
AT and CH share the peak band columns (Mon-Fri 06:00-09:00 and
16:00-19:00 on declared high-load sections). _peak_fraction() takes the
exact overlap, then scales it by 5/7 where the bands are weekday-only:
a Segment carries clock minutes but not a service date, so a weekday
tariff is priced at its expected value.

Both surcharges are applied to the peak-overlapping share of any run,
not only to sections confirmed as congested. That is a deliberate
conservative default: a night train's morning approach into Zurich HB or
Wien Hbf plausibly touches a declared section, and pricing every
unconfirmed approach at zero would understate cost in exactly the pattern
night trains run.

Stops
-----
A segment owns its to_stop; a trip's origin is nobody's to_stop, so the
first segment of a trip charges both of its ends. Each stop is charged at
its own country's rate.

Passages
--------
Storebaelt, Oresund and the Channel Tunnel are resolved at routing time
by polygon intersection (rail_router.PassageIndex). This module only
reads segment.passages and looks each id up, so a crossing split by an
intermediate stop is charged once per trip, not once per leg. The Channel
Tunnel additionally charges per passenger, which is what
segment_passengers carries — from the traffic pre-pass in
models/evaluation/calc.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from models.infrastructure.model import WEEKDAY_BLEND
from models.params import (
    Composition,
    PassageChargeCollection,
    TrackInfraCollection,
    TrackInfrastructure,
)
from models.route.trip import Segment
from models.utils import band_overlap_min

logger = logging.getLogger(__name__)

# =============================================================================
# RESULT OBJECTS
# =============================================================================


@dataclass
class CountryTac:
    """TAC breakdown for one country run within one segment. Every monetary
    field is EUR/trip — one train run over this segment."""

    country_code: str
    km: float  # this country's share of the segment length
    night_km: float  # km priced at the night rate (0 in mode 'none')
    base_eur: float  # day_km x b_day + night_km x b_night
    tonnage_eur: float  # gamma x gross tonnes x km
    seat_eur: float  # seat_km x places x km
    fixed_eur: float  # fixed_per_train_km x km
    stop_eur: float  # per_stop x stops charged in this country
    revenue_share_eur: float  # revenue_share x segment revenue x dist share
    congestion_eur: float  # AT-style flat surcharge; the CH multiplier is
    # folded into base_eur instead, since it scales the day rate itself

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
    """Charge for one crossing attributed to this segment. EUR/trip."""

    passage_id: str
    fixed_eur: float
    per_passenger_eur: float  # rate x segment_passengers, already multiplied

    @property
    def total_eur(self) -> float:
        return self.fixed_eur + self.per_passenger_eur


@dataclass
class SegmentTac:
    """Full TAC result for one segment of one trip. EUR/trip."""

    country_tacs: list[CountryTac] = field(default_factory=list)
    passage_tacs: list[PassageTac] = field(default_factory=list)

    @property
    def total_eur(self) -> float:
        return sum(c.total_eur for c in self.country_tacs) + sum(
            p.total_eur for p in self.passage_tacs
        )

    @property
    def passage_eur(self) -> float:
        return sum(p.total_eur for p in self.passage_tacs)

    @property
    def by_country(self) -> dict[str, float]:
        """{country_code: EUR/trip} over the country runs only — what the
        per-country cost views allocate on. Passage charges are deliberately
        absent: a crossing is billed by its operator, not by the country
        whose waters it sits in, so folding it in here would misattribute
        it (models/evaluation/views.py spreads it by distance share
        instead, and says so)."""
        totals: dict[str, float] = {}
        for entry in self.country_tacs:
            totals[entry.country_code] = (
                totals.get(entry.country_code, 0.0) + entry.total_eur
            )
        return totals


# =============================================================================
# PLACING A COUNTRY RUN ON THE CLOCK
# =============================================================================


def _country_windows(segment: Segment) -> list[tuple[str, float, float, float]]:
    """
    Place each country run of the segment on the clock:
    (country_code, enter_min, exit_min, distance_share), in path order.

    Each country's time share positions it between the from_stop departure
    and the to_stop arrival; its distance share gives it a length. "UNK"
    slices (open water, ferries, geometry outside every polygon) still
    advance the time cursor so they do not shift later countries' windows,
    and are yielded like any other — the caller skips them, since there is
    no infrastructure manager to pay.
    """
    t0 = segment.from_stop.departure_time_min
    t1 = segment.to_stop.arrival_time_min
    duration = float((t1 or 0) - (t0 or 0)) if t0 is not None else 0.0

    # Ordered path list. Payloads stored before ROUTE_BUILDER 0.9.21 have
    # none — fall back to the share dict's keys, which loses ordering
    # precision (and so places the clock windows only approximately) but
    # keeps a stale route evaluable.
    countries = segment.countries or list(segment.country_distance_shares.keys())

    windows: list[tuple[str, float, float, float]] = []
    cursor = float(t0 or 0)
    for cc in countries:
        enter = cursor
        cursor += duration * segment.country_time_shares.get(cc, 0.0)
        windows.append(
            (cc, enter, cursor, segment.country_distance_shares.get(cc, 0.0))
        )
    return windows


def _night_fraction(
    track: TrackInfrastructure, composition: Composition, enter: float, exit_: float
) -> float:
    """Share of a country run priced at the night rate — 0 in mode 'none',
    the band overlap in mode 'time_band', widened to the whole run by the
    German accommodation rule. See the module docstring."""
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
        enter,
        exit_,
        track.tac_night_band_start_min,
        track.tac_night_band_end_min,
    ) / (exit_ - enter)


def _peak_fraction(track: TrackInfrastructure, enter: float, exit_: float) -> float:
    """Share of a country run inside the country's declared peak bands,
    scaled by the weekday blend where the bands are Mon-Fri only. 0.0 for a
    country that declares no peak bands."""
    if exit_ <= enter:
        return 0.0
    overlap = 0.0
    for start, end in (
        (track.tac_peak_band1_start_min, track.tac_peak_band1_end_min),
        (track.tac_peak_band2_start_min, track.tac_peak_band2_end_min),
    ):
        if start is not None and end is not None:
            overlap += band_overlap_min(enter, exit_, start, end)
    fraction = overlap / (exit_ - enter)
    if track.tac_peak_weekdays_only:
        fraction *= WEEKDAY_BLEND
    return fraction


# =============================================================================
# SEGMENT TAC
# =============================================================================


def _country_run_tac(
    track: TrackInfrastructure,
    composition: Composition,
    *,
    country_code: str,
    km: float,
    dist_share: float,
    enter: float,
    exit_: float,
    segment_revenue_eur: float,
) -> CountryTac:
    """Every per-kilometre term for one country run. Stop charges are added
    afterwards by the caller — a stop belongs to its own country, which is
    not necessarily one of the run windows."""
    night_km = km * _night_fraction(track, composition, enter, exit_)
    day_km = km - night_km

    b_day = track.tac_b_day or 0.0
    # A banded country with no separate night rate prices the night share at
    # its day rate. The reverse — a night-only tariff sourced without a day
    # rate, as in DE and BE — deliberately leaves the day fringe at zero:
    # only sourced values are priced, and the resulting understatement is
    # recorded as such in TAC_CALIBRATION.md.
    b_night = track.tac_b_night if track.tac_b_night is not None else b_day
    base_eur = day_km * b_day + night_km * b_night

    # CH-style multiplier: scales the DAY-rate term on the peak-overlapping
    # share of the run. Applying it to the day term is exact rather than
    # approximate, since a commuter peak band never overlaps a night band.
    if track.tac_peak_multiplier is not None and track.tac_peak_multiplier != 1.0:
        base_eur += (
            (track.tac_peak_multiplier - 1.0)
            * b_day
            * km
            * _peak_fraction(track, enter, exit_)
        )

    congestion_eur = 0.0
    if track.tac_congestion_surcharge_eur_km is not None:
        congestion_eur = (
            track.tac_congestion_surcharge_eur_km
            * km
            * _peak_fraction(track, enter, exit_)
        )

    return CountryTac(
        country_code=country_code,
        km=km,
        night_km=night_km,
        base_eur=base_eur,
        tonnage_eur=(track.tac_gamma or 0.0) * composition.total_gross_weight_t * km,
        seat_eur=(track.tac_seat_km or 0.0)
        * sum(composition.places_by_class.values())
        * km,
        fixed_eur=(track.tac_fixed_per_train_km or 0.0) * km,
        stop_eur=0.0,  # filled by _add_stop_charges()
        revenue_share_eur=(track.tac_revenue_share or 0.0)
        * segment_revenue_eur
        * dist_share,
        congestion_eur=congestion_eur,
    )


def _add_stop_charges(
    result: SegmentTac,
    segment: Segment,
    tracks: TrackInfraCollection,
    *,
    is_first_segment: bool,
) -> None:
    """Per-stop path-capacity terms, each at its own stop's country rate.
    Folded onto that country's existing run entry where there is one; a stop
    in a country the run never enters (a border station reached over the
    neighbour's track) gets its own zero-kilometre entry rather than being
    dropped."""
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


def _add_passage_charges(
    result: SegmentTac,
    segment: Segment,
    passages: PassageChargeCollection,
    segment_passengers: float,
) -> None:
    """Crossings this segment owns, attributed at routing time."""
    for passage_id in segment.passages:
        charge = passages.get(passage_id)
        if charge is None:
            logger.warning(
                "Segment %s->%s crosses passage '%s' but this scenario's "
                "pinned passage_charges version has no row for it — charge "
                "skipped.",
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
    Track access charge for one segment of one trip, in EUR/trip.

    segment_revenue_eur and segment_passengers are this segment's ticket
    revenue and passengers aboard PER TRAIN RUN, from the traffic pre-pass
    in models/evaluation/calc.py. Revenue feeds the Swiss Deckungsbeitrag
    term; passengers feed the Channel Tunnel's per-passenger fee.

    is_first_segment: a trip's origin stop is nobody's to_stop, so the
    first segment charges per-stop terms at both of its ends.
    """
    result = SegmentTac()
    distance_km = segment.distance_m / 1000.0

    for cc, enter, exit_, dist_share in _country_windows(segment):
        track = tracks.get(cc)
        if track is None:
            continue  # "UNK" — open water or ferry, no infrastructure manager
        km = distance_km * dist_share
        if km <= 0.0:
            continue
        result.country_tacs.append(
            _country_run_tac(
                track,
                composition,
                country_code=cc,
                km=km,
                dist_share=dist_share,
                enter=enter,
                exit_=exit_,
                segment_revenue_eur=segment_revenue_eur,
            )
        )

    _add_stop_charges(result, segment, tracks, is_first_segment=is_first_segment)
    _add_passage_charges(result, segment, passages, segment_passengers)
    return result
