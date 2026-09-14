"""
model.py
========
Version constant, description, changelog, standard values, and open
TODOs for the demand model — same single-anchor convention as every
other model.py under models/: every standard assumption the model makes
lives here, and modules using a value import it from here.

The demand model is currently the stopgap uniform-distribution proxy
(stopgap.py) — DEMAND_MODEL_VERSION stays 0.0.x until the real model
(OPEN_TODOS["demand_model"] below) replaces it. The version is not yet
reported in API responses; that wiring lands with the real model.
"""

DEMAND_MODEL_VERSION: str = "0.0.5"

DEMAND_MODEL_DESCRIPTION: str = (
    "Demand model (placeholder): assumes every accommodation class is "
    "70% booked at a flat two-part fare (fixed + per-km, by class), spread "
    "evenly across all "
    "connections — a stand-in until a real demand model with directional "
    "demand, price sensitivity, and competition from other modes "
    "replaces it."
)

CHANGELOG: dict = {
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
# STANDARD VALUES — stopgap demand (stopgap.distribute_demand() inputs)
# =============================================================================

STOPGAP_UTILIZATION_PER: float = 0.7
"""Placeholder scalar utilization applied uniformly to every class until a
real demand model lands."""

STOPGAP_FARE_PER_KM_BY_CLASS: dict[str, float] = {
    "Seat": 0.025,
    "Couchette": 0.035,
    "Sleeper": 0.060,
    "Capsule": 0.040,
    "Catering": 0.0,
}
"""Distance part of the base fare by class_main, EUR per passenger-km, net
of VAT, 2032 price year (DEMAND 0.0.5 — see STOPGAP_FARE_PER_PAX_BY_CLASS
for the basis shared by both parts).

Deliberately small: a night-train tariff is nearly flat over distance.
ÖBB Nightjet prices one band per class for ANY German domestic journey,
and the spread between a 300 km and a 1,300 km ticket at the other
operators is a fraction of the fare, not a multiple. Expressed in tenths
of a cent, which the request field carries at 4 decimals.

Since CALC 0.9.27 these are the DEFAULTS: a request may carry its own
`fares_eur_per_km` (api/helpers/member_compute.py), per proposal and part of
the family key. Catering is not a fare class and is pinned to 0 whatever
the request says."""

FARE_CLASS_MAINS: tuple[str, ...] = ("Seat", "Couchette", "Sleeper", "Capsule")
"""The class_mains a request may price. Everything else in
STOPGAP_FARE_PER_KM_BY_CLASS is fixed."""

STOPGAP_FARE_PER_PAX_BY_CLASS: dict[str, float] = {
    "Seat": 30.0,
    "Couchette": 55.0,
    "Sleeper": 110.0,
    "Capsule": 75.0,
}
"""FIXED part of the base fare, EUR per passenger carried, net of VAT,
2032 price year.

The tariff is two-part: a ticket costs `fare_per_pax + fare_per_km x km`.
Real night-train tariffs are not proportional to distance — a berth has a
price of admission that a 300 km journey pays as surely as a 1,300 km one
— so most of the fare sits here. Overridable per proposal as
`fares_eur_per_pax`. Ticket revenue: inside every overhead and margin base.

Basis (DEMAND 0.0.5, research 2026-09-14): revenue-weighted REALISED
average fares — the mix of Sparschiene/Standard tickets and berth types
an operator actually sells, not entry prices — read from 2025-26 tariffs
of ÖBB Nightjet (German domestic price bands per class), European
Sleeper (Brussels-Prague), Nox (announced 129 EUR single / 219 EUR
double cabin), Trenitalia Intercity Notte and SNCF Intercités de nuit,
weighted toward the open-access operators since the PSO fares are set
under subsidy. Targets at 1,000 km, gross 2026: seat ~55, couchette ~90,
capsule ~110, sleeper ~165 EUR (a berth, blended over single/double/
triple). Cross-checks: Back-on-Track's Nox critique puts open-access cost
coverage at ~95 EUR net per passenger at ~1,000 km; DLR's low-cost
airline average on 500-1,500 km was 79 EUR gross (autumn 2024).

Price year: observed 2026 gross, stripped of ~7-8% blended VAT (x0.925)
and escalated to nominal 2032 at 2%/yr (x1.126) — the two nearly cancel
(x1.04), so the parameters read like the 2026 gross figures. The
`vat_exempt` measure multiplies THIS net base, so do not strip VAT twice.

Implied fares, per_pax + per_km x km, at 300 / 700 / 1,200 km:
seat 38 / 48 / 60 — couchette 66 / 80 / 97 — capsule 87 / 103 / 123 —
sleeper 128 / 152 / 182."""

STOPGAP_SERVICES_EUR_PER_PAX_BY_CLASS: dict[str, float] = {
    "Seat": 1.50,
    "Couchette": 2.50,
    "Sleeper": 4.00,
    "Capsule": 2.50,
}
"""Revenue from additional services, EUR per passenger carried, net of VAT,
2032 price year (DEMAND 0.0.5).

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

STOPGAP_CATERING_EUR_PER_PAX_BY_CLASS: dict[str, float] = {
    "Seat": 1.50,
    "Couchette": 2.00,
    "Sleeper": 1.00,
    "Capsule": 2.00,
}
"""NET catering contribution per passenger carried, EUR, by class, 2032
price year (DEMAND 0.0.5).

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
because breakfast and a welcome drink are already in its fare. Watch the
cost side: svc_stockings at 0.25-1.50 EUR/place cannot carry linen plus
an included breakfast; if that line is under-costed, these positives are
partly offset there.

Per class since DEMAND 0.0.4 because the classes differ in what their base
fare already includes — a sleeper fare that covers breakfast leaves less
to buy on board than a seat fare that covers nothing, so the same
restaurant nets differently from the two. A class at 0.00 is a claim that
its passengers buy nothing, not an absence of data.

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
    return _resolve_per_class(override, STOPGAP_CATERING_EUR_PER_PAX_BY_CLASS)


def resolve_services(override: dict | None) -> dict[str, float]:
    """Additional-services revenue per passenger, per class. Never
    negative: nobody is paid to bring a bicycle."""
    return _resolve_per_class(override, STOPGAP_SERVICES_EUR_PER_PAX_BY_CLASS)


def resolve_fares_per_pax(override: dict | None) -> dict[str, float]:
    """The fixed part of the base fare, per class."""
    return _resolve_per_class(override, STOPGAP_FARE_PER_PAX_BY_CLASS)


def resolve_fares(override: dict | None) -> dict[str, float]:
    """The per-km fares one evaluation runs with: the defaults, with the
    request's values on top for the classes it names. Always returns a
    complete dict so the distribution never hits a missing class."""
    fares = dict(STOPGAP_FARE_PER_KM_BY_CLASS)
    for class_main, value in (override or {}).items():
        if class_main in FARE_CLASS_MAINS:
            fares[class_main] = float(value)
    return fares


# =============================================================================
# OPEN TODOS
# =============================================================================

OPEN_TODOS: dict[str, str] = {
    "demand_model": (
        "Replace stopgap.distribute_demand()'s inputs (STOPGAP_UTILIZATION_"
        "PER, STOPGAP_FARE_PER_KM_BY_CLASS above) and its uniform-"
        "distribution proxy with a real demand model accounting for "
        "asymmetric directional demand, price elasticity, and competition "
        "from other modes — likely with per-scenario parameters. Candidate "
        "structure identified: the French open-source night train shift "
        "model's log-additive factor form (compatible with the existing "
        "test suite). The placeholder demand KPIs in adapters/proposal/"
        "projection.py (_PLACEHOLDER_* constants, adapters/proposal/README.md §8.1) "
        "are the second replacement site once this lands."
    ),
}
