"""
test_60_feedback_api.py
========================
Feedback endpoints — POST /api/feedback and GET /api/feedback/categories.

Covers:
  - Validation errors (missing identity, missing required fields, bad email)
  - Anonymous submission (email-identified) and logged-in submission
    (user_id-identified), including the domain_error for an unknown user_id
  - email_sent is always a bool and never blocks storage — whether SMTP
    is configured varies by environment (see adapters/mailer.py), so
    tests check email_sent/notified_at agree with each other rather than
    assuming a fixed value
  - GET /api/feedback/categories: static categories present, and the
    Infrastructure/Compositions sub_categories lists are non-empty and
    match known TrackInfrastructures/StopInfrastructures/compositions
    fields

Isolation: inserts commit through the API's own connection, so the
per-test rollback fixture can't undo them (same situation as
test_50_proposals_api.py). This module's own rows are tagged with a
_TEST_SUBJECT_PREFIX and purged before and after the module.
"""

import pytest
import requests

from tests.helpers import FEEDBACK_CATEGORIES_URL, FEEDBACK_URL

_TEST_SUBJECT_PREFIX = "TEST_FEEDBACK_60_"


def _purge_test_feedback(db_cur, db_conn):
    db_cur.execute(
        "DELETE FROM admin.feedback WHERE subject LIKE %s",
        (f"{_TEST_SUBJECT_PREFIX}%",),
    )
    db_conn.commit()


def _seeded_user_id(db_cur) -> int:
    """user_id of any seeded admin.users row (David/Bjarne — see
    db/dev/seed.py:USERS) — fetched rather than hardcoded so a reseed with
    different insert order can't silently break this file."""
    db_cur.execute("SELECT user_id FROM admin.users ORDER BY user_id LIMIT 1")
    row = db_cur.fetchone()
    assert row is not None, "No seeded admin.users row — seed data missing."
    return row["user_id"]


@pytest.fixture(scope="module", autouse=True)
def _clean_test_feedback(db_cur, db_conn):
    _purge_test_feedback(db_cur, db_conn)
    yield
    _purge_test_feedback(db_cur, db_conn)


# =============================================================================
# POST /api/feedback — validation
# =============================================================================


def test_feedback_requires_identity(api_base):
    """Neither user_id nor email → 400 validation_error."""
    body = {
        "subject": f"{_TEST_SUBJECT_PREFIX}no_identity",
        "category": "Bug report",
        "sub_category": "General",
        "message": "Missing identity.",
    }
    resp = requests.post(f"{api_base}{FEEDBACK_URL}", json=body, timeout=15)
    assert resp.status_code == 400
    data = resp.json()
    assert data["error"] == "validation_error"
    assert any("user_id" in d or "email" in d for d in data["details"])


def test_feedback_rejects_invalid_email(api_base):
    body = {
        "email": "not-an-email",
        "subject": f"{_TEST_SUBJECT_PREFIX}bad_email",
        "category": "Bug report",
        "sub_category": "General",
        "message": "Invalid email format.",
    }
    resp = requests.post(f"{api_base}{FEEDBACK_URL}", json=body, timeout=15)
    assert resp.status_code == 400
    assert any("email" in d for d in resp.json()["details"])


def test_feedback_requires_subject_category_message(api_base):
    body = {"email": "someone@example.com"}
    resp = requests.post(f"{api_base}{FEEDBACK_URL}", json=body, timeout=15)
    assert resp.status_code == 400
    details = " ".join(resp.json()["details"])
    for field in ("subject", "category", "sub_category", "message"):
        assert field in details


def test_feedback_unknown_user_id_is_domain_error(api_base):
    body = {
        "user_id": 999_999_999,
        "subject": f"{_TEST_SUBJECT_PREFIX}unknown_user",
        "category": "Bug report",
        "sub_category": "General",
        "message": "This user_id should not exist.",
    }
    resp = requests.post(f"{api_base}{FEEDBACK_URL}", json=body, timeout=15)
    assert resp.status_code == 422
    assert resp.json()["error"] == "domain_error"


# =============================================================================
# POST /api/feedback — success paths
# =============================================================================


def test_feedback_anonymous_submission_is_stored(api_base, db_cur):
    body = {
        "email": "anonymous.tester@example.com",
        "subject": f"{_TEST_SUBJECT_PREFIX}anonymous",
        "category": "Infrastructure",
        "sub_category": "tac_eur_train_km",
        "message": "The DE TAC rate looks out of date.",
    }
    resp = requests.post(f"{api_base}{FEEDBACK_URL}", json=body, timeout=15)
    assert resp.status_code == 201
    data = resp.json()
    assert isinstance(data["feedback_id"], int)
    assert isinstance(data["email_sent"], bool)
    assert data["created_at"]

    db_cur.execute(
        "SELECT user_id, email, category, sub_category, subject, notified_at "
        "FROM admin.feedback WHERE feedback_id = %s",
        (data["feedback_id"],),
    )
    row = db_cur.fetchone()
    assert row is not None
    assert row["user_id"] is None
    assert row["email"] == body["email"]
    assert row["category"] == body["category"]
    assert row["sub_category"] == body["sub_category"]
    # Whether SMTP is configured varies by environment (see
    # adapters/mailer.py) — the row is stored either way, and the two
    # fields must agree with each other rather than either being pinned
    # to a fixed value.
    if data["email_sent"]:
        assert row["notified_at"] is not None
    else:
        assert row["notified_at"] is None


def test_feedback_logged_in_submission_is_stored(api_base, db_cur):
    user_id = _seeded_user_id(db_cur)
    body = {
        "user_id": user_id,
        "subject": f"{_TEST_SUBJECT_PREFIX}logged_in",
        "category": "Feature request",
        "sub_category": "Export to CSV",
        "message": "Would love a CSV export of proposal summaries.",
    }
    resp = requests.post(f"{api_base}{FEEDBACK_URL}", json=body, timeout=15)
    assert resp.status_code == 201
    data = resp.json()

    db_cur.execute(
        "SELECT user_id, email FROM admin.feedback WHERE feedback_id = %s",
        (data["feedback_id"],),
    )
    row = db_cur.fetchone()
    assert row["user_id"] == user_id
    # email column stays NULL for a logged-in submitter — their address is
    # looked up from admin.users instead (see create_admin_schema.sql).
    assert row["email"] is None


# =============================================================================
# GET /api/feedback/categories
# =============================================================================


def test_feedback_categories_lists_all_categories(api_base):
    resp = requests.get(f"{api_base}{FEEDBACK_CATEGORIES_URL}", timeout=15)
    assert resp.status_code == 200
    categories = {c["category"] for c in resp.json()["categories"]}
    assert categories == {
        "Infrastructure",
        "Compositions",
        "Evaluation — calculation method",
        "Evaluation — results / view",
        "Route or timetable",
        "General functionality",
        "Bug report",
        "Feature request",
        "Other",
    }


def _sub_categories_for(payload: dict, category: str) -> list[dict]:
    return next(
        c["sub_categories"] for c in payload["categories"] if c["category"] == category
    )


def test_feedback_categories_infrastructure_is_dynamic(api_base):
    resp = requests.get(f"{api_base}{FEEDBACK_CATEGORIES_URL}", timeout=15)
    assert resp.status_code == 200
    entries = _sub_categories_for(resp.json(), "Infrastructure")
    parameters = {e["parameter"] for e in entries}
    groups = {e["group"] for e in entries}
    # Spot-check one field from each source collection rather than the
    # full set — the exact list is expected to grow as parameters are
    # added, so pinning the whole thing here would be brittle.
    assert "tac_eur_train_km" in parameters
    assert "stop_charge_eur" in parameters
    assert groups == {"TrackInfrastructures", "StopInfrastructures"}


def test_feedback_categories_compositions_is_dynamic(api_base):
    resp = requests.get(f"{api_base}{FEEDBACK_CATEGORIES_URL}", timeout=15)
    assert resp.status_code == 200
    entries = _sub_categories_for(resp.json(), "Compositions")
    assert entries  # non-empty
    assert all(e["group"] == "Compositions" for e in entries)


def test_feedback_categories_calc_method_is_dynamic(api_base):
    resp = requests.get(f"{api_base}{FEEDBACK_CATEGORIES_URL}", timeout=15)
    assert resp.status_code == 200
    entries = _sub_categories_for(resp.json(), "Evaluation — calculation method")
    parameters = {e["parameter"] for e in entries}
    groups = {e["group"] for e in entries}
    # Spot-check one leaf per top-level branch of the Breakdown tree
    # (models/evaluation/views.py) rather than pinning the full set.
    assert "cost.operator.variable.driver_eur" in parameters
    assert "cost.infrastructure.tac_eur" in parameters
    assert "revenue.ticket_revenue_eur" in parameters
    assert "margin.ebit_margin_eur" in parameters
    assert groups == {"cost", "revenue", "margin"}


def test_feedback_categories_eval_view_is_dynamic(api_base):
    resp = requests.get(f"{api_base}{FEEDBACK_CATEGORIES_URL}", timeout=15)
    assert resp.status_code == 200
    entries = _sub_categories_for(resp.json(), "Evaluation — results / view")
    parameters = {e["parameter"] for e in entries}
    # Matches evaluation_serialize.py's five views exactly — this category
    # is meant to enumerate them completely, unlike the open-ended lists
    # above, so pinning the full set here is appropriate.
    assert parameters == {
        "route",
        "per_trip_pair",
        "per_trip_pair_per_country",
        "per_trip_pair_per_od",
        "per_trip_per_stop",
    }


def test_feedback_categories_static_lists_present(api_base):
    resp = requests.get(f"{api_base}{FEEDBACK_CATEGORIES_URL}", timeout=15)
    assert resp.status_code == 200
    payload = resp.json()
    assert _sub_categories_for(payload, "Route or timetable")
    assert _sub_categories_for(payload, "General functionality")
    for category in ("Bug report", "Feature request", "Other"):
        assert _sub_categories_for(payload, category) == []
