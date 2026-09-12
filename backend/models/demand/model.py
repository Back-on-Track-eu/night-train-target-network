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

DEMAND_MODEL_VERSION: str = "0.0.4"

DEMAND_MODEL_DESCRIPTION: str = (
    "Demand model (placeholder): assumes every accommodation class is "
    "70% booked at a flat per-kilometre fare, spread evenly across all "
    "connections — a stand-in until a real demand model with directional "
    "demand, price sensitivity, and competition from other modes "
    "replaces it."
)

CHANGELOG: dict = {
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
    "Seat": 0.10,
    "Couchette": 0.13,
    "Sleeper": 0.18,
    "Capsule": 0.12,
    "Catering": 0.0,
}
"""Placeholder flat per-km fares by class_main — same caveat as above.

Since CALC 0.9.27 these are the DEFAULTS: a request may carry its own
`fares_eur_per_km` (api/helpers/member_compute.py), per proposal and part of
the family key. Catering is not a fare class and is pinned to 0 whatever
the request says."""

FARE_CLASS_MAINS: tuple[str, ...] = ("Seat", "Couchette", "Sleeper", "Capsule")
"""The class_mains a request may price. Everything else in
STOPGAP_FARE_PER_KM_BY_CLASS is fixed."""

STOPGAP_FARE_PER_PAX_BY_CLASS: dict[str, float] = {
    "Seat": 8.0,
    "Couchette": 12.0,
    "Sleeper": 18.0,
    "Capsule": 12.0,
}
"""Placeholder FIXED part of the base fare, EUR per passenger carried.

The tariff is two-part: a ticket costs `fare_per_pax + fare_per_km x km`.
Real night-train tariffs are not proportional to distance — a berth has a
price of admission that a 300 km journey pays as surely as a 1,300 km one
— and pricing on distance alone made short OD pairs implausibly cheap and
long ones implausibly dear. Overridable per proposal as
`fares_eur_per_pax`. Ticket revenue: inside every overhead and margin base.

Placeholder, like the per-km rates beside it: these are plausible round
numbers, not a calibration (DEMAND 0.0.4)."""

STOPGAP_SERVICES_EUR_PER_PAX_BY_CLASS: dict[str, float] = {
    "Seat": 1.50,
    "Couchette": 2.00,
    "Sleeper": 3.00,
    "Capsule": 2.00,
}
"""Placeholder revenue from additional services, EUR per passenger carried.

Bicycle carriage, oversized luggage, pets, seat reservations bought
alongside the ticket. NOT signed and NOT a net figure, which is what
separates it from catering: its cost is either zero or already paid for in
the lower place density of the coach that carries the bikes, so it is
already in the cost model elsewhere and must not be netted here again.

Being ordinary ticket revenue, it stays INSIDE the variable-overhead and
EBIT-margin bases. Overridable as `services_eur_per_pax`."""

STOPGAP_CATERING_EUR_PER_PAX_BY_CLASS: dict[str, float] = {
    "Seat": 1.20,
    "Couchette": 1.20,
    "Sleeper": 0.60,
    "Capsule": 1.20,
}
"""Placeholder NET catering contribution per passenger carried, EUR, by class.

Signed, and a NET figure: the restaurant is not modelled as a business of
its own, so one number per class carries its sales less its own service,
stocking and overhead costs. Positive means the service pays for itself
and contributes; negative means the tickets it helps sell carry it, which
is the usual night-train case.

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
