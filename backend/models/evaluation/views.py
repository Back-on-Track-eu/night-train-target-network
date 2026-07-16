"""
views.py — Breakdown tree and views over EvaluationResult.

Canonical unit: €/year. Every leaf is annualised at build time.

Conversion rules (calc.py → €/year):
  €/year already   coach_amortisation, financing, fix_overhead,
                   revenue, svc_stockings, var_overhead, ebit_margin
  €/operating-day  cleaning, parking             → × operating_days
  €/segment        all variable + infra costs    → × operating_days
  €/trip-cycle     loco, shunting                → × operating_days

Tree:
  Breakdown
  ├── cost: CostBreakdown
  │   ├── operator: OperatorCost
  │   │   ├── variable: OperatorVariableCost
  │   │   │     driver, crew, coach_maintenance, loco,
  │   │   │     svc_stockings, var_overhead
  │   │   └── fixed: OperatorFixedCost
  │   │         coach_amortisation, financing, fix_overhead,
  │   │         cleaning, shunting
  │   └── infrastructure: InfrastructureCost
  │         tac, energy, station_charge, parking
  ├── revenue: RevenueBreakdown   ticket_revenue
  └── margin:  MarginBreakdown    ebit_margin

driver/crew merge driving (SegmentCost) and dwelling (StopCost).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from models.route.route import Route, TripPair
from models.evaluation.calc import (
    EvaluationResult,
    SegmentPassengerLoad,
    ODSegmentLoad,
    ParkingCost,
    ShuntingCost,
)

# =============================================================================
# BREAKDOWN TREE
# =============================================================================


@dataclass
class OperatorVariableCost:
    """Costs scaling with usage — hours, km, tickets sold."""

    driver_eur: float = 0.0
    crew_eur: float = 0.0
    coach_maintenance_eur: float = 0.0
    loco_eur: float = 0.0
    svc_stockings_eur: float = 0.0
    var_overhead_eur: float = 0.0

    @property
    def total_eur(self) -> float:
        return round(
            self.driver_eur
            + self.crew_eur
            + self.coach_maintenance_eur
            + self.loco_eur
            + self.svc_stockings_eur
            + self.var_overhead_eur,
            2,
        )

    def __iadd__(self, other: OperatorVariableCost) -> OperatorVariableCost:
        self.driver_eur += other.driver_eur
        self.crew_eur += other.crew_eur
        self.coach_maintenance_eur += other.coach_maintenance_eur
        self.loco_eur += other.loco_eur
        self.svc_stockings_eur += other.svc_stockings_eur
        self.var_overhead_eur += other.var_overhead_eur
        return self


@dataclass
class OperatorFixedCost:
    """Costs independent of how much the train runs."""

    coach_amortisation_eur: float = 0.0
    financing_eur: float = 0.0
    fix_overhead_eur: float = 0.0
    cleaning_eur: float = 0.0
    shunting_eur: float = 0.0

    @property
    def total_eur(self) -> float:
        return round(
            self.coach_amortisation_eur
            + self.financing_eur
            + self.fix_overhead_eur
            + self.cleaning_eur
            + self.shunting_eur,
            2,
        )

    def __iadd__(self, other: OperatorFixedCost) -> OperatorFixedCost:
        self.coach_amortisation_eur += other.coach_amortisation_eur
        self.financing_eur += other.financing_eur
        self.fix_overhead_eur += other.fix_overhead_eur
        self.cleaning_eur += other.cleaning_eur
        self.shunting_eur += other.shunting_eur
        return self


@dataclass
class OperatorCost:
    variable: OperatorVariableCost = field(default_factory=OperatorVariableCost)
    fixed: OperatorFixedCost = field(default_factory=OperatorFixedCost)

    @property
    def total_eur(self) -> float:
        return round(self.variable.total_eur + self.fixed.total_eur, 2)

    def __iadd__(self, other: OperatorCost) -> OperatorCost:
        self.variable += other.variable
        self.fixed += other.fixed
        return self


@dataclass
class InfrastructureCost:
    """Costs paid to third-party network and station operators."""

    tac_eur: float = 0.0
    energy_eur: float = 0.0
    station_charge_eur: float = 0.0
    parking_eur: float = 0.0

    @property
    def total_eur(self) -> float:
        return round(
            self.tac_eur + self.energy_eur + self.station_charge_eur + self.parking_eur,
            2,
        )

    def __iadd__(self, other: InfrastructureCost) -> InfrastructureCost:
        self.tac_eur += other.tac_eur
        self.energy_eur += other.energy_eur
        self.station_charge_eur += other.station_charge_eur
        self.parking_eur += other.parking_eur
        return self


@dataclass
class CostBreakdown:
    operator: OperatorCost = field(default_factory=OperatorCost)
    infrastructure: InfrastructureCost = field(default_factory=InfrastructureCost)

    @property
    def total_eur(self) -> float:
        return round(self.operator.total_eur + self.infrastructure.total_eur, 2)

    def __iadd__(self, other: CostBreakdown) -> CostBreakdown:
        self.operator += other.operator
        self.infrastructure += other.infrastructure
        return self


@dataclass
class RevenueBreakdown:
    ticket_revenue_eur: float = 0.0

    @property
    def total_eur(self) -> float:
        return round(self.ticket_revenue_eur, 2)

    def __iadd__(self, other: RevenueBreakdown) -> RevenueBreakdown:
        self.ticket_revenue_eur += other.ticket_revenue_eur
        return self


@dataclass
class MarginBreakdown:
    """Target EBIT carve-out — neither cost nor revenue."""

    ebit_margin_eur: float = 0.0

    @property
    def total_eur(self) -> float:
        return round(self.ebit_margin_eur, 2)

    def __iadd__(self, other: MarginBreakdown) -> MarginBreakdown:
        self.ebit_margin_eur += other.ebit_margin_eur
        return self


@dataclass
class Breakdown:
    """
    Annual receipt for one scope. All leaves are €/year.
    Supports += to accumulate across scopes.
    """

    cost: CostBreakdown = field(default_factory=CostBreakdown)
    revenue: RevenueBreakdown = field(default_factory=RevenueBreakdown)
    margin: MarginBreakdown = field(default_factory=MarginBreakdown)

    @property
    def total_cost_eur(self) -> float:
        return round(self.cost.total_eur, 2)

    @property
    def total_revenue_eur(self) -> float:
        return round(self.revenue.total_eur, 2)

    @property
    def net_eur(self) -> float:
        return round(
            self.total_revenue_eur - self.total_cost_eur - self.margin.total_eur, 2
        )

    def __iadd__(self, other: Breakdown) -> Breakdown:
        self.cost += other.cost
        self.revenue += other.revenue
        self.margin += other.margin
        return self


# =============================================================================
# CONVERSION HELPERS
# =============================================================================


def _ann_op_day(value: float, operating_days: int) -> float:
    """€/operating-day → €/year."""
    return value * operating_days


def _ann_trip(value: float, operating_days: int) -> float:
    """€/segment or €/trip-cycle → €/year (one cycle per operating day)."""
    return value * operating_days


# Every EUR leaf of the Breakdown tree, as attribute paths. Single source
# of truth for _map_breakdown() below — _round_breakdown(), normalise(),
# and _scale_breakdown() all derive from it, so a new leaf only needs to
# be added here (plus the dataclass field and serializer key).
_LEAF_PATHS: tuple[tuple[str, ...], ...] = (
    ("cost", "operator", "variable", "driver_eur"),
    ("cost", "operator", "variable", "crew_eur"),
    ("cost", "operator", "variable", "coach_maintenance_eur"),
    ("cost", "operator", "variable", "loco_eur"),
    ("cost", "operator", "variable", "svc_stockings_eur"),
    ("cost", "operator", "variable", "var_overhead_eur"),
    ("cost", "operator", "fixed", "coach_amortisation_eur"),
    ("cost", "operator", "fixed", "financing_eur"),
    ("cost", "operator", "fixed", "fix_overhead_eur"),
    ("cost", "operator", "fixed", "cleaning_eur"),
    ("cost", "operator", "fixed", "shunting_eur"),
    ("cost", "infrastructure", "tac_eur"),
    ("cost", "infrastructure", "energy_eur"),
    ("cost", "infrastructure", "station_charge_eur"),
    ("cost", "infrastructure", "parking_eur"),
    ("revenue", "ticket_revenue_eur"),
    ("margin", "ebit_margin_eur"),
)


def _map_breakdown(b: Breakdown, fn) -> Breakdown:
    """Apply fn to every EUR leaf of b, returning a new Breakdown."""
    r = Breakdown()
    for path in _LEAF_PATHS:
        src, dst = b, r
        for attr in path[:-1]:
            src = getattr(src, attr)
            dst = getattr(dst, attr)
        setattr(dst, path[-1], fn(getattr(src, path[-1])))
    return r


def _round_breakdown(b: Breakdown) -> Breakdown:
    """
    Round every EUR leaf of a Breakdown to 2 decimal places, returning a new
    Breakdown. Applied at the end of every builder and normaliser in this
    file so serialize.py never needs its own number formatting — by the
    time a Breakdown reaches breakdown_to_dict(), every value (leaves and
    the total_eur/net_eur properties above) is already exactly 2dp.
    """
    return _map_breakdown(b, lambda v: round(v, 2))


def _scale_breakdown(b: Breakdown, factor: float) -> Breakdown:
    """Multiply every EUR leaf by factor, returning a new (unrounded)
    Breakdown. Used for share-based slicing of an already-built cell."""
    return _map_breakdown(b, lambda v: v * factor)


# =============================================================================
# PRE-COMPUTATION
# =============================================================================


def _pair_fleet_share(pair: TripPair, fc, route: Route) -> float:
    """
    This pair's share of one CompositionFleetCost. calc.py sums
    coaches_required across all pairs sharing a comp_id (one shared fleet),
    so a pair-filtered view must scale the fleet cost down to the pair's
    own coach count — otherwise two pairs sharing a composition would each
    carry the combined fleet cost and per-pair cells would sum to more
    than the route total.
    """
    if fc.coaches_required <= 0:
        return 0.0
    n_pair = pair.composition_count(route.schedule).get(fc.comp_id, 0.0)
    return n_pair / fc.coaches_required


# =============================================================================
# LAYER 1 — WHOLE ROUTE / PER TRIP PAIR
# =============================================================================


def build_breakdown(
    route: Route,
    result: EvaluationResult,
    trip_pair: TripPair | None = None,
) -> Breakdown:
    """
    Build a canonical annual Breakdown for the whole route or one TripPair.

    trip_pair=None  → all segments/stops/OD pairs; full route-level costs.
    trip_pair=pair  → filtered to that pair's trip_ids and composition.
                      Parking included for stops in this pair's trip_ids.
    """
    b = Breakdown()
    operating_days = route.schedule.operating_days_per_year
    trip_ids = (
        {trip_pair.outbound.trip_id, trip_pair.return_trip.trip_id}
        if trip_pair is not None
        else None
    )

    for sc in result.segment_costs:
        if trip_ids is not None and sc.trip_id not in trip_ids:
            continue
        b.cost.operator.variable.driver_eur += _ann_trip(sc.driver_eur, operating_days)
        b.cost.operator.variable.crew_eur += _ann_trip(sc.crew_eur, operating_days)
        b.cost.operator.variable.coach_maintenance_eur += _ann_trip(
            sc.coach_maintenance_eur, operating_days
        )
        b.cost.infrastructure.tac_eur += _ann_trip(sc.tac_eur, operating_days)
        b.cost.infrastructure.energy_eur += _ann_trip(sc.energy_eur, operating_days)

    for stc in result.stop_costs:
        if trip_ids is not None and stc.trip_id not in trip_ids:
            continue
        b.cost.infrastructure.station_charge_eur += _ann_trip(
            stc.station_charge_eur, operating_days
        )
        b.cost.operator.variable.driver_eur += _ann_trip(
            stc.dwell_driver_eur, operating_days
        )
        b.cost.operator.variable.crew_eur += _ann_trip(
            stc.dwell_crew_eur, operating_days
        )

    for fc in result.composition_fleet_costs:
        if trip_pair is not None and fc.comp_id != trip_pair.composition.comp_id:
            continue
        # Pair filter → only this pair's coach share of the (possibly
        # shared) fleet; whole route → the full fleet cost once.
        fleet_share = (
            _pair_fleet_share(trip_pair, fc, route) if trip_pair is not None else 1.0
        )
        b.cost.operator.fixed.coach_amortisation_eur += (
            fc.coach_amortisation_eur * fleet_share
        )  # already €/year
        b.cost.operator.fixed.financing_eur += (
            fc.financing_eur * fleet_share
        )  # already €/year
        b.cost.operator.fixed.fix_overhead_eur += (
            fc.fix_overhead_eur * fleet_share
        )  # already €/year
        b.cost.operator.fixed.cleaning_eur += (
            _ann_op_day(fc.cleaning_eur, operating_days) * fleet_share
        )

    composition = (
        trip_pair.composition
        if trip_pair is not None
        else route.trip_pairs[0].composition
    )

    loco_min = (
        trip_pair.loco_propulsion_min
        if trip_pair is not None
        else route.loco_propulsion_min
    )
    b.cost.operator.variable.loco_eur = _ann_trip(
        composition.loco_full_service_lease_eur_h * loco_min / 60.0, operating_days
    )

    sc_trip_ids = trip_ids  # None = all, set = filtered to pair
    for sc in result.shunting_costs:
        if sc_trip_ids is not None and sc.trip_id not in sc_trip_ids:
            continue
        b.cost.operator.fixed.shunting_eur += _ann_trip(sc.shunting_eur, operating_days)

    # Parking applies per pair too, not only route-wide: a ParkingCost
    # carries the trip_ids whose formation parks there, so a pair filter
    # keeps exactly its own parkings (a stabled formation belongs to one
    # pair). Start-stop and "all trips" selections now cost the same
    # parking, as they should.
    for pc in result.parking_costs:
        if trip_ids is not None and not trip_ids.intersection(pc.trip_ids):
            continue
        b.cost.infrastructure.parking_eur += _ann_op_day(pc.parking_eur, operating_days)

    for r in result.od_pair_revenues:
        if trip_ids is not None and r.trip_id not in trip_ids:
            continue
        b.revenue.ticket_revenue_eur += r.revenue_eur

    for c in result.od_pair_costs:
        if trip_ids is not None and c.trip_id not in trip_ids:
            continue
        b.cost.operator.variable.svc_stockings_eur += c.svc_stockings_eur
        b.cost.operator.variable.var_overhead_eur += c.var_overhead_eur

    for m in result.od_pair_margins:
        if trip_ids is not None and m.trip_id not in trip_ids:
            continue
        b.margin.ebit_margin_eur += m.ebit_margin_eur

    return _round_breakdown(b)


def build_breakdown_per_trip_pair(
    route: Route,
    result: EvaluationResult,
) -> dict[str, Breakdown]:
    """
    dict keyed by outbound trip_id, plus "all" for the whole route.
    """
    result_dict: dict[str, Breakdown] = {"all": build_breakdown(route, result)}
    for pair in route.trip_pairs:
        result_dict[pair.outbound.trip_id] = build_breakdown(
            route, result, trip_pair=pair
        )
    return result_dict


# =============================================================================
# LAYER 2A — PER TRIP PAIR × COUNTRY
# =============================================================================


def build_breakdown_per_trip_pair_per_country(
    route: Route,
    result: EvaluationResult,
) -> dict[tuple[str, str], Breakdown]:
    """
    Matrix keyed by (pair_key, country_code), with "all" as wildcard in either position.

    Allocation rules:
      driver, crew, loco, cleaning   → country_time_shares
      coach_maintenance,
      coach_amortisation, financing,
      fix_overhead                   → country_distance_shares
      shunting                       → 100% to terminal stop's country
      tac, energy                    → directly from SegmentCost
      station_charge                 → 100% to StopCost.country_code
      parking                        → 100% to Parking.country_code
      svc_stockings, var_overhead,
      revenue, margin                → OD place-km share per country
                                       (from result.segment_passenger_loads)
    """
    operating_days = route.schedule.operating_days_per_year
    segment_loads = result.segment_passenger_loads

    all_countries = route.countries

    matrix: dict[tuple[str, str], Breakdown] = {}
    sc_by_key = {(sc.trip_id, sc.segment_index): sc for sc in result.segment_costs}

    for pair in route.trip_pairs:
        pair_key = pair.outbound.trip_id
        trip_ids = {pair.outbound.trip_id, pair.return_trip.trip_id}
        composition = pair.composition

        # Segment loads for this pair — primary source for all segment-level data
        pair_loads = [sl for sl in segment_loads.values() if sl.trip_id in trip_ids]
        pair_total_km = sum(sl.distance_km for sl in pair_loads)
        pair_total_h = sum(sl.driving_time_min / 60.0 for sl in pair_loads)

        # Shunting locations for this pair — filter route's stored list by pair's stop ids
        pair_shunting_costs = [
            sc for sc in result.shunting_costs if sc.trip_id in trip_ids
        ]

        # Pre-aggregate OD weighted place-km per country from segment passenger loads.
        # Weighted by class density so Sleeper/Couchette carry higher share than Seat.
        od_country_pkm: dict[tuple, dict[str, float]] = {}
        od_total_pkm: dict[tuple, float] = {}
        for sl in pair_loads:
            for ol in sl.od_loads:
                od_key = (
                    ol.od_trip_id,
                    ol.origin_stop_id,
                    ol.destination_stop_id,
                    ol.class_main,
                )
                od_total_pkm[od_key] = (
                    od_total_pkm.get(od_key, 0.0) + ol.weighted_place_km
                )
                cc_map = od_country_pkm.setdefault(od_key, {})
                for cc, v in ol.weighted_place_km_by_country.items():
                    cc_map[cc] = cc_map.get(cc, 0.0) + v

        for country in all_countries:
            b = Breakdown()

            # Country totals for fixed cost share denominators
            country_km = sum(
                sl.distance_km * sl.country_distance_shares.get(country, 0.0)
                for sl in pair_loads
            )
            country_h = sum(
                sl.driving_time_min / 60.0 * sl.country_time_shares.get(country, 0.0)
                for sl in pair_loads
            )
            d_share = country_km / pair_total_km if pair_total_km > 0 else 0.0
            t_share = country_h / pair_total_h if pair_total_h > 0 else 0.0

            # Segment-level variable costs — read from SegmentCost (monetary values)
            # shares from SegmentPassengerLoad (physics, same data, already on the load)
            for sl in pair_loads:
                sc = sc_by_key.get((sl.trip_id, sl.segment_index))
                if sc is None:
                    continue
                t = sl.country_time_shares.get(country, 0.0)
                d = sl.country_distance_shares.get(country, 0.0)
                b.cost.operator.variable.driver_eur += _ann_trip(
                    sc.driver_eur * t, operating_days
                )
                b.cost.operator.variable.crew_eur += _ann_trip(
                    sc.crew_eur * t, operating_days
                )
                b.cost.operator.variable.coach_maintenance_eur += _ann_trip(
                    sc.coach_maintenance_eur * d, operating_days
                )
                b.cost.infrastructure.tac_eur += _ann_trip(
                    sc.tac_eur * d, operating_days
                )
                b.cost.infrastructure.energy_eur += _ann_trip(
                    sc.energy_eur * d, operating_days
                )

            # Stop costs — 100% to stop's country
            for stc in result.stop_costs:
                if stc.trip_id not in trip_ids or stc.country_code != country:
                    continue
                b.cost.infrastructure.station_charge_eur += _ann_trip(
                    stc.station_charge_eur, operating_days
                )
                b.cost.operator.variable.driver_eur += _ann_trip(
                    stc.dwell_driver_eur, operating_days
                )
                b.cost.operator.variable.crew_eur += _ann_trip(
                    stc.dwell_crew_eur, operating_days
                )

            # Fixed fleet costs — pair's fleet share, split by country
            # distance/time share
            for fc in result.composition_fleet_costs:
                if fc.comp_id != composition.comp_id:
                    continue
                fleet_share = _pair_fleet_share(pair, fc, route)
                b.cost.operator.fixed.coach_amortisation_eur += (
                    fc.coach_amortisation_eur * fleet_share * d_share
                )
                b.cost.operator.fixed.financing_eur += (
                    fc.financing_eur * fleet_share * d_share
                )
                b.cost.operator.fixed.fix_overhead_eur += (
                    fc.fix_overhead_eur * fleet_share * d_share
                )
                b.cost.operator.fixed.cleaning_eur += (
                    _ann_op_day(fc.cleaning_eur, operating_days) * fleet_share * t_share
                )

            # Loco — time-based
            loco_eur = (
                composition.loco_full_service_lease_eur_h
                * pair.loco_propulsion_min
                / 60.0
            )
            b.cost.operator.variable.loco_eur = _ann_trip(
                loco_eur * t_share, operating_days
            )

            # Shunting — sum ShuntingCost for events in this country
            b.cost.operator.fixed.shunting_eur = sum(
                _ann_trip(sc.shunting_eur, operating_days)
                for sc in pair_shunting_costs
                if sc.country_code == country
            )

            # Parking — this pair's ParkingCosts (matched via trip_ids)
            # in this country; without the pair filter every pair row would
            # carry the full country parking and ("all", country) would
            # multiply-count it.
            b.cost.infrastructure.parking_eur = sum(
                _ann_op_day(pc.parking_eur, operating_days)
                for pc in result.parking_costs
                if pc.country_code == country and trip_ids.intersection(pc.trip_ids)
            )

            # OD-based: revenue, margin, svc_stockings, var_overhead
            for od_r, od_c, od_m in zip(
                result.od_pair_revenues, result.od_pair_costs, result.od_pair_margins
            ):
                if od_r.trip_id not in trip_ids:
                    continue
                od_key = (
                    od_r.trip_id,
                    od_r.origin_stop_id,
                    od_r.destination_stop_id,
                    od_r.class_main,
                )
                total_pkm = od_total_pkm.get(od_key, 0.0)
                if total_pkm == 0:
                    continue
                od_share = od_country_pkm.get(od_key, {}).get(country, 0.0) / total_pkm
                if od_share == 0.0:
                    continue
                b.revenue.ticket_revenue_eur += od_r.revenue_eur * od_share
                b.cost.operator.variable.svc_stockings_eur += (
                    od_c.svc_stockings_eur * od_share
                )
                b.cost.operator.variable.var_overhead_eur += (
                    od_c.var_overhead_eur * od_share
                )
                b.margin.ebit_margin_eur += od_m.ebit_margin_eur * od_share

            matrix[(pair_key, country)] = b

        matrix[(pair_key, "all")] = build_breakdown(route, result, trip_pair=pair)

    # ("all", country) — sum across all pairs
    for country in all_countries:
        b_all = Breakdown()
        for pair in route.trip_pairs:
            if (pair.outbound.trip_id, country) in matrix:
                b_all += matrix[(pair.outbound.trip_id, country)]
        matrix[("all", country)] = b_all

    matrix[("all", "all")] = build_breakdown(route, result)
    return {k: _round_breakdown(v) for k, v in matrix.items()}


# =============================================================================
# LAYER 2B — PER TRIP PAIR × OD PAIR
# =============================================================================


def build_breakdown_per_trip_pair_per_od(
    route: Route,
    result: EvaluationResult,
    segment_loads: dict[tuple[str, int], SegmentPassengerLoad] | None = None,
) -> dict[tuple[str, str], Breakdown]:
    """
    Matrix keyed by (pair_key, od_key), with "all" as wildcard.

    pair_key: outbound trip_id, or "all".
    od_key:   "{origin_stop_id}__{destination_stop_id}__{class_main}", or "all".
              No trip_id in the key — Copenhagen→Munich aggregates across
              both trip pairs in a Y-shape if both are selected.

    Keys produced:
      ("all", "all")          — whole route, all OD pairs
      ("all", od_key)         — all pairs, one OD pair aggregated
      (pair_key, "all")       — one pair, all OD pairs
      (pair_key, od_key)      — one pair, one OD pair

    Cost allocation per OD pair:
      coach_maintenance, tac, energy     → place_km share per segment
                                           (od_load.place_km / seg_load.total_place_km)
      driver, crew                       → place_hours share per segment
                                           (od_load.place_hours / seg_load.total_place_hours)
      loco, cleaning                     → od weighted place-hours share of the
                                           whole pair (sums to 1 across both
                                           directions — loco/cleaning are billed
                                           once per pair cycle, not per trip)
      coach_amortisation, financing,
      fix_overhead                        → pair's fleet share (see
                                           _pair_fleet_share) × od weighted
                                           place-km share of the whole pair
      station_charge, dwell_driver,
      dwell_crew                          → places_sold share at each stop
                                           (od pairs boarding OR alighting at
                                           that stop; if none, the od pairs
                                           riding through it, so no stop's
                                           cost is dropped)
      shunting, parking                   → revenue share
                                           (od_revenue / total_trip_revenue);
                                           parking filtered to this pair's trip_ids
      svc_stockings, var_overhead,
      revenue, margin                     → direct (already per OD pair in result)
    """
    operating_days = route.schedule.operating_days_per_year

    if segment_loads is None:
        segment_loads = result.segment_passenger_loads

    def od_key(t_id: str, origin: str, destination: str, class_main: str) -> str:
        return f"{origin}__{destination}__{class_main}"

    matrix: dict[tuple[str, str], Breakdown] = {}

    for pair in route.trip_pairs:
        pair_key = pair.outbound.trip_id
        trip_ids = {pair.outbound.trip_id, pair.return_trip.trip_id}
        composition = pair.composition

        pair_loads = [sl for sl in segment_loads.values() if sl.trip_id in trip_ids]

        # Pre-compute per-OD totals across all segments (keyed by (trip_id, od_key))
        # We compute internally per trip_id then aggregate into od_key for output
        od_place_km: dict[
            tuple, float
        ] = {}  # (trip_id, od_key) → total weighted_place_km
        od_place_hours: dict[
            tuple, float
        ] = {}  # (trip_id, od_key) → total weighted_place_hours

        for sl in pair_loads:
            for ol in sl.od_loads:
                k = (
                    ol.od_trip_id,
                    od_key(
                        ol.od_trip_id,
                        ol.origin_stop_id,
                        ol.destination_stop_id,
                        ol.class_main,
                    ),
                )
                od_place_km[k] = od_place_km.get(k, 0.0) + ol.weighted_place_km
                od_place_hours[k] = od_place_hours.get(k, 0.0) + ol.weighted_place_hours

        # Revenue per (trip_id, od_key) for revenue-proportional allocation
        od_revenue: dict[tuple, float] = {}
        for r in result.od_pair_revenues:
            if r.trip_id not in trip_ids:
                continue
            k = (
                r.trip_id,
                od_key(
                    r.trip_id, r.origin_stop_id, r.destination_stop_id, r.class_main
                ),
            )
            od_revenue[k] = od_revenue.get(k, 0.0) + r.revenue_eur
        total_trip_revenue = sum(od_revenue.values())

        # Stop index lookup for this pair's trips
        stop_indices: dict[str, dict[str, int]] = {
            trip.trip_id: {s.stop_id: i for i, s in enumerate(trip.stops)}
            for trip in pair.trips
        }

        # Parking — this pair's parkings only (matched via trip_ids),
        # revenue-proportional share across OD pairs
        parking_total = sum(
            _ann_op_day(pc.parking_eur, operating_days)
            for pc in result.parking_costs
            if trip_ids.intersection(pc.trip_ids)
        )

        # Shunting (pair-level, revenue-proportional)
        pair_shunting_costs = [
            sc for sc in result.shunting_costs if sc.trip_id in trip_ids
        ]
        shunting_total = sum(
            _ann_trip(sc.shunting_eur, operating_days) for sc in pair_shunting_costs
        )

        # Segment-level variable costs — O(1) lookup via sc_by_key
        sc_by_key = {(sc.trip_id, sc.segment_index): sc for sc in result.segment_costs}
        internal: dict[tuple, Breakdown] = {}
        for sl in pair_loads:
            sc = sc_by_key.get((sl.trip_id, sl.segment_index))
            if sc is None:
                continue
            seg_total_pkm = sl.total_weighted_place_km
            seg_total_ph = sl.total_weighted_place_hours
            for ol in sl.od_loads:
                k = (
                    ol.od_trip_id,
                    od_key(
                        ol.od_trip_id,
                        ol.origin_stop_id,
                        ol.destination_stop_id,
                        ol.class_main,
                    ),
                )
                if k not in internal:
                    internal[k] = Breakdown()
                b = internal[k]
                pkm_share = (
                    ol.weighted_place_km / seg_total_pkm if seg_total_pkm > 0 else 0.0
                )
                ph_share = (
                    ol.weighted_place_hours / seg_total_ph if seg_total_ph > 0 else 0.0
                )
                b.cost.operator.variable.coach_maintenance_eur += _ann_trip(
                    sc.coach_maintenance_eur * pkm_share, operating_days
                )
                b.cost.operator.variable.driver_eur += _ann_trip(
                    sc.driver_eur * ph_share, operating_days
                )
                b.cost.operator.variable.crew_eur += _ann_trip(
                    sc.crew_eur * ph_share, operating_days
                )
                b.cost.infrastructure.tac_eur += _ann_trip(
                    sc.tac_eur * pkm_share, operating_days
                )
                b.cost.infrastructure.energy_eur += _ann_trip(
                    sc.energy_eur * pkm_share, operating_days
                )

        # Fixed fleet + loco + dwell crew + station charge + shunting + parking
        #
        # Pair-wide denominators: weighted place-km/-hours summed over BOTH
        # directions, so each share family sums to exactly 1.0 across all OD
        # cells of the pair — the previous per-trip denominators (and the raw
        # od-distance / pair-distance ratio for fixed costs) made OD cells
        # sum to roughly 2× (loco, cleaning) or arbitrarily more (fleet)
        # than the pair total.
        total_pair_wpkm = sum(od_place_km.values())
        total_pair_wph = sum(od_place_hours.values())

        for (trip_id, odk), b in internal.items():
            k = (trip_id, odk)
            wpkm_share = (
                od_place_km.get(k, 0.0) / total_pair_wpkm
                if total_pair_wpkm > 0
                else 0.0
            )
            wph_share = (
                od_place_hours.get(k, 0.0) / total_pair_wph
                if total_pair_wph > 0
                else 0.0
            )

            # Fixed fleet — pair's fleet share × od weighted place-km share
            for fc in result.composition_fleet_costs:
                if fc.comp_id != composition.comp_id:
                    continue
                fleet_share = _pair_fleet_share(pair, fc, route)
                b.cost.operator.fixed.coach_amortisation_eur += (
                    fc.coach_amortisation_eur * fleet_share * wpkm_share
                )
                b.cost.operator.fixed.financing_eur += (
                    fc.financing_eur * fleet_share * wpkm_share
                )
                b.cost.operator.fixed.fix_overhead_eur += (
                    fc.fix_overhead_eur * fleet_share * wpkm_share
                )
                b.cost.operator.fixed.cleaning_eur += (
                    _ann_op_day(fc.cleaning_eur, operating_days)
                    * fleet_share
                    * wph_share
                )

            # Loco — billed once per pair cycle, allocated by weighted
            # place-hours share
            loco_eur = (
                composition.loco_full_service_lease_eur_h
                * pair.loco_propulsion_min
                / 60.0
            )
            b.cost.operator.variable.loco_eur += _ann_trip(
                loco_eur * wph_share, operating_days
            )

            # Revenue share for shunting + parking
            rev = od_revenue.get(k, 0.0)
            rev_share = rev / total_trip_revenue if total_trip_revenue > 0 else 0.0
            b.cost.operator.fixed.shunting_eur += shunting_total * rev_share
            b.cost.infrastructure.parking_eur += parking_total * rev_share

        # Stop costs — station charge + dwell crew, allocated by places_sold at stop
        for stc in result.stop_costs:
            if stc.trip_id not in trip_ids:
                continue
            trip_stop_idx = stop_indices.get(stc.trip_id, {})
            stop_idx = trip_stop_idx.get(stc.stop_id)
            if stop_idx is None:
                continue

            # OD pairs boarding or alighting at this stop carry its cost;
            # if none do (an intermediate stop everyone rides through),
            # fall back to the ODs on board during the dwell — otherwise
            # the stop's cost would be dropped and OD cells would no
            # longer sum to the pair total.
            touching: list[tuple[tuple, int]] = []  # (k, places_sold)
            on_board: list[tuple[tuple, int]] = []
            for od in pair.od_pairs:
                if od.trip_id != stc.trip_id:
                    continue
                odk = od_key(
                    od.trip_id, od.origin_stop_id, od.destination_stop_id, od.class_main
                )
                k = (od.trip_id, odk)
                origin_idx = trip_stop_idx.get(od.origin_stop_id)
                dest_idx = trip_stop_idx.get(od.destination_stop_id)
                if origin_idx is None or dest_idx is None:
                    continue
                if origin_idx == stop_idx or dest_idx == stop_idx:
                    touching.append((k, od.places_sold))
                elif origin_idx < stop_idx < dest_idx:
                    on_board.append((k, od.places_sold))
            if not touching:
                touching = on_board

            total_places_at_stop = sum(ps for _, ps in touching)
            if total_places_at_stop == 0:
                continue

            for k, places in touching:
                if k not in internal:
                    continue
                share = places / total_places_at_stop
                b = internal[k]
                b.cost.infrastructure.station_charge_eur += _ann_trip(
                    stc.station_charge_eur * share, operating_days
                )
                b.cost.operator.variable.driver_eur += _ann_trip(
                    stc.dwell_driver_eur * share, operating_days
                )
                b.cost.operator.variable.crew_eur += _ann_trip(
                    stc.dwell_crew_eur * share, operating_days
                )

        # OD pair revenue / cost / margin — direct from result
        for od_r, od_c, od_m in zip(
            result.od_pair_revenues, result.od_pair_costs, result.od_pair_margins
        ):
            if od_r.trip_id not in trip_ids:
                continue
            odk = od_key(
                od_r.trip_id,
                od_r.origin_stop_id,
                od_r.destination_stop_id,
                od_r.class_main,
            )
            k = (od_r.trip_id, odk)
            if k not in internal:
                internal[k] = Breakdown()
            b = internal[k]
            b.revenue.ticket_revenue_eur += od_r.revenue_eur
            b.cost.operator.variable.svc_stockings_eur += od_c.svc_stockings_eur
            b.cost.operator.variable.var_overhead_eur += od_c.var_overhead_eur
            b.margin.ebit_margin_eur += od_m.ebit_margin_eur

        # Aggregate internal (trip_id, od_key) → output (pair_key, od_key)
        # OD pairs with same od_key but different trip_ids sum together
        for (trip_id, odk), b in internal.items():
            cell_key = (pair_key, odk)
            if cell_key not in matrix:
                matrix[cell_key] = Breakdown()
            matrix[cell_key] += b

        # (pair_key, "all") — all OD pairs for this pair
        matrix[(pair_key, "all")] = build_breakdown(route, result, trip_pair=pair)

    # ("all", od_key) — aggregate this OD pair across all pairs
    all_od_keys: set[str] = {odk for pk, odk in matrix if pk != "all" and odk != "all"}
    for odk in all_od_keys:
        b_all = Breakdown()
        for pair in route.trip_pairs:
            cell = matrix.get((pair.outbound.trip_id, odk))
            if cell:
                b_all += cell
        matrix[("all", odk)] = b_all

    # ("all", "all")
    matrix[("all", "all")] = build_breakdown(route, result)
    return {k: _round_breakdown(v) for k, v in matrix.items()}


# =============================================================================
# LAYER 2B2 — PER TRIP PAIR × ROUTE SECTION
# =============================================================================


@dataclass(frozen=True)
class NormalisationScope:
    """
    Annual physical denominators for one view cell, used by the per-unit
    normalisers when a cell covers less than a whole trip pair (route
    sections). All values are per YEAR — same basis as the Breakdown's
    €/year leaves.
    """

    train_km: float  # annual train-km in scope
    available_place_km: float  # annual capacity place-km in scope
    sold_place_km: float  # annual sold place-km in scope

    def __add__(self, other: "NormalisationScope") -> "NormalisationScope":
        return NormalisationScope(
            train_km=self.train_km + other.train_km,
            available_place_km=self.available_place_km + other.available_place_km,
            sold_place_km=self.sold_place_km + other.sold_place_km,
        )


def build_breakdown_per_trip_pair_per_section(
    route: Route,
    result: EvaluationResult,
) -> tuple[dict[tuple[str, str], Breakdown], dict[tuple[str, str], NormalisationScope]]:
    """
    Matrix keyed by (pair_key, section_key), with "all" as wildcard, plus a
    parallel dict of per-cell NormalisationScope (annual train-km /
    available-place-km / sold-place-km of the section) so the per-unit
    normalisers can divide by the section's own physics rather than the
    whole pair's.

    pair_key:    outbound trip_id, or "all".
    section_key: "{origin_stop_id}__{destination_stop_id}__{class_main}" with
                 class_main = "all" for the class-independent section cell,
                 or one class_main per class with passengers in the section.
                 Directional: Hamburg→Berlin covers the trip(s) running in
                 that direction; the opposite direction is its own key.

    Semantics — a section is a physical piece of the trip, NOT a ticket
    relation (that's per_trip_pair_per_od): selecting [Hamburg, Berlin] on a
    [Copenhagen, Hamburg, Berlin, Munich] trip means every cost occurring
    between Hamburg and Berlin, and a km-proportional share of the revenue
    of EVERYONE on board there — a Copenhagen→Munich passenger contributes
    exactly the fraction of their fare matching the km they ride within the
    section. Sections overlap by construction (the full-trip section IS the
    whole trip), so section cells deliberately do NOT sum to the pair total.

    Allocation, "__all" cell:
      driver, crew, coach_maintenance,
      tac, energy                        → 100% of segments inside the section
      station_charge, dwell driver/crew  → 100% of stop calls origin..destination
                                           (both boundary stops included)
      loco                               → direct: lease rate × section operating
                                           minutes (segment total time + dwell)
      coach_amortisation, financing,
      fix_overhead                        → pair fleet share × section-km /
                                           pair-km (distance basis)
      cleaning                            → pair fleet share × section driving
                                           hours / pair driving hours (time basis)
      shunting, parking                   → pair totals (parking pair-filtered)
                                           × section revenue / pair revenue
      revenue, svc_stockings,
      var_overhead, margin                → Σ over on-board ticket groups of
                                           value × overlap_km / ride_km

    Class cells ("__{class_main}"): the passenger-side leaves of that class
    directly, plus every train-level leaf of the "__all" cell scaled by the
    class's density-weighted place-km share within the section — class cells
    therefore sum exactly to the "__all" cell.
    """
    operating_days = route.schedule.operating_days_per_year
    segment_loads = result.segment_passenger_loads
    sc_by_key = {(sc.trip_id, sc.segment_index): sc for sc in result.segment_costs}
    stc_by_key = {(stc.trip_id, stc.stop_id): stc for stc in result.stop_costs}
    rev_by_key = {
        (r.trip_id, r.origin_stop_id, r.destination_stop_id, r.class_main): r
        for r in result.od_pair_revenues
    }
    cost_by_key = {
        (c.trip_id, c.origin_stop_id, c.destination_stop_id, c.class_main): c
        for c in result.od_pair_costs
    }
    margin_by_key = {
        (m.trip_id, m.origin_stop_id, m.destination_stop_id, m.class_main): m
        for m in result.od_pair_margins
    }

    matrix: dict[tuple[str, str], Breakdown] = {}
    scopes: dict[tuple[str, str], NormalisationScope] = {}

    for pair in route.trip_pairs:
        pair_key = pair.outbound.trip_id
        trip_ids = {pair.outbound.trip_id, pair.return_trip.trip_id}
        composition = pair.composition
        density_by_class = composition.density_by_class
        total_places = sum(composition.places_by_class.values())

        pair_loads = [sl for sl in segment_loads.values() if sl.trip_id in trip_ids]
        pair_total_km = sum(sl.distance_km for sl in pair_loads)
        pair_total_h = sum(sl.driving_time_min / 60.0 for sl in pair_loads)
        pair_total_revenue = sum(
            r.revenue_eur for r in result.od_pair_revenues if r.trip_id in trip_ids
        )
        pair_shunting_total = sum(
            _ann_trip(sc.shunting_eur, operating_days)
            for sc in result.shunting_costs
            if sc.trip_id in trip_ids
        )
        pair_parking_total = sum(
            _ann_op_day(pc.parking_eur, operating_days)
            for pc in result.parking_costs
            if trip_ids.intersection(pc.trip_ids)
        )

        for trip in pair.trips:
            trip_id = trip.trip_id
            stop_idx = {s.stop_id: i for i, s in enumerate(trip.stops)}
            seg_km = [seg.distance_m / 1000.0 for seg in trip.segments]
            # Cumulative km up to each stop index — O(1) range distances
            cum_km = [0.0]
            for km in seg_km:
                cum_km.append(cum_km[-1] + km)

            # Distinct physical sections on this trip = distinct (origin,
            # destination) among its OD pairs, regardless of class
            trip_ods = [od for od in pair.od_pairs if od.trip_id == trip_id]
            sections = {
                (od.origin_stop_id, od.destination_stop_id)
                for od in trip_ods
                if od.origin_stop_id in stop_idx
                and od.destination_stop_id in stop_idx
                and stop_idx[od.origin_stop_id] < stop_idx[od.destination_stop_id]
            }

            for origin_id, dest_id in sections:
                oi, di = stop_idx[origin_id], stop_idx[dest_id]
                section_km = cum_km[di] - cum_km[oi]

                b = Breakdown()

                # --- Direct segment costs: 100% of segments inside the section
                section_drive_h = 0.0
                for i in range(oi, di):
                    sc = sc_by_key.get((trip_id, i))
                    if sc is None:
                        continue
                    section_drive_h += sc.driving_time_min / 60.0
                    b.cost.operator.variable.driver_eur += _ann_trip(
                        sc.driver_eur, operating_days
                    )
                    b.cost.operator.variable.crew_eur += _ann_trip(
                        sc.crew_eur, operating_days
                    )
                    b.cost.operator.variable.coach_maintenance_eur += _ann_trip(
                        sc.coach_maintenance_eur, operating_days
                    )
                    b.cost.infrastructure.tac_eur += _ann_trip(
                        sc.tac_eur, operating_days
                    )
                    b.cost.infrastructure.energy_eur += _ann_trip(
                        sc.energy_eur, operating_days
                    )

                # --- Direct stop costs: every stop call origin..destination
                section_dwell_min = 0
                for i in range(oi, di + 1):
                    stop = trip.stops[i]
                    if stop.dwell_time_min is not None:
                        section_dwell_min += stop.dwell_time_min
                    stc = stc_by_key.get((trip_id, stop.stop_id))
                    if stc is None:
                        continue
                    b.cost.infrastructure.station_charge_eur += _ann_trip(
                        stc.station_charge_eur, operating_days
                    )
                    b.cost.operator.variable.driver_eur += _ann_trip(
                        stc.dwell_driver_eur, operating_days
                    )
                    b.cost.operator.variable.crew_eur += _ann_trip(
                        stc.dwell_crew_eur, operating_days
                    )

                # --- Loco: direct — lease rate × the section's own operating
                # minutes (segment total time + dwell), mirroring
                # TripPair.loco_propulsion_min restricted to the section
                section_loco_min = (
                    sum(seg.total_time_min for seg in trip.segments[oi:di])
                    + section_dwell_min
                )
                b.cost.operator.variable.loco_eur += _ann_trip(
                    composition.loco_full_service_lease_eur_h * section_loco_min / 60.0,
                    operating_days,
                )

                # --- Fixed fleet: pair fleet share × section distance/time share
                d_share = section_km / pair_total_km if pair_total_km > 0 else 0.0
                t_share = section_drive_h / pair_total_h if pair_total_h > 0 else 0.0
                for fc in result.composition_fleet_costs:
                    if fc.comp_id != composition.comp_id:
                        continue
                    fleet_share = _pair_fleet_share(pair, fc, route)
                    b.cost.operator.fixed.coach_amortisation_eur += (
                        fc.coach_amortisation_eur * fleet_share * d_share
                    )
                    b.cost.operator.fixed.financing_eur += (
                        fc.financing_eur * fleet_share * d_share
                    )
                    b.cost.operator.fixed.fix_overhead_eur += (
                        fc.fix_overhead_eur * fleet_share * d_share
                    )
                    b.cost.operator.fixed.cleaning_eur += (
                        _ann_op_day(fc.cleaning_eur, operating_days)
                        * fleet_share
                        * t_share
                    )

                # --- Passenger side: everyone on board in the section,
                # km-proportional. Per-class accumulators feed the class cells.
                revenue_by_class: dict[str, float] = {}
                svc_by_class: dict[str, float] = {}
                voh_by_class: dict[str, float] = {}
                margin_by_class: dict[str, float] = {}
                wpkm_by_class: dict[str, float] = {}
                sold_pkm_by_class: dict[str, float] = {}

                for od in trip_ods:
                    ai = stop_idx.get(od.origin_stop_id)
                    bi = stop_idx.get(od.destination_stop_id)
                    if ai is None or bi is None or ai >= bi:
                        continue
                    lo, hi = max(oi, ai), min(di, bi)
                    if lo >= hi:
                        continue  # ticket's ride range doesn't touch the section
                    overlap_km = cum_km[hi] - cum_km[lo]
                    ride_km = cum_km[bi] - cum_km[ai]
                    share = overlap_km / ride_km if ride_km > 0 else 0.0

                    k = (
                        od.trip_id,
                        od.origin_stop_id,
                        od.destination_stop_id,
                        od.class_main,
                    )
                    cls = od.class_main
                    if r := rev_by_key.get(k):
                        revenue_by_class[cls] = (
                            revenue_by_class.get(cls, 0.0) + r.revenue_eur * share
                        )
                    if c := cost_by_key.get(k):
                        svc_by_class[cls] = (
                            svc_by_class.get(cls, 0.0) + c.svc_stockings_eur * share
                        )
                        voh_by_class[cls] = (
                            voh_by_class.get(cls, 0.0) + c.var_overhead_eur * share
                        )
                    if m := margin_by_key.get(k):
                        margin_by_class[cls] = (
                            margin_by_class.get(cls, 0.0) + m.ebit_margin_eur * share
                        )
                    sold_pkm = od.places_sold * overlap_km  # places_sold is annual
                    sold_pkm_by_class[cls] = sold_pkm_by_class.get(cls, 0.0) + sold_pkm
                    wpkm_by_class[cls] = wpkm_by_class.get(
                        cls, 0.0
                    ) + sold_pkm * density_by_class.get(cls, 0.0)

                # --- Shunting + parking: pair totals × section revenue share
                section_revenue = sum(revenue_by_class.values())
                rev_share = (
                    section_revenue / pair_total_revenue
                    if pair_total_revenue > 0
                    else 0.0
                )
                b.cost.operator.fixed.shunting_eur += pair_shunting_total * rev_share
                b.cost.infrastructure.parking_eur += pair_parking_total * rev_share

                # The "__all" cell: train-level costs above + all classes'
                # passenger-side values. Snapshot the train-level part first —
                # the class cells slice it by weighted place-km share.
                train_level = _scale_breakdown(b, 1.0)
                b.revenue.ticket_revenue_eur += section_revenue
                b.cost.operator.variable.svc_stockings_eur += sum(svc_by_class.values())
                b.cost.operator.variable.var_overhead_eur += sum(voh_by_class.values())
                b.margin.ebit_margin_eur += sum(margin_by_class.values())

                all_key = (pair_key, f"{origin_id}__{dest_id}__all")
                total_sold_pkm = sum(sold_pkm_by_class.values())
                all_scope = NormalisationScope(
                    train_km=section_km * operating_days,
                    available_place_km=total_places * section_km * operating_days,
                    sold_place_km=total_sold_pkm,
                )
                # Accumulate, don't overwrite — the same directional section
                # key can only recur if a stop sequence repeats, but silently
                # dropping a cell would corrupt aggregates
                if all_key in matrix:
                    matrix[all_key] += b
                    scopes[all_key] = scopes[all_key] + all_scope
                else:
                    matrix[all_key] = b
                    scopes[all_key] = all_scope

                # Class cells: passenger leaves of that class directly, plus
                # train-level costs scaled by the class's weighted place-km
                # share of the section — class cells sum to the "__all" cell.
                total_wpkm = sum(wpkm_by_class.values())
                for cls in sorted(wpkm_by_class):
                    cls_share = (
                        wpkm_by_class[cls] / total_wpkm if total_wpkm > 0 else 0.0
                    )
                    cb = _scale_breakdown(train_level, cls_share)
                    cb.revenue.ticket_revenue_eur += revenue_by_class.get(cls, 0.0)
                    cb.cost.operator.variable.svc_stockings_eur += svc_by_class.get(
                        cls, 0.0
                    )
                    cb.cost.operator.variable.var_overhead_eur += voh_by_class.get(
                        cls, 0.0
                    )
                    cb.margin.ebit_margin_eur += margin_by_class.get(cls, 0.0)

                    cls_key = (pair_key, f"{origin_id}__{dest_id}__{cls}")
                    cls_scope = NormalisationScope(
                        # Train-km is not class-divisible — a class cell is
                        # still normalised per section train-km
                        train_km=section_km * operating_days,
                        available_place_km=composition.places_by_class.get(cls, 0)
                        * section_km
                        * operating_days,
                        sold_place_km=sold_pkm_by_class.get(cls, 0.0),
                    )
                    if cls_key in matrix:
                        matrix[cls_key] += cb
                        scopes[cls_key] = scopes[cls_key] + cls_scope
                    else:
                        matrix[cls_key] = cb
                        scopes[cls_key] = cls_scope

        # (pair_key, "all") — whole pair; default (trip-pair) normalisation scope
        matrix[(pair_key, "all")] = build_breakdown(route, result, trip_pair=pair)

    # ("all", section_key) — aggregate each section across pairs serving it
    all_section_keys: set[str] = {
        sk for pk, sk in matrix if pk != "all" and sk != "all"
    }
    for sk in all_section_keys:
        b_all = Breakdown()
        scope_all = NormalisationScope(0.0, 0.0, 0.0)
        for pair in route.trip_pairs:
            cell_key = (pair.outbound.trip_id, sk)
            if cell_key in matrix:
                b_all += matrix[cell_key]
                scope_all = scope_all + scopes[cell_key]
        matrix[("all", sk)] = b_all
        scopes[("all", sk)] = scope_all

    # ("all", "all") — whole route; default (route) normalisation scope
    matrix[("all", "all")] = build_breakdown(route, result)

    return {k: _round_breakdown(v) for k, v in matrix.items()}, scopes


# =============================================================================
# LAYER 2C — PER TRIP × STOP
# =============================================================================


def build_breakdown_per_trip_per_stop(
    route: Route,
    result: EvaluationResult,
    segment_loads: dict[tuple[str, int], SegmentPassengerLoad] | None = None,
) -> dict[tuple[str, str], Breakdown]:
    """
    Matrix keyed by (trip_id, stop_id), with "all" as wildcard.

    Keys produced:
      ("all", "all")       — whole route
      (trip_id, "all")     — all stops on one trip summed
      ("all", stop_id)     — this stop across all trips that serve it
      (trip_id, stop_id)   — one stop on one trip

    Only boarding and alighting OD pairs are considered at each stop —
    through-riders are not attributed to the stop.

    Allocation rules:
      station_charge, dwell_driver, dwell_crew
                          → directly from StopCost for (trip_id, stop_id)
      all other costs     → boarding+alighting weighted_place_km at this stop
                            as share of total route weighted_place_km
      revenue, svc_stockings, var_overhead, margin
                          → direct from OD pairs boarding or alighting here
    """
    operating_days = route.schedule.operating_days_per_year

    if segment_loads is None:
        segment_loads = result.segment_passenger_loads

    # Total route weighted place-km — denominator for fixed cost allocation
    route_total_weighted_pkm = sum(
        sl.total_weighted_place_km for sl in segment_loads.values()
    )

    # StopCost lookup by (trip_id, stop_id)
    stc_by_key: dict[tuple[str, str], object] = {
        (stc.trip_id, stc.stop_id): stc for stc in result.stop_costs
    }

    # Pre-compute for each (trip_id, stop_id): which OD pairs board or alight
    # and their total weighted_place_km across the full trip
    # od_weighted_pkm: (trip_id, od_key) → total weighted_place_km for that OD pair
    od_weighted_pkm: dict[tuple, float] = {}
    for sl in segment_loads.values():
        for ol in sl.od_loads:
            k = (
                ol.od_trip_id,
                ol.origin_stop_id,
                ol.destination_stop_id,
                ol.class_main,
            )
            od_weighted_pkm[k] = od_weighted_pkm.get(k, 0.0) + ol.weighted_place_km

    # Revenue lookup by (trip_id, origin, destination, class_main)
    rev_by_key = {
        (r.trip_id, r.origin_stop_id, r.destination_stop_id, r.class_main): r
        for r in result.od_pair_revenues
    }
    cost_by_key = {
        (c.trip_id, c.origin_stop_id, c.destination_stop_id, c.class_main): c
        for c in result.od_pair_costs
    }
    margin_by_key = {
        (m.trip_id, m.origin_stop_id, m.destination_stop_id, m.class_main): m
        for m in result.od_pair_margins
    }

    # Fleet / loco / shunting / parking totals (route-level, for fixed cost share)
    fleet_amort = sum(
        fc.coach_amortisation_eur for fc in result.composition_fleet_costs
    )
    fleet_fin = sum(fc.financing_eur for fc in result.composition_fleet_costs)
    fleet_fix = sum(fc.fix_overhead_eur for fc in result.composition_fleet_costs)
    fleet_clean = sum(
        _ann_op_day(fc.cleaning_eur, operating_days)
        for fc in result.composition_fleet_costs
    )
    loco_total = _ann_trip(
        route.trip_pairs[0].composition.loco_full_service_lease_eur_h
        * route.loco_propulsion_min
        / 60.0,
        operating_days,
    )
    shunting_total = sum(
        _ann_trip(sc.shunting_eur, operating_days) for sc in result.shunting_costs
    )
    parking_total = sum(
        _ann_op_day(pc.parking_eur, operating_days) for pc in result.parking_costs
    )

    matrix: dict[tuple[str, str], Breakdown] = {}

    for pair in route.trip_pairs:
        trip_ids = {pair.outbound.trip_id, pair.return_trip.trip_id}
        composition = pair.composition

        for trip in pair.trips:
            trip_id = trip.trip_id
            stop_idx = {s.stop_id: i for i, s in enumerate(trip.stops)}

            for stop in trip.stops:
                stop_id = stop.stop_id
                b = Breakdown()

                # Direct stop costs
                stc = stc_by_key.get((trip_id, stop_id))
                if stc is not None:
                    b.cost.infrastructure.station_charge_eur += _ann_trip(
                        stc.station_charge_eur, operating_days
                    )
                    b.cost.operator.variable.driver_eur += _ann_trip(
                        stc.dwell_driver_eur, operating_days
                    )
                    b.cost.operator.variable.crew_eur += _ann_trip(
                        stc.dwell_crew_eur, operating_days
                    )

                # Boarding + alighting OD pairs at this stop
                stop_i = stop_idx[stop_id]
                boarding_alighting_ods = [
                    od
                    for od in pair.od_pairs
                    if od.trip_id == trip_id
                    and (
                        od.origin_stop_id == stop_id
                        or od.destination_stop_id == stop_id
                    )
                ]

                # Half the OD pair's weighted place-km assigned to origin, half to destination.
                # This ensures sum of route_share across all stops equals 1.0 exactly.
                stop_weighted_pkm = sum(
                    od_weighted_pkm.get(
                        (
                            od.trip_id,
                            od.origin_stop_id,
                            od.destination_stop_id,
                            od.class_main,
                        ),
                        0.0,
                    )
                    / 2.0
                    for od in boarding_alighting_ods
                )

                # Share of route total — denominator for all fixed costs
                route_share = (
                    stop_weighted_pkm / route_total_weighted_pkm
                    if route_total_weighted_pkm > 0
                    else 0.0
                )

                # Segment costs — sum over segments where this stop is the from_stop or to_stop,
                # weighted by boarding/alighting OD pair share
                for sc in result.segment_costs:
                    if sc.trip_id != trip_id:
                        continue
                    if sc.from_stop_id != stop_id and sc.to_stop_id != stop_id:
                        continue
                    sl = segment_loads.get((trip_id, sc.segment_index))
                    if sl is None:
                        continue
                    seg_total_wpkm = sl.total_weighted_place_km
                    seg_stop_wpkm = sum(
                        ol.weighted_place_km / 2.0
                        for ol in sl.od_loads
                        if ol.origin_stop_id == stop_id
                        or ol.destination_stop_id == stop_id
                    )
                    seg_share = (
                        seg_stop_wpkm / seg_total_wpkm if seg_total_wpkm > 0 else 0.0
                    )
                    b.cost.operator.variable.coach_maintenance_eur += _ann_trip(
                        sc.coach_maintenance_eur * seg_share, operating_days
                    )
                    b.cost.operator.variable.driver_eur += _ann_trip(
                        sc.driver_eur * seg_share, operating_days
                    )
                    b.cost.operator.variable.crew_eur += _ann_trip(
                        sc.crew_eur * seg_share, operating_days
                    )
                    b.cost.infrastructure.tac_eur += _ann_trip(
                        sc.tac_eur * seg_share, operating_days
                    )
                    b.cost.infrastructure.energy_eur += _ann_trip(
                        sc.energy_eur * seg_share, operating_days
                    )

                # Fixed costs — route share
                b.cost.operator.fixed.coach_amortisation_eur += (
                    fleet_amort * route_share
                )
                b.cost.operator.fixed.financing_eur += fleet_fin * route_share
                b.cost.operator.fixed.fix_overhead_eur += fleet_fix * route_share
                b.cost.operator.fixed.cleaning_eur += fleet_clean * route_share
                b.cost.operator.variable.loco_eur += loco_total * route_share
                b.cost.operator.fixed.shunting_eur += shunting_total * route_share
                b.cost.infrastructure.parking_eur += parking_total * route_share

                # Revenue / cost / margin — direct from boarding+alighting OD pairs
                for od in boarding_alighting_ods:
                    k = (
                        od.trip_id,
                        od.origin_stop_id,
                        od.destination_stop_id,
                        od.class_main,
                    )
                    if r := rev_by_key.get(k):
                        b.revenue.ticket_revenue_eur += r.revenue_eur
                    if c := cost_by_key.get(k):
                        b.cost.operator.variable.svc_stockings_eur += (
                            c.svc_stockings_eur
                        )
                        b.cost.operator.variable.var_overhead_eur += c.var_overhead_eur
                    if m := margin_by_key.get(k):
                        b.margin.ebit_margin_eur += m.ebit_margin_eur

                matrix[(trip_id, stop_id)] = b

    # (trip_id, "all") — all stops on one trip
    all_trip_ids = {k[0] for k in matrix if k[0] != "all"}
    for trip_id in all_trip_ids:
        b_all = Breakdown()
        for k, b in matrix.items():
            if k[0] == trip_id and k[1] != "all":
                b_all += b
        matrix[(trip_id, "all")] = b_all

    # ("all", stop_id) — this stop across all trips
    all_stop_ids = {k[1] for k in matrix if k[1] != "all"}
    for stop_id in all_stop_ids:
        b_all = Breakdown()
        for k, b in matrix.items():
            if k[1] == stop_id and k[0] != "all":
                b_all += b
        matrix[("all", stop_id)] = b_all

    # ("all", "all")
    matrix[("all", "all")] = build_breakdown(route, result)
    return {k: _round_breakdown(v) for k, v in matrix.items()}


# =============================================================================
# LAYER 3 — NORMALISERS
# =============================================================================


def normalise(breakdown: Breakdown, denominator: float) -> Breakdown:
    """
    Divide every leaf of breakdown by denominator, returning a new Breakdown.
    The tree shape is preserved — only the values change.
    Returns a zero Breakdown if denominator is 0.
    """
    if denominator == 0.0:
        return Breakdown()
    return _round_breakdown(_map_breakdown(breakdown, lambda v: v / denominator))


def normalise_per_operating_day(
    breakdown: Breakdown,
    route: Route,
) -> Breakdown:
    """
    Divide every leaf by operating_days_per_year → €/operating-day.
    Since Breakdown is already €/year, this reverses the annualisation
    applied in build_breakdown.
    """
    return normalise(breakdown, float(route.schedule.operating_days_per_year))


def normalise_per_train_km(
    breakdown: Breakdown,
    route: Route,
    trip_pair: TripPair | None = None,
    scope: NormalisationScope | None = None,
) -> Breakdown:
    """
    Divide every leaf by annual train-km in scope → €/train-km.

    The Breakdown is €/year, so the divisor must be annual too:
    cycle distance × operating_days_per_year. (Dividing by one cycle's
    distance — the pre-0.9.4 behavior — left the result inflated by a
    factor of operating_days.)

    scope set      → the cell's own annual train-km (route sections).
    trip_pair=None → whole route: all trips in all pairs (outbound +
                     return both counted) × operating days.
    trip_pair=pair → that pair's cycle distance × operating days.
    """
    if scope is not None:
        return normalise(breakdown, scope.train_km)
    trips = (
        [t for pair in route.trip_pairs for t in pair.trips]
        if trip_pair is None
        else list(trip_pair.trips)
    )
    cycle_km = sum(seg.distance_m / 1000.0 for trip in trips for seg in trip.segments)
    return normalise(breakdown, cycle_km * route.schedule.operating_days_per_year)


def normalise_per_available_place_km(
    breakdown: Breakdown,
    route: Route,
    trip_pair: TripPair | None = None,
    scope: NormalisationScope | None = None,
) -> Breakdown:
    """
    Divide every leaf by annual available place-km → €/available-place-km.

    Available place-km = Σ(places_by_class × segment_distance_km) across
    all classes and all segments in scope, × operating_days_per_year.
    Capacity-based — independent of demand. Annualised for the same reason
    as normalise_per_train_km (and for consistency with
    normalise_per_sold_place_km, whose places_sold input is already annual).

    scope set      → the cell's own annual available place-km.
    trip_pair=None → whole route (all pairs, all segments).
    trip_pair=pair → that pair's trips only.
    """
    if scope is not None:
        return normalise(breakdown, scope.available_place_km)
    pairs = [trip_pair] if trip_pair is not None else route.trip_pairs
    cycle_place_km = sum(
        sum(pair.composition.places_by_class.values()) * seg.distance_m / 1000.0
        for pair in pairs
        for trip in pair.trips
        for seg in trip.segments
    )
    return normalise(breakdown, cycle_place_km * route.schedule.operating_days_per_year)


def normalise_per_sold_place_km(
    breakdown: Breakdown,
    route: Route,
    trip_pair: TripPair | None = None,
    scope: NormalisationScope | None = None,
) -> Breakdown:
    """
    Divide every leaf by total sold place-km → €/sold-place-km.

    Sold place-km = Σ(od.places_sold × segment_distance_km) for each OD
    pair across its segment range (origin_stop_idx to destination_stop_idx).
    Already annual — places_sold is annual. Unweighted — raw sold seat-km
    regardless of class density.

    scope set      → the cell's own annual sold place-km.
    trip_pair=None → whole route (all pairs).
    trip_pair=pair → that pair's OD pairs only.
    """
    if scope is not None:
        return normalise(breakdown, scope.sold_place_km)
    pairs = [trip_pair] if trip_pair is not None else route.trip_pairs
    sold_place_km = 0.0
    for pair in pairs:
        for trip in pair.trips:
            stop_ids = [s.stop_id for s in trip.stops]
            for od in pair.od_pairs:
                if od.trip_id != trip.trip_id:
                    continue
                if (
                    od.origin_stop_id not in stop_ids
                    or od.destination_stop_id not in stop_ids
                ):
                    continue
                start_idx = stop_ids.index(od.origin_stop_id)
                end_idx = stop_ids.index(od.destination_stop_id)
                sold_place_km += sum(
                    od.places_sold * seg.distance_m / 1000.0
                    for i, seg in enumerate(trip.segments)
                    if start_idx <= i < end_idx
                )
    return normalise(breakdown, sold_place_km)


# =============================================================================
# VIEW METADATA — for the API's "views_meta" section
# =============================================================================
#
# Documents, once per view × normalisation combination, what filter/scope
# stage(s) produced that number and what it was divided by. Consumed by
# api/evaluation.py to build a single "views_meta" block in the response —
# not repeated per data point, since the same 25 descriptions apply
# identically to every pair/country/OD/stop key in "views".

_VIEW_FILTER_STAGES: dict[str, list[str]] = {
    "route": ["all trip pairs", "all segments/stops/OD pairs"],
    "per_trip_pair": [
        "one trip pair (outbound + return), or 'all' for the whole route"
    ],
    "per_trip_pair_per_country": [
        "one trip pair (outbound + return), or 'all'",
        "one country, via distance/time/place-km allocation share, or 'all'",
    ],
    "per_trip_pair_per_od": [
        "one trip pair (outbound + return), or 'all'",
        "one OD pair (origin, destination, class), via place-km/place-hours/revenue "
        "allocation share, or 'all'",
    ],
    "per_trip_pair_per_section": [
        "one trip pair (outbound + return), or 'all'",
        "one route section (all costs occurring between two stops of a trip; "
        "km-proportional revenue of everyone on board there), sub-keyed by "
        "class_main or 'all'",
    ],
    "per_trip_per_stop": [
        "one trip (outbound or return), or 'all'",
        "one stop call, via place-km/route-share allocation, or 'all'",
    ],
}

_VIEW_DESCRIPTIONS: dict[str, str] = {
    "route": "Whole-route annual totals — every trip pair, segment, stop and OD pair "
    "rolled into one figure.",
    "per_trip_pair": "Annual totals filtered to a single trip pair, or the whole route "
    "under key 'all'.",
    "per_trip_pair_per_country": "Matrix of annual totals by trip pair x country. Cost "
    "types are allocated to countries by distance share, "
    "time share, or OD place-km share depending on the "
    "cost — see build_breakdown_per_trip_pair_per_country().",
    "per_trip_pair_per_od": "Matrix of annual totals by trip pair x OD pair (origin, "
    "destination, class) — money attributed to one passenger "
    "relation. Cost types are allocated by place-km, "
    "place-hours, or revenue share depending on the cost — see "
    "build_breakdown_per_trip_pair_per_od(). Cells partition "
    "the pair total (they sum to it).",
    "per_trip_pair_per_section": "Matrix of annual totals by trip pair x route "
    "section (two stops of a trip, directional). A section "
    "carries every cost physically occurring between its "
    "stops plus a share of route-level costs, and the "
    "km-proportional revenue of everyone on board there — "
    "including passengers whose tickets extend beyond the "
    "section. Each section additionally carries per-class "
    "cells (revenue/cost/margin of one class_main; train-"
    "level costs split by density-weighted place-km) that "
    "sum to the section's 'all' cell. Sections overlap by "
    "construction, so section cells deliberately do NOT sum "
    "to the pair total — see "
    "build_breakdown_per_trip_pair_per_section().",
    "per_trip_per_stop": "Matrix of annual totals by trip x individual stop call — "
    "station charge and dwell driver/crew cost, plus a route-share "
    "allocation of fixed/infrastructure costs.",
}

# (description, extra processing_sequence stage) per normalisation — appended
# after a view's own filter stages to form the full sequence for that cell.
_NORMALISATION_STAGES: dict[str, tuple[str, list[str]]] = {
    "per_year": (
        "Raw annual figure — no further division.",
        [],
    ),
    "per_operating_day": (
        "Divided by operating days per year.",
        ["÷ operating_days_per_year"],
    ),
    "per_train_km": (
        "Divided by annual train-km in scope (cycle distance × operating days; "
        "a route section's own distance for section cells).",
        ["÷ annual train-km in scope"],
    ),
    "per_available_place_km": (
        "Divided by annual available place-km in scope (capacity × distance × "
        "operating days, independent of demand).",
        ["÷ annual available place-km"],
    ),
    "per_sold_place_km": (
        "Divided by annual sold place-km in scope (annual tickets sold × distance, "
        "unweighted by class density).",
        ["÷ annual sold place-km"],
    ),
}

VIEW_META: dict[str, dict] = {
    view: {
        "description": _VIEW_DESCRIPTIONS[view],
        "normalisations": {
            norm: {
                "description": norm_description,
                "processing_sequence": _VIEW_FILTER_STAGES[view] + extra_stage,
            }
            for norm, (norm_description, extra_stage) in _NORMALISATION_STAGES.items()
        },
    }
    for view in _VIEW_DESCRIPTIONS
}
