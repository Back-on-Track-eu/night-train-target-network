"""
test_53_proposal_refresh.py
============================
Version-refresh mechanism (adapters/proposal/README.md §4.2,
2026-08-04): the on-load fallback in GET /api/proposal/<id>
(api/proposals.py) and the batch script (scripts/refresh_proposals.py).
Both share one staleness check — adapters/proposal/repository.py's
outdated_trigger().

These tests force staleness by mutating proposals.proposals directly
(route_builder_version to a value guaranteed older than any real one) —
the same "force it via direct DB mutation" pattern
test_52_proposals_gallery_api.py used for the now-removed
scenario_outdated flag, applied here to a trigger that still exists.
base_scenario_moved/calc_version aren't separately exercised: all three
triggers run through the exact same outdated_trigger()/refresh_proposal()
code path, so one trigger's coverage stands in for the mechanism itself.

Isolation: same discipline as test_50/test_52 — publishing (and the
script's writes) commit outside the suite's per-test rollback, so this
module purges published proposals before/after itself.
"""

import pytest
import requests

from adapters.proposal.repository import outdated_trigger
from api.helpers import dependencies
from models.route.model import ROUTE_BUILDER_VERSION
from scripts.refresh_proposals import run as run_refresh
from tests.helpers import PROPOSAL_URL, compute, publish, purge_saved_proposals

_STOPS = ["osm:n3856100103", "osm:w423692233"]
_COMPOSITION = "NEW-BAL-7"

# Guaranteed older than any real ROUTE_BUILDER_VERSION (semver-style
# strings compare fine for this purpose — we only need "!= current").
_STALE_ROUTE_BUILDER_VERSION = "0.0.1"


@pytest.fixture(scope="module", autouse=True)
def clean_proposals(db_conn, script_headers):
    """Purge published proposals before and after this module — same
    convention as test_50/test_52 (the permanent seed proposal is
    preserved by purge_saved_proposals)."""
    purge_saved_proposals(db_conn)
    yield
    purge_saved_proposals(db_conn)


def _publish_one(api_base, script_headers, name: str) -> dict:
    request = compute(api_base, _STOPS, _COMPOSITION)["request"]
    return publish(api_base, request, name=name, headers=script_headers)


def _mark_stale(db_conn, proposal_id: int) -> None:
    """Directly age a published proposal's route_builder_version so
    outdated_trigger() fires on it."""
    cur = db_conn.cursor()
    cur.execute(
        "UPDATE proposals.proposals SET route_builder_version = %s "
        "WHERE proposal_id = %s",
        (_STALE_ROUTE_BUILDER_VERSION, proposal_id),
    )
    db_conn.commit()


def _stored_route_builder_version(db_cur, db_conn, proposal_id: int) -> str:
    """Reads the column directly — deliberately NOT via GET /api/proposal/
    <id>, which would trigger its own on-load refresh and mask whatever
    state a dry-run (or an as-yet-unrun batch) actually left behind."""
    db_cur.execute(
        "SELECT route_builder_version FROM proposals.proposals WHERE proposal_id = %s",
        (proposal_id,),
    )
    row = db_cur.fetchone()
    db_conn.commit()
    return row["route_builder_version"]


# =============================================================================
# On-load fallback — GET /api/proposal/<id>
# =============================================================================


class TestOnLoadFallback:
    def test_stale_proposal_is_refreshed_on_load(
        self, api_base, script_headers, db_conn, db_cur
    ):
        published = _publish_one(
            api_base, script_headers, "Stale on load (refresh test)"
        )
        _mark_stale(db_conn, published["proposal_id"])

        resp = requests.get(
            f"{api_base}{PROPOSAL_URL}/{published['proposal_id']}", timeout=60
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["route_builder_version"] == ROUTE_BUILDER_VERSION
        # A refresh is a state transition like any overwrite — the
        # counter bumps even though no user touched anything.
        assert body["proposal_version"] == 2

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
        assert row["detail"]["from"] == _STALE_ROUTE_BUILDER_VERSION
        assert row["detail"]["to"] == ROUTE_BUILDER_VERSION

    def test_current_proposal_is_not_refreshed_on_load(self, api_base, script_headers):
        # A load that finds nothing outdated must not bump the version —
        # confirms outdated_trigger() actually gates the fallback rather
        # than refreshing unconditionally on every load.
        published = _publish_one(
            api_base, script_headers, "Current on load (refresh test)"
        )
        resp = requests.get(
            f"{api_base}{PROPOSAL_URL}/{published['proposal_id']}", timeout=15
        )
        assert resp.status_code == 200
        assert resp.json()["proposal_version"] == 1


# =============================================================================
# Batch script — scripts/refresh_proposals.py
# =============================================================================


class TestBatchScript:
    def test_dry_run_reports_but_does_not_write(
        self, api_base, script_headers, db_conn, db_cur
    ):
        published = _publish_one(
            api_base, script_headers, "Batch dry-run (refresh test)"
        )
        _mark_stale(db_conn, published["proposal_id"])

        failures = run_refresh(dry_run=True)
        assert failures == 0
        assert (
            _stored_route_builder_version(db_cur, db_conn, published["proposal_id"])
            == _STALE_ROUTE_BUILDER_VERSION
        )

    def test_run_refreshes_and_is_idempotent(
        self, api_base, script_headers, db_conn, db_cur
    ):
        published = _publish_one(api_base, script_headers, "Batch run (refresh test)")
        _mark_stale(db_conn, published["proposal_id"])

        repo = dependencies.get_proposal_repository()
        outdated_before = repo.list_outdated()
        assert published["proposal_id"] in {
            row["proposal_id"] for row in outdated_before
        }

        failures = run_refresh()
        assert failures == 0
        assert (
            _stored_route_builder_version(db_cur, db_conn, published["proposal_id"])
            == ROUTE_BUILDER_VERSION
        )

        # Idempotent: list_outdated() re-derives the work queue fresh
        # from current DB state every call, so a second run — with
        # nothing left to do — must find this proposal gone from it.
        outdated_after = repo.list_outdated()
        assert published["proposal_id"] not in {
            row["proposal_id"] for row in outdated_after
        }

        failures_second_run = run_refresh()
        assert failures_second_run == 0

    def test_list_outdated_agrees_with_outdated_trigger(
        self, api_base, script_headers, db_conn
    ):
        # list_outdated()'s SQL filter and outdated_trigger()'s Python
        # check are two independent expressions of the same rule (§4.2) —
        # this is the one place they're checked against each other
        # directly, rather than only indirectly through run()'s behaviour.
        published = _publish_one(
            api_base, script_headers, "Trigger agreement (refresh test)"
        )
        _mark_stale(db_conn, published["proposal_id"])

        repo = dependencies.get_proposal_repository()
        row = next(
            r
            for r in repo.list_outdated()
            if r["proposal_id"] == published["proposal_id"]
        )
        trigger = outdated_trigger(row)
        assert trigger is not None
        assert trigger["trigger"] == "route_builder_version"
