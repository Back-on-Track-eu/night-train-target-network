"""
test_51_proposal_engagement_api.py
===================================
Proposal likes and comments — POST/DELETE/GET /api/proposal/<id>/likes and
GET/POST/PATCH/DELETE /api/proposal/<id>/comments[/<cid>].

Covers:
  - 404 for an unknown proposal_id on every endpoint
  - Likes: auth required to write, idempotent like/unlike, liked_by_me is
    per-caller and False for an unauthenticated GET
  - Comments: validation (empty/oversized body), auth required to write,
    proposal_version is stamped from the target's current version,
    author-only edit/delete (403 for a different user), soft-delete
    behaviour (is_deleted + cleared body, still listed, further
    edit/delete on it is 404)

Target: the permanent seed proposal (_SEED_PROPOSAL_ID, see
test_50_proposals_api.py) rather than a freshly built route — engagement
rows don't depend on route content, and a fresh route build is expensive
(live OpenRailRouting). This is safe because proposals.likes/comments
carry no permanent seed data of their own (db/dev/seed.py seeds none), so
helpers.purge_saved_proposals clears both tables unconditionally on
teardown regardless of which proposal_id they reference.

Isolation: writes commit through the API's own connection, so the
per-test rollback fixture can't undo them (same situation as
test_50/test_60). This module's own rows are purged before and after via
the module fixture below.
"""

import pytest
import requests

from tests.helpers import comments_url, likes_url, purge_saved_proposals

# Matches test_50_proposals_api.py's constant — the permanent proposal
# seeded at DB init time (db/dev/seed.py), always present.
_SEED_PROPOSAL_ID = 1

_UNKNOWN_PROPOSAL_ID = 987654321


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


# =============================================================================
# Likes
# =============================================================================


def test_get_likes_unknown_proposal_returns_404(api_base):
    resp = requests.get(f"{api_base}{likes_url(_UNKNOWN_PROPOSAL_ID)}", timeout=10)
    assert resp.status_code == 404
    assert resp.json()["error"] == "not_found"


def test_like_requires_auth(api_base):
    resp = requests.post(f"{api_base}{likes_url(_SEED_PROPOSAL_ID)}", timeout=10)
    assert resp.status_code == 401


def test_like_unknown_proposal_returns_404(api_base, script_headers):
    resp = requests.post(
        f"{api_base}{likes_url(_UNKNOWN_PROPOSAL_ID)}",
        timeout=10,
        headers=script_headers,
    )
    assert resp.status_code == 404


def test_like_unliked_proposal_starts_at_zero(api_base, clean_engagement_per_test):
    resp = requests.get(f"{api_base}{likes_url(_SEED_PROPOSAL_ID)}", timeout=10)
    assert resp.status_code == 200
    assert resp.json() == {"count": 0, "liked_by_me": False}


def test_like_is_idempotent_and_per_caller(
    api_base, clean_engagement_per_test, script_headers, guest
):
    # First like: count 1, liked_by_me True for the liker.
    resp = requests.post(
        f"{api_base}{likes_url(_SEED_PROPOSAL_ID)}", timeout=10, headers=script_headers
    )
    assert resp.status_code == 200
    assert resp.json() == {"count": 1, "liked_by_me": True}

    # Liking again is a no-op, not a second row.
    resp = requests.post(
        f"{api_base}{likes_url(_SEED_PROPOSAL_ID)}", timeout=10, headers=script_headers
    )
    assert resp.json() == {"count": 1, "liked_by_me": True}

    # A different caller sees the same count but liked_by_me False for
    # themselves until they also like it.
    resp = requests.get(
        f"{api_base}{likes_url(_SEED_PROPOSAL_ID)}",
        timeout=10,
        headers=guest["headers"],
    )
    assert resp.json() == {"count": 1, "liked_by_me": False}

    resp = requests.post(
        f"{api_base}{likes_url(_SEED_PROPOSAL_ID)}",
        timeout=10,
        headers=guest["headers"],
    )
    assert resp.json() == {"count": 2, "liked_by_me": True}


def test_unlike_is_idempotent(api_base, clean_engagement_per_test, script_headers):
    requests.post(
        f"{api_base}{likes_url(_SEED_PROPOSAL_ID)}", timeout=10, headers=script_headers
    )

    resp = requests.delete(
        f"{api_base}{likes_url(_SEED_PROPOSAL_ID)}", timeout=10, headers=script_headers
    )
    assert resp.status_code == 200
    assert resp.json() == {"count": 0, "liked_by_me": False}

    # Unliking again (nothing left to remove) is still a clean 200.
    resp = requests.delete(
        f"{api_base}{likes_url(_SEED_PROPOSAL_ID)}", timeout=10, headers=script_headers
    )
    assert resp.status_code == 200
    assert resp.json() == {"count": 0, "liked_by_me": False}


def test_unlike_requires_auth(api_base):
    resp = requests.delete(f"{api_base}{likes_url(_SEED_PROPOSAL_ID)}", timeout=10)
    assert resp.status_code == 401


# =============================================================================
# Comments — validation, unknown proposal
# =============================================================================


def test_get_comments_unknown_proposal_returns_404(api_base):
    resp = requests.get(f"{api_base}{comments_url(_UNKNOWN_PROPOSAL_ID)}", timeout=10)
    assert resp.status_code == 404


def test_comment_requires_auth(api_base):
    resp = requests.post(
        f"{api_base}{comments_url(_SEED_PROPOSAL_ID)}", json={"body": "hi"}, timeout=10
    )
    assert resp.status_code == 401


def test_comment_rejects_empty_body(api_base, script_headers):
    resp = requests.post(
        f"{api_base}{comments_url(_SEED_PROPOSAL_ID)}",
        json={"body": "   "},
        timeout=10,
        headers=script_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "validation_error"


def test_comment_rejects_oversized_body(api_base, script_headers):
    resp = requests.post(
        f"{api_base}{comments_url(_SEED_PROPOSAL_ID)}",
        json={"body": "x" * 4001},
        timeout=10,
        headers=script_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "validation_error"


def test_comment_unknown_proposal_returns_404(api_base, script_headers):
    resp = requests.post(
        f"{api_base}{comments_url(_UNKNOWN_PROPOSAL_ID)}",
        json={"body": "hi"},
        timeout=10,
        headers=script_headers,
    )
    assert resp.status_code == 404


# =============================================================================
# Comments — full lifecycle (add, list, edit, delete, ownership)
# =============================================================================


@pytest.fixture
def posted_comment(api_base, clean_engagement_per_test, script_headers, script_user_id):
    """One fresh comment on the seed proposal, owned by test_script."""
    resp = requests.post(
        f"{api_base}{comments_url(_SEED_PROPOSAL_ID)}",
        json={"body": "  Have you compared the Basel alternative?  "},
        timeout=10,
        headers=script_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_add_comment_returns_stored_shape(posted_comment, script_user_id):
    """body is stripped server-side; proposal_version is stamped from the
    proposal's current version at the moment of commenting."""
    assert posted_comment["proposal_id"] == _SEED_PROPOSAL_ID
    assert posted_comment["proposal_version"] == 1  # seed proposal is v1
    assert posted_comment["user_id"] == script_user_id
    assert posted_comment["user_name"] == "test_script"
    assert posted_comment["body"] == "Have you compared the Basel alternative?"
    assert posted_comment["is_deleted"] is False
    assert posted_comment["created_at"] == posted_comment["updated_at"]


def test_list_comments_includes_posted_comment(api_base, posted_comment):
    resp = requests.get(f"{api_base}{comments_url(_SEED_PROPOSAL_ID)}", timeout=10)
    assert resp.status_code == 200
    body = resp.json()
    assert body["proposal_id"] == _SEED_PROPOSAL_ID
    ids = [c["comment_id"] for c in body["comments"]]
    assert posted_comment["comment_id"] in ids


def test_edit_comment_by_author_succeeds(api_base, posted_comment, script_headers):
    cid = posted_comment["comment_id"]
    resp = requests.patch(
        f"{api_base}{comments_url(_SEED_PROPOSAL_ID, cid)}",
        json={"body": "Updated: Basel is 12 min faster."},
        timeout=10,
        headers=script_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["body"] == "Updated: Basel is 12 min faster."
    assert body["updated_at"] >= posted_comment["updated_at"]


def test_edit_comment_by_other_user_is_forbidden(api_base, posted_comment, guest):
    resp = requests.patch(
        f"{api_base}{comments_url(_SEED_PROPOSAL_ID, posted_comment['comment_id'])}",
        json={"body": "hijacked"},
        timeout=10,
        headers=guest["headers"],
    )
    assert resp.status_code == 403


def test_edit_comment_unknown_id_returns_404(api_base, script_headers):
    resp = requests.patch(
        f"{api_base}{comments_url(_SEED_PROPOSAL_ID, 999999)}",
        json={"body": "hi"},
        timeout=10,
        headers=script_headers,
    )
    assert resp.status_code == 404


def test_delete_comment_by_other_user_is_forbidden(api_base, posted_comment, guest):
    resp = requests.delete(
        f"{api_base}{comments_url(_SEED_PROPOSAL_ID, posted_comment['comment_id'])}",
        timeout=10,
        headers=guest["headers"],
    )
    assert resp.status_code == 403


def test_delete_comment_by_author_soft_deletes(
    api_base, posted_comment, script_headers
):
    cid = posted_comment["comment_id"]
    resp = requests.delete(
        f"{api_base}{comments_url(_SEED_PROPOSAL_ID, cid)}",
        timeout=10,
        headers=script_headers,
    )
    assert resp.status_code == 204
    assert resp.text == ""

    # Still listed, chronological place kept, but body cleared and flagged.
    listed = requests.get(
        f"{api_base}{comments_url(_SEED_PROPOSAL_ID)}", timeout=10
    ).json()["comments"]
    entry = next(c for c in listed if c["comment_id"] == cid)
    assert entry["is_deleted"] is True
    assert entry["body"] == ""

    # A soft-deleted comment can no longer be edited or deleted.
    resp = requests.patch(
        f"{api_base}{comments_url(_SEED_PROPOSAL_ID, cid)}",
        json={"body": "resurrect me"},
        timeout=10,
        headers=script_headers,
    )
    assert resp.status_code == 404

    resp = requests.delete(
        f"{api_base}{comments_url(_SEED_PROPOSAL_ID, cid)}",
        timeout=10,
        headers=script_headers,
    )
    assert resp.status_code == 404
