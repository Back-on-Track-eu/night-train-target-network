"""Verdict logic. The exit code is a gate, so the truth table is a test.

Two of these guard bugs that were live in the tool this replaces: a baseline
outage reading as PASS, and a run where every probe reported SAME exiting 0.
"""

from __future__ import annotations

from osm_pipe.verify import FAILING, UNTESTABLE, RouteResult, _passes_through, _verdict
from osm_pipe.geo import BBox

OK_VIA = RouteResult(ok=True, distance_km=340, time_min=201, via=True)
OK_NOT_VIA = RouteResult(ok=True, distance_km=471, time_min=323, via=False)
DOWN = RouteResult(ok=False, error="connection refused")


def test_pass_when_only_the_target_goes_through():
    assert _verdict(OK_NOT_VIA, OK_VIA) == "PASS"


def test_already_when_both_go_through():
    # An already-open project, or a via_bbox wide enough to catch the old
    # alignment too. Koralm should report this at every date.
    assert _verdict(OK_VIA, OK_VIA) == "ALREADY"


def test_same_when_the_path_did_not_move():
    assert _verdict(OK_NOT_VIA, OK_NOT_VIA) == "SAME"


def test_same_is_a_failure():
    # The silent no-op this stage exists to catch. Letting it exit 0 made the
    # whole check decorative.
    assert "SAME" in FAILING


def test_fail_when_the_target_lost_a_route_the_baseline_had():
    assert _verdict(OK_NOT_VIA, DOWN) == "FAIL"


def test_no_route_when_neither_side_routes():
    assert _verdict(DOWN, DOWN) == UNTESTABLE


def test_no_route_is_not_counted_as_a_failure():
    # On a country extract it is the normal answer for every project outside
    # the region, and counting it would make the gate useless there.
    assert UNTESTABLE not in FAILING


def test_a_baseline_outage_is_not_a_pass():
    # The bug this guards: a down baseline reports ok=False and therefore
    # via=False, which reads as "the baseline does not go this way".
    assert _verdict(DOWN, OK_VIA) == "BASELINE ERROR"
    assert "BASELINE ERROR" in FAILING


def test_passes_through_reads_lon_lat():
    # GraphHopper returns [lon, lat] with points_encoded false.
    box = BBox(54.30, 10.90, 54.80, 11.65)
    assert _passes_through([[11.2, 54.5]], box)
    assert not _passes_through([[54.5, 11.2]], box)


def test_passes_through_survives_elevation():
    # With elevation enabled GraphHopper returns [lon, lat, ele]. Unpacking a
    # fixed pair would raise rather than degrade.
    box = BBox(54.30, 10.90, 54.80, 11.65)
    assert _passes_through([[11.2, 54.5, 12.0]], box)


def test_passes_through_ignores_malformed_points():
    box = BBox(54.30, 10.90, 54.80, 11.65)
    assert not _passes_through([[11.2]], box)
