"""
test_42_proposal_family_api.py
==============================
Contract tests for the proposal family (adapters/family/README.md):

  POST /api/proposal/family
  GET  /api/proposal/family/<key>
  GET  /api/proposal/family/<key>/members/<sv>/<comp>/views

Against the live stack. Every infra_2032 member is an error member on a
one-instance stack (routing_graph_not_configured) and an ok member on a
two-instance one — the assertions are written for both.

Kept small on purpose: a default-axes family is 6 × 12 members. One narrow
explicit family (2 variants × 2 compositions) covers the structural
cases, one default family the counts and the cache, both shared via
module fixtures.
"""

from __future__ import annotations

import random

import pytest
import requests

from models.route.model import DEFAULT_COMPOSITION_ID
from tests.conftest import DEFAULT_COMPOSITION, REF_COMPOSITION, STOPS_BERLIN_WIEN
from tests.helpers import (
    PROPOSAL_FAMILY_URL,
    SCENARIOS_URL,
    compute,
    family,
    member_views_url,
    post_family,
)

BASE_REQUEST = {"stops": STOPS_BERLIN_WIEN, "auto_stop_addition": "off"}

MEMBER_KEYS_OK = {
    "scenario_variant_id",
    "composition_id",
    "status",
    "route_ref",
    "summary",
}
MEMBER_KEYS_ERROR = {
    "scenario_variant_id",
    "composition_id",
    "status",
    "error",
    "message",
}


@pytest.fixture(scope="module")
def scenarios(api_base):
    body = requests.get(f"{api_base}{SCENARIOS_URL}", timeout=15).json()
    variants = body["scenario_variants"]
    return {
        "variants": variants,
        "base": next(v for v in variants if v["is_current_base"]),
        "hsr_2026": next(v for v in variants if v["scenario_key"] == "infra-2026-hsr"),
        "base_2032": next(v for v in variants if v["scenario_key"] == "infra-2032"),
        "n_current": len(
            {v["scenario_id"] for v in body["current_base"]["scenarios"]}
            | {v["scenario_id"] for v in body["current_scenarios"]["scenarios"]}
        ),
        "n_measure_sets": len(body["measure_sets"]),
    }


@pytest.fixture(scope="module")
def narrow_body(scenarios):
    """2 variants (base, 2026 HSR) × 2 compositions = 4 ok members."""
    return {
        **BASE_REQUEST,
        "scenario_variant_ids": [
            scenarios["base"]["scenario_variant_id"],
            scenarios["hsr_2026"]["scenario_variant_id"],
        ],
        "composition_ids": [DEFAULT_COMPOSITION, REF_COMPOSITION],
    }


@pytest.fixture(scope="module")
def narrow_document(api_base, narrow_body):
    return family(api_base, **narrow_body)


@pytest.fixture(scope="module")
def default_document(api_base):
    return family(api_base, **BASE_REQUEST)


def ok_members(document):
    return [m for m in document["members"] if m["status"] == "ok"]


# =============================================================================
# Validation
# =============================================================================


class TestValidation:
    @pytest.mark.parametrize(
        "patch",
        [
            {"stops": ["osm:n3856100103"]},
            {"stops": "osm:n3856100103"},
            {"auto_stop_addition": "add"},
            {"timetable_mode": "nope"},
            {"scenario_variant_ids": []},
            {"scenario_variant_ids": [1, 1]},
            {"scenario_variant_ids": ["1"]},
            {"scenario_variant_ids": [999999]},
            {"composition_ids": ["NOT-A-TRAIN"]},
            {"presented": {"composition_id": 7}},
            {"presented": {"scenario_variant_id": 999999}},
        ],
    )
    def test_bad_requests_are_400(self, api_base, patch):
        resp = post_family(api_base, {**BASE_REQUEST, **patch}, timeout=30)
        assert resp.status_code == 400, resp.text[:300]
        assert resp.json()["error"] in {"validation_error", "family_too_large"}

    def test_empty_body_is_400(self, api_base):
        resp = requests.post(f"{api_base}{PROPOSAL_FAMILY_URL}", json={}, timeout=10)
        assert resp.status_code == 400

    def test_presented_outside_the_axes_is_400(self, api_base, narrow_body, scenarios):
        body = {
            **narrow_body,
            "presented": {
                "scenario_variant_id": scenarios["base_2032"]["scenario_variant_id"]
            },
        }
        resp = post_family(api_base, body, timeout=30)
        assert resp.status_code == 400
        assert "not on the axes" in " ".join(resp.json()["details"])


# =============================================================================
# The document
# =============================================================================


class TestDocument:
    def test_top_level_shape(self, narrow_document):
        assert set(narrow_document) == {
            "family_key",
            "route_builder_version",
            "calc_version",
            "request",
            "axes",
            "presented",
            "geometries",
            "routes",
            "members",
            "stats",
        }
        assert narrow_document["family_key"].startswith("sha256:")

    def test_request_echo_is_resolved_and_carries_no_axis(self, narrow_document):
        echo = narrow_document["request"]
        assert echo["stops"] == STOPS_BERLIN_WIEN
        assert echo["auto_stop_addition"] == "off"
        assert echo["timetable_mode"] == "simpleAutomatic"
        assert "composition_id" not in echo and "scenario_id" not in echo

    def test_axes_keep_request_order(self, narrow_document, narrow_body):
        axes = narrow_document["axes"]
        assert [v["scenario_variant_id"] for v in axes["scenario_variants"]] == (
            narrow_body["scenario_variant_ids"]
        )
        assert axes["compositions"] == narrow_body["composition_ids"]
        for variant in axes["scenario_variants"]:
            assert {
                "scenario_id",
                "measure_set_id",
                "scenario_key",
                "dimensions",
            } <= set(variant)

    def test_members_variants_outer_compositions_inner(
        self, narrow_document, narrow_body
    ):
        expected = [
            (sv, cid)
            for sv in narrow_body["scenario_variant_ids"]
            for cid in narrow_body["composition_ids"]
        ]
        actual = [
            (m["scenario_variant_id"], m["composition_id"])
            for m in narrow_document["members"]
        ]
        assert actual == expected

    def test_member_count_and_stats_agree(self, narrow_document):
        stats = narrow_document["stats"]
        assert stats["n_members"] == len(narrow_document["members"]) == 4
        assert stats["n_ok"] + stats["n_error"] == stats["n_members"]
        assert stats["n_ok"] == 4, "every 2026 member must compute"
        assert stats["n_routes"] == len(narrow_document["routes"])
        assert stats["n_geometries"] == len(narrow_document["geometries"])
        # cache_hit is not asserted here: family.documents outlives a test
        # run (3 h TTL), so this fixture is a miss on the first run of the
        # day and a hit on the next. TestCache below posts a family nothing
        # has built before and pins both sides of that.
        assert isinstance(stats["cache_hit"], bool)
        # The build context's own counters are nested, not merged: its
        # n_leg_variants counts distinct router calls, which is a different
        # number from this document's route count.
        assert stats["context"]["route_hits"] > 0

    def test_ok_member_shape(self, narrow_document):
        for member in ok_members(narrow_document):
            assert set(member) == MEMBER_KEYS_OK
            assert member["route_ref"] in narrow_document["routes"]
            summary = member["summary"]
            assert summary["total_distance_km"] > 0
            assert "subsidy_eur_per_year" in summary
            assert "geom_simplified" not in summary

    def test_every_reference_resolves_and_no_geometry_repeats(self, narrow_document):
        """The document carries each geometry once — the content-addressed
        pool — and every segment points into it."""
        pool = narrow_document["geometries"]
        seen_coords = [tuple(map(tuple, coords)) for coords in pool.values()]
        assert len(set(seen_coords)) == len(seen_coords), "a geometry is stored twice"
        for route in narrow_document["routes"].values():
            for pair in route["trip_pairs"]:
                for trip in (pair["outbound"], pair["return_trip"]):
                    for segment in trip["segments"]:
                        assert segment["geometry_id"] in pool

    def test_compact_route_shape(self, narrow_document):
        """Stops once per trip, segments by index, nothing the member can
        fetch elsewhere (route_serialize.route_compact_to_dict)."""
        for route in narrow_document["routes"].values():
            assert "geometries" not in route and "track_infrastructure" not in route
            for pair in route["trip_pairs"]:
                assert "composition" not in pair and "od_pairs" not in pair
                assert pair["composition_id"] in narrow_document["axes"]["compositions"]
                for trip in (pair["outbound"], pair["return_trip"]):
                    stops = trip["stops"]
                    assert [s["stop_id"] for s in stops][0] == STOPS_BERLIN_WIEN[0] or [
                        s["stop_id"] for s in stops
                    ][0] == STOPS_BERLIN_WIEN[-1]
                    for i, segment in enumerate(trip["segments"]):
                        assert (segment["from"], segment["to"]) == (i, i + 1)
                        assert "from_stop" not in segment and "to_stop" not in segment
                    assert len(stops) == len(trip["segments"]) + 1
                    assert not trip["trip_id"].startswith("P0_V0_")

    def test_routes_differ_across_variants(self, narrow_document, narrow_body):
        """The HSR variant routes differently for the same composition
        — otherwise the family would be one route repeated."""
        base, hsr = narrow_body["scenario_variant_ids"]
        refs = {
            m["scenario_variant_id"]: m["route_ref"]
            for m in ok_members(narrow_document)
            if m["composition_id"] == DEFAULT_COMPOSITION
        }
        assert refs[base] != refs[hsr]

    def test_presented_defaults_to_base_and_default_composition(
        self, narrow_document, scenarios
    ):
        assert narrow_document["presented"] == {
            "scenario_variant_id": scenarios["base"]["scenario_variant_id"],
            "composition_id": DEFAULT_COMPOSITION_ID,
        }

    def test_presented_member_summary_equals_calc(
        self, narrow_document, api_base, scenarios
    ):
        """A member is the same computation /calc makes for that scenario
        and composition — the summary must be identical, not close."""
        presented = narrow_document["presented"]
        member = next(
            m
            for m in ok_members(narrow_document)
            if (m["scenario_variant_id"], m["composition_id"])
            == (presented["scenario_variant_id"], presented["composition_id"])
        )
        calc = compute(
            api_base,
            STOPS_BERLIN_WIEN,
            presented["composition_id"],
            scenario_id=scenarios["base"]["scenario_id"],
            auto_stop_addition="off",
        )
        assert member["summary"] == calc["summary"]


# =============================================================================
# Default axes, error members, suggestions
# =============================================================================


class TestDefaultFamily:
    def test_default_axes_are_every_current_variant_times_the_catalog(
        self, default_document, scenarios, api_base
    ):
        catalog = requests.get(f"{api_base}/api/params/compositions", timeout=15).json()
        n_compositions = len(catalog["compositions"])
        n_variants = scenarios["n_current"] * scenarios["n_measure_sets"]
        assert len(default_document["axes"]["scenario_variants"]) == n_variants
        assert len(default_document["axes"]["compositions"]) == n_compositions
        assert default_document["stats"]["n_members"] == n_variants * n_compositions

    def test_base_variant_comes_first(self, default_document, scenarios):
        first = default_document["axes"]["scenario_variants"][0]
        assert first["scenario_variant_id"] == scenarios["base"]["scenario_variant_id"]

    def test_2032_members_are_ok_or_error_by_graph(self, default_document, scenarios):
        """With the second OpenRailRouting instance every 2032 member
        computes; without it every one is an error member with the code
        /calc would answer — never a 500, never a missing member."""
        members_2032 = [
            m
            for m in default_document["members"]
            if any(
                v["scenario_variant_id"] == m["scenario_variant_id"]
                and v["routing_graph_key"] == "infra_2032"
                for v in default_document["axes"]["scenario_variants"]
            )
        ]
        assert members_2032
        statuses = {m["status"] for m in members_2032}
        assert len(statuses) == 1, "one graph, one answer for every member on it"
        for member in members_2032:
            if member["status"] == "error":
                assert set(member) >= MEMBER_KEYS_ERROR
                assert member["error"] == "routing_graph_not_configured"

    def test_document_size_is_bounded(self, default_document):
        """The point of the compact route and the geometry pool: a full
        default family fits in a couple of megabytes, not tens."""
        import json

        raw = len(json.dumps(default_document, separators=(",", ":")))
        assert raw < 4_000_000, f"document is {raw / 1e6:.1f} MB"


class TestSuggestions:
    def test_suggest_runs_once_on_the_presented_member(self, api_base, narrow_body):
        document = family(api_base, **{**narrow_body, "auto_stop_addition": "suggest"})
        assert isinstance(document["suggested_stops"], list)
        for s in document["suggested_stops"]:
            assert s["added_time_min"] > 0
        assert document["request"]["auto_stop_addition"] == "suggest"
        assert document["stats"]["n_ok"] == 4, "suggest must not break other members"

    def test_off_family_carries_no_suggestions(self, narrow_document):
        assert "suggested_stops" not in narrow_document


# =============================================================================
# Cache and the two GETs
# =============================================================================


class TestCache:
    def test_a_new_family_misses_then_hits(self, api_base, narrow_body):
        """The miss → hit pair, on a family nothing has built before: the
        add-on minutes are randomised per run, so the key is new even on a
        database whose document cache is warm from an earlier run."""
        body = {
            **narrow_body,
            "expert_timetable": {
                "outbound": {
                    "segment_addons": [
                        {
                            "from_stop_id": STOPS_BERLIN_WIEN[0],
                            "to_stop_id": STOPS_BERLIN_WIEN[1],
                            "add_min": random.randint(1, 60),
                        }
                    ]
                }
            },
        }
        first = family(api_base, **body)
        assert first["stats"]["cache_hit"] is False
        second = family(api_base, **body)
        assert second["stats"]["cache_hit"] is True
        assert second["family_key"] == first["family_key"]
        assert second["members"] == first["members"]

    def test_second_post_is_a_cache_hit_with_the_same_key(
        self, api_base, narrow_body, narrow_document
    ):
        again = family(api_base, **narrow_body)
        assert again["family_key"] == narrow_document["family_key"]
        assert again["stats"]["cache_hit"] is True
        assert again["members"] == narrow_document["members"]

    def test_presented_is_not_in_the_key(self, api_base, narrow_body, narrow_document):
        body = {**narrow_body, "presented": {"composition_id": REF_COMPOSITION}}
        other = family(api_base, **body)
        assert other["family_key"] == narrow_document["family_key"]
        assert other["presented"]["composition_id"] == REF_COMPOSITION
        assert other["stats"]["cache_hit"] is True

    def test_expert_timetable_changes_key_and_times_not_the_corridor(
        self, api_base, narrow_body, narrow_document
    ):
        """A manual departure is a timetable edit: new key, new times, same
        corridor. The geometry check is by pool SIZE and route refs rather
        than by id: route_cache keys a stop pair lo→hi and serves the other
        direction reversed, so the very first build of a corridor can carry
        the return trip's own live path where every later build carries the
        reverse of the outbound's. Same corridor, different points — see
        models/family/context.py::prewarm, which routes the two directions
        in order so a cold build already matches the warm one."""
        shift_min = 30
        body = {
            **narrow_body,
            "expert_timetable": {
                "outbound": {"departure": {"mode": "shift", "shift_min": shift_min}}
            },
        }
        shifted = family(api_base, **body)
        assert shifted["family_key"] != narrow_document["family_key"]
        assert set(shifted["routes"]) == set(narrow_document["routes"])
        assert len(shifted["geometries"]) == len(narrow_document["geometries"])

        ref = next(m["route_ref"] for m in ok_members(shifted))

        def departure(document):
            return document["routes"][ref]["trip_pairs"][0]["outbound"]["stops"][0][
                "departure_time_min"
            ]

        assert (departure(shifted) - departure(narrow_document)) % (
            24 * 60
        ) == shift_min

    def test_get_by_key_returns_the_document(self, api_base, narrow_document):
        resp = requests.get(
            f"{api_base}{PROPOSAL_FAMILY_URL}/{narrow_document['family_key']}",
            timeout=15,
        )
        assert resp.status_code == 200
        assert resp.json()["members"] == narrow_document["members"]

    def test_get_unknown_key_is_404(self, api_base):
        resp = requests.get(f"{api_base}{PROPOSAL_FAMILY_URL}/sha256:nope", timeout=15)
        assert resp.status_code == 404
        assert resp.json()["error"] == "not_found"


class TestMemberViews:
    def test_views_for_the_presented_member_equal_calc(
        self, api_base, narrow_document, scenarios
    ):
        presented = narrow_document["presented"]
        resp = requests.get(
            f"{api_base}{member_views_url(narrow_document['family_key'], presented['scenario_variant_id'], presented['composition_id'])}",
            timeout=120,
        )
        assert resp.status_code == 200, resp.text[:300]
        body = resp.json()
        assert set(body) == {"views"}
        calc = compute(
            api_base,
            STOPS_BERLIN_WIEN,
            presented["composition_id"],
            scenario_id=scenarios["base"]["scenario_id"],
            auto_stop_addition="off",
        )
        assert body["views"] == calc["evaluation"]["views"]

    def test_views_for_an_unknown_member_are_404(self, api_base, narrow_document):
        resp = requests.get(
            f"{api_base}{member_views_url(narrow_document['family_key'], 999999, DEFAULT_COMPOSITION)}",
            timeout=30,
        )
        assert resp.status_code == 404
        resp = requests.get(
            f"{api_base}{member_views_url(narrow_document['family_key'], narrow_document['presented']['scenario_variant_id'], 'NOT-A-TRAIN')}",
            timeout=30,
        )
        assert resp.status_code == 404

    def test_views_on_an_unknown_key_are_404(self, api_base):
        resp = requests.get(
            f"{api_base}{member_views_url('sha256:nope', 1, DEFAULT_COMPOSITION)}",
            timeout=30,
        )
        assert resp.status_code == 404
