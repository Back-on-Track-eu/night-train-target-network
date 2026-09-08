"""
test_41_proposal_calc_matrix_api.py
===================================
Contract tests for POST /api/proposal/calc/matrix (adapters/proposal/
README.md §2.5): one route under every scenario × composition, as one
JSON document or as an NDJSON stream of records.

Against the live stack. CI runs the infra_2026 OpenRailRouting instance
only, so every cell on an infra_2032 scenario is an error cell
(routing_graph_not_configured) by design — the tests assert that rather
than skip it; a stack that does run the second instance simply sees
fewer error cells (the assertions are written for both).

Kept small on purpose: a default-axes matrix is 6 × 12 cells. The module
computes one 2-stop matrix over a narrow explicit axis set for the
structural cases and one default-axes matrix for the count/cache cases,
both shared via module fixtures.
"""

from __future__ import annotations

import json

import pytest
import requests

from models.route.model import DEFAULT_COMPOSITION_ID
from tests.conftest import DEFAULT_COMPOSITION, REF_COMPOSITION, STOPS_BERLIN_WIEN
from tests.helpers import PROPOSAL_CALC_URL, SCENARIOS_URL, compute

MATRIX_URL = f"{PROPOSAL_CALC_URL}/matrix"
NDJSON = "application/x-ndjson"

BASE_REQUEST = {"stops": STOPS_BERLIN_WIEN, "auto_stop_addition": "off"}


def post_matrix(api_base, body, accept=None, timeout=600):
    headers = {"Accept": accept} if accept else {}
    return requests.post(
        f"{api_base}{MATRIX_URL}",
        json=body,
        headers=headers,
        timeout=timeout,
        stream=accept == NDJSON,
    )


@pytest.fixture(scope="module")
def scenarios(api_base):
    body = requests.get(f"{api_base}{SCENARIOS_URL}", timeout=15).json()
    return {
        "base": body["current_base"]["scenarios"][0],
        "current": [
            *body["current_base"]["scenarios"],
            *body["current_scenarios"]["scenarios"],
        ],
        "historical": body["historical_scenarios"]["scenarios"],
    }


@pytest.fixture(scope="module")
def scenario_2026(scenarios):
    return [s for s in scenarios["current"] if s["scenario_key"] == "infra-2026-hsr"][0]


@pytest.fixture(scope="module")
def scenario_2032(scenarios):
    return [s for s in scenarios["current"] if s["scenario_key"] == "infra-2032"][0]


@pytest.fixture(scope="module")
def narrow_body(scenarios, scenario_2026, scenario_2032):
    """2 scenarios (base + 2026 HSR) × 2 compositions plus one 2032 row:
    3 × 2 = 6 cells, at least two of which error on a one-instance stack."""
    return {
        **BASE_REQUEST,
        "scenario_ids": [
            scenarios["base"]["scenario_id"],
            scenario_2026["scenario_id"],
            scenario_2032["scenario_id"],
        ],
        "composition_ids": [DEFAULT_COMPOSITION, REF_COMPOSITION],
    }


@pytest.fixture(scope="module")
def narrow_document(api_base, narrow_body):
    resp = post_matrix(api_base, narrow_body)
    assert resp.status_code == 200, resp.text[:300]
    return resp.json()


@pytest.fixture(scope="module")
def full_document(api_base, narrow_body):
    resp = post_matrix(api_base, {**narrow_body, "detail": "full"})
    assert resp.status_code == 200, resp.text[:300]
    return resp.json()


@pytest.fixture(scope="module")
def default_document(api_base):
    resp = post_matrix(api_base, BASE_REQUEST)
    assert resp.status_code == 200, resp.text[:300]
    return resp.json()


def ok_cells(document):
    return [c for c in document["cells"] if c["status"] == "ok"]


# =============================================================================
# Validation — decided before the first byte
# =============================================================================


class TestValidation:
    @pytest.mark.parametrize(
        "patch",
        [
            {"stops": ["osm:n3856100103"]},
            {"composition_ids": []},
            {"scenario_ids": []},
            {"composition_ids": ["NO-SUCH-COMP"]},
            {"scenario_ids": [999999]},
            {"scenario_ids": [1, 1]},
            {"scenario_ids": ["1"]},
            {"detail": "everything"},
            {"timetable_mode": "nope"},
            {"fixed_night_interval": ["osm:n3856100103", "osm:w423692233"]},
        ],
    )
    def test_bad_requests_are_400(self, api_base, patch):
        resp = post_matrix(api_base, {**BASE_REQUEST, **patch})
        assert resp.status_code == 400, resp.text[:300]
        assert resp.json()["error"] == "validation_error"

    def test_empty_body_is_400(self, api_base):
        resp = requests.post(f"{api_base}{MATRIX_URL}", timeout=15)
        assert resp.status_code == 400

    def test_default_grid_fits_the_cap(self, default_document):
        """6 current scenarios × the whole catalog must be allowed by
        CALC_MATRIX_MAX_CELLS — otherwise the default request is a 400."""
        assert default_document["n_cells"] == len(default_document["cells"])


# =============================================================================
# Document mode — axes, indexing, cells
# =============================================================================


class TestDocument:
    def test_top_level_shape(self, narrow_document):
        assert set(narrow_document) >= {
            "route_builder_version",
            "calc_version",
            "request",
            "axes",
            "n_cells",
            "baseline_index",
            "status",
            "stats",
            "cells",
        }
        assert "shared" not in narrow_document  # summary detail: nothing shared
        assert "models" not in narrow_document
        assert narrow_document["status"] == "complete"

    def test_axes_keep_request_order(self, narrow_document, narrow_body):
        axes = narrow_document["axes"]
        assert [s["scenario_id"] for s in axes["scenarios"]] == narrow_body[
            "scenario_ids"
        ]
        assert [c["composition_id"] for c in axes["compositions"]] == narrow_body[
            "composition_ids"
        ]
        assert set(axes["scenarios"][0]) >= {
            "scenario_id",
            "scenario_key",
            "scenario_name",
            "is_current_base",
            "routing_graph_key",
            "dimensions",
        }
        assert set(axes["compositions"][0]) >= {
            "composition_id",
            "description",
            "material_strategy",
            "operator_id",
            "operator_name",
            "places_by_class",
            "places_total",
        }

    def test_request_echo_is_resolved(self, narrow_document, narrow_body):
        request = narrow_document["request"]
        assert request["composition_ids"] == narrow_body["composition_ids"]
        assert request["scenario_ids"] == narrow_body["scenario_ids"]
        assert request["detail"] == "summary"
        assert request["timetable_mode"] == "simpleAutomatic"
        assert request["expert_timetable"] is None

    def test_cells_indexed_scenarios_outer_compositions_inner(self, narrow_document):
        axes = narrow_document["axes"]
        n_comp = len(axes["compositions"])
        assert [c["index"] for c in narrow_document["cells"]] == list(
            range(narrow_document["n_cells"])
        )
        for cell in narrow_document["cells"]:
            scenario = axes["scenarios"][cell["index"] // n_comp]
            composition = axes["compositions"][cell["index"] % n_comp]
            assert cell["scenario_id"] == scenario["scenario_id"]
            assert cell["composition_id"] == composition["composition_id"]

    def test_baseline_is_base_scenario_with_default_composition(
        self, narrow_document, scenarios
    ):
        baseline = narrow_document["cells"][narrow_document["baseline_index"]]
        assert baseline["scenario_id"] == scenarios["base"]["scenario_id"]
        assert baseline["composition_id"] == DEFAULT_COMPOSITION_ID
        assert baseline["status"] == "ok"

    def test_ok_cell_shape_summary_level(self, narrow_document):
        cell = ok_cells(narrow_document)[0]
        assert set(cell) == {
            "index",
            "scenario_id",
            "composition_id",
            "status",
            "cache_hit",
            "route_fingerprint",
            "summary",
        }
        assert cell["route_fingerprint"].startswith("sha256:")
        assert set(cell["summary"]) >= {
            "subsidy_eur_per_year",
            "net_eur_per_year",
            "train_km_per_year",
            "available_place_km_per_year",
            "co2_savings_t_per_year",
            "total_time_h",
        }

    def test_2032_cells_are_error_cells_without_the_instance(
        self, narrow_document, scenario_2032
    ):
        """On a one-instance stack (CI) every infra_2032 cell is a
        routing_graph_not_configured error cell and the request is still
        200; with the instance running they are ordinary ok cells."""
        cells_2032 = [
            c
            for c in narrow_document["cells"]
            if c["scenario_id"] == scenario_2032["scenario_id"]
        ]
        assert len(cells_2032) == 2
        statuses = {c["status"] for c in cells_2032}
        assert len(statuses) == 1
        if statuses == {"error"}:
            assert all(c["error"] == "routing_graph_not_configured" for c in cells_2032)
            assert all("message" in c for c in cells_2032)
        stats = narrow_document["stats"]
        assert stats["n_ok"] + stats["n_error"] == stats["n_cells"] == 6
        assert stats["n_error"] == len(
            [c for c in cells_2032 if c["status"] == "error"]
        )

    def test_cells_differ_across_axes(self, narrow_document):
        """Different composition → different fingerprint (the route is
        composition-specific); same composition on the HSR scenario →
        different figures. Guards against a cell loop that ignores its
        coordinates."""
        by_key = {
            (c["scenario_id"], c["composition_id"]): c
            for c in ok_cells(narrow_document)
        }
        fingerprints = {c["route_fingerprint"] for c in by_key.values()}
        assert len(fingerprints) >= 2
        assert (
            len({c["summary"]["cost_eur_per_train_km"] for c in by_key.values()}) >= 2
        )


# =============================================================================
# Cache relationship (§2.3)
# =============================================================================


class TestCacheWarming:
    def test_cells_warm_the_calc_cache(self, api_base, narrow_document, narrow_body):
        cell = ok_cells(narrow_document)[0]
        response = compute(
            api_base,
            narrow_body["stops"],
            composition_id=cell["composition_id"],
            scenario_id=cell["scenario_id"],
            auto_stop_addition="off",
        )
        assert response["cache_hit"] is True
        assert response["route_fingerprint"] == cell["route_fingerprint"]
        assert response["summary"] == cell["summary"]

    def test_second_matrix_is_all_cache_hits(
        self, api_base, narrow_document, narrow_body
    ):
        second = post_matrix(api_base, narrow_body).json()
        assert second["stats"]["n_cache_hit"] == second["stats"]["n_ok"]
        assert second["stats"]["n_ok"] == narrow_document["stats"]["n_ok"]


# =============================================================================
# Full detail — shared blocks and references
# =============================================================================


class TestFullDetail:
    def test_header_carries_models_once(self, full_document):
        assert set(full_document["models"]) >= {"evaluation"}
        for cell in full_document["cells"]:
            assert "models" not in cell

    def test_every_reference_resolves(self, full_document):
        shared = full_document["shared"]
        assert set(shared) >= {
            "geometry",
            "track_infrastructures",
            "stop_infrastructures",
            "compositions",
        }
        n_segments = 0
        for cell in ok_cells(full_document):
            assert "geometries" not in cell["route"]
            for pair in cell["route"]["trip_pairs"]:
                for trip in (pair["outbound"], pair["return_trip"]):
                    for seg in trip["segments"]:
                        n_segments += 1
                        assert seg["geometry_id"] in shared["geometry"]
            refs = cell["evaluation"]["parameters_refs"]
            for kind, ref in refs.items():
                assert ref in shared[kind]
            assert "views" in cell["evaluation"]
        # Dedup did something: fewer geometry blocks than segment references.
        assert len(shared["geometry"]) < n_segments

    def test_one_by_one_full_cell_equals_calc(self, api_base, narrow_body, scenarios):
        """A 1×1 full matrix is /calc with the references inlined."""
        body = {
            **narrow_body,
            "scenario_ids": [scenarios["base"]["scenario_id"]],
            "composition_ids": [DEFAULT_COMPOSITION],
            "detail": "full",
        }
        document = post_matrix(api_base, body).json()
        [cell] = document["cells"]
        calc = compute(
            api_base,
            body["stops"],
            composition_id=DEFAULT_COMPOSITION,
            scenario_id=body["scenario_ids"][0],
            auto_stop_addition="off",
        )
        assert cell["route_fingerprint"] == calc["route_fingerprint"]
        assert cell["summary"] == calc["summary"]
        assert cell["evaluation"]["views"] == calc["evaluation"]["views"]
        parameters = calc["evaluation"]["input"]["parameters"]
        for kind, ref in cell["evaluation"]["parameters_refs"].items():
            assert document["shared"][kind][ref] == parameters[kind]
        # Route equal once geometry refs are re-inlined.
        calc_geometry = {g["id"]: g["coords"] for g in calc["route"]["geometries"]}
        for pair_m, pair_c in zip(
            cell["route"]["trip_pairs"], calc["route"]["trip_pairs"]
        ):
            for direction in ("outbound", "return_trip"):
                for seg_m, seg_c in zip(
                    pair_m[direction]["segments"], pair_c[direction]["segments"]
                ):
                    assert (
                        document["shared"]["geometry"][seg_m["geometry_id"]]
                        == calc_geometry[seg_c["geometry_id"]]
                    )

    def test_suggestions_only_in_full(self, api_base, narrow_body, scenarios):
        body = {
            **narrow_body,
            "scenario_ids": [scenarios["base"]["scenario_id"]],
            "composition_ids": [DEFAULT_COMPOSITION],
            "auto_stop_addition": "suggest",
        }
        summary_cell = post_matrix(api_base, body).json()["cells"][0]
        assert "suggested_stops" not in summary_cell
        full_cell = post_matrix(api_base, {**body, "detail": "full"}).json()["cells"][0]
        assert isinstance(full_cell.get("suggested_stops"), list)


# =============================================================================
# NDJSON stream
# =============================================================================


class TestStream:
    @pytest.fixture(scope="class")
    def records(self, api_base, narrow_body):
        resp = post_matrix(api_base, {**narrow_body, "detail": "full"}, accept=NDJSON)
        assert resp.status_code == 200
        assert resp.headers["Content-Type"].startswith(NDJSON)
        assert "Content-Length" not in resp.headers
        assert resp.headers.get("Content-Encoding") in (None, "identity")
        lines = [line for line in resp.iter_lines() if line]
        return [json.loads(line) for line in lines]

    def test_record_order(self, records, narrow_document):
        assert records[0]["type"] == "header"
        assert records[-1]["type"] == "done"
        assert records[-1]["status"] == "complete"
        cells = [r for r in records if r["type"] == "cell"]
        assert len(cells) == narrow_document["n_cells"]
        # Baseline first, always.
        assert cells[0]["index"] == records[0]["baseline_index"]

    def test_shared_before_first_reference(self, records):
        seen: set[str] = set()
        for record in records:
            if record["type"] == "shared":
                assert record["id"] not in seen  # emitted once
                seen.add(record["id"])
            elif record["type"] == "cell" and record["status"] == "ok":
                for pair in record["route"]["trip_pairs"]:
                    for direction in ("outbound", "return_trip"):
                        for seg in pair[direction]["segments"]:
                            assert seg["geometry_id"] in seen
                for ref in record["evaluation"]["parameters_refs"].values():
                    assert ref in seen

    def test_header_arrives_before_the_end(self, api_base, narrow_body):
        """The stream is not buffered by the app: the header line is
        readable before the response has finished."""
        resp = post_matrix(api_base, narrow_body, accept=NDJSON)
        lines = resp.iter_lines()
        first = json.loads(next(line for line in lines if line))
        assert first["type"] == "header"
        assert not resp.raw.closed
        resp.close()
