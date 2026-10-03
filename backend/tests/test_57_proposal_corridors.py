"""
test_57_proposal_corridors.py
=============================
proposals.proposal_corridors (adapters/proposal/README.md §5.4b): the
gallery's corridor overview precomputed at publish, read by
POST /api/proposals' map_lines, backfilled by the data task runner
(db/run_tasks.py + db/tasks/2026-10-03_backfill_proposal_corridors.py).

What is pinned here:
  - a publish writes the base rows (one per direction-collapsed stop pair
    of the stored route) and, for every computed scenario row that
    carries segments, that variant's rows — keyed exactly as the JSON
  - the table path and the request-time derivation it replaced agree:
    same corridors, same counts, same routed flags, on the base and on a
    variant
  - the fallback: with a proposal's rows deleted, map_lines still answers
    (derived), the proposal is on the backfill queue, and the task puts
    the rows back and records a `done` run — then the fast path answers
    the same again
  - the runner's bookkeeping: pending/completed from admin.data_task_runs

Isolation: same discipline as test_56 — publish commits outside the
per-test rollback, so the module purges published proposals before and
after itself. Corridor rows go with the container (FK cascade).
"""

import pytest
import requests

from adapters.proposal.repository import ProposalRepository
from db import run_tasks
from tests.helpers import (
    PROPOSALS_URL,
    _variant_id_for,
    compute,
    publish,
    purge_saved_proposals,
)

_STOPS = ["osm:n3856100103", "osm:w423692233"]
_COMPOSITION = "NEW-BAL-7"
_BACKFILL_TASK = "2026-10-03_backfill_proposal_corridors.py"


@pytest.fixture(scope="module", autouse=True)
def clean_proposals(db_conn, script_headers):
    purge_saved_proposals(db_conn)
    yield
    purge_saved_proposals(db_conn)


@pytest.fixture(scope="module")
def published(api_base, script_headers):
    computed = compute(api_base, _STOPS, _COMPOSITION)
    return publish(
        api_base,
        computed["request"],
        name="Berlin – Wien (corridor rows test)",
        headers=script_headers,
    )


@pytest.fixture(scope="module")
def repo():
    """The repository on the test process's own pool — the same SQL the
    api runs, without going through dependencies.init()."""
    return ProposalRepository()


def _corridor_rows(db_cur, proposal_id: int) -> list[dict]:
    db_cur.execute(
        "SELECT proposal_version, scenario_variant_id, stop_a, stop_b, "
        "       geometry_routed, ST_NPoints(geom) AS n_points, "
        "       ST_GeometryType(geom) AS geom_type "
        "FROM proposals.proposal_corridors WHERE proposal_id = %s "
        "ORDER BY scenario_variant_id NULLS FIRST, stop_a, stop_b",
        (proposal_id,),
    )
    return [dict(r) for r in db_cur.fetchall()]


def _filter(published: dict) -> dict:
    return {"sources": ["proposal"], "proposal_ids": [published["proposal_id"]]}


def _gallery_lines(api_base: str, published: dict, **body) -> list[dict]:
    resp = requests.post(
        f"{api_base}{PROPOSALS_URL}",
        json={"filter": _filter(published), "include": ["map_lines"], **body},
        timeout=60,
    )
    assert resp.status_code == 200, resp.text[:300]
    return resp.json()["map_lines"]["features"]


def _shape(rows: list[dict]) -> set[tuple]:
    """What must agree between the table path and the derivation: the
    corridor set with its counts and routed flag (geometry is the same
    source simplified at the same tolerance, but the representative pick
    may legitimately differ, so it is not compared point by point)."""
    return {
        (
            r["stop_a"],
            r["stop_b"],
            r["proposal_count"],
            r["existing_count"],
            r["total_count"],
            bool(r["geometry_routed"]),
        )
        for r in rows
    }


def _feature_shape(features: list[dict]) -> set[tuple]:
    return _shape([f["properties"] for f in features])


# =============================================================================
# Write path
# =============================================================================


def test_publish_writes_base_rows_for_every_stop_pair(db_cur, published):
    rows = _corridor_rows(db_cur, published["proposal_id"])
    base = [r for r in rows if r["scenario_variant_id"] is None]
    assert base, "a publish writes the base corridor rows"
    assert all(r["proposal_version"] == published["proposal_version"] for r in rows)
    assert all(r["geom_type"] == "ST_LineString" and r["n_points"] >= 2 for r in rows)
    assert all(r["stop_a"] < r["stop_b"] for r in rows), "direction collapsed"

    # Exactly the stored route's stop pairs, outbound and return on one row.
    db_cur.execute(
        "SELECT DISTINCT LEAST(s.from_stop_id, s.to_stop_id) AS a, "
        "       GREATEST(s.from_stop_id, s.to_stop_id) AS b "
        "FROM proposals.trips t JOIN proposals.segments s ON s.trip_id = t.trip_id "
        "WHERE t.route_id = %s AND s.shape_id IS NOT NULL",
        (f"P{published['proposal_id']}_V{published['proposal_version']}_R1",),
    )
    expected = {(r["a"], r["b"]) for r in db_cur.fetchall()}
    assert {(r["stop_a"], r["stop_b"]) for r in base} == expected


def test_publish_writes_variant_rows_keyed_like_the_segments_json(db_cur, published):
    db_cur.execute(
        "SELECT scenario_variant_id, status, segments "
        "FROM proposals.proposal_scenario_summaries WHERE proposal_id = %s",
        (published["proposal_id"],),
    )
    scenario_rows = [dict(r) for r in db_cur.fetchall()]
    rows = _corridor_rows(db_cur, published["proposal_id"])
    by_variant: dict[int, set] = {}
    for r in rows:
        if r["scenario_variant_id"] is not None:
            by_variant.setdefault(r["scenario_variant_id"], set()).add(
                (r["stop_a"], r["stop_b"])
            )
    for sr in scenario_rows:
        variant = sr["scenario_variant_id"]
        if sr["status"] == "ok" and sr["segments"]:
            expected = {tuple(key.split("__", 1)) for key in sr["segments"]}
            assert by_variant.get(variant) == expected, variant
        else:
            # An error row draws nothing on its scenario, as before.
            assert variant not in by_variant


# =============================================================================
# Read path — table == derivation
# =============================================================================


def test_map_lines_from_the_table_matches_the_derivation(repo, published):
    filters = _filter(published)
    fast = repo.map_lines(filters)
    derived = repo._map_lines_derived(filters)
    assert fast, "the published proposal has corridors"
    assert _shape(fast) == _shape(derived)
    assert all(r["geometry"] is not None for r in fast)


def test_map_lines_on_a_variant_matches_the_derivation(
    repo, api_base, published, hsr_scenario
):
    variant = _variant_id_for(api_base, hsr_scenario["scenario_id"])
    filters = _filter(published)
    fast = repo.map_lines(filters, scenario_variant_id=variant)
    derived = repo._map_lines_derived(filters, scenario_variant_id=variant)
    # Both empty when this stack cannot compute the variant (an error row
    # draws no corridor) — still an agreement worth asserting.
    assert _shape(fast) == _shape(derived)


def test_api_map_lines_uses_the_same_corridors(repo, api_base, published):
    api = _feature_shape(_gallery_lines(api_base, published))
    assert api == _shape(repo.map_lines(_filter(published)))


# =============================================================================
# Fallback, backfill queue, the data task runner
# =============================================================================


def test_missing_rows_fall_back_then_the_task_backfills(
    repo, api_base, db_conn, db_cur, published
):
    """Last in the module: it deletes and restores the proposal's rows."""
    before = _feature_shape(_gallery_lines(api_base, published))
    assert before

    with db_conn.cursor() as cur:
        cur.execute(
            "DELETE FROM proposals.proposal_corridors WHERE proposal_id = %s",
            (published["proposal_id"],),
        )
    db_conn.commit()

    # On the queue, and the api answers the same from the derivation.
    assert published["proposal_id"] in {
        g["proposal_id"] for g in repo.list_corridor_gaps()
    }
    assert not repo._corridors_complete()
    assert _feature_shape(_gallery_lines(api_base, published)) == before

    # The task, through the runner, on the test process's own tracking
    # connection — the same call the deploy's `data-tasks` one-shot makes.
    tracking = run_tasks.migrate._connect()
    try:
        run_tasks._ensure_tracking_table(tracking)
        assert _BACKFILL_TASK in run_tasks._task_files()
        assert run_tasks._run_one(tracking, _BACKFILL_TASK, dry_run=False)
        assert _BACKFILL_TASK in run_tasks._completed(tracking)
        assert _BACKFILL_TASK not in run_tasks._pending(tracking)
    finally:
        tracking.close()

    db_cur.execute(
        "SELECT status, summary FROM admin.data_task_runs "
        "WHERE filename = %s ORDER BY run_id DESC LIMIT 1",
        (_BACKFILL_TASK,),
    )
    last = db_cur.fetchone()
    assert last["status"] == "done"
    assert "proposal" in last["summary"]

    assert _corridor_rows(db_cur, published["proposal_id"])
    assert published["proposal_id"] not in {
        g["proposal_id"] for g in repo.list_corridor_gaps()
    }
    assert _feature_shape(_gallery_lines(api_base, published)) == before
