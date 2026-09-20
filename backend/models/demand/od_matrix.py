"""
od_matrix.py
============
The spread of one train's sales over its OD pairs (docs/2026-09-18_manual_
demand_guide.md D25–D30): an origin × destination matrix of shares over
the SELLABLE pairs of a trip, filled from one weight per boarding and
alighting stop, with pinned cells that hold their share while the rest
rescales.

Sellable pair: a stop the trip boards at (BOARDING or BOTH) before a
stop it alights at (ALIGHTING or BOTH). NIGHT stops are on neither side
— demand-quiet by definition; they still dwell and cost, they just sell
no places. This is the rule the stopgap carried since ROUTE_BUILDER
0.9.13, now in one place.

Shares are keyed by (origin_stop_id, destination_stop_id) — stop ids,
never names — and expressed as fractions summing to 1 over the sellable
pairs (pins are posted and echoed in percent). One-to-one ports of the
sketch's odShares(), pinPair() and presetWeights(); the frontend's
lib/odMatrix.ts is the same arithmetic and tests/test_83_demand_units.py
pins both.

Public interface:
  SellablePair(origin_stop_id, destination_stop_id, distance_km)
  sellable_pairs(trip) -> list[SellablePair]           # route order
  boarding_stop_ids(trip), alighting_stop_ids(trip)    # route order
  preset_weights(board_ids, alight_ids, preset) -> (board, alight)
  resolve_weights(stop_ids, weights) -> dict           # defaults filled
  od_shares(pairs, board, alight, pins_pct) -> dict[(o, d), fraction]
  pin_pair(pairs, board, alight, pins_pct, key, value_pct) -> pins_pct
  drop_stale_pins(pins_pct, pairs) -> (kept, dropped)
  average_distance_km(pairs, shares) -> float
"""

from __future__ import annotations

from dataclasses import dataclass

from models.demand.model import (
    DEFAULT_OD_WEIGHT,
    OD_PRESETS,
    OD_WEIGHT_MIN,
    OD_WEIGHT_SPAN,
)
from models.route.trip import StopType, Trip

PairKey = tuple[str, str]


@dataclass(frozen=True)
class SellablePair:
    origin_stop_id: str
    destination_stop_id: str
    distance_km: float

    @property
    def key(self) -> PairKey:
        return (self.origin_stop_id, self.destination_stop_id)


def _cumulative_km(trip: Trip) -> list[float]:
    out = [0.0]
    for segment in trip.segments:
        out.append(out[-1] + segment.distance_m / 1000.0)
    return out


def boarding_stop_ids(trip: Trip) -> list[str]:
    return [
        s.stop_id
        for s in trip.stops
        if s.stop_type in (StopType.BOARDING, StopType.BOTH)
    ]


def alighting_stop_ids(trip: Trip) -> list[str]:
    return [
        s.stop_id
        for s in trip.stops
        if s.stop_type in (StopType.ALIGHTING, StopType.BOTH)
    ]


def sellable_pairs(trip: Trip) -> list[SellablePair]:
    """Every (boarding stop, later alighting stop) of the trip with its
    journey length, in route order — origins outer, destinations inner."""
    stops = trip.stops
    km = _cumulative_km(trip)
    return [
        SellablePair(stops[i].stop_id, stops[j].stop_id, km[j] - km[i])
        for i in range(len(stops))
        for j in range(i + 1, len(stops))
        if stops[i].stop_type in (StopType.BOARDING, StopType.BOTH)
        and stops[j].stop_type in (StopType.ALIGHTING, StopType.BOTH)
    ]


# The four fill presets as position factors (D27): x is the stop's position
# in its list, 0 = first, 1 = last. What the margins show is what fills the
# matrix — there is no separate distance curve.
_PRESET_FACTORS = {
    "even": (lambda x: 1.0, lambda x: 1.0),
    "long": (lambda x: 1.0 - x, lambda x: x),
    "mid": (lambda x: 1.0 - abs(2.0 * x - 1.0), lambda x: 1.0 - abs(2.0 * x - 1.0)),
    "short": (lambda x: x, lambda x: 1.0 - x),
}


def preset_weights(
    board_ids: list[str], alight_ids: list[str], preset: str
) -> tuple[dict[str, float], dict[str, float]]:
    """The stop weights a preset writes: OD_WEIGHT_MIN + OD_WEIGHT_SPAN x f,
    one decimal, over the position factor f of each stop — except `even`,
    which is 1 everywhere rather than the formula's 3.0 (finding 5)."""
    if preset not in OD_PRESETS:
        raise ValueError(
            f"Unknown OD preset '{preset}'. Supported: {list(OD_PRESETS)}."
        )
    board_f, alight_f = _PRESET_FACTORS[preset]

    def pos(ids: list[str], i: int) -> float:
        return i / (len(ids) - 1) if len(ids) > 1 else 0.5

    def weight(f: float) -> float:
        return 1.0 if preset == "even" else round(OD_WEIGHT_MIN + OD_WEIGHT_SPAN * f, 1)

    return (
        {s: weight(board_f(pos(board_ids, i))) for i, s in enumerate(board_ids)},
        {s: weight(alight_f(pos(alight_ids, i))) for i, s in enumerate(alight_ids)},
    )


def resolve_weights(
    stop_ids: list[str], weights: dict[str, float] | None
) -> dict[str, float]:
    """One weight per stop of the list, the request's where it names the
    stop and DEFAULT_OD_WEIGHT elsewhere; weights for stops not on the list
    are dropped (a stop that left the route keeps nothing here — the
    request echo is the place a client reads its weights back from)."""
    given = weights or {}
    return {s: float(given.get(s, DEFAULT_OD_WEIGHT)) for s in stop_ids}


def od_shares(
    pairs: list[SellablePair],
    board: dict[str, float],
    alight: dict[str, float],
    pins_pct: dict[PairKey, float] | None = None,
) -> dict[PairKey, float]:
    """Share of the demand per sellable pair, as fractions summing to 1:
    boarding weight x alighting weight, normalised over the unpinned pairs
    onto whatever the pins leave; a pinned pair keeps its value (D26,
    D28). All weights 0 and no pins → every pair 0."""
    pins = pins_pct or {}
    base = {
        p.key: board.get(p.origin_stop_id, 0.0) * alight.get(p.destination_stop_id, 0.0)
        for p in pairs
    }
    pinned = sum(pins.get(p.key, 0.0) for p in pairs)
    free = sum(base[p.key] for p in pairs if p.key not in pins)
    rest = max(0.0, 100.0 - pinned)
    return {
        p.key: (
            pins[p.key]
            if p.key in pins
            else (base[p.key] / free * rest if free else 0.0)
        )
        / 100.0
        for p in pairs
    }


def pin_pair(
    pairs: list[SellablePair],
    board: dict[str, float],
    alight: dict[str, float],
    pins_pct: dict[PairKey, float],
    key: PairKey,
    value_pct: float,
) -> dict[PairKey, float]:
    """Pin one pair at value_pct; every OTHER pair rescales so the total
    stays 100 — the other pins explicitly, by (100 − v) / (100 − old)
    (finding 6), the unpinned ones by themselves through the remainder.
    Returns the new pin map (percent, two decimals like the sketch)."""
    current = od_shares(pairs, board, alight, pins_pct)
    old = current.get(key, 0.0) * 100.0
    value = min(100.0, max(0.0, float(value_pct)))
    k = (100.0 - value) / (100.0 - old) if old < 100.0 else 0.0
    new_pins = {other: round(v * k, 2) for other, v in pins_pct.items() if other != key}
    new_pins[key] = round(value, 2)
    return new_pins


def drop_stale_pins(
    pins_pct: dict[PairKey, float], pairs: list[SellablePair]
) -> tuple[dict[PairKey, float], list[PairKey]]:
    """Keep the pins whose pair is still sellable on this trip; report the
    rest, so the response can say which pins were dropped (§4)."""
    sellable = {p.key for p in pairs}
    kept = {k: v for k, v in pins_pct.items() if k in sellable}
    dropped = [k for k in pins_pct if k not in sellable]
    return kept, dropped


def average_distance_km(
    pairs: list[SellablePair], shares: dict[PairKey, float]
) -> float:
    """The share-weighted journey length — what the sketch's What-follows
    panel prices a class's revenue on."""
    return sum(p.distance_km * shares.get(p.key, 0.0) for p in pairs)
