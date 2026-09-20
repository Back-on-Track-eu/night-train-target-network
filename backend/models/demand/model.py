"""
model.py
========
Version constant, description, changelog, standard values, and open
TODOs for the demand model — same single-anchor convention as every
other model.py under models/: every standard assumption the model makes
lives here, and modules using a value import it from here.

DEMAND 0.1.0 is the MANUAL demand model (docs/2026-09-18_manual_demand_
guide.md): a potential demand per year is a request input, split into
five traveller groups with class preferences (groups.py), allocated onto
a composition's places by a fixed rule, spread over the sellable OD pairs
by a stop-weight matrix (od_matrix.py), and attributed to its sources —
shifted from the plane, from the car, or induced — by distance
(sources.py). distribute.py runs the three on a Route. The constants the
rule needs are below; only the total, the level, the group shares and
the OD weights/pins are request inputs.
"""

DEMAND_MODEL_VERSION: str = "0.1.0"

DEMAND_MODEL_DESCRIPTION: str = (
    "Manual demand model: a potential demand per year is an input, split "
    "into five traveller groups that each book only the classes they "
    "list — a fixed allocation rule seats them round by round, so one "
    "demand reads as a utilisation on every composition, and demand no "
    "listed class can seat is not served. Sales spread over the sellable "
    "OD pairs by a boarding × alighting stop-weight matrix, and every "
    "passenger is attributed by journey length to the plane, the car or "
    "an induced trip for the climate figures. Fares are a flat two-part "
    "tariff per class."
)

CHANGELOG: dict = {
    "0.1.0": {
        "date": "2026-09-19",
        "author": "david + claude",
        "changes": "THE STOPGAP IS REPLACED BY THE MANUAL DEMAND MODEL "
        "(docs/2026-09-18_manual_demand_guide.md, sketch round 7). "
        "STOPGAP_UTILIZATION_PER (a flat 70 % of every class) is gone; a "
        "request now carries demand.passengers_per_year (default MEDIUM, "
        "200 000 both directions, levels S/M/L/XL 100/200/300/500 k), "
        "demand.group_shares_pct (defaults 50/25/10/10/5 for comfort, "
        "group, senior, budget, business) and demand.od (stop weights per "
        "boarding and alighting stop, default 1, four fill presets, pinned "
        "cells). Per trip = per year / departures. Allocation (groups.py, "
        "D14-D19): four ROUNDS releasing 50/20/20/10 % of every group's "
        "demand, groups walked in order, RULE_SHARE 80 % seated along the "
        "preference list first-until-full, the other 20 % spread evenly "
        "over the group's other listed classes, expected values not "
        "draws; a group sits only in the classes it lists, the rest is "
        "not served. OD spread (od_matrix.py, D25-D30): share(o,d) ~ "
        "w_board(o) x w_alight(d) over the sellable pairs (boarding stop "
        "before alighting stop, night stops sell nothing), pins hold and "
        "the rest rescales. places_sold per OD pair per class per year is "
        "served x share x departures — a FLOAT now (ODPair.places_sold, "
        "proposals.od_pairs.places_sold DOUBLE PRECISION). Tariff "
        "defaults re-set (D31): Seat 10 + 0.06/km, Couchette 75 + 0.03, "
        "Sleeper 125 + 0.04, Capsule 75 + 0.03; services and catering "
        "keep 0.0.5. NEW sources.py: every OD pair's passengers split by "
        "distance into shift from air (0 below 300 km, 25 % at 300 km, "
        "linear to 100 % at 1 200 km) and other/induced, the latter half "
        "car shift and half induced — this replaces the flat "
        "MODE_SHIFT_SHARES of the emissions model in the summary's "
        "demand KPIs, which stop being placeholders. Reference values at "
        "the defaults (Berlin-Verona, 3 days/week): NEW-BAL-7 sells 260 "
        "of 637.5 places a trip, 81 566 passengers and 6 840 558 EUR "
        "ticket revenue a year (tests/test_83_demand_units.py).",
    },
    "0.0.5": {
        "date": "2026-09-14",
        "author": "david + claude",
        "changes": "THE STOPGAP TARIFF DEFAULTS ARE NOW BENCHMARKED, not round "
        "numbers. Every per-class default (fare_per_pax, fare_per_km, "
        "services, catering) is re-set from realised 2025-26 night-train "
        "fares — ÖBB Nightjet, European Sleeper, Nox, Trenitalia ICN, SNCF "
        "Intercités de nuit — net of VAT and carried to the 2032 price year. "
        "The SHAPE changes more than the level: real tariffs are nearly flat "
        "over distance (Nightjet prices one band per class for any German "
        "domestic journey), so the fixed part rises roughly fourfold and the "
        "per-km part falls to a quarter — a 1,000 km seat was 108 EUR and is "
        "now 55, a 300 km couchette was 51 and is now 66. Per-km rates are "
        "now expressed in tenths of a cent (0.025), which the request already "
        "carried at 4 decimals; the frontend follows in the same commit. "
        "Every evaluation that does not override the fares changes with "
        "this — hence the version bump.",
    },
    "0.0.4": {
        "date": "2026-09-12",
        "author": "david + claude",
        "changes": "THE TARIFF IS NOW THREE PARTS, each per class_main. "
        "(1) The base fare gains a FIXED term beside the per-km one: "
        "STOPGAP_FARE_PER_PAX_BY_CLASS, request field fares_eur_per_pax, so "
        "a ticket is fare_per_pax + fare_per_km x km rather than distance "
        "alone — a 300 km and a 1,300 km journey no longer differ by the "
        "full ratio of their lengths. (2) Additional services "
        "(STOPGAP_SERVICES_EUR_PER_PAX_BY_CLASS, services_eur_per_pax): the "
        "ticket revenue for carrying a bike or oversized luggage. NOT "
        "signed and NOT net — its cost is zero or already paid for in the "
        "coach's lower place density — so unlike catering it stays INSIDE "
        "the variable-overhead and EBIT-margin bases. (3) The catering "
        "contribution becomes per class "
        "(STOPGAP_CATERING_EUR_PER_PAX_BY_CLASS): different classes include "
        "different service in the base fare, so their passengers differ in "
        "what they buy on board. catering_eur_per_pax is therefore a MAP "
        "now, not a number — a breaking request-shape change.",
    },
    "0.0.3": {
        "date": "2026-09-12",
        "author": "david",
        "changes": "STOPGAP_CATERING_EUR_PER_PAX and resolve_catering() added: "
        "the on-board catering service enters the model as one signed net "
        "contribution per passenger (its own sales less its own costs), "
        "overridable per proposal as the request field "
        "catering_eur_per_pax — the same lifecycle the fares got with "
        "CALC 0.9.27. Not a fare class: catering sells no places, so it "
        "stays pinned to 0 in STOPGAP_FARE_PER_KM_BY_CLASS.",
    },
    "0.0.2": {
        "date": "2026-08-10",
        "author": "david",
        "changes": "version.py renamed to model.py (every model now anchors "
        "version, description, and changelog in a model.py); "
        "DEMAND_MODEL_DESCRIPTION and CHANGELOG added. Standard values "
        "and behaviour unchanged.",
    },
    "0.0.1": {
        "date": "2026-08-03",
        "author": "david",
        "changes": "Stopgap demand model moved out of models/route/ into its "
        "own models/demand/ package (route builder 0.9.13): "
        "distribute_demand() uniform-distribution proxy plus the "
        "STOPGAP_* standard values, ahead of the real demand model "
        "landing here.",
    },
}


# =============================================================================
# STANDARD VALUES — request defaults and the constants of the allocation
# rule (groups.py), the OD spread (od_matrix.py) and the source split
# (sources.py). Changing any of them changes model output — bump the
# version above.
# =============================================================================

CLASS_ORDER: tuple[str, ...] = ("Seat", "Couchette", "Sleeper", "Capsule")
"""The four accommodation classes a traveller can book, in the order the
model reports them — the same order the frontend's CLASS_ICONS use. Every
per-class map in a demand result is keyed and ordered by this."""

DEMAND_LEVELS: dict[str, int] = {
    "small": 100_000,
    "medium": 200_000,
    "large": 300_000,
    "xl": 500_000,
}
"""Potential demand presets, passengers per year over both directions
(D11). Defaults, not a scenario switch: the level writes the total and is
saved with the proposal as `demand.level`; a total matching none of them
is `custom`."""

DEFAULT_DEMAND_LEVEL: str = "medium"
"""The level a request without a demand block runs at (§2.8)."""

DEMAND_LEVEL_CUSTOM: str = "custom"

GROUP_ORDER: tuple[str, ...] = ("comfort", "group", "senior", "budget", "business")
"""The five traveller groups in allocation order (D14): every round walks
them in this order, which is what keeps the first group from taking a class
outright before a later group with the same first preference gets a turn."""

GROUP_CLASS_PREFERENCES: dict[str, tuple[str, ...]] = {
    "comfort": ("Sleeper", "Capsule", "Couchette"),
    "group": ("Couchette", "Seat"),
    "senior": ("Couchette", "Sleeper"),
    "budget": ("Seat",),
    "business": ("Sleeper", "Capsule"),
}
"""Which classes each group books, first preference first — and ONLY
those (D14, D17): demand no listed class can seat is not served, there is
no overflow into other classes and no spill between groups."""

GROUP_LABELS: dict[str, str] = {
    "comfort": "Leisure – comfort",
    "group": "Leisure – group",
    "senior": "Senior leisure",
    "budget": "Leisure – budget",
    "business": "Business",
}
"""Display names of the groups, for the models registry."""

DEFAULT_GROUP_SHARES_PCT: dict[str, float] = {
    "comfort": 50.0,
    "group": 25.0,
    "senior": 10.0,
    "budget": 10.0,
    "business": 5.0,
}
"""Default share of the potential demand per group, percent (D14). A
request may post its own; a sum other than 100 is allowed and means the
groups ask for total x sum (D15), no rebalancing."""

ROUNDS_PCT: tuple[float, ...] = (50.0, 20.0, 20.0, 10.0)
"""Share of each group's demand released in each allocation round (D16).
The rounds interleave the groups — see GROUP_ORDER."""

RULE_SHARE: float = 0.8
"""Within a round, the share of a group's released demand that follows the
rule — first listed class until full, then the next. The rest spreads
evenly over the group's OTHER listed classes; a single-class group has
none, so it is 100 % rule. Expected values, not random draws (D18)."""

OD_PRESETS: tuple[str, ...] = ("even", "long", "mid", "short")
"""Fill presets of the OD matrix (D27): each writes one weight per
boarding and alighting stop from its position along the route (0 = first,
1 = last of that list): even (all 1), long journeys (board 1−x, alight x),
mid distance (1−|2x−1| on both), short hops (board x, alight 1−x)."""

OD_PRESET_CUSTOM: str = "custom"

OD_WEIGHT_MIN: float = 0.3
OD_WEIGHT_SPAN: float = 2.7
"""A preset maps its position factor f in 0..1 to the weight
OD_WEIGHT_MIN + OD_WEIGHT_SPAN x f, one decimal (0.3 … 3.0). Even is
special-cased to 1 so the margins read naturally (finding 5)."""

DEFAULT_OD_WEIGHT: float = 1.0
"""Weight of a stop no request weight names — the even spread (D30)."""

# --- Sources (sources.py): who the passengers are, by journey length ------

AIR_SHIFT_FLOOR_KM: float = 300.0
"""Below this journey length nobody would have flown: the air share is 0."""

AIR_SHIFT_AT_FLOOR: float = 0.25
"""The air share at exactly AIR_SHIFT_FLOOR_KM, from where it rises
linearly to 1 at AIR_SHIFT_FULL_KM."""

AIR_SHIFT_FULL_KM: float = 1200.0
"""From this journey length on every passenger is a shift from the plane;
the other sources are negligible on a night train that long."""

OTHER_CAR_SHARE: float = 0.5
"""Of the passengers who would NOT have flown, the share that would have
driven; the rest is induced — a trip that would not have been made. Car
shift saves the car's emissions less the train's, an induced trip adds the
train's (models/emissions/model.py)."""

# --- Tariff (D31): a flat two-part base fare per class, plus services and
# catering per passenger. Defaults a request may override per class.

FARE_PER_KM_BY_CLASS: dict[str, float] = {
    "Seat": 0.06,
    "Couchette": 0.03,
    "Sleeper": 0.04,
    "Capsule": 0.03,
    "Catering": 0.0,
}
"""Distance part of the base fare by class_main, EUR per passenger-km, net
of VAT, 2032 price year (DEMAND 0.1.0, D31 — decided 2026-09-18 on the
sketch: seat 10 + 0.06/km, couchette 75 + 0.03, sleeper 125 + 0.04,
capsule 75 + 0.03). Deliberately small: a night-train tariff is nearly
flat over distance. Since CALC 0.9.27 these are the DEFAULTS: a request
may carry its own `fares_eur_per_km` (api/helpers/member_compute.py), per
proposal and part of the family key. Catering is not a fare class and is
pinned to 0 whatever the request says."""

FARE_CLASS_MAINS: tuple[str, ...] = ("Seat", "Couchette", "Sleeper", "Capsule")
"""The class_mains a request may price. Everything else in
FARE_PER_KM_BY_CLASS is fixed."""

FARE_PER_PAX_BY_CLASS: dict[str, float] = {
    "Seat": 10.0,
    "Couchette": 75.0,
    "Sleeper": 125.0,
    "Capsule": 75.0,
}
"""FIXED part of the base fare, EUR per passenger carried, net of VAT,
2032 price year (DEMAND 0.1.0, D31). A ticket costs `fare_per_pax +
fare_per_km x km`: a berth has a price of admission a 300 km journey pays
as surely as a 1,300 km one, so most of the fare sits here. Implied fares
at 300 / 700 / 1,200 km: seat 28 / 52 / 82 — couchette 84 / 96 / 111 —
capsule 84 / 96 / 111 — sleeper 137 / 153 / 173. Overridable per proposal
as `fares_eur_per_pax`. Ticket revenue: inside every overhead and margin
base. The 0.0.5 basis (realised 2025-26 fares of Nightjet, European
Sleeper, Nox, ICN, Intercités de nuit, net of VAT, 2032 price year) still
frames these; the 2026-09-18 decision moved the seat down and the berths
up to where the sketch's revenues read right."""

SERVICES_EUR_PER_PAX_BY_CLASS: dict[str, float] = {
    "Seat": 1.50,
    "Couchette": 2.50,
    "Sleeper": 4.00,
    "Capsule": 2.50,
}
"""Revenue from additional services, EUR per passenger carried, net of VAT,
2032 price year (DEMAND 0.0.5, kept by 0.1.0).

Bicycle carriage, oversized luggage, pets — set at ~2.5-3% of the class's
base fare, the usual ancillary share in long-distance rail; no operator
publishes the figure per passenger. Interrail/pass reservation fees are
NOT here: a pass holder's reservation IS that passenger's fare and
belongs in avg_price. NOT signed and NOT a net figure, which is what
separates it from catering: its cost is either zero or already paid for in
the lower place density of the coach that carries the bikes, so it is
already in the cost model elsewhere and must not be netted here again.

Being ordinary ticket revenue, it stays INSIDE the variable-overhead and
EBIT-margin bases. Overridable as `services_eur_per_pax`."""

CATERING_EUR_PER_PAX_BY_CLASS: dict[str, float] = {
    "Seat": 1.50,
    "Couchette": 2.00,
    "Sleeper": 1.00,
    "Capsule": 2.00,
}
"""NET catering contribution per passenger carried, EUR, by class, 2032
price year (DEMAND 0.0.5, kept by 0.1.0).

Signed, and a NET figure: the restaurant is not modelled as a business of
its own, so one number per class carries its sales less its goods,
provisioning and logistics costs. Positive means the service pays for
itself and contributes; negative means the tickets it helps sell carry
it. It EXCLUDES attendant time — the dining-coach attendant is already in
the crew line (compositions/calib/CALIBRATION.md: one attendant per
dining or bistro coach), so netting staff here again would count it
twice; a train with no catering coach sells from the trolley with the
same crew it has anyway.

Basis: DB's day trains take under 1 EUR gross per passenger (2023
on-board revenue ~110 M EUR on ~130 M passengers). A night train captures
an evening and a morning, so ~4-6 EUR gross per seat/couchette passenger,
netted at ~45% after goods and logistics, gives ~2 EUR. Sleeper is lower
because breakfast and a welcome drink are already in its fare.

Per class since DEMAND 0.0.4 because the classes differ in what their base
fare already includes. A class at 0.00 is a claim that its passengers buy
nothing, not an absence of data.

Deliberately outside the variable-overhead and EBIT-margin bases, which
stay on ticket revenue (models/evaluation/model.py): charging distribution
overhead on a figure that already nets its own overhead would count it
twice. Overridable as `catering_eur_per_pax`."""


def _resolve_per_class(
    override: dict | None, defaults: dict[str, float]
) -> dict[str, float]:
    """Defaults with the override laid over them, class by class. A request
    that prices one class leaves the others where the model had them, and
    the result is always complete so the distribution never hits a missing
    class."""
    resolved = dict(defaults)
    for class_main, value in (override or {}).items():
        if class_main in resolved:
            resolved[class_main] = float(value)
    return resolved


def resolve_catering(override: dict | None) -> dict[str, float]:
    """The net catering contribution per passenger, per class. Signed — a
    negative override is a service the tickets carry, not an error."""
    return _resolve_per_class(override, CATERING_EUR_PER_PAX_BY_CLASS)


def resolve_services(override: dict | None) -> dict[str, float]:
    """Additional-services revenue per passenger, per class. Never
    negative: nobody is paid to bring a bicycle."""
    return _resolve_per_class(override, SERVICES_EUR_PER_PAX_BY_CLASS)


def resolve_fares_per_pax(override: dict | None) -> dict[str, float]:
    """The fixed part of the base fare, per class."""
    return _resolve_per_class(override, FARE_PER_PAX_BY_CLASS)


def resolve_fares(override: dict | None) -> dict[str, float]:
    """The per-km fares one evaluation runs with: the defaults, with the
    request's values on top for the classes it names. Always returns a
    complete dict so the distribution never hits a missing class."""
    fares = dict(FARE_PER_KM_BY_CLASS)
    for class_main, value in (override or {}).items():
        if class_main in FARE_CLASS_MAINS:
            fares[class_main] = float(value)
    return fares


# =============================================================================
# OPEN TODOS
# =============================================================================

OPEN_TODOS: dict[str, str] = {
    "demand_model": (
        "The manual model takes the potential demand as an input. A demand "
        "MODEL that derives it — asymmetric directional demand, price "
        "elasticity, competition from other modes, likely per scenario — "
        "would write demand.passengers_per_year and the group shares "
        "instead of the user; the allocation, OD spread and source split "
        "stay. Candidate structure: the French open-source night train shift "
        "model's log-additive factor form."
    ),
    "od_by_class": (
        "One OD matrix for all classes (D29). Sleeper demand plausibly skews "
        "long; the request shape allows a later demand.od.by_class."
    ),
}
