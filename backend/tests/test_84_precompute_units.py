"""
test_84_precompute_units.py
===========================
The parts of scripts/precompute_route_segments.py that decide whether an
overnight batch can be resumed, retried and uploaded — all pure, no stack
needed: the resume reader (including the two shapes a killed run leaves
behind), the transient/permanent split that decides what a retry round
reattempts, the failures report, and the pgAdmin upload kit's CSV split
and staging DDL.

The routing itself is covered by test_79_route_segment_cache.py.
"""

from __future__ import annotations

import csv
import gzip
import json

import pytest

from db.schema import ROUTE_CACHE_TABLES
from models.route.routing.rail_router import RailRoutingError
from models.route.routing.segment_cache import CSV_COLUMNS
from scripts.precompute_route_segments import (
    collect_done_keys,
    is_transient,
    read_failure_keys,
    read_segment_keys,
    record_failure,
    repair_partial_tail,
    split_csv,
    staging_ddl,
    write_failures,
)


def _row(lo: str, hi: str, vkey: str, n_points: int = 10) -> list:
    return [
        lo,
        hi,
        vkey,
        250_000,
        '{"DE":250000.0}',
        '{"DE":4674000.0}',
        '["DE"]',
        "[]",
        json.dumps([[13.4, 52.5]] * n_points),
    ]


def _write(path, rows, header: bool = True) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if header:
            writer.writerow(CSV_COLUMNS)
        for row in rows:
            writer.writerow(row)


class TestResume:
    def test_keys_are_read_without_the_header(self, tmp_path):
        out = tmp_path / "route_segments_test.csv"
        _write(out, [_row("a", "b", "v1"), _row("a", "c", "v1")])
        assert read_segment_keys(out) == {("a", "b", "v1"), ("a", "c", "v1")}

    def test_partial_final_row_is_truncated_not_raised(self, tmp_path):
        out = tmp_path / "route_segments_test.csv"
        _write(out, [_row("a", "b", "v1")])
        with open(out, "a", encoding="utf-8") as fh:
            fh.write('a,c,v1,250000,"{"')  # killed mid-write

        assert repair_partial_tail(out) is True
        assert read_segment_keys(out) == {("a", "b", "v1")}
        # Idempotent: a repaired file is left alone on the next start.
        assert repair_partial_tail(out) is False

    def test_geometry_beyond_the_csv_field_cap_is_readable(self, tmp_path):
        # A long route serialises to far more than the csv module's 128 kB
        # default field limit — resume must not choke on its own output.
        out = tmp_path / "route_segments_test.csv"
        _write(out, [_row("a", "z", "v1", n_points=20_000)])
        assert out.stat().st_size > 128 * 1024
        assert read_segment_keys(out) == {("a", "z", "v1")}

    def test_resume_from_gzip_counts_as_done(self, tmp_path):
        out = tmp_path / "route_segments_test.csv"
        _write(out, [_row("a", "b", "v1")])
        previous = tmp_path / "route_segments_previous.csv.gz"
        with gzip.open(previous, "wt", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(CSV_COLUMNS)
            writer.writerow(_row("a", "d", "v1"))

        assert collect_done_keys(out, [previous]) == {
            ("a", "b", "v1"),
            ("a", "d", "v1"),
        }


class TestFailureClassification:
    @pytest.mark.parametrize(
        "message",
        ["Routing engine HTTP 503: busy", "Routing engine HTTP 502: read timed out"],
    )
    def test_server_side_hiccups_are_transient(self, message):
        assert is_transient(RailRoutingError(message)) is True

    def test_no_route_is_permanent(self):
        # The word "connection" appears in the message — classification must
        # not key on it, or every unroutable pair would be retried all night.
        exc = RailRoutingError(
            "Routing engine error: connection between locations not found"
        )
        assert is_transient(exc) is False


class TestFailureReport:
    def test_report_is_rewritten_and_counts_attempts(self, tmp_path):
        path = tmp_path / "route_segments_test.failures.csv"
        path.write_text("stale content that must not survive\n", encoding="utf-8")
        failures: dict = {}
        task = ("a", "b", "night_train", "v1")
        for _ in range(2):
            record_failure(failures, task, RailRoutingError("HTTP 502: gateway"))

        write_failures(path, failures, [("x", "y", "night_train", "v1")])

        rows = list(csv.DictReader(open(path, newline="", encoding="utf-8")))
        assert {r["error_type"] for r in rows} == {"RailRoutingError", "NotSnapped"}
        assert [r["attempts"] for r in rows if r["stop_lo"] == "a"] == ["2"]
        # Unsnappable pairs are reported too, so the file answers "what is
        # missing" rather than "what raised".
        assert read_failure_keys(path) == {("a", "b", "v1"), ("x", "y", "v1")}


class TestUploadKit:
    def test_every_part_carries_the_header(self, tmp_path):
        out = tmp_path / "route_segments_test.csv"
        _write(out, [_row(f"s{i}", f"s{i + 1}", "v1", 200) for i in range(200)])
        target = tmp_path / "upload"
        target.mkdir()

        parts = split_csv(out, target, split_mb=0.05)

        assert len(parts) > 1
        routed = 0
        for part in parts:
            rows = list(csv.reader(open(part, newline="", encoding="utf-8")))
            assert rows[0] == CSV_COLUMNS
            routed += len(rows) - 1
        assert routed == 200

    def test_staging_ddl_mirrors_the_declared_schema(self, tmp_path):
        segments = next(t for t in ROUTE_CACHE_TABLES if t.name == "route_segments")
        ddl = staging_ddl("route_cache.route_segments_staging")

        for column in CSV_COLUMNS:
            declared = next(c for c in segments.columns if c.name == column)
            assert f"{column} " in ddl or f"{column}\n" in ddl
            assert declared.sql_type.split(" NOT NULL")[0] in ddl
        # Staging validates nothing the merge does not: the file carries
        # neither the graph key nor the source.
        assert "NOT NULL" not in ddl
        assert "routing_graph_key" not in ddl
