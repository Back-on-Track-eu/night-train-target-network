"""
test_50_proposals_api.py
========================
Proposal save/list/load endpoints — the write path on top of everything
below it in the dependency order (routes come from the shared session
fixtures, so no extra OpenRailRouting calls happen here).

Covers:
  - POST /api/proposal: created / versioned / branched semantics, draft ID
    rewriting, GTFS decomposition, validation and domain errors
  - GET  /api/proposal/<id>: round-trip of the stored plan response, 404
  - GET/POST /api/proposals: summaries, filters (user/country/stop),
    sorting, pagination

Isolation: saves commit through the API's own connection, so the suite's
per-test rollback can't undo them. The module fixture purges saved
proposals (JSONB rows + their GTFS decomposition) before and after this
file — except the one permanent example proposal seeded at DB init time
(db/dev/seed.py, proposal_id=_SEED_PROPOSAL_ID) — and bumps the
proposal_id sequence above the placeholder IDs the session route fixtures
were planned with (100-999, see conftest.py) so a sequence-assigned ID
can never collide with a fixture's embedded one.
"""

import pytest
import requests

from tests.helpers import (
    PROPOSAL_URL,
    PROPOSALS_URL,
    save_proposal,
)

# Well above the proposal_id placeholders (100-999) the session route
# fixtures embed — see conftest.py's range-convention comment.
_SEQUENCE_FLOOR = 1000

# Matches db/dev/seed.py's _SEED_PROPOSAL_ID / seed_example_proposal() —
# a real saved proposal seeded at DB init time, permanent and outside
# this module's purge, so a full test run doesn't erase the one working
# example a person could inspect right after docker-compose up.
_SEED_PROPOSAL_ID = 1
_SEED_ROUTE_ID = f"P{_SEED_PROPOSAL_ID}_V1_R1"


def _find_prefixed_strings(obj, prefix: str, limit: int = 5) -> list[str]:
    """Recursively collect up to `limit` strings (dict keys or values)
    starting with `prefix`. Used instead of `prefix not in json.dumps(obj)`
    for large structures (like an evaluation response) — pytest's
    assertion-diff machinery is O(n^2)-ish over big text and can hang
    comparing a short prefix against a multi-KB JSON dump; a short, bounded
    match list gives the same signal without ever building that diff."""
    found: list[str] = []

    def walk(node):
        if len(found) >= limit:
            return
        if isinstance(node, str):
            if node.startswith(prefix):
                found.append(node)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            for key, value in node.items():
                if isinstance(key, str) and key.startswith(prefix):
                    found.append(f"key:{key}")
                walk(value)

    walk(obj)
    return found


def _wrap(route: dict) -> dict:
    """Minimal route_body envelope around a bare route dict, for
    tests that POST the raw body directly (error-path tests bypassing the
    save_proposal() helper's more complete wrapping)."""
    return {"route_builder_version": "test", "request": {}, "route": route}


def _purge_saved_proposals(conn) -> None:
    """Delete everything a proposal save writes in THIS module, while
    preserving the one real example proposal seeded at DB init time (see
    _SEED_PROPOSAL_ID above). Saved GTFS IDs all start with 'P'
    (P{id}_V{version}_...), the seeded GTFS demo rows don't (NJ-...) — so
    the prefix cleanly separates test data from unrelated seed data.
    '!~ ^P1_V1_R1' is a regex anchor, not a numeric comparison — it
    excludes exactly the seed's own IDs (P1_V1_R1, P1_V1_R1_D0_T1_SHAPE,
    P1_V1_R1_SVC, ...) without accidentally also excluding P100_.../
    P1000_...-prefixed rows this module creates, which share the "P1"
    substring but not the "P1_" boundary. Deleting routes cascades trips
    and stop_times; deleting services cascades calendar and
    calendar_dates."""
    cur = conn.cursor()
    cur.execute(
        f"DELETE FROM proposals.routes WHERE route_id ~ '^P' "
        f"AND route_id !~ '^{_SEED_ROUTE_ID}'"
    )
    cur.execute(
        f"DELETE FROM proposals.shapes WHERE shape_id ~ '^P' "
        f"AND shape_id !~ '^{_SEED_ROUTE_ID}'"
    )
    cur.execute(
        f"DELETE FROM proposals.services WHERE service_id ~ '^P' "
        f"AND service_id !~ '^{_SEED_ROUTE_ID}'"
    )
    cur.execute(
        "DELETE FROM proposals.proposals WHERE proposal_id != %s",
        (_SEED_PROPOSAL_ID,),
    )
    conn.commit()
    cur.close()


@pytest.fixture(scope="module", autouse=True)
def clean_proposals(db_conn):
    """Purge saved proposals before and after this module (the seeded
    example proposal, id=_SEED_PROPOSAL_ID, is preserved — see
    _purge_saved_proposals), and lift the proposal_id sequence above the
    fixture placeholder range."""
    _purge_saved_proposals(db_conn)
    cur = db_conn.cursor()
    cur.execute(
        "SELECT setval(pg_get_serial_sequence('proposals.proposals', 'proposal_id'), "
        "%s, true)",
        (_SEQUENCE_FLOOR,),
    )
    db_conn.commit()
    cur.close()
    yield
    _purge_saved_proposals(db_conn)


@pytest.fixture(scope="module")
def user_ids(db_conn):
    """(david, bjarne) user_ids resolved by email — never hard-coded."""
    cur = db_conn.cursor()
    ids = {}
    for email in ("david@backontrack.eu", "bjarne@backontrack.eu"):
        cur.execute("SELECT user_id FROM admin.users WHERE email = %s", (email,))
        row = cur.fetchone()
        assert row is not None, f"Seed user {email} missing — see db/dev/seed.py."
        ids[email] = row[0]
    cur.close()
    db_conn.rollback()
    return ids["david@backontrack.eu"], ids["bjarne@backontrack.eu"]


# =============================================================================
# POST /api/proposal — save semantics
# =============================================================================


@pytest.mark.timeout(30)
def test_save_new_proposal_created(api_base, route_berlin_dresden_wien, user_ids):
    """Saving a route with an unknown (fixture-placeholder) proposal_id
    creates a new proposal at version 1 with a sequence-assigned ID."""
    david, _ = user_ids
    body = save_proposal(
        api_base, route_berlin_dresden_wien, david, change_log="initial save"
    )

    assert body["action"] == "created"
    proposal = body["proposal"]
    assert proposal["proposal_version"] == 1
    assert proposal["is_current"] is True
    assert proposal["user_id"] == david
    assert proposal["user_name"] == "David"
    assert proposal["change_log"] == "initial save"
    assert body["route_id"] == f"P{proposal['proposal_id']}_V1_R1"
    # Sequence-assigned, never the placeholder embedded in the fixture route.
    assert proposal["proposal_id"] > _SEQUENCE_FLOOR


@pytest.mark.timeout(30)
def test_save_rewrites_all_draft_ids(api_base, route_berlin_dresden_wien, user_ids):
    """Every ID in the stored route (route_id, trip_ids, geometry refs,
    shunting/parking trip references) carries the real proposal prefix —
    no trace of the draft prefix survives."""
    david, _ = user_ids
    saved = save_proposal(api_base, route_berlin_dresden_wien, david)
    pid = saved["proposal"]["proposal_id"]

    resp = requests.get(f"{api_base}{PROPOSAL_URL}/{pid}", timeout=10)
    assert resp.status_code == 200
    route = resp.json()["route_body"]["route"]

    old_prefix = route_berlin_dresden_wien["route_id"].rsplit("R1", 1)[0]  # "P2_V1_"
    new_prefix = f"P{pid}_V1_"
    assert route["route_id"] == f"{new_prefix}R1"
    leftover = _find_prefixed_strings(route, old_prefix)
    assert not leftover, f"draft prefix survived rewrite: {leftover}"

    for pair in route["trip_pairs"]:
        for trip in (pair["outbound"], pair["return_trip"]):
            assert trip["trip_id"].startswith(new_prefix)
            for seg in trip["segments"]:
                assert seg["geometry_id"].startswith(new_prefix)
    assert all(g["id"].startswith(new_prefix) for g in route["geometries"])
    assert all(s["trip_id"].startswith(new_prefix) for s in route["shuntings"])
    assert all(
        tid.startswith(new_prefix) for p in route["parkings"] for tid in p["trip_ids"]
    )


@pytest.mark.timeout(30)
def test_save_own_proposal_creates_new_version(
    api_base, route_berlin_dresden_wien, user_ids, db_cur
):
    """Re-saving your own proposal appends version 2 and flips is_current —
    append-only, the version-1 row stays."""
    david, _ = user_ids
    first = save_proposal(api_base, route_berlin_dresden_wien, david)
    pid = first["proposal"]["proposal_id"]

    saved_route = requests.get(f"{api_base}{PROPOSAL_URL}/{pid}", timeout=10).json()[
        "route_body"
    ]["route"]
    second = save_proposal(
        api_base, saved_route, david, change_log="tweaked composition"
    )

    assert second["action"] == "versioned"
    assert second["proposal"]["proposal_id"] == pid
    assert second["proposal"]["proposal_version"] == 2
    assert second["route_id"] == f"P{pid}_V2_R1"

    db_cur.execute(
        "SELECT proposal_version, is_current FROM proposals.proposals "
        "WHERE proposal_id = %s ORDER BY proposal_version",
        (pid,),
    )
    rows = db_cur.fetchall()
    assert [(r["proposal_version"], r["is_current"]) for r in rows] == [
        (1, False),
        (2, True),
    ]


@pytest.mark.timeout(30)
def test_save_foreign_proposal_branches(api_base, route_berlin_dresden_wien, user_ids):
    """Saving someone else's proposal duplicates it under a new proposal_id
    at version 1 — the original stays untouched and current."""
    david, bjarne = user_ids
    original = save_proposal(api_base, route_berlin_dresden_wien, david)
    pid = original["proposal"]["proposal_id"]

    saved_route = requests.get(f"{api_base}{PROPOSAL_URL}/{pid}", timeout=10).json()[
        "route_body"
    ]["route"]
    branch = save_proposal(api_base, saved_route, bjarne)

    assert branch["action"] == "branched"
    assert branch["proposal"]["proposal_id"] != pid
    assert branch["proposal"]["proposal_version"] == 1
    assert branch["proposal"]["user_id"] == bjarne

    untouched = requests.get(f"{api_base}{PROPOSAL_URL}/{pid}", timeout=10).json()
    assert untouched["proposal"]["proposal_version"] == 1
    assert untouched["proposal"]["user_id"] == david


# =============================================================================
# POST /api/proposal — GTFS decomposition
# =============================================================================


@pytest.mark.timeout(30)
def test_save_writes_gtfs_decomposition(
    api_base, route_berlin_dresden_wien, user_ids, db_cur
):
    """A save decomposes the route into all GTFS tables: routes row with a
    derived long name, one trip per direction, one stop_time per stop, a
    per-trip shape whose length matches the segment physics, and an
    all-week daily calendar."""
    david, _ = user_ids
    saved = save_proposal(api_base, route_berlin_dresden_wien, david)
    route_id = saved["route_id"]

    db_cur.execute(
        "SELECT route_long_name FROM proposals.routes WHERE route_id = %s", (route_id,)
    )
    long_name = db_cur.fetchone()["route_long_name"]
    assert "Berlin" in long_name and "Wien" in long_name

    db_cur.execute(
        "SELECT trip_id, direction_id, shape_id, composition_type_id "
        "FROM proposals.trips WHERE route_id = %s ORDER BY direction_id",
        (route_id,),
    )
    trips = db_cur.fetchall()
    assert [t["direction_id"] for t in trips] == [0, 1]
    assert all(t["composition_type_id"] == "STD-7.1" for t in trips)

    for trip in trips:
        # 3-stop fixture route → 3 stop_times per direction.
        db_cur.execute(
            "SELECT COUNT(*) AS n FROM proposals.stop_times WHERE trip_id = %s",
            (trip["trip_id"],),
        )
        assert db_cur.fetchone()["n"] == 3

        db_cur.execute(
            "SELECT length_km FROM proposals.shapes WHERE shape_id = %s",
            (trip["shape_id"],),
        )
        length_km = float(db_cur.fetchone()["length_km"])
        assert length_km > 0

    # One shared all-week daily service for the version.
    db_cur.execute(
        "SELECT monday, sunday, start_date, end_date FROM proposals.calendar "
        "WHERE service_id = %s",
        (f"{route_id}_SVC",),
    )
    calendar = db_cur.fetchone()
    assert calendar["monday"] is True and calendar["sunday"] is True


@pytest.mark.timeout(30)
def test_gtfs_shape_length_matches_route_physics(
    api_base, route_berlin_dresden_wien, user_ids, db_cur
):
    """Sum of persisted shape lengths equals the route's total segment
    distance — the GTFS side and the JSONB side describe the same route."""
    david, _ = user_ids
    saved = save_proposal(api_base, route_berlin_dresden_wien, david)

    expected_km = (
        sum(
            seg["distance_m"]
            for pair in route_berlin_dresden_wien["trip_pairs"]
            for trip in (pair["outbound"], pair["return_trip"])
            for seg in trip["segments"]
        )
        / 1000.0
    )

    db_cur.execute(
        "SELECT SUM(s.length_km) AS total FROM proposals.trips t "
        "JOIN proposals.shapes s ON s.shape_id = t.shape_id "
        "WHERE t.route_id = %s",
        (saved["route_id"],),
    )
    assert float(db_cur.fetchone()["total"]) == pytest.approx(expected_km, abs=0.1)


# =============================================================================
# POST /api/proposal — evaluation snapshot
# =============================================================================


@pytest.mark.timeout(60)
def test_save_with_evaluation_stores_and_rewrites_it(api_base, eval_standard, user_ids):
    """A save that includes an evaluation stores it, rewrites its embedded
    draft IDs (the evaluation response echoes the route under
    input.route), and round-trips it via GET."""
    david, _ = user_ids
    costed_route, evaluation = eval_standard

    saved = save_proposal(api_base, costed_route, david, evaluation=evaluation)
    pid = saved["proposal"]["proposal_id"]

    body = requests.get(f"{api_base}{PROPOSAL_URL}/{pid}", timeout=10).json()
    stored_eval = body["evaluation_body"]
    assert stored_eval is not None
    assert stored_eval["route_id"] == saved["route_id"]

    old_prefix = costed_route["route_id"].rsplit("R1", 1)[0]
    leftover = _find_prefixed_strings(stored_eval, old_prefix)
    assert not leftover, f"draft prefix survived rewrite: {leftover}"
    assert stored_eval["input"]["route"]["route_id"] == saved["route_id"]


@pytest.mark.timeout(60)
def test_save_with_mismatched_evaluation_is_rejected(
    api_base, route_berlin_zuerich_wien, eval_standard, user_ids
):
    """evaluation_body.input.route must match route_body.route
    exactly (validate_route_evaluation_sync) — guards against posting an
    evaluation snapshot for the wrong route. eval_standard is built for
    route_berlin_dresden_wien, so pairing it with the (different) Zürich
    route always produces a mismatch."""
    david, _ = user_ids
    _, evaluation = eval_standard
    resp = requests.post(
        f"{api_base}{PROPOSAL_URL}",
        json={
            "user_id": david,
            "route_body": _wrap(route_berlin_zuerich_wien),
            "evaluation_body": evaluation,
        },
        timeout=10,
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "validation_error"


@pytest.mark.timeout(30)
def test_save_without_evaluation_leaves_financial_fields_null(
    api_base, route_berlin_dresden_wien, user_ids
):
    """A save with no evaluation stores evaluation_body as NULL — GET
    reflects that, and the proposal still lists fine with null financials."""
    david, _ = user_ids
    saved = save_proposal(api_base, route_berlin_dresden_wien, david)
    body = requests.get(
        f"{api_base}{PROPOSAL_URL}/{saved['proposal']['proposal_id']}", timeout=10
    ).json()
    assert body["evaluation_body"] is None


# =============================================================================
# POST /api/proposal — validation and domain errors
# =============================================================================


@pytest.mark.timeout(10)
def test_save_without_user_id_is_rejected(api_base, route_berlin_dresden_wien):
    resp = requests.post(
        f"{api_base}{PROPOSAL_URL}",
        json={"route_body": _wrap(route_berlin_dresden_wien)},
        timeout=10,
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "validation_error"


@pytest.mark.timeout(10)
def test_save_with_unknown_user_is_rejected(
    api_base, route_berlin_dresden_wien, user_ids
):
    resp = requests.post(
        f"{api_base}{PROPOSAL_URL}",
        json={
            "user_id": 999_999_999,
            "route_body": _wrap(route_berlin_dresden_wien),
        },
        timeout=10,
    )
    assert resp.status_code == 422
    assert resp.json()["error"] == "domain_error"


@pytest.mark.timeout(10)
def test_save_with_unconventional_route_id_is_rejected(
    api_base, route_berlin_dresden_wien, user_ids
):
    """A route_id outside the P{id}_V{version}_R1 convention can't be
    version-resolved and is rejected up front."""
    david, _ = user_ids
    broken = {**route_berlin_dresden_wien, "route_id": "NJ-BER-VIE"}
    resp = requests.post(
        f"{api_base}{PROPOSAL_URL}",
        json={"user_id": david, "route_body": _wrap(broken)},
        timeout=10,
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "validation_error"


# =============================================================================
# GET /api/proposal/<id>
# =============================================================================


@pytest.mark.timeout(30)
def test_get_proposal_round_trips_plan_response(
    api_base, route_berlin_dresden_wien, user_ids
):
    """GET returns the stored plan-response shape (route_builder_version /
    request / route) plus the proposal metadata block."""
    david, _ = user_ids
    saved = save_proposal(
        api_base,
        route_berlin_dresden_wien,
        david,
        route_builder_version="test-rbv",
        request={"stops": ["DE_BERLIN_HBF"]},
    )
    pid = saved["proposal"]["proposal_id"]

    body = requests.get(f"{api_base}{PROPOSAL_URL}/{pid}", timeout=10).json()
    assert body["proposal"]["proposal_id"] == pid
    assert body["route_body"]["route_builder_version"] == "test-rbv"
    assert body["route_body"]["request"] == {"stops": ["DE_BERLIN_HBF"]}
    assert body["route_body"]["route"]["route_id"] == saved["route_id"]
    # Same structure as the plan response — geometries included for the map.
    assert isinstance(body["route_body"]["route"]["geometries"], list)


@pytest.mark.timeout(10)
def test_get_unknown_proposal_returns_404(api_base):
    resp = requests.get(f"{api_base}{PROPOSAL_URL}/987654321", timeout=10)
    assert resp.status_code == 404
    assert resp.json()["error"] == "not_found"


@pytest.mark.timeout(10)
def test_seeded_example_proposal_is_queryable(api_base):
    """db/dev/seed.py's seed_example_proposal() should always have run by
    the time the API-backed docker-compose stack tests hit — this isn't a
    skip-if-absent check, it's a hard assertion that the invariant "every
    GTFS route has a real owning proposal" holds for the one seeded at DB
    init time (id=_SEED_PROPOSAL_ID, Berlin Hbf -> Dresden Hbf -> Wien Hbf,
    3 stops, both directions, no evaluation)."""
    body = requests.get(
        f"{api_base}{PROPOSAL_URL}/{_SEED_PROPOSAL_ID}", timeout=10
    ).json()
    assert body["proposal"]["proposal_id"] == _SEED_PROPOSAL_ID
    assert body["proposal"]["user_name"] == "David"
    route = body["route_body"]["route"]
    assert route["route_id"] == _SEED_ROUTE_ID
    assert len(route["trip_pairs"]) == 1
    pair = route["trip_pairs"][0]
    stop_ids = [seg["from_stop"]["stop_id"] for seg in pair["outbound"]["segments"]] + [
        pair["outbound"]["segments"][-1]["to_stop"]["stop_id"]
    ]
    assert stop_ids == ["DE_BERLIN_HBF", "DE_DRESDEN_HBF", "AT_WIEN_HBF"]
    assert body["evaluation_body"] is None  # seeded without demand/evaluation


# =============================================================================
# GET/POST /api/proposals — listing, filters, sorting, pagination
# =============================================================================


@pytest.fixture(scope="module")
def listed_proposals(
    api_base,
    route_berlin_wien,
    route_berlin_zuerich_wien,
    user_ids,
    db_conn,
):
    """Two proposals with distinct footprints for filter tests: the 2-stop
    DE/AT route saved twice by David (so only its version 2 may appear in
    lists), and the CH-touching route saved by Bjarne. Starts from a clean
    slate so list totals are exact."""
    _purge_saved_proposals(db_conn)
    david, bjarne = user_ids

    first = save_proposal(api_base, route_berlin_wien, david)
    saved_route = requests.get(
        f"{api_base}{PROPOSAL_URL}/{first['proposal']['proposal_id']}", timeout=10
    ).json()["route_body"]["route"]
    berlin_wien = save_proposal(api_base, saved_route, david)

    zuerich = save_proposal(api_base, route_berlin_zuerich_wien, bjarne)
    return {"berlin_wien": berlin_wien, "zuerich": zuerich}


@pytest.mark.timeout(30)
def test_list_returns_current_summaries(api_base, listed_proposals, user_ids):
    """GET /api/proposals lists exactly one entry per proposal (current
    version only) with all summary fields populated. Total is 3, not 2 —
    the two proposals this fixture creates plus the permanent seeded
    example proposal (id=_SEED_PROPOSAL_ID, never purged by this module)."""
    body = requests.get(f"{api_base}{PROPOSALS_URL}", timeout=10).json()
    assert body["total"] == 3

    by_id = {p["proposal_id"]: p for p in body["proposals"]}
    berlin_wien = by_id[listed_proposals["berlin_wien"]["proposal"]["proposal_id"]]
    assert berlin_wien["proposal_version"] == 2  # v1 must not be listed
    assert berlin_wien["user_name"] == "David"
    assert "Berlin" in berlin_wien["name"] and "Wien" in berlin_wien["name"]
    assert berlin_wien["total_distance_km"] > 0
    assert berlin_wien["total_time_h"] > berlin_wien["total_driving_time_h"] > 0
    assert set(berlin_wien["countries"]) >= {"DE", "AT"}
    assert {"stop_id": "DE_BERLIN_HBF", "stop_name": "Berlin Hbf"} in berlin_wien[
        "stops"
    ] or any(s["stop_id"] == "DE_BERLIN_HBF" for s in berlin_wien["stops"])


@pytest.mark.timeout(30)
def test_filtered_list_by_country_stop_and_user(api_base, listed_proposals, user_ids):
    david, bjarne = user_ids
    zuerich_pid = listed_proposals["zuerich"]["proposal"]["proposal_id"]

    def filtered(filter_body):
        resp = requests.post(
            f"{api_base}{PROPOSALS_URL}", json={"filter": filter_body}, timeout=10
        )
        assert resp.status_code == 200
        return resp.json()

    # Country: only the Zürich route touches CH.
    body = filtered({"countries": ["CH"]})
    assert body["total"] == 1
    assert body["proposals"][0]["proposal_id"] == zuerich_pid

    # Stop: only the Zürich route serves Zürich HB.
    body = filtered({"stop_ids": ["CH_ZUERICH_HB"]})
    assert body["total"] == 1
    assert body["proposals"][0]["proposal_id"] == zuerich_pid

    # User: David owns the seeded example proposal plus his own
    # berlin_wien save — two current proposals, not one.
    body = filtered({"user_ids": [david]})
    assert body["total"] == 2
    assert all(p["user_id"] == david for p in body["proposals"])


@pytest.mark.timeout(30)
def test_list_sorting_and_pagination(api_base, listed_proposals):
    """Distance sort orders the short DE/AT route before the longer Zürich
    detour; limit/offset paginate while total stays the filtered count."""
    resp = requests.post(
        f"{api_base}{PROPOSALS_URL}",
        json={"sort": [{"by": "total_distance_km", "dir": "asc"}]},
        timeout=10,
    )
    distances = [p["total_distance_km"] for p in resp.json()["proposals"]]
    assert distances == sorted(distances)

    resp = requests.post(
        f"{api_base}{PROPOSALS_URL}",
        json={"sort": [{"by": "total_distance_km", "dir": "asc"}], "limit": 1},
        timeout=10,
    )
    body = resp.json()
    assert body["total"] == 3  # 2 from this fixture + the permanent seed proposal
    assert len(body["proposals"]) == 1
    assert body["proposals"][0]["total_distance_km"] == min(distances)


@pytest.mark.timeout(30)
def test_list_sort_by_margin_is_null_safe(api_base, listed_proposals):
    """Neither proposal this fixture creates was saved with an evaluation,
    and neither is the permanent seed proposal — sorting by a financial
    key must not raise on the resulting null margin_eur values, and every
    entry should report null financials."""
    resp = requests.post(
        f"{api_base}{PROPOSALS_URL}",
        json={"sort": [{"by": "margin_eur", "dir": "desc"}]},
        timeout=10,
    )
    assert resp.status_code == 200
    proposals = resp.json()["proposals"]
    assert len(proposals) == 3
    assert all(p["margin_eur"] is None for p in proposals)


@pytest.mark.timeout(10)
def test_list_rejects_unknown_sort_key(api_base):
    resp = requests.post(
        f"{api_base}{PROPOSALS_URL}",
        json={"sort": [{"by": "unknown_field"}]},
        timeout=10,
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "validation_error"