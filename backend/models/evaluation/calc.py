"""
calc.py
=======
Flat cost and revenue calculation. No aggregation, no normalisation,
no serialisation — see views.py for grouped/normalised views and
serialisation.py for JSON output.

Cost hierarchy
--------------
  Route       → loco lease (full-service, utilization-based, billed on
                route-wide deduplicated operating time — see Route.loco_propulsion_min)
  Parking     → one ParkingCost per Parking event (parking_eur_day per country)
  Shunting    → one ShuntingCost per Shunting event (shunting_eur_event per country)
  Composition → fixed fleet costs (amortisation, financing, fix overhead,
                cleaning), summed across all TripPairs sharing that
                composition — not per TripPair, since two pairs using the
                same composition share one fleet, not two
  Segment     → variable/km (coach maintenance only — loco maintenance is
                bundled into the full-service lease, see Route), variable/hour
                driving, infrastructure (TAC, energy)
  Stop        → station charge, dwell crew cost — deduplicated by stop_id in
                EvaluationResult.stop_costs, since a stop is touched by two
                segments (to_stop of one, from_stop of the next) and a shared
                stop on a Y-shape is touched by multiple trips

Revenue, cost, and margin (OD pair level)
-------------------------------------------
  ODPairRevenue → ticket revenue, pure
  ODPairCost    → svc_stockings, var_overhead — real costs, not revenue
  ODPairMargin  → ebit margin — target profit allocation, neither cost nor revenue

All costs in EUR. evaluate_route() walks a Route and returns a flat
EvaluationResult — one cost object per segment, one per trip pair, one
per route, one revenue object per OD pair. No grouping or filtering here.
"""

from __future__ import annotations

from dataclasses import dataclass

from models.params import Composition, StopInfraCollection, TrackInfraCollection
from models.route.route import Route
from models.route.trip import Segment, Stop

# =============================================================================
# RESULT OBJECTS
# =============================================================================

@dataclass
class StopCost:
    """Cost attributable to one stop call: station charge + dwell driver/crew cost.
    Keyed by (trip_id, stop_id) — each trip call to a stop is a separate charge,
    so outbound and return both pay. Within one trip a stop is only charged once
    even though it borders two adjacent segments.
    dwell_driver_eur and dwell_crew_eur are 0.0 if dwell_time_min is None
    (trip origin/destination). Kept separate so they merge into their respective
    driver_eur / crew_eur totals in views.py.

    All fields: €/trip (one train call to this stop).
    """

    trip_id: str                # which trip made this stop call
    stop_id: str
    country_code: str           # from Stop.country_code — ISO 3166-1 alpha-2
    station_charge_eur: float   # €/trip
    dwell_driver_eur: float     # €/trip
    dwell_crew_eur: float       # €/trip

    @property
    def total_eur(self) -> float:   # €/trip
        return self.station_charge_eur + self.dwell_driver_eur + self.dwell_crew_eur

@dataclass
class SegmentCost:
    """Variable + infrastructure cost for one segment. Stop costs (station
    charge, dwell crew cost) are NOT here — they're computed once per
    unique stop in EvaluationResult.stop_costs, since a stop is touched by
    two segments (as to_stop of one, from_stop of the next) and embedding
    it here would double-count it.

    All fields: €/segment (one segment of one trip).
    """

    trip_id: str
    segment_index: int
    from_stop_id: str
    to_stop_id: str
    distance_m: int                         # metres
    driving_time_min: int                   # driving only, excludes dwell
    country_distance_shares: dict[str, float]   # fraction of distance per country, sums to 1.0
    country_time_shares: dict[str, float]       # fraction of driving time per country, sums to 1.0

    coach_maintenance_eur: float    # €/segment  (loco maintenance is in RouteCost.loco_eur — full-service lease)
    driver_eur: float               # €/segment  (driving time only — dwell is in StopCost)
    crew_eur: float                 # €/segment  (driving time only — dwell is in StopCost)
    tac_eur: float                  # €/segment
    energy_eur: float               # €/segment

    @property
    def variable_km_eur(self) -> float:
        return self.coach_maintenance_eur

    @property
    def variable_hour_eur(self) -> float:
        return self.driver_eur + self.crew_eur

    @property
    def infrastructure_eur(self) -> float:
        return self.tac_eur + self.energy_eur

    @property
    def total_eur(self) -> float:
        return self.variable_km_eur + self.variable_hour_eur + self.infrastructure_eur

@dataclass
class CompositionFleetCost:
    """
    Fixed cost for one composition type's fleet, summed across all
    TripPairs using it. Not trip-pair-level: amortisation, financing,
    fix overhead, and cleaning are all properties of owning N coach sets
    of this composition — if two TripPairs share a comp_id, the cost is
    computed once for their combined coach count, not once per pair
    (which would double-count the same fleet).

    Shunting is NOT here — see ShuntingCost, computed per movement at
    route level rather than per composition.

    Units per field:
      coach_amortisation_eur  €/year   (purchase_coach_eur / coach_amort_years × n)
      financing_eur           €/year   (purchase_coach_eur × financing_quota_per × n)
      fix_overhead_eur        €/year   (coach_amortisation_eur × fix_overhead_quota_per)
      cleaning_eur            €/operating-day  (cleaning_services_eur_day × n)
    """

    comp_id: str
    coaches_required: float  # this route's share of the fleet — see TripPair.composition_count
    coach_amortisation_eur: float   # €/year
    financing_eur: float            # €/year
    fix_overhead_eur: float         # €/year
    cleaning_eur: float             # €/operating-day

    @property
    def total_eur(self) -> float:
        return (
            self.coach_amortisation_eur
            + self.financing_eur
            + self.fix_overhead_eur
            + self.cleaning_eur
        )

@dataclass
class ShuntingCost:
    """
    Cost of shunting movements across the route. shunting_count comes
    from Route.shunting_count (currently 2 per trip — a placeholder
    rule). shunting_eur_event is an operator-level rate (one shunting
    yard contract per operator) — Route's operator invariant guarantees
    every TripPair's composition carries the same rate.

    total_eur unit: €/trip-cycle (one outbound + return).
    """

    route_id: str
    shunting_count: int
    shunting_eur_event: float       # €/event

    @property
    def total_eur(self) -> float:   # €/trip-cycle
        return self.shunting_count * self.shunting_eur_event

@dataclass
class ParkingCost:
    """Cost for one overnight parking location. Mirrors Parking —
    one ParkingCost per Parking in route.parkings.
    parking_eur: €/operating-day (track_parking_eur_day from TrackInfrastructure)."""

    stop_id: str
    trip_ids: list[str]         # trips whose formation parks here
    country_code: str
    parking_eur: float          # €/operating-day

@dataclass
class ShuntingCost:
    """Cost for one shunting event. Mirrors Shunting —
    one ShuntingCost per Shunting in route.shuntings.
    shunting_eur: €/event (track_shunting_eur_event from TrackInfrastructure)."""

    stop_id: str
    trip_id: str                # which trip this shunting belongs to
    country_code: str
    shunting_eur: float         # €/event

@dataclass
class RouteCost:
    """Loco lease cost for the route — the only route-level cost that doesn't
    have a natural per-event object (unlike parking and shunting which mirror
    Parking/Shunting). Parking and shunting costs live in EvaluationResult
    as separate lists, one cost object per event.

    loco_eur: €/trip-cycle (loco_lease_eur_h × loco_propulsion_min / 60)
    """

    route_id: str
    loco_eur: float                 # €/trip-cycle

    @property
    def total_eur(self) -> float:
        return self.loco_eur

@dataclass
class ODPairRevenue:
    """Ticket revenue for one OD pair. Pure revenue — no costs here.
    places_sold is annual — so revenue_eur is €/year directly.
    No further annualisation needed in views.py."""

    trip_id: str
    origin_stop_id: str
    destination_stop_id: str
    class_main: str
    places_sold: int            # annual tickets sold
    revenue_eur: float          # €/year  (places_sold × avg_price)

@dataclass
class ODPairCost:
    """
    Per-ticket costs for one OD pair: onboard service/stockings cost and
    a variable overhead allocation, both scaling with ticket revenue or
    places sold. Not infrastructure or composition cost — those are
    segment/composition-level (see SegmentCost, CompositionFleetCost).
    All fields: €/year (places_sold is annual).
    """

    trip_id: str
    origin_stop_id: str
    destination_stop_id: str
    class_main: str
    svc_stockings_eur: float    # €/year  (svc_stockings_eur_place × places_sold)
    var_overhead_eur: float     # €/year  (var_overhead_per × revenue_eur)

    @property
    def total_eur(self) -> float:   # €/year
        return self.svc_stockings_eur + self.var_overhead_eur

@dataclass
class ODPairMargin:
    """
    Target profit margin allocated to one OD pair — a deduction carved
    out of revenue to reach the operator's required EBIT margin, not a
    cost paid to any third party and not raw ticket revenue.
    All fields: €/year (places_sold is annual).
    """

    trip_id: str
    origin_stop_id: str
    destination_stop_id: str
    class_main: str
    ebit_margin_eur: float      # €/year  (ebit_margin_per × revenue_eur)

# =============================================================================
# SEGMENT PASSENGER LOAD
# =============================================================================

@dataclass
class ODSegmentLoad:
    """One OD pair's contribution to one segment — place-km and place-hours,
    unweighted and density-weighted, total and per country. Annual figures."""
    od_trip_id: str
    origin_stop_id: str
    destination_stop_id: str
    class_main: str
    places_sold: int                            # annual
    density: float                              # space factor from Composition.density_by_class

    place_km: float                             # places_sold × distance_km
    place_hours: float                          # places_sold × driving_h
    weighted_place_km: float                    # × density
    weighted_place_hours: float                 # × density

    place_km_by_country: dict[str, float]
    place_hours_by_country: dict[str, float]
    weighted_place_km_by_country: dict[str, float]
    weighted_place_hours_by_country: dict[str, float]

@dataclass
class SegmentPassengerLoad:
    """All OD pairs riding one segment, with totals and per-country sums.
    Key: (trip_id, segment_index)."""
    trip_id: str
    segment_index: int
    distance_km: float
    driving_time_min: int
    country_distance_shares: dict[str, float]
    country_time_shares: dict[str, float]
    od_loads: list[ODSegmentLoad]

    @property
    def total_place_km(self) -> float:
        return sum(l.place_km for l in self.od_loads)

    @property
    def total_place_hours(self) -> float:
        return sum(l.place_hours for l in self.od_loads)

    @property
    def total_weighted_place_km(self) -> float:
        return sum(l.weighted_place_km for l in self.od_loads)

    @property
    def total_weighted_place_hours(self) -> float:
        return sum(l.weighted_place_hours for l in self.od_loads)

    def total_place_km_for_country(self, cc: str) -> float:
        return sum(l.place_km_by_country.get(cc, 0.0) for l in self.od_loads)

    def total_place_hours_for_country(self, cc: str) -> float:
        return sum(l.place_hours_by_country.get(cc, 0.0) for l in self.od_loads)

    def total_weighted_place_km_for_country(self, cc: str) -> float:
        return sum(l.weighted_place_km_by_country.get(cc, 0.0) for l in self.od_loads)

    def total_weighted_place_hours_for_country(self, cc: str) -> float:
        return sum(l.weighted_place_hours_by_country.get(cc, 0.0) for l in self.od_loads)

@dataclass
class EvaluationResult:
    """
    Flat, ungrouped output of evaluate_route(). One entry per segment,
    per unique stop, per composition's fleet, per OD pair, plus one
    route-level cost. See views.py for grouped, filtered, normalised
    views over this data.
    """

    route_cost: RouteCost
    composition_fleet_costs: list[CompositionFleetCost]
    segment_costs: list[SegmentCost]
    stop_costs: list[StopCost]
    parking_costs: list[ParkingCost]
    shunting_costs: list[ShuntingCost]
    od_pair_revenues: list[ODPairRevenue]
    od_pair_costs: list[ODPairCost]
    od_pair_margins: list[ODPairMargin]
    segment_passenger_loads: dict[tuple[str, int], "SegmentPassengerLoad"]

# =============================================================================
# SEGMENT COST
# =============================================================================

def _calc_stop_cost(trip_id: str, stop: Stop, stop_infra: StopInfraCollection, composition: Composition) -> StopCost:
    sp = stop_infra.get(stop.stop_id)
    station_charge_eur = sp.stop_charge_eur if sp else 0.0
    country_code = stop.country_code
    dwell_h = stop.dwell_time_min / 60.0 if stop.dwell_time_min is not None else 0.0
    dwell_driver_eur = dwell_h * composition.driver_costs_eur_h
    dwell_crew_eur = dwell_h * composition.crew_costs_eur_h
    return StopCost(
        trip_id=trip_id,
        stop_id=stop.stop_id,
        country_code=country_code,
        station_charge_eur=station_charge_eur,
        dwell_driver_eur=dwell_driver_eur,
        dwell_crew_eur=dwell_crew_eur,
    )

def _calc_segment_cost(
    trip_id: str,
    segment_index: int,
    segment: Segment,
    composition: Composition,
    tracks: TrackInfraCollection,
) -> SegmentCost:
    distance_km = segment.distance_m / 1000.0
    driving_h = segment.driving_time_min / 60.0

    coach_maintenance_eur = composition.coach_maint_eur_km * distance_km
    driver_eur = composition.driver_costs_eur_h * driving_h
    crew_eur = composition.crew_costs_eur_h * driving_h

    tac_eur = 0.0
    energy_eur = 0.0
    for cc, dist_share in segment.country_distance_shares.items():
        track = tracks.get_or_default(cc)
        if track is None:
            continue
        tac_eur += distance_km * dist_share * track.tac_eur_train_km
        energy_eur += segment.energy_kwh * dist_share * track.energy_price_eur_kwh

    return SegmentCost(
        trip_id=trip_id,
        segment_index=segment_index,
        from_stop_id=segment.from_stop.stop_id,
        to_stop_id=segment.to_stop.stop_id,
        distance_m=segment.distance_m,
        driving_time_min=segment.driving_time_min,
        country_distance_shares=segment.country_distance_shares,
        country_time_shares=segment.country_time_shares,
        coach_maintenance_eur=coach_maintenance_eur,
        driver_eur=driver_eur,
        crew_eur=crew_eur,
        tac_eur=tac_eur,
        energy_eur=energy_eur,
    )

# =============================================================================
# COMPOSITION FLEET COST (route level, grouped by comp_id)
# =============================================================================

def _calc_composition_fleet_costs(route: Route) -> list[CompositionFleetCost]:
    """
    Groups TripPairs by comp_id, summing coaches_required, then computes
    fixed fleet cost once per composition for its total coach count — not
    once per TripPair, since two pairs sharing a composition share one fleet.

    n is already availability-adjusted (TripPair.composition_count divides
    by coach_avail_per) — the amortisation/financing formulas multiply by n
    directly and must NOT divide by coach_avail_per again.
    """
    compositions: dict[str, Composition] = {
        pair.composition.comp_id: pair.composition
        for pair in route.trip_pairs
    }
    coach_totals = route.composition_counts

    results = []
    for comp_id, n in coach_totals.items():
        c = compositions[comp_id]
        coach_amortisation_eur = (                      # €/year
            c.purchase_coach_eur / c.coach_amort_years * n
            if c.coach_amort_years > 0
            else 0.0
        )
        financing_eur = c.purchase_coach_eur * c.financing_quota_per * n  # €/year
        fix_overhead_eur = coach_amortisation_eur * c.fix_overhead_quota_per  # €/year

        results.append(CompositionFleetCost(
            comp_id=comp_id,
            coaches_required=n,
            coach_amortisation_eur=coach_amortisation_eur,
            financing_eur=financing_eur,
            fix_overhead_eur=fix_overhead_eur,
            cleaning_eur=c.cleaning_services_eur_day * n,   # €/operating-day
        ))
    return results

# =============================================================================
# ROUTE COST
# =============================================================================

def _calc_route_cost(route: Route, tracks: TrackInfraCollection) -> RouteCost:
    """Loco lease only — parking and shunting are computed per-event
    in _calc_parking_costs and _calc_shunting_costs."""
    composition = route.trip_pairs[0].composition
    loco_eur = composition.loco_full_service_lease_eur_h * route.loco_propulsion_min / 60.0
    return RouteCost(route_id=route.route_id, loco_eur=loco_eur)

def _calc_parking_costs(route: Route, tracks: TrackInfraCollection) -> list[ParkingCost]:
    """One ParkingCost per Parking — mirrors route.parkings."""
    costs = []
    for p in route.parkings:
        track = tracks.get_or_default(p.country_code)
        costs.append(ParkingCost(
            stop_id=p.stop_id,
            trip_ids=p.trip_ids,
            country_code=p.country_code,
            parking_eur=track.parking_eur_day if track else 0.0,  # €/operating-day
        ))
    return costs

def _calc_shunting_costs(route: Route, tracks: TrackInfraCollection) -> list[ShuntingCost]:
    """One ShuntingCost per Shunting — mirrors route.shuntings."""
    costs = []
    for s in route.shuntings:
        track = tracks.get_or_default(s.country_code)
        costs.append(ShuntingCost(
            stop_id=s.stop_id,
            trip_id=s.trip_id,
            country_code=s.country_code,
            shunting_eur=track.shunting_eur_event if track else 0.0,  # €/event
        ))
    return costs

# =============================================================================
# OD PAIR REVENUE
# =============================================================================

def _calc_od_pair_results(
    route: Route,
) -> tuple[list[ODPairRevenue], list[ODPairCost], list[ODPairMargin]]:
    """
    Computes revenue, cost, and margin per OD pair.
    Iterates trip_pairs directly — composition is always available without
    a lookup since ODPair now lives on TripPair.

    od.places_sold is annual, so all outputs are €/year directly —
    no frequency multiplier (operating_days_per_year) is needed here.
    """
    revenues: list[ODPairRevenue] = []
    costs: list[ODPairCost] = []
    margins: list[ODPairMargin] = []

    for pair in route.trip_pairs:
        composition = pair.composition
        for od in pair.od_pairs:
            revenue_eur = od.places_sold * od.avg_price
            svc_stockings_eur = (
                composition.svc_stockings_eur_place.get(od.class_main, 0.0)
                * od.places_sold
            )
            var_overhead_eur = revenue_eur * composition.var_overhead_per
            ebit_margin_eur = revenue_eur * composition.ebit_margin_per

            revenues.append(ODPairRevenue(
                trip_id=od.trip_id,
                origin_stop_id=od.origin_stop_id,
                destination_stop_id=od.destination_stop_id,
                class_main=od.class_main,
                places_sold=od.places_sold,
                revenue_eur=revenue_eur,
            ))
            costs.append(ODPairCost(
                trip_id=od.trip_id,
                origin_stop_id=od.origin_stop_id,
                destination_stop_id=od.destination_stop_id,
                class_main=od.class_main,
                svc_stockings_eur=svc_stockings_eur,
                var_overhead_eur=var_overhead_eur,
            ))
            margins.append(ODPairMargin(
                trip_id=od.trip_id,
                origin_stop_id=od.origin_stop_id,
                destination_stop_id=od.destination_stop_id,
                class_main=od.class_main,
                ebit_margin_eur=ebit_margin_eur,
            ))

    return revenues, costs, margins

# =============================================================================
# PUBLIC ENTRY POINT
# =============================================================================

def compute_segment_passenger_loads(
    route: Route,
    result: EvaluationResult,
) -> dict[tuple[str, int], SegmentPassengerLoad]:
    """
    Pre-computes annual place-km and place-hours per (trip_id, segment_index)
    for every OD pair that rides that segment.

    An OD pair rides segment i if origin_stop_index <= i < destination_stop_index.
    place-km and place-hours use country_distance_shares / country_time_shares
    for the per-country breakdown.
    """
    sc_by_key = {(sc.trip_id, sc.segment_index): sc for sc in result.segment_costs}

    stop_indices: dict[str, dict[str, int]] = {
        trip.trip_id: {s.stop_id: i for i, s in enumerate(trip.stops)}
        for pair in route.trip_pairs
        for trip in pair.trips
    }

    loads: dict[tuple[str, int], SegmentPassengerLoad] = {}

    for pair in route.trip_pairs:
        density_by_class = pair.composition.density_by_class
        for trip in pair.trips:
            trip_stop_idx = stop_indices[trip.trip_id]
            for seg_idx in range(len(trip.segments)):
                sc = sc_by_key.get((trip.trip_id, seg_idx))
                if sc is None:
                    continue
                distance_km = sc.distance_m / 1000.0
                driving_h = sc.driving_time_min / 60.0
                od_loads: list[ODSegmentLoad] = []

                for od in pair.od_pairs:
                    if od.trip_id != trip.trip_id:
                        continue
                    if od.origin_stop_id not in trip_stop_idx or od.destination_stop_id not in trip_stop_idx:
                        continue
                    if not (trip_stop_idx[od.origin_stop_id] <= seg_idx < trip_stop_idx[od.destination_stop_id]):
                        continue

                    density = density_by_class.get(od.class_main, 0.0)
                    p = od.places_sold
                    place_km = p * distance_km
                    place_hours = p * driving_h
                    w_km = place_km * density
                    w_hours = place_hours * density

                    od_loads.append(ODSegmentLoad(
                        od_trip_id=od.trip_id,
                        origin_stop_id=od.origin_stop_id,
                        destination_stop_id=od.destination_stop_id,
                        class_main=od.class_main,
                        places_sold=p,
                        density=density,
                        place_km=place_km,
                        place_hours=place_hours,
                        weighted_place_km=w_km,
                        weighted_place_hours=w_hours,
                        place_km_by_country={cc: place_km * s for cc, s in sc.country_distance_shares.items()},
                        place_hours_by_country={cc: place_hours * s for cc, s in sc.country_time_shares.items()},
                        weighted_place_km_by_country={cc: w_km * s for cc, s in sc.country_distance_shares.items()},
                        weighted_place_hours_by_country={cc: w_hours * s for cc, s in sc.country_time_shares.items()},
                    ))

                loads[(trip.trip_id, seg_idx)] = SegmentPassengerLoad(
                    trip_id=trip.trip_id,
                    segment_index=seg_idx,
                    distance_km=distance_km,
                    driving_time_min=sc.driving_time_min,
                    country_distance_shares=sc.country_distance_shares,
                    country_time_shares=sc.country_time_shares,
                    od_loads=od_loads,
                )

    return loads

def evaluate_route(
    route: Route,
    tracks: TrackInfraCollection,
    stop_infra: StopInfraCollection,
) -> EvaluationResult:
    """Compute flat cost and revenue for a Route. No aggregation or
    normalisation — see views.py."""
    composition_fleet_costs = _calc_composition_fleet_costs(route)

    segment_costs = []
    seen_stop_ids: set[tuple[str, str]] = set()
    stop_costs: list[StopCost] = []

    for pair in route.trip_pairs:
        for trip in pair.trips:
            for i, segment in enumerate(trip.segments):
                segment_costs.append(_calc_segment_cost(
                    trip_id=trip.trip_id,
                    segment_index=i,
                    segment=segment,
                    composition=pair.composition,
                    tracks=tracks,
                ))

            # Deduplicated by (trip_id, stop_id): each stop is touched by
            # two segments within one trip (as to_stop of segment N and
            # from_stop of segment N+1), so without deduplication it would
            # be charged twice per trip. But a stop visited by both the
            # outbound and return trip — or by two different trip pairs on a
            # Y-shape — is a separate train call each time and must be
            # charged separately. Hence the key includes trip_id.
            for stop in trip.stops:
                key = (trip.trip_id, stop.stop_id)
                if key in seen_stop_ids:
                    continue
                seen_stop_ids.add(key)
                stop_costs.append(_calc_stop_cost(trip.trip_id, stop, stop_infra, pair.composition))

    od_pair_revenues, od_pair_costs, od_pair_margins = _calc_od_pair_results(route)

    result = EvaluationResult(
        route_cost=_calc_route_cost(route, tracks),
        composition_fleet_costs=composition_fleet_costs,
        segment_costs=segment_costs,
        stop_costs=stop_costs,
        parking_costs=_calc_parking_costs(route, tracks),
        shunting_costs=_calc_shunting_costs(route, tracks),
        od_pair_revenues=od_pair_revenues,
        od_pair_costs=od_pair_costs,
        od_pair_margins=od_pair_margins,
        segment_passenger_loads={},  # populated below — needs full result
    )
    result.segment_passenger_loads = compute_segment_passenger_loads(route, result)
    return result