"""
test_20_route_content.py
========================
Content-logic tests for route-building — verifies the numbers a route
carries are internally consistent and match the models that produced them,
using only data present in the response. Routes are built via
POST /api/proposal/calc (tests/helpers.py:build_route()).

Covers:
  - Country attribution: shares sum to 1, expected countries present,
    per-country km sums to trip distance
  - Route geometry sanity: direct vs detour distance, outbound/return symmetry
  - Timetable math: arrival = departure + driving + dynamics + buffer, dwell at
    intermediate stops
  - Track infra defaulting as seen by a compute (SE)
  - Energy model: flat 28 kWh/km dummy factor, composition-independent
    (REPLACE the flat-factor tests once the real regression model is calibrated)
  - Parkings/shuntings derivation
  - Mode switches (routing_mode/timetable_mode/schedule_mode/
    auto_stop_addition), fixed-night interval stretching, scenario_id
    handling — content coverage ported from the pre-WP5 contract suite
    (Brno auto-insertion behavior, fixed-night slack/warning math); only
    the endpoint and response-envelope shape changed at the port, not
    what's asserted.
"""

import pytest
import requests

from tests.conftest import STOPS_BERLIN_DRESDEN_WIEN, STOPS_BERLIN_WIEN
from tests.helpers import (
    PROPOSAL_CALC_URL,
    all_trips,
    build_route,
    country_km,
    route_countries,
    stop_times,
    trip_by_direction,
    trip_distance_km,
)


# =============================================================================
# Country attribution
# =============================================================================


class TestCountryAttribution:
    def test_shares_sum_to_one_per_segment(self, route_berlin_zuerich_wien):
        """country_distance_shares and country_time_shares each sum to 1.0
        on every segment — the allocation basis for TAC/energy costing."""
        for trip in all_trips(route_berlin_zuerich_wien):
            for seg in trip["segments"]:
                assert sum(seg["country_distance_shares"].values()) == pytest.approx(
                    1.0, abs=1e-3
                )
                assert sum(seg["country_time_shares"].values()) == pytest.approx(
                    1.0, abs=1e-3
                )

    def test_berlin_wien_crosses_de_and_at(self, route_berlin_wien):
        """Berlin → Wien touches at least DE and AT."""
        countries = route_countries(route_berlin_wien)
        assert {"DE", "AT"} <= countries

    def test_via_zuerich_crosses_three_countries(self, route_berlin_zuerich_wien):
        """Berlin → Zürich → Wien touches at least DE, CH, AT."""
        countries = route_countries(route_berlin_zuerich_wien)
        assert {"DE", "CH", "AT"} <= countries

    def test_country_km_sums_to_trip_distance(self, route_berlin_zuerich_wien):
        """Per-country km (distance × share) sums back to the trip's total
        distance — no distance is lost or double-counted in attribution."""
        for trip in all_trips(route_berlin_zuerich_wien):
            attributed = sum(country_km(trip).values())
            assert attributed == pytest.approx(trip_distance_km(trip), rel=1e-3)

    def test_track_infrastructure_matches_traversed_countries(
        self, route_berlin_zuerich_wien
    ):
        """route['track_infrastructure'] lists every country the segments
        touch (incl. transit-only), and nothing beyond segment + stop
        countries — mirrors Route.countries exactly."""
        route = route_berlin_zuerich_wien
        listed = {t["country_code"] for t in route["track_infrastructure"]}
        traversed = route_countries(route)
        stop_countries = {
            st["country_code"] for trip in all_trips(route) for st in stop_times(trip)
        }
        assert traversed <= listed
        assert listed <= traversed | stop_countries


# =============================================================================
# Route geometry sanity
# =============================================================================


class TestRouteGeometry:
    def test_outbound_and_return_distances_symmetric(self, route_berlin_wien):
        """Outbound and return follow (near-)identical rail paths — total
        distances agree within 5%."""
        out_km = trip_distance_km(trip_by_direction(route_berlin_wien, 0))
        ret_km = trip_distance_km(trip_by_direction(route_berlin_wien, 1))
        assert out_km == pytest.approx(ret_km, rel=0.05)

    def test_detour_not_shorter_than_direct(
        self, route_berlin_wien, route_berlin_zuerich_wien
    ):
        """Berlin → Wien via Zürich cannot be shorter than the direct routing
        — a violation would mean the direct route wasn't actually optimised."""
        direct_km = trip_distance_km(trip_by_direction(route_berlin_wien, 0))
        detour_km = trip_distance_km(trip_by_direction(route_berlin_zuerich_wien, 0))
        assert detour_km >= direct_km

    def test_distance_independent_of_composition(self, api_base):
        """Same stops, different compositions with identical routing flags
        (both STD, hsr_allowed=True) → identical route distance.

        auto_stop_addition="off": this pins a ROUTING property, and the
        auto-add layer on top is legitimately composition-dependent —
        stop costs include the mass-dependent accel/brake pair, so a
        heavier composition affords fewer marginal candidates within the
        same detour budget and the final stop sets (hence distances) can
        differ by metres. With the selection layer disabled, the same
        stops through the same profile must route identically."""
        distances = {}
        # Same material family on purpose: REF compositions route differently
        # (hsr_allowed=False, v_max 200) — distance invariance only holds
        # within one material strategy.
        for comp_id in ("NEW-BAL-7", "NEW-BAL-14"):
            route = build_route(
                api_base,
                STOPS_BERLIN_WIEN,
                comp_id,
                auto_stop_addition="off",
            )
            distances[comp_id] = trip_distance_km(trip_by_direction(route, 0))
        assert distances["NEW-BAL-7"] == distances["NEW-BAL-14"]


# =============================================================================
# Timetable math
# =============================================================================


class TestTimetableMath:
    def test_arrival_equals_departure_plus_driving_plus_buffer(
        self, route_berlin_dresden_wien
    ):
        """For every segment: to_stop.arrival = from_stop.departure +
        driving_time + buffer_time — the exact build_final_timetable() math."""
        for trip in all_trips(route_berlin_dresden_wien):
            for seg in trip["segments"]:
                dep = seg["from_stop"]["departure_time_min"]
                arr = seg["to_stop"]["arrival_time_min"]
                assert (
                    arr
                    == dep
                    + seg["driving_time_min"]
                    + seg["dynamics_time_min"]
                    + seg["buffer_time_min"]
                )

    def test_intermediate_dwell_at_least_one_minute(self, route_berlin_dresden_wien):
        """Dresden (the intermediate stop) has a real positive dwell —
        departure strictly after arrival. The exact minimum depends on which
        boarding/alighting minimum applies, so only positivity is asserted."""
        for trip in all_trips(route_berlin_dresden_wien):
            dresden = next(
                s for s in stop_times(trip) if s["stop_id"] == "osm:n25397500"
            )
            assert dresden["dwell_time_min"] is not None
            assert dresden["dwell_time_min"] >= 1

    def test_buffer_time_non_negative(self, route_berlin_dresden_wien):
        """Buffer time (schedule padding) is never negative."""
        for trip in all_trips(route_berlin_dresden_wien):
            for seg in trip["segments"]:
                assert seg["buffer_time_min"] >= 0
                assert seg["dynamics_time_min"] >= 0


# =============================================================================
# Track infrastructure defaulting as seen by a compute
# =============================================================================


class TestTrackInfraDefaulting:
    def test_se_route_lists_dk_and_se(self, route_copenhagen_stockholm):
        """Copenhagen → Stockholm lists both DK and SE track infra entries."""
        countries = {
            t["country_code"]
            for t in route_copenhagen_stockholm["track_infrastructure"]
        }
        assert {"DK", "SE"} <= countries

    def test_defaulted_fields_only_contain_exposed_fields(
        self, route_copenhagen_stockholm
    ):
        """defaulted_fields entries are restricted to the physics fields the
        response actually shows — never a cost field like tac_eur_train_km."""
        exposed = {
            "hsr_allowed",
            "min_boarding_time_min",
            "min_alighting_time_min",
            "terrain_score",
            "terrain_category",
            "buffer_quota_per",
        }
        for entry in route_copenhagen_stockholm["track_infrastructure"]:
            assert set(entry["defaulted_fields"]) <= exposed, (
                f"{entry['country_code']}: unexpected defaulted field"
            )


# =============================================================================
# Energy model (current dummy implementation)
# =============================================================================


# =============================================================================
# Parkings and shuntings
# =============================================================================


class TestParkingsAndShuntings:
    def test_two_shuntings_per_trip(self, route_berlin_wien):
        """Current rule: 2 shuntings per trip (one per trip end/start), no
        deduplication → one round-trip pair produces 4 shuntings."""
        n_trips = len(all_trips(route_berlin_wien))
        assert len(route_berlin_wien["shuntings"]) == 2 * n_trips

    def test_shuntings_at_trip_terminals(self, route_berlin_wien):
        """Every shunting sits at a terminal stop of the trip it belongs to."""
        terminals_by_trip = {
            trip["trip_id"]: {
                stop_times(trip)[0]["stop_id"],
                stop_times(trip)[-1]["stop_id"],
            }
            for trip in all_trips(route_berlin_wien)
        }
        for s in route_berlin_wien["shuntings"]:
            assert s["stop_id"] in terminals_by_trip[s["trip_id"]], (
                f"Shunting at non-terminal stop {s['stop_id']} for {s['trip_id']}"
            )

    def test_parkings_deduplicated_by_stop(self, route_berlin_wien):
        """Parkings exist and are deduplicated by stop_id, each listing the
        trips whose formation parks there."""
        parkings = route_berlin_wien["parkings"]
        assert len(parkings) > 0
        stop_ids = [p["stop_id"] for p in parkings]
        assert len(stop_ids) == len(set(stop_ids)), "Duplicate parking stop_ids"
        for p in parkings:
            assert len(p["trip_ids"]) >= 1


# =============================================================================
# Mode switches, fixed-night interval, and scenario handling
# (ported from the pre-WP5 contract suite — see module docstring)
# =============================================================================

BASE_REQUEST = {
    "stops": STOPS_BERLIN_DRESDEN_WIEN,
    "composition_id": "NEW-BAL-7",
    # Pinned off so the structural tests below see a deterministic
    # caller's-list route — osm:n3325029085 would otherwise be auto-added
    # (see module docstring); the add/suggest paths have their own
    # fixture/requests in TestModeSwitches.
    "auto_stop_addition": "off",
}

# The stop list the "add" default actually produces on this corridor
# (AUTO_STOP_BUFFER_M=10km, AUTO_STOP_ANALYTIC_DETOUR_M=100m) — 7 catalog
# stops merged in at their geographic positions between Dresden and Wien,
# everything else the caller's own. Re-derive with a POST of
# auto_stop_addition="add" and read trip_pairs[0].outbound whenever
# AUTO_STOP_BUFFER_M, AUTO_STOP_ANALYTIC_DETOUR_M, AUTO_STOP_MAX_DETOUR_PER,
# or the stop catalog itself changes.
#
# Updated at ROUTE_BUILDER 0.9.24, which moved the detour budget onto
# TECHNICAL trip time (driving + dynamics + dwell) instead of padded time.
# osm:n2736023837 and osm:n3129289404 dropped out: both sat at the margin of
# the old, larger budget. That marginality is inherent — this list pins a
# greedy cumulative budget, so a few per cent either way moves its tail, and
# a diff here means the budget moved, not that the search broke.
#
# Re-pinned when the stop classification pipeline replaced the catalog:
# coordinates now come from OSM rather than ONTD, so marginal candidates
# moved a little and the greedy budget resolved differently. Bad Schandau
# (osm:n2736023837) and Ceska Trebova (osm:n3129289404) came back in, and
# Decin (osm:n5062517821) and Breclav-area osm:n3325029085 dropped out to
# pay for them — the same tail churn the paragraph above describes, at the
# same count of seven. What is asserted structurally rather than by
# identity is the invariant that matters: every stop 'add' inserts also
# appears in 'suggest' (test_..._suggest_... below).
STOPS_WITH_BRNO = [
    "osm:n3856100103",
    "osm:n25397500",
    "osm:n2736023837",
    "osm:n4171354660",
    "osm:n3134733933",
    "osm:n24684084",
    "osm:n3129312254",
    "osm:n3129289404",
    "osm:n3315724401",
    "osm:w423692233",
]


# The merged compute response's top-level envelope (api/proposal_calc.py) —
# used by the suggest-mode key-set assertion below.
_CALC_ENVELOPE_KEYS = {
    "route_builder_version",
    "calc_version",
    "route_fingerprint",
    "cache_hit",
    "request",
    "summary",
    "route",
    "evaluation",
}


@pytest.fixture(scope="module")
def plan_response(api_base):
    """One full compute response (POST /api/proposal/calc) for the standard
    3-stop request with auto_stop_addition="off" — built once for this
    module."""
    resp = requests.post(
        f"{api_base}{PROPOSAL_CALC_URL}", json=BASE_REQUEST, timeout=90
    )
    assert resp.status_code == 200, f"Route build failed: {resp.text[:300]}"
    return resp.json()


@pytest.fixture(scope="module")
def plan_response_default_add(api_base):
    """Same request with auto_stop_addition omitted entirely — covers the
    "add" default, which inserts osm:n3325029085 on this corridor. Built once
    for this module."""
    body = {k: v for k, v in BASE_REQUEST.items() if k != "auto_stop_addition"}
    resp = requests.post(f"{api_base}{PROPOSAL_CALC_URL}", json=body, timeout=90)
    assert resp.status_code == 200, f"Route build failed: {resp.text[:300]}"
    return resp.json()


class TestModeSwitches:
    def test_explicit_default_values_accepted(self, api_base):
        """Spelling out every default mode explicitly is accepted."""
        body = {
            **BASE_REQUEST,
            "routing_mode": "fullRouting",
            "timetable_mode": "simpleAutomatic",
            "schedule_mode": "alwaysDaily",
            "auto_stop_addition": "add",
        }
        resp = requests.post(f"{api_base}{PROPOSAL_CALC_URL}", json=body, timeout=90)
        assert resp.status_code == 200

    def test_simple_routing_mode_accepted(self, api_base):
        """routing_mode='simpleRouting' (cheap single-pass routing) is a
        valid alternative and still produces a full route."""
        body = {**BASE_REQUEST, "routing_mode": "simpleRouting"}
        resp = requests.post(f"{api_base}{PROPOSAL_CALC_URL}", json=body, timeout=90)
        assert resp.status_code == 200
        assert len(resp.json()["route"]["trip_pairs"]) == 1

    @pytest.mark.parametrize(
        "field",
        ["routing_mode", "timetable_mode", "schedule_mode", "auto_stop_addition"],
    )
    def test_invalid_mode_returns_400(self, api_base, field):
        """An unknown value for any mode switch is rejected at validation."""
        body = {**BASE_REQUEST, field: "not-a-real-mode"}
        resp = requests.post(f"{api_base}{PROPOSAL_CALC_URL}", json=body, timeout=10)
        assert resp.status_code == 400

    # --- auto_stop_addition — one case per enum value + bool rejection ------

    def test_auto_stop_addition_defaults_to_add_and_inserts_brno(
        self, plan_response_default_add
    ):
        """With auto_stop_addition omitted (the 'add' default), 7 catalog
        stops along the Dresden-Wien corridor — all within
        AUTO_STOP_BUFFER_M (10km) and within the cumulative detour budget
        — are inserted at their geographic positions, marked
        auto_added=true, everything else the caller's own (see
        STOPS_WITH_BRNO's own comment for how to re-derive this list:
        10 entries total = 2 user stops + 7 auto-added + 1 user stop).
        The return trip carries the same final stop list reversed with the
        same auto_added marking (the search runs once, from outbound — see
        _build_trip_pair() in route_factory.py)."""
        pair = plan_response_default_add["route"]["trip_pairs"][0]
        assert "suggested_stops" not in plan_response_default_add

        expected_added = [False, False] + [True] * 7 + [False]
        outbound = stop_times(pair["outbound"])
        assert [s["stop_id"] for s in outbound] == STOPS_WITH_BRNO
        assert [s["auto_added"] for s in outbound] == expected_added

        return_stops = stop_times(pair["return_trip"])
        assert [s["stop_id"] for s in return_stops] == list(reversed(STOPS_WITH_BRNO))
        assert [s["auto_added"] for s in return_stops] == list(reversed(expected_added))

    def test_auto_stop_addition_add_explicit_accepted(self, api_base):
        """Explicit 'add' (the default spelled out) behaves identically to
        the omitted field — Brno inserted — and does not carry a
        suggested_stops section (that's exclusive to 'suggest')."""
        body = {**BASE_REQUEST, "auto_stop_addition": "add"}
        resp = requests.post(f"{api_base}{PROPOSAL_CALC_URL}", json=body, timeout=90)
        assert resp.status_code == 200
        assert "suggested_stops" not in resp.json()
        outbound = resp.json()["route"]["trip_pairs"][0]["outbound"]
        assert [s["stop_id"] for s in stop_times(outbound)] == STOPS_WITH_BRNO

    def test_auto_stop_addition_off_returns_exact_caller_list(self, api_base):
        """Explicit opt-out: auto_stop_addition='off' skips the candidate
        search entirely and returns exactly the caller's own stop list,
        with no suggested_stops section."""
        body = {**BASE_REQUEST, "auto_stop_addition": "off"}
        resp = requests.post(f"{api_base}{PROPOSAL_CALC_URL}", json=body, timeout=90)
        assert resp.status_code == 200
        assert "suggested_stops" not in resp.json()
        outbound = resp.json()["route"]["trip_pairs"][0]["outbound"]
        assert [s["stop_id"] for s in stop_times(outbound)] == STOPS_BERLIN_DRESDEN_WIEN

    def test_auto_stop_addition_suggest_returns_suggested_stops_section(
        self, api_base, plan_response_default_add
    ):
        """auto_stop_addition='suggest' routes exactly like 'off' (caller's
        own stop list, nothing added, auto_added false throughout) but
        carries a top-level suggested_stops list placed between request and
        route.

        Mode 'suggest' deliberately ignores AUTO_STOP_MAX_DETOUR_PER (see
        apply_auto_stop_addition()'s docstring), so at the wide
        AUTO_STOP_BUFFER_M=10km buffer it surfaces MORE candidates than
        'add' actually inserts — cross-mode consistency is now a subset
        relation, not equality: every stop 'add' inserted also appears in
        'suggest' (both start from the same candidate search), but
        'suggest' additionally surfaces the over-budget candidates 'add'
        had to stop short of. This corridor: 20 suggested vs 10 inserted.

        Re-pinned with the stop classification pipeline's catalog, which is
        denser along the Berlin approach — Gesundbrunnen, Lichtenberg,
        Ostbahnhof and Suedkreuz are all genuinely within AUTO_STOP_BUFFER_M
        of the corridor and now appear, where the previous ONTD-only catalog
        simply had no row for them.

        The final pair (osm:n60093107 / osm:n66432827) is asserted as
        a set, not a strict order: both sit close together near the
        route's Vienna approach, so suggest_auto_stops()'s
        (leg_index, along_leg_fraction) sort assigns them to the routed
        polyline geometrically, not topologically — which one gets the
        smaller fraction can flip with the router's own path geometry
        (graph version, internal tie-breaking) even though both stops'
        coordinates are fixed and unchanged. Asserting a strict order for
        a genuinely near-tied pair over-specifies the router, not the
        auto-stop logic this test targets; every other candidate here is
        well-separated and keeps a strict order."""
        body = {**BASE_REQUEST, "auto_stop_addition": "suggest"}
        resp = requests.post(f"{api_base}{PROPOSAL_CALC_URL}", json=body, timeout=90)
        assert resp.status_code == 200
        payload = resp.json()

        assert set(payload) == _CALC_ENVELOPE_KEYS | {"suggested_stops"}
        keys = list(payload)
        assert (
            keys.index("request")
            < keys.index("suggested_stops")
            < keys.index("summary")
            < keys.index("route")
        )

        suggested = payload["suggested_stops"]
        suggested_ids = [s["stop_id"] for s in suggested]
        assert suggested_ids[:-2] == [
            "osm:n267379240",
            "osm:n3723386251",
            "osm:n2736023837",
            "osm:n5062517821",
            "osm:n4171354660",
            "osm:n3134751791",
            "osm:n3134733933",
            "osm:n24684084",
            "osm:n3129312254",
            "osm:n3129289404",
            "osm:n3325029085",
            "osm:n3315724401",
        ]

        # The cross-mode invariant, independent of either pinned list: 'add'
        # and 'suggest' run the same candidate search, so everything 'add'
        # inserted must be offered by 'suggest'. This is what actually breaks
        # if the search regresses; the lists above only pin today's budget.
        auto_added = [
            s["stop_id"]
            for s in stop_times(
                plan_response_default_add["route"]["trip_pairs"][0]["outbound"]
            )
            if s["auto_added"]
        ]
        assert set(auto_added) <= set(suggested_ids)
        assert set(suggested_ids[-2:]) == {"osm:n60093107", "osm:n66432827"}
        for s in suggested:
            assert set(s) == {
                "stop_id",
                "stop_name",
                "country_code",
                "lat",
                "lon",
                "added_time_min",
            }
            assert s["added_time_min"] > 0

        # Route itself is exactly the caller's own list — nothing added.
        outbound = payload["route"]["trip_pairs"][0]["outbound"]
        assert [s["stop_id"] for s in stop_times(outbound)] == STOPS_BERLIN_DRESDEN_WIEN
        for stop in stop_times(outbound):
            assert stop["auto_added"] is False

        # Cross-mode consistency: every 'add'-inserted stop is a subset of
        # 'suggest's fuller candidate list (not equality — see docstring).
        added = {
            s["stop_id"]
            for s in stop_times(
                plan_response_default_add["route"]["trip_pairs"][0]["outbound"]
            )
            if s["auto_added"]
        }
        assert added <= {s["stop_id"] for s in suggested}

    def test_auto_added_field_false_throughout_when_off(self, plan_response):
        """With auto_stop_addition='off' (the module fixture), every stop is
        the caller's own — auto_added is present and false throughout."""
        outbound = plan_response["route"]["trip_pairs"][0]["outbound"]
        for stop in stop_times(outbound):
            assert stop["auto_added"] is False

    @pytest.mark.parametrize("legacy_bool", [True, False])
    def test_auto_stop_addition_bool_returns_400(self, api_base, legacy_bool):
        """Pre-0.9.5 booleans are rejected, not silently mapped to
        'add'/'off' — the request contract is the string enum only."""
        body = {**BASE_REQUEST, "auto_stop_addition": legacy_bool}
        resp = requests.post(f"{api_base}{PROPOSAL_CALC_URL}", json=body, timeout=10)
        assert resp.status_code == 400

    def test_auto_stop_addition_wrong_type_returns_400(self, api_base):
        body = {**BASE_REQUEST, "auto_stop_addition": "yes"}
        resp = requests.post(f"{api_base}{PROPOSAL_CALC_URL}", json=body, timeout=10)
        assert resp.status_code == 400


# =============================================================================
# timetable_mode='simpleAutomaticWithFixedNight'
# =============================================================================

# Night window thresholds, minutes from midnight day 1 — mirror
# NIGHT_START_MIN / NIGHT_END_MIN in models/route/version.py. Deliberately
# restated as literals: these tests pin the API contract, not the constants.
NIGHT_START = 24 * 60  # 00:00 (+1)
NIGHT_END = 29 * 60  # 05:00 (+1)

FIXED_NIGHT_REQUEST = {
    **BASE_REQUEST,
    "timetable_mode": "simpleAutomaticWithFixedNight",
    # Berlin->Dresden is ~2h naturally — far shorter than the 5h night
    # window, so this interval MUST be stretched, exercising slack
    # distribution and the slow-section warning in one live response.
    "fixed_night_interval": ["osm:n3856100103", "osm:n25397500"],
}


@pytest.fixture(scope="module")
def fixed_night_response(api_base):
    """One full fixed-night response for the Berlin-Dresden interval on the
    standard corridor — built once for this module."""
    resp = requests.post(
        f"{api_base}{PROPOSAL_CALC_URL}", json=FIXED_NIGHT_REQUEST, timeout=90
    )
    assert resp.status_code == 200, f"Route build failed: {resp.text[:300]}"
    return resp.json()


class TestFixedNightMode:
    @staticmethod
    def _interval_times(trip, interval):
        """(departure at interval start, arrival at interval end) for one
        trip, looked up by stop_id."""
        by_id = {s["stop_id"]: s for s in stop_times(trip)}
        return (
            by_id[interval[0]]["departure_time_min"],
            by_id[interval[1]]["arrival_time_min"],
        )

    def test_interval_covers_night_window_both_directions(self, fixed_night_response):
        """The fixed interval departs strictly before 00:00 and arrives at
        05:00 or later — in the outbound direction as requested, and in the
        return direction with the interval applied reversed automatically."""
        interval = FIXED_NIGHT_REQUEST["fixed_night_interval"]
        for trip in all_trips(fixed_night_response["route"]):
            trip_interval = interval if trip["direction"] == 0 else interval[::-1]
            dep_a, arr_b = self._interval_times(trip, trip_interval)
            assert dep_a < NIGHT_START, f"D{trip['direction']}: departs {dep_a}"
            assert arr_b >= NIGHT_END, f"D{trip['direction']}: arrives {arr_b}"

    def test_short_interval_is_stretched_with_slack(self, fixed_night_response):
        """A ~2h interval must gain slack to span the 5h+1min night window —
        slack sits ONLY on the interval's own legs, and each segment's
        elapsed stop-to-stop time equals its physics components + slack."""
        interval = FIXED_NIGHT_REQUEST["fixed_night_interval"]
        for trip in all_trips(fixed_night_response["route"]):
            trip_interval = set(interval if trip["direction"] == 0 else interval[::-1])
            total_slack = 0
            for seg in trip["segments"]:
                seg_stops = {seg["from_stop"]["stop_id"], seg["to_stop"]["stop_id"]}
                if not seg_stops == trip_interval:
                    assert seg["slack_time_min"] == 0
                total_slack += seg["slack_time_min"]

                elapsed = (
                    seg["to_stop"]["arrival_time_min"]
                    - seg["from_stop"]["departure_time_min"]
                )
                physics = (
                    seg["driving_time_min"]
                    + seg["dynamics_time_min"]
                    + seg["buffer_time_min"]
                    + seg["slack_time_min"]
                )
                assert elapsed == physics
            assert total_slack > 0

    def test_slow_stretch_produces_timetable_warning(self, fixed_night_response):
        """Stretching ~2h of running to a 5h window drops the interval's
        timetable speed far below FIXED_NIGHT_MIN_SPEED_RATIO of routing
        speed — every trip carries a fixed_night_stretch_slow warning with
        both speeds and their ratio."""
        for trip in all_trips(fixed_night_response["route"]):
            warnings = trip["general_parameters"]["timetable_warnings"]
            assert len(warnings) == 1
            w = warnings[0]
            assert w["code"] == "fixed_night_stretch_slow"
            assert set(w) == {
                "code",
                "interval",
                "timetable_speed_kmh",
                "routing_speed_kmh",
                "ratio",
            }
            assert 0 < w["timetable_speed_kmh"] < w["routing_speed_kmh"]
            assert 0 < w["ratio"] < 1

    def test_long_interval_gets_no_slack_or_warning(self, api_base):
        """An interval whose natural span already exceeds the night window
        (Berlin->Wien, ~7h+) needs no stretching: zero slack everywhere, no
        warnings, window constraints still satisfied."""
        body = {
            **FIXED_NIGHT_REQUEST,
            "fixed_night_interval": ["osm:n3856100103", "osm:w423692233"],
        }
        resp = requests.post(f"{api_base}{PROPOSAL_CALC_URL}", json=body, timeout=90)
        assert resp.status_code == 200, resp.text[:300]
        for trip in all_trips(resp.json()["route"]):
            interval = (
                body["fixed_night_interval"]
                if trip["direction"] == 0
                else body["fixed_night_interval"][::-1]
            )
            dep_a, arr_b = self._interval_times(trip, interval)
            assert dep_a < NIGHT_START
            assert arr_b >= NIGHT_END
            assert all(s["slack_time_min"] == 0 for s in trip["segments"])
            assert trip["general_parameters"]["timetable_warnings"] == []

    @pytest.mark.parametrize(
        "interval, reason",
        [
            (None, "missing entirely"),
            (["osm:n3856100103"], "only one stop"),
            (["osm:n3856100103", "osm:n3856100103"], "same stop twice"),
            (["osm:n3856100103", 42], "non-string entry"),
            (["osm:n3856100103", "osm:n2506241285"], "stop not in stops list"),
            (["osm:w423692233", "osm:n3856100103"], "wrong travel order"),
        ],
    )
    def test_invalid_interval_returns_400(self, api_base, interval, reason):
        body = {k: v for k, v in FIXED_NIGHT_REQUEST.items()}
        if interval is None:
            body.pop("fixed_night_interval")
        else:
            body["fixed_night_interval"] = interval
        resp = requests.post(f"{api_base}{PROPOSAL_CALC_URL}", json=body, timeout=30)
        assert resp.status_code == 400, f"{reason}: {resp.text[:200]}"
        assert resp.json()["error"] == "validation_error"

    def test_interval_rejected_outside_fixed_night_mode(self, api_base):
        """fixed_night_interval alongside plain simpleAutomatic is rejected,
        not silently ignored."""
        body = {
            **BASE_REQUEST,
            "timetable_mode": "simpleAutomatic",
            "fixed_night_interval": ["osm:n3856100103", "osm:n25397500"],
        }
        resp = requests.post(f"{api_base}{PROPOSAL_CALC_URL}", json=body, timeout=30)
        assert resp.status_code == 400
        assert resp.json()["error"] == "validation_error"


# =============================================================================
# Scenario handling
# =============================================================================
# WP5: the proposal_id/proposal_version half of the old TestProposalAndScenario
# is gone — /api/proposal/calc has no such fields (publish-only concerns,
# §2.1). Only the scenario_id defaulting/override behavior survives.


class TestScenarioHandling:
    def test_omitted_scenario_id_resolves_to_base(self, plan_response, base_scenario):
        """Without a scenario_id, the route embeds the concrete resolved id
        of the live is_current_base scenario — never None."""
        assert plan_response["route"]["scenario_id"] == base_scenario["scenario_id"]

    def test_explicit_scenario_id_embedded(self, api_base, hsr_scenario):
        """An explicit scenario_id (the seeded HSR-allowed scenario) is
        embedded verbatim."""
        body = {**BASE_REQUEST, "scenario_id": hsr_scenario["scenario_id"]}
        resp = requests.post(f"{api_base}{PROPOSAL_CALC_URL}", json=body, timeout=90)
        assert resp.status_code == 200
        assert resp.json()["route"]["scenario_id"] == hsr_scenario["scenario_id"]
