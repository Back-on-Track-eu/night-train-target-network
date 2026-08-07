"""
test_50_proposals_api.py
========================
POST /api/proposal/publish, GET /api/proposal/<id>, and GET/POST
/api/proposals (adapters/proposal/README.md §2.2, §7.1, §7.2). Publish is the
only user write path.

Covers:
  - publish mode="new": create, response shape, GTFS decomposition, load
    round-trip
  - publish mode="overwrite": edit (composition change), version bump,
    previous state pruned; ownership (403 foreign, 404 unknown)
  - base-scenario rule: non-base compute_request.scenario_id -> 422
  - build on foreign: load + compute + publish new with
    based_on_proposal_id
  - validation errors (400) and missing auth (401)
  - GET /api/proposal/<id>: 404 unknown, round-trip of a fresh publish
  - GET/POST /api/proposals: summaries, user_ids filter, pagination

Identities: the suite publishes as the seeded 'test_script' user
(conftest.py: script_headers — already a plain {"Authorization": ...}
header dict); guest sessions from POST /api/auth/guest supply the
second, foreign owner where ownership/branch semantics need one.

Isolation: publishing commits through the API's own connection, so the
suite's per-test rollback can't undo it. The module fixture purges
published proposals before and after this file — except the permanent
example proposal seeded at DB init time (db/dev/seed.py,
proposal_id=_SEED_PROPOSAL_ID).
"""

from datetime import datetime

import pytest
import requests

from tests.helpers import (
    PROPOSAL_URL,
    PROPOSALS_URL,
    compute,
    publish,
    purge_saved_proposals,
)

# Matches db/dev/seed.py's _SEED_PROPOSAL_ID / seed_example_proposal() —
# a real published proposal seeded at DB init time, permanent and outside
# this module's purge, so a full test run doesn't erase the one working
# example a person could inspect right after docker-compose up.
_SEED_PROPOSAL_ID = 1

# The cheapest corridor the seed data supports — every fresh publish in
# this file uses it to keep OpenRailRouting time bounded.
_STOPS = ["DE_BERLIN_HBF", "AT_WIEN_HBF"]
_COMPOSITION = "NEW-BAL-7"
_OTHER_COMPOSITION = "REF-BAL-9"  # the composition-change-via-overwrite case


@pytest.fixture(scope="module", autouse=True)
def clean_proposals(db_conn, script_headers):
    """Purge published proposals before and after this module (the seeded
    example proposal is preserved — see purge_saved_proposals). Depends on
    script_headers so the session-level teardown purge there runs strictly
    after this module's own."""
    purge_saved_proposals(db_conn)
    yield
    purge_saved_proposals(db_conn)


@pytest.fixture(scope="module")
def guest(api_base):
    """A guest session — the foreign owner for ownership/branch semantics.
    {'headers': ..., 'user_id': ...}"""
    resp = requests.post(f"{api_base}/api/auth/guest", timeout=10)
    if resp.status_code == 429:
        pytest.skip("guest endpoint rate-limited — rerun later")
    assert resp.status_code == 200
    body = resp.json()
    return {
        "headers": {"Authorization": f"Bearer {body['token']}"},
        "user_id": body["user_id"],
    }


def _computed_request(api_base, stops=_STOPS, composition_id=_COMPOSITION, **extra):
    """A resolved compute_request — exactly what a real publish carries
    (§2.2: 'the exact resolved request of §2.1'). Goes through a live
    POST /api/proposal/calc rather than being hand-built, so it's always
    valid (defaults applied, scenario_id concrete) the same way a real
    frontend publish flow would produce it."""
    return compute(api_base, stops, composition_id, **extra)["request"]


# =============================================================================
# publish mode="new"
# =============================================================================


@pytest.fixture(scope="module")
def published(api_base, script_headers):
    """One fresh publish — the proposal the overwrite/ownership/load tests
    build on. Module-scoped: tests within TestPublishOverwrite build on
    each other's state in definition order (don't reorder or -k-split)."""
    return publish(
        api_base,
        _computed_request(api_base),
        name="Berlin \u2013 Wien (test)",
        headers=script_headers,
    )


class TestPublishNew:
    @pytest.mark.timeout(120)
    def test_publish_new_returns_full_shape(self, published, script_user_id):
        assert published["proposal_version"] == 1
        assert published["user_id"] == script_user_id
        assert published["name"] == "Berlin \u2013 Wien (test)"
        assert published["route"]["route_id"] == f"P{published['proposal_id']}_V1_R1"
        assert set(published["evaluation"]) == {"models", "input", "views"}

    def test_publish_new_forbids_proposal_id(self, api_base, script_headers):
        resp = requests.post(
            f"{api_base}{PROPOSAL_URL}/publish",
            json={
                "compute_request": _computed_request(api_base),
                "name": "x",
                "mode": "new",
                "proposal_id": 12345,
            },
            headers=script_headers,
            timeout=60,
        )
        assert resp.status_code == 400

    def test_publish_requires_auth(self, api_base):
        resp = requests.post(
            f"{api_base}{PROPOSAL_URL}/publish",
            json={
                "compute_request": _computed_request(api_base),
                "name": "x",
                "mode": "new",
            },
            timeout=60,
        )
        assert resp.status_code == 401

    def test_publish_new_round_trips_via_load(self, api_base, published):
        resp = requests.get(
            f"{api_base}{PROPOSAL_URL}/{published['proposal_id']}", timeout=15
        )
        assert resp.status_code == 200
        loaded = resp.json()
        assert loaded["proposal_id"] == published["proposal_id"]
        assert loaded["proposal_version"] == 1
        assert loaded["name"] == published["name"]
        assert loaded["route_fingerprint"] == published["route_fingerprint"]
        assert set(loaded["route"]["trip_pairs"][0]) == set(
            published["route"]["trip_pairs"][0]
        )


# =============================================================================
# publish mode="overwrite"
# =============================================================================


class TestPublishOverwrite:
    def test_overwrite_bumps_version_and_changes_composition(
        self, api_base, script_headers, published
    ):
        overwritten = publish(
            api_base,
            _computed_request(api_base, composition_id=_OTHER_COMPOSITION),
            name=published["name"],
            mode="overwrite",
            proposal_id=published["proposal_id"],
            headers=script_headers,
        )
        assert overwritten["proposal_id"] == published["proposal_id"]
        assert overwritten["proposal_version"] == 2
        assert (
            overwritten["route"]["trip_pairs"][0]["composition_id"]
            == _OTHER_COMPOSITION
        )

        resp = requests.get(
            f"{api_base}{PROPOSAL_URL}/{published['proposal_id']}", timeout=15
        )
        assert resp.json()["proposal_version"] == 2

    def test_overwrite_unknown_proposal_404(self, api_base, script_headers):
        resp = requests.post(
            f"{api_base}{PROPOSAL_URL}/publish",
            json={
                "compute_request": _computed_request(api_base),
                "name": "x",
                "mode": "overwrite",
                "proposal_id": 999_999_999,
            },
            headers=script_headers,
            timeout=60,
        )
        assert resp.status_code == 404

    def test_overwrite_foreign_proposal_403(self, api_base, published, guest):
        resp = requests.post(
            f"{api_base}{PROPOSAL_URL}/publish",
            json={
                "compute_request": _computed_request(api_base),
                "name": "x",
                "mode": "overwrite",
                "proposal_id": published["proposal_id"],
            },
            headers=guest["headers"],
            timeout=60,
        )
        assert resp.status_code == 403


# =============================================================================
# Base-scenario rule (§2.2, locked decision 4)
# =============================================================================


class TestBaseScenarioRule:
    def test_non_base_scenario_rejected(
        self, api_base, script_headers, historical_scenario
    ):
        compute_request = _computed_request(
            api_base, scenario_id=historical_scenario["scenario_id"]
        )
        resp = requests.post(
            f"{api_base}{PROPOSAL_URL}/publish",
            json={"compute_request": compute_request, "name": "x", "mode": "new"},
            headers=script_headers,
            timeout=60,
        )
        assert resp.status_code == 422
        assert resp.json()["error"] == "scenario_not_base"


# =============================================================================
# Build on foreign
# =============================================================================


class TestBuildOnForeign:
    def test_build_on_seed_publishes_new_under_caller(self, api_base, guest):
        """Load the permanent seed proposal (read-only, foreign), compute
        freely, publish as new with based_on_proposal_id — §6 'build on
        foreign' flow. The new proposal belongs to the guest, not the
        seed's owner."""
        resp = requests.get(f"{api_base}{PROPOSAL_URL}/{_SEED_PROPOSAL_ID}", timeout=15)
        assert resp.status_code == 200
        seed = resp.json()

        branched = publish(
            api_base,
            seed["request"],
            name="Branched from seed",
            mode="new",
            based_on_proposal_id=_SEED_PROPOSAL_ID,
            headers=guest["headers"],
        )
        assert branched["proposal_id"] != _SEED_PROPOSAL_ID
        assert branched["user_id"] == guest["user_id"]


# =============================================================================
# Validation
# =============================================================================


class TestPublishValidation:
    def test_missing_name(self, api_base, script_headers):
        resp = requests.post(
            f"{api_base}{PROPOSAL_URL}/publish",
            json={"compute_request": _computed_request(api_base), "mode": "new"},
            headers=script_headers,
            timeout=60,
        )
        assert resp.status_code == 400

    def test_invalid_mode(self, api_base, script_headers):
        resp = requests.post(
            f"{api_base}{PROPOSAL_URL}/publish",
            json={
                "compute_request": _computed_request(api_base),
                "name": "x",
                "mode": "sideways",
            },
            headers=script_headers,
            timeout=60,
        )
        assert resp.status_code == 400

    def test_overwrite_without_proposal_id(self, api_base, script_headers):
        resp = requests.post(
            f"{api_base}{PROPOSAL_URL}/publish",
            json={
                "compute_request": _computed_request(api_base),
                "name": "x",
                "mode": "overwrite",
            },
            headers=script_headers,
            timeout=60,
        )
        assert resp.status_code == 400

    def test_malformed_compute_request(self, api_base, script_headers):
        resp = requests.post(
            f"{api_base}{PROPOSAL_URL}/publish",
            json={
                "compute_request": {"stops": ["ONLY_ONE"]},
                "name": "x",
                "mode": "new",
            },
            headers=script_headers,
            timeout=60,
        )
        assert resp.status_code == 400


# =============================================================================
# GET /api/proposal/<id>
# =============================================================================


def test_get_unknown_proposal_returns_404(api_base):
    resp = requests.get(f"{api_base}{PROPOSAL_URL}/999999999", timeout=15)
    assert resp.status_code == 404


def test_seeded_example_proposal_is_queryable(api_base):
    resp = requests.get(f"{api_base}{PROPOSAL_URL}/{_SEED_PROPOSAL_ID}", timeout=15)
    assert resp.status_code == 200
    body = resp.json()
    assert body["proposal_id"] == _SEED_PROPOSAL_ID
    per_year = body["evaluation"]["views"]["route"]["data"]["per_year"]["all"]
    assert per_year["total_revenue_eur"] > 0


class TestLoad:
    """Response-contract coverage for GET /api/proposal/<id> (§7.2, WP7):
    the full compute-response shape (§2.1) plus the metadata block. The
    round-trip test above already checks specific-field equality against
    a fresh publish; this class checks the shape itself, independent of
    any one publish's content."""

    def test_top_level_keys(self, api_base, published):
        resp = requests.get(
            f"{api_base}{PROPOSAL_URL}/{published['proposal_id']}", timeout=15
        )
        assert resp.status_code == 200
        body = resp.json()
        assert set(body) >= {
            "proposal_id",
            "proposal_version",
            "user_id",
            "user_name",
            "name",
            "created_at",
            "updated_at",
            "route_builder_version",
            "calc_version",
            "route_fingerprint",
            "request",
            "route",
            "evaluation",
        }
        assert set(body["evaluation"]) == {"models", "input", "views"}

    def test_timestamps_are_well_formed(self, api_base, published):
        # published (the publish response) and the load response should
        # both carry real, parseable timestamps — publish() used to omit
        # created_at entirely (WP7 fix, §14).
        for source in (published, self._load(api_base, published["proposal_id"])):
            assert isinstance(source["created_at"], str)
            assert isinstance(source["updated_at"], str)
            datetime.fromisoformat(source["created_at"])
            datetime.fromisoformat(source["updated_at"])

    def test_load_created_at_matches_publish(self, api_base, published):
        # A round-trip-specific check the shape test above doesn't cover:
        # load must report the SAME created_at publish did, not a fresh
        # timestamp — this is the one field a naive re-select could get
        # wrong if it weren't excluded from the overwrite's SET list.
        loaded = self._load(api_base, published["proposal_id"])
        assert loaded["created_at"] == published["created_at"]

    @staticmethod
    def _load(api_base, proposal_id):
        resp = requests.get(f"{api_base}{PROPOSAL_URL}/{proposal_id}", timeout=15)
        assert resp.status_code == 200
        return resp.json()


# =============================================================================
# GET/POST /api/proposals — list
# =============================================================================


class TestList:
    """WP6-minimal coverage of the sectioned response envelope — the full
    §7.1 filter/sort/section contract is covered end to end in
    test_52_proposals_gallery_api.py."""

    def test_list_includes_published_and_seed(self, api_base, published):
        """GET /api/proposals defaults to sources=both (WP10 step 6b) —
        the plain GET has no body to filter with, so the response mixes
        in existing (ONTD) rows, which omit proposal_id entirely (the
        reduced shape, not null-padded). This test is about proposal
        identity specifically, so it reads only source="proposal" rows."""
        resp = requests.get(f"{api_base}{PROPOSALS_URL}", timeout=15)
        assert resp.status_code == 200
        body = resp.json()
        ids = {
            p["proposal_id"]
            for p in body["summaries"]["proposals"]
            if p["source"] == "proposal"
        }
        assert published["proposal_id"] in ids
        assert _SEED_PROPOSAL_ID in ids

    def test_filter_by_user_ids(self, api_base, published, script_user_id):
        resp = requests.post(
            f"{api_base}{PROPOSALS_URL}",
            json={"filter": {"user_ids": [script_user_id]}},
            timeout=15,
        )
        assert resp.status_code == 200
        proposals = resp.json()["summaries"]["proposals"]
        assert all(p["user_id"] == script_user_id for p in proposals)
        assert published["proposal_id"] in {p["proposal_id"] for p in proposals}

    def test_pagination(self, api_base, published):
        resp = requests.post(
            f"{api_base}{PROPOSALS_URL}", json={"limit": 1, "offset": 0}, timeout=15
        )
        assert resp.status_code == 200
        assert len(resp.json()["summaries"]["proposals"]) <= 1

    def test_list_rejects_unknown_filter_key(self, api_base):
        resp = requests.post(
            f"{api_base}{PROPOSALS_URL}", json={"filter": {"bogus": [1]}}, timeout=15
        )
        assert resp.status_code == 400
