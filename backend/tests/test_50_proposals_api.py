"""
test_50_proposals_api.py
========================
Persist-on-calc semantics and the remaining proposals read endpoints — the
write path is now inside the pipelines themselves (POST /api/proposal is
gone, see api/route.py: _persist_plan and api/evaluation.py:
_persist_evaluation).

Covers:
  - POST /api/route/plan persistence: created / unchanged (setup dedupe) /
    versioned / branched, draft ID rewriting, GTFS decomposition,
    tokenless compute-only
  - POST /api/evaluation/calc persistence: filled (in-place on the version
    it was computed for) / unchanged / versioned on scenario change /
    branched for non-owners, and the compute-only outcomes
    (unauthenticated, unpersisted_route, historical_version,
    route_mismatch)
  - GET  /api/proposal/<id>: round-trip of the stored plan response, 404
  - GET/POST /api/proposals: summaries, filters (user/country/stop),
    sorting, pagination

Identities: the suite persists as the seeded 'test_script' user
(conftest.py: script_headers); guest sessions from POST /api/auth/guest
supply the second, foreign owner where branching semantics need one.

Isolation & ordering: persistence commits through the API's own
connection, so the suite's per-test rollback can't undo it. The module
fixture purges persisted proposals before and after this file — except
the permanent example proposal seeded at DB init time (db/dev/seed.py,
proposal_id=_SEED_PROPOSAL_ID). The session route fixtures are tokenless
and therefore never persisted here. Tests WITHIN a module-fixture group
below build on each other's version history in definition order (e.g.
"unchanged" runs before the setup change creates version 2) — documented
per group, don't reorder or -k-split them.
"""

import pytest
import requests

from tests.helpers import (
    PROPOSAL_URL,
    PROPOSALS_URL,
    ROUTE_URL,
    evaluate,
    inject_demand,
    purge_saved_proposals,
)

# Matches db/dev/seed.py's _SEED_PROPOSAL_ID / seed_example_proposal() —
# a real persisted proposal seeded at DB init time, permanent and outside
# this module's purge, so a full test run doesn't erase the one working
# example a person could inspect right after docker-compose up.
_SEED_PROPOSAL_ID = 1
_SEED_ROUTE_ID = f"P{_SEED_PROPOSAL_ID}_V1_R1"

# The cheapest corridor the seed data supports — every fresh authenticated
# plan in this file uses it to keep OpenRailRouting time bounded.
_STOPS = ["DE_BERLIN_HBF", "AT_WIEN_HBF"]
_COMPOSITION = "STD-7.1"
_OTHER_COMPOSITION = "STD-6.1"  # setup change for the versioned/branched paths


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


def _plan(api_base, headers, **extra) -> dict:
    """POST /api/route/plan on the cheap 2-stop corridor and return the FULL
    response (persist-on-calc needs the envelope + proposal block, not just
    the route dict tests/helpers.build_route returns)."""
    body = {
        "stops": _STOPS,
        "composition_id": _COMPOSITION,
        "auto_stop_addition": "off",
        **extra,
    }
    resp = requests.post(
        f"{api_base}{ROUTE_URL}", json=body, timeout=90, headers=headers
    )
    assert resp.status_code == 200, f"route/plan failed: {resp.text[:300]}"
    return resp.json()


@pytest.fixture(scope="module", autouse=True)
def clean_proposals(db_conn, script_headers):
    """Purge persisted proposals before and after this module (the seeded
    example proposal is preserved — see purge_saved_proposals). Depends on
    script_headers so the session-level teardown purge there runs strictly
    after this module's own."""
    purge_saved_proposals(db_conn)
    yield
    purge_saved_proposals(db_conn)


@pytest.fixture(scope="module")
def guest(api_base):
    """A guest session — the foreign owner for branch semantics.
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


# =============================================================================
# POST /api/route/plan — persistence semantics
# (tests share `planned` and build on each other in definition order)
# =============================================================================


@pytest.fixture(scope="module")
def planned(api_base, script_headers, clean_proposals):
    """One fresh authenticated plan — the proposal the plan-side tests
    version, branch, and dedupe against."""
    return _plan(api_base, script_headers)


@pytest.mark.timeout(120)
def test_plan_persists_created(planned, script_user_id):
    """An authenticated plan without a proposal_id persists itself:
    action 'created', version 1, owned by the caller, route_id final."""
    block = planned["proposal"]
    assert block["persisted"] is True
    assert block["action"] == "created"
    assert block["proposal_version"] == 1
    assert block["user_id"] == script_user_id
    pid = block["proposal_id"]
    assert planned["route"]["route_id"] == f"P{pid}_V1_R1"


@pytest.mark.timeout(30)
def test_plan_response_matches_stored_body(api_base, planned):
    """The response IS the stored route_body (plus the proposal block): no
    draft prefix survives anywhere, and GET /api/proposal/<id> round-trips
    the envelope byte-for-byte."""
    pid = planned["proposal"]["proposal_id"]

    # No draft placeholder (P1xxxxxxxxx_) anywhere in the response.
    leftovers = [
        s
        for s in _find_prefixed_strings(planned["route"], "P1", limit=50)
        if not s.replace("key:", "").startswith(f"P{pid}_")
    ]
    assert not leftovers, f"draft prefix survived rewrite: {leftovers[:5]}"

    body = requests.get(f"{api_base}{PROPOSAL_URL}/{pid}", timeout=10).json()
    stored = body["route_body"]
    assert stored == {k: v for k, v in planned.items() if k != "proposal"}
    assert body["proposal"]["proposal_id"] == pid
    assert body["evaluation_body"] is None  # plan persists the route only


@pytest.mark.timeout(30)
def test_plan_writes_gtfs_decomposition(planned, db_cur):
    """The persisted version carries its GTFS decomposition: one route, a
    service with a daily calendar, both trips with ordered stop_times."""
    route_id = planned["route"]["route_id"]

    db_cur.execute(
        "SELECT trip_id FROM proposals.trips WHERE route_id = %s", (route_id,)
    )
    trip_ids = {r["trip_id"] for r in db_cur.fetchall()}
    assert len(trip_ids) == 2  # outbound + return

    db_cur.execute(
        "SELECT COUNT(*) AS n FROM proposals.stop_times WHERE trip_id = ANY(%s)",
        (list(trip_ids),),
    )
    assert db_cur.fetchone()["n"] == 2 * len(_STOPS)

    db_cur.execute(
        "SELECT monday, sunday FROM proposals.calendar WHERE service_id = %s",
        (f"{route_id}_SVC",),
    )
    cal = db_cur.fetchone()
    assert cal is not None and cal["monday"] and cal["sunday"]


@pytest.mark.timeout(120)
def test_tokenless_plan_computes_only(api_base, db_cur):
    """No token → the old contract: draft placeholder IDs, nothing written,
    proposal block says so."""
    payload = _plan(api_base, headers=None)
    assert payload["proposal"] == {"persisted": False, "action": "unauthenticated"}
    draft_pid = int(payload["route"]["route_id"].split("_")[0][1:])
    assert draft_pid > 1_000_000_000

    db_cur.execute(
        "SELECT 1 FROM proposals.proposals WHERE proposal_id = %s", (draft_pid,)
    )
    assert db_cur.fetchone() is None


@pytest.mark.timeout(120)
def test_replan_identical_setup_is_unchanged(api_base, script_headers, planned, db_cur):
    """Replanning an existing proposal with an identical resolved setup
    writes nothing — the response references the stored current version."""
    pid = planned["proposal"]["proposal_id"]
    payload = _plan(api_base, script_headers, proposal_id=pid)

    block = payload["proposal"]
    assert block["persisted"] is False
    assert block["action"] == "unchanged"
    assert block["proposal_id"] == pid
    assert block["proposal_version"] == 1
    assert payload["route"]["route_id"] == f"P{pid}_V1_R1"
    assert payload["request"]["proposal_id"] == pid

    db_cur.execute(
        "SELECT COUNT(*) AS n FROM proposals.proposals WHERE proposal_id = %s", (pid,)
    )
    assert db_cur.fetchone()["n"] == 1  # still only version 1


@pytest.mark.timeout(120)
def test_replan_changed_setup_creates_new_version(
    api_base, script_headers, planned, db_cur
):
    """A result-touching setup change (different composition) by the owner
    appends version 2 and flips is_current — append-only, version 1 stays."""
    pid = planned["proposal"]["proposal_id"]
    payload = _plan(
        api_base, script_headers, proposal_id=pid, composition_id=_OTHER_COMPOSITION
    )

    block = payload["proposal"]
    assert block["persisted"] is True
    assert block["action"] == "versioned"
    assert block["proposal_id"] == pid
    assert block["proposal_version"] == 2
    assert payload["route"]["route_id"] == f"P{pid}_V2_R1"

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


@pytest.mark.timeout(120)
def test_replan_foreign_identical_setup_is_unchanged(api_base, planned, guest):
    """The dedupe outranks ownership: a foreign caller replanning the
    current setup (version 2's composition, after the test above) gets the
    stored version back, no branch."""
    pid = planned["proposal"]["proposal_id"]
    payload = _plan(
        api_base,
        guest["headers"],
        proposal_id=pid,
        composition_id=_OTHER_COMPOSITION,
    )
    assert payload["proposal"]["action"] == "unchanged"
    assert payload["proposal"]["proposal_version"] == 2


@pytest.mark.timeout(120)
def test_replan_foreign_changed_setup_branches(api_base, planned, guest, db_cur):
    """A setup change by a non-owner duplicates under a new proposal_id
    owned by the caller — the original proposal is untouched."""
    pid = planned["proposal"]["proposal_id"]
    payload = _plan(api_base, guest["headers"], proposal_id=pid)  # back to STD-7.1

    block = payload["proposal"]
    assert block["persisted"] is True
    assert block["action"] == "branched"
    assert block["proposal_id"] != pid
    assert block["proposal_version"] == 1
    assert block["user_id"] == guest["user_id"]

    db_cur.execute(
        "SELECT MAX(proposal_version) AS v FROM proposals.proposals "
        "WHERE proposal_id = %s",
        (pid,),
    )
    assert db_cur.fetchone()["v"] == 2  # original unchanged


# =============================================================================
# POST /api/evaluation/calc — persistence semantics
# (tests share `planned_eval` and build on each other in definition order)
# =============================================================================


@pytest.fixture(scope="module")
def planned_eval(api_base, script_headers, clean_proposals):
    """A second fresh authenticated plan, kept separate from `planned` so
    the eval-side history isn't entangled with the plan-side versioning
    tests above."""
    return _plan(api_base, script_headers)


@pytest.mark.timeout(120)
def test_eval_fills_own_version_in_place(
    api_base, script_headers, planned_eval, db_cur
):
    """Evaluating a persisted route fills that version's evaluation_body in
    place — same version, no new row, response IDs unchanged."""
    pid = planned_eval["proposal"]["proposal_id"]
    result = evaluate(api_base, planned_eval["route"], headers=script_headers)

    block = result["proposal"]
    assert block["persisted"] is True
    assert block["action"] == "filled"
    assert block["proposal_id"] == pid
    assert block["proposal_version"] == 1
    assert result["route_id"] == f"P{pid}_V1_R1"
    assert result["scenario_id"] == planned_eval["route"]["scenario_id"]

    db_cur.execute(
        "SELECT COUNT(*) AS n, "
        "       BOOL_OR(evaluation_body IS NOT NULL) AS has_eval "
        "FROM proposals.proposals WHERE proposal_id = %s",
        (pid,),
    )
    row = db_cur.fetchone()
    assert row["has_eval"] and row["n"] == 1  # filled in place, no new row


@pytest.mark.timeout(60)
def test_eval_identical_inputs_is_unchanged(api_base, script_headers, planned_eval):
    """Re-evaluating under identical inputs (same route incl. demand, same
    resolved scenario, same calc version) recomputes but writes nothing."""
    result = evaluate(api_base, planned_eval["route"], headers=script_headers)
    block = result["proposal"]
    assert block["persisted"] is False
    assert block["action"] == "unchanged"
    assert block["proposal_version"] == 1


@pytest.mark.timeout(60)
def test_eval_scenario_override_creates_new_version(
    api_base, script_headers, planned_eval, historical_scenario, db_cur
):
    """A scenario override is a result-touching input change: a new version
    is appended carrying the unchanged route_body and the new evaluation.
    The response's IDs already reference the new version."""
    pid = planned_eval["proposal"]["proposal_id"]
    scenario_id = historical_scenario["scenario_id"]
    result = evaluate(
        api_base, planned_eval["route"], scenario_id=scenario_id, headers=script_headers
    )

    block = result["proposal"]
    assert block["persisted"] is True
    assert block["action"] == "versioned"
    assert block["proposal_version"] == 2
    assert result["route_id"] == f"P{pid}_V2_R1"
    assert result["scenario_id"] == scenario_id

    # Version 2's route_body is version 1's route carried over (only the
    # IDs are rewritten) — same corridor, same physics.
    db_cur.execute(
        "SELECT route_body FROM proposals.proposals "
        "WHERE proposal_id = %s AND proposal_version = 2",
        (pid,),
    )
    v2_route = db_cur.fetchone()["route_body"]["route"]
    assert v2_route["route_id"] == f"P{pid}_V2_R1"
    v1_seg = planned_eval["route"]["trip_pairs"][0]["outbound"]["segments"]
    v2_seg = v2_route["trip_pairs"][0]["outbound"]["segments"]
    assert [s["distance_m"] for s in v2_seg] == [s["distance_m"] for s in v1_seg]


@pytest.mark.timeout(60)
def test_eval_of_historical_version_computes_only(
    api_base, script_headers, planned_eval
):
    """After the scenario override advanced the proposal to version 2,
    evaluating the version-1 route again is answered but never mutates
    history."""
    result = evaluate(api_base, planned_eval["route"], headers=script_headers)
    block = result["proposal"]
    assert block["persisted"] is False
    assert block["action"] == "historical_version"
    assert block["proposal_version"] == 1


@pytest.mark.timeout(60)
def test_eval_of_unpersisted_route_computes_only(
    api_base, script_headers, route_berlin_wien
):
    """The session fixtures are tokenless drafts — evaluating one is
    answered but has nowhere to persist."""
    result = evaluate(api_base, route_berlin_wien, headers=script_headers)
    assert result["proposal"] == {"persisted": False, "action": "unpersisted_route"}


@pytest.mark.timeout(60)
def test_eval_of_edited_route_computes_only(api_base, script_headers, planned_eval):
    """A route that no longer matches its stored version (here: replaced
    demand) is answered but not stored — hand-edited JSON never overwrites
    a persisted version."""
    pid = planned_eval["proposal"]["proposal_id"]
    current = requests.get(f"{api_base}{PROPOSAL_URL}/{pid}", timeout=10).json()
    edited = inject_demand(current["route_body"]["route"], [])  # demand wiped
    result = evaluate(api_base, edited, headers=script_headers)
    block = result["proposal"]
    assert block["persisted"] is False
    assert block["action"] == "route_mismatch"


@pytest.mark.timeout(60)
def test_eval_tokenless_computes_only(api_base, planned_eval):
    result = evaluate(api_base, planned_eval["route"])
    assert result["proposal"] == {"persisted": False, "action": "unauthenticated"}


@pytest.mark.timeout(60)
def test_eval_by_non_owner_branches(api_base, guest, db_cur):
    """A non-owner evaluating a persisted route they don't own branches —
    exercised against the permanent seed proposal (no evaluation, owned by
    the seed user), so no extra route build is needed."""
    seed_route = requests.get(
        f"{api_base}{PROPOSAL_URL}/{_SEED_PROPOSAL_ID}", timeout=10
    ).json()["route_body"]["route"]
    result = evaluate(api_base, seed_route, headers=guest["headers"], timeout=90)

    block = result["proposal"]
    assert block["persisted"] is True
    assert block["action"] == "branched"
    assert block["proposal_id"] != _SEED_PROPOSAL_ID

    db_cur.execute(
        "SELECT user_id, evaluation_body IS NOT NULL AS has_eval "
        "FROM proposals.proposals WHERE proposal_id = %s",
        (block["proposal_id"],),
    )
    row = db_cur.fetchone()
    assert row["user_id"] == guest["user_id"] and row["has_eval"]

    # The seed proposal itself is untouched.
    db_cur.execute(
        "SELECT evaluation_body IS NULL AS still_empty FROM proposals.proposals "
        "WHERE proposal_id = %s",
        (_SEED_PROPOSAL_ID,),
    )
    assert db_cur.fetchone()["still_empty"]


# =============================================================================
# GET /api/proposal/<id>
# =============================================================================


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
def listed_proposals(api_base, script_headers, guest, db_conn):
    """Two proposals with distinct footprints for filter tests: the 2-stop
    DE/AT corridor persisted twice by test_script (a composition change
    appends version 2, so only that version may appear in lists), and a
    CH-touching corridor persisted by a guest. Starts from a clean slate so
    list totals are exact (three with the permanent seed proposal)."""
    purge_saved_proposals(db_conn)

    first = _plan(api_base, script_headers)
    pid = first["proposal"]["proposal_id"]
    berlin_wien = _plan(
        api_base, script_headers, proposal_id=pid, composition_id=_OTHER_COMPOSITION
    )

    zuerich_body = {
        "stops": ["DE_BERLIN_HBF", "CH_ZUERICH_HB", "AT_WIEN_HBF"],
        "composition_id": _COMPOSITION,
        "auto_stop_addition": "off",
    }
    resp = requests.post(
        f"{api_base}{ROUTE_URL}",
        json=zuerich_body,
        timeout=120,
        headers=guest["headers"],
    )
    assert resp.status_code == 200, f"zuerich plan failed: {resp.text[:300]}"
    return {"berlin_wien": berlin_wien, "zuerich": resp.json()}


@pytest.mark.timeout(300)
def test_list_returns_current_summaries(api_base, listed_proposals, script_user_id):
    """GET /api/proposals lists exactly one entry per proposal (current
    version only) with all summary fields populated. Total is 3, not 2 —
    the two proposals this fixture creates plus the permanent seeded
    example proposal (id=_SEED_PROPOSAL_ID, never purged by this module)."""
    body = requests.get(f"{api_base}{PROPOSALS_URL}", timeout=10).json()
    assert body["total"] == 3

    by_id = {p["proposal_id"]: p for p in body["proposals"]}
    berlin_wien = by_id[listed_proposals["berlin_wien"]["proposal"]["proposal_id"]]
    assert berlin_wien["proposal_version"] == 2  # v1 must not be listed
    assert berlin_wien["user_id"] == script_user_id
    assert berlin_wien["user_name"] == "test_script"
    assert "Berlin" in berlin_wien["name"] and "Wien" in berlin_wien["name"]
    assert berlin_wien["total_distance_km"] > 0
    assert berlin_wien["total_time_h"] > berlin_wien["total_driving_time_h"] > 0
    assert set(berlin_wien["countries"]) >= {"DE", "AT"}
    assert any(s["stop_id"] == "DE_BERLIN_HBF" for s in berlin_wien["stops"])


@pytest.mark.timeout(30)
def test_filtered_list_by_country_stop_and_user(
    api_base, listed_proposals, script_user_id, guest
):
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

    # User: test_script owns exactly its berlin_wien proposal (the seed
    # proposal belongs to the seed user, the Zürich one to the guest).
    body = filtered({"user_ids": [script_user_id]})
    assert body["total"] == 1
    assert body["proposals"][0]["user_id"] == script_user_id

    body = filtered({"user_ids": [guest["user_id"]]})
    assert body["total"] == 1
    assert body["proposals"][0]["proposal_id"] == zuerich_pid


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
    """Neither proposal this fixture creates carries an evaluation (plans
    persist the route only), and neither does the permanent seed proposal —
    sorting by a financial key must not raise on the resulting null
    margin_eur values, and every entry should report null financials."""
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