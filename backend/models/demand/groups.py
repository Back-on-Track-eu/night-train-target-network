"""
groups.py
=========
The allocation rule of DEMAND 0.1.0 (docs/2026-09-18_manual_demand_guide.md
D14–D19): one departure's demand, split into traveller groups, seated onto
one composition's places by class.

Four rounds release ROUNDS_PCT of every group's demand; in each round the
groups are walked in GROUP_ORDER and each seats what it released: the
RULE_SHARE along its preference list, first class until full then the
next; the rest spread evenly over the group's other listed classes,
first, and whatever of it cannot be seated rejoins the rule-followers of
the same round. A group sits only in the classes it lists; demand no
listed class can seat is not served. The rounds are the point (finding
1): they interleave the groups so the first group cannot take a class
outright before a later group with the same first preference has had a
turn — keep them, do not "optimise" the loop away.

Everything is floats and expected values, so a recalculation is
reproducible. This is a one-to-one port of the sketch's allocate(); the
frontend carries the same function in lib/demandAllocation.ts and the
parity tests pin both to the reference values in
tests/test_83_demand_units.py.

Public interface:
  allocate(places_by_class, demand_by_group) -> Allocation
  split_by_group(total, shares_pct) -> dict[str, float]
"""

from __future__ import annotations

from dataclasses import dataclass, field

from models.demand.model import (
    CLASS_ORDER,
    GROUP_CLASS_PREFERENCES,
    GROUP_ORDER,
    ROUNDS_PCT,
    RULE_SHARE,
)


@dataclass(frozen=True)
class Allocation:
    """One departure seated on one composition. Places, not places per
    year: the caller scales by the departures it wants."""

    by_group_by_class: dict[str, dict[str, float]]
    by_class: dict[str, float]
    served: float
    not_served_by_group: dict[str, float]
    not_served: float
    demand_by_group: dict[str, float] = field(default_factory=dict)

    @property
    def demand(self) -> float:
        return sum(self.demand_by_group.values())


def split_by_group(total: float, shares_pct: dict[str, float]) -> dict[str, float]:
    """Passengers per group: the total split by the shares as entered — in
    floats, never rounded per group (finding 4). A share sum other than
    100 is reflected, not rebalanced (D15)."""
    return {g: total * float(shares_pct.get(g, 0.0)) / 100.0 for g in GROUP_ORDER}


def allocate(
    places_by_class: dict[str, float], demand_by_group: dict[str, float]
) -> Allocation:
    """Seat one departure's group demand onto a train.

    places_by_class: the composition's places per class_main (a class it
    does not carry may be absent or 0). demand_by_group: passengers per
    group for this departure, keyed by GROUP_ORDER."""
    room = {c: float(places_by_class.get(c, 0.0)) for c in CLASS_ORDER}
    demand = {g: float(demand_by_group.get(g, 0.0)) for g in GROUP_ORDER}
    left = dict(demand)
    alloc = {g: {c: 0.0 for c in CLASS_ORDER} for g in GROUP_ORDER}
    # Released but not yet seated, per group, within a round.
    pending = {g: 0.0 for g in GROUP_ORDER}

    def seat(g: str, c: str, amount: float) -> float:
        take = min(amount, room[c])
        if take > 0:
            alloc[g][c] += take
            room[c] -= take
            left[g] -= take
        return take

    for share in ROUNDS_PCT:
        for g in GROUP_ORDER:
            prefs = GROUP_CLASS_PREFERENCES[g]
            others = prefs[1:]
            released = demand[g] * share / 100.0
            # The deviating share first: an even split over the other
            # listed classes; what they cannot seat joins the rule-followers.
            stray = released * (1.0 - RULE_SHARE) if others else 0.0
            pending[g] += released - stray
            for c in others:
                each = stray / len(others)
                pending[g] += each - seat(g, c, each)
            for c in prefs:
                pending[g] -= seat(g, c, pending[g])

    by_class = {c: sum(alloc[g][c] for g in GROUP_ORDER) for c in CLASS_ORDER}
    # Floating-point residue can leave a served group at -0.0.
    not_served = {g: max(0.0, left[g]) for g in GROUP_ORDER}
    return Allocation(
        by_group_by_class=alloc,
        by_class=by_class,
        served=sum(by_class.values()),
        not_served_by_group=not_served,
        not_served=sum(not_served.values()),
        demand_by_group=demand,
    )
