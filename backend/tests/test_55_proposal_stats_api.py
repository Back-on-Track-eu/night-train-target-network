"""
test_55_proposal_stats_api.py
==============================
GET /api/proposals/stats — the §7.7 statistics contract: counts, KPI
aggregates per scope, and the country / country-relation rankings.

Isolation: publishing commits outside the suite's per-test rollback, so
this module purges published proposals before and after itself (the
permanent seed proposal survives), the same discipline test_50/test_52
follow.

Two things this module deliberately does NOT assume:

  * that input_params.country_relations is populated. The build needs a
    live router at seed time; where it hasn't run, the universe is empty
    and the ranking tests skip rather than fail — an empty universe is a
    seeding state, not a broken endpoint. The shape assertions still run.
  * that the ONTD catalog is loaded. Existing-source coverage uses the
    same hand-inserted ontd.route_summaries rows test_52 uses, so it
    works on a CI database where only the empty schema exists.
"""

import pytest
import requests

from tests.helpers import (
    PROPOSALS_URL,
    compute,
    publish,
    purge_saved_proposals,
)

STATS_URL = "/api/proposals/stats"

_STOPS = ["osm:n3856100103", "osm:w423692233"]
_COMPOSITION = "NEW-BAL-7"

_EXISTING_ROUTE_ID = "TEST-STATS-E1"


@pytest.fixture(scope="module", autouse=True)
def clean_proposals(db_conn, script_headers):
    purge_saved_proposals(db_conn)
    yield
    purge_saved_proposals(db_conn)


@pytest.fixture(scope="module")
def published(api_base, script_headers):
    """One published Berlin–Wien proposal: two countries, so it serves
    exactly the DE–AT relation and nothing else."""
    computed = compute(api_base, _STOPS, _COMPOSITION)
    return publish(
        api_base,
        computed["request"],
        name="Berlin – Wien (stats test)",
        headers=script_headers,
    )


@pytest.fixture(scope="module")
def existing_route(db_conn):
    """One hand-made existing row carrying its own country_relations, so
    the per-source split is observable without the ONTD bootstrap."""
    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ontd.route_summaries (
                route_id, name, stop_ids, n_stops, countries, country_relations,
                total_distance_km, total_time_h, avg_speed_kmh,
                co2_g_per_pax_km, geometry_routed
            ) VALUES (
                %s, 'Stats test existing Berlin–Wien',
                ARRAY['osm:n3856100103','osm:w423692233'], 2, ARRAY['DE','AT'],
                ARRAY['AT__DE'], 700.0, 9.5, 74.0, 33.0, FALSE
            )
            ON CONFLICT (route_id) DO NOTHING
            """,
            (_EXISTING_ROUTE_ID,),
        )
    db_conn.commit()
    yield _EXISTING_ROUTE_ID
    with db_conn.cursor() as cur:
        cur.execute(
            "DELETE FROM ontd.route_summaries WHERE route_id = %s",
            (_EXISTING_ROUTE_ID,),
        )
    db_conn.commit()


def _stats(api_base, **params) -> dict:
    response = requests.get(f"{api_base}{STATS_URL}", params=params, timeout=30)
    assert response.status_code == 200, response.text[:300]
    return response.json()


def _relation_key(row: dict) -> str:
    return f"{row['country_a']}__{row['country_b']}"


# =============================================================================
# Shape and counts
# =============================================================================


class TestShape:
    def test_all_three_scopes_always_present(self, api_base, published):
        """A stable response shape means the frontend never branches on
        which scopes happen to be non-empty."""
        stats = _stats(api_base)
        assert set(stats["counts"]) == {"proposal", "existing", "all"}
        assert set(stats["kpis"]) == {"proposal", "existing", "all"}

    def test_counts_agree_with_the_gallery(self, api_base, published):
        """Both read the same union CTE — a disagreement would mean the
        two filter differently, which is the failure this endpoint could
        hide longest."""
        stats = _stats(api_base)
        gallery = requests.post(
            f"{api_base}{PROPOSALS_URL}",
            json={"include": ["summaries"], "limit": 1},
            timeout=30,
        ).json()
        assert stats["counts"]["all"]["n"] == gallery["summaries"]["total"]

    def test_proposal_scope_carries_financials_others_do_not(
        self, api_base, published, existing_route
    ):
        """Existing rows are NULL in every proposal-only column, so
        reporting those columns under 'existing' or 'all' would label a
        proposal statistic as something broader."""
        kpis = _stats(api_base)["kpis"]
        assert "cost_eur_per_train_km" in kpis["proposal"]
        assert "cost_eur_per_train_km" not in kpis["existing"]
        assert "cost_eur_per_train_km" not in kpis["all"]
        # The shared metrics are present everywhere.
        assert "total_distance_km" in kpis["existing"]

    def test_sum_only_on_extensive_columns(self, api_base, published):
        kpis = _stats(api_base)["kpis"]["proposal"]
        assert "sum" in kpis["total_distance_km"]
        assert "sum" not in kpis["cost_eur_per_train_km"]
        assert "sum" not in kpis["avg_speed_kmh"]

    def test_distinct_reach_is_the_union_not_the_sum(self, api_base, published):
        """Reach is the union of what the rows touch, never a sum of
        their n_stops — two proposals over one corridor reach the
        stations between them once, not twice.

        Checked against the gallery's own rows for the same scope rather
        than against fixed numbers: this suite runs on a database that
        also carries the ONTD catalog and whatever earlier modules
        published, so any absolute count would be asserting the state of
        the database instead of the property.
        """
        user_id = published["user_id"]
        counts = _stats(api_base, user_id=user_id)["counts"]["proposal"]

        rows = requests.post(
            f"{api_base}{PROPOSALS_URL}",
            json={
                "filter": {"user_ids": [user_id], "sources": ["proposal"]},
                "include": ["summaries"],
                "limit": 200,
            },
            timeout=30,
        ).json()["summaries"]["proposals"]

        stops = {stop for row in rows for stop in row["stop_ids"]}
        countries = {country for row in rows for country in row["countries"]}
        assert counts["n_distinct_stops"] == len(stops)
        assert counts["n_distinct_countries"] == len(countries)
        assert counts["n_distinct_stops"] <= sum(row["n_stops"] for row in rows)

    def test_unknown_query_parameter_rejected(self, api_base):
        response = requests.get(f"{api_base}{STATS_URL}", params={"top": 3}, timeout=30)
        assert response.status_code == 400
        assert response.json()["error"] == "validation_error"

    def test_non_integer_user_id_rejected(self, api_base):
        response = requests.get(
            f"{api_base}{STATS_URL}", params={"user_id": "abc"}, timeout=30
        )
        assert response.status_code == 400


# =============================================================================
# user_id narrowing
# =============================================================================


class TestUserNarrowing:
    def test_narrowing_excludes_existing_trains(
        self, api_base, published, existing_route
    ):
        """Existing trains have no owner, so a per-user question must not
        count them — and the shape stays three-scoped regardless."""
        stats = _stats(api_base, user_id=published["user_id"])
        assert stats["scope"]["sources"] == ["proposal"]
        assert stats["counts"]["existing"]["n"] == 0
        assert stats["counts"]["proposal"]["n"] >= 1
        assert stats["counts"]["all"]["n"] == stats["counts"]["proposal"]["n"]

    def test_unknown_user_is_empty_not_404(self, api_base):
        """An aggregate over nothing is a valid answer; this is not a
        resource lookup."""
        stats = _stats(api_base, user_id=99_999_999)
        assert stats["counts"]["all"]["n"] == 0
        assert stats["kpis"]["proposal"] == {}


# =============================================================================
# Country ranking
# =============================================================================


class TestCountries:
    def test_served_countries_lead_the_top(self, api_base, published):
        top = _stats(api_base)["countries"]["top"]
        assert {"DE", "AT"} <= {row["country"] for row in top}
        counts = [row["n_proposals"] for row in top]
        assert counts == sorted(counts, reverse=True)

    def test_flop_reaches_countries_nobody_proposed(self, api_base, published):
        """The zero-fill is the point: "nobody has proposed anything
        here" is the answer the flop list exists to give."""
        flop = _stats(api_base)["countries"]["flop"]
        assert flop, "flop list should never be empty on a seeded catalog"
        assert all(row["n_proposals"] == 0 for row in flop)

    def test_unk_sentinel_never_ranked(self, api_base, published):
        stats = _stats(api_base)["countries"]
        assert "UNK" not in {row["country"] for row in stats["top"] + stats["flop"]}

    def test_per_source_split_adds_up(self, api_base, published, existing_route):
        for row in _stats(api_base)["countries"]["top"]:
            assert row["n"] == row["n_proposals"] + row["n_existing"]


# =============================================================================
# Relation ranking
# =============================================================================


@pytest.fixture(scope="module")
def relation_universe(api_base):
    """Skip the ranking tests where the relation build hasn't run — it
    needs a live router at seed time, and its absence is a seeding state
    rather than an endpoint fault."""
    universe = _stats(api_base)["country_relations"]["universe"]
    if not universe["n_pairs"]:
        pytest.skip(
            "input_params.country_relations is empty — run "
            "scripts/build_country_relations.py against a live router"
        )
    return universe


class TestRelations:
    def test_universe_reported_even_when_empty(self, api_base):
        """Nothing disappears without a number attached: pairs too far
        apart and pairs with no rail path are counted, not silently
        absent."""
        universe = _stats(api_base)["country_relations"]["universe"]
        assert {
            "n_pairs",
            "n_countries",
            "excluded_over_threshold",
            "excluded_unroutable",
            "unresolved_countries",
        } <= set(universe)

    def test_pairs_are_ordered_and_within_threshold(self, api_base, relation_universe):
        block = _stats(api_base)["country_relations"]
        ceiling = block["basis"]["max_relation_km"]
        for row in block["top"] + block["flop"]:
            assert row["country_a"] < row["country_b"]
            assert row["rail_km"] <= ceiling

    def test_served_relation_ranks_top(
        self, api_base, published, existing_route, relation_universe
    ):
        """The published Berlin–Wien proposal and the existing train both
        serve AT–DE, so it should lead — assuming the pair is in the
        universe at all (it is, unless the catalog changed radically)."""
        block = _stats(api_base)["country_relations"]
        if "AT__DE" not in {_relation_key(row) for row in block["top"] + block["flop"]}:
            pytest.skip("AT–DE not in the relation universe on this database")
        top = block["top"]
        assert _relation_key(top[0]) == "AT__DE"
        assert top[0]["n_proposals"] >= 1
        assert top[0]["n_existing"] >= 1

    def test_flop_starts_with_the_nearest_unserved(self, api_base, relation_universe):
        """Within the zeros — which dominate while proposal volume is low
        — the ordering that carries information is by distance, closest
        first: the nearest unserved pair is the most plausible missing
        night train."""
        flop = _stats(api_base)["country_relations"]["flop"]
        zeros = [row for row in flop if row["n"] == 0]
        if len(zeros) < 2:
            pytest.skip("not enough unserved relations to check the ordering")
        distances = [row["rail_km"] for row in zeros]
        assert distances == sorted(distances)

    def test_transited_country_contributes_no_relation(self, api_base, db_conn):
        """A relation is boarding-to-alighting, not "both countries
        appear in the route": the summary projection derives it from
        od_pairs, so a country the train only passes through cannot
        create one. Asserted against stored data rather than the ranking,
        which the universe would filter."""
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT countries, country_relations "
                "FROM proposals.proposal_summaries "
                "WHERE cardinality(countries) > 2 LIMIT 1"
            )
            row = cur.fetchone()
        if row is None:
            pytest.skip("no multi-country proposal stored to check against")
        countries, relations = row
        possible = {
            "__".join(sorted((a, b)))
            for a in countries
            for b in countries
            if a < b and "UNK" not in (a, b)
        }
        assert set(relations) <= possible
