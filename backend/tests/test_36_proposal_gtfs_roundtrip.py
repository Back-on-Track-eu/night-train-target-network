"""
test_36_proposal_gtfs_roundtrip.py
====================================
Round-trip tests for WP3 (docs/PROPOSALS_DESIGN.md §5.1/§5.2):
api/helpers/route_gtfs_serialize.py's insert_route_gtfs() +
route_dict_from_gtfs() must deep-equal the original POST /api/proposal/calc
(WP2) route it was given, and input_parameters_from_scenario() must
deep-equal the original evaluation.input.parameters.

No publish endpoint exists yet (WP5) — this file calls the write/read
functions directly against the DB, exactly as the design doc's WP3
"testable by" note specifies. proposal_id is allocated from the real
proposals.proposals SERIAL sequence via
ProposalRepository._next_proposal_id() — the same counter the old
persist-on-calc write path uses, so there's no separate "test range" to
maintain; the sequence itself guarantees no collision with any other row,
past or future. No commit happens anywhere in this file — the session-
scoped autouse rollback_after_test fixture (conftest.py) cleans up
after every test, so there is nothing to purge and nothing survives a
crash mid-test either.

Writes go through db_cur (conftest.py) — a plain DB cursor, deliberately
NOT ProposalRepository — insert_route_gtfs()/route_dict_from_gtfs() are
standalone functions that take a cursor, independent of that class (see
route_gtfs_serialize.py's module docstring for why).
"""

import json

import pytest

from adapters.proposal_repository import ProposalRepository, rewrite_id_prefix
from api.helpers.route_gtfs_serialize import (
    insert_route_gtfs,
    route_dict_from_gtfs,
    input_parameters_from_scenario,
)
from tests.conftest import STOPS_BERLIN_DRESDEN_WIEN, STOPS_BERLIN_WIEN
from tests.helpers import compute


def _json_normalize(obj):
    """route_dict_from_gtfs()/input_parameters_from_scenario() return
    native Python objects straight out of the DB/domain layer; the
    "original" side of every comparison in this file came back through
    an actual HTTP response, i.e. already round-tripped through JSON
    (dict keys forced to strings, Decimal collapsed to float, etc.).
    Normalizing the reconstructed side through the same round-trip before
    comparing is the fair comparison — it's what a real caller (e.g.
    WP5's eventual load endpoint) would also do before either value
    reaches a client — not a workaround for a real discrepancy."""
    return json.loads(json.dumps(obj))


def _round_avg_price(obj):
    """avg_price is stored as NUMERIC(10,2) in proposals.od_pairs (WP1's
    schema) — correct precision for a EUR-denominated field. The stopgap
    demand model's raw output (distribute_demand(): a flat per-km fare
    times distance) isn't itself rounded, so the *published* (pre-storage)
    value can carry more decimals than the DB will ever keep — e.g.
    77.38690000000001. Once a route is actually published, avg_price is
    genuinely a 2-decimal value; rounding the expected side here models
    that correctly rather than loosening the round-trip guarantee to
    paper over it."""
    if isinstance(obj, dict):
        return {
            k: (round(v, 2) if k == "avg_price" else _round_avg_price(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_round_avg_price(v) for v in obj]
    return obj


def _publish_fixture(db_cur, response: dict) -> tuple[int, int, dict]:
    """Turn a WP2 compute() response into a "published" route dict — real
    P{proposal_id}_V{version}_ IDs instead of WP2's neutral R1/... ones —
    the same rewrite_id_prefix() mechanism the old save() path already
    uses to assign real prefixes, just starting from an empty (already-
    stripped) prefix instead of another draft one. old_prefix="R1" is
    precise here, not a loose heuristic: WP2 always emits exactly one
    route named "R1" (single-route proposals only, today), and every
    trip_id/geometry_id in its route dict is constructed by
    route_factory.py as "R1_..." — nothing else in the payload starts
    with those two characters.

    Returns (proposal_id, proposal_version, published_route_dict).
    """
    pid = ProposalRepository._next_proposal_id(db_cur)
    version = 1
    published_route = rewrite_id_prefix(
        response["route"], "R1", f"P{pid}_V{version}_R1"
    )
    return pid, version, published_route


class TestRouteRoundtrip:
    def test_two_stop_route_deep_equals_after_roundtrip(self, db_cur, loader, api_base):
        response = compute(
            api_base,
            stops=STOPS_BERLIN_WIEN,
            composition_id="NEW-BAL-7",
            auto_stop_addition="off",
        )
        scenario_id = response["request"]["scenario_id"]
        pid, version, published_route = _publish_fixture(db_cur, response)

        insert_route_gtfs(db_cur, published_route)
        reconstructed = route_dict_from_gtfs(pid, version, loader, scenario_id, db_cur)

        assert _json_normalize(reconstructed) == _round_avg_price(published_route)

    def test_three_stop_route_with_intermediate_stop_deep_equals(self, db_cur, loader, api_base):
        """Covers a night-classified intermediate stop and a longer
        segment chain — not just the 2-stop terminal-only case above."""
        response = compute(
            api_base,
            stops=STOPS_BERLIN_DRESDEN_WIEN,
            composition_id="NEW-BAL-7",
            auto_stop_addition="off",
        )
        scenario_id = response["request"]["scenario_id"]
        pid, version, published_route = _publish_fixture(db_cur, response)

        insert_route_gtfs(db_cur, published_route)
        reconstructed = route_dict_from_gtfs(pid, version, loader, scenario_id, db_cur)

        assert _json_normalize(reconstructed) == _round_avg_price(published_route)

    def test_auto_added_stop_survives_roundtrip(self, db_cur, loader, api_base):
        """The gap this file's migration (phase1b) closed — a stop
        auto_stop_addition inserted must come back with auto_added=true,
        not silently downgraded to false."""
        response = compute(
            api_base,
            stops=STOPS_BERLIN_DRESDEN_WIEN,
            composition_id="NEW-BAL-7",
            auto_stop_addition="add",
        )
        stops_in_route = [
            s
            for pair in response["route"]["trip_pairs"]
            for s in (
                [seg["from_stop"] for seg in pair["outbound"]["segments"]]
                + [pair["outbound"]["segments"][-1]["to_stop"]]
            )
        ]
        assert any(s["auto_added"] for s in stops_in_route), (
            "fixture assumption: CZ_BRNO_HLN should auto-add on this "
            "corridor — see test_20_route_plan_api.py's module docstring"
        )

        scenario_id = response["request"]["scenario_id"]
        pid, version, published_route = _publish_fixture(db_cur, response)
        insert_route_gtfs(db_cur, published_route)
        reconstructed = route_dict_from_gtfs(pid, version, loader, scenario_id, db_cur)
        reconstructed_normalized = _json_normalize(reconstructed)

        assert reconstructed_normalized == _round_avg_price(published_route)
        reconstructed_stops = [
            s
            for pair in reconstructed_normalized["trip_pairs"]
            for s in (
                [seg["from_stop"] for seg in pair["outbound"]["segments"]]
                + [pair["outbound"]["segments"][-1]["to_stop"]]
            )
        ]
        assert any(s["auto_added"] for s in reconstructed_stops)

    def test_od_pairs_survive_roundtrip(self, db_cur, loader, api_base):
        """Stopgap demand (distribute_demand(), always run by
        POST /api/proposal/calc) populates od_pairs — confirms the
        proposals.od_pairs sidecar table round-trips real content, not
        just an empty list."""
        response = compute(
            api_base,
            stops=STOPS_BERLIN_WIEN,
            composition_id="NEW-BAL-7",
            auto_stop_addition="off",
        )
        assert len(response["route"]["trip_pairs"][0]["od_pairs"]) > 0, (
            "fixture assumption: stopgap demand always populates od_pairs"
        )

        scenario_id = response["request"]["scenario_id"]
        pid, version, published_route = _publish_fixture(db_cur, response)
        insert_route_gtfs(db_cur, published_route)
        reconstructed = route_dict_from_gtfs(pid, version, loader, scenario_id, db_cur)

        # od_pairs carries trip_id references, which only get their real
        # P{pid}_V{version}_ prefix from _publish_fixture()'s rewrite —
        # compare against published_route's copy, not response["route"]'s
        # pre-rewrite (neutral-ID) one.
        published_od_pairs = published_route["trip_pairs"][0]["od_pairs"]
        assert _json_normalize(reconstructed)["trip_pairs"][0]["od_pairs"] == _round_avg_price(
            published_od_pairs
        )


    def test_unknown_proposal_raises(self, db_cur, loader):
        with pytest.raises(ValueError, match="no trips found"):
            route_dict_from_gtfs(987654321, 1, loader, 1, db_cur)


class TestInputParametersRoundtrip:
    def test_input_parameters_deep_equal_original(self, db_cur, loader, api_base):
        """input_parameters_from_scenario() doesn't touch the GTFS tables
        at all (§5.1: parameters are rebuilt from the scenario pin alone)
        — no insert needed, just compare against the original compute
        response's own evaluation.input.parameters."""
        response = compute(
            api_base,
            stops=STOPS_BERLIN_WIEN,
            composition_id="NEW-BAL-7",
            auto_stop_addition="off",
        )
        scenario_id = response["request"]["scenario_id"]
        original_parameters = response["evaluation"]["input"]["parameters"]

        rebuilt = input_parameters_from_scenario(scenario_id, loader)

        # See _json_normalize()'s docstring — same reasoning applies here.
        rebuilt_normalized = _json_normalize(rebuilt)

        assert rebuilt_normalized["parameters"] == original_parameters
