"""
Gauge routing against the live stack — the 0.9.27 behaviours that only the
real graph can prove: a broad-gauge trip routing on its own profile, an
impossible pairing answering 422 gauge_mismatch (not a snap error), a
router-level failure answering 422 routing_error (not a 500), and the
Belarus/Russia exclusion holding on a corridor that would otherwise cut
through Belarus.

Stops are selected from the seeded catalog BY GAUGE, not by hardcoded ids:
the catalog moves (2026-08 widening), and what these tests assert is the
gauge machinery, not any particular station's presence.
"""

import psycopg2.extras
import pytest
import requests

from tests.conftest import API_BASE
from tests.helpers import PROPOSAL_CALC_URL

CALC_URL = f"{API_BASE}{PROPOSAL_CALC_URL}"

# Generous: a broad-gauge fullRouting call does the same two-pass work as
# the suite's other routes, plus LM instead of CH for the custom-model pass.
CALC_TIMEOUT = 180


def _query_stops_by_gauge(db_conn, country_code: str, gauge_mm: int):
    """Current-base stops of a country supporting gauge_mm, south to north."""
    cur = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        """
        SELECT i.stop_id, i.stop_name, i.stop_lat
          FROM input_params.stop_infrastructures i
          JOIN scenario.scenarios s
            ON s.stop_infrastructures_version = i.stop_infra_version
         WHERE s.is_current_base
           AND i.country_code = %s
           AND i.gauges_mm @> ARRAY[%s]::integer[]
         ORDER BY i.stop_lat
        """,
        (country_code, gauge_mm),
    )
    rows = cur.fetchall()
    cur.close()
    return rows


def _stops_by_gauge(db_conn, country_code: str, gauge_mm: int, n: int = 2):
    """n well-separated stops (first and last by latitude — the longest
    available axis), or skip when the catalog cannot supply them. What
    these tests assert is the gauge machinery, not any station's presence."""
    rows = _query_stops_by_gauge(db_conn, country_code, gauge_mm)
    if len(rows) < n:
        pytest.skip(
            f"catalog has {len(rows)} {country_code} stops with "
            f"{gauge_mm} mm — need {n}"
        )
    return [rows[0], rows[-1]]


def _calc(stop_ids: list[str], **extra) -> requests.Response:
    body = {"stops": stop_ids, "composition_id": "NEW-BAL-7", **extra}
    return requests.post(CALC_URL, json=body, timeout=CALC_TIMEOUT)


def _route_any_pair(db_conn, country_code: str, gauge_mm: int, attempts: int = 6):
    """Route the first connected pair among a country's gauge_mm stops.

    Pairs are drawn from the stops CLOSEST TO THE COUNTRY'S CENTROID
    outward, not from the latitude extremes. A national network is not
    guaranteed connected in the graph, and the extremes are exactly where
    it breaks: Ukraine's four southernmost 1520 stops are all Crimean
    (Севастополь, Симферополь, Евпатория-Курорт, Керчь-Порт), and the
    peninsula is a separate component in the May 2026 extract — the
    Perekop and Chonhar lines north to Kherson are not routable, which
    OSM tagging since 2022 explains. Working outward from the centre
    reaches the core network first.

    The claim under test is that the gauge PROFILE routes this country's
    trips, not that any particular pair is reachable — so this tries
    several and fails naming every one it tried, which is how the Crimean
    component was identified in the first place.
    """
    rows = _query_stops_by_gauge(db_conn, country_code, gauge_mm)
    if len(rows) < 2:
        pytest.skip(f"catalog has {len(rows)} {country_code} {gauge_mm} mm stops")

    mid_lat = (float(rows[0]["stop_lat"]) + float(rows[-1]["stop_lat"])) / 2
    central = sorted(rows, key=lambda r: abs(float(r["stop_lat"]) - mid_lat))

    tried = []
    for offset in range(min(attempts, len(central) // 2)):
        a, b = central[2 * offset], central[2 * offset + 1]
        resp = _calc([a["stop_id"], b["stop_id"]])
        if resp.status_code == 200:
            return resp, a, b
        tried.append(
            f"{a['stop_name']} -> {b['stop_name']}: "
            f"{resp.status_code} {resp.text[:120]}"
        )
    pytest.fail(
        f"no connected {gauge_mm} mm pair in {country_code} after "
        f"{len(tried)} attempts:\n  " + "\n  ".join(tried)
    )


class TestBroadGaugeRoutes:
    """The headline capability: trips that failed as snap errors before
    0.9.27 now route on their own gauge profile."""

    def test_finnish_1524_routes_and_reports_the_family(self, db_conn):
        resp, south, north = _route_any_pair(db_conn, "FI", 1524)
        trips = resp.json()["route"]["trip_pairs"][0]
        # Both directions: the return trip resolves its own gauge from the
        # reversed stop list, and must land on the same profile. Finnish
        # stops are tagged 1524, which folds into the 1520 family — the
        # reported gauge is the family representative the trip routed on.
        for direction in ("outbound", "return_trip"):
            general = trips[direction]["general_parameters"]
            assert general["track_gauge_mm"] == 1520
            assert general["trip_km"] > 50

    def test_ukrainian_1520_routes(self, db_conn):
        resp, _, _ = _route_any_pair(db_conn, "UA", 1520)
        general = resp.json()["route"]["trip_pairs"][0]["outbound"][
            "general_parameters"
        ]
        assert general["track_gauge_mm"] == 1520

    def test_standard_gauge_reports_1435(self, db_conn):
        resp, _, _ = _route_any_pair(db_conn, "DE", 1435)
        general = resp.json()["route"]["trip_pairs"][0]["outbound"][
            "general_parameters"
        ]
        assert general["track_gauge_mm"] == 1435


class TestGaugeMismatch:
    def test_1520_against_1435_is_422_gauge_mismatch(self, db_conn):
        ua = _stops_by_gauge(db_conn, "UA", 1520, n=1)[0]
        de = _stops_by_gauge(db_conn, "DE", 1435, n=1)[0]
        resp = _calc([ua["stop_id"], de["stop_id"]])
        assert resp.status_code == 422, resp.text[:400]
        body = resp.json()
        # The dedicated error, not the generic domain_error — the frontend
        # marks stops from conflicting_stops.
        assert body["error"] == "gauge_mismatch"
        conflicting = body["conflicting_stops"]
        assert conflicting[ua["stop_id"]] == [1520]
        assert 1435 in conflicting[de["stop_id"]]

    def test_mismatch_beats_the_router(self, db_conn):
        # The pre-check must answer before any routing happens — the
        # message names stops and gauges, never a snapping failure.
        ua = _stops_by_gauge(db_conn, "UA", 1520, n=1)[0]
        de = _stops_by_gauge(db_conn, "DE", 1435, n=1)[0]
        resp = _calc([ua["stop_id"], de["stop_id"]])
        message = resp.json()["message"].lower()
        assert "snap" not in message
        assert "gauge" in message


class TestRoutingErrorIsNotA500:
    def test_unroutable_pair_is_422_routing_error(self, db_conn):
        """A Ukraine ↔ Baltic 1520 pair: same gauge on both ends, but the
        two networks connect only through Belarus, which 0.9.27 hard-
        blocks. The router must answer "no connection" and the API must
        turn that into 422 routing_error — one test, two proofs: the
        RailRoutingError arm exists, and the Belarus exclusion holds. A
        200 here would mean a route exists, i.e. the block failed."""
        ua = _stops_by_gauge(db_conn, "UA", 1520, n=1)[0]
        baltic = None
        for cc in ("LT", "LV", "EE"):
            rows = _query_stops_by_gauge(db_conn, cc, 1520)
            if rows:
                baltic = rows[0]
                break
        if baltic is None:
            pytest.skip("no Baltic 1520 stop in the catalog")
        resp = _calc([ua["stop_id"], baltic["stop_id"]])
        assert resp.status_code == 422, (
            f"expected 422, got {resp.status_code}: {resp.text[:400]} — "
            "a 200 here means the route found a path, i.e. the "
            "Belarus/Russia exclusion did NOT hold"
        )
        body = resp.json()
        assert body["error"] == "routing_error", body
        assert "something went wrong" not in body["message"].lower()


class TestAutoStopGaugeFilter:
    def test_no_gauge_foreign_stop_is_ever_auto_added(self, db_conn):
        # Any broad-gauge trip with auto_stop_addition="add": every stop
        # of the result must support the trip's gauge. Data-driven — the
        # concrete corridor doesn't matter, the invariant does.
        # Same connectivity-aware selection as the routing tests — this
        # test is about the gauge filter, not about which pair connects.
        # Reuse the connectivity-aware selection, then re-route the same
        # pair with auto-stop addition on — this test is about the gauge
        # filter, not about which pair connects.
        _, a, b = _route_any_pair(db_conn, "FI", 1524)
        resp = _calc([a["stop_id"], b["stop_id"]], auto_stop_addition="add")
        assert resp.status_code == 200, resp.text[:400]
        route = resp.json()["route"]
        stop_ids = [
            s["stop_id"]
            for seg in route["trip_pairs"][0]["outbound"]["segments"]
            for s in (seg["from_stop"], seg["to_stop"])
        ]
        cur = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT i.stop_id, i.gauges_mm
              FROM input_params.stop_infrastructures i
              JOIN scenario.scenarios s
                ON s.stop_infrastructures_version = i.stop_infra_version
             WHERE s.is_current_base AND i.stop_id = ANY(%s)
            """,
            (stop_ids,),
        )
        gauges = {r["stop_id"]: r["gauges_mm"] for r in cur.fetchall()}
        cur.close()
        family = {1520, 1524}  # GAUGE_FAMILY_MM — either tag supports the trip
        for stop_id in stop_ids:
            assert gauges.get(stop_id) and family & set(gauges[stop_id]), (
                f"{stop_id} on a 1520-family trip without 1520/1524 support "
                f"(gauges: {gauges.get(stop_id)})"
            )
