"""
calc_facility.py
================
What a service facility charges for handling a train that is not carrying
passengers: one shunting movement, one stabling occupation, and the power
drawn while the train stands.

Track access is priced in models/infrastructure/tac/, traction energy while
driving in models/infrastructure/energy_pricing/. Cleaning, interior
servicing and maintenance-facility use are operator-side and are not here.

Every rate this module reads is EUR at the 2032 evaluation year. Currency and
price-basis conversion happen exactly once, in the calibration notebook,
before the values are ever seeded. Derivations:
models/infrastructure/facility/calib/FACILITY_CALIBRATION.md.

Shunting
--------
One number per country, and most of it is not an infrastructure charge at
all: where the infrastructure manager sells only facility access — which is
twenty-three of twenty-eight countries — the calibration adds the market cost
of the shunting locomotive and crew that the IM does not supply. Pricing from
published tariffs alone books about a quarter of what an operator-side model
books for the same rotation.

The event count comes from the route builder, not from here: two Shunting
events per terminal (one from each trip that ends or starts there), which is
the two movements of one turnaround.

Stabling
--------
Four bases exist in Europe and all four are carried, because two of them are
structurally different rather than merely differently priced:

  per_metre_day   length_m x rate x started 24 h periods
  per_hour        rate x started hours, length-independent — Germany's
                  Anlagenpreissystem is explicitly "zuglaengenunabhaengig"
  per_event       one flat charge per occupation, no time term
  none            positively documented as not levied

A country's free allowance is subtracted from the stabled hours first, and an
allowance longer than the layover zeroes the charge — which is why Norway
(48 h free) and Croatia (24 h) cost nothing on a twelve-hour turnaround.

Hotel power is charged on the ACTUAL stabled hours, not on the billable hours
after that allowance: the electricity flows whether or not the siding is free.
"""

import logging
import math
from dataclasses import dataclass

from models.params import TrackInfrastructure

logger = logging.getLogger(__name__)

# =============================================================================
# RESULT OBJECTS
# =============================================================================


@dataclass
class ParkingCharge:
    """One stabling occupation. Every monetary field is EUR per event."""

    hours: float  # as scheduled — what hotel power is charged on
    billable_hours: float  # after the country's free allowance
    basis: str  # which arithmetic priced facility_eur
    facility_eur: float  # the siding itself
    hotel_power_eur: float  # power drawn while standing

    @property
    def total_eur(self) -> float:
        return self.facility_eur + self.hotel_power_eur


# =============================================================================
# PRICING
# =============================================================================


def shunting_event_eur(track: TrackInfrastructure) -> float:
    """All-in cost of one shunting movement in this country."""
    return track.shunting_eur_event


def calc_parking_event(
    track: TrackInfrastructure, *, length_m: float, hours: float
) -> ParkingCharge:
    """
    Cost of one stabling occupation of `hours` for a train `length_m` long.

    hours comes from the schedule (Parking.hours) — the gap between the
    arrival that ends one trip and the departure that starts the next at this
    terminal. A non-positive value prices nothing rather than raising: a
    single-trip route has no layover to charge for.
    """
    free_hours = track.parking_free_hours or 0.0
    billable = max(0.0, hours - free_hours)
    basis = track.parking_basis or "none"

    facility_eur = 0.0
    if basis == "per_event":
        # No time term at all: the charge is for the operation, so a train
        # that stands at all pays it in full.
        if hours > 0.0:
            facility_eur = track.parking_eur_event or 0.0
    elif billable > 0.0:
        if basis == "per_metre_day":
            rate = track.parking_eur_metre_day or 0.0
            facility_eur = rate * length_m * math.ceil(billable / 24.0)
        elif basis == "per_hour":
            rate = track.parking_eur_hour or 0.0
            facility_eur = rate * math.ceil(billable)
        elif basis != "none":
            logger.warning(
                "TrackInfrastructure[%s]: unknown parking basis '%s' — stabling "
                "priced at zero.",
                track.country_code,
                basis,
            )

    hotel_power_eur = (track.parking_hotel_power_eur_hour or 0.0) * max(0.0, hours)

    return ParkingCharge(
        hours=hours,
        billable_hours=billable,
        basis=basis,
        facility_eur=facility_eur,
        hotel_power_eur=hotel_power_eur,
    )
