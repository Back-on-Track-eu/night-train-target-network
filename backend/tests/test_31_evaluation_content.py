"""
test_31_evaluation_content.py
=============================
Content-logic tests for POST /api/evaluation/calc — the numbers, not just
the shape.

The core idea: recompute cost components BY HAND from (a) the physics in the
posted route JSON and (b) the parameter values served by /api/params/*, then
require the evaluation to match. This pins the actual cost model
(models/evaluation/calc.py) end to end:

  tac_eur            = Σ segments Σ countries  km × share × tac_rate  × days
  energy_eur         = Σ segments Σ countries  kWh × share × price   × days
  station_charge_eur = Σ trips Σ stop calls    stop_charge           × days
  coach_maintenance  = maint_rate × total km                          × days
  ticket revenue     = Σ ODs  places_sold × avg_price   (places are ANNUAL)

Also covers: mathematical identities of the breakdown tree, exact
normalisation divisors (unweighted place-km — density is NOT applied in
normalisation), demand behaviour, matrix consistency, and the scenario
override (what-if pins DE track infra v1, tac 3.10 < base 5.40).
"""

import pytest
import requests

from tests.helpers import (
    all_trips,
    country_km,
    evaluate,
    inject_demand,
    operating_days,
    route_bd,
    stop_times,
    trip_distance_km,
)

REL_TOL = 1e-3  # EUR leaves are rounded to 2dp — 0.1% covers that comfortably


# =============================================================================
# Parameter rate fixtures — fetched from the params API, so these tests also
# pin cross-endpoint consistency (params rates in == evaluation costs out)
# =============================================================================

@pytest.fixture(scope="module")
def track_rates(api_base):
    """{country_code: {'tac': €/train-km, 'energy_price': €/kWh}} from
    GET /api/params/TrackInfrastructures (base scenario)."""
    body = requests.get(f"{api_base}/api/params/TrackInfrastructures", timeout=15).json()
    return {
        t["country_code"]: {
            "tac": t["tac_eur_train_km"]["value"],
            "energy_price": t["energy_price_eur_kwh"]["value"],
        }
        for t in body["track_infrastructures"]
    }


@pytest.fixture(scope="module")
def stop_charges(api_base):
    """{stop_id: station charge €/call} from GET /api/params/StopInfrastructures."""
    body = requests.get(f"{api_base}/api/params/StopInfrastructures", timeout=15).json()
    return {s["stop_id"]: s["stop_charge_eur"]["value"] for s in body["stops"]}


@pytest.fixture(scope="module")
def maint_rates(api_base):
    """{comp_id: coach_maint_eur_km} from GET /api/params/compositions."""
    body = requests.get(f"{api_base}/api/params/compositions", timeout=15).json()
    return {c["comp_id"]: c["variable_km"]["coach_maint_eur_km"]
            for c in body["compositions"]}


@pytest.fixture(scope="module")
def eval_zero(api_base, route_berlin_wien):
    """Evaluation of the 2-stop route with zero demand (empty od_pairs)."""
    return evaluate(api_base, inject_demand(route_berlin_wien, []))


# =============================================================================
# Cost components vs manual recomputation
# =============================================================================

class TestCostRecomputation:

    def test_tac_matches_manual_calculation(self, eval_standard, track_rates):
        """Annual TAC equals Σ (per-country km × country tac rate) over all
        trips, annualised — mirrors _calc_segment_cost() exactly."""
        costed, result = eval_standard
        days = operating_days(costed)

        expected = sum(
            km * track_rates[cc]["tac"]
            for trip in all_trips(costed)
            for cc, km in country_km(trip).items()
        ) * days

        actual = route_bd(result)["cost"]["infrastructure"]["tac_eur"]
        assert actual == pytest.approx(expected, rel=REL_TOL)

    def test_energy_cost_matches_manual_calculation(self, eval_standard, track_rates):
        """Annual energy cost equals Σ (segment kWh × country distance share
        × country energy price), annualised."""
        costed, result = eval_standard
        days = operating_days(costed)

        expected = sum(
            seg["energy_kwh"] * share * track_rates[cc]["energy_price"]
            for trip in all_trips(costed)
            for seg in trip["segments"]
            for cc, share in seg["country_distance_shares"].items()
        ) * days

        actual = route_bd(result)["cost"]["infrastructure"]["energy_eur"]
        assert actual == pytest.approx(expected, rel=REL_TOL)

    def test_station_charge_matches_manual_calculation(self, eval_standard, stop_charges):
        """Annual station charges equal Σ stop charge per stop call (every
        trip pays every stop it calls at once), annualised."""
        costed, result = eval_standard
        days = operating_days(costed)

        expected = sum(
            stop_charges[st["stop_id"]]
            for trip in all_trips(costed)
            for st in stop_times(trip)
        ) * days

        actual = route_bd(result)["cost"]["infrastructure"]["station_charge_eur"]
        assert actual == pytest.approx(expected, rel=REL_TOL)

    def test_coach_maintenance_matches_manual_calculation(self, eval_standard, maint_rates):
        """Annual coach maintenance equals maint rate × total km across all
        trips, annualised."""
        costed, result = eval_standard
        days = operating_days(costed)
        comp_id = costed["trip_pairs"][0]["composition_id"]

        total_km = sum(trip_distance_km(t) for t in all_trips(costed))
        expected = maint_rates[comp_id] * total_km * days

        actual = route_bd(result)["cost"]["operator"]["variable"]["coach_maintenance_eur"]
        assert actual == pytest.approx(expected, rel=REL_TOL)

    def test_revenue_matches_manual_calculation(self, eval_standard):
        """Annual revenue equals Σ places_sold × avg_price over all OD pairs
        — places_sold is annual, so no operating-days multiplier applies."""
        costed, result = eval_standard
        expected = sum(
            od["places_sold"] * od["avg_price"]
            for tp in costed["trip_pairs"]
            for od in tp["od_pairs"]
        )
        assert route_bd(result)["total_revenue_eur"] == pytest.approx(expected, rel=REL_TOL)


# =============================================================================
# Breakdown tree identities
# =============================================================================

class TestBreakdownIdentities:

    def test_net_equals_revenue_minus_cost_minus_margin(self, eval_standard):
        _, result = eval_standard
        bd = route_bd(result)
        assert bd["net_eur"] == pytest.approx(
            bd["total_revenue_eur"] - bd["total_cost_eur"] - bd["margin"]["ebit_margin_eur"],
            rel=REL_TOL,
        )

    def test_cost_total_equals_operator_plus_infrastructure(self, eval_standard):
        _, result = eval_standard
        cost = route_bd(result)["cost"]
        assert cost["total_eur"] == pytest.approx(
            cost["operator"]["total_eur"] + cost["infrastructure"]["total_eur"], rel=REL_TOL
        )

    def test_operator_total_equals_variable_plus_fixed(self, eval_standard):
        _, result = eval_standard
        op = route_bd(result)["cost"]["operator"]
        assert op["total_eur"] == pytest.approx(
            op["variable"]["total_eur"] + op["fixed"]["total_eur"], rel=REL_TOL
        )

    def test_variable_total_equals_sum_of_leaves(self, eval_standard):
        _, result = eval_standard
        v = route_bd(result)["cost"]["operator"]["variable"]
        leaf_sum = (v["driver_eur"] + v["crew_eur"] + v["coach_maintenance_eur"]
                    + v["loco_eur"] + v["svc_stockings_eur"] + v["var_overhead_eur"])
        assert v["total_eur"] == pytest.approx(leaf_sum, rel=REL_TOL)

    def test_fixed_total_equals_sum_of_leaves(self, eval_standard):
        _, result = eval_standard
        f = route_bd(result)["cost"]["operator"]["fixed"]
        leaf_sum = (f["coach_amortisation_eur"] + f["financing_eur"]
                    + f["fix_overhead_eur"] + f["cleaning_eur"] + f["shunting_eur"])
        assert f["total_eur"] == pytest.approx(leaf_sum, rel=REL_TOL)

    def test_infrastructure_total_equals_sum_of_leaves(self, eval_standard):
        _, result = eval_standard
        infra = route_bd(result)["cost"]["infrastructure"]
        leaf_sum = (infra["tac_eur"] + infra["energy_eur"]
                    + infra["station_charge_eur"] + infra["parking_eur"])
        assert infra["total_eur"] == pytest.approx(leaf_sum, rel=REL_TOL)

    def test_net_identity_holds_in_all_normalisations(self, eval_standard):
        """Normalisation divides every leaf by the same denominator — the net
        identity must survive it in every view."""
        _, result = eval_standard
        for norm in ("per_year", "per_operating_day", "per_trip_km",
                     "per_available_place_km", "per_sold_place_km"):
            bd = route_bd(result, norm)
            assert bd["net_eur"] == pytest.approx(
                bd["total_revenue_eur"] - bd["total_cost_eur"] - bd["margin"]["ebit_margin_eur"],
                rel=REL_TOL,
            ), f"net identity failed in normalisation '{norm}'"


# =============================================================================
# Normalisation divisors — recomputed exactly
# =============================================================================

class TestNormalisationDivisors:

    def test_per_operating_day_times_days_equals_per_year(self, eval_standard):
        """per_operating_day × operating days (from the route's own embedded
        schedule) reproduces per_year."""
        costed, result = eval_standard
        days = operating_days(costed)
        per_year = route_bd(result, "per_year")["total_cost_eur"]
        per_day = route_bd(result, "per_operating_day")["total_cost_eur"]
        assert per_year == pytest.approx(per_day * days, rel=REL_TOL)

    def test_per_trip_km_divisor(self, eval_standard):
        """per_trip_km divides by the summed distance of ALL trips (outbound
        + return both counted)."""
        costed, result = eval_standard
        total_km = sum(trip_distance_km(t) for t in all_trips(costed))
        per_year = route_bd(result, "per_year")["total_cost_eur"]
        per_km = route_bd(result, "per_trip_km")["total_cost_eur"]
        assert per_year == pytest.approx(per_km * total_km, rel=REL_TOL)

    def test_per_available_place_km_divisor_is_unweighted(self, eval_standard):
        """per_available_place_km divides by Σ (total places × segment km) —
        UNWEIGHTED capacity. Class density is exposed as data on compositions
        but deliberately NOT applied in this divisor (see views.py:
        normalise_per_available_place_km)."""
        costed, result = eval_standard
        places = sum(costed["trip_pairs"][0]["composition"]["places_by_class"].values())
        available_pkm = places * sum(trip_distance_km(t) for t in all_trips(costed))

        per_year = route_bd(result, "per_year")["total_cost_eur"]
        per_pkm = route_bd(result, "per_available_place_km")["total_cost_eur"]
        assert per_year == pytest.approx(per_pkm * available_pkm, rel=REL_TOL)

    def test_per_sold_place_km_divisor(self, eval_standard):
        """per_sold_place_km divides by Σ (places_sold × OD segment-range km).
        STANDARD_DEMAND is directional and spans each full trip, so sold
        place-km is simply Σ trips (70 places × trip km)."""
        costed, result = eval_standard
        places_per_trip = 40 + 30  # STANDARD_DEMAND: Couchette + Seat
        sold_pkm = sum(places_per_trip * trip_distance_km(t) for t in all_trips(costed))

        per_year = route_bd(result, "per_year")["total_cost_eur"]
        per_pkm = route_bd(result, "per_sold_place_km")["total_cost_eur"]
        assert per_year == pytest.approx(per_pkm * sold_pkm, rel=REL_TOL)

    def test_per_sold_cost_exceeds_per_available_at_partial_load(self, eval_standard):
        """Partial load → sold place-km < available place-km → cost per sold
        unit is strictly higher than per available unit."""
        _, result = eval_standard
        avail = route_bd(result, "per_available_place_km")["total_cost_eur"]
        sold = route_bd(result, "per_sold_place_km")["total_cost_eur"]
        assert sold > avail


# =============================================================================
# Demand behaviour
# =============================================================================

class TestDemandBehaviour:

    @staticmethod
    def _single_od(route, places, price):
        trip_id = route["trip_pairs"][0]["outbound"]["trip_id"]
        return [{"origin_stop_id": "DE_BERLIN_HBF",
                 "destination_stop_id": "AT_WIEN_HBF",
                 "class_main": "Seat", "trip_id": trip_id,
                 "places_sold": places, "avg_price": price}]

    def test_zero_demand_gives_zero_revenue_but_positive_cost(self, eval_zero):
        """No demand → zero revenue; running the train still costs money."""
        bd = route_bd(eval_zero)
        assert bd["total_revenue_eur"] == 0.0
        assert bd["total_cost_eur"] > 0

    def test_zero_demand_per_sold_view_is_zeroed(self, eval_zero):
        """Zero sold place-km → divisor 0 → per_sold view collapses to a zero
        breakdown rather than dividing by zero."""
        sold_bd = route_bd(eval_zero, "per_sold_place_km")
        assert sold_bd["total_revenue_eur"] == 0.0
        assert sold_bd["total_cost_eur"] == 0.0

    def test_zero_demand_per_available_still_positive(self, eval_zero):
        """Capacity-based normalisation is demand-independent — positive cost
        per available place-km even with zero demand."""
        assert route_bd(eval_zero, "per_available_place_km")["total_cost_eur"] > 0

    def test_fare_scales_revenue_linearly(self, api_base, route_berlin_wien):
        """Revenue is linear in avg_price: tripling the fare triples revenue
        exactly (places held constant)."""
        cheap = evaluate(api_base, inject_demand(
            route_berlin_wien, self._single_od(route_berlin_wien, 30, 33.0)))
        pricey = evaluate(api_base, inject_demand(
            route_berlin_wien, self._single_od(route_berlin_wien, 30, 99.0)))
        assert route_bd(pricey)["total_revenue_eur"] == pytest.approx(
            route_bd(cheap)["total_revenue_eur"] * 3.0, rel=REL_TOL
        )


# =============================================================================
# Matrix views — consistency with the route view
# =============================================================================

class TestMatrixConsistency:

    def test_country_all_all_equals_route_view(self, eval_standard):
        """The (all, all) country matrix cell equals the route-level breakdown."""
        _, result = eval_standard
        cell = result["views"]["per_trip_pair_per_country"]["data"]["all"]["all"]
        assert cell["values"]["per_year"]["total_cost_eur"] == pytest.approx(
            route_bd(result)["total_cost_eur"], rel=REL_TOL
        )

    def test_country_tac_cells_sum_to_total(self, eval_standard):
        """Per-country TAC cells (in the 'all' trip-pair row) sum back to the
        route-level TAC — the country allocation loses nothing."""
        _, result = eval_standard
        countries = result["views"]["per_trip_pair_per_country"]["data"]["all"]
        tac_sum = sum(
            cell["values"]["per_year"]["cost"]["infrastructure"]["tac_eur"]
            for cc, cell in countries.items()
            if cc != "all"
        )
        assert tac_sum == pytest.approx(
            route_bd(result)["cost"]["infrastructure"]["tac_eur"], rel=REL_TOL
        )

    def test_traversed_countries_appear_in_matrix(self, eval_standard):
        """Every country the route traverses appears as a country key."""
        costed, result = eval_standard
        matrix = result["views"]["per_trip_pair_per_country"]["data"]
        matrix_countries = {cc for row in matrix.values() for cc in row if cc != "all"}
        traversed = {cc for t in all_trips(costed) for cc in country_km(t)}
        assert traversed <= matrix_countries

    def test_od_matrix_carries_directional_keys_with_revenue(self, eval_standard):
        """The directional demand produces both direction OD keys
        (origin__destination__class), each with positive annual revenue."""
        _, result = eval_standard
        all_ods = result["views"]["per_trip_pair_per_od"]["data"]["all"]
        for key in ("DE_BERLIN_HBF__AT_WIEN_HBF__Couchette",
                    "AT_WIEN_HBF__DE_BERLIN_HBF__Couchette"):
            assert key in all_ods, f"OD key missing: {key}"
            assert all_ods[key]["values"]["per_year"]["total_revenue_eur"] > 0

    def test_stop_matrix_terminal_has_station_charge(self, eval_standard):
        """The origin stop carries a positive station charge in the stop matrix."""
        _, result = eval_standard
        all_stops = result["views"]["per_trip_per_stop"]["data"]["all"]
        berlin = all_stops["DE_BERLIN_HBF"]
        charge = berlin["values"]["per_year"]["cost"]["infrastructure"]["station_charge_eur"]
        assert charge > 0


# =============================================================================
# Scenario override
# =============================================================================

class TestScenarioOverride:

    def test_whatif_override_lowers_tac(self, api_base, route_berlin_wien, whatif_scenario):
        """Costing the SAME base-planned route under the what-if scenario
        (track infra v1: DE tac 3.10 instead of 5.40) yields strictly lower
        TAC — the override actually swaps the parameter version, and only
        for the table the scenario re-pins."""
        base = evaluate(api_base, inject_demand(route_berlin_wien, []))
        whatif = evaluate(api_base, inject_demand(route_berlin_wien, []),
                          scenario_id=whatif_scenario["scenario_id"])

        tac_base = route_bd(base)["cost"]["infrastructure"]["tac_eur"]
        tac_whatif = route_bd(whatif)["cost"]["infrastructure"]["tac_eur"]
        assert tac_whatif < tac_base

        # Stop infrastructure is pinned identically in both scenarios —
        # station charges must be unchanged by the override.
        sc_base = route_bd(base)["cost"]["infrastructure"]["station_charge_eur"]
        sc_whatif = route_bd(whatif)["cost"]["infrastructure"]["station_charge_eur"]
        assert sc_whatif == pytest.approx(sc_base, rel=REL_TOL)
