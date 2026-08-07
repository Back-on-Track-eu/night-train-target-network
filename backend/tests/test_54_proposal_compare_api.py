"""
test_54_proposal_compare_api.py
================================
POST /api/proposals/compare (adapters/proposal/README.md §7.3).

Covers:
  - request validation (400): side count, unknown keys, wrong types
  - unknown anchor (404, side index named)
  - stored vs stored (cross-proposal): published flags, full §2.1 side
    shape + summary blocks, diff correctness against the sides' own
    values, route context (composition differs, routes agree/disagree as
    the data dictates)
  - override sides: published: false, overrides echoed, on-the-fly
    summary, ephemerality (nothing persisted), domain error -> 422
  - the "any override present -> computed side" rule via an override
    equal to the stored value (identical result, route_identical, all
    deltas zero)
  - a genuinely different scenario override (historical snapshot):
    non-zero cost deltas, scenario_id in differing_request_fields
  - on-load refresh of a stale anchor inside compare (WP8 reuse)
  - pure diff semantics on synthetic sides: rel on zero base,
    non-numeric skipping, unmatched-path collection, and the
    published-prefix neutralisation that lets trip-keyed views match
    across two proposals

Isolation: same discipline as test_50/test_53 — publishing commits
outside the suite's per-test rollback, so this module purges published
proposals before and after itself.
"""

import re

import pytest
import requests

from models.route.version import ROUTE_BUILDER_VERSION
from api.helpers.proposal_compare import build_diff, build_route_context
from tests.helpers import (
    PROPOSALS_COMPARE_URL,
    compare_sides,
    compute,
    publish,
    purge_saved_proposals,
)

_STOPS = ["DE_BERLIN_HBF", "AT_WIEN_HBF"]
_COMPOSITION = "NEW-BAL-7"
_OTHER_COMPOSITION = "REF-BAL-9"

# Same convention as test_53: guaranteed != any real version, so
# outdated_trigger() fires on a row mutated to it.
_STALE_ROUTE_BUILDER_VERSION = "0.0.1"

# Every §2.1 compute-response key a compare side must carry on top of its
# compare-specific ones (published, summary; overrides/proposal metadata
# differ per side kind and are asserted separately).
_COMPUTE_SHAPE_KEYS = {
    "route_builder_version",
    "calc_version",
    "route_fingerprint",
    "request",
    "route",
    "evaluation",
}


@pytest.fixture(scope="module", autouse=True)
def clean_proposals(db_conn, script_headers):
    """Purge published proposals before and after this module — same
    convention as test_50/test_53 (the permanent seed proposal is
    preserved by purge_saved_proposals)."""
    purge_saved_proposals(db_conn)
    yield
    purge_saved_proposals(db_conn)


@pytest.fixture(scope="module")
def proposal_a(api_base, script_headers):
    """Published fixture A: the standard corridor/composition."""
    request = compute(api_base, _STOPS, _COMPOSITION)["request"]
    return publish(
        api_base, request, name="Compare A (WP9 test)", headers=script_headers
    )


@pytest.fixture(scope="module")
def proposal_b(api_base, script_headers):
    """Published fixture B: same corridor, different composition — the
    cross-proposal compare partner."""
    request = compute(api_base, _STOPS, _OTHER_COMPOSITION)["request"]
    return publish(
        api_base, request, name="Compare B (WP9 test)", headers=script_headers
    )


def _post_compare(api_base, body, timeout=120):
    return requests.post(
        f"{api_base}{PROPOSALS_COMPARE_URL}", json=body, timeout=timeout
    )


# =============================================================================
# Validation + not-found
# =============================================================================


class TestValidation:
    def test_empty_body_is_rejected(self, api_base):
        resp = _post_compare(api_base, None, timeout=15)
        assert resp.status_code == 400
        assert resp.json()["error"] == "bad_request"

    @pytest.mark.parametrize("n_sides", [0, 1, 3])
    def test_side_count_must_be_two(self, api_base, n_sides):
        sides = [{"proposal_id": 1}] * n_sides
        resp = _post_compare(api_base, {"sides": sides}, timeout=15)
        assert resp.status_code == 400
        assert "exactly 2" in resp.json()["details"][0]

    def test_unknown_side_keys_are_rejected(self, api_base):
        resp = _post_compare(
            api_base,
            {
                "sides": [
                    {"proposal_id": 1, "routing_mode": "fullRouting"},
                    {"proposal_id": 1},
                ]
            },
            timeout=15,
        )
        assert resp.status_code == 400
        assert any("unknown keys" in d for d in resp.json()["details"])

    def test_wrong_types_are_rejected(self, api_base):
        resp = _post_compare(
            api_base,
            {
                "sides": [
                    {"proposal_id": "1"},
                    {"proposal_id": 1, "scenario_id": "base", "composition_id": 7},
                ]
            },
            timeout=15,
        )
        assert resp.status_code == 400
        details = " ".join(resp.json()["details"])
        assert "sides[0].proposal_id" in details
        assert "sides[1].scenario_id" in details
        assert "sides[1].composition_id" in details

    def test_unknown_anchor_is_404_with_side_index(self, api_base, proposal_a):
        resp = _post_compare(
            api_base,
            {
                "sides": [
                    {"proposal_id": proposal_a["proposal_id"]},
                    {"proposal_id": 999999},
                ]
            },
            timeout=60,
        )
        assert resp.status_code == 404
        assert "sides[1]" in resp.json()["message"]
        assert "999999" in resp.json()["message"]


# =============================================================================
# Stored vs stored — cross-proposal compare
# =============================================================================


class TestStoredVsStored:
    @pytest.fixture(scope="class")
    def result(self, api_base, proposal_a, proposal_b):
        return compare_sides(
            api_base,
            [
                {"proposal_id": proposal_a["proposal_id"]},
                {"proposal_id": proposal_b["proposal_id"]},
            ],
        )

    def test_top_level_shape(self, result):
        assert set(result) == {"sides", "diff", "route_context"}
        assert set(result["diff"]) == {"summary", "views", "views_unmatched"}

    def test_sides_are_published_full_shape(self, result, proposal_a, proposal_b):
        for side, published in zip(result["sides"], (proposal_a, proposal_b)):
            assert side["published"] is True
            assert side["proposal_id"] == published["proposal_id"]
            assert _COMPUTE_SHAPE_KEYS <= set(side)
            # Stored sides carry the full gallery summary row, engagement
            # count included.
            assert side["summary"]["proposal_id"] == published["proposal_id"]
            assert "likes_count" in side["summary"]

    def test_summary_diff_matches_side_values(self, result):
        diff = result["diff"]["summary"]["cost_eur_per_train_km"]
        a = result["sides"][0]["summary"]["cost_eur_per_train_km"]
        b = result["sides"][1]["summary"]["cost_eur_per_train_km"]
        assert diff["a"] == a
        assert diff["b"] == b
        assert diff["abs"] == pytest.approx(b - a, abs=1e-6)
        # Two different compositions must not cost the same per train-km.
        assert diff["abs"] != 0

    def test_views_diff_reaches_cost_leaves(self, result):
        # One representative leaf: annual total cost in the route view —
        # a - b sanity plus the leaf shape contract.
        leaf = result["diff"]["views"]["route"]["data"]["per_year"]["all"][
            "total_cost_eur"
        ]
        assert set(leaf) == {"a", "b", "abs", "rel"}
        assert leaf["abs"] == pytest.approx(leaf["b"] - leaf["a"], abs=1e-6)

    def test_pair_keyed_views_diff_across_two_proposals(self, result):
        """The regression this pairs with: both sides are published, so
        their per-trip views are keyed by different P{id}_V{n}_ prefixes.
        Before neutralisation every pair-keyed view fell wholesale into
        views_unmatched — the diff silently covered only the route view.
        A and B share stops and schedule mode, so every trip key must now
        match."""
        for view in (
            "per_trip_pair",
            "per_trip_pair_per_country",
            "per_trip_pair_per_od",
            "per_trip_pair_per_section",
            "per_trip_per_stop",
        ):
            data = result["diff"]["views"].get(view, {}).get("data", {})
            # Not just "the view diffed at all": under the old bug the
            # "all" aggregate still matched, so a truthy view proved
            # nothing. At least one REAL per-trip cell must be present.
            assert [key for key in data if key != "all"], (
                f"{view} diffed only its 'all' aggregate — per-trip cells unmatched"
            )

        # NOT "views_unmatched is empty": A and B run different
        # compositions, so their coach-class keys legitimately differ and
        # land here (e.g. "route.data.per_year.Capsule") — that's the
        # generic diff working as designed. What must never appear again
        # is an unmatched path caused by a PROPOSAL PREFIX, which is
        # exactly what this fix removed.
        unmatched = result["diff"]["views_unmatched"]
        prefixed = [
            path
            for path in unmatched["a_only"] + unmatched["b_only"]
            if re.search(r"P\d+_V\d+_", path)
        ]
        assert prefixed == [], f"prefix leaked into unmatched paths: {prefixed[:5]}"

        # Diff keys are structural — neither proposal's prefix leaks into
        # the diff tree, though the sides themselves still carry theirs.
        # Every trip-keyed view also carries an "all" aggregate key
        # alongside its per-pair keys; that one is prefix-free on both
        # sides by construction, and it is precisely why the old bug was
        # invisible on a single-pair route — "all" matched, so the diff
        # looked populated while every real pair cell was unmatched.
        pair_keys = list(result["diff"]["views"]["per_trip_pair"]["data"])
        assert pair_keys and not any(re.match(r"P\d+_V\d+_", key) for key in pair_keys)
        for side in result["sides"]:
            prefix = f"P{side['proposal_id']}_V{side['proposal_version']}_"
            trip_keys = [
                key
                for key in side["evaluation"]["views"]["per_trip_pair"]["data"]
                if key != "all"
            ]
            assert trip_keys, "side has no per-pair keys to check"
            assert all(key.startswith(prefix) for key in trip_keys), (
                f"side {side['proposal_id']} keys not all prefixed: {trip_keys}"
            )

    def test_route_context_names_the_composition(self, result):
        context = result["route_context"]
        assert "composition_id" in context["differing_request_fields"]
        assert context["route_identical"] == (
            context["fingerprints"][0] == context["fingerprints"][1]
        )


# =============================================================================
# Override sides — ephemeral compute
# =============================================================================


class TestOverrides:
    def test_override_equal_to_stored_is_computed_but_identical(
        self, api_base, proposal_a
    ):
        # The "any override present -> computed side" rule: overriding
        # scenario_id with the STORED value must route through the
        # compute path (published: false) yet produce the identical
        # result — same fingerprint, every delta zero.
        stored_scenario_id = proposal_a["request"]["scenario_id"]
        result = compare_sides(
            api_base,
            [
                {"proposal_id": proposal_a["proposal_id"]},
                {
                    "proposal_id": proposal_a["proposal_id"],
                    "scenario_id": stored_scenario_id,
                },
            ],
        )
        side_b = result["sides"][1]
        assert side_b["published"] is False
        assert side_b["overrides"] == {"scenario_id": stored_scenario_id}
        # A bool either way: this side replays the anchor's own stored
        # compute_request, which publish itself just computed — so within
        # the cache TTL this is typically a HIT ("comparing warms the
        # editor and vice versa", §2.3). Semantics in test_39.
        assert isinstance(side_b["cache_hit"], bool)
        # Computed summaries are projection-built, not DB rows — no
        # engagement fields, no geometry.
        assert "likes_count" not in side_b["summary"]
        assert "geom_simplified" not in side_b["summary"]

        assert result["route_context"]["route_identical"] is True
        assert result["route_context"]["differing_request_fields"] == []
        assert all(leaf["abs"] == 0 for leaf in result["diff"]["summary"].values())

    def test_scenario_override_changes_costs(
        self, api_base, proposal_a, historical_scenario, db_cur, db_conn
    ):
        result = compare_sides(
            api_base,
            [
                {"proposal_id": proposal_a["proposal_id"]},
                {
                    "proposal_id": proposal_a["proposal_id"],
                    "scenario_id": historical_scenario["scenario_id"],
                },
            ],
        )
        side_b = result["sides"][1]
        assert side_b["published"] is False
        assert side_b["request"]["scenario_id"] == historical_scenario["scenario_id"]
        assert side_b["summary"]["scenario_id"] == historical_scenario["scenario_id"]
        assert result["route_context"]["differing_request_fields"] == ["scenario_id"]
        # The historical snapshot pins different infrastructure tariffs
        # (e.g. DE tac 3.10 vs 5.40) — the cost KPI must move.
        assert result["diff"]["summary"]["cost_eur_per_train_km"]["abs"] != 0

        # Ephemerality: the what-if compute left no trace — the anchor's
        # stored state is untouched.
        db_cur.execute(
            "SELECT proposal_version, scenario_id FROM proposals.proposals "
            "WHERE proposal_id = %s",
            (proposal_a["proposal_id"],),
        )
        row = db_cur.fetchone()
        db_conn.commit()
        assert row["proposal_version"] == proposal_a["proposal_version"]
        assert row["scenario_id"] == proposal_a["request"]["scenario_id"]

    def test_composition_override(self, api_base, proposal_a):
        result = compare_sides(
            api_base,
            [
                {"proposal_id": proposal_a["proposal_id"]},
                {
                    "proposal_id": proposal_a["proposal_id"],
                    "composition_id": _OTHER_COMPOSITION,
                },
            ],
        )
        side_b = result["sides"][1]
        assert side_b["published"] is False
        assert side_b["summary"]["composition_id"] == _OTHER_COMPOSITION
        assert "composition_id" in result["route_context"]["differing_request_fields"]
        assert result["diff"]["summary"]["cost_eur_per_train_km"]["abs"] != 0

    def test_unknown_composition_override_is_422_with_side_index(
        self, api_base, proposal_a
    ):
        resp = _post_compare(
            api_base,
            {
                "sides": [
                    {"proposal_id": proposal_a["proposal_id"]},
                    {
                        "proposal_id": proposal_a["proposal_id"],
                        "composition_id": "NO-SUCH-COMPOSITION",
                    },
                ]
            },
        )
        assert resp.status_code == 422
        assert resp.json()["error"] == "domain_error"
        assert "sides[1]" in resp.json()["message"]


# =============================================================================
# On-load refresh inside compare (WP8 reuse)
# =============================================================================


class TestOnLoadRefreshInCompare:
    def test_stale_anchor_is_refreshed(self, api_base, script_headers, db_conn, db_cur):
        request = compute(api_base, _STOPS, _COMPOSITION)["request"]
        published = publish(
            api_base, request, name="Compare stale (WP9 test)", headers=script_headers
        )
        cur = db_conn.cursor()
        cur.execute(
            "UPDATE proposals.proposals SET route_builder_version = %s "
            "WHERE proposal_id = %s",
            (_STALE_ROUTE_BUILDER_VERSION, published["proposal_id"]),
        )
        db_conn.commit()

        result = compare_sides(
            api_base,
            [
                {"proposal_id": published["proposal_id"]},
                {"proposal_id": published["proposal_id"]},
            ],
        )
        # Both sides see the refreshed state (version corrected, state
        # counter bumped) — the first side's load triggered the refresh,
        # the second found the proposal already current.
        for side in result["sides"]:
            assert side["route_builder_version"] == ROUTE_BUILDER_VERSION
            assert side["proposal_version"] == 2

        db_cur.execute(
            "SELECT event, detail FROM proposals.update_log "
            "WHERE proposal_id = %s AND proposal_version = 2",
            (published["proposal_id"],),
        )
        row = db_cur.fetchone()
        db_conn.commit()
        assert row is not None
        assert row["event"] == "recalculated"
        assert row["detail"]["trigger"] == "route_builder_version"


# =============================================================================
# Diff semantics — pure, on synthetic sides
# =============================================================================


def _synthetic_side(
    views: dict,
    summary: dict,
    fingerprint: str,
    request: dict,
    published: bool = False,
    proposal_id: int = 0,
    proposal_version: int = 0,
) -> dict:
    """published defaults to False — an unpublished side's views are
    already structural, so most cases here can state their trip keys as
    plain T1/T3. The published variant (with proposal_id/version) exists
    for the prefix-neutralisation case, where the whole point is that
    the two sides carry DIFFERENT prefixes."""
    return {
        "published": published,
        "proposal_id": proposal_id,
        "proposal_version": proposal_version,
        "evaluation": {"views": views},
        "summary": summary,
        "route_fingerprint": fingerprint,
        "request": request,
    }


class TestDiffSemantics:
    def test_leaf_shape_zero_base_and_skipping(self):
        side_a = _synthetic_side(
            views={
                "route": {
                    "description": "text is skipped",
                    "data": {"net_eur": 0.0, "total_cost_eur": 100.0, "label": "x"},
                }
            },
            summary={"total_distance_km": 800.0, "subsidy_eur_per_t_co2": None},
            fingerprint="sha256:aa",
            request={"scenario_id": 3, "composition_id": "NEW-BAL-7"},
        )
        side_b = _synthetic_side(
            views={
                "route": {
                    "description": "text is skipped",
                    "data": {"net_eur": 5.0, "total_cost_eur": 100.3, "label": "y"},
                }
            },
            summary={"total_distance_km": 800.0, "subsidy_eur_per_t_co2": 12.0},
            fingerprint="sha256:bb",
            request={"scenario_id": 4, "composition_id": "NEW-BAL-7"},
        )
        diff = build_diff(side_a, side_b)

        # Zero base -> rel is null, abs still real.
        assert diff["views"]["route"]["data"]["net_eur"] == {
            "a": 0.0,
            "b": 5.0,
            "abs": 5.0,
            "rel": None,
        }
        # Float noise absorbed by the delta rounding.
        assert diff["views"]["route"]["data"]["total_cost_eur"]["abs"] == 0.3
        # Strings never diff; a numeric-vs-null summary KPI is skipped.
        assert "label" not in diff["views"]["route"]["data"]
        assert "description" not in diff["views"]["route"]
        assert "subsidy_eur_per_t_co2" not in diff["summary"]
        assert diff["summary"]["total_distance_km"]["abs"] == 0

        context = build_route_context(side_a, side_b)
        assert context["route_identical"] is False
        assert context["differing_request_fields"] == ["scenario_id"]

    def test_published_prefixes_are_neutralised_before_diffing(self):
        """Two published proposals key their trip views by their OWN
        P{id}_V{n}_ prefix. Diffed verbatim, nothing below the route view
        could ever match — so both sides are neutralised to structural
        ids first, and the resulting paths are structural too."""
        side_a = _synthetic_side(
            views={"per_trip_pair": {"data": {"P12_V3_T1": {"x": 1.0}}}},
            summary={},
            fingerprint="sha256:aa",
            request={},
            published=True,
            proposal_id=12,
            proposal_version=3,
        )
        side_b = _synthetic_side(
            views={"per_trip_pair": {"data": {"P15_V1_T1": {"x": 1.5}}}},
            summary={},
            fingerprint="sha256:aa",
            request={},
            published=True,
            proposal_id=15,
            proposal_version=1,
        )
        diff = build_diff(side_a, side_b)
        assert diff["views"]["per_trip_pair"]["data"]["T1"]["x"]["abs"] == 0.5
        assert diff["views_unmatched"] == {"a_only": [], "b_only": []}

    def test_published_and_computed_sides_diff_against_each_other(self):
        """The mixed case: a published side (prefixed) against an
        override side (already structural) — the asymmetry must not
        reintroduce a mismatch."""
        side_a = _synthetic_side(
            views={"per_trip_pair": {"data": {"P12_V3_T1": {"x": 2.0}}}},
            summary={},
            fingerprint="sha256:aa",
            request={},
            published=True,
            proposal_id=12,
            proposal_version=3,
        )
        side_b = _synthetic_side(
            views={"per_trip_pair": {"data": {"T1": {"x": 3.0}}}},
            summary={},
            fingerprint="sha256:aa",
            request={},
        )
        diff = build_diff(side_a, side_b)
        assert diff["views"]["per_trip_pair"]["data"]["T1"]["x"]["abs"] == 1.0
        assert diff["views_unmatched"] == {"a_only": [], "b_only": []}

    def test_unmatched_keys_are_collected_not_half_diffed(self):
        side_a = _synthetic_side(
            views={"per_trip_pair": {"data": {"T1": {"x": 1.0}, "T3": {"x": 2.0}}}},
            summary={},
            fingerprint="sha256:aa",
            request={},
        )
        side_b = _synthetic_side(
            views={"per_trip_pair": {"data": {"T1": {"x": 1.5}, "T5": {"x": 9.0}}}},
            summary={},
            fingerprint="sha256:aa",
            request={},
        )
        diff = build_diff(side_a, side_b)
        assert diff["views"]["per_trip_pair"]["data"]["T1"]["x"]["abs"] == 0.5
        assert "T3" not in diff["views"]["per_trip_pair"]["data"]
        assert diff["views_unmatched"]["a_only"] == ["per_trip_pair.data.T3"]
        assert diff["views_unmatched"]["b_only"] == ["per_trip_pair.data.T5"]
