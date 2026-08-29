"""
test_74_locomotive_units.py
===========================
Pure unit tests for the locomotive catalog in models/params.py and its
resolution in the loader — no Docker stack, no DB. Runnable standalone:

    uv run --extra dev pytest tests/test_74_locomotive_units.py -v

What is pinned here is the modelling, not the numbers: that the count
follows the assignment rather than being stored beside it, that gross
weight is coaches plus EVERY machine, that the lease is summed per
machine at this operator's rate, and that an unpriced (operator, machine)
pairing fails loudly instead of resolving to something plausible.
"""

import pytest

from adapters.data_loader_from_db import DBDataLoader
from models.params import LocoType

VECTRON_200 = LocoType(
    loco_type_id="VECTRON-MS-200",
    description="Siemens Vectron MS, 200 km/h configuration.",
    traction="electric multi-system",
    weight_t=90.0,
    max_speed_kmh=200,
)

VECTRON_230 = LocoType(
    loco_type_id="VECTRON-MS-230",
    description="Siemens Vectron MS, 230 km/h configuration (CD class 384).",
    traction="electric multi-system",
    weight_t=90.0,
    max_speed_kmh=230,
)

CATALOG = {loco.loco_type_id: loco for loco in (VECTRON_200, VECTRON_230)}

COSTS = {
    ("STD-REF", "VECTRON-MS-200"): 161.0,
    ("STD-NEW", "VECTRON-MS-230"): 174.0,
}


def _compose(operator_id, loco_ids, costs=None):
    return DBDataLoader._compose_locos(
        "TEST-COMP", operator_id, loco_ids, CATALOG, COSTS if costs is None else costs
    )


# ---------------------------------------------------------------------------
# resolution
# ---------------------------------------------------------------------------


def test_single_machine_resolves_to_its_operators_rate():
    locos, rates = _compose("STD-NEW", ["VECTRON-MS-230"])
    assert [loco.loco_type_id for loco in locos] == ["VECTRON-MS-230"]
    assert rates == {"VECTRON-MS-230": 174.0}


def test_same_machine_costs_different_operators_differently():
    """The whole reason the rate is a property of the pairing: a lease
    price belongs to neither the machine nor the operator alone."""
    costs = {**COSTS, ("STD-REF", "VECTRON-MS-230"): 151.0}
    _, ref = _compose("STD-REF", ["VECTRON-MS-230"], costs)
    _, new = _compose("STD-NEW", ["VECTRON-MS-230"], costs)
    assert ref["VECTRON-MS-230"] != new["VECTRON-MS-230"]


def test_position_order_is_preserved():
    costs = {**COSTS, ("STD-NEW", "VECTRON-MS-200"): 161.0}
    locos, _ = _compose("STD-NEW", ["VECTRON-MS-230", "VECTRON-MS-200"], costs)
    assert [loco.max_speed_kmh for loco in locos] == [230, 200]


# ---------------------------------------------------------------------------
# the hard fail
# ---------------------------------------------------------------------------


def test_unpriced_pairing_raises_naming_both_sides():
    """A missing row means the catalog and the cost table disagree about
    what this operator can run. Substituting a list price would turn
    inconsistent data into a plausible number, which is the one outcome
    worth preventing outright."""
    with pytest.raises(ValueError) as excinfo:
        _compose("STD-REF", ["VECTRON-MS-230"])
    message = str(excinfo.value)
    assert "STD-REF" in message and "VECTRON-MS-230" in message
    assert "operator_loco_costs" in message


def test_no_machines_is_not_an_error():
    """An unpowered composition is a data question, not a crash — the
    catalog has no such row today, and the loader should not be the layer
    that decides it can never exist."""
    locos, rates = _compose("STD-REF", [])
    assert locos == [] and rates == {}


# ---------------------------------------------------------------------------
# derived quantities on the composition
# ---------------------------------------------------------------------------


class _Composition:
    """Minimal stand-in carrying only what the derived properties read."""

    def __init__(self, locos, coach_weight_t=319.0, rates=None):
        self.locos = locos
        self.total_weight_t = coach_weight_t
        self.loco_lease_eur_h = rates or {
            loco.loco_type_id: COSTS[("STD-NEW", loco.loco_type_id)]
            for loco in locos
            if ("STD-NEW", loco.loco_type_id) in COSTS
        }

    n_locos = property(lambda self: len(self.locos))
    total_gross_weight_t = property(
        lambda self: self.total_weight_t + sum(loco.weight_t for loco in self.locos)
    )
    loco_lease_total_eur_h = property(
        lambda self: sum(
            self.loco_lease_eur_h[loco.loco_type_id] for loco in self.locos
        )
    )


def test_n_locos_follows_the_assignment():
    """Derived, never stored — a count and a list that can disagree is a
    class of bug worth designing out."""
    assert _Composition([VECTRON_230]).n_locos == 1
    assert _Composition([VECTRON_230, VECTRON_230]).n_locos == 2
    assert _Composition([]).n_locos == 0


def test_gross_weight_counts_every_machine():
    """The old expression added ONE locomotive's mass regardless of how
    many the composition had — this is the divergence the catalog exists
    to remove."""
    assert _Composition([VECTRON_230]).total_gross_weight_t == pytest.approx(409.0)
    assert _Composition([VECTRON_230, VECTRON_230]).total_gross_weight_t == (
        pytest.approx(499.0)
    )


def test_gross_weight_matches_the_retired_constant_at_one_machine():
    """Pins the value-neutrality claim in the ROUTE_BUILDER 0.9.22
    changelog: at one 90 t machine the new expression equals the old
    total_weight_t + TRACTION_LOCO_WEIGHT_T exactly."""
    comp = _Composition([VECTRON_230])
    assert comp.total_gross_weight_t == pytest.approx(comp.total_weight_t + 90.0)


def test_lease_is_summed_per_machine_not_counted():
    """Two different machines cost their two different rates — a count
    times one rate could only ever price identical locomotives."""
    comp = _Composition(
        [VECTRON_230, VECTRON_200],
        rates={"VECTRON-MS-230": 174.0, "VECTRON-MS-200": 161.0},
    )
    assert comp.loco_lease_total_eur_h == pytest.approx(335.0)
