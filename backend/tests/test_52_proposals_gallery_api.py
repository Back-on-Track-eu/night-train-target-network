"""
test_52_proposals_gallery_api.py
=================================
POST /api/proposals — the full §7.1 gallery/map filter contract (WP6):
generic range/list/array/substring filters over proposal_summaries,
trip_windows, bbox, sort, windowed total, and the sectioned `include`
response.

test_50_proposals_api.py keeps the basic sectioned-envelope smoke tests
(user_ids filter, pagination, unknown-key rejection); this module is the
one-filter-of-each-kind + map-sections coverage WP6 adds on top.

Isolation: same discipline as test_50 — publishing commits outside the
suite's per-test rollback, so this module purges published proposals
before/after itself (the permanent seed proposal is preserved).
"""

import pytest
import requests

from tests.helpers import (
    PROPOSALS_URL,
    comment_url,
    compute,
    like_url,
    publish,
    purge_saved_proposals,
    stop_times,
)

_STOPS = ["osm:n3856100103", "osm:w423692233"]
_COMPOSITION = "NEW-BAL-7"


@pytest.fixture(scope="module", autouse=True)
def clean_proposals(db_conn, script_headers):
    purge_saved_proposals(db_conn)
    yield
    purge_saved_proposals(db_conn)


@pytest.fixture(scope="module")
def computed(api_base):
    """The raw compute response backing `published` — kept around so
    trip_windows tests can build an exact-match window from the real
    schedule rather than guessing."""
    return compute(api_base, _STOPS, _COMPOSITION)


@pytest.fixture(scope="module")
def published(api_base, script_headers, computed):
    return publish(
        api_base,
        computed["request"],
        name="Berlin \u2013 Wien (gallery test)",
        headers=script_headers,
    )


_EXISTING_ROUTE_IDS = ["TEST-GALLERY-E1", "TEST-GALLERY-E2"]


@pytest.fixture(scope="module")
def existing_routes(db_conn):
    """Two fake ontd.route_summaries rows (+ one corridor each) so the
    step-6b union has existing rows to return even where the ONTD
    bootstrap has never run (CI: seed.py only creates the empty schema).
    E1 shares the Berlin–Wien stop namespace with `published` so
    corridor/stop merging is observable; E2 is disjoint (FR). Committed
    (the API reads through its own connection) and deleted on teardown —
    same lifecycle pattern as purge_saved_proposals. geom_simplified is
    a real PostGIS geometry, matching the proposal projection's type."""
    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ontd.route_summaries (
                route_id, name, stop_ids, n_stops, countries,
                total_distance_km, total_time_h, avg_speed_kmh,
                co2_g_per_pax_km, geom_simplified, geometry_routed
            ) VALUES
            (%s, 'Gallery test existing Berlin–Wien',
             ARRAY['osm:n3856100103','osm:w423692233'], 2, ARRAY['DE','AT'],
             700.0, 9.5, 74.0, 33.0,
             ST_SetSRID(ST_GeomFromGeoJSON(
               '{"type":"MultiLineString","coordinates":[[[13.37,52.52],[16.37,48.19]]]}'
             ), 4326), FALSE),
            (%s, 'Gallery test existing FR',
             ARRAY['FR_PARIS_AUSTERLITZ','FR_TOULOUSE_MATABIAU'], 2, ARRAY['FR'],
             680.0, 7.0, 97.0, 33.0,
             ST_SetSRID(ST_GeomFromGeoJSON(
               '{"type":"MultiLineString","coordinates":[[[2.36,48.84],[1.45,43.61]]]}'
             ), 4326), FALSE)
            ON CONFLICT (route_id) DO NOTHING
            """,
            _EXISTING_ROUTE_IDS,
        )
        cur.execute(
            """
            INSERT INTO ontd.route_corridors (route_id, stop_a, stop_b, geometry)
            VALUES
            (%s, 'osm:w423692233', 'osm:n3856100103',
             '{"type":"LineString","coordinates":[[13.37,52.52],[16.37,48.19]]}'::jsonb),
            (%s, 'FR_PARIS_AUSTERLITZ', 'FR_TOULOUSE_MATABIAU',
             '{"type":"LineString","coordinates":[[2.36,48.84],[1.45,43.61]]}'::jsonb)
            ON CONFLICT (route_id, stop_a, stop_b) DO NOTHING
            """,
            _EXISTING_ROUTE_IDS,
        )
    db_conn.commit()
    yield _EXISTING_ROUTE_IDS
    with db_conn.cursor() as cur:
        cur.execute(
            "DELETE FROM ontd.route_corridors WHERE route_id = ANY(%s)",
            (_EXISTING_ROUTE_IDS,),
        )
        cur.execute(
            "DELETE FROM ontd.route_summaries WHERE route_id = ANY(%s)",
            (_EXISTING_ROUTE_IDS,),
        )
    db_conn.commit()


def _gallery(api_base, **body):
    resp = requests.post(f"{api_base}{PROPOSALS_URL}", json=body, timeout=15)
    assert resp.status_code == 200, resp.text[:300]
    return resp.json()


def _proposal_ids(gallery_response) -> set[int]:
    return {
        p["proposal_id"]
        for p in gallery_response["summaries"]["proposals"]
        if p["source"] == "proposal"
    }


def _row_keys(summary_rows) -> list[tuple]:
    """Row identity as (source, id), in list order — the two id spaces are
    unrelated, so the source has to be part of the key."""
    return [
        ("existing", r["route_id"])
        if r["source"] == "existing"
        else ("proposal", r["proposal_id"])
        for r in summary_rows
    ]


def _route_keys(map_routes_features) -> list[tuple]:
    """The same identity, read off map_routes features."""
    return [
        ("existing", f["properties"]["route_id"])
        if f["properties"]["source"] == "existing"
        else ("proposal", f["properties"]["proposal_id"])
        for f in map_routes_features
    ]


def _summary_row(api_base, published) -> dict:
    """The gallery row for one published proposal, fetched through the
    ordinary filter path (no dedicated by-id endpoint exists)."""
    body = _gallery(api_base, filter={"proposal_ids": [published["proposal_id"]]})
    return body["summaries"]["proposals"][0]


# =============================================================================
# One filter of each kind
# =============================================================================


class TestFilterKinds:
    def test_range_filter_matches(self, api_base, published):
        # summaries carries total_distance_km directly — read the real
        # value back once, then probe a range around it and one excluding
        # it. filter by proposal_ids (not user_ids) so the read-back can't
        # accidentally pick a different proposal of the same user should
        # one exist by this point in the module.
        summary = _gallery(
            api_base, filter={"proposal_ids": [published["proposal_id"]]}
        )["summaries"]["proposals"][0]
        km = summary["total_distance_km"]

        hit = _gallery(
            api_base, filter={"total_distance_km": {"min": km - 1, "max": km + 1}}
        )
        assert published["proposal_id"] in _proposal_ids(hit)

        miss = _gallery(api_base, filter={"total_distance_km": {"max": km - 1}})
        assert published["proposal_id"] not in _proposal_ids(miss)

    def test_list_filter_composition_ids(self, api_base, published):
        hit = _gallery(api_base, filter={"composition_ids": [_COMPOSITION]})
        assert published["proposal_id"] in _proposal_ids(hit)

        miss = _gallery(api_base, filter={"composition_ids": ["REF-BAL-9"]})
        assert published["proposal_id"] not in _proposal_ids(miss)

    def test_substring_name_filter(self, api_base, published):
        hit = _gallery(api_base, filter={"name": "wien"})  # case-insensitive
        assert published["proposal_id"] in _proposal_ids(hit)

        miss = _gallery(api_base, filter={"name": "nonexistent-corridor-xyz"})
        assert published["proposal_id"] not in _proposal_ids(miss)

    def test_array_overlap_countries_filter(self, api_base, published):
        hit = _gallery(api_base, filter={"countries": ["DE"]})
        assert published["proposal_id"] in _proposal_ids(hit)

        miss = _gallery(api_base, filter={"countries": ["XX"]})
        assert published["proposal_id"] not in _proposal_ids(miss)

    def test_array_overlap_stop_ids_filter(self, api_base, published):
        hit = _gallery(api_base, filter={"stop_ids": ["osm:n3856100103"]})
        assert published["proposal_id"] in _proposal_ids(hit)

    def test_proposal_ids_filter(self, api_base, published):
        hit = _gallery(api_base, filter={"proposal_ids": [published["proposal_id"]]})
        assert _proposal_ids(hit) == {published["proposal_id"]}

        miss = _gallery(api_base, filter={"proposal_ids": [-1]})
        assert published["proposal_id"] not in _proposal_ids(miss)

    def test_array_filter_any_vs_all_mode(self, api_base, script_headers):
        """countries: plain list / mode "any" is OR (overlap); mode "all"
        is AND (every listed country must be touched). Doesn't hardcode
        which real countries a corridor crosses (auto_stop_addition and
        in-transit country attribution — §5.4's country_distance_shares —
        both mean a route can touch countries beyond its named stops, e.g.
        Zurich sits near the DE/CH/FR tripoint); instead reads back the
        proposal's actual `countries` and builds the any/all cases from
        that plus one country code ("XX") guaranteed absent."""
        via_zuerich = publish(
            api_base,
            compute(
                api_base,
                ["osm:n3856100103", "osm:n1236383343", "osm:w423692233"],
                _COMPOSITION,
            )["request"],
            name="Berlin \u2013 Wien via Z\u00fcrich (gallery test)",
            headers=script_headers,
        )
        pid = via_zuerich["proposal_id"]
        summary = _gallery(api_base, filter={"proposal_ids": [pid]})["summaries"][
            "proposals"
        ][0]
        actual_countries = summary["countries"]
        assert len(actual_countries) >= 1

        any_hit = _gallery(api_base, filter={"countries": [actual_countries[0], "XX"]})
        assert pid in _proposal_ids(any_hit)

        all_hit = _gallery(
            api_base, filter={"countries": {"values": actual_countries, "mode": "all"}}
        )
        assert pid in _proposal_ids(all_hit)

        all_miss = _gallery(
            api_base,
            filter={"countries": {"values": actual_countries + ["XX"], "mode": "all"}},
        )
        assert pid not in _proposal_ids(all_miss)

    def test_array_filter_invalid_mode_rejected(self, api_base):
        resp = requests.post(
            f"{api_base}{PROPOSALS_URL}",
            json={"filter": {"countries": {"values": ["DE"], "mode": "sideways"}}},
            timeout=15,
        )
        assert resp.status_code == 400

    def test_created_at_range_filter(self, api_base, published):
        # filter by proposal_ids, not user_ids — by this point in the
        # module the same script user may own more than one proposal
        # (test_array_filter_any_vs_all_mode's via_zuerich), and the
        # default sort (updated_at DESC) would silently pick the wrong
        # one at index [0].
        created_at = _gallery(
            api_base, filter={"proposal_ids": [published["proposal_id"]]}
        )["summaries"]["proposals"][0]["created_at"]

        hit = _gallery(api_base, filter={"created_at": {"min": created_at}})
        assert published["proposal_id"] in _proposal_ids(hit)

        # a lower bound one year in the future excludes everything already seeded
        miss = _gallery(
            api_base, filter={"created_at": {"min": "2099-01-01T00:00:00+00:00"}}
        )
        assert published["proposal_id"] not in _proposal_ids(miss)

    def test_updated_at_range_filter(self, api_base, published):
        miss = _gallery(
            api_base, filter={"updated_at": {"max": "2000-01-01T00:00:00+00:00"}}
        )
        assert published["proposal_id"] not in _proposal_ids(miss)

    def test_version_and_scenario_filters_no_longer_accepted(self, api_base):
        """WP6.1: route_builder_version/calc_version/scenario_id are
        internal/analytical and every gallery row is always on the
        current base scenario by construction — none of the three are
        filterable anymore."""
        for key in ("route_builder_versions", "calc_versions", "scenario_ids"):
            resp = requests.post(
                f"{api_base}{PROPOSALS_URL}", json={"filter": {key: ["x"]}}, timeout=15
            )
            assert resp.status_code == 400, key

    def test_sources_unknown_rejected(self, api_base):
        resp = requests.post(
            f"{api_base}{PROPOSALS_URL}",
            json={"filter": {"sources": ["archive"]}},
            timeout=15,
        )
        assert resp.status_code == 400

    def test_sources_empty_rejected(self, api_base):
        resp = requests.post(
            f"{api_base}{PROPOSALS_URL}",
            json={"filter": {"sources": []}},
            timeout=15,
        )
        assert resp.status_code == 400


# =============================================================================
# Source union (WP10 step 6b)
# =============================================================================


class TestSourceUnion:
    """The gallery's proposal/existing union: sources filter, default
    BOTH, the reduced existing row shape, NULL-semantics exclusion, and
    the per-source + total counts on every map section."""

    def test_sources_existing_only(self, api_base, existing_routes):
        # name filter isolates the fixture rows deterministically — the
        # real ONTD catalog has ~200 existing rows, all NULL updated_at
        # (arbitrary tie order), so an unfiltered default-limit page
        # isn't guaranteed to contain any particular route_id.
        body = _gallery(
            api_base,
            filter={"sources": ["existing"], "name": "Gallery test existing"},
        )
        rows = body["summaries"]["proposals"]
        assert body["summaries"]["total"] >= 2
        assert all(r["source"] == "existing" for r in rows)
        by_id = {r["route_id"]: r for r in rows}
        assert set(existing_routes) <= set(by_id)
        row = by_id[existing_routes[0]]
        # Reduced descriptive shape — proposal-only keys OMITTED, not
        # null. country_relations belongs to the SHARED metric subset
        # (both projections derive it, §7.7): an existing train serves
        # country-to-country relations exactly as a proposal does, which
        # is what lets the statistics rank both sources on one axis.
        assert set(row) == {
            "source",
            "route_id",
            "name",
            "composition_id",
            "total_distance_km",
            "total_time_h",
            "avg_speed_kmh",
            "n_stops",
            "countries",
            "country_relations",
            "stop_ids",
            "co2_g_per_pax_km",
            "geometry_routed",
            "ontd_url",
        }
        assert row["geometry_routed"] is False
        assert row["ontd_url"].endswith(row["route_id"])

    def test_sources_default_is_both(self, api_base, existing_routes, published):
        body = _gallery(api_base)
        sources = {r["source"] for r in body["summaries"]["proposals"]}
        assert sources == {"proposal", "existing"}
        # Existing rows have NULL updated_at — NULLS LAST puts every
        # proposal before every existing row on the default sort.
        row_sources = [r["source"] for r in body["summaries"]["proposals"]]
        assert row_sources.index("existing") == row_sources.count("proposal")

    def test_sources_proposal_only_unchanged(self, api_base, existing_routes):
        body = _gallery(api_base, filter={"sources": ["proposal"]})
        assert all(r["source"] == "proposal" for r in body["summaries"]["proposals"])

    def test_financial_filter_excludes_existing(self, api_base, existing_routes):
        """Existing rows carry NULL financials — a margin range filter
        must exclude them via SQL NULL semantics, with no sources filter
        needed."""
        body = _gallery(
            api_base,
            filter={"margin_eur_per_train_km": {"min": -1_000_000}},
        )
        assert all(r["source"] == "proposal" for r in body["summaries"]["proposals"])

    def test_stop_ids_filter_spans_sources(self, api_base, existing_routes, published):
        """stop_ids is a shared Target Network namespace (step 6a) —
        one filter matches proposals AND existing routes over the same
        stop."""
        body = _gallery(api_base, filter={"stop_ids": ["osm:n3856100103"]})
        sources = {r["source"] for r in body["summaries"]["proposals"]}
        assert sources == {"proposal", "existing"}

    def test_map_lines_triple_counts_and_merge(
        self, api_base, existing_routes, published
    ):
        """The Berlin–Wien direct corridor is served by `published`'s
        endpoints AND fake existing route E1 — but a proposal's segments
        run between consecutive stops (incl. auto-added ones), so the
        merge assertion targets the count invariants on every feature
        and E1's corridor being present with its existing_count."""
        body = _gallery(api_base, include=["map_lines"])
        features = body["map_lines"]["features"]
        assert features
        for f in features:
            props = f["properties"]
            assert (
                props["total_count"]
                == props["proposal_count"] + props["existing_count"]
            )
            assert len(props["proposal_ids"]) == props["proposal_count"]
            assert len(props["existing_route_ids"]) == props["existing_count"]
        e1_features = [
            f
            for f in features
            if existing_routes[0] in f["properties"]["existing_route_ids"]
        ]
        assert len(e1_features) == 1
        assert e1_features[0]["properties"]["existing_count"] >= 1
        # Existing-only corridors carry no margin.
        fr = [
            f
            for f in features
            if existing_routes[1] in f["properties"]["existing_route_ids"]
        ]
        assert fr and fr[0]["properties"]["avg_margin_eur_per_train_km"] is None

    def test_map_stop_counts_triple(self, api_base, existing_routes, published):
        body = _gallery(api_base, include=["map_stop_counts"])
        rows = {r["stop_id"]: r for r in body["map_stop_counts"]}
        for row in rows.values():
            assert row["n"] == row["n_proposals"] + row["n_existing"]
        berlin = rows["osm:n3856100103"]
        assert berlin["n_proposals"] >= 1 and berlin["n_existing"] >= 1

    def test_map_country_counts_triple(self, api_base, existing_routes, published):
        """n == n_proposals + n_existing everywhere, and both sources
        contribute somewhere. Doesn't assert FR's n_proposals is exactly
        0 — other tests in the full suite run may have published
        proposals through France independently of this fixture; the
        merge invariant (the sum) is what step 6b actually guarantees,
        not the absence of unrelated test data."""
        body = _gallery(api_base, include=["map_country_counts"])
        props = {
            f["properties"]["country"]: f["properties"]
            for f in body["map_country_counts"]["features"]
        }
        for entry in props.values():
            assert entry["n"] == entry["n_proposals"] + entry["n_existing"]
        assert props["DE"]["n_existing"] >= 1 and props["DE"]["n_proposals"] >= 1
        assert props["FR"]["n_existing"] >= 1


# =============================================================================
# trip_windows
# =============================================================================


class TestTripWindows:
    def _departure_window(self, computed, stop_id: str, pad_min: int = 5):
        trip = computed["route"]["trip_pairs"][0]["outbound"]
        stops = stop_times(trip)
        stop = next(s for s in stops if s["stop_id"] == stop_id)
        dep = (
            stop["departure_time_min"]
            if stop["departure_time_min"] is not None
            else stop["arrival_time_min"]
        )
        lo_h, lo_m = divmod(max(dep - pad_min, 0), 60)
        hi_h, hi_m = divmod(dep + pad_min, 60)
        return f"{lo_h:02d}:{lo_m:02d}", f"{hi_h:02d}:{hi_m:02d}"

    def test_matching_window(self, api_base, published, computed):
        frm, to = self._departure_window(computed, "osm:n3856100103")
        hit = _gallery(
            api_base,
            filter={
                "trip_windows": [
                    {"stop_id": "osm:n3856100103", "departure": {"from": frm, "to": to}}
                ]
            },
        )
        assert published["proposal_id"] in _proposal_ids(hit)

    def test_non_matching_window(self, api_base, published):
        miss = _gallery(
            api_base,
            filter={
                "trip_windows": [
                    {
                        "stop_id": "osm:n3856100103",
                        "departure": {"from": "03:00", "to": "03:01"},
                    }
                ]
            },
        )
        assert published["proposal_id"] not in _proposal_ids(miss)


# =============================================================================
# bbox
# =============================================================================


class TestBbox:
    def test_bbox_intersecting_route(self, api_base, published):
        # Loosely covers the DACH region — the Berlin-Wien corridor sits inside.
        hit = _gallery(api_base, filter={"bbox": [8.0, 45.0, 20.0, 55.0]})
        assert published["proposal_id"] in _proposal_ids(hit)

    def test_bbox_not_intersecting_route(self, api_base, published):
        # Somewhere over the South Atlantic — no proposal route reaches here.
        miss = _gallery(api_base, filter={"bbox": [-40.0, -40.0, -30.0, -30.0]})
        assert published["proposal_id"] not in _proposal_ids(miss)


# =============================================================================
# Sort + windowed total
# =============================================================================


class TestSortAndPagination:
    def test_sort_by_total_distance_km(self, api_base):
        body = _gallery(api_base, sort=[{"by": "total_distance_km", "dir": "asc"}])
        values = [p["total_distance_km"] for p in body["summaries"]["proposals"]]
        assert values == sorted(values)

    def test_sort_rejects_unknown_column(self, api_base):
        resp = requests.post(
            f"{api_base}{PROPOSALS_URL}",
            json={"sort": [{"by": "not_a_column"}]},
            timeout=15,
        )
        assert resp.status_code == 400

    def test_windowed_total_matches_filtered_count_not_page_size(
        self, api_base, published
    ):
        body = _gallery(
            api_base, filter={"user_ids": [published["user_id"]]}, limit=1, offset=0
        )
        assert len(body["summaries"]["proposals"]) <= 1
        assert body["summaries"]["total"] >= 1


# =============================================================================
# include — sectioned response, only requested sections computed
# =============================================================================


class TestIncludeSections:
    def test_default_include_is_summaries_only(self, api_base):
        body = _gallery(api_base)
        assert set(body) == {"summaries"}

    def test_map_lines_geojson(self, api_base, published):
        # published's request under default auto_stop_addition ("add")
        # commonly inserts intermediate stops between the two named
        # endpoints, so the corridor is N literal stop-pair segments, not
        # necessarily one — map_lines groups by literal segment, not by
        # "logical journey". Assert every segment the proposal appears on
        # is well-formed, not that there's exactly one.
        body = _gallery(
            api_base,
            filter={"proposal_ids": [published["proposal_id"]]},
            include=["map_lines"],
        )
        assert set(body) == {"map_lines"}
        assert body["map_lines"]["type"] == "FeatureCollection"
        # Filtering to this one proposal means every returned corridor is
        # one of its segments.
        features = body["map_lines"]["features"]
        assert len(features) >= 1
        for feature in features:
            assert feature["properties"]["proposal_count"] >= 1
            assert feature["geometry"]["type"] == "LineString"
            # Simplified for overview zoom, but still a drawable line.
            assert len(feature["geometry"]["coordinates"]) >= 2

    def test_map_lines_omits_contributing_id_lists(self, api_base, published):
        """The id arrays were removed deliberately: their combined length
        is the number of distinct (proposal, corridor) pairs, the one term
        in this section unbounded in proposal count. Pinned as a test
        because re-adding them would silently reintroduce that."""
        body = _gallery(
            api_base,
            filter={"proposal_ids": [published["proposal_id"]]},
            include=["map_lines"],
        )
        for feature in body["map_lines"]["features"]:
            assert "proposal_ids" not in feature["properties"]
            assert "existing_route_ids" not in feature["properties"]

    def test_map_lines_thickness_reflects_shared_corridor(
        self, api_base, script_headers, published
    ):
        """A second proposal on the exact same corridor (identical stop
        list) should land on the SAME map_lines feature(s) as `published`
        rather than adding its own, with proposal_count bumped — the whole
        point of aggregating by corridor rather than by proposal.
        Identical stop lists under the same default auto_stop_addition
        behaviour insert the same intermediate stops, so every literal
        segment is shared; with the filter restricted to exactly these two
        proposals, EVERY returned corridor must therefore carry both.

        Both sides use the SAME composition. An earlier version varied it,
        which quietly made the test depend on two compositions producing an
        identical auto-added stop list: the "add" budget is a share of
        technical trip time, so a faster or slower consist can admit a
        different number of marginal candidates and split the corridor into
        different segments. That is correct behaviour and nothing to do with
        corridor aggregation, which is what this test is about."""
        second = publish(
            api_base,
            compute(api_base, _STOPS, _COMPOSITION)["request"],
            name="Berlin \u2013 Wien (gallery test, second proposal)",
            headers=script_headers,
        )
        body = _gallery(
            api_base,
            filter={"proposal_ids": [published["proposal_id"], second["proposal_id"]]},
            include=["map_lines"],
        )
        features = body["map_lines"]["features"]
        assert len(features) >= 1
        for feature in features:
            assert feature["properties"]["proposal_count"] >= 2

    def test_map_stop_counts(self, api_base, published):
        body = _gallery(
            api_base,
            filter={"user_ids": [published["user_id"]]},
            include=["map_stop_counts"],
        )
        stop_ids = {row["stop_id"] for row in body["map_stop_counts"]}
        assert "osm:n3856100103" in stop_ids
        berlin = next(
            r for r in body["map_stop_counts"] if r["stop_id"] == "osm:n3856100103"
        )
        assert berlin["lat"] is not None and berlin["lon"] is not None
        assert berlin["n"] >= 1

    def test_map_country_counts(self, api_base, published):
        body = _gallery(
            api_base,
            filter={"user_ids": [published["user_id"]]},
            include=["map_country_counts"],
        )
        assert body["map_country_counts"]["type"] == "FeatureCollection"
        by_country = {
            f["properties"]["country"]: f
            for f in body["map_country_counts"]["features"]
        }
        assert by_country["DE"]["properties"]["n"] >= 1
        assert by_country["AT"]["properties"]["n"] >= 1
        # both DE and AT have a seeded Natural Earth border polygon
        assert by_country["DE"]["geometry"]["type"] in ("Polygon", "MultiPolygon")
        assert by_country["AT"]["geometry"]["type"] in ("Polygon", "MultiPolygon")

    def test_map_routes_matches_the_listed_rows(self, api_base, published):
        """map_routes is the ONE map section that honours limit/offset,
        because it exists to draw the route behind a card the user can
        see. It must therefore cover exactly the rows summaries returned,
        in the same order — otherwise the map draws routes for cards that
        are not on screen."""
        body = _gallery(
            api_base,
            sort=[{"by": "total_distance_km", "dir": "desc"}],
            limit=5,
            offset=0,
            include=["summaries", "map_routes"],
        )
        assert set(body) == {"summaries", "map_routes"}
        assert body["map_routes"]["type"] == "FeatureCollection"
        assert _row_keys(body["summaries"]["proposals"]) == _route_keys(
            body["map_routes"]["features"]
        )

    def test_map_routes_follows_the_window(self, api_base, published):
        """A different page must yield a different, equally-aligned set —
        the guard against map_routes quietly ignoring offset and always
        returning the first page."""
        common = dict(
            sort=[{"by": "total_distance_km", "dir": "desc"}],
            limit=3,
            include=["summaries", "map_routes"],
        )
        first = _gallery(api_base, offset=0, **common)
        second = _gallery(api_base, offset=3, **common)

        for body in (first, second):
            assert _row_keys(body["summaries"]["proposals"]) == _route_keys(
                body["map_routes"]["features"]
            )
        # Only meaningful once there are enough rows for a second page.
        if second["summaries"]["proposals"]:
            assert _route_keys(first["map_routes"]["features"]) != _route_keys(
                second["map_routes"]["features"]
            )

    def test_map_routes_emits_null_geometry_rather_than_dropping_a_row(
        self, api_base, existing_routes
    ):
        """ONTD routes whose routing failed have geom_simplified NULL. The
        feature is still emitted so "no geometry" stays distinguishable
        from "not on this page" — which is what keeps the row-for-row
        alignment above true."""
        body = _gallery(
            api_base,
            filter={"sources": ["existing"]},
            limit=50,
            include=["summaries", "map_routes"],
        )
        features = body["map_routes"]["features"]
        assert _row_keys(body["summaries"]["proposals"]) == _route_keys(features)
        for feature in features:
            assert feature["geometry"] is None or feature["geometry"]["type"] in (
                "LineString",
                "MultiLineString",
            )

    def test_multiple_sections_together(self, api_base):
        body = _gallery(api_base, include=["summaries", "map_country_counts"])
        assert set(body) == {"summaries", "map_country_counts"}

    def test_unknown_include_section_rejected(self, api_base):
        resp = requests.post(
            f"{api_base}{PROPOSALS_URL}",
            json={"include": ["bogus_section"]},
            timeout=15,
        )
        assert resp.status_code == 400


# =============================================================================
# Engagement counts — live-joined from proposals.likes / proposals.comments,
# neither one a summary column
# =============================================================================


class TestEngagementCounts:
    def test_likes_count_appears_in_summary_and_is_filterable(
        self, api_base, script_headers, published
    ):
        resp = requests.post(
            f"{api_base}{like_url(published['proposal_id'])}",
            timeout=10,
            headers=script_headers,
        )
        assert resp.status_code == 200

        assert _summary_row(api_base, published)["likes_count"] >= 1

        hit = _gallery(api_base, filter={"likes_count": {"min": 1}})
        assert published["proposal_id"] in _proposal_ids(hit)

        miss = _gallery(api_base, filter={"likes_count": {"min": 999}})
        assert published["proposal_id"] not in _proposal_ids(miss)

    def test_sort_by_likes_count(self, api_base):
        """likes_count is a proposal-only concept — existing rows omit
        the key entirely (WP10 step 6b's reduced shape), so this sorts
        within sources=["proposal"] rather than the default union."""
        body = _gallery(
            api_base,
            filter={"sources": ["proposal"]},
            sort=[{"by": "likes_count", "dir": "desc"}],
        )
        values = [p["likes_count"] for p in body["summaries"]["proposals"]]
        assert values == sorted(values, reverse=True)

    def test_comments_count_appears_in_summary_and_is_filterable(
        self, api_base, script_headers, published
    ):
        """WP11: the gallery carries the comment count so a card can show
        it without one engagements call per row. Deleted comments are
        excluded, matching GET /api/proposal/<id>/engagements."""
        pid = published["proposal_id"]
        posted = [
            requests.post(
                f"{api_base}{comment_url(pid)}",
                json={"body": body},
                timeout=10,
                headers=script_headers,
            )
            for body in ("First thought.", "Second thought.")
        ]
        assert [r.status_code for r in posted] == [201, 201]

        row = _summary_row(api_base, published)
        assert row["comments_count"] == 2

        hit = _gallery(api_base, filter={"comments_count": {"min": 2}})
        assert pid in _proposal_ids(hit)

        miss = _gallery(api_base, filter={"comments_count": {"min": 999}})
        assert pid not in _proposal_ids(miss)

        resp = requests.delete(
            f"{api_base}{comment_url(pid, posted[0].json()['comment_id'])}",
            timeout=10,
            headers=script_headers,
        )
        assert resp.status_code == 204
        assert _summary_row(api_base, published)["comments_count"] == 1

    def test_sort_by_comments_count(self, api_base):
        """Proposal-only, same as likes_count — sorted within
        sources=["proposal"] rather than the default union."""
        body = _gallery(
            api_base,
            filter={"sources": ["proposal"]},
            sort=[{"by": "comments_count", "dir": "desc"}],
        )
        values = [p["comments_count"] for p in body["summaries"]["proposals"]]
        assert values == sorted(values, reverse=True)

    def test_existing_rows_omit_both_counts(self, api_base, existing_routes):
        """Engagement is a proposal-only concept (locked decision 23) —
        an existing route carries neither key."""
        body = _gallery(api_base, filter={"sources": ["existing"]})
        rows = body["summaries"]["proposals"]
        assert rows, "expected at least one existing row"
        for row in rows:
            assert "likes_count" not in row
            assert "comments_count" not in row
