"""
calc_energy_price.py
====================
Cost of the electricity one segment draws, plus the charges levied for
supplying it — the price side of traction energy.

How much energy a train uses is a different question, answered by
models/energy/ before this module runs: it enriches Segment.energy_kwh, and
this module only prices it. Track access is priced separately
(models/infrastructure/tac/calc_tac.py) and excludes every
supply-equipment charge per country, which is precisely why they are
charged here.

Every rate this module reads is EUR at the 2032 evaluation year. Currency
and price-basis conversion happen exactly once, in the calibration
notebook, before the values are ever seeded — no unit, currency or year
arithmetic belongs here. Derivations:
models/infrastructure/energy_pricing/calib/ENERGY_PRICING_CALIBRATION.md.

Terms
-----
  energy_price_eur_kwh        EUR/kWh, the day rate — and the rate around
                              the clock for the 25 countries whose tariff
                              is not banded
  energy_price_night_eur_kwh  EUR/kWh inside the national night band. None
                              is a tariff fact, not a gap: only AT, CH and
                              HR band their electricity price
  catenary_eur_train_km       EUR/train-km for use of the catenary and the
                              traction power-supply installations (FR, HR,
                              HU, IT, LT, LU, LV, PL, RO)
  catenary_eur_gross_tonne_km the same charge where the IM levies it on
                              weight moved instead (FI, GR, SK), on the
                              whole consist including locomotives

The two catenary columns are never both populated for one country — an
infrastructure manager picks a unit. They stay in their published units
rather than being folded into the per-kWh price, because converting them
would need an assumed consumption, and models/energy/ is still a flat
placeholder factor: every one of these rates would silently move the day
that model is calibrated.

Night band
----------
The in-band share of a country run is its clock overlap with the band, and
the energy drawn there is that share of the country run's kWh. That equates
time share with distance share within a single country run, which is exact
at constant speed and close enough otherwise: the alternative would need to
know where along the run the clock crossed the band boundary, which the
routed geometry does not carry.

The electricity band is independent of the track access night band and must
not be conflated with it. Germany bands track access 23:00-06:00 and does
not band electricity at all; Switzerland bands electricity 22:00-06:00 and
has no track access night rate.
"""

import logging
from dataclasses import dataclass, field

from models.params import Composition, TrackInfraCollection, TrackInfrastructure
from models.route.trip import Segment
from models.utils import band_overlap_min

logger = logging.getLogger(__name__)

# =============================================================================
# RESULT OBJECTS
# =============================================================================


@dataclass
class CountryEnergy:
    """Energy cost for one country run within one segment. Every monetary
    field is EUR/trip — one train run over this segment."""

    country_code: str
    km: float  # this country's share of the segment length
    kwh: float  # this country's share of the segment's energy
    night_kwh: float  # of that, drawn inside the night band (0 if unbanded)
    price_eur: float  # day_kwh x day rate + night_kwh x night rate
    catenary_eur: float  # supply-equipment charge, either unit

    @property
    def total_eur(self) -> float:
        return self.price_eur + self.catenary_eur


@dataclass
class SegmentEnergy:
    """Full traction energy cost for one segment of one trip. EUR/trip."""

    country_energies: list[CountryEnergy] = field(default_factory=list)

    @property
    def total_eur(self) -> float:
        return sum(c.total_eur for c in self.country_energies)

    @property
    def price_eur(self) -> float:
        """The electricity itself, across every country run."""
        return sum(c.price_eur for c in self.country_energies)

    @property
    def catenary_eur(self) -> float:
        """The supply-equipment charges, across every country run."""
        return sum(c.catenary_eur for c in self.country_energies)

    @property
    def by_country(self) -> dict[str, float]:
        """{country_code: EUR/trip} — what the per-country cost views
        allocate on. Every term here is levied by the country whose leg it
        was drawn on, so unlike track access there is no crossing charge to
        keep out of this."""
        totals: dict[str, float] = {}
        for entry in self.country_energies:
            totals[entry.country_code] = (
                totals.get(entry.country_code, 0.0) + entry.total_eur
            )
        return totals


# =============================================================================
# BAND SHARE OF A COUNTRY RUN
# =============================================================================


def _night_fraction(track: TrackInfrastructure, enter: float, exit_: float) -> float:
    """Share of a country run priced at the night rate — 0 where the country
    has no banded tariff. See the module docstring on why a clock share is
    applied to kilowatt-hours."""
    if (
        track.energy_price_night_eur_kwh is None
        or track.energy_night_band_start_min is None
        or track.energy_night_band_end_min is None
        or exit_ <= enter
    ):
        return 0.0
    return band_overlap_min(
        enter,
        exit_,
        track.energy_night_band_start_min,
        track.energy_night_band_end_min,
    ) / (exit_ - enter)


# =============================================================================
# SEGMENT ENERGY
# =============================================================================


def _country_run_energy(
    track: TrackInfrastructure,
    composition: Composition,
    *,
    country_code: str,
    km: float,
    kwh: float,
    enter: float,
    exit_: float,
) -> CountryEnergy:
    """The electricity bill and the supply-equipment charge for one country
    run."""
    night_kwh = kwh * _night_fraction(track, enter, exit_)
    day_kwh = kwh - night_kwh

    day_rate = track.energy_price_eur_kwh
    # Only reached when a night rate exists — _night_fraction returns 0
    # otherwise, so the day rate prices the whole run.
    night_rate = track.energy_price_night_eur_kwh or day_rate
    price_eur = day_kwh * day_rate + night_kwh * night_rate

    # A country levies one unit or the other, never both — but summing
    # rather than branching keeps the code honest if one ever does.
    catenary_eur = (track.energy_catenary_eur_train_km or 0.0) * km
    if track.energy_catenary_eur_gross_tonne_km is not None:
        catenary_eur += (
            track.energy_catenary_eur_gross_tonne_km
            * composition.total_gross_weight_t
            * km
        )

    return CountryEnergy(
        country_code=country_code,
        km=km,
        kwh=kwh,
        night_kwh=night_kwh,
        price_eur=price_eur,
        catenary_eur=catenary_eur,
    )


def calc_segment_energy(
    segment: Segment,
    composition: Composition,
    tracks: TrackInfraCollection,
) -> SegmentEnergy:
    """
    Traction energy cost for one segment of one trip, in EUR/trip.

    Energy is split between countries by distance share, the same basis the
    energy model itself uses, and then between day and night by the clock
    time each country run spends inside that country's electricity band.
    """
    result = SegmentEnergy()
    distance_km = segment.distance_m / 1000.0

    for cc, enter, exit_, dist_share in segment.country_windows():
        track = tracks.get(cc)
        if track is None:
            continue  # "UNK" — open water or ferry, no supplier to pay
        km = distance_km * dist_share
        if km <= 0.0:
            continue
        result.country_energies.append(
            _country_run_energy(
                track,
                composition,
                country_code=cc,
                km=km,
                kwh=segment.energy_kwh * dist_share,
                enter=enter,
                exit_=exit_,
            )
        )
    return result
