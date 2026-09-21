"""
test_56_proposal_scenario_summaries.py
=======================================
proposals.proposal_scenario_summaries (adapters/proposal/README.md §5.4a):
the gallery projection once per current scenario variant, written with
every publish, replaced on overwrite, and read by POST /api/proposals
when the request names a scenario_variant_id.

What is pinned here:
  - a publish writes one row per current variant; the base variant's row
    carries the same figures as proposal_summaries, so the two read paths
    cannot disagree
  - the two ways to those rows agree: reading the builder's family
    document (the publish-after-Evaluate case) and rebuilding the family
    produce identical rows, and a variant whose routing graph is not
    served is an error row without either
  - a variant the deployment cannot compute is an error row with a known
    code, never a missing row (CI has no Infra 2032 routing instance, so
    those variants exercise it there; a stack that serves them stores ok
    rows — the test accepts either, asserting only the invariant)
  - the gallery on a variant returns that variant's figures, geometry and
    corridors, and the base path is byte-for-byte the pre-§5.4a contract
  - an overwrite replaces the rows, and the backfill work queue is empty
    for a freshly published proposal

Isolation: same discipline as test_52 — publish commits outside the
per-test rollback, so the module purges published proposals before and
after itself. The scenario rows go with the container (FK cascade).
"""

import pytest
import requests

from tests.helpers import (
    PROPOSALS_URL,
    _variant_id_for,
    compute,
    publish,
    purge_saved_proposals,
)

_STOPS = ["osm:n3856100103", "osm:w423692233"]
_COMPOSITION = "NEW-BAL-7"
_OTHER_COMPOSITION = "NEW-BAL-14"

# Every code api/helpers/member_compute.py classify_compute_error() can
# name, plus the fallback scenario_summaries.py stores when it cannot.
_KNOWN_ERROR_CODES = {
    "gauge_mismatch",
    "routing_graph_not_configured",
    "routing_error",
    "domain_error",
    "calc_error",
}

_COMPARED_COLUMNS = (
    "total_distance_km",
    "total_time_h",
    "n_stops",
    "cost_eur_per_train_km",
    "revenue_eur_per_train_km",
    "subsidy_eur_per_year",
    "demand_trips_per_year",
    "co2_savings_t_per_year",
)


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
        name="Berlin \u2013 Wien (scenario rows test)",
        headers=script_headers,
    )


@pytest.fixture(scope="module")
def current_variant_ids(db_conn):
    """Every variant of a current scenario — the set the rows must cover."""
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT v.scenario_variant_id "
            "FROM scenario.scenario_variants v "
            "JOIN scenario.scenarios s ON s.scenario_id = v.scenario_id "
            "WHERE s.is_current_scenario ORDER BY 1"
        )
        return [row[0] for row in cur.fetchall()]


def _scenario_rows(db_cur, proposal_id: int) -> dict[int, dict]:
    db_cur.execute(
        "SELECT * FROM proposals.proposal_scenario_summaries "
        "WHERE proposal_id = %s ORDER BY scenario_variant_id",
        (proposal_id,),
    )
    return {row["scenario_variant_id"]: dict(row) for row in db_cur.fetchall()}


def _gallery(api_base: str, published: dict, **body) -> dict:
    resp = requests.post(
        f"{api_base}{PROPOSALS_URL}",
        json={
            "filter": {
                "sources": ["proposal"],
                "proposal_ids": [published["proposal_id"]],
            },
            "include": ["summaries", "map_routes", "map_lines"],
            **body,
        },
        timeout=60,
    )
    assert resp.status_code == 200, resp.text[:300]
    return resp.json()


# =============================================================================
# Write path
# =============================================================================


def test_publish_writes_one_row_per_current_variant(
    db_cur, published, current_variant_ids
):
    rows = _scenario_rows(db_cur, published["proposal_id"])
    assert sorted(rows) == current_variant_ids
    for row in rows.values():
        assert row["proposal_version"] == published["proposal_version"]
        assert row["composition_id"] == _COMPOSITION
        assert row["status"] in {"ok", "error"}
        if row["status"] == "ok":
            assert row["error_code"] is None
            assert row["geom_simplified"] is not None
            assert row["segments"], "an ok row carries its corridor segments"
            assert row["total_distance_km"] is not None
        else:
            assert row["error_code"] in _KNOWN_ERROR_CODES
            assert row["total_distance_km"] is None
            assert row["geom_simplified"] is None


def test_base_row_matches_proposal_summaries(api_base, db_cur, published):
    base_variant = _variant_id_for(api_base, None)
    rows = _scenario_rows(db_cur, published["proposal_id"])
    base = rows[base_variant]
    assert base["status"] == "ok"

    db_cur.execute(
        "SELECT * FROM proposals.proposal_summaries WHERE proposal_id = %s",
        (published["proposal_id"],),
    )
    summary = db_cur.fetchone()
    assert summary["scenario_id"] == base["scenario_id"]
    for column in _COMPARED_COLUMNS:
        assert base[column] == summary[column], column
    assert list(base["stop_ids"]) == list(summary["stop_ids"])


def test_hsr_variant_is_its_own_computation(api_base, db_cur, published, hsr_scenario):
    """The HSR scenario runs on the base graph, so it is computable
    wherever the base is — and it is a different route, so its row must
    not be a copy of the base one."""
    hsr_variant = _variant_id_for(api_base, hsr_scenario["scenario_id"])
    base_variant = _variant_id_for(api_base, None)
    rows = _scenario_rows(db_cur, published["proposal_id"])
    hsr, base = rows[hsr_variant], rows[base_variant]
    assert hsr["status"] == "ok"
    assert hsr["scenario_id"] == hsr_scenario["scenario_id"]
    assert (
        hsr["total_time_h"],
        hsr["total_distance_km"],
        hsr["cost_eur_per_train_km"],
    ) != (
        base["total_time_h"],
        base["total_distance_km"],
        base["cost_eur_per_train_km"],
    )


def test_corridor_segments_are_direction_collapsed(db_cur, published):
    rows = _scenario_rows(db_cur, published["proposal_id"])
    for row in rows.values():
        if row["status"] != "ok":
            continue
        for key, geometry in row["segments"].items():
            stop_a, stop_b = key.split("__")
            assert stop_a < stop_b, key
            assert geometry["type"] == "LineString"
            assert len(geometry["coordinates"]) >= 2


def test_overwrite_replaces_rows(
    api_base, db_cur, script_headers, published, current_variant_ids
):
    computed = compute(api_base, _STOPS, _OTHER_COMPOSITION)
    overwritten = publish(
        api_base,
        computed["request"],
        name="Berlin \u2013 Wien (scenario rows test, overwritten)",
        mode="overwrite",
        proposal_id=published["proposal_id"],
        headers=script_headers,
    )
    assert overwritten["proposal_version"] == published["proposal_version"] + 1
    rows = _scenario_rows(db_cur, published["proposal_id"])
    assert sorted(rows) == current_variant_ids
    assert {row["composition_id"] for row in rows.values()} == {_OTHER_COMPOSITION}
    assert {row["proposal_version"] for row in rows.values()} == {
        overwritten["proposal_version"]
    }
    # Put the composition back for the read-path tests below.
    computed = compute(api_base, _STOPS, _COMPOSITION)
    restored = publish(
        api_base,
        computed["request"],
        name="Berlin \u2013 Wien (scenario rows test)",
        mode="overwrite",
        proposal_id=published["proposal_id"],
        headers=script_headers,
    )
    published["proposal_version"] = restored["proposal_version"]


# =============================================================================
# The two paths to a row (A.1)
# =============================================================================


def test_unservable_variants_short_circuit(api_base, published):
    """A variant whose routing graph this deployment serves no instance
    for is an error row, and is decided before any family runs — which is
    what keeps a publish cheap on a stack without Infra 2032."""
    from api.helpers import dependencies
    from api.helpers.scenario_summaries import _split_by_routing_graph
    from api.helpers.family_compute import resolve_family_axes

    dependencies.init()
    loader = dependencies.get_loader()
    axes = resolve_family_axes({}, loader)
    servable, unavailable = _split_by_routing_graph(axes)

    assert servable, "the base scenario's graph must be configured"
    assert len(servable) + len(unavailable) == len(axes.variants)
    for _variant, code in unavailable:
        assert code == "routing_graph_not_configured"
    graphs = {axes.scenarios[v.scenario_id].routing_graph_key for v in servable}
    unserved = {axes.scenarios[v.scenario_id].routing_graph_key for v, _ in unavailable}
    assert not (graphs & unserved), "a graph is either served or it is not"


def test_document_and_build_paths_agree(api_base, db_conn, published):
    """The publish path (document hit) and the backfill path (full build)
    must produce the same rows — same figures, same corridor keys, same
    geometry — or the gallery would change under a refresh."""
    from api.helpers import dependencies
    from api.helpers import scenario_summaries as ss

    dependencies.init()
    container = dependencies.get_proposal_repository().get_container(
        published["proposal_id"]
    )
    request = dict(container["compute_request"])

    # The builder's document for these stops is in family.documents from
    # the publish above; ask for the rows and confirm which path ran.
    from_document = ss.compute_scenario_rows(request)
    document_source = ss.SCENARIO_ROW_SOURCE

    dependencies.get_family_document_cache().flush()
    from_build = ss.compute_scenario_rows(request)
    assert ss.SCENARIO_ROW_SOURCE == "build"

    if document_source != "document":
        pytest.skip("no family document for this request — path not exercised")

    by_variant = {row["scenario_variant_id"]: row for row in from_build}
    assert set(by_variant) == {row["scenario_variant_id"] for row in from_document}
    for row in from_document:
        other = by_variant[row["scenario_variant_id"]]
        assert row["status"] == other["status"]
        assert row["error_code"] == other["error_code"]
        if row["status"] != "ok":
            continue
        for column in _COMPARED_COLUMNS:
            assert row["summary"][column] == other["summary"][column], column
        assert set(row["segments"]) == set(other["segments"])
        assert row["summary"]["geom_simplified"] == other["summary"]["geom_simplified"]


def test_backfill_queue_is_empty_for_a_fresh_publish(published):
    from api.helpers import dependencies

    dependencies.init()
    queue = dependencies.get_proposal_repository().list_scenario_backfill()
    assert published["proposal_id"] not in {row["proposal_id"] for row in queue}


# =============================================================================
# Read path — POST /api/proposals
# =============================================================================


def test_default_gallery_is_the_base_projection(api_base, published):
    body = _gallery(api_base, published)
    assert body["summaries"]["scenario_variant_id"] is None
    (row,) = body["summaries"]["proposals"]
    assert row["status"] == "ok"
    assert row["error_code"] is None
    assert row["scenario_variant_id"] is None


def test_gallery_on_a_variant_reads_that_variant(
    api_base, db_cur, published, hsr_scenario
):
    hsr_variant = _variant_id_for(api_base, hsr_scenario["scenario_id"])
    body = _gallery(api_base, published, scenario_variant_id=hsr_variant)
    assert body["summaries"]["scenario_variant_id"] == hsr_variant
    (row,) = body["summaries"]["proposals"]
    assert row["status"] == "ok"
    assert row["scenario_variant_id"] == hsr_variant
    assert row["scenario_id"] == hsr_scenario["scenario_id"]
    # Identity and engagement come from the container, the figures from
    # the scenario row.
    assert row["proposal_id"] == published["proposal_id"]
    assert row["likes_count"] == 0
    assert row["created_at"] is not None
    stored = _scenario_rows(db_cur, published["proposal_id"])[hsr_variant]
    assert row["total_time_h"] == float(stored["total_time_h"])
    assert row["cost_eur_per_train_km"] == float(stored["cost_eur_per_train_km"])

    # The map follows: the card's own route and at least one corridor,
    # both from the scenario row rather than the GTFS tables.
    (feature,) = body["map_routes"]["features"]
    assert feature["properties"]["proposal_id"] == published["proposal_id"]
    assert feature["geometry"]["type"] == "MultiLineString"
    corridors = body["map_lines"]["features"]
    assert corridors
    assert all(c["properties"]["proposal_count"] == 1 for c in corridors)
    assert all(c["geometry"] is not None for c in corridors)


def test_gallery_on_an_error_variant_lists_the_row_without_figures(
    api_base, db_cur, published
):
    """A scenario changes what a card SAYS, never whether it is listed:
    the row is there with its identity and the base projection's
    filterable columns, and only the figures are null."""
    rows = _scenario_rows(db_cur, published["proposal_id"])
    error_rows = [row for row in rows.values() if row["status"] == "error"]
    if not error_rows:
        pytest.skip("every current variant is computable on this stack")
    variant = error_rows[0]["scenario_variant_id"]
    body = _gallery(api_base, published, scenario_variant_id=variant)
    (row,) = body["summaries"]["proposals"]
    assert row["status"] == "error"
    assert row["error_code"] == error_rows[0]["error_code"]
    assert row["total_distance_km"] is None
    assert row["cost_eur_per_train_km"] is None
    assert row["stop_ids"] == _STOPS
    assert row["name"] == published["name"]
    (feature,) = body["map_routes"]["features"]
    assert feature["geometry"] is None
    assert body["map_lines"]["features"] == []


def test_a_scenario_never_changes_the_result_set(api_base, published, hsr_scenario):
    """The same filter must return the same proposals on every scenario —
    the panel changes figures, not membership."""
    hsr_variant = _variant_id_for(api_base, hsr_scenario["scenario_id"])
    filters = {"sources": ["proposal"], "stop_ids": {"values": _STOPS, "mode": "all"}}
    base = requests.post(
        f"{api_base}{PROPOSALS_URL}", json={"filter": filters}, timeout=60
    ).json()
    on_hsr = requests.post(
        f"{api_base}{PROPOSALS_URL}",
        json={"filter": filters, "scenario_variant_id": hsr_variant},
        timeout=60,
    ).json()
    assert on_hsr["summaries"]["total"] == base["summaries"]["total"]
    assert [p["proposal_id"] for p in on_hsr["summaries"]["proposals"]] == [
        p["proposal_id"] for p in base["summaries"]["proposals"]
    ]


def test_unknown_variant_is_rejected(api_base):
    resp = requests.post(
        f"{api_base}{PROPOSALS_URL}", json={"scenario_variant_id": 999999}, timeout=30
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "unknown_scenario_variant"

    resp = requests.post(
        f"{api_base}{PROPOSALS_URL}", json={"scenario_variant_id": "base"}, timeout=30
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "validation_error"


def test_a_proposal_without_rows_is_listed_as_missing(
    api_base, db_conn, published, hsr_scenario
):
    """Published before the backfill ran: still listed, figures null, the
    base geometry on the map so nothing disappears. Last in the module —
    it deletes the proposal's scenario rows for good."""
    hsr_variant = _variant_id_for(api_base, hsr_scenario["scenario_id"])
    with db_conn.cursor() as cur:
        cur.execute(
            "DELETE FROM proposals.proposal_scenario_summaries WHERE proposal_id = %s",
            (published["proposal_id"],),
        )
    db_conn.commit()

    body = _gallery(api_base, published, scenario_variant_id=hsr_variant)
    (row,) = body["summaries"]["proposals"]
    assert row["status"] == "missing"
    assert row["error_code"] is None
    assert row["scenario_variant_id"] == hsr_variant
    assert row["total_distance_km"] is None
    assert row["stop_ids"] == _STOPS
    (feature,) = body["map_routes"]["features"]
    assert feature["geometry"] is not None, "the base geometry stands in"
    assert body["map_lines"]["features"] == []

    from api.helpers import dependencies

    dependencies.init()
    queue = dependencies.get_proposal_repository().list_scenario_backfill()
    assert published["proposal_id"] in {row["proposal_id"] for row in queue}
