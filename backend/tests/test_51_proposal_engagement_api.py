"""
test_51_proposal_engagement_api.py
===================================
Proposal engagement (WP11): GET /api/proposal/<id>/engagements,
POST/DELETE /api/proposal/<id>/like, and
POST/PATCH/DELETE /api/proposal/<id>/comment[/<cid>].

Covers:
  - 404 for an unknown proposal_id on every endpoint
  - Likes: auth required to write, idempotent like/unlike, liked_by_me is
    per-caller and False for an unauthenticated read
  - Comments: validation (empty/oversized body), auth required to write,
    proposal_version stamped from the target's current version,
    author-only edit/delete (403 for a different user), a deleted comment
    disappearing from the thread and refusing further edit/delete
  - Timeline: chronological merge of update_log + likes + comments;
    system refresh vs user overwrite distinguished by actor; withdrawn
    likes and deleted comments leaving no trace; an edited comment moving
    to its edit time; branch events landing on both proposals

Targets: the like/comment behaviour tests use the permanent seed proposal
(_SEED_PROPOSAL_ID, see test_50_proposals_api.py) rather than a freshly
built route — engagement rows don't depend on route content, and a route
build is expensive (live OpenRailRouting). The timeline tests do need
real publishes, since update_log rows only exist as a side effect of the
publish/refresh transaction.

Isolation: writes commit through the API's own connection, so the
per-test rollback fixture can't undo them (same situation as
test_50/test_60). This module's own rows are purged before and after via
the module fixture below; purge_saved_proposals clears likes, comments
and update_log unconditionally.
"""

import pytest
import requests

from models.route.model import ROUTE_BUILDER_VERSION
from tests.helpers import (
    PROPOSAL_URL,
    comment_url,
    compute,
    engagements_url,
    like_url,
    publish,
    purge_saved_proposals,
)

# Matches test_50_proposals_api.py's constant — the permanent proposal
# seeded at DB init time (db/dev/seed.py), always present.
_SEED_PROPOSAL_ID = 1

_UNKNOWN_PROPOSAL_ID = 987654321

_STOPS = ["DE_BERLIN_HBF", "AT_WIEN_HBF"]
_COMPOSITION = "NEW-BAL-7"

# Mirrors test_53_proposal_refresh.py: guaranteed older than any real
# ROUTE_BUILDER_VERSION, so outdated_trigger() fires on the next load.
_STALE_ROUTE_BUILDER_VERSION = "0.0.1"


@pytest.fixture(scope="module", autouse=True)
def clean_engagement(db_conn):
    """Purge before and after this module — see module docstring for why
    it's safe to target the permanent seed proposal here."""
    purge_saved_proposals(db_conn)
    yield
    purge_saved_proposals(db_conn)


@pytest.fixture
def clean_engagement_per_test(db_conn):
    """A per-test purge for tests that assert exact counts/state and
    would otherwise interfere with each other by sharing the seed
    proposal within the module."""
    purge_saved_proposals(db_conn)
    yield
    purge_saved_proposals(db_conn)


@pytest.fixture(scope="module")
def guest(api_base):
    """A guest session — the foreign owner for ownership checks. Mirrors
    test_50_proposals_api.py's own copy (module-local fixtures aren't
    shared across files)."""
    resp = requests.post(f"{api_base}/api/auth/guest", timeout=10)
    if resp.status_code == 429:
        pytest.skip("guest endpoint rate-limited — rerun later")
    assert resp.status_code == 200
    body = resp.json()
    return {
        "headers": {"Authorization": f"Bearer {body['token']}"},
        "user_id": body["user_id"],
    }


def _engagements(api_base, proposal_id: int, headers: dict | None = None) -> dict:
    resp = requests.get(
        f"{api_base}{engagements_url(proposal_id)}", timeout=15, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _events(body: dict) -> list[str]:
    return [event["event"] for event in body["timeline"]]


# =============================================================================
# Aggregate read — unknown proposal, empty state
# =============================================================================


def test_engagements_unknown_proposal_returns_404(api_base):
    resp = requests.get(
        f"{api_base}{engagements_url(_UNKNOWN_PROPOSAL_ID)}", timeout=10
    )
    assert resp.status_code == 404
    assert resp.json()["error"] == "not_found"


def test_engagements_of_untouched_proposal_is_empty(
    api_base, clean_engagement_per_test
):
    body = _engagements(api_base, _SEED_PROPOSAL_ID)
    assert body["proposal_id"] == _SEED_PROPOSAL_ID
    assert body["likes"] == {"count": 0, "liked_by_me": False}
    assert body["comments"] == {"count": 0, "items": []}
    # The seed proposal is written by seed.py, not by publish(), so it
    # has no update_log rows of its own either.
    assert body["timeline"] == []


# =============================================================================
# Likes
# =============================================================================


def test_like_requires_auth(api_base):
    resp = requests.post(f"{api_base}{like_url(_SEED_PROPOSAL_ID)}", timeout=10)
    assert resp.status_code == 401


def test_unlike_requires_auth(api_base):
    resp = requests.delete(f"{api_base}{like_url(_SEED_PROPOSAL_ID)}", timeout=10)
    assert resp.status_code == 401


def test_like_unknown_proposal_returns_404(api_base, script_headers):
    resp = requests.post(
        f"{api_base}{like_url(_UNKNOWN_PROPOSAL_ID)}",
        timeout=10,
        headers=script_headers,
    )
    assert resp.status_code == 404


def test_like_is_idempotent_and_per_caller(
    api_base, clean_engagement_per_test, script_headers, guest
):
    # First like: count 1, liked_by_me True for the liker.
    resp = requests.post(
        f"{api_base}{like_url(_SEED_PROPOSAL_ID)}", timeout=10, headers=script_headers
    )
    assert resp.status_code == 200
    assert resp.json() == {"count": 1, "liked_by_me": True}

    # Liking again is a no-op, not a second row.
    resp = requests.post(
        f"{api_base}{like_url(_SEED_PROPOSAL_ID)}", timeout=10, headers=script_headers
    )
    assert resp.json() == {"count": 1, "liked_by_me": True}

    # A different caller sees the same count but liked_by_me False for
    # themselves until they also like it.
    body = _engagements(api_base, _SEED_PROPOSAL_ID, headers=guest["headers"])
    assert body["likes"] == {"count": 1, "liked_by_me": False}

    resp = requests.post(
        f"{api_base}{like_url(_SEED_PROPOSAL_ID)}",
        timeout=10,
        headers=guest["headers"],
    )
    assert resp.json() == {"count": 2, "liked_by_me": True}


def test_liked_by_me_is_false_for_anonymous_reader(
    api_base, clean_engagement_per_test, script_headers
):
    requests.post(
        f"{api_base}{like_url(_SEED_PROPOSAL_ID)}", timeout=10, headers=script_headers
    )
    body = _engagements(api_base, _SEED_PROPOSAL_ID)
    assert body["likes"] == {"count": 1, "liked_by_me": False}


def test_unlike_is_idempotent_and_removes_the_event(
    api_base, clean_engagement_per_test, script_headers
):
    requests.post(
        f"{api_base}{like_url(_SEED_PROPOSAL_ID)}", timeout=10, headers=script_headers
    )
    assert "liked" in _events(_engagements(api_base, _SEED_PROPOSAL_ID))

    resp = requests.delete(
        f"{api_base}{like_url(_SEED_PROPOSAL_ID)}", timeout=10, headers=script_headers
    )
    assert resp.status_code == 200
    assert resp.json() == {"count": 0, "liked_by_me": False}

    # Unliking again (nothing left to remove) is still a clean 200.
    resp = requests.delete(
        f"{api_base}{like_url(_SEED_PROPOSAL_ID)}", timeout=10, headers=script_headers
    )
    assert resp.status_code == 200
    assert resp.json() == {"count": 0, "liked_by_me": False}

    # A withdrawn like leaves no trace — the timeline is a projection of
    # current state, not an audit trail (locked decision 28).
    assert _events(_engagements(api_base, _SEED_PROPOSAL_ID)) == []


# =============================================================================
# Comments — validation, unknown proposal
# =============================================================================


def test_comment_requires_auth(api_base):
    resp = requests.post(
        f"{api_base}{comment_url(_SEED_PROPOSAL_ID)}", json={"body": "hi"}, timeout=10
    )
    assert resp.status_code == 401


def test_comment_rejects_empty_body(api_base, script_headers):
    resp = requests.post(
        f"{api_base}{comment_url(_SEED_PROPOSAL_ID)}",
        json={"body": "   "},
        timeout=10,
        headers=script_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "validation_error"


def test_comment_rejects_oversized_body(api_base, script_headers):
    resp = requests.post(
        f"{api_base}{comment_url(_SEED_PROPOSAL_ID)}",
        json={"body": "x" * 4001},
        timeout=10,
        headers=script_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "validation_error"


def test_comment_unknown_proposal_returns_404(api_base, script_headers):
    resp = requests.post(
        f"{api_base}{comment_url(_UNKNOWN_PROPOSAL_ID)}",
        json={"body": "hi"},
        timeout=10,
        headers=script_headers,
    )
    assert resp.status_code == 404


# =============================================================================
# Comments — full lifecycle (add, read, edit, delete, ownership)
# =============================================================================


@pytest.fixture
def posted_comment(api_base, clean_engagement_per_test, script_headers, script_user_id):
    """One fresh comment on the seed proposal, owned by test_script."""
    resp = requests.post(
        f"{api_base}{comment_url(_SEED_PROPOSAL_ID)}",
        json={"body": "  Have you compared the Basel alternative?  "},
        timeout=10,
        headers=script_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_add_comment_returns_stored_shape(posted_comment, script_user_id):
    """body is stripped server-side; proposal_version is stamped from the
    proposal's current version at the moment of commenting. is_deleted is
    not part of the API shape at all since WP11 — a deleted comment is
    returned by nothing, so the flag could only ever have been false."""
    assert posted_comment["proposal_id"] == _SEED_PROPOSAL_ID
    assert posted_comment["proposal_version"] == 1  # seed proposal is v1
    assert posted_comment["user_id"] == script_user_id
    assert posted_comment["user_name"] == "test_script"
    assert posted_comment["body"] == "Have you compared the Basel alternative?"
    assert "is_deleted" not in posted_comment
    assert posted_comment["created_at"] == posted_comment["updated_at"]


def test_engagements_includes_posted_comment(api_base, posted_comment):
    body = _engagements(api_base, _SEED_PROPOSAL_ID)
    assert body["comments"]["count"] == 1
    assert body["comments"]["items"][0]["comment_id"] == posted_comment["comment_id"]

    event = body["timeline"][0]
    assert event["event"] == "commented"
    assert event["detail"] == {
        "comment_id": posted_comment["comment_id"],
        "edited": False,
    }
    assert event["at"] == posted_comment["updated_at"]


def test_edit_comment_by_author_moves_its_event(
    api_base, posted_comment, script_headers
):
    cid = posted_comment["comment_id"]
    resp = requests.patch(
        f"{api_base}{comment_url(_SEED_PROPOSAL_ID, cid)}",
        json={"body": "Updated: Basel is 12 min faster."},
        timeout=10,
        headers=script_headers,
    )
    assert resp.status_code == 200
    edited = resp.json()
    assert edited["body"] == "Updated: Basel is 12 min faster."
    assert edited["updated_at"] > posted_comment["updated_at"]

    # The event follows the edit rather than staying at the post time.
    event = _engagements(api_base, _SEED_PROPOSAL_ID)["timeline"][0]
    assert event["detail"] == {"comment_id": cid, "edited": True}
    assert event["at"] == edited["updated_at"]


def test_edit_comment_by_other_user_is_forbidden(api_base, posted_comment, guest):
    resp = requests.patch(
        f"{api_base}{comment_url(_SEED_PROPOSAL_ID, posted_comment['comment_id'])}",
        json={"body": "hijacked"},
        timeout=10,
        headers=guest["headers"],
    )
    assert resp.status_code == 403


def test_edit_comment_unknown_id_returns_404(api_base, script_headers):
    resp = requests.patch(
        f"{api_base}{comment_url(_SEED_PROPOSAL_ID, 999999)}",
        json={"body": "hi"},
        timeout=10,
        headers=script_headers,
    )
    assert resp.status_code == 404


def test_delete_comment_by_other_user_is_forbidden(api_base, posted_comment, guest):
    resp = requests.delete(
        f"{api_base}{comment_url(_SEED_PROPOSAL_ID, posted_comment['comment_id'])}",
        timeout=10,
        headers=guest["headers"],
    )
    assert resp.status_code == 403


def test_delete_comment_by_author_removes_it_everywhere(
    api_base, posted_comment, script_headers
):
    cid = posted_comment["comment_id"]
    resp = requests.delete(
        f"{api_base}{comment_url(_SEED_PROPOSAL_ID, cid)}",
        timeout=10,
        headers=script_headers,
    )
    assert resp.status_code == 204
    assert resp.text == ""

    # Gone from both the thread and the timeline — no tombstone (WP11).
    body = _engagements(api_base, _SEED_PROPOSAL_ID)
    assert body["comments"] == {"count": 0, "items": []}
    assert body["timeline"] == []

    # The row still exists underneath, so a second edit/delete is a 404
    # rather than a resurrection.
    resp = requests.patch(
        f"{api_base}{comment_url(_SEED_PROPOSAL_ID, cid)}",
        json={"body": "resurrect me"},
        timeout=10,
        headers=script_headers,
    )
    assert resp.status_code == 404

    resp = requests.delete(
        f"{api_base}{comment_url(_SEED_PROPOSAL_ID, cid)}",
        timeout=10,
        headers=script_headers,
    )
    assert resp.status_code == 404


# =============================================================================
# Timeline — update_log merged with engagement (needs real publishes)
# =============================================================================


class TestTimeline:
    @pytest.fixture(scope="class")
    def compute_request(self, api_base):
        """One route build shared by every test in this class — the
        expensive part, and none of these assertions depend on the route
        content."""
        return compute(api_base, _STOPS, _COMPOSITION)["request"]

    def test_publish_comment_like_overwrite_refresh_in_order(
        self, api_base, script_headers, script_user_id, db_conn, compute_request
    ):
        """The WP11 acceptance case: every event kind on one proposal, in
        the order it happened, with a user overwrite and a system refresh
        told apart by their actor."""
        published = publish(
            api_base,
            compute_request,
            name="Timeline order (engagement test)",
            headers=script_headers,
        )
        pid = published["proposal_id"]

        resp = requests.post(
            f"{api_base}{comment_url(pid)}",
            json={"body": "Why not via Praha?"},
            timeout=10,
            headers=script_headers,
        )
        assert resp.status_code == 201

        resp = requests.post(
            f"{api_base}{like_url(pid)}", timeout=10, headers=script_headers
        )
        assert resp.status_code == 200

        publish(
            api_base,
            compute_request,
            name="Timeline order (overwritten)",
            mode="overwrite",
            proposal_id=pid,
            headers=script_headers,
        )

        # Force the on-load fallback to recalculate, which is the system
        # write path (test_53 covers the mechanism itself).
        with db_conn.cursor() as cur:
            cur.execute(
                "UPDATE proposals.proposals SET route_builder_version = %s "
                "WHERE proposal_id = %s",
                (_STALE_ROUTE_BUILDER_VERSION, pid),
            )
        db_conn.commit()
        resp = requests.get(f"{api_base}{PROPOSAL_URL}/{pid}", timeout=60)
        assert resp.status_code == 200

        body = _engagements(api_base, pid)
        assert _events(body) == [
            "published",
            "commented",
            "liked",
            "overwritten",
            "recalculated",
        ]

        # Timestamps are non-decreasing — the merge is ordered by time,
        # not by source.
        stamps = [event["at"] for event in body["timeline"]]
        assert stamps == sorted(stamps)

        # The version counter as it stood after each event.
        assert [event["proposal_version"] for event in body["timeline"]] == [
            1,
            1,
            1,
            2,
            3,
        ]

        by_event = {event["event"]: event for event in body["timeline"]}
        # A user overwrite carries its author...
        assert by_event["overwritten"]["actor"] == {
            "user_id": script_user_id,
            "user_name": "test_script",
        }
        # ...a system refresh has no actor at all, and says what moved.
        assert by_event["recalculated"]["actor"] is None
        assert by_event["recalculated"]["detail"] == {
            "trigger": "route_builder_version",
            "from": _STALE_ROUTE_BUILDER_VERSION,
            "to": ROUTE_BUILDER_VERSION,
        }

    def test_branch_events_land_on_both_proposals(
        self, api_base, script_headers, compute_request
    ):
        """based_on_proposal_id writes the informational branch pair
        (§4.1) — branched_from on the new proposal, branched_to on the
        one it was built from."""
        source = publish(
            api_base,
            compute_request,
            name="Branch source (engagement test)",
            headers=script_headers,
        )
        branch = publish(
            api_base,
            compute_request,
            name="Branch result (engagement test)",
            based_on_proposal_id=source["proposal_id"],
            headers=script_headers,
        )

        branch_events = _events(_engagements(api_base, branch["proposal_id"]))
        assert branch_events == ["published", "branched_from"]

        source_body = _engagements(api_base, source["proposal_id"])
        assert _events(source_body) == ["published", "branched_to"]
        branched_to = source_body["timeline"][1]
        assert branched_to["detail"] == {"source_proposal_id": branch["proposal_id"]}
