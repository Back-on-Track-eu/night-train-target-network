"""
test_37_proposal_projection.py
================================
Pure-function tests for WP4 (docs/PROPOSALS_DESIGN.md §3.1/§5.4):
adapters/proposal_projection.py's route_fingerprint() and
build_summary_row(), plus the fingerprint's wiring into
POST /api/proposal/calc's response (route_fingerprint, cache_hit).

No publish endpoint exists yet (WP5) — the schema-conformance case at the
bottom inserts a build_summary_row() row directly into the still-empty
proposals.proposal_summaries table (landed by WP1), the same way
test_36_proposal_gtfs_roundtrip.py exercises WP3's write path ahead of
WP5's cutover. No commit happens anywhere in this file — the session-
scoped autouse rollback_after_test fixture (conftest.py) cleans up after
every test.
"""

import json

import pytest

from adapters.proposal_projection import route_fingerprint, build_summary_row
from adapters.proposal_repository import ProposalRepository
from tests.conftest import STOPS_BERLIN_DRESDEN_WIEN, STOPS_BERLIN_WIEN
from tests.helpers import compute

BASE_REQUEST = {
    "stops": STOPS_BERLIN_DRESDEN_WIEN,
    "composition_id": "NEW-BAL-7",
    "auto_stop_addition": "off",
}


@pytest.fixture(scope="module")
def calc_response(api_base):
    return compute(api_base, **BASE_REQUEST)


# =============================================================================
# route_fingerprint() — §3.1
# =============================================================================


class TestFingerprint:
    def test_present_and_well_formed(self, calc_response):
        fp = calc_response["route_fingerprint"]
        assert fp.startswith("sha256:")
        assert len(fp) == len("sha256:") + 64

    def test_deterministic_across_identical_requests(self, api_base):
        """Same route, computed twice, must fingerprint identically —
        stop times and geometry are deterministic outputs of the route
        builder for a fixed request."""
        first = compute(api_base, **BASE_REQUEST)
        second = compute(api_base, **BASE_REQUEST)
        assert first["route_fingerprint"] == second["route_fingerprint"]

    def test_differs_for_a_different_route(self, api_base):
        other = compute(
            api_base,
            stops=STOPS_BERLIN_WIEN,
            composition_id="NEW-BAL-7",
            auto_stop_addition="off",
        )
        first = compute(api_base, **BASE_REQUEST)
        assert first["route_fingerprint"] != other["route_fingerprint"]

    def test_matches_direct_call_on_route_dict(self, calc_response):
        """The endpoint's route_fingerprint must be exactly what calling
        route_fingerprint() on the returned route dict produces — the
        response isn't computing it some other way."""
        assert calc_response["route_fingerprint"] == route_fingerprint(
            calc_response["route"]
        )

    def test_ignores_id_prefix(self, calc_response):
        """§3.1: ephemeral (neutral R1_... ids) and published
        (P{id}_V{n}_R1_... ids) forms of the identical route must hash
        identically — the canonical extract never reads route_id/trip_id/
        geometry_id, only stop_id, so re-prefixing the route dict must
        not change the fingerprint."""
        from adapters.proposal_repository import rewrite_id_prefix

        prefixed = rewrite_id_prefix(calc_response["route"], "R1", "P999_V1_R1")
        assert route_fingerprint(prefixed) == calc_response["route_fingerprint"]


class TestCacheHitPlaceholder:
    def test_always_false(self, calc_response):
        """No compute cache exists yet (WP13) — every call is a fresh
        compute, so cache_hit is always false rather than absent."""
        assert calc_response["cache_hit"] is False


# =============================================================================
# build_summary_row() — §5.4
# =============================================================================


class TestSummaryRow:
    @pytest.fixture(scope="class")
    def row(self, calc_response):
        return build_summary_row(calc_response["route"], calc_response["evaluation"])

    def test_has_every_non_identity_column(self, row):
        assert set(row) == {
            "total_distance_km",
            "total_time_h",
            "avg_speed_kmh",
            "n_stops",
            "countries",
            "stop_ids",
            "geom_simplified",
            "cost_eur_per_train_km",
            "revenue_eur_per_train_km",
            "margin_eur_per_train_km",
            "subsidy_eur_per_year",
            "demand_trips_per_year",
            "demand_trip_km_per_year",
            "shift_air_trips_per_year",
            "shift_air_trip_km_per_year",
            "shift_car_trips_per_year",
            "shift_car_trip_km_per_year",
            "co2_savings_t_per_year",
            "subsidy_eur_per_t_co2",
            "demand_kpis_placeholder",
        }

    def test_route_metrics_are_plausible(self, row):
        assert row["total_distance_km"] > 0
        assert row["total_time_h"] > 0
        assert row["avg_speed_kmh"] > 0
        assert row["n_stops"] == 3  # Berlin, Dresden, Wien
        assert row["countries"] == sorted(row["countries"])
        assert len(row["stop_ids"]) == row["n_stops"]

    def test_financial_kpis_match_evaluation_views(self, calc_response, row):
        route_data = calc_response["evaluation"]["views"]["route"]["data"]
        per_train_km = route_data["per_train_km"]["all"]
        per_year = route_data["per_year"]["all"]
        assert row["cost_eur_per_train_km"] == round(per_train_km["total_cost_eur"], 2)
        assert row["revenue_eur_per_train_km"] == round(
            per_train_km["total_revenue_eur"], 2
        )
        assert row["margin_eur_per_train_km"] == round(per_train_km["net_eur"], 2)
        assert row["subsidy_eur_per_year"] == round(max(0.0, -per_year["net_eur"]), 2)

    def test_demand_kpis_are_placeholder(self, row):
        assert row["demand_kpis_placeholder"] is True
        assert row["demand_trips_per_year"] >= 0
        assert row["demand_trip_km_per_year"] >= 0
        assert row["co2_savings_t_per_year"] >= 0

    def test_geom_simplified_is_valid_multilinestring(self, row):
        geom = row["geom_simplified"]
        assert geom["type"] == "MultiLineString"
        assert len(geom["coordinates"]) >= 1
        for line in geom["coordinates"]:
            assert len(line) >= 2  # a LineString needs at least 2 points


class TestSummaryRowSchemaConformance:
    """Inserts a build_summary_row() row directly into
    proposals.proposal_summaries (WP1's still-empty table) — proves the
    row shape actually satisfies the schema's NOT NULLs/types ahead of
    WP5 wiring the real publish path."""

    def test_row_inserts_cleanly(self, db_cur, calc_response):
        row = build_summary_row(calc_response["route"], calc_response["evaluation"])
        proposal_id = ProposalRepository._next_proposal_id(db_cur)

        params = {
            "proposal_id": proposal_id,
            "proposal_version": 1,
            "user_id": None,
            "route_fingerprint": calc_response["route_fingerprint"],
            "composition_id": calc_response["request"]["composition_id"],
            "scenario_id": calc_response["request"]["scenario_id"],
            "name": "WP4 schema-conformance test row",
            "route_builder_version": calc_response["route_builder_version"],
            "calc_version": calc_response["calc_version"],
            "geom_simplified": json.dumps(row["geom_simplified"]),
            **{k: v for k, v in row.items() if k != "geom_simplified"},
        }

        db_cur.execute(
            """
            INSERT INTO proposals.proposal_summaries (
                proposal_id, proposal_version, user_id, route_fingerprint,
                composition_id, scenario_id, name, route_builder_version,
                calc_version, total_distance_km, total_time_h, avg_speed_kmh,
                n_stops, countries, stop_ids, geom_simplified,
                cost_eur_per_train_km, revenue_eur_per_train_km,
                margin_eur_per_train_km, subsidy_eur_per_year,
                demand_trips_per_year, demand_trip_km_per_year,
                shift_air_trips_per_year, shift_air_trip_km_per_year,
                shift_car_trips_per_year, shift_car_trip_km_per_year,
                co2_savings_t_per_year, subsidy_eur_per_t_co2,
                demand_kpis_placeholder
            ) VALUES (
                %(proposal_id)s, %(proposal_version)s, %(user_id)s, %(route_fingerprint)s,
                %(composition_id)s, %(scenario_id)s, %(name)s, %(route_builder_version)s,
                %(calc_version)s, %(total_distance_km)s, %(total_time_h)s, %(avg_speed_kmh)s,
                %(n_stops)s, %(countries)s, %(stop_ids)s,
                ST_SetSRID(ST_GeomFromGeoJSON(%(geom_simplified)s), 4326),
                %(cost_eur_per_train_km)s, %(revenue_eur_per_train_km)s,
                %(margin_eur_per_train_km)s, %(subsidy_eur_per_year)s,
                %(demand_trips_per_year)s, %(demand_trip_km_per_year)s,
                %(shift_air_trips_per_year)s, %(shift_air_trip_km_per_year)s,
                %(shift_car_trips_per_year)s, %(shift_car_trip_km_per_year)s,
                %(co2_savings_t_per_year)s, %(subsidy_eur_per_t_co2)s,
                %(demand_kpis_placeholder)s
            )
            """,
            params,
        )

        db_cur.execute(
            "SELECT n_stops, ST_GeometryType(geom_simplified) AS geom_type "
            "FROM proposals.proposal_summaries WHERE proposal_id = %s",
            (proposal_id,),
        )
        stored = db_cur.fetchone()
        assert stored["n_stops"] == row["n_stops"]
        assert stored["geom_type"] == "ST_MultiLineString"
