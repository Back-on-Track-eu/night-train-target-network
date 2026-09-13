"""
test_30_evaluation_content.py
=============================
Content-logic tests for the evaluation model (models/evaluation/calc.py)
— the numbers, not just the shape.

Controlled demand scenarios need an override POST /api/proposal/calc
deliberately doesn't offer (it always builds fresh and runs the stopgap
demand model internally), so these tests call the model layer directly
(tests/helpers.py:compute_evaluation_domain() — route_from_dict() ->
add_directional_domain_demand() -> models.pipeline.
evaluate_and_build_views() -> views), skipping HTTP for the compute step
entirely; only route_berlin_wien/route_berlin_dresden_wien themselves
still come from a live POST /api/proposal/calc (session-scoped fixtures,
conftest.py). See adapters/proposal/README.md for the decision.

The core idea: recompute cost components BY HAND from (a) the physics in the
posted route JSON and (b) the parameter values served by /api/params/*, then
require the evaluation to match. This pins the actual cost model
(models/evaluation/calc.py) end to end:

  tac_eur            = Σ segments Σ countries  km × share × tac_rate  × days
  energy_eur         = Σ segments Σ countries  kWh × (day|night price)
                                               + catenary per km/gtkm  × days
  shunting_eur       = Σ shunting events       all-in rate           × days
  parking_eur        = Σ parkings  basis(layover, length) + hotel power × days
  station_charge_eur = Σ trips Σ stop calls    stop_charge           × days
  coach_maintenance  = maint_rate × total km                          × days
  ticket revenue     = Σ ODs  places_sold × avg_price   (places are ANNUAL)

Also covers: mathematical identities of the breakdown tree, exact
normalisation divisors (unweighted place-km — density is NOT applied in
normalisation), demand behaviour, matrix consistency, the scenario
override (what-if pins DE track infra v1, tac 3.10 < base 5.40), and —
since CALC 0.9.26 — that evaluating under NO_MEASURES changes nothing.
"""

import math

import pytest
import requests

from models.demand.model import FARE_CLASS_MAINS
from tests.helpers import (
    add_directional_domain_demand,
    all_trips,
    compute_evaluation_domain,
    country_km,
    operating_days,
    route_bd,
    stop_times,
    trip_distance_km,
)

REL_TOL = 1e-3  # annual EUR leaves are 2dp; normalised views round finer, scaled
# to their divisor (NORMALISATION_NDIGITS) — 0.1% covers all of them comfortably


# =============================================================================
# Parameter rate fixtures — fetched from the params API, so these tests also
# pin cross-endpoint consistency (params rates in == evaluation costs out)
# =============================================================================


@pytest.fixture(scope="module")
def track_rates(api_base):
    """{country_code: {'tac': €/train-km, 'energy_price': €/kWh}} from
    GET /api/params/TrackInfrastructures (base scenario).

    Both figures are the API's headline per-country values. Neither is what
    the cost model prices from any more — track access is a component sum
    (CALC 0.9.18) and energy is banded with a supply charge on top (0.9.21),
    and both recomputations below read the components off the loader instead.
    Kept because it pins the cross-endpoint contract this file exists to
    check: the same parameter version the evaluation used is the one /params
    serves.
    """
    body = requests.get(
        f"{api_base}/api/params/TrackInfrastructures", timeout=15
    ).json()
    return {
        t["country_code"]: {
            "tac": t["tac_eur_train_km"]["value"],
            "energy_price": t["energy_price_eur_kwh"]["value"],
        }
        for t in body["track_infrastructures"]
    }


@pytest.fixture(scope="module")
def stop_charges(api_base):
    """{stop_id: station charge €/call} from GET /api/params/StopInfrastructures
    — the fixed part only. A per-tonne stop (Czechia) reports 0.0 here and
    its rate in per_tonne_eur; see TestPerTonneStationCharge."""
    body = requests.get(f"{api_base}/api/params/StopInfrastructures", timeout=15).json()
    return {s["stop_id"]: s["stop_charge_eur"]["value"] for s in body["stops"]}


@pytest.fixture(scope="module")
def maint_rates(api_base):
    """{composition_id: coach_maint_eur_km} from GET /api/params/compositions."""
    body = requests.get(f"{api_base}/api/params/compositions", timeout=15).json()
    return {
        c["composition_id"]: c["variable_km"]["coach_maint_eur_km"]
        for c in body["compositions"]
    }


@pytest.fixture(scope="module")
def overhead_quotas(api_base):
    """{composition_id: fix_overhead_quota_per} from GET /api/params/
    compositions — the operator factor the Overhead tab renders next to
    the euros. The quota is an operator property, so it is read off the
    catalog's operators section by way of each composition's operator_id."""
    body = requests.get(f"{api_base}/api/params/compositions", timeout=15).json()
    by_operator = {
        o["operator_id"]: o["fix_overhead_quota_per"] for o in body["operators"]
    }
    return {
        c["composition_id"]: by_operator[c["operator_id"]] for c in body["compositions"]
    }


@pytest.fixture(scope="module")
def eval_zero(loader, route_berlin_wien):
    """Evaluation of the 2-stop route with zero demand (empty od_pairs)."""
    return compute_evaluation_domain(route_berlin_wien, loader, demand=[])[1]


# =============================================================================
# Cost components vs manual recomputation
# =============================================================================


class TestCostRecomputation:
    def test_params_endpoint_serves_the_rates_the_evaluation_priced_from(
        self, eval_standard, loader, track_rates
    ):
        """The headline per-country figures /params serves are the ones the
        evaluation's own loader resolved, at the same pinned version.

        Neither recomputation below reads these — track access and energy are
        both component models now — so without this the two endpoints could
        drift apart unnoticed: a stale parameter version served to the
        frontend while the evaluation prices from another.
        """
        costed, _ = eval_standard
        tracks = loader.build_all_tracks(costed["scenario_id"])
        checked = 0
        for cc, rates in track_rates.items():
            track = tracks.get(cc)
            if track is None:
                continue
            assert rates["energy_price"] == pytest.approx(
                track.energy_price_eur_kwh, rel=1e-4
            ), f"{cc}: /params energy price differs from the loader's"
            assert rates["tac"] == pytest.approx(track.tac_eur_train_km, rel=1e-4)
            checked += 1
        assert checked > 20, f"only {checked} countries compared — fixture too thin"

    def test_tac_matches_manual_calculation(self, eval_standard, loader):
        """Annual TAC equals Σ over every country run of its own calibrated
        component terms, annualised.

        Recomputed here from the loader's TrackInfrastructure objects
        rather than from a single per-kilometre rate: since CALC 0.9.18 the
        charge is a component sum, and no one rate exists to multiply
        distance by. The night and peak SHARES are the one thing not
        recomputed — that is clock arithmetic, pinned exhaustively in
        test_73_calc_tac_units.py — so this test reads them back off the
        breakdown and checks the money built on top of them, which is what
        the annualisation and view aggregation path can actually get wrong.
        """
        costed, result = eval_standard
        days = operating_days(costed)
        tracks = loader.build_all_tracks(costed["scenario_id"])
        composition = next(
            c
            for c in loader.build_all_compositions(costed["scenario_id"]).all().values()
            if c.comp_id == costed["trip_pairs"][0]["composition_id"]
        )

        # The Berlin-Wien corridor levies no per-stop, revenue-share or
        # seat-km term and crosses no charged passage, so the whole charge
        # is per-kilometre: train-km at the day or night rate, plus
        # gross-tonne-km, plus Austria's congestion surcharge on the
        # peak-overlapping share.
        expected = 0.0
        for trip in all_trips(costed):
            for cc, km in country_km(trip).items():
                track = tracks.get(cc)
                if track is None:
                    continue  # UNK — open water, no infrastructure manager
                assert track.tac_per_stop is None and track.tac_revenue_share is None, (
                    f"{cc} gained a non-distance TAC term — this test's "
                    "per-kilometre shortcut no longer holds"
                )
                rate = track.tac_b_day or 0.0
                if track.tac_night_mode == "time_band":
                    # Germany widens the night rate to the whole run for a
                    # train carrying night accommodation, which every
                    # sleeper composition on this corridor does.
                    assert composition.has_night_accommodation
                    rate = track.tac_b_night if track.tac_b_night is not None else rate
                expected += km * rate
                expected += (
                    km * (track.tac_gamma or 0.0) * composition.total_gross_weight_t
                )

        actual = route_bd(result)["cost"]["infrastructure"]["tac_eur"]
        congestion = actual / days - expected
        # Austria's surcharge is the only remaining term; it is applied to
        # the peak-overlapping share of a run, so it is non-negative and
        # bounded by charging the whole Austrian distance at the full rate.
        at_km = sum(country_km(trip).get("AT", 0.0) for trip in all_trips(costed))
        at_surcharge = tracks.get("AT").tac_congestion_surcharge_eur_km or 0.0
        assert -1e-6 <= congestion <= at_km * at_surcharge + 1e-6, (
            f"unexplained TAC residual of {congestion:.2f} EUR/trip beyond "
            "the recomputed per-kilometre terms"
        )
        assert actual == pytest.approx((expected + congestion) * days, rel=REL_TOL)

    def test_energy_cost_matches_manual_calculation(self, eval_standard, loader):
        """Annual energy cost equals Σ over every country run of the energy it
        drew at that country's price, plus what the country charges for
        supplying it, annualised.

        Recomputed from the loader's TrackInfrastructure objects rather than
        from one price per country: since CALC 0.9.21 a banded country prices
        the in-band share of a run at its night rate, and a country levying a
        catenary charge adds a per-kilometre or per-gross-tonne-km term on
        top. Same shape as the TAC test above, and for the same reason — the
        night SHARE is clock arithmetic, pinned exhaustively in
        test_75_calc_energy_price_units.py, so here the bill is bracketed
        between pricing the whole run at the day rate and pricing it all at
        the night rate. That bracket is what the annualisation and view
        aggregation path can actually get wrong; a collapsed bracket (no
        banded country on the corridor) becomes an equality on its own.
        """
        costed, result = eval_standard
        days = operating_days(costed)
        tracks = loader.build_all_tracks(costed["scenario_id"])
        composition = next(
            c
            for c in loader.build_all_compositions(costed["scenario_id"]).all().values()
            if c.comp_id == costed["trip_pairs"][0]["composition_id"]
        )

        all_day = all_night = 0.0
        for trip in all_trips(costed):
            for seg in trip["segments"]:
                for cc, share in seg["country_distance_shares"].items():
                    track = tracks.get(cc)
                    if track is None:
                        continue  # UNK — open water, no supplier to pay
                    kwh = seg["energy_kwh"] * share
                    km = seg["distance_m"] / 1000.0 * share
                    catenary = (track.energy_catenary_eur_train_km or 0.0) * km + (
                        track.energy_catenary_eur_gross_tonne_km or 0.0
                    ) * composition.total_gross_weight_t * km
                    night_rate = (
                        track.energy_price_night_eur_kwh
                        if track.energy_price_night_eur_kwh is not None
                        else track.energy_price_eur_kwh
                    )
                    all_day += kwh * track.energy_price_eur_kwh + catenary
                    all_night += kwh * night_rate + catenary

        actual = route_bd(result)["cost"]["infrastructure"]["energy_eur"]
        assert all_night * days - 1e-6 <= actual <= all_day * days + 1e-6, (
            f"energy cost {actual:.2f} outside the day/night bracket "
            f"[{all_night * days:.2f}, {all_day * days:.2f}]"
        )
        if all_night == pytest.approx(all_day):
            # No banded tariff on this corridor — the bracket is a single
            # number, so the recomputation is exact.
            assert actual == pytest.approx(all_day * days, rel=REL_TOL)

    def test_shunting_matches_manual_calculation(self, eval_standard, loader):
        """Annual shunting equals one all-in event charge per Shunting event at
        the event's own country rate, annualised per trip.

        The event count is the calibration's reference rotation made concrete:
        two movements per turnaround, which the route builder emits as one
        Shunting from each trip that ends or starts at a terminal. If that ever
        drifts to one or four per turnaround, this is the test that notices.
        """
        costed, result = eval_standard
        days = operating_days(costed)
        tracks = loader.build_all_tracks(costed["scenario_id"])

        expected = (
            sum(
                tracks.get(s["country_code"]).shunting_eur_event
                for s in costed["shuntings"]
            )
            * days
        )
        actual = route_bd(result)["cost"]["operator"]["fixed"]["shunting_eur"]
        assert actual == pytest.approx(expected, rel=REL_TOL)

        # Two per terminal, and a trip pair has two terminals.
        assert len(costed["shuntings"]) == 4, (
            f"{len(costed['shuntings'])} shunting events on a trip pair — the "
            "reference rotation is two movements per turnaround"
        )

    def test_parking_matches_manual_calculation(self, eval_standard, loader):
        """Annual stabling equals, per parking location, the country's own
        basis applied to the scheduled layover and the train's length, plus
        hotel power on the actual stabled hours.

        Recomputed from the loader rather than from one rate per country: since
        CALC 0.9.22 the flat track_parking_eur_day column is display-only and
        four different arithmetics exist. The four bases are pinned exhaustively
        in test_76_calc_facility_units.py; what this adds is that the layover
        the route builder scheduled is the one the cost model billed, and that
        the annualisation is per operating day.
        """
        costed, result = eval_standard
        days = operating_days(costed)
        tracks = loader.build_all_tracks(costed["scenario_id"])
        composition = next(
            c
            for c in loader.build_all_compositions(costed["scenario_id"]).all().values()
            if c.comp_id == costed["trip_pairs"][0]["composition_id"]
        )

        expected = 0.0
        for p in costed["parkings"]:
            track = tracks.get(p["country_code"])
            hours = p["hours"]
            assert hours > 0, (
                f"parking at {p['stop_id']} has no layover — a trip pair "
                "stables at both of its terminals"
            )
            billable = max(0.0, hours - (track.parking_free_hours or 0.0))
            basis = track.parking_basis
            if basis == "per_event":
                facility = track.parking_eur_event or 0.0
            elif basis == "per_hour" and billable > 0:
                facility = (track.parking_eur_hour or 0.0) * math.ceil(billable)
            elif basis == "per_metre_day" and billable > 0:
                facility = (
                    (track.parking_eur_metre_day or 0.0)
                    * composition.total_length_m
                    * math.ceil(billable / 24.0)
                )
            else:
                facility = 0.0
            hotel = (track.parking_hotel_power_eur_hour or 0.0) * hours
            expected += facility + hotel

        actual = route_bd(result)["cost"]["infrastructure"]["parking_eur"]
        assert actual == pytest.approx(expected * days, rel=REL_TOL)

    def test_station_charge_matches_manual_calculation(
        self, eval_standard, stop_charges
    ):
        """Annual station charges equal Σ stop charge per stop call (every
        trip pays every stop it calls at once), annualised."""
        costed, result = eval_standard
        days = operating_days(costed)

        expected = (
            sum(
                stop_charges[st["stop_id"]]
                for trip in all_trips(costed)
                for st in stop_times(trip)
            )
            * days
        )

        actual = route_bd(result)["cost"]["infrastructure"]["station_charge_eur"]
        assert actual == pytest.approx(expected, rel=REL_TOL)

    def test_coach_maintenance_matches_manual_calculation(
        self, eval_standard, maint_rates
    ):
        """Annual coach maintenance equals maint rate × total km across all
        trips, annualised."""
        costed, result = eval_standard
        days = operating_days(costed)
        comp_id = costed["trip_pairs"][0]["composition_id"]

        total_km = sum(trip_distance_km(t) for t in all_trips(costed))
        expected = maint_rates[comp_id] * total_km * days

        actual = route_bd(result)["cost"]["operator"]["variable"][
            "coach_maintenance_eur"
        ]
        assert actual == pytest.approx(expected, rel=REL_TOL)

    def test_revenue_matches_manual_calculation(self, eval_standard):
        """Annual BASE FARE revenue equals Σ places_sold × avg_price over all
        OD pairs — places_sold is annual, so no operating-days multiplier
        applies, and avg_price already carries both terms of the two-part
        tariff. Total revenue is that plus the other two leaves (CALC
        0.9.30), which TestThreePartTariff pins on their own."""
        costed, result = eval_standard
        expected = sum(
            od["places_sold"] * od["avg_price"]
            for tp in costed["trip_pairs"]
            for od in tp["od_pairs"]
        )
        bd = route_bd(result)
        assert bd["revenue"]["ticket_revenue_eur"] == pytest.approx(
            expected, rel=REL_TOL
        )
        assert bd["total_revenue_eur"] == pytest.approx(
            expected
            + bd["revenue"]["services_revenue_eur"]
            + bd["revenue"]["catering_contribution_eur"],
            rel=REL_TOL,
        )


# =============================================================================
# Breakdown tree identities
# =============================================================================


class TestBreakdownIdentities:
    def test_net_equals_revenue_minus_cost_minus_margin(self, eval_standard):
        _, result = eval_standard
        bd = route_bd(result)
        assert bd["net_eur"] == pytest.approx(
            bd["total_revenue_eur"]
            - bd["total_cost_eur"]
            - bd["margin"]["ebit_margin_eur"],
            rel=REL_TOL,
        )

    def test_cost_total_equals_operator_plus_infrastructure(self, eval_standard):
        _, result = eval_standard
        cost = route_bd(result)["cost"]
        assert cost["total_eur"] == pytest.approx(
            cost["operator"]["total_eur"] + cost["infrastructure"]["total_eur"],
            rel=REL_TOL,
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
        leaf_sum = (
            v["driver_eur"]
            + v["crew_eur"]
            + v["coach_maintenance_eur"]
            + v["loco_eur"]
            + v["svc_stockings_eur"]
            + v["var_overhead_eur"]
        )
        assert v["total_eur"] == pytest.approx(leaf_sum, rel=REL_TOL)

    def test_fixed_total_equals_sum_of_leaves(self, eval_standard):
        _, result = eval_standard
        f = route_bd(result)["cost"]["operator"]["fixed"]
        leaf_sum = (
            f["coach_amortisation_eur"]
            + f["financing_eur"]
            + f["fix_overhead_eur"]
            + f["cleaning_eur"]
            + f["shunting_eur"]
        )
        assert f["total_eur"] == pytest.approx(leaf_sum, rel=REL_TOL)

    def test_infrastructure_total_equals_sum_of_leaves(self, eval_standard):
        _, result = eval_standard
        infra = route_bd(result)["cost"]["infrastructure"]
        leaf_sum = (
            infra["tac_eur"]
            + infra["energy_eur"]
            + infra["station_charge_eur"]
            + infra["parking_eur"]
        )
        assert infra["total_eur"] == pytest.approx(leaf_sum, rel=REL_TOL)

    def test_net_identity_holds_in_all_normalisations(self, eval_standard):
        """net = revenue - cost - margin in every normalisation. CALC 0.9.9:
        every normalisation is class-keyed ("all" + one cell per
        class_main); the identity must hold in every cell."""
        _, result = eval_standard
        data = result["views"]["route"]["data"]
        for norm, payload in data.items():
            for cls, bd in payload.items():
                assert bd["net_eur"] == pytest.approx(
                    bd["total_revenue_eur"]
                    - bd["total_cost_eur"]
                    - bd["margin"]["ebit_margin_eur"],
                    abs=0.05,
                ), f"net identity failed in '{norm}' class '{cls}'"


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

    def test_per_train_km_divisor_is_annual(self, eval_standard):
        """per_train_km divides by ANNUAL train-km: the summed distance of
        ALL trips (outbound + return both counted) x operating days — the
        per_year figure is annual, so the divisor must be too."""
        costed, result = eval_standard
        annual_train_km = sum(
            trip_distance_km(t) for t in all_trips(costed)
        ) * operating_days(costed)
        per_year = route_bd(result, "per_year")["total_cost_eur"]
        per_km = route_bd(result, "per_train_km")["total_cost_eur"]
        assert per_year == pytest.approx(per_km * annual_train_km, rel=REL_TOL)

    def test_country_per_train_km_divides_by_that_countrys_km(self, eval_standard):
        """A country cell's per-train-km divides by the kilometres run in
        THAT country, not the whole route's.

        Before CALC 0.9.20 country cells fell back to the pair-wide
        denominator, so every per-unit country figure was scaled down by
        that country's share of the route — Dutch track access reading
        0.38 EUR/train-km where the applied rate is 2.58. The check is
        per-country so a route where one country happens to dominate
        cannot mask it.
        """
        costed, result = eval_standard
        days = operating_days(costed)
        countries = result["views"]["per_trip_pair_per_country"]["data"]["all"]

        for cc, cell in countries.items():
            if cc == "all":
                continue
            cc_km = sum(country_km(trip).get(cc, 0.0) for trip in all_trips(costed))
            if cc_km == 0:
                continue
            per_year = cell["values"]["per_year"]["all"]["total_cost_eur"]
            per_km = cell["values"]["per_train_km"]["all"]["total_cost_eur"]
            assert per_year == pytest.approx(per_km * cc_km * days, rel=REL_TOL), (
                f"{cc}: per_train_km is not divided by {cc}'s own km"
            )

    def test_country_per_km_cells_satisfy_the_weighted_identity(self, eval_standard):
        """Per-unit country cells are NOT additive — rates over different
        denominators cannot be summed — so the identity that replaces
        'country cells sum to the route total' is the weighted one:
        Σ(country rate × country km) == route rate × route km.

        This is the invariant that catches allocation drift now that the
        naive sum no longer holds.
        """
        costed, result = eval_standard
        days = operating_days(costed)
        countries = result["views"]["per_trip_pair_per_country"]["data"]["all"]

        weighted = 0.0
        for cc, cell in countries.items():
            if cc == "all":
                continue
            cc_km = sum(country_km(trip).get(cc, 0.0) for trip in all_trips(costed))
            weighted += (
                cell["values"]["per_train_km"]["all"]["total_cost_eur"] * cc_km * days
            )

        route_km = sum(trip_distance_km(t) for t in all_trips(costed)) * days
        route_per_km = route_bd(result, "per_train_km")["total_cost_eur"]
        assert weighted == pytest.approx(route_per_km * route_km, rel=REL_TOL)

    def test_country_per_km_cells_no_longer_sum_naively(self, eval_standard):
        """The flip side, asserted deliberately rather than left implicit:
        on a multi-country route the naive sum of per-km country cells
        EXCEEDS the route figure, because each divides by its own smaller
        distance. If this ever passes as an equality again, the scopes have
        silently stopped being applied."""
        costed, result = eval_standard
        countries = result["views"]["per_trip_pair_per_country"]["data"]["all"]
        cells = [
            cell["values"]["per_train_km"]["all"]["total_cost_eur"]
            for cc, cell in countries.items()
            if cc != "all"
        ]
        if len(cells) < 2:
            pytest.skip("single-country route — nothing to over-count")
        route_per_km = route_bd(result, "per_train_km")["total_cost_eur"]
        assert sum(cells) > route_per_km * 1.01

    def test_od_per_train_km_divides_by_its_own_span(self, eval_standard):
        """An OD pair's train-km is the span it rides, not the whole cycle
        the train runs regardless of who is aboard. A passenger travelling
        one leg of a five-stop route should not be charged against the
        other four legs' kilometres."""
        costed, result = eval_standard
        days = operating_days(costed)
        ods = result["views"]["per_trip_pair_per_od"]["data"]["all"]
        route_km = sum(trip_distance_km(t) for t in all_trips(costed))

        checked = 0
        for od_key, cell in ods.items():
            if od_key == "all":
                continue
            per_year = cell["values"]["per_year"]["all"]["total_cost_eur"]
            per_km = cell["values"]["per_train_km"]["all"]["total_cost_eur"]
            if per_km == 0 or per_year == 0:
                continue
            span_km = per_year / (per_km * days)
            # The implied divisor must be a real span: positive, and no
            # longer than the whole cycle.
            assert 0 < span_km <= route_km * 1.01, (
                f"{od_key}: implied span {span_km:.1f} km is not a "
                f"sub-span of the {route_km:.1f} km cycle"
            )
            checked += 1
        assert checked > 0, "no OD cell carried a per_train_km figure to check"

    def test_per_available_place_km_divisor_is_unweighted(self, eval_standard):
        """per_available_place_km divides by Σ (total places × segment km)
        × operating days — UNWEIGHTED annual capacity. Class density is
        exposed as data on compositions but deliberately NOT applied in this
        divisor (see views.py: normalise_per_available_place_km)."""
        costed, result = eval_standard
        places = sum(costed["trip_pairs"][0]["composition"]["places_by_class"].values())
        available_pkm = (
            places
            * sum(trip_distance_km(t) for t in all_trips(costed))
            * operating_days(costed)
        )

        per_year = route_bd(result, "per_year")["total_cost_eur"]
        per_pkm = route_bd(result, "per_available_place_km")["total_cost_eur"]
        assert per_year == pytest.approx(per_pkm * available_pkm, rel=REL_TOL)

    def test_per_sold_place_km_divisor(self, eval_standard):
        """per_sold_place_km is class-keyed with 'all' restored as the
        fleet-wide weighted average (CALC 0.9.9): only classes with sales
        present, each with a positive per-sold cost and a matching
        per_year class cell; the 'all' cell sits within the class range."""
        _, result = eval_standard
        per_sold = route_bd(result, "per_sold_place_km", class_main=None)
        per_year_classes = route_bd(result, "per_year", class_main=None)
        class_cells = {cls: bd for cls, bd in per_sold.items() if cls != "all"}
        assert class_cells, "no class with sold place-km in per_sold view"
        assert "all" in per_sold
        for cls, bd in class_cells.items():
            assert cls in per_year_classes
            assert bd["total_cost_eur"] > 0
        costs = [bd["total_cost_eur"] for bd in class_cells.values()]
        assert min(costs) <= per_sold["all"]["total_cost_eur"] <= max(costs)

    def test_class_cells_sum_to_all_where_divisor_is_class_independent(
        self, eval_standard
    ):
        """per_year / per_operating_day / per_train_km share one divisor
        across the class axis, so class cells must sum back to 'all' (up
        to per-leaf rounding)."""
        _, result = eval_standard
        for norm in ("per_year", "per_operating_day", "per_train_km"):
            cells = route_bd(result, norm, class_main=None)
            class_sum = sum(bd["net_eur"] for cls, bd in cells.items() if cls != "all")
            assert class_sum == pytest.approx(cells["all"]["net_eur"], abs=0.5), (
                f"class cells don't sum to 'all' in '{norm}'"
            )

    def test_per_sold_cost_exceeds_per_available_at_partial_load(self, eval_standard):
        """At partial load, unsold capacity concentrates cost on sold
        places: the max per-sold class cost must be at least the
        aggregate per-available cost."""
        _, result = eval_standard
        per_sold = route_bd(result, "per_sold_place_km", class_main=None)
        per_avail = route_bd(result, "per_available_place_km")
        assert (
            max(bd["total_cost_eur"] for bd in per_sold.values())
            >= per_avail["total_cost_eur"]
        )


# =============================================================================
# Demand behaviour
# =============================================================================


class TestDemandBehaviour:
    def test_zero_demand_gives_zero_revenue_but_positive_cost(self, eval_zero):
        """No demand → zero revenue; running the train still costs money."""
        bd = route_bd(eval_zero)
        assert bd["total_revenue_eur"] == 0.0
        assert bd["total_cost_eur"] > 0

    def test_zero_demand_per_sold_view_is_zeroed(self, eval_zero):
        """Zero demand ⇒ no sold place-km anywhere ⇒ the class-keyed
        per_sold view is empty — classes without sales are omitted, and
        'all' is omitted when total sold place-km is 0 (CALC 0.9.9)."""
        sold_bd = route_bd(eval_zero, "per_sold_place_km", class_main=None)
        assert sold_bd == {}

    def test_zero_demand_per_available_still_positive(self, eval_zero):
        """Capacity-based normalisation is demand-independent — positive cost
        per available place-km even with zero demand."""
        assert route_bd(eval_zero, "per_available_place_km")["total_cost_eur"] > 0

    def test_fare_scales_revenue_linearly(self, loader, route_berlin_wien):
        """Ticket revenue is linear in avg_price: tripling the fare triples
        it exactly (places held constant). Not total revenue — the catering
        contribution rides on the passengers, which did not move."""
        _, cheap = compute_evaluation_domain(
            route_berlin_wien, loader, demand=[("Seat", 30, 33.0)]
        )
        _, pricey = compute_evaluation_domain(
            route_berlin_wien, loader, demand=[("Seat", 30, 99.0)]
        )
        assert route_bd(pricey)["revenue"]["ticket_revenue_eur"] == pytest.approx(
            route_bd(cheap)["revenue"]["ticket_revenue_eur"] * 3.0, rel=REL_TOL
        )
        assert route_bd(pricey)["revenue"][
            "catering_contribution_eur"
        ] == pytest.approx(
            route_bd(cheap)["revenue"]["catering_contribution_eur"], rel=REL_TOL
        )


# =============================================================================
# Matrix views — consistency with the route view
# =============================================================================


class TestMatrixConsistency:
    def test_country_all_all_equals_route_view(self, eval_standard):
        """The (all, all) country matrix cell equals the route-level breakdown."""
        _, result = eval_standard
        cell = result["views"]["per_trip_pair_per_country"]["data"]["all"]["all"]
        assert cell["values"]["per_year"]["all"]["total_cost_eur"] == pytest.approx(
            route_bd(result)["total_cost_eur"], rel=REL_TOL
        )

    def test_pair_selection_includes_parking(self, eval_standard):
        """Selecting the (only) trip pair must carry the same parking cost as
        'all trips' — parking is matched to pairs via ParkingCost.trip_ids
        and must not vanish behind the pair filter (regression: pre-0.9.4 a
        pair selection silently dropped parking entirely)."""
        _, result = eval_standard
        data = result["views"]["per_trip_pair"]["data"]
        pair_key = next(k for k in data if k != "all")
        pair_parking = data[pair_key]["values"]["per_year"]["all"]["cost"][
            "infrastructure"
        ]["parking_eur"]
        all_parking = route_bd(result)["cost"]["infrastructure"]["parking_eur"]
        assert all_parking > 0
        assert pair_parking == pytest.approx(all_parking, rel=REL_TOL)

    def test_country_tac_cells_sum_to_total(self, eval_standard):
        """Per-country TAC cells (in the 'all' trip-pair row) sum back to the
        route-level TAC — the country allocation loses nothing."""
        _, result = eval_standard
        countries = result["views"]["per_trip_pair_per_country"]["data"]["all"]
        tac_sum = sum(
            cell["values"]["per_year"]["all"]["cost"]["infrastructure"]["tac_eur"]
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
        for key in (
            "osm:n3856100103__osm:w423692233__Couchette",
            "osm:w423692233__osm:n3856100103__Couchette",
        ):
            assert key in all_ods, f"OD key missing: {key}"
            assert all_ods[key]["values"]["per_year"]["all"]["total_revenue_eur"] > 0

    def test_od_cells_partition_pair_total(self, eval_standard):
        """OD cells partition the pair total: cost, revenue, and net of all
        OD cells sum to the pair's 'all' cell (allocation shares sum to
        exactly 1 — regression: pre-0.9.4 loco/cleaning double-counted,
        fleet over-allocated, parking and pass-through stop costs dropped)."""
        _, result = eval_standard
        data = result["views"]["per_trip_pair_per_od"]["data"]
        pair_key = next(k for k in data if k != "all")
        cells = [
            cell["values"]["per_year"]["all"]
            for key, cell in data[pair_key].items()
            if key != "all"
        ]
        pair_cell = data[pair_key]["all"]["values"]["per_year"]["all"]
        for field in ("total_cost_eur", "total_revenue_eur", "net_eur"):
            assert pair_cell[field] == pytest.approx(
                sum(c[field] for c in cells), rel=REL_TOL
            ), f"OD cells don't sum to pair total for {field}"

    def test_stop_matrix_terminal_has_station_charge(self, eval_standard):
        """The origin stop carries a positive station charge in the stop matrix."""
        _, result = eval_standard
        all_stops = result["views"]["per_trip_per_stop"]["data"]["all"]
        berlin = all_stops["osm:n3856100103"]
        charge = berlin["values"]["per_year"]["all"]["cost"]["infrastructure"][
            "station_charge_eur"
        ]
        assert charge > 0


# =============================================================================
# Section view — physical route sections with class sub-cells
# =============================================================================


class TestSectionView:
    SECTION_ALL = "osm:n3856100103__osm:w423692233__all"

    def test_every_stop_range_has_a_section_cell(self, eval_standard):
        """Sections exist for EVERY ordered stop pair (CALC 0.9.16) — not only
        ticketed OD relations — each with an 'all' cell and one cell per
        class_main with passengers. Keys are canonical outbound order, so
        reverse-ordered keys must be gone."""
        _, result = eval_standard
        sections = result["views"]["per_trip_pair_per_section"]["data"]["all"]
        for key in (
            "osm:n3856100103__osm:w423692233__all",
            "osm:n3856100103__osm:w423692233__Couchette",
            "osm:n3856100103__osm:w423692233__Seat",
            # sub-sections bounded by the intermediate stop — before 0.9.16
            # these only existed if Dresden happened to carry tickets
            "osm:n3856100103__osm:n25397500__all",
            "osm:n25397500__osm:w423692233__all",
        ):
            assert key in sections, f"section key missing: {key}"
        assert "osm:w423692233__osm:n3856100103__all" not in sections, (
            "reverse-ordered key present — section keys must be canonical"
        )

    def test_class_cells_sum_to_section_all(self, eval_standard):
        """Per-class cells partition their section: cost, revenue, and margin
        of the class cells sum to the section's 'all' cell."""
        _, result = eval_standard
        sections = result["views"]["per_trip_pair_per_section"]["data"]["all"]
        all_cell = sections[self.SECTION_ALL]["values"]["per_year"]["all"]
        cls_cells = [
            cell["values"]["per_year"]["all"]
            for key, cell in sections.items()
            if key.startswith("osm:n3856100103__osm:w423692233__")
            and not key.endswith("__all")
        ]
        assert cls_cells, "no class cells found for section"
        for field in ("total_cost_eur", "total_revenue_eur", "net_eur"):
            assert all_cell[field] == pytest.approx(
                sum(c[field] for c in cls_cells), rel=REL_TOL
            ), f"class cells don't sum to section 'all' for {field}"

    def test_full_trip_section_captures_all_revenue(self, eval_standard):
        """Every ticket rides entirely within the full-length section, and the
        canonical cell folds both directions (CALC 0.9.16) — so the single
        full-trip cell carries the route's entire revenue."""
        _, result = eval_standard
        sections = result["views"]["per_trip_pair_per_section"]["data"]["all"]
        revenue = sections[self.SECTION_ALL]["values"]["per_year"]["all"][
            "total_revenue_eur"
        ]
        assert revenue == pytest.approx(
            route_bd(result)["total_revenue_eur"], rel=REL_TOL
        )

    def test_adjacent_sections_revenue_sums_to_enclosing(self, eval_standard):
        """Revenue is km-overlap-proportional and km are additive, so the two
        sub-sections around Dresden sum to the full section's revenue. (Costs
        deliberately don't — the shared boundary stop call is in both.)"""
        _, result = eval_standard
        sections = result["views"]["per_trip_pair_per_section"]["data"]["all"]

        def rev(key: str) -> float:
            return sections[key]["values"]["per_year"]["all"]["total_revenue_eur"]

        assert rev(self.SECTION_ALL) == pytest.approx(
            rev("osm:n3856100103__osm:n25397500__all")
            + rev("osm:n25397500__osm:w423692233__all"),
            rel=REL_TOL,
        )

    def test_section_train_km_divisor_is_section_scoped(self, eval_standard):
        """A section cell's per_train_km divides by the SECTION's own annual
        train-km (section distance x operating days) — summed over BOTH
        directions since the canonical cell folds them (CALC 0.9.16) — not
        the whole pair's default scope."""
        costed, result = eval_standard
        sections = result["views"]["per_trip_pair_per_section"]["data"]["all"]
        cell = sections[self.SECTION_ALL]["values"]
        section_annual_km = sum(
            trip_distance_km(t) for t in all_trips(costed)
        ) * operating_days(costed)
        per_year = cell["per_year"]["all"]["total_cost_eur"]
        per_km = cell["per_train_km"]["all"]["total_cost_eur"]
        assert per_year == pytest.approx(per_km * section_annual_km, rel=REL_TOL)


# =============================================================================
# Class axis — exhaustively, across every view/filter/normalisation combo
# =============================================================================


def _iter_all_cells(result: dict):
    """Yield (view_name, cell_label, values) for every cell in every view —
    'route' has no filter/values nesting (data IS the values dict directly);
    per_trip_pair is one level deep ({key: {filter, values}}); the matrix
    views (country/od/section/stop) are two levels deep
    ({key1: {key2: {filter, values}}}). values is always the
    {norm: {class_main | "all": breakdown}} payload for that cell (CALC
    0.9.9), so every assertion below runs identically regardless of which
    view/filter combination produced it."""
    yield "route", "route", result["views"]["route"]["data"]
    for view_name in (
        "per_trip_pair",
        "per_trip_pair_per_country",
        "per_trip_pair_per_od",
        "per_trip_pair_per_section",
        "per_trip_per_stop",
    ):
        for k1, v1 in result["views"][view_name]["data"].items():
            if "values" in v1:
                yield view_name, k1, v1["values"]
            else:
                for k2, v2 in v1.items():
                    yield view_name, f"{k1}/{k2}", v2["values"]


class TestClassAxisAcrossAllViewsAndNorms:
    """The class axis (CALC 0.9.9) is orthogonal to view and filter by
    design — these checks walk every (view, filtered cell, normalisation)
    combination the standard fixture produces, not just the route view's
    defaults, so a bug that only shows up in one corner of the cube (as
    the per_sold 'all' mediant-bound violation did — it was invisible at
    route/per_year and only surfaced once "all" was checked against the
    class range) gets caught."""

    def test_every_present_norm_has_an_all_cell(self, eval_standard):
        _, result = eval_standard
        checked = 0
        for view_name, label, values in _iter_all_cells(result):
            for norm, cells in values.items():
                if not cells:
                    continue  # e.g. per_sold_place_km with zero demand there
                assert "all" in cells, f"{view_name}[{label}][{norm}]: no 'all' cell"
                checked += 1
        assert checked > 20, "too few cells exercised — fixture may have shrunk"

    def test_net_identity_holds_everywhere(self, eval_standard):
        """net = revenue - cost - margin in every view, every filtered
        cell, every normalisation, every class cell — not just 'all'."""
        _, result = eval_standard
        checked = 0
        for view_name, label, values in _iter_all_cells(result):
            for norm, cells in values.items():
                for cls, bd in cells.items():
                    assert bd["net_eur"] == pytest.approx(
                        bd["total_revenue_eur"]
                        - bd["total_cost_eur"]
                        - bd["margin"]["ebit_margin_eur"],
                        abs=0.05,
                    ), f"net identity failed: {view_name}[{label}][{norm}][{cls}]"
                    checked += 1
        assert checked > 50, "too few cells exercised — fixture may have shrunk"

    def test_class_independent_norms_sum_to_all_everywhere(self, eval_standard):
        """per_year / per_operating_day / per_train_km share one divisor
        across the class axis, so class cells must sum back to 'all' in
        EVERY view and filtered cell that carries more than one class —
        not just the route view (test_class_cells_sum_to_all_where_
        divisor_is_class_independent above checks that narrower case)."""
        _, result = eval_standard
        class_independent = ("per_year", "per_operating_day", "per_train_km")
        checked = 0
        for view_name, label, values in _iter_all_cells(result):
            for norm in class_independent:
                cells = values.get(norm)
                if not cells or "all" not in cells or len(cells) < 2:
                    continue  # single-class (identity) cells trivially match
                class_sum = sum(
                    bd["net_eur"] for cls, bd in cells.items() if cls != "all"
                )
                assert class_sum == pytest.approx(cells["all"]["net_eur"], abs=0.5), (
                    f"{view_name}[{label}][{norm}]: class cells don't sum to 'all'"
                )
                checked += 1
        assert checked > 5, "too few multi-class cells exercised"

    def test_per_unit_norms_all_within_class_range_everywhere(self, eval_standard):
        """per_available_place_km / per_sold_place_km: 'all' must be a
        mediant of the participating classes' own cost-per-unit ratios —
        it can never fall outside their [min, max] — in every view and
        filtered cell with more than one class present. Regression guard:
        pre-fix, a class with a zero divisor (no capacity, or — for
        per_sold — no sales that period) still had its cost folded into
        'all's numerator while being excluded from the denominator,
        which can push 'all' past every class's own figure (observed in
        production: two class costs of ~69 and ~44 €/sold-place-km
        against an 'all' of ~135 — see build_class_keyed_normalisations)."""
        _, result = eval_standard
        per_unit = ("per_available_place_km", "per_sold_place_km")
        checked = 0
        for view_name, label, values in _iter_all_cells(result):
            for norm in per_unit:
                cells = values.get(norm)
                if not cells or "all" not in cells:
                    continue
                class_costs = [
                    bd["total_cost_eur"] for cls, bd in cells.items() if cls != "all"
                ]
                if len(class_costs) < 2:
                    continue  # identity cells (OD/section class-scoped)
                lo, hi = min(class_costs), max(class_costs)
                all_cost = cells["all"]["total_cost_eur"]
                # 6dp leaf rounding can nudge the mediant a hair past an
                # exact bound; REL_TOL scaled against the range absorbs
                # that without masking a real violation like the one this
                # test was written to catch (~2x past the upper bound)
                slack = max(abs(hi), abs(lo)) * REL_TOL
                assert lo - slack <= all_cost <= hi + slack, (
                    f"{view_name}[{label}][{norm}]: 'all'={all_cost} outside "
                    f"class range [{lo}, {hi}]"
                )
                checked += 1
        assert checked > 0, "no multi-class per-unit cell found — check fixture demand"


# =============================================================================
# Scenario override
# =============================================================================


class TestScenarioOverride:
    def test_historical_override_lowers_tac(
        self, loader, route_berlin_wien, historical_scenario
    ):
        """Costing the SAME base-planned route under the superseded
        infra-2026 revision (track infra v4: DE tac 3.10 instead of 5.40)
        yields strictly lower TAC — the override actually swaps the
        parameter version."""
        _, base = compute_evaluation_domain(route_berlin_wien, loader, demand=[])
        _, historical = compute_evaluation_domain(
            route_berlin_wien,
            loader,
            demand=[],
            scenario_id=historical_scenario["scenario_id"],
        )

        tac_base = route_bd(base)["cost"]["infrastructure"]["tac_eur"]
        tac_historical = route_bd(historical)["cost"]["infrastructure"]["tac_eur"]
        assert tac_historical < tac_base

        # Stop infrastructure carries byte-identical values across every
        # scenario (only the version number differs) — station charges
        # must be unchanged by the override.
        sc_base = route_bd(base)["cost"]["infrastructure"]["station_charge_eur"]
        sc_historical = route_bd(historical)["cost"]["infrastructure"][
            "station_charge_eur"
        ]
        assert sc_historical == pytest.approx(sc_base, rel=REL_TOL)


# =============================================================================
# Measure sets (CALC 0.9.26)
# =============================================================================


class TestMeasureSetsAreIdentityToday:
    """The WP18 hook: evaluate_route() takes a MeasureSet and records it.
    Until WP17 seeds rates every factor is 1.0, so the numbers must be
    byte-identical to what the model returned before the parameter
    existed. These tests are what makes that claim checkable — and what
    fails loudly the day WP17 changes a factor without saying so."""

    @pytest.fixture(scope="class")
    def evaluated_route(self, loader, route_berlin_dresden_wien):
        """The domain Route behind route_berlin_dresden_wien with
        STANDARD_DEMAND applied, plus the collections to evaluate it —
        built once so both evaluations below run on the SAME objects and
        any difference can only come from the measure set."""
        from tests.conftest import STANDARD_DEMAND
        from api.helpers.route_serialize import route_from_dict

        scenario_id = route_berlin_dresden_wien["scenario_id"]
        route, _ = route_from_dict(
            route_berlin_dresden_wien, loader, scenario_id=scenario_id
        )
        for pair in route.trip_pairs:
            pair.od_pairs = []
        for class_main, places_sold, avg_price in STANDARD_DEMAND:
            add_directional_domain_demand(route, class_main, places_sold, avg_price)
        return (
            route,
            loader.build_all_tracks(scenario_id),
            loader.build_all_stops(scenario_id),
            loader.build_all_passages(scenario_id),
        )

    def test_no_measures_is_the_default(self, evaluated_route):
        """Omitting measures and passing NO_MEASURES explicitly produce
        the identical views — the property every caller that has not
        heard of measure sets relies on."""
        from api.helpers.evaluation_serialize import views_to_dict
        from models.params import NO_MEASURES
        from models.pipeline import evaluate_and_build_views

        route, tracks, stop_infra, passages = evaluated_route
        _, default_views = evaluate_and_build_views(route, tracks, stop_infra, passages)
        _, explicit_views = evaluate_and_build_views(
            route, tracks, stop_infra, passages, NO_MEASURES
        )
        assert views_to_dict(default_views, route) == views_to_dict(
            explicit_views, route
        )

    def test_result_records_the_measure_set_it_was_priced_under(self, evaluated_route):
        """A result carries its own political assumptions, the way
        RouteProvenance carries its parameter versions."""
        from models.params import NO_MEASURES
        from models.pipeline import evaluate_and_build_views

        route, tracks, stop_infra, passages = evaluated_route
        result, _ = evaluate_and_build_views(route, tracks, stop_infra, passages)
        assert result.measures is NO_MEASURES
        assert result.measures.key == "none"

    def test_every_factor_is_one(self):
        """The three hooks, stated as a test rather than only as a
        comment: ticket revenue, energy cost and track access are all
        unscaled today (models/params.py MeasureSet)."""
        from models.params import NO_MEASURES

        assert NO_MEASURES.ticket_revenue_factor == 1.0
        assert NO_MEASURES.energy_cost_factor == 1.0
        assert NO_MEASURES.track_access_factor == 1.0


# =============================================================================
# Catering — one signed net figure per passenger (CALC 0.9.29)
# =============================================================================


class TestCateringContribution:
    """The contribution is revenue, rides on passengers rather than on
    fares, and stays out of the two bases that are shares of ticket
    revenue. Every assertion here is about that separation."""

    @staticmethod
    def _passengers(costed):
        return sum(
            od["places_sold"] for tp in costed["trip_pairs"] for od in tp["od_pairs"]
        )

    def test_contribution_is_passengers_times_the_rate(self, loader, route_berlin_wien):
        """Per class since CALC 0.9.30 — the route total is the sum over the
        classes it actually carries, not one rate times everybody."""
        from models.demand.model import STOPGAP_CATERING_EUR_PER_PAX_BY_CLASS

        costed, result = compute_evaluation_domain(
            route_berlin_wien, loader, demand=[("Seat", 30, 49.0)]
        )
        expected = sum(
            od["places_sold"] * STOPGAP_CATERING_EUR_PER_PAX_BY_CLASS[od["class_main"]]
            for tp in costed["trip_pairs"]
            for od in tp["od_pairs"]
        )
        assert route_bd(result)["revenue"][
            "catering_contribution_eur"
        ] == pytest.approx(expected, rel=REL_TOL)

    def test_a_negative_rate_is_carried_through_signed(self, loader, route_berlin_wien):
        """The ordinary night-train case: the restaurant is carried by the
        tickets it helps sell, so the leaf is negative and total revenue
        falls below what the other two leaves earned. Compared against
        ticket + services rather than ticket alone — services are revenue
        too, and on this route they more than cover the restaurant."""
        costed, result = compute_evaluation_domain(
            route_berlin_wien,
            loader,
            demand=[("Seat", 30, 49.0)],
            catering_eur_per_pax=dict.fromkeys(FARE_CLASS_MAINS, -0.80),
        )
        bd = route_bd(result)
        assert bd["revenue"]["catering_contribution_eur"] == pytest.approx(
            self._passengers(costed) * -0.80, rel=REL_TOL
        )
        assert (
            bd["total_revenue_eur"]
            < bd["revenue"]["ticket_revenue_eur"]
            + bd["revenue"]["services_revenue_eur"]
        )

    def test_it_moves_the_net_result_and_nothing_else(self, loader, route_berlin_wien):
        """Between two evaluations differing only in the catering rate,
        cost, variable overhead and the margin are untouched — they are
        shares of ticket revenue, and the contribution already nets its own
        overhead."""
        costed, with_cat = compute_evaluation_domain(
            route_berlin_wien,
            loader,
            demand=[("Seat", 30, 49.0)],
            catering_eur_per_pax=dict.fromkeys(FARE_CLASS_MAINS, 2.50),
        )
        _, without = compute_evaluation_domain(
            route_berlin_wien,
            loader,
            demand=[("Seat", 30, 49.0)],
            catering_eur_per_pax=dict.fromkeys(FARE_CLASS_MAINS, 0.0),
        )
        a, b = route_bd(with_cat), route_bd(without)
        assert a["total_cost_eur"] == pytest.approx(b["total_cost_eur"], rel=REL_TOL)
        assert a["cost"]["operator"]["variable"]["var_overhead_eur"] == pytest.approx(
            b["cost"]["operator"]["variable"]["var_overhead_eur"], rel=REL_TOL
        )
        assert a["margin"]["ebit_margin_eur"] == pytest.approx(
            b["margin"]["ebit_margin_eur"], rel=REL_TOL
        )
        assert a["net_eur"] - b["net_eur"] == pytest.approx(
            self._passengers(costed) * 2.50, rel=REL_TOL
        )

    def test_no_passengers_no_contribution(self, eval_zero):
        """Nobody on board, nobody in the restaurant — whatever the rate."""
        assert route_bd(eval_zero)["revenue"]["catering_contribution_eur"] == 0.0

    def test_the_views_allocate_it_like_ticket_revenue(self, eval_standard):
        """Every OD cell's contribution sums back to the route's, the same
        identity the ticket leaf satisfies — it is allocated on the same
        key, so a country/section/stop view cannot lose or invent any."""
        _, result = eval_standard
        route_total = route_bd(result)["revenue"]["catering_contribution_eur"]
        data = result["views"]["per_trip_pair_per_od"]["data"]
        pair_key = next(k for k in data if k != "all")
        summed = sum(
            cell["values"]["per_year"]["all"]["revenue"]["catering_contribution_eur"]
            for key, cell in data[pair_key].items()
            if key != "all"
        )
        assert route_total != 0
        assert summed == pytest.approx(route_total, rel=REL_TOL)


# =============================================================================
# Overhead and margin reach the per-trip-pair view (handover §6.4)
# =============================================================================


class TestOverheadFieldsInViews:
    """The Overhead tab reads its three receipts off the per_trip_pair
    view and builds the fixed-overhead base from the two operator
    subtotals. Pinned here so a reshaping of the view cannot silently take
    them away."""

    def test_per_trip_pair_carries_overhead_margin_and_the_subtotals(
        self, eval_standard
    ):
        _, result = eval_standard
        data = result["views"]["per_trip_pair"]["data"]
        for key, cell in data.items():
            bd = cell["values"]["per_year"]["all"]
            variable = bd["cost"]["operator"]["variable"]
            fixed = bd["cost"]["operator"]["fixed"]
            assert "var_overhead_eur" in variable, key
            assert "fix_overhead_eur" in fixed, key
            assert "ebit_margin_eur" in bd["margin"], key
            # The base the fixed-overhead receipt lists row by row.
            assert "total_eur" in variable and "total_eur" in fixed, key

    def test_fixed_overhead_is_the_quota_on_the_documented_base(
        self, eval_standard, overhead_quotas
    ):
        """q_fix,oh × (operator variable excl. variable overhead + operator
        fixed excl. the leaf itself) — infrastructure stays outside."""
        _, result = eval_standard
        bd = route_bd(result)
        variable = bd["cost"]["operator"]["variable"]
        fixed = bd["cost"]["operator"]["fixed"]
        base = (
            variable["total_eur"]
            - variable["var_overhead_eur"]
            + fixed["total_eur"]
            - fixed["fix_overhead_eur"]
        )
        costed, _ = eval_standard
        comp_id = costed["trip_pairs"][0]["composition"]["composition_id"]
        assert fixed["fix_overhead_eur"] == pytest.approx(
            overhead_quotas[comp_id] * base, rel=REL_TOL
        )


# =============================================================================
# Operations — the physical side, per pair and per trip (CALC 0.9.29)
# =============================================================================


class TestOperationsPerTrip:
    """The pair figures are what they always were; the trips[] entries are
    the per-direction split the receipts read. The two must agree, or the
    panel and the strip above it would disagree on the same train."""

    @pytest.fixture(scope="class")
    def ops(self, loader, route_berlin_dresden_wien):
        from tests.conftest import STANDARD_DEMAND
        from api.helpers.route_serialize import route_from_dict
        from models.evaluation.operations import build_operations
        from models.pipeline import evaluate_and_build_views

        scenario_id = route_berlin_dresden_wien["scenario_id"]
        route, _ = route_from_dict(
            route_berlin_dresden_wien, loader, scenario_id=scenario_id
        )
        for pair in route.trip_pairs:
            pair.od_pairs = []
        for class_main, places_sold, avg_price in STANDARD_DEMAND:
            add_directional_domain_demand(route, class_main, places_sold, avg_price)
        result, _ = evaluate_and_build_views(
            route,
            loader.build_all_tracks(scenario_id),
            loader.build_all_stops(scenario_id),
            loader.build_all_passages(scenario_id),
        )
        return build_operations(route, result)

    @pytest.fixture(scope="class")
    def priced(self, loader, route_berlin_dresden_wien):
        """The route and its raw evaluation, for the assertions that go
        beneath the operations block."""
        from api.helpers.route_serialize import route_from_dict
        from models.pipeline import evaluate_and_build_views

        scenario_id = route_berlin_dresden_wien["scenario_id"]
        route, _ = route_from_dict(
            route_berlin_dresden_wien, loader, scenario_id=scenario_id
        )
        result, _ = evaluate_and_build_views(
            route,
            loader.build_all_tracks(scenario_id),
            loader.build_all_stops(scenario_id),
            loader.build_all_passages(scenario_id),
        )
        return route, result

    def test_staff_are_paid_for_the_whole_segment(self, priced):
        """CALC 0.9.31 — the buffer is on the clock. A segment's staff hours
        are its total time, not its driving time: a 10 h trip no longer pays
        its driver for 8 h."""
        route, result = priced
        by_key = {(c.trip_id, c.segment_index): c for c in result.segment_costs}
        for pair in route.trip_pairs:
            for trip in pair.trips:
                for i, seg in enumerate(trip.segments):
                    cost = by_key[(trip.trip_id, i)]
                    assert cost.driver_hours == pytest.approx(
                        seg.total_time_min / 60.0 * pair.composition.driver_factor,
                        rel=REL_TOL,
                    )
                    assert (
                        seg.total_time_min
                        > seg.driving_time_min + seg.dynamics_time_min
                    )

    def test_every_role_is_on_board_for_the_whole_trip(self, ops):
        """hours_on_train is headcount x trip time — a figure the reader can
        check against the loco's own hours — and the factor is nowhere in
        it."""
        for pair in ops["trip_pairs"]:
            for trip in pair["trips"]:
                trip_h = trip["loco_hours"]["total"]
                for role in ("drivers", "train_chief", "attendants"):
                    r = trip["staffing"][role]
                    assert r["hours_on_train"] == pytest.approx(
                        r["on_board"] * trip_h, abs=0.05
                    )
                # The chief in particular: one person, one trip's hours.
                chief = trip["staffing"]["train_chief"]
                if chief["on_board"]:
                    assert chief["hours_on_train"] == pytest.approx(trip_h, abs=0.05)
                    assert chief["factor"] > 1.0

    def test_every_pair_has_both_directions_in_order(self, ops):
        for pair in ops["trip_pairs"]:
            assert [t["direction"] for t in pair["trips"]] == ["outbound", "return"]
            assert len({t["trip_id"] for t in pair["trips"]}) == 2

    def test_trip_loco_hours_sum_to_the_cycle(self, ops):
        for pair in ops["trip_pairs"]:
            assert sum(
                t["loco_hours"]["total"] for t in pair["trips"]
            ) == pytest.approx(pair["loco_hours"]["per_trip_cycle"], rel=REL_TOL)

    def test_loco_running_and_dwell_make_up_the_total(self, ops):
        for pair in ops["trip_pairs"]:
            for trip in pair["trips"]:
                lh = trip["loco_hours"]
                assert lh["running"] + lh["at_stops"] == pytest.approx(
                    lh["total"], rel=REL_TOL
                )

    def test_trip_staff_hours_and_euros_sum_to_the_cycle(self, ops):
        for pair in ops["trip_pairs"]:
            trips = pair["trips"]
            assert sum(
                t["staffing"]["total"]["hours_on_train"] for t in trips
            ) == pytest.approx(
                pair["staffing"]["total"]["hours_per_trip_cycle"], rel=REL_TOL
            )
            assert sum(t["staffing"]["total"]["eur"] for t in trips) == pytest.approx(
                pair["staffing"]["total"]["eur_per_trip_cycle"], rel=REL_TOL
            )

    def test_the_train_chief_is_one_person_at_a_factor(self, ops):
        """1.19 is attendant-equivalents, never a head count — the panel
        shows "1 x 1.19" and must be able to."""
        for pair in ops["trip_pairs"]:
            for trip in pair["trips"]:
                chief = trip["staffing"]["train_chief"]
                assert chief["on_board"] in (0.0, 1.0)
                assert chief["factor"] >= 1.0

    def test_paid_hours_exceed_hours_on_train(self, ops):
        """Roster efficiency is below 1 by construction: sign-on, sign-off,
        positioning and reserve cover are paid and not on the train."""
        for pair in ops["trip_pairs"]:
            for trip in pair["trips"]:
                for role in ("drivers", "train_chief", "attendants"):
                    r = trip["staffing"][role]
                    if r["hours_on_train"] == 0:
                        continue
                    assert 0 < r["roster_efficiency"] <= 1
                    assert r["paid_hours"] >= r["hours_on_train"]

    def test_role_euros_sum_to_the_trip_total(self, ops):
        for pair in ops["trip_pairs"]:
            for trip in pair["trips"]:
                staffing = trip["staffing"]
                assert sum(
                    staffing[role]["eur"]
                    for role in ("drivers", "train_chief", "attendants")
                ) == pytest.approx(staffing["total"]["eur"], rel=REL_TOL)

    def test_fleet_reports_the_basis_the_cost_model_used(self, ops):
        """coaches_needed is the cost model's own n — coaches per rake times
        the theoretical trainsets, not the physical ones. Compared against
        the unrounded quotient: `theoretical` is reported at two decimals
        for the reader, and multiplying that by seven coaches would drift
        by more than the figure itself is worth."""
        for pair in ops["trip_pairs"]:
            fleet, sets = pair["fleet"], pair["trainsets"]
            exact = sets["physical"] / sets["coach_avail_per"]
            assert fleet["coaches_needed"] == pytest.approx(
                fleet["coaches_per_set"] * exact, abs=0.01
            )
            assert fleet["coaches_needed"] > fleet["coaches_per_set"] * sets["physical"]
            assert fleet["amort_years"] > 0
            assert fleet["shunting_events_per_trip_cycle"] == 4

    def test_route_total_carries_the_two_annualisers(self, ops):
        """A per-trip figure reaches the year on the backend's own numbers,
        not on a schedule the reader re-derives."""
        total = ops["route"]
        assert total["departures_per_year"] == (
            total["operating_days_per_year"] * 2 * len(ops["trip_pairs"])
        )


# =============================================================================
# The three-part tariff (CALC 0.9.30)
# =============================================================================


class TestThreePartTariff:
    """Base fare (fixed + per km), additional services, catering. What
    separates them is which bases they enter, so that is what is pinned."""

    @staticmethod
    def _passengers(costed):
        return sum(
            od["places_sold"] for tp in costed["trip_pairs"] for od in tp["od_pairs"]
        )

    def test_services_are_passengers_times_the_class_rate(
        self, loader, route_berlin_wien
    ):
        costed, result = compute_evaluation_domain(
            route_berlin_wien,
            loader,
            demand=[("Seat", 30, 49.0)],
            services_eur_per_pax=dict.fromkeys(FARE_CLASS_MAINS, 2.0),
        )
        assert route_bd(result)["revenue"]["services_revenue_eur"] == pytest.approx(
            self._passengers(costed) * 2.0, rel=REL_TOL
        )

    def test_services_enter_the_overhead_and_margin_bases(
        self, loader, route_berlin_wien
    ):
        """The one thing that separates services from catering: a bike fare
        is ticket revenue, so it carries distribution overhead and the
        profit requirement like any other ticket."""
        _, with_svc = compute_evaluation_domain(
            route_berlin_wien,
            loader,
            demand=[("Seat", 30, 49.0)],
            services_eur_per_pax=dict.fromkeys(FARE_CLASS_MAINS, 5.0),
        )
        _, without = compute_evaluation_domain(
            route_berlin_wien,
            loader,
            demand=[("Seat", 30, 49.0)],
            services_eur_per_pax=dict.fromkeys(FARE_CLASS_MAINS, 0.0),
        )
        a, b = route_bd(with_svc), route_bd(without)
        assert (
            a["cost"]["operator"]["variable"]["var_overhead_eur"]
            > b["cost"]["operator"]["variable"]["var_overhead_eur"]
        )
        assert a["margin"]["ebit_margin_eur"] > b["margin"]["ebit_margin_eur"]

    def test_catering_still_enters_neither(self, loader, route_berlin_wien):
        _, rich = compute_evaluation_domain(
            route_berlin_wien,
            loader,
            demand=[("Seat", 30, 49.0)],
            catering_eur_per_pax=dict.fromkeys(FARE_CLASS_MAINS, 5.0),
        )
        _, none = compute_evaluation_domain(
            route_berlin_wien,
            loader,
            demand=[("Seat", 30, 49.0)],
            catering_eur_per_pax=dict.fromkeys(FARE_CLASS_MAINS, 0.0),
        )
        a, b = route_bd(rich), route_bd(none)
        assert a["cost"]["operator"]["variable"]["var_overhead_eur"] == pytest.approx(
            b["cost"]["operator"]["variable"]["var_overhead_eur"], rel=REL_TOL
        )
        assert a["margin"]["ebit_margin_eur"] == pytest.approx(
            b["margin"]["ebit_margin_eur"], rel=REL_TOL
        )

    def test_the_three_leaves_sum_to_total_revenue(self, eval_standard):
        _, result = eval_standard
        revenue = route_bd(result)["revenue"]
        assert revenue["total_eur"] == pytest.approx(
            revenue["ticket_revenue_eur"]
            + revenue["services_revenue_eur"]
            + revenue["catering_contribution_eur"],
            rel=REL_TOL,
        )

    def test_the_base_fare_has_a_fixed_part(self, loader, route_berlin_wien):
        """Two OD pairs of different length no longer differ by the full
        ratio of their distances — the fixed term is paid by both."""
        from models.demand.model import STOPGAP_FARE_PER_PAX_BY_CLASS

        costed, _ = compute_evaluation_domain(
            route_berlin_wien, loader, demand=[("Seat", 30, 49.0)]
        )
        prices = sorted(
            od["avg_price"]
            for tp in costed["trip_pairs"]
            for od in tp["od_pairs"]
            if od["places_sold"] > 0
        )
        assert prices[0] >= STOPGAP_FARE_PER_PAX_BY_CLASS["Seat"]

    def test_services_allocate_like_the_other_leaves(self, eval_standard):
        """Same allocator, so the OD cells still sum to the route total."""
        _, result = eval_standard
        route_total = route_bd(result)["revenue"]["services_revenue_eur"]
        data = result["views"]["per_trip_pair_per_od"]["data"]
        pair_key = next(k for k in data if k != "all")
        summed = sum(
            cell["values"]["per_year"]["all"]["revenue"]["services_revenue_eur"]
            for key, cell in data[pair_key].items()
            if key != "all"
        )
        assert route_total > 0
        assert summed == pytest.approx(route_total, rel=REL_TOL)


# =============================================================================
# Operations — the infrastructure block (handover §6.5)
# =============================================================================


class TestOperationsInfrastructure:
    """What each country charged on, per trip, folded from the same component
    records the cost model priced. Every total here has to agree with the
    breakdown leaf it explains."""

    @pytest.fixture(scope="class")
    def built(self, loader, route_berlin_dresden_wien):
        from tests.conftest import STANDARD_DEMAND
        from api.helpers.route_serialize import route_from_dict
        from models.evaluation.operations import build_operations
        from models.pipeline import evaluate_and_build_views

        scenario_id = route_berlin_dresden_wien["scenario_id"]
        route, _ = route_from_dict(
            route_berlin_dresden_wien, loader, scenario_id=scenario_id
        )
        for pair in route.trip_pairs:
            pair.od_pairs = []
        for class_main, places_sold, avg_price in STANDARD_DEMAND:
            add_directional_domain_demand(route, class_main, places_sold, avg_price)
        tracks = loader.build_all_tracks(scenario_id)
        stop_infra = loader.build_all_stops(scenario_id)
        result, views = evaluate_and_build_views(
            route,
            tracks,
            stop_infra,
            loader.build_all_passages(scenario_id),
        )
        return result, views, build_operations(route, result, tracks, stop_infra)

    def test_every_trip_is_there_in_order(self, built):
        _, _, ops = built
        trips = ops["infrastructure"]["trips"]
        assert [t["direction"] for t in trips] == ["outbound", "return"]

    def test_track_access_sums_to_the_leaf(self, built):
        """Both trips' track access, countries and crossings together, is
        the breakdown's per-cycle tac_eur."""
        result, _, ops = built
        per_cycle = sum(seg.tac_eur for seg in result.segment_costs)
        summed = sum(t["track_access"]["eur"] for t in ops["infrastructure"]["trips"])
        assert summed == pytest.approx(per_cycle, rel=REL_TOL)

    def test_the_charged_on_list_adds_up_to_the_country(self, built):
        """The terms a country lists are the ones it levied, and they sum to
        that country's figure — nothing charged is left off the list."""
        _, _, ops = built
        for trip in ops["infrastructure"]["trips"]:
            for country in trip["track_access"]["countries"]:
                assert country["terms"], country["country_code"]
                assert sum(term["eur"] for term in country["terms"]) == pytest.approx(
                    country["eur"], abs=0.05
                )
                assert country["km"] > 0
                assert 0 <= country["night_km"] <= country["km"] + 0.1

    def test_energy_sums_to_the_leaf_and_carries_the_tariff(self, built):
        result, _, ops = built
        per_cycle = sum(seg.energy_eur for seg in result.segment_costs)
        trips = ops["infrastructure"]["trips"]
        assert sum(t["energy"]["eur"] for t in trips) == pytest.approx(
            per_cycle, rel=REL_TOL
        )
        for trip in trips:
            assert trip["energy"]["kwh"] > 0
            for country in trip["energy"]["countries"]:
                assert country["price_eur"] + country["catenary_eur"] == pytest.approx(
                    country["eur"], abs=0.02
                )
                assert "tariff" in country
                assert country["tariff"]["day_eur_kwh"] > 0

    def test_stations_are_every_call_and_sum_to_the_leaf(self, built):
        result, _, ops = built
        per_cycle = sum(c.station_charge_eur for c in result.stop_costs)
        trips = ops["infrastructure"]["trips"]
        assert sum(t["stations"]["eur"] for t in trips) == pytest.approx(
            per_cycle, rel=REL_TOL
        )
        assert sum(len(t["stations"]["calls"]) for t in trips) == len(result.stop_costs)
        for trip in trips:
            for call in trip["stations"]["calls"]:
                assert call["stop_name"]
                assert len(call["country_code"]) == 2
                # Provenance travels with the figure: whether the charge is
                # the stop's own or the global default, and its category.
                assert isinstance(call["defaulted"], bool)
                assert "category" in call

    def test_every_figure_says_whether_it_is_a_default(self, built):
        _, _, ops = built
        for trip in ops["infrastructure"]["trips"]:
            for country in trip["track_access"]["countries"]:
                assert isinstance(country["defaulted"], bool)
            for country in trip["energy"]["countries"]:
                assert isinstance(country["tariff"]["defaulted"], bool)
        for p in ops["infrastructure"]["parkings"]:
            assert isinstance(p["defaulted"], bool)

    def test_parkings_are_per_location_and_sum_to_the_leaf(self, built):
        result, _, ops = built
        parkings = ops["infrastructure"]["parkings"]
        assert len(parkings) == len(result.parking_costs)
        assert sum(p["eur_per_operating_day"] for p in parkings) == pytest.approx(
            sum(p.parking_eur for p in result.parking_costs), rel=REL_TOL
        )
        for p in parkings:
            assert p["facility_eur"] + p["hotel_power_eur"] == pytest.approx(
                p["eur_per_operating_day"], abs=0.02
            )
            assert p["basis"]

    def test_without_the_tracks_the_tariff_is_simply_absent(
        self, built, loader, route_berlin_dresden_wien
    ):
        """A caller that has no track infrastructure to hand still gets the
        kWh and the euros — only the tariff fields are missing."""
        from models.evaluation.operations import build_operations
        from api.helpers.route_serialize import route_from_dict

        result, _, _ = built
        scenario_id = route_berlin_dresden_wien["scenario_id"]
        route, _ = route_from_dict(
            route_berlin_dresden_wien, loader, scenario_id=scenario_id
        )
        ops = build_operations(route, result)
        for trip in ops["infrastructure"]["trips"]:
            for country in trip["energy"]["countries"]:
                assert "tariff" not in country
                assert country["kwh"] > 0


# =============================================================================
# Mass-based station charges — CALC 0.9.32
# =============================================================================

STOPS_BERLIN_PRAHA_WIEN = ["osm:n3856100103", "osm:n3134751791", "osm:w423692233"]
PRAHA_HL_N = "osm:n3134751791"


class TestPerTonneStationCharge:
    """Czechia prices a passenger stop per tonne of coach mass (Správa
    železnic Annex C II.5). The catalog carries the rate beside an explicit
    0.00 fixed part; the evaluation multiplies it by the composition's
    total_weight_t. These tests skip while Praha has no rate — the tariff
    reaches the database through the catalog, and a catalog without CZ is
    a data gap, not a model regression."""

    @pytest.fixture(scope="class")
    def built_via_praha(self, loader, api_base):
        from tests.conftest import STANDARD_DEMAND
        from tests.helpers import build_route
        from api.helpers.route_serialize import route_from_dict
        from models.evaluation.operations import build_operations
        from models.pipeline import evaluate_and_build_views

        route_dict = build_route(
            api_base, STOPS_BERLIN_PRAHA_WIEN, auto_stop_addition="off"
        )
        scenario_id = route_dict["scenario_id"]
        route, _ = route_from_dict(route_dict, loader, scenario_id=scenario_id)
        for pair in route.trip_pairs:
            pair.od_pairs = []
        for class_main, places_sold, avg_price in STANDARD_DEMAND:
            add_directional_domain_demand(route, class_main, places_sold, avg_price)
        tracks = loader.build_all_tracks(scenario_id)
        stop_infra = loader.build_all_stops(scenario_id)
        praha = stop_infra.get(PRAHA_HL_N)
        if praha is None or not praha.stop_charge_per_tonne_eur:
            pytest.skip("Praha hl.n. carries no per-tonne rate — CZ not in the catalog")
        result, _ = evaluate_and_build_views(
            route, tracks, stop_infra, loader.build_all_passages(scenario_id)
        )
        return (
            route,
            result,
            stop_infra,
            build_operations(route, result, tracks, stop_infra),
        )

    def test_praha_pays_rate_times_coach_mass(self, built_via_praha):
        route, result, stop_infra, _ = built_via_praha
        praha = stop_infra.get(PRAHA_HL_N)
        mass = route.trip_pairs[0].composition.total_weight_t
        calls = [c for c in result.stop_costs if c.stop_id == PRAHA_HL_N]
        assert len(calls) == 2  # outbound and return both call
        for c in calls:
            assert c.station_charge_eur == pytest.approx(
                praha.stop_charge_eur + praha.stop_charge_per_tonne_eur * mass,
                abs=0.005,
            )
            assert c.station_charge_per_tonne_eur == praha.stop_charge_per_tonne_eur
            assert c.train_mass_t == pytest.approx(mass)

    def test_per_call_stops_on_the_same_route_are_untouched(self, built_via_praha):
        """The mass term is zero for a per-call tariff: Berlin and Wien pay
        exactly their catalog figure, as before 0.9.32."""
        _, result, stop_infra, _ = built_via_praha
        for c in result.stop_costs:
            if c.stop_id == PRAHA_HL_N:
                continue
            assert c.station_charge_per_tonne_eur == 0.0
            assert c.station_charge_eur == pytest.approx(
                stop_infra.get(c.stop_id).stop_charge_eur, abs=0.005
            )

    def test_operations_view_shows_the_rate_and_the_mass(self, built_via_praha):
        """A reader can check the Praha figure from the view alone."""
        _, _, _, ops = built_via_praha
        for trip in ops["infrastructure"]["trips"]:
            calls = {c["stop_id"]: c for c in trip["stations"]["calls"]}
            praha = calls[PRAHA_HL_N]
            assert praha["per_tonne"] is not None
            assert praha["eur"] == pytest.approx(
                praha["per_tonne"]["eur_per_t"] * praha["per_tonne"]["train_mass_t"],
                abs=0.01,
            )
            assert praha["defaulted"] is False
            for stop_id, call in calls.items():
                if stop_id != PRAHA_HL_N:
                    assert call["per_tonne"] is None
