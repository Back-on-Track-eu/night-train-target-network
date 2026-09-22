"""
summary.py
==========
Gallery-summary KPI derivation (adapters/proposal/README.md §5.4) — pure
functions over the same dicts a member payload carries
(route_to_dict() shape + the evaluation "views" block). No DB access, no
domain-object construction, and no geometry: the simplified gallery-map
geometry is deliberately NOT part of this row — the calc response
already carries full per-segment geometry, so only the DB-shaped
assembly in adapters/proposal/projection.py (build_summary_db_row())
adds a `geom_simplified` for `proposals.proposal_summaries`.

Moved out of adapters/proposal/projection.py with WP10 step 5: the same
derivation now feeds the calc response's "summary" block
(api/helpers/member_compute.py), the compare sides
(api/helpers/proposal_compare.py, via that block), and the publish-time
proposal_summaries write (adapters/proposal/repository.py via
projection.py) — and api/helpers must never import calculation code from
adapters/ (layering, AGENTS.md), so the shared home is models/. One
function, every consumer: the calc response and the gallery projection
cannot drift when a formula changes.

Public interface:
  build_summary_row(route, evaluation) → dict  (every §5.4 KPI column:
      route metrics, financial KPIs incl. the signed net_eur_per_year,
      the annual supply denominators (train-km, available/sold place-km,
      operating days), the demand KPIs — passengers, their sources and
      the CO2 saving (DEMAND 0.1.0) — the served country_relations, and
      the flat night-train co2_g_per_pax_km. Identity columns and
      geom_simplified are the callers' concern.)
  country_relations(route)             → list  (the served "AA__BB"
      relation keys, derived from od_pairs — §7.7's stats dimension)
  ordered_stops(trip)                  → list  (a trip's stops in travel
      order — shared with the route fingerprint's canonical extract in
      adapters/proposal/projection.py)
"""

from __future__ import annotations

from models.demand.sources import split_sources
from models.route.route import cycle_days_between, trainsets_for_cycle
from models.route.timetable import schedule_from_dict
from models.emissions.model import EMISSION_FACTORS


def ordered_stops(trip: dict) -> list[dict]:
    """A trip's stops in travel order — the first segment's origin, then
    every segment's destination. Shared by the route-metrics stop
    count/list below and the fingerprint's canonical extract
    (adapters/proposal/projection.py)."""
    segments = trip["segments"]
    return [segments[0]["from_stop"]] + [seg["to_stop"] for seg in segments]


def _terminal_times(trip: dict) -> tuple[int, int]:
    """(departure at the first stop, arrival at the last) of a full-route
    trip dict — the shape every build_summary_row() caller hands in, and
    the one ordered_stops() below already assumes."""
    first = trip["segments"][0]["from_stop"]
    last = trip["segments"][-1]["to_stop"]
    dep = first.get("departure_time_min") or 0
    arr = last.get("arrival_time_min") or dep
    return int(dep), int(arr)


def build_summary_row(route: dict, evaluation: dict) -> dict:
    """The §5.4 gallery-KPI columns for one (route, evaluation) pair —
    exactly the shape a member (and each family member) carries as "summary" and
    the publish repository merges with its identity columns
    (proposal_id, user_id, composition_id, scenario_id, name, versions)
    and geom_simplified."""
    metrics = _route_metrics(route)
    financials = _financial_kpis(evaluation)
    supply = _supply_kpis(route)
    demand = _demand_kpis(route, financials["subsidy_eur_per_year"])
    return {
        **metrics,
        **financials,
        **supply,
        **demand,
        "country_relations": country_relations(route),
        # Flat factor (decision 24) until the energy-based,
        # country-resolved model enriches it per route.
        "co2_g_per_pax_km": EMISSION_FACTORS["night_train"].g_per_pax_km,
    }


def country_relations(route: dict) -> list[str]:
    """Every country-to-country relation the route actually SERVES, as
    sorted "AA__BB" keys (§7.7 — the ranking dimension behind
    GET /api/proposals/stats).

    Read off the route's own od_pairs rather than its countries list: an
    OD pair exists only where a boarding-capable stop precedes an
    alighting-capable one (models/demand/od_matrix.py), so a country merely
    transited, or reachable only boarding-to-boarding, contributes no
    relation. Same-country pairs are dropped — a relation is between two
    countries; domestic demand is a different question.
    """
    country_by_stop = {
        stop["stop_id"]: stop.get("country_code")
        for pair in route["trip_pairs"]
        for trip in (pair["outbound"], pair["return_trip"])
        for stop in ordered_stops(trip)
    }
    relations = {
        "__".join(sorted((origin, destination)))
        for pair in route["trip_pairs"]
        for od in pair.get("od_pairs", [])
        if (origin := country_by_stop.get(od["origin_stop_id"]))
        and (destination := country_by_stop.get(od["destination_stop_id"]))
        and origin != destination
    }
    return sorted(relations)


def _route_metrics(route: dict) -> dict:
    """total_distance_km/total_time_h/avg_speed_kmh/n_stops/countries/
    stop_ids, summed across both outbound and return trips. total_time_h
    is read from each trip's already-correct
    general_parameters.route_duration_min rather than re-summed from
    segments, which would silently omit slack_time_min."""
    total_distance_m = 0
    total_duration_min = 0
    countries: set[str] = set()
    stop_ids: list[str] = []
    seen_stop_ids: set[str] = set()

    for pair in route["trip_pairs"]:
        for stop in ordered_stops(pair["outbound"]):
            if stop["stop_id"] not in seen_stop_ids:
                seen_stop_ids.add(stop["stop_id"])
                stop_ids.append(stop["stop_id"])
        for trip in (pair["outbound"], pair["return_trip"]):
            total_duration_min += trip["general_parameters"]["route_duration_min"]
            for seg in trip["segments"]:
                total_distance_m += seg["distance_m"]
                countries.update(seg["country_distance_shares"])

    total_distance_km = round(total_distance_m / 1000.0, 1)
    total_time_h = round(total_duration_min / 60.0, 2)
    avg_speed_kmh = round(total_distance_km / total_time_h, 1) if total_time_h else 0.0

    return {
        "total_distance_km": total_distance_km,
        "total_time_h": total_time_h,
        "avg_speed_kmh": avg_speed_kmh,
        "n_stops": len(stop_ids),
        "countries": sorted(countries),
        "stop_ids": stop_ids,
    }


def _financial_kpis(evaluation: dict) -> dict:
    """cost/revenue/margin per train-km from views.route.data.per_train_km,
    and from views.route.data.per_year both the signed net_eur_per_year
    (negative = the operator is short by that much, positive = surplus
    beyond the target margin) and subsidy_eur_per_year (§9 locked
    decision 12: gap to target margin, max(0, -net_eur)). The signed
    value exists so a surplus route can be shown as one rather than as
    "subsidy 0" — the UI never shows a negative subsidy to lay users.
    All already rounded by the evaluation pipeline at a finer precision
    (4dp/2dp, see evaluation_serialize.py) than the schema's
    NUMERIC(10,2)/(14,2) columns, hence the explicit round() here rather
    than passing values through as-is."""
    route_data = evaluation["views"]["route"]["data"]
    per_train_km = route_data["per_train_km"]["all"]
    per_year = route_data["per_year"]["all"]
    net_eur_per_year = round(per_year["net_eur"], 2)
    return {
        # The two non-accommodation revenue leaves, both already inside
        # net_eur/total_revenue_eur, reported on their own so a panel can
        # show what each contributed without re-deriving it. Services are
        # ordinary ticket revenue; catering is signed and already net
        # (CALC 0.9.30).
        "services_revenue_eur": round(per_year["revenue"]["services_revenue_eur"], 2),
        "catering_contribution_eur": round(
            per_year["revenue"]["catering_contribution_eur"], 2
        ),
        "cost_eur_per_train_km": round(per_train_km["total_cost_eur"], 2),
        "revenue_eur_per_train_km": round(per_train_km["total_revenue_eur"], 2),
        "margin_eur_per_train_km": round(per_train_km["net_eur"], 2),
        "net_eur_per_year": net_eur_per_year,
        "subsidy_eur_per_year": round(max(0.0, -net_eur_per_year), 2),
    }


def _supply_kpis(route: dict) -> dict:
    """The annual supply side the per-unit normalisations divide by
    (models/evaluation/views.py's normalise_per_train_km /
    normalise_per_available_place_km, re-derived here from the route
    dict): operating days from the schedule, train-km and
    capacity place-km over every trip of every pair × operating days,
    and sold place-km from the OD loads (places_sold is already annual).
    Exposed so a comparison table can show €/place-km and utilisation
    per composition without the full views block."""
    # Through the domain object so the legacy two-season shape a stored
    # payload may still carry is widened the same way route_from_dict does.
    schedule = schedule_from_dict(route["schedule"])
    operating_days = schedule.operating_days_per_year
    # ROUTE_BUILDER 0.9.35 fleet rule, from the dict: each pair's terminal
    # times are on its first and last segment. The route's fleet is the
    # busiest pair's.
    trainsets = max(
        (
            trainsets_for_cycle(
                cycle_days_between(
                    *_terminal_times(pair["outbound"]),
                    *_terminal_times(pair["return_trip"]),
                    schedule.min_turnaround_min,
                ),
                schedule,
            )
            for pair in route["trip_pairs"]
        ),
        default=0,
    )
    if not schedule.is_operating:
        trainsets = 0
    cycle_km = 0.0
    cycle_place_km = 0.0
    sold_place_km = 0.0
    # Counted over every OD pair unconditionally, unlike sold_place_km
    # below, which needs both of a pair's stops on the trip to have a
    # distance: a ticket is a passenger whether or not its ride range
    # resolves.
    passengers = sum(
        od["places_sold"]
        for pair in route["trip_pairs"]
        for od in pair.get("od_pairs", [])
    )
    for pair in route["trip_pairs"]:
        places = sum(pair["composition"]["places_by_class"].values())
        for trip in (pair["outbound"], pair["return_trip"]):
            segment_km = [seg["distance_m"] / 1000.0 for seg in trip["segments"]]
            cycle_km += sum(segment_km)
            cycle_place_km += places * sum(segment_km)
            stop_ids = [stop["stop_id"] for stop in ordered_stops(trip)]
            for od in pair.get("od_pairs", []):
                if od["trip_id"] != trip["trip_id"]:
                    continue
                if (
                    od["origin_stop_id"] not in stop_ids
                    or od["destination_stop_id"] not in stop_ids
                ):
                    continue
                start = stop_ids.index(od["origin_stop_id"])
                end = stop_ids.index(od["destination_stop_id"])
                sold_place_km += od["places_sold"] * sum(segment_km[start:end])
    return {
        "operating_days_per_year": operating_days,
        # Every operating day sees one departure per trip of every pair.
        # Rounded here only because the gallery column is an INTEGER; the
        # exact divisor the receipts need is operations.route (CALC 0.9.33).
        "departures_per_year": round(
            operating_days * sum(2 for _ in route["trip_pairs"])
        ),
        "trainsets_physical": trainsets,
        "train_km_per_year": round(cycle_km * operating_days),
        "available_place_km_per_year": round(cycle_place_km * operating_days),
        "sold_place_km_per_year": round(sold_place_km),
        "passengers_per_year": round(passengers),
    }


def _od_loads(route: dict) -> list[tuple[float, float]]:
    """(journey km, annual passengers) of every OD pair on every trip — the
    loads the source split sums over. A pair whose stops do not both
    resolve on its trip has no length and is skipped, exactly as
    _supply_kpis skips it for sold place-km."""
    loads: list[tuple[float, float]] = []
    for pair in route["trip_pairs"]:
        for trip in (pair["outbound"], pair["return_trip"]):
            segment_km = [seg["distance_m"] / 1000.0 for seg in trip["segments"]]
            stop_ids = [stop["stop_id"] for stop in ordered_stops(trip)]
            for od in pair.get("od_pairs", []):
                if od["trip_id"] != trip["trip_id"]:
                    continue
                if (
                    od["origin_stop_id"] not in stop_ids
                    or od["destination_stop_id"] not in stop_ids
                ):
                    continue
                start = stop_ids.index(od["origin_stop_id"])
                end = stop_ids.index(od["destination_stop_id"])
                loads.append((sum(segment_km[start:end]), od["places_sold"]))
    return loads


def _demand_kpis(route: dict, subsidy_eur_per_year: float) -> dict:
    """The demand KPIs from the places actually sold (DEMAND 0.1.0): the
    trips are the passengers, the trip-km their journeys, and every
    passenger is a shift from the plane, a shift from the car or an
    induced trip by journey length (models/demand/sources.py). CO2 saving:
    a shifted passenger-km saves that mode's factor less the train's own,
    an induced one costs the train's (models/emissions/model.py), in
    tonnes (/1e6 from g). demand_kpis_placeholder is FALSE — the column
    stays for readers that filter on it."""
    factors = EMISSION_FACTORS
    train_g = factors["night_train"].g_per_pax_km
    split = split_sources(_od_loads(route))
    co2_savings_t = round(
        (
            split.air_trip_km * (factors["air"].g_per_pax_km - train_g)
            + split.car_trip_km * (factors["car"].g_per_pax_km - train_g)
            - split.induced_trip_km * train_g
        )
        / 1e6,
        1,
    )
    trips = split.air_trips + split.other_trips
    return {
        "demand_trips_per_year": round(trips),
        "demand_trip_km_per_year": round(split.air_trip_km + split.other_trip_km),
        "shift_air_trips_per_year": round(split.air_trips),
        "shift_air_trip_km_per_year": round(split.air_trip_km),
        "shift_other_trips_per_year": round(split.other_trips),
        "shift_other_trip_km_per_year": round(split.other_trip_km),
        "co2_savings_t_per_year": co2_savings_t,
        "subsidy_eur_per_t_co2": (
            round(subsidy_eur_per_year / co2_savings_t, 2)
            if co2_savings_t > 0
            else None
        ),
        "demand_kpis_placeholder": False,
    }
