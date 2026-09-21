"""
test_84_precompute_units.py
===========================
The parts of scripts/precompute_route_segments.py that decide whether an
overnight batch can be resumed, retried and uploaded — all pure, no stack
needed: the resume reader (including the two shapes a killed run leaves
behind), the transient/permanent split that decides what a retry round
reattempts, the gauge-aware snap helper search, the failures report, and
the pgAdmin upload kit's CSV split and staging DDL.

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
    expand_resume_paths,
    finalize,
    generate_pairs,
    is_transient,
    read_failure_keys,
    read_segment_keys,
    record_failure,
    repair_partial_tail,
    snap_helpers,
    snap_needed,
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

        write_failures(
            path,
            failures,
            [("x", "y", "night_train", "v1")],
            {("x", "night_train"): "Cannot find point 0"},
        )

        rows = list(csv.DictReader(open(path, newline="", encoding="utf-8")))
        assert {r["error_type"] for r in rows} == {"RailRoutingError", "NotSnapped"}
        assert [r["attempts"] for r in rows if r["stop_lo"] == "a"] == ["2"]
        # A NotSnapped row names the end that failed and why.
        assert [r["error_message"] for r in rows if r["stop_lo"] == "x"] == [
            "x: Cannot find point 0"
        ]
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


class _SnapRouter:
    """snap_point() the way GraphHopper fails it: 'point 0' when the stop
    itself is off the network, anything else when the helper is."""

    profile = "night_train"

    def __init__(self, off_network=(), disconnected=()):
        self.off_network = set(off_network)
        self.disconnected = set(disconnected)
        self.calls: list[tuple[float, float]] = []

    def profile_for_gauge(self, gauge_mm):
        return self.profile if gauge_mm == 1435 else f"{self.profile}_{gauge_mm}"

    def snap_point(self, lon, lat, helper, profile):
        self.calls.append((lon, helper[0]))
        if lon in self.off_network:
            raise RailRoutingError("Routing engine HTTP 400: Cannot find point 0")
        if helper[0] in self.disconnected:
            raise RailRoutingError(
                "Routing engine HTTP 400: Connection between locations not found"
            )
        return [lon, lat]


def _stop(stop_id, lon, gauges):
    from types import SimpleNamespace

    return SimpleNamespace(stop_id=stop_id, lon=lon, lat=0.0, gauges_mm=gauges)


class TestSnapping:
    # Barcelona-Sants' nearest catalog stop is Iberian-gauge only; with a
    # nearest-stop helper its standard-gauge snap failed on a good stop.
    STOPS = {
        s.stop_id: s
        for s in [
            _stop("sants", 0.0, [1435, 1668]),
            _stop("iberian", 0.1, [1668]),
            _stop("cut_off", 0.2, [1435]),
            _stop("figueres", 0.5, [1435]),
            _stop("unknown", 0.6, None),
            _stop("off_network", 5.0, [1435]),
        ]
    }

    def test_helpers_carry_the_profile_gauge_nearest_first(self):
        helpers = snap_helpers(self.STOPS["sants"], self.STOPS, 1435)
        # Wrong gauge and unknown gauge are no basis for a snap.
        assert [h.stop_id for h in helpers] == ["cut_off", "figueres", "off_network"]

    def test_next_helper_is_tried_when_the_connection_fails(self, tmp_path):
        router = _SnapRouter(disconnected={0.2})
        snapped, errors = snap_needed(
            router, self.STOPS, {("sants", "night_train")}, tmp_path / "s.csv"
        )
        assert ("sants", "night_train") in snapped and not errors
        assert router.calls == [(0.0, 0.2), (0.0, 0.5)]

    def test_a_stop_off_the_network_gives_up_after_one_call(self, tmp_path):
        router = _SnapRouter(off_network={5.0})
        snapped, errors = snap_needed(
            router, self.STOPS, {("off_network", "night_train")}, tmp_path / "s.csv"
        )
        assert not snapped
        assert "point 0" in errors[("off_network", "night_train")]
        assert len(router.calls) == 1


class TestFinalize:
    def test_counts_rows_and_writes_a_readable_gzip(self, tmp_path):
        out = tmp_path / "route_segments_test.csv"
        _write(out, [_row(f"s{i}", f"s{i + 1}", "v1", 500) for i in range(40)])

        finalize(out, {}, "infra_test", "2026-09-13T00:01:42Z", 300, 41)

        meta = json.loads(out.with_suffix(".meta.json").read_text(encoding="utf-8"))
        assert meta["n_segments"] == 40
        gz = out.with_suffix(".csv.gz")
        with gzip.open(gz, "rb") as fh:
            assert fh.read() == out.read_bytes()


class TestResumeSources:
    def test_a_failures_report_is_not_read_as_segments(self, tmp_path):
        # Same column count, same leading three columns — without the header
        # check every failed pair would count as done and never be retried.
        report = tmp_path / "route_segments_test.failures.csv"
        write_failures(
            report,
            {},
            [("a", "b", "night_train", "v1")],
            {("a", "night_train"): "Cannot find point 0"},
        )
        assert read_segment_keys(report) == set()

    def test_a_directory_yields_segment_files_once(self, tmp_path):
        _write(tmp_path / "route_segments_x.csv", [_row("a", "b", "v1")])
        (tmp_path / "route_segments_x.csv.gz").write_bytes(b"")
        (tmp_path / "route_segments_x.snapped.csv").write_text("", encoding="utf-8")
        (tmp_path / "route_segments_x.failures.csv").write_text("", encoding="utf-8")
        _write(tmp_path / "route_segments_y.csv", [])
        (tmp_path / "route_segments_z.csv.gz").write_bytes(b"")

        names = [p.name for p in expand_resume_paths([tmp_path])]
        assert names == [
            "route_segments_x.csv",
            "route_segments_y.csv",
            "route_segments_z.csv.gz",
        ]


class TestWorkOrder:
    def test_pairs_come_shortest_first_within_the_cap(self):
        # Along the equator 1° of longitude is ~111 km.
        stops = {
            sid: _stop(sid, lon, [1435])
            for sid, lon in [("a", 0.0), ("b", 1.0), ("c", 3.0), ("d", 3.5)]
        }
        pairs = generate_pairs(stops, cap_km=300)

        assert list(pairs) == [("c", "d"), ("a", "b"), ("b", "c"), ("b", "d")]
        assert list(pairs.values()) == sorted(pairs.values())
        # a–c (~334 km) and a–d (~389 km) are outside the cap.
        assert ("a", "c") not in pairs
