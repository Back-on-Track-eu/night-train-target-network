"""
test_37_proposal_projection.py
================================
Pure-function tests (adapters/proposal/README.md §3.1/§5.4):
adapters/proposal/projection.py's route_fingerprint() and
build_summary_db_row(), models/evaluation/summary.py's
build_summary_row() (the shared §5.4 KPI derivation, WP10 step 5), plus
their wiring into POST /api/proposal/calc's response (route_fingerprint,
cache_hit, summary).

The schema-conformance case at the bottom inserts a
build_summary_db_row() row directly into proposals.proposal_summaries,
keeping this file focused purely on the projection functions —
endpoint-level coverage of the real summary writer (publish()) lives in
test_50. No commit happens anywhere
in this file — the autouse rollback_after_test fixture (conftest.py)
cleans up after every test.
"""

import json

import pytest

from adapters.proposal.projection import build_summary_db_row, route_fingerprint
from models.emissions.model import EMISSION_FACTORS
from models.evaluation.summary import build_summary_row
from adapters.proposal.repository import ProposalRepository
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
        from adapters.proposal.id_prefix import rewrite_id_prefix

        prefixed = rewrite_id_prefix(calc_response["route"], "R1", "P999_V1_R1")
        assert route_fingerprint(prefixed) == calc_response["route_fingerprint"]


class TestCacheHitFlag:
    def test_is_bool(self, calc_response):
        """Shape only — hit/miss semantics live in
        test_39_compute_cache.py, behind its own cache flush."""
        assert isinstance(calc_response["cache_hit"], bool)


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
            "country_relations",
            "stop_ids",
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
            "co2_g_per_pax_km",
        }

    def test_country_relations_are_served_pairs(self, row):
        """Relations come from od_pairs (boarding-capable origin before
        alighting-capable destination), so they are a subset of the pairs
        the route's own countries could form — a merely transited country
        contributes none. Sorted "AA__BB" keys, no self-pairs."""
        possible = {
            "__".join(sorted((a, b)))
            for a in row["countries"]
            for b in row["countries"]
            if a < b
        }
        assert set(row["country_relations"]) <= possible
        assert row["country_relations"] == sorted(row["country_relations"])

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

    def test_co2_is_the_flat_night_train_factor(self, row):
        """Decision 24 — the flat models/emissions factor until the
        energy-based, country-resolved model enriches it per route."""
        assert row["co2_g_per_pax_km"] == EMISSION_FACTORS["night_train"].g_per_pax_km

    def test_calc_response_summary_is_the_same_row(self, calc_response, row):
        """WP10 step 5 — the endpoint's "summary" block is built by the
        exact same build_summary_row() as this fixture, so the two must
        agree value for value (and neither carries geom_simplified)."""
        assert calc_response["summary"] == row


class TestSummaryDbRow:
    """build_summary_db_row() — the shared KPI row plus the DB-only
    geom_simplified (adapters/proposal/projection.py)."""

    @pytest.fixture(scope="class")
    def db_row(self, calc_response):
        return build_summary_db_row(calc_response["route"], calc_response["evaluation"])

    def test_is_kpi_row_plus_geometry(self, calc_response, db_row):
        kpi_row = build_summary_row(calc_response["route"], calc_response["evaluation"])
        assert set(db_row) == set(kpi_row) | {"geom_simplified"}
        assert {k: v for k, v in db_row.items() if k != "geom_simplified"} == kpi_row

    def test_geom_simplified_is_valid_multilinestring(self, db_row):
        geom = db_row["geom_simplified"]
        assert geom["type"] == "MultiLineString"
        assert len(geom["coordinates"]) >= 1
        for line in geom["coordinates"]:
            assert len(line) >= 2  # a LineString needs at least 2 points


class TestSummaryRowSchemaConformance:
    """Inserts a build_summary_db_row() row directly into
    proposals.proposal_summaries — proves the row shape actually
    satisfies the schema's NOT NULLs/types independently of the real
    publish path."""

    def test_row_inserts_cleanly(self, db_cur, calc_response):
        row = build_summary_db_row(calc_response["route"], calc_response["evaluation"])
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
                demand_kpis_placeholder, co2_g_per_pax_km
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
                %(demand_kpis_placeholder)s, %(co2_g_per_pax_km)s
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
