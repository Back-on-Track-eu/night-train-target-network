"""
test_35_proposal_calc_api.py
=============================
Contract tests for POST /api/proposal/calc — the merged compute endpoint
(PROPOSALS_DESIGN.md §2.1, WP2). Response-structure and
request-validation coverage for the single merged response shape;
content-logic coverage lives in test_20_route_content.py (route side) and
test_30_evaluation_content.py (evaluation side). Deeper content-parity
cases (every timetable/routing mode combination, full breakdown-field
completeness per view) can still be ported over incrementally.

Response shape (§2.1):
  route_builder_version, calc_version, request (resolved), summary,
  suggested_stops (only if auto_stop_addition="suggest"),
  route.{...}  (route_to_dict() shape, neutral ids — no P{id}_V{n}_ prefix),
  evaluation.{models, input.{parameters.{...}} (no "route" key — see below),
              views.{route|per_trip_pair|per_trip_pair_per_country|
                     per_trip_pair_per_od|per_trip_pair_per_section|
                     per_trip_per_stop}}

proposal/calc never persists — no proposal_id/proposal_version anywhere in
request or response, and no Authorization header has any effect (unlike
build_route()/evaluate()).
"""

import re

import pytest
import requests

from tests.conftest import STOPS_BERLIN_DRESDEN_WIEN, STOPS_BERLIN_WIEN
from tests.helpers import PROPOSAL_CALC_URL, compute

BASE_REQUEST = {
    "stops": STOPS_BERLIN_DRESDEN_WIEN,
    "composition_id": "NEW-BAL-7",
    # Pinned off for deterministic structural assertions — see
    # test_20_route_content.py's module docstring for why CZ_BRNO_HLN
    # would otherwise get auto-added on this corridor.
    "auto_stop_addition": "off",
}


@pytest.fixture(scope="module")
def calc_response(api_base):
    """One full merged response for the standard 3-stop request — shared
    read-only across this module's structural tests."""
    return compute(api_base, **BASE_REQUEST)


# =============================================================================
# Response structure
# =============================================================================


class TestResponseStructure:
    def test_top_level_keys(self, calc_response):
        assert set(calc_response) >= {
            "route_builder_version",
            "calc_version",
            "route_fingerprint",
            "cache_hit",
            "request",
            "summary",
            "route",
            "evaluation",
        }

    def test_route_fingerprint_is_well_formed(self, calc_response):
        """§3.1 — deeper fingerprint coverage (determinism, prefix
        independence, reconstruction equality) lives in
        test_37_proposal_projection.py and
        test_36_proposal_gtfs_roundtrip.py; this is just the contract
        shape check alongside the rest of this file's structural tests."""
        fp = calc_response["route_fingerprint"]
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", fp)

    def test_cache_hit_is_bool(self, calc_response):
        """Shape only — either value is legitimate here, since conftest's
        session route fixtures may already have warmed the §2.3 cache
        with this exact request. Hit/miss SEMANTICS live in
        test_39_compute_cache.py, behind its own cache flush."""
        assert isinstance(calc_response["cache_hit"], bool)

    def test_calc_version_is_semver(self, calc_response):
        assert re.fullmatch(r"\d+\.\d+\.\d+", calc_response["calc_version"])

    def test_route_builder_version_is_semver(self, calc_response):
        assert re.fullmatch(r"\d+\.\d+\.\d+", calc_response["route_builder_version"])

    def test_no_suggested_stops_when_off(self, calc_response):
        """auto_stop_addition='off' (BASE_REQUEST) omits suggested_stops
        entirely — only 'suggest' includes it, per §2.1."""
        assert "suggested_stops" not in calc_response

    def test_evaluation_has_models_input_views(self, calc_response):
        assert set(calc_response["evaluation"]) == {"models", "input", "views"}

    def test_models_has_emissions_factors(self, calc_response):
        """WP10 step 5 (decision 24) — the per-mode reference values the
        frontend renders next to a proposal's co2_g_per_pax_km."""
        emissions = calc_response["evaluation"]["models"]["emissions"]
        assert set(emissions) == {"version", "description", "factors"}
        assert set(emissions["factors"]) == {"night_train", "air", "car"}
        for factor in emissions["factors"].values():
            assert factor["g_per_pax_km"] > 0
            assert factor["source"]

    def test_summary_carries_gallery_kpis_without_geometry(self, calc_response):
        """WP10 step 5 — the §5.4 gallery KPI row, minus geom_simplified
        (the response already carries full per-segment geometry). Value
        equality with build_summary_row() is asserted in test_37."""
        summary = calc_response["summary"]
        assert "geom_simplified" not in summary
        assert summary["total_distance_km"] > 0
        assert summary["demand_kpis_placeholder"] is True
        night_train = calc_response["evaluation"]["models"]["emissions"]["factors"][
            "night_train"
        ]
        assert summary["co2_g_per_pax_km"] == night_train["g_per_pax_km"]

    def test_views_has_all_six(self, calc_response):
        assert set(calc_response["evaluation"]["views"]) == {
            "route",
            "per_trip_pair",
            "per_trip_pair_per_country",
            "per_trip_pair_per_od",
            "per_trip_pair_per_section",
            "per_trip_per_stop",
        }

    def test_input_has_no_route_copy(self, calc_response):
        """§2.1: 'no route copy under evaluation.input anywhere' — the
        route appears exactly once, as a sibling of 'evaluation'."""
        assert "route" not in calc_response["evaluation"]["input"]
        assert set(calc_response["evaluation"]["input"]) == {"parameters"}

    def test_input_parameters_present(self, calc_response):
        assert set(calc_response["evaluation"]["input"]["parameters"]) == {
            "track_infrastructures",
            "stop_infrastructures",
            "compositions",
        }


# =============================================================================
# Resolved request echo
# =============================================================================


class TestResolvedRequest:
    def test_request_has_no_proposal_identity(self, calc_response):
        """proposal_id/proposal_version are publish concerns (§2.2) — the
        compute request never carries them."""
        assert "proposal_id" not in calc_response["request"]
        assert "proposal_version" not in calc_response["request"]

    def test_request_echoes_composition_and_stops(self, calc_response):
        assert calc_response["request"]["stops"] == STOPS_BERLIN_DRESDEN_WIEN
        assert calc_response["request"]["composition_id"] == "NEW-BAL-7"

    def test_request_scenario_id_is_concrete(self, calc_response):
        """scenario_id is resolved to a concrete int even when omitted
        from the posted request (None = 'use current base')."""
        assert isinstance(calc_response["request"]["scenario_id"], int)

    def test_omitted_defaults_resolved_explicitly(self, api_base):
        """An omitted field and an explicitly-posted default must echo
        identically (§2.1's 'resolved request' contract)."""
        implicit = compute(
            api_base, stops=STOPS_BERLIN_WIEN, composition_id="NEW-BAL-7"
        )
        explicit = compute(
            api_base,
            stops=STOPS_BERLIN_WIEN,
            composition_id="NEW-BAL-7",
            timetable_mode="simpleAutomatic",
            schedule_mode="alwaysDaily",
            routing_mode="fullRouting",
            auto_stop_addition="add",
        )
        assert implicit["request"] == explicit["request"]


# =============================================================================
# Neutral structural IDs
# =============================================================================


class TestNeutralIds:
    def test_route_id_has_no_proposal_prefix(self, calc_response):
        """§2.1: compute responses carry neutral structural IDs — no
        P{id}_V{n}_ prefix (that only exists on published proposals)."""
        assert not calc_response["route"]["route_id"].startswith("P")
        assert calc_response["route"]["route_id"] == "R1"

    def test_trip_ids_have_no_proposal_prefix(self, calc_response):
        for pair in calc_response["route"]["trip_pairs"]:
            for trip in (pair["outbound"], pair["return_trip"]):
                assert not trip["trip_id"].startswith("P")
                assert trip["trip_id"].startswith("R1_")

    def test_per_trip_pair_view_keys_are_neutral(self, calc_response):
        """rewrite_id_prefix() strips the prefix from dict KEYS too (views
        keyed by trip_id, e.g. per_trip_pair) — not just string values."""
        per_pair_data = calc_response["evaluation"]["views"]["per_trip_pair"]["data"]
        for key in per_pair_data:
            if key == "all":
                continue
            assert not key.startswith("P")


# =============================================================================
# Request validation
# =============================================================================


class TestValidation:
    def test_missing_stops(self, api_base):
        resp = requests.post(
            f"{api_base}{PROPOSAL_CALC_URL}",
            json={"composition_id": "NEW-BAL-7"},
            timeout=30,
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "validation_error"

    def test_too_few_stops(self, api_base):
        resp = requests.post(
            f"{api_base}{PROPOSAL_CALC_URL}",
            json={"stops": ["DE_BERLIN_HBF"], "composition_id": "NEW-BAL-7"},
            timeout=30,
        )
        assert resp.status_code == 400

    def test_missing_composition_id(self, api_base):
        resp = requests.post(
            f"{api_base}{PROPOSAL_CALC_URL}",
            json={"stops": STOPS_BERLIN_WIEN},
            timeout=30,
        )
        assert resp.status_code == 400

    def test_invalid_timetable_mode(self, api_base):
        resp = requests.post(
            f"{api_base}{PROPOSAL_CALC_URL}",
            json={
                "stops": STOPS_BERLIN_WIEN,
                "composition_id": "NEW-BAL-7",
                "timetable_mode": "bogus",
            },
            timeout=30,
        )
        assert resp.status_code == 400

    def test_boolean_auto_stop_addition_rejected(self, api_base):
        """auto_stop_addition is a string enum since route builder 0.9.5 —
        booleans are rejected."""
        resp = requests.post(
            f"{api_base}{PROPOSAL_CALC_URL}",
            json={
                "stops": STOPS_BERLIN_WIEN,
                "composition_id": "NEW-BAL-7",
                "auto_stop_addition": True,
            },
            timeout=30,
        )
        assert resp.status_code == 400

    def test_scenario_id_must_be_int(self, api_base):
        resp = requests.post(
            f"{api_base}{PROPOSAL_CALC_URL}",
            json={
                "stops": STOPS_BERLIN_WIEN,
                "composition_id": "NEW-BAL-7",
                "scenario_id": "not-an-int",
            },
            timeout=30,
        )
        assert resp.status_code == 400

    def test_not_json_body(self, api_base):
        resp = requests.post(f"{api_base}{PROPOSAL_CALC_URL}", timeout=30)
        assert resp.status_code == 400


# =============================================================================
# auto_stop_addition="suggest"
# =============================================================================


class TestSuggestMode:
    def test_suggest_returns_suggested_stops_key(self, api_base):
        result = compute(
            api_base,
            stops=STOPS_BERLIN_DRESDEN_WIEN,
            composition_id="NEW-BAL-7",
            auto_stop_addition="suggest",
        )
        assert "suggested_stops" in result
        assert isinstance(result["suggested_stops"], list)

    def test_suggest_does_not_modify_stops(self, api_base):
        """'suggest' routes exactly like 'off' — candidates are reported,
        not inserted."""
        result = compute(
            api_base,
            stops=STOPS_BERLIN_DRESDEN_WIEN,
            composition_id="NEW-BAL-7",
            auto_stop_addition="suggest",
        )
        assert result["request"]["stops"] == STOPS_BERLIN_DRESDEN_WIEN


# =============================================================================
# Statelessness
# =============================================================================


class TestStatelessness:
    def test_no_persistence_metadata_in_response(self, calc_response):
        """Unlike /api/route/plan and /api/evaluation/calc, proposal/calc
        never persists — no 'proposal' block in the response."""
        assert "proposal" not in calc_response

    def test_repeated_identical_requests_are_independent(self, api_base):
        """No shared/mutated state between calls — same request twice
        yields the same resolved request and route shape (route_fingerprint
        equality itself is WP4's concern, not asserted here)."""
        first = compute(api_base, **BASE_REQUEST)
        second = compute(api_base, **BASE_REQUEST)
        assert first["request"] == second["request"]
        assert first["route"]["route_id"] == second["route"]["route_id"] == "R1"
