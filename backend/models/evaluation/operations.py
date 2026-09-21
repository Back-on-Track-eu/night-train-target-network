"""
operations.py
=============
What it takes to run a proposal, in physical units: rakes, locomotive
hours, people on board and their hours. CALC 0.9.29.

The cost model already computes every input here and then multiplies it by
a rate — calc.py's SegmentCost carries driver_hours / crew_hours, StopCost
the dwell equivalents, RouteCost the loco lease, CompositionFleetCost the
fleet basis — but only the euros reached the wire. This module reads the
same EvaluationResult and reports the quantities before the rates, per trip
pair, so a reader can see "two trainsets, one driver and four attendants,
14.5 person-hours a trip" next to the money it turns into.

    build_operations(route, result) -> dict

is the only entry point. api/helpers/member_compute.py attaches its output
as evaluation["operations"]; it never enters the family document (D9 —
views on demand), only a member's views response.

Two figures are deliberately both shown:

    trainsets.physical      the integer rakes the cycle-time rule needs
                            (TripPair.trainsets, ROUTE_BUILDER 0.9.35)
    trainsets.theoretical   physical / coach_avail_per — what the cost
                            model charges, this route's fair share of a
                            spare fleet pooled across an operator's
                            network (see TripPair's docstring)

Neither is wrong; they answer different questions, and the panel that
shows them says which is which.

Per pair AND per trip (CALC 0.9.29). Fleet figures are symmetric by
nature — a rake does not care which way it is pointing — so they stay on
the pair. Loco hours and staffing are not: the two trips of a pair differ
in running time, in dwell, and therefore in where the duty boundaries
fall, so trip_pairs[].trips[] reports each direction on its own while the
per-cycle figures stay where they were.

INFRASTRUCTURE (handover §6.5). The per-country views already attribute
track access, energy and station charges to the country that levied them,
and the per-stop view has the station charge per call; what they cannot
say is WHAT each country charged on. `infrastructure` fills that in, per
trip, from the same component records the cost model priced:

    track_access   per country: km, night km, and every TERM that country
                   levies with its euros — distance, tonnage, seats, the
                   fixed add-on, stop fees, revenue share, congestion; plus
                   the separately billed crossings
    energy         per country: km, kWh, night kWh, the tariff it was
                   priced at (day and night rate), the electricity and the
                   catenary charge
    stations       every stop call with its country and charge
    parkings       one entry per stabling location, with the basis it was
                   priced on, the hours, and the siding and hotel-power
                   parts

It needs the track infrastructure the route was priced against for the
tariffs, so build_operations takes it as an optional argument; without it
the tariff fields are absent and everything else is still there.

What this module does NOT report: euros that are already leaves of the
breakdown. The fleet receipt's five lines (maintenance, cleaning,
shunting, amortisation, financing) are per-year leaves of the
per_trip_pair view divided by departures_per_year, and a second copy here
would be free to drift from the first. "fleet" carries the BASIS those
lines are computed from instead — the part the breakdown does not have.
"""

from __future__ import annotations

from models.evaluation.calc import EvaluationResult
from models.params import StopInfraCollection, TrackInfraCollection, roster_efficiency
from models.route.route import Route, TripPair
from models.route.trip import Trip


def _staff(on_board: float, hours: float, eur: float, operating_days: float) -> dict:
    """Euros are the cost model's own, not hours times a rate re-derived
    here: the staff rate depends on the trip's driving and on-train hours
    (roster efficiency, models/params.py), so the only figure guaranteed to
    match the cost breakdown is the one it produced. The effective rate is
    reported as eur / hours for the reader."""
    return {
        "on_board": round(on_board, 2),
        "hours_per_trip_cycle": round(hours, 2),
        "effective_rate_eur_h": round(eur / hours, 2) if hours else None,
        "eur_per_trip_cycle": round(eur, 2),
        "eur_per_year": round(eur * operating_days, 2),
    }


def _trip_staff(
    on_board: float,
    factor: float,
    trip_hours: float,
    efficiency: float,
    eur: float,
) -> dict:
    """One role on one trip, in figures a reader can check against a clock
    (CALC 0.9.31):

        hours_on_train  = on_board x trip hours       person-hours on board
        paid_hours      = hours_on_train / efficiency what the roster pays
        eur             = the cost model's own figure, factor included

    The attendant-equivalent FACTOR — the train chief is one person paid at
    1.19 attendants — appears only where the cost model applies it: in the
    euros. Putting it into the hours too (as 0.9.30 did) produced a chief
    with 10 h on a 10 h trip but 12 h "on train", which nobody could read.

    on_board is a head count where the composition has one (drivers, the
    chief) and the crew-factor sum where it does not: 0.5 attendants per
    coach is three and a half attendants on a seven-coach train, and that
    is what the hours and the euros are computed from."""
    hours_on_train = on_board * trip_hours
    paid_hours = hours_on_train / efficiency if efficiency else 0.0
    return {
        "on_board": round(on_board, 2),
        "factor": round(factor, 2),
        "hours_on_train": round(hours_on_train, 2),
        "roster_efficiency": round(efficiency, 4),
        "paid_hours": round(paid_hours, 2),
        "eur": round(eur, 2),
    }


def _trip_operations(
    trip: Trip, pair: TripPair, result: EvaluationResult, direction: str
) -> dict:
    """One trip's loco hours and staffing, off the same segment and stop
    records the cost model priced."""
    composition = pair.composition
    segs = [c for c in result.segment_costs if c.trip_id == trip.trip_id]
    stops = [c for c in result.stop_costs if c.trip_id == trip.trip_id]

    # The euros are the cost model's own. The hours are NOT summed from the
    # cost records — they are headcount x trip time (see _trip_staff) — so
    # the two never disagree with each other by a factor the reader cannot
    # see.
    driver_eur = sum(c.driver_eur for c in segs) + sum(
        c.dwell_driver_eur for c in stops
    )
    crew_eur = sum(c.crew_eur for c in segs) + sum(c.dwell_crew_eur for c in stops)

    # calc.py derives this trip's two paid rates from exactly these two
    # durations, so the efficiencies below are the ones behind its euros —
    # same inputs, not a rate divided back out of a rounded result.
    driving_h = (trip.driving_time_min + trip.dynamics_time_min) / 60.0
    on_train_h = (trip.arrival_time_min - trip.departure_time_min) / 60.0
    driver_eff = roster_efficiency(composition, "driver", driving_h, on_train_h)
    crew_eff = roster_efficiency(composition, "crew", on_train_h, on_train_h)

    chief = composition.zugchef_crew_factor
    attendants = max(0.0, composition.total_crew - chief)
    chief_share = chief / composition.total_crew if composition.total_crew else 0.0

    # Running time is what the loco spends moving (driving, dynamics,
    # buffer and any padding); the rest of its hours are the dwells at
    # intermediate stops, where it stays coupled. Terminal turnaround is
    # NOT loco time in this model — standing at a terminal is priced as
    # parking (calc.py's ParkingCost), not as lease hours.
    running_min = sum(seg.total_time_min for seg in trip.segments)
    dwell_min = sum(s.dwell_time_min or 0 for s in trip.stops)
    # Every role is on board for the whole of it.
    trip_hours = (running_min + dwell_min) / 60.0

    chief_heads = 1.0 if chief else 0.0
    staffing = {
        "drivers": _trip_staff(
            composition.driver_factor, 1.0, trip_hours, driver_eff, driver_eur
        ),
        "train_chief": _trip_staff(
            chief_heads, chief, trip_hours, crew_eff, crew_eur * chief_share
        ),
        "attendants": _trip_staff(
            attendants, 1.0, trip_hours, crew_eff, crew_eur * (1 - chief_share)
        ),
    }
    roles = ("drivers", "train_chief", "attendants")
    staffing["total"] = {
        "on_board": round(composition.driver_factor + chief_heads + attendants, 2),
        "factor_equivalents": round(
            composition.driver_factor + composition.total_crew, 2
        ),
        "hours_on_train": round(sum(staffing[r]["hours_on_train"] for r in roles), 2),
        "paid_hours": round(sum(staffing[r]["paid_hours"] for r in roles), 2),
        "eur": round(driver_eur + crew_eur, 2),
    }
    return {
        "trip_id": trip.trip_id,
        "direction": direction,
        "loco_hours": {
            "running": round(running_min / 60.0, 2),
            "at_stops": round(dwell_min / 60.0, 2),
            "total": round((running_min + dwell_min) / 60.0, 2),
        },
        "staffing": staffing,
    }


def _fleet(pair: TripPair, theoretical: float) -> dict:
    """The basis behind the fleet receipt's lines — coach count, purchase,
    write-off, availability, the two per-unit rates, the shunting event
    count. The euros stay in the breakdown (module docstring).
    coaches_needed is the cost model's own n: coaches per rake times the
    theoretical trainsets, the figure both the amortisation and the
    financing formula multiply."""
    composition = pair.composition
    coaches_per_set = len(composition.coaches)
    return {
        "coaches_per_set": coaches_per_set,
        "coaches_needed": round(coaches_per_set * theoretical, 2),
        "purchase_coach_eur": composition.purchase_coach_eur,
        "amort_years": composition.coach_amort_years,
        "financing_quota_per": composition.financing_quota_per,
        "coach_maint_eur_km": composition.coach_maint_eur_km,
        "cleaning_eur_coach_day": composition.cleaning_services_eur_day,
        # Two per trip, one at each terminal (TripPair.shunting_count) —
        # the count the shunting leaf was priced on. Its rate is levied per
        # country and lives with the track infrastructure, not here.
        "shunting_events_per_trip_cycle": pair.shunting_count,
    }


def _pair_operations(pair: TripPair, route: Route, result: EvaluationResult) -> dict:
    schedule = route.schedule
    composition = pair.composition
    operating_days = schedule.operating_days_per_year

    # The pair is the sum of its two trips. Hours come from the trips
    # (headcount x trip time, _trip_staff) and euros from the same cost
    # records the trips read, so the cycle figures and the per-direction
    # figures cannot disagree.
    trips = [
        _trip_operations(pair.outbound, pair, result, "outbound"),
        _trip_operations(pair.return_trip, pair, result, "return"),
    ]

    def both_trips(role: str, field: str) -> float:
        return sum(t["staffing"][role][field] for t in trips)

    chief = composition.zugchef_crew_factor
    attendants = max(0.0, composition.total_crew - chief)
    chief_heads = 1.0 if chief else 0.0

    physical = pair.trainsets(schedule)
    theoretical = physical / composition.coach_avail_per
    cycle = (
        pair.cycle_days(schedule.min_turnaround_min) if schedule.is_operating else None
    )
    peak_month = max(
        schedule.days_per_week_by_month, key=schedule.days_per_week_by_month.get
    )

    loco_h_cycle = pair.loco_propulsion_min / 60.0

    return {
        "composition_id": composition.comp_id,
        "trainsets": {
            "physical": physical,
            "theoretical": round(theoretical, 2),
            "coach_avail_per": composition.coach_avail_per,
            "cycle_days": cycle,
            "peak_month": peak_month,
            "min_turnaround_min": schedule.min_turnaround_min,
        },
        "fleet": _fleet(pair, theoretical),
        "loco_hours": {
            "per_trip_cycle": round(loco_h_cycle, 2),
            "per_year": round(loco_h_cycle * operating_days, 1),
            "n_locos": len(composition.locos),
        },
        "staffing": {
            "drivers": _staff(
                composition.driver_factor,
                both_trips("drivers", "hours_on_train"),
                both_trips("drivers", "eur"),
                operating_days,
            ),
            "train_chief": _staff(
                chief_heads,
                both_trips("train_chief", "hours_on_train"),
                both_trips("train_chief", "eur"),
                operating_days,
            ),
            "attendants": _staff(
                attendants,
                both_trips("attendants", "hours_on_train"),
                both_trips("attendants", "eur"),
                operating_days,
            ),
            "total": {
                "on_board": round(
                    composition.driver_factor + chief_heads + attendants, 2
                ),
                "factor_equivalents": round(
                    composition.driver_factor + composition.total_crew, 2
                ),
                "hours_per_trip_cycle": round(both_trips("total", "hours_on_train"), 2),
                "paid_hours_per_trip_cycle": round(
                    both_trips("total", "paid_hours"), 2
                ),
                "eur_per_trip_cycle": round(both_trips("total", "eur"), 2),
                "eur_per_year": round(both_trips("total", "eur") * operating_days, 2),
            },
        },
        # Outbound first, return second — pair.trips' own order. A caller
        # that wants one direction matches on "direction", not on position.
        "trips": trips,
    }


# The TAC terms, in the order the tariff documents list them. A term is
# reported only where it was non-zero: the "charged on" list is what the
# country actually levied on this run, not the full menu.
_TAC_TERMS = (
    ("base_eur", "distance"),
    ("tonnage_eur", "gross_weight"),
    ("seat_eur", "places"),
    ("fixed_eur", "fixed_add_on"),
    ("stop_eur", "stop_fee"),
    ("revenue_share_eur", "revenue_share"),
    ("congestion_eur", "congestion"),
)


def _country_defaults(tracks: TrackInfraCollection | None, code: str) -> dict:
    """Which of a country's infrastructure figures came from the EU-average
    defaults rather than from that country's own row — so a receipt can say
    "this number is a placeholder" beside the number. A country with no row
    at all is defaulted on every field."""
    infra = tracks.get(code) if tracks else None
    if infra is None:
        return {"country": False, "energy_tariff": False, "parking": False}
    flags = infra.field_is_default
    return {
        "country": not infra.has_row,
        "energy_tariff": not infra.has_row or bool(flags.get("energy_price_eur_kwh")),
        "parking": not infra.has_row or bool(flags.get("parking_eur_day")),
    }


def _trip_infrastructure(
    trip: Trip,
    route: Route,
    result: EvaluationResult,
    tracks: TrackInfraCollection | None,
    stop_infra: StopInfraCollection | None,
    direction: str,
) -> dict:
    """One trip's infrastructure charges, term by term and country by
    country, summed over its segments. Each country run in each segment
    carries its own component record; this folds them per country so the
    receipt reads once per country rather than once per segment."""
    segs = [c for c in result.segment_costs if c.trip_id == trip.trip_id]
    stops = [c for c in result.stop_costs if c.trip_id == trip.trip_id]
    names = {s.stop_id: s.stop_name for s in trip.stops}

    countries: dict[str, dict] = {}
    for seg in segs:
        for run in seg.tac.country_tacs:
            c = countries.setdefault(
                run.country_code,
                {
                    "country_code": run.country_code,
                    "km": 0.0,
                    "night_km": 0.0,
                    "terms": {key: 0.0 for _, key in _TAC_TERMS},
                    "eur": 0.0,
                },
            )
            c["km"] += run.km
            c["night_km"] += run.night_km
            for attr, key in _TAC_TERMS:
                c["terms"][key] += getattr(run, attr)
            c["eur"] += run.total_eur
    track_access = {
        "countries": [
            {
                "country_code": c["country_code"],
                "km": round(c["km"], 1),
                "night_km": round(c["night_km"], 1),
                # Only the terms this country actually charged, in tariff
                # order — the "charged on" list.
                "terms": [
                    {"term": key, "eur": round(c["terms"][key], 2)}
                    for _, key in _TAC_TERMS
                    if abs(c["terms"][key]) > 0.005
                ],
                "eur": round(c["eur"], 2),
                # The whole country priced from the EU-average defaults —
                # no track_infrastructures row of its own.
                "defaulted": _country_defaults(tracks, c["country_code"])["country"],
            }
            for c in countries.values()
        ],
        "passages": [
            {
                "passage_id": p.passage_id,
                "fixed_eur": round(p.fixed_eur, 2),
                "per_passenger_eur": round(p.per_passenger_eur, 2),
                "eur": round(p.total_eur, 2),
            }
            for seg in segs
            for p in seg.tac.passage_tacs
        ],
        "eur": round(sum(seg.tac_eur for seg in segs), 2),
    }

    energies: dict[str, dict] = {}
    for seg in segs:
        for run in seg.energy.country_energies:
            e = energies.setdefault(
                run.country_code,
                {
                    "country_code": run.country_code,
                    "km": 0.0,
                    "kwh": 0.0,
                    "night_kwh": 0.0,
                    "price_eur": 0.0,
                    "catenary_eur": 0.0,
                },
            )
            e["km"] += run.km
            e["kwh"] += run.kwh
            e["night_kwh"] += run.night_kwh
            e["price_eur"] += run.price_eur
            e["catenary_eur"] += run.catenary_eur
    energy_countries = []
    for e in energies.values():
        entry = {
            "country_code": e["country_code"],
            "km": round(e["km"], 1),
            "kwh": round(e["kwh"], 1),
            "night_kwh": round(e["night_kwh"], 1),
            "price_eur": round(e["price_eur"], 2),
            "catenary_eur": round(e["catenary_eur"], 2),
            "eur": round(e["price_eur"] + e["catenary_eur"], 2),
        }
        # The tariff it was priced at, so a reader can multiply kWh by it.
        # No VAT figure: the model prices infrastructure net of VAT and the
        # parameters carry no rate, so none is invented here.
        infra = tracks.get(e["country_code"]) if tracks else None
        if infra is not None:
            entry["tariff"] = {
                "day_eur_kwh": infra.energy_price_eur_kwh,
                "night_eur_kwh": infra.energy_price_night_eur_kwh,
                "defaulted": _country_defaults(tracks, e["country_code"])[
                    "energy_tariff"
                ],
            }
        energy_countries.append(entry)
    energy = {
        "countries": energy_countries,
        "kwh": round(sum(e["kwh"] for e in energies.values()), 1),
        "eur": round(sum(seg.energy_eur for seg in segs), 2),
    }

    stations = []
    for c in stops:
        stop = stop_infra.get(c.stop_id) if stop_infra else None
        entry = {
            "stop_id": c.stop_id,
            "stop_name": names.get(c.stop_id, c.stop_id),
            "country_code": c.country_code,
            "category": stop.stop_charge_class if stop else None,
            "eur": round(c.station_charge_eur, 2),
            # Where the tariff is mass-based (Czechia) the figure is rate ×
            # coach mass, and a reader can only check it with both beside
            # it. null for a per-call tariff.
            "per_tonne": (
                {
                    "eur_per_t": round(c.station_charge_per_tonne_eur, 6),
                    "train_mass_t": round(c.train_mass_t, 1),
                }
                if c.station_charge_per_tonne_eur
                else None
            ),
        }
        if stop_infra is not None:
            pv = stop_infra.param_versions.get(
                f"stop_infra:{c.stop_id}:stop_charge_eur"
            )
            # A stop with no charge of its own was priced at the global
            # default; say so beside the figure. Two ways to tell: the
            # loader flagged the field as resolved from the default (the
            # column was NULL), or the stored figure IS the default with no
            # charge class or source behind it — the classification pipeline
            # writes the EU-average into every stop it cannot price, which
            # the first test cannot see.
            flagged = bool(pv.is_default) if pv else False
            looks_default = (
                stop is not None
                and stop.stop_charge_class is None
                and stop.stop_charge_source is None
                and any(
                    abs(stop.stop_charge_eur - d.stop_charge_eur) < 0.005
                    for d in stop_infra.defaults.values()
                )
            )
            entry["defaulted"] = flagged or looks_default
        stations.append(entry)

    return {
        "trip_id": trip.trip_id,
        "direction": direction,
        "track_access": track_access,
        "energy": energy,
        "stations": {
            "calls": stations,
            "eur": round(sum(c.station_charge_eur for c in stops), 2),
        },
    }


def _parkings(
    route: Route, result: EvaluationResult, tracks: TrackInfraCollection | None
) -> list[dict]:
    """One entry per stabling location — €/operating-day, which is what the
    breakdown's parking leaf is built from (one stay per location per
    day), with the basis the country prices on and the two parts."""
    names = {
        s.stop_id: s.stop_name
        for pair in route.trip_pairs
        for trip in pair.trips
        for s in trip.stops
    }
    return [
        {
            "stop_id": p.stop_id,
            "stop_name": names.get(p.stop_id, p.stop_id),
            "country_code": p.country_code,
            "trip_ids": list(p.trip_ids),
            "basis": p.parking.basis,
            "hours": round(p.parking.hours, 2),
            "billable_hours": round(p.parking.billable_hours, 2),
            "facility_eur": round(p.parking.facility_eur, 2),
            "hotel_power_eur": round(p.parking.hotel_power_eur, 2),
            "eur_per_operating_day": round(p.parking_eur, 2),
            "defaulted": _country_defaults(tracks, p.country_code)["parking"],
        }
        for p in result.parking_costs
    ]


def build_operations(
    route: Route,
    result: EvaluationResult,
    tracks: TrackInfraCollection | None = None,
    stop_infra: StopInfraCollection | None = None,
) -> dict:
    """Per trip pair plus a route total. The total sums what sums (hours,
    euros, physical rakes) and leaves per-pair facts (cycle days, the
    composition) to the pairs. The two annualisers sit on the total too, so
    a per-trip figure reaches the year on the numbers the backend used
    rather than on a schedule the reader re-derives."""
    pairs = [_pair_operations(p, route, result) for p in route.trip_pairs]
    operating_days = route.schedule.operating_days_per_year
    total = {
        "operating_days_per_year": operating_days,
        # One departure per trip of every pair on every operating day —
        # EXACT, not rounded (CALC 0.9.33): this is the divisor the receipts
        # take a per-year leaf to a per-trip figure with, and 3 days a week
        # over a 366-day year is 313.71 departures, not 314. The summary row
        # rounds its copy because it is an INTEGER gallery column.
        "departures_per_year": operating_days * 2 * len(route.trip_pairs),
        "trainsets_physical": sum(p["trainsets"]["physical"] for p in pairs),
        "trainsets_theoretical": round(
            sum(p["trainsets"]["theoretical"] for p in pairs), 2
        ),
        "loco_hours_per_year": round(
            sum(p["loco_hours"]["per_year"] for p in pairs), 1
        ),
        "staff_hours_per_trip_cycle": round(
            sum(p["staffing"]["total"]["hours_per_trip_cycle"] for p in pairs), 2
        ),
        "staff_eur_per_year": round(
            sum(p["staffing"]["total"]["eur_per_year"] for p in pairs), 2
        ),
    }
    infrastructure = {
        "trips": [
            _trip_infrastructure(trip, route, result, tracks, stop_infra, direction)
            for pair in route.trip_pairs
            for trip, direction in (
                (pair.outbound, "outbound"),
                (pair.return_trip, "return"),
            )
        ],
        "parkings": _parkings(route, result, tracks),
    }
    return {"trip_pairs": pairs, "route": total, "infrastructure": infrastructure}
