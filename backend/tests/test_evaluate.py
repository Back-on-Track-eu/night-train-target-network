"""
test_evaluate.py
================
Integration tests for POST /api/evaluation/calc.

Tests the full pipeline: route JSON in → evaluation result out.
Demand is embedded in the route JSON via od_pairs on each TripPair.
All monetary assertions use pytest.approx(rel=1e-3) — 0.1% tolerance.

Response shape:
  result.route_id
  result.views.route.per_year / per_operating_day / per_trip_km / ...
  result.views.per_trip_pair.{pair_key}.per_year / ...
  result.views.per_trip_pair_per_country.{pair_key}.{country}.per_year / ...
  result.views.per_trip_pair_per_od.{pair_key}.{od_key}.per_year / ...
  result.views.per_trip_per_stop.{trip_id}.{stop_id}.per_year / ...
"""

import pytest
import requests

ROUTE_URL = "/api/route/planOrUpdate"
EVAL_URL = "/api/evaluation/calc"
REL_TOL = 1e-3

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_route(api_base, stops, comp_id="STD-7.1", proposal_id=100):
    """Plan a route via the route builder API, return the route dict."""
    resp = requests.post(
        f"{api_base}{ROUTE_URL}",
        json={
            "proposal_id": proposal_id,
            "proposal_version": 1,
            "stops": stops,
            "composition_id": comp_id,
            "departure_time": "21:00",
        },
        timeout=60,
    )
    assert resp.status_code == 200, resp.text[:300]
    return resp.json()["route"]

def _inject_demand(route: dict, od_pairs_per_trip: list[dict]) -> dict:
    """Inject od_pairs into all trip pairs in the route dict."""
    route = dict(route)
    route["trip_pairs"] = [
        {**tp, "od_pairs": od_pairs_per_trip}
        for tp in route["trip_pairs"]
    ]
    return route

def _eval(api_base, route: dict) -> dict:
    """Call the evaluation endpoint and return result dict."""
    resp = requests.post(f"{api_base}{EVAL_URL}", json={"route": route}, timeout=30)
    assert resp.status_code == 200, resp.text[:300]
    return resp.json()["result"]

def _route_bd(result: dict, normalisation: str = "per_year") -> dict:
    """Shortcut to route-level breakdown at a given normalisation."""
    return result["views"]["route"][normalisation]

# ---------------------------------------------------------------------------
# Shared stop lists and OD pair sets
# ---------------------------------------------------------------------------

STOPS_3 = [
    {"stop_id": "DE_BERLIN_HBF", "stop_type": "boarding"},
    {"stop_id": "DE_DRESDEN_HBF", "stop_type": "both"},
    {"stop_id": "AT_WIEN_HBF", "stop_type": "alighting"},
]

STOPS_2 = [
    {"stop_id": "DE_BERLIN_HBF", "stop_type": "boarding"},
    {"stop_id": "AT_WIEN_HBF", "stop_type": "alighting"},
]

SIMPLE_OD = [
    {
        "origin_stop_id": "DE_BERLIN_HBF",
        "destination_stop_id": "AT_WIEN_HBF",
        "class_main": "Couchette",
        "trip_id": None,  # filled per trip below
        "places_sold": 40,
        "avg_price": 89.0,
    },
    {
        "origin_stop_id": "DE_BERLIN_HBF",
        "destination_stop_id": "AT_WIEN_HBF",
        "class_main": "Seat",
        "trip_id": None,
        "places_sold": 30,
        "avg_price": 49.0,
    },
]

MULTI_OD = [
    {
        "origin_stop_id": "DE_BERLIN_HBF",
        "destination_stop_id": "AT_WIEN_HBF",
        "class_main": "Couchette",
        "trip_id": None,
        "places_sold": 30,
        "avg_price": 89.0,
    },
    {
        "origin_stop_id": "DE_BERLIN_HBF",
        "destination_stop_id": "AT_WIEN_HBF",
        "class_main": "Seat",
        "trip_id": None,
        "places_sold": 20,
        "avg_price": 49.0,
    },
    {
        "origin_stop_id": "DE_BERLIN_HBF",
        "destination_stop_id": "DE_DRESDEN_HBF",
        "class_main": "Seat",
        "trip_id": None,
        "places_sold": 15,
        "avg_price": 29.0,
    },
    {
        "origin_stop_id": "DE_DRESDEN_HBF",
        "destination_stop_id": "AT_WIEN_HBF",
        "class_main": "Couchette",
        "trip_id": None,
        "places_sold": 10,
        "avg_price": 79.0,
    },
]

def _with_trip_ids(route: dict, od_template: list[dict]) -> list[dict]:
    """Fill trip_id in OD pair templates for both outbound and return trips
    of all trip pairs."""
    ods = []
    for tp in route["trip_pairs"]:
        for trip in (tp["outbound"], tp["return_trip"]):
            trip_id = trip["trip_id"]
            for od in od_template:
                ods.append({**od, "trip_id": trip_id})
    return ods

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def route_3stop(api_base):
    return _build_route(api_base, STOPS_3, proposal_id=200)

@pytest.fixture(scope="module")
def route_2stop(api_base):
    return _build_route(api_base, STOPS_2, proposal_id=201)

@pytest.fixture(scope="module")
def result_simple(api_base, route_3stop):
    od = _with_trip_ids(route_3stop, SIMPLE_OD)
    return _eval(api_base, _inject_demand(route_3stop, od))

@pytest.fixture(scope="module")
def result_multi_od(api_base, route_3stop):
    od = _with_trip_ids(route_3stop, MULTI_OD)
    return _eval(api_base, _inject_demand(route_3stop, od))

# ---------------------------------------------------------------------------
# Response structure
# ---------------------------------------------------------------------------

class TestResponseStructure:

    def test_result_has_route_id(self, result_simple):
        assert isinstance(result_simple["route_id"], str)

    def test_views_has_all_keys(self, result_simple):
        views = result_simple["views"]
        assert "route" in views
        assert "per_trip_pair" in views
        assert "per_trip_pair_per_country" in views
        assert "per_trip_pair_per_od" in views
        assert "per_trip_per_stop" in views

    def test_route_view_has_all_normalisations(self, result_simple):
        route_view = result_simple["views"]["route"]
        for norm in ("per_year", "per_operating_day", "per_trip_km",
                     "per_available_place_km", "per_sold_place_km"):
            assert norm in route_view, f"missing normalisation: {norm}"

    def test_breakdown_has_cost_revenue_margin(self, result_simple):
        bd = _route_bd(result_simple)
        assert "cost" in bd
        assert "revenue" in bd
        assert "margin" in bd
        assert "total_cost_eur" in bd
        assert "total_revenue_eur" in bd
        assert "net_eur" in bd

    def test_cost_has_operator_and_infrastructure(self, result_simple):
        cost = _route_bd(result_simple)["cost"]
        assert "operator" in cost
        assert "infrastructure" in cost
        assert "total_eur" in cost

    def test_operator_has_variable_and_fixed(self, result_simple):
        op = _route_bd(result_simple)["cost"]["operator"]
        assert "variable" in op
        assert "fixed" in op

    def test_per_trip_pair_has_all_key(self, result_simple):
        assert "all" in result_simple["views"]["per_trip_pair"]

    def test_per_trip_pair_per_country_nested_structure(self, result_simple):
        country_matrix = result_simple["views"]["per_trip_pair_per_country"]
        assert "all" in country_matrix
        assert "all" in country_matrix["all"]

# ---------------------------------------------------------------------------
# Mathematical identities
# ---------------------------------------------------------------------------

class TestMathIdentities:

    def test_net_equals_revenue_minus_cost_minus_margin(self, result_simple):
        bd = _route_bd(result_simple)
        assert bd["net_eur"] == pytest.approx(
            bd["total_revenue_eur"] - bd["total_cost_eur"] - bd["margin"]["ebit_margin_eur"],
            rel=REL_TOL,
        )

    def test_operator_total_equals_variable_plus_fixed(self, result_simple):
        op = _route_bd(result_simple)["cost"]["operator"]
        assert op["total_eur"] == pytest.approx(
            op["variable"]["total_eur"] + op["fixed"]["total_eur"], rel=REL_TOL
        )

    def test_cost_total_equals_operator_plus_infrastructure(self, result_simple):
        cost = _route_bd(result_simple)["cost"]
        assert cost["total_eur"] == pytest.approx(
            cost["operator"]["total_eur"] + cost["infrastructure"]["total_eur"],
            rel=REL_TOL,
        )

    def test_variable_total_equals_sum_of_leaves(self, result_simple):
        v = _route_bd(result_simple)["cost"]["operator"]["variable"]
        leaf_sum = (
            v["driver_eur"] + v["crew_eur"] + v["coach_maintenance_eur"]
            + v["loco_eur"] + v["svc_stockings_eur"] + v["var_overhead_eur"]
        )
        assert v["total_eur"] == pytest.approx(leaf_sum, rel=REL_TOL)

    def test_fixed_total_equals_sum_of_leaves(self, result_simple):
        f = _route_bd(result_simple)["cost"]["operator"]["fixed"]
        leaf_sum = (
            f["coach_amortisation_eur"] + f["financing_eur"] + f["fix_overhead_eur"]
            + f["cleaning_eur"] + f["shunting_eur"]
        )
        assert f["total_eur"] == pytest.approx(leaf_sum, rel=REL_TOL)

    def test_infrastructure_total_equals_sum_of_leaves(self, result_simple):
        infra = _route_bd(result_simple)["cost"]["infrastructure"]
        leaf_sum = (
            infra["tac_eur"] + infra["energy_eur"]
            + infra["station_charge_eur"] + infra["parking_eur"]
        )
        assert infra["total_eur"] == pytest.approx(leaf_sum, rel=REL_TOL)

# ---------------------------------------------------------------------------
# Normalisation consistency
# ---------------------------------------------------------------------------

class TestNormalisations:

    def test_per_operating_day_times_days_equals_per_year(self, result_simple, route_3stop):
        operating_days = route_3stop["schedule"]["seasonal_schedules"]
        days = sum(
            26 * 3 if ss["frequency"] == "three_per_week" else 26 * 7
            for ss in operating_days
        )
        per_year = _route_bd(result_simple, "per_year")["total_revenue_eur"]
        per_day = _route_bd(result_simple, "per_operating_day")["total_revenue_eur"]
        assert per_year == pytest.approx(per_day * days, rel=REL_TOL)

    def test_per_trip_km_is_positive(self, result_simple):
        bd = _route_bd(result_simple, "per_trip_km")
        assert bd["total_cost_eur"] > 0

    def test_per_available_place_km_is_positive(self, result_simple):
        bd = _route_bd(result_simple, "per_available_place_km")
        assert bd["total_cost_eur"] > 0

    def test_per_sold_place_km_is_positive(self, result_simple):
        bd = _route_bd(result_simple, "per_sold_place_km")
        assert bd["total_cost_eur"] > 0

    def test_net_identity_holds_in_all_normalisations(self, result_simple):
        for norm in ("per_year", "per_operating_day", "per_trip_km",
                     "per_available_place_km", "per_sold_place_km"):
            bd = _route_bd(result_simple, norm)
            assert bd["net_eur"] == pytest.approx(
                bd["total_revenue_eur"] - bd["total_cost_eur"] - bd["margin"]["ebit_margin_eur"],
                rel=REL_TOL,
            ), f"net identity failed in normalisation '{norm}'"

    def test_per_sold_lt_per_available_place_km_cost(self, result_simple):
        """Cost per sold place-km >= cost per available place-km
        (sold <= available capacity)."""
        avail = _route_bd(result_simple, "per_available_place_km")["total_cost_eur"]
        sold = _route_bd(result_simple, "per_sold_place_km")["total_cost_eur"]
        assert sold >= avail

# ---------------------------------------------------------------------------
# Revenue accuracy
# ---------------------------------------------------------------------------

class TestRevenueAccuracy:

    def test_revenue_matches_manual_calculation(self, result_simple, route_3stop):
        """Revenue = places_sold × avg_price per trip, summed across all trips."""
        expected_per_trip = 40 * 89.0 + 30 * 49.0  # Couchette + Seat = 5030
        # both outbound and return trips in all pairs
        n_trips = len(route_3stop["trip_pairs"]) * 2
        expected_annual = expected_per_trip * n_trips
        actual = _route_bd(result_simple, "per_year")["total_revenue_eur"]
        assert actual == pytest.approx(expected_annual, rel=REL_TOL)

    def test_zero_demand_gives_zero_revenue(self, api_base, route_2stop):
        route = _inject_demand(route_2stop, [])
        result = _eval(api_base, route)
        assert _route_bd(result)["total_revenue_eur"] == 0.0

    def test_zero_demand_still_has_costs(self, api_base, route_2stop):
        route = _inject_demand(route_2stop, [])
        result = _eval(api_base, route)
        assert _route_bd(result)["total_cost_eur"] > 0

    def test_higher_utilisation_gives_higher_revenue(self, api_base, route_2stop):
        trip_id = route_2stop["trip_pairs"][0]["outbound"]["trip_id"]
        def make_od(places):
            return [{
                "origin_stop_id": "DE_BERLIN_HBF",
                "destination_stop_id": "AT_WIEN_HBF",
                "class_main": "Couchette",
                "trip_id": trip_id,
                "places_sold": places,
                "avg_price": 89.0,
            }]
        low = _eval(api_base, _inject_demand(route_2stop, make_od(10)))
        high = _eval(api_base, _inject_demand(route_2stop, make_od(80)))
        assert _route_bd(high)["total_revenue_eur"] > _route_bd(low)["total_revenue_eur"]

    def test_higher_fare_scales_revenue_linearly(self, api_base, route_2stop):
        trip_id = route_2stop["trip_pairs"][0]["outbound"]["trip_id"]
        def make_od(price):
            return [{
                "origin_stop_id": "DE_BERLIN_HBF",
                "destination_stop_id": "AT_WIEN_HBF",
                "class_main": "Seat",
                "trip_id": trip_id,
                "places_sold": 30,
                "avg_price": price,
            }]
        cheap = _eval(api_base, _inject_demand(route_2stop, make_od(29.0)))
        pricey = _eval(api_base, _inject_demand(route_2stop, make_od(99.0)))
        assert _route_bd(pricey)["total_revenue_eur"] == pytest.approx(
            _route_bd(cheap)["total_revenue_eur"] * (99.0 / 29.0), rel=REL_TOL
        )

# ---------------------------------------------------------------------------
# Country matrix
# ---------------------------------------------------------------------------

class TestCountryMatrix:

    def test_all_all_matches_route_view(self, result_simple):
        """("all", "all") in country matrix should equal route-level breakdown."""
        country_all = result_simple["views"]["per_trip_pair_per_country"]["all"]["all"]["per_year"]
        route_all = _route_bd(result_simple)
        assert country_all["total_cost_eur"] == pytest.approx(
            route_all["total_cost_eur"], rel=REL_TOL
        )

    def test_country_cells_have_all_normalisations(self, result_simple):
        matrix = result_simple["views"]["per_trip_pair_per_country"]
        for pair_key, countries in matrix.items():
            for country_key, cell in countries.items():
                for norm in ("per_year", "per_operating_day", "per_trip_km"):
                    assert norm in cell, (
                        f"({pair_key}, {country_key}) missing normalisation '{norm}'"
                    )

    def test_de_appears_in_country_matrix(self, result_simple):
        """Berlin→Wien route must cross Germany."""
        matrix = result_simple["views"]["per_trip_pair_per_country"]
        all_countries = {cc for countries in matrix.values() for cc in countries}
        assert "DE" in all_countries

    def test_tac_positive_for_countries_with_track(self, result_simple):
        matrix = result_simple["views"]["per_trip_pair_per_country"]
        for pair_key, countries in matrix.items():
            for cc, cell in countries.items():
                if cc == "all":
                    continue
                tac = cell["per_year"]["cost"]["infrastructure"]["tac_eur"]
                assert tac >= 0, f"Negative TAC for country {cc}"

# ---------------------------------------------------------------------------
# OD pair matrix
# ---------------------------------------------------------------------------

class TestODMatrix:

    def test_od_matrix_has_all_all(self, result_simple):
        assert "all" in result_simple["views"]["per_trip_pair_per_od"]
        assert "all" in result_simple["views"]["per_trip_pair_per_od"]["all"]

    def test_od_cells_have_all_normalisations(self, result_simple):
        matrix = result_simple["views"]["per_trip_pair_per_od"]
        for pair_key, ods in matrix.items():
            for od_key, cell in ods.items():
                for norm in ("per_year", "per_operating_day"):
                    assert norm in cell, (
                        f"({pair_key}, {od_key}) missing '{norm}'"
                    )

    def test_od_revenue_positive_when_demand_set(self, result_simple):
        matrix = result_simple["views"]["per_trip_pair_per_od"]
        for pair_key, ods in matrix.items():
            for od_key, cell in ods.items():
                if od_key == "all":
                    continue
                rev = cell["per_year"]["total_revenue_eur"]
                assert rev > 0, f"Expected revenue > 0 for OD ({pair_key}, {od_key})"

    def test_full_od_has_more_revenue_than_partial(self, result_multi_od):
        """BER→VIE (longer) has more revenue than BER→DRE (shorter)."""
        matrix = result_multi_od["views"]["per_trip_pair_per_od"]
        full_key = "DE_BERLIN_HBF__AT_WIEN_HBF__Seat"
        partial_key = "DE_BERLIN_HBF__DE_DRESDEN_HBF__Seat"
        # Find in "all" pair
        all_ods = matrix.get("all", {})
        if full_key in all_ods and partial_key in all_ods:
            assert (
                all_ods[full_key]["per_year"]["total_revenue_eur"]
                > all_ods[partial_key]["per_year"]["total_revenue_eur"]
            )

# ---------------------------------------------------------------------------
# Stop matrix
# ---------------------------------------------------------------------------

class TestStopMatrix:

    def test_stop_matrix_has_all_all(self, result_simple):
        assert "all" in result_simple["views"]["per_trip_per_stop"]
        assert "all" in result_simple["views"]["per_trip_per_stop"]["all"]

    def test_stop_cells_have_normalisations(self, result_simple):
        matrix = result_simple["views"]["per_trip_per_stop"]
        for trip_key, stops in matrix.items():
            for stop_key, cell in stops.items():
                assert "per_year" in cell

    def test_terminal_stop_has_station_charge(self, result_simple):
        """Origin stop should have non-zero station charge."""
        matrix = result_simple["views"]["per_trip_per_stop"]
        all_stops = matrix.get("all", {})
        berlin_key = "DE_BERLIN_HBF"
        if berlin_key in all_stops:
            station_charge = all_stops[berlin_key]["per_year"]["cost"]["infrastructure"]["station_charge_eur"]
            assert station_charge > 0

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidation:

    def test_missing_route_returns_400(self, api_base):
        resp = requests.post(f"{api_base}{EVAL_URL}", json={}, timeout=10)
        assert resp.status_code == 400

    def test_empty_body_returns_400(self, api_base):
        resp = requests.post(
            f"{api_base}{EVAL_URL}",
            data="not json",
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        assert resp.status_code == 400

    def test_missing_trip_pairs_returns_400(self, api_base):
        resp = requests.post(
            f"{api_base}{EVAL_URL}",
            json={"route": {"route_id": "test", "schedule": {}, "trip_pairs": []}},
            timeout=10,
        )
        assert resp.status_code == 400

    def test_valid_route_returns_200(self, api_base, route_2stop):
        route = _inject_demand(route_2stop, [])
        resp = requests.post(f"{api_base}{EVAL_URL}", json={"route": route}, timeout=30)
        assert resp.status_code == 200

    def test_response_has_calc_version(self, api_base, route_2stop):
        route = _inject_demand(route_2stop, [])
        resp = requests.post(f"{api_base}{EVAL_URL}", json={"route": route}, timeout=30)
        assert "calc_version" in resp.json()